import pytest

from codepilot.ui.intent import (
    build_post_task_prompt,
    chat_response,
    classify_intent,
    classify_intent_with_context,
    classify_task,
    expand_choice_reply,
    greeting_response,
    is_greeting,
    previous_ai_awaits_followup,
)
from codepilot.agent.router import select_agent_for_task


@pytest.mark.parametrize("text", [
    "hello",
    "hello there",
    "你好！",
    "您好",
    "thanks, that's helpful!",
    "谢谢你，辛苦了",
])
def test_greetings_do_not_enter_coding_flow(text):
    assert classify_intent(text) == "greeting"
    assert classify_task(text) == "general_question"
    assert is_greeting(text) is True


@pytest.mark.parametrize("text", [
    "hello, analyze current project",
    "你好，分析当前项目结构",
    "thanks, now fix the tests",
])
def test_greeting_prefix_with_dev_intent_stays_coding(text):
    assert classify_intent(text) == "coding"
    assert is_greeting(text) is False


def test_project_analysis_request_is_coding():
    assert classify_intent("分析当前项目结构并给出优化方案") == "coding"
    assert classify_task("分析当前项目结构并给出优化方案") == "project_analysis"


@pytest.mark.parametrize("text", [
    "重新运行当前程序，进行测试，给出测试结果评估文档",
    "运行 pytest 和 ruff 后评估当前项目效果",
    "rerun the app tests and produce an evaluation report",
])
def test_test_evaluation_requests_get_dedicated_task_type(text):
    assert classify_intent(text) == "coding"
    assert classify_task(text) == "test_evaluation"


@pytest.mark.parametrize("text", [
    "请总结当前项目结构、核心执行链路和最值得优化的一个点。不要修改文件。",
    "基于 docs/evaluation-report-20260607.md 评估当前项目效果，不要修改文件",
])
def test_readonly_analysis_request_stays_project_analysis(text):
    assert classify_intent(text) == "coding"
    assert classify_task(text) == "project_analysis"


def test_apply_optimization_request_routes_to_file_edit():
    text = "根据评估结果给出优化方案，并按照方案进行优化"

    assert classify_intent(text) == "coding"
    assert classify_task(text) == "file_edit"


@pytest.mark.parametrize("text", ["help", "帮助", "你是谁", "你能做什么"])
def test_help_and_identity_prompts_are_chat_not_greeting(text):
    assert classify_intent(text) == "chat"
    assert classify_task(text) == "general_question"
    assert is_greeting(text) is False


def test_readonly_search_request_is_code_search_even_if_it_mentions_edit():
    text = "find where API tokens are validated. Do not edit files."
    assert classify_intent(text) == "coding"
    assert classify_task(text) == "code_search"


def test_find_and_fix_request_stays_file_edit():
    text = "find the checkout bug and fix it"
    assert classify_task(text) == "file_edit"


def test_simple_search_uses_react_build_agent():
    text = "find where API tokens are validated"
    task_type = classify_task(text)

    assert select_agent_for_task(text, task_type, requested_agent="auto") == "build"


def test_complex_implementation_routes_to_plan_execute():
    text = "评估当前项目效果，给出优化方案，根据方案进行优化，运行测试并提交"
    task_type = classify_task(text)

    assert select_agent_for_task(text, task_type, requested_agent="auto") == "plan-execute"


def test_readonly_analysis_routes_to_plan_agent():
    text = "分析当前项目结构并给出方案，不要修改文件"
    task_type = classify_task(text)

    assert select_agent_for_task(text, task_type, requested_agent="auto") == "plan"


def test_greeting_response_matches_user_language():
    assert greeting_response("hello").startswith("Hello!")
    assert greeting_response("你好").startswith("你好！")


def test_chat_response_is_deterministic_for_help_and_identity():
    assert "CodePilot" in chat_response("help")
    assert "分析当前项目" in chat_response("你能做什么")
    assert "AI 编程助手" in chat_response("你是谁")


# --- Context-aware classification --------------------------------------------

class _FakeAI:
    """Lightweight stand-in for AIMessage so tests don't depend on langchain."""

    def __init__(self, content: str) -> None:
        self.content = content


# `classify_intent_with_context` checks the class name, so make the type look right.
_FakeAI.__name__ = "AIMessage"


class _FakeHuman:
    def __init__(self, content: str) -> None:
        self.content = content


