import pytest

from codepilot.ui.intent import (
    chat_response,
    classify_intent,
    classify_task,
    greeting_response,
    is_greeting,
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