_FakeHuman.__name__ = "HumanMessage"


def test_previous_ai_awaits_followup_detects_question_markers():
    assert previous_ai_awaits_followup([_FakeAI("是否需要我继续修复其他文件？")]) is True
    assert previous_ai_awaits_followup([_FakeAI("已完成所有修改。")]) is False
    assert previous_ai_awaits_followup([]) is False


@pytest.mark.parametrize("reply", ["好的", "好", "继续", "可以", "ok", "yes", "确定"])
def test_short_affirmative_after_followup_is_routed_to_coding(reply):
    history = [_FakeAI("我可以帮你运行 pytest 验证刚才的修改，是否继续？")]

    assert classify_intent_with_context(reply, history) == "coding"


def test_short_affirmative_without_context_still_uses_canned_branch():
    # The original bug: a bare "好的" with no follow-up question gets the
    # canned greeting/chat reply (or coding if it happens to hit a keyword);
    # what matters is that the classifier doesn't fabricate context.
    assert classify_intent_with_context("好的", []) in {"greeting", "chat"}
    assert classify_intent_with_context("ok", []) in {"greeting", "chat"}


@pytest.mark.parametrize("reply", ["不", "不要", "算了", "no", "cancel"])
def test_short_negative_after_followup_is_routed_to_coding(reply):
    history = [_FakeAI("是否需要我继续修复？")]

    assert classify_intent_with_context(reply, history) == "coding"


def test_short_affirmative_without_followup_keeps_canned_reply():
    history = [_FakeAI("已完成所有修改，输出已经显示在上面。")]
    # No question marker -> falls back to keyword-only classification.
    assert classify_intent_with_context("好的", history) in {"greeting", "chat"}


def test_expand_choice_reply_handles_affirmative_after_followup():
    history = [_FakeAI("是否需要我继续运行 ruff 检查？")]
    expanded = expand_choice_reply("好的", history)
    assert "用户确认继续" in expanded


def test_expand_choice_reply_handles_negative_after_followup():
    history = [_FakeAI("要不要我把这块逻辑迁移到独立模块？")]
    expanded = expand_choice_reply("不要", history)
    assert "拒绝" in expanded


def test_expand_choice_reply_passthrough_when_no_followup():
    history = [_FakeAI("已完成。")]
    assert expand_choice_reply("好的", history) == "好的"
    assert expand_choice_reply("hi", history) == "hi"


def test_expand_choice_reply_numeric_still_works():
    history = [_FakeAI(
        "建议操作（任选）：\n1 运行 pytest\n2 运行 ruff\n3 提交\n需要我执行其中哪一个？"
    )]
    expanded = expand_choice_reply("2", history)
    assert "第 2 项" in expanded


def test_brief_followup_reply_with_low_keyword_density_routes_to_coding():
    # User says "试试看" right after the agent asked a follow-up. Without context
    # this is filtered out as chat/no-op; with context it should reach the agent.
    history = [_FakeAI("我可以帮你接着把测试加上，要不要继续？")]
    assert classify_intent_with_context("试试看", history) == "coding"


# --- Post-task suggestions ----------------------------------------------------

def test_build_post_task_prompt_returns_numbered_options_for_file_edit():
    prompt = build_post_task_prompt("file_edit", "success", use_chinese=True)
    assert "下一步可以做" in prompt
    assert "1 " in prompt
    assert "2 " in prompt
    assert "3 " in prompt
    assert "回复编号" in prompt


def test_build_post_task_prompt_error_offers_retry_path():
    prompt = build_post_task_prompt("file_edit", "error", use_chinese=True)
    assert "错误" in prompt or "重试" in prompt


def test_build_post_task_prompt_english_when_requested():
    prompt = build_post_task_prompt("file_edit", "success", use_chinese=False)
    assert "Suggested next steps" in prompt
    assert "Reply with a number" in prompt


def test_post_task_prompt_round_trips_with_context_aware_classifier():
    """A follow-up menu plus a brief reply should route to coding, not greeting."""
    menu = build_post_task_prompt("file_edit", "success", use_chinese=True)
    history = [_FakeAI(menu)]

    assert previous_ai_awaits_followup(history) is True
    assert classify_intent_with_context("2", history) == "coding"
    assert classify_intent_with_context("好的", history) == "coding"
    assert "第 2 项" in expand_choice_reply("2", history)
