"""Intent recognition and task classification for REPL."""
from __future__ import annotations

import re
from typing import Iterable, Sequence


GREETING_EXACT = frozenset({
    "hello", "hi", "hey", "hola", "yo", "sup", "what's up",
    "good morning", "good evening", "good afternoon",
    "你好", "您好", "嗨", "早上好", "上午好", "下午好", "晚上好", "早", "晚安",
    "咋样", "最近怎样", "再见", "拜拜", "辛苦了",
    "thanks", "thank you", "thx", "ty", "谢谢", "多谢", "感谢",
    "好的", "ok", "okay", "got it", "明白", "了解", "知道了",
})

GREETING_PREFIXES = (
    "hello", "hi", "hey", "你好", "您好", "嗨",
    "thanks", "thank you", "谢谢", "谢谢你", "多谢", "感谢", "感谢你",
)

CASUAL_SHORT = frozenset({
    "hi", "ok", "yo", "早", "嗨", "嗯", "哦", "好",
})

NON_CODING_TOPICS = (
    "天气", "weather", "新闻", "news", "电影", "movie", "音乐", "music",
    "游戏", "game", "运动", "sport", "菜谱", "recipe", "美食", "food",
    "旅游", "travel", "股票", "stock",
    "笑话", "joke", "聊天", "闲聊", "心情", "mood",
    "推荐", "recommend", "评价", "review",
)

CODING_KEYWORDS = (
    "file", "code", "function", "class", "method", "variable", "import",
    "module", "package", "test", "debug", "error", "exception", "stack",
    "git", "commit", "branch", "merge", "deploy", "build", "compile",
    "api", "database", "query", "server", "client", "config", "install",
    "refactor", "optimize", "optimization", "improve", "repo", "project",
    "文件", "代码", "函数", "类", "方法", "变量", "模块", "包",
    "配置", "安装", "依赖", "版本", "功能", "接口", "数据库",
    "服务", "部署", "编译", "运行", "执行", "命令", "脚本",
    "项目", "工程", "目录", "路径", "日志", "调试", "报错",
    "修改", "编辑", "搜索", "查找", "分析", "修复", "实现", "创建",
    "优化", "改进",
)

DEV_KEYWORDS = (
    "增加", "添加", "完成", "实现", "开发", "修改", "改", "新增",
    "优化", "改进",
    "add", "implement", "create", "support", "feature", "optimize", "improve",
    "需求", "功能",
)

CHAT_PHRASES = {
    "what can you do", "你能做什么", "你会什么",
    "你是谁", "who are you", "你叫什么", "你的名字",
    "介绍一下你自己", "introduce yourself",
    "help", "帮助", "怎么用", "how to use",
}


def _starts_with_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        if text == phrase:
            return True
        for sep in (" ", ",", "，", "!", "！", ".", "。"):
            if text.startswith(f"{phrase}{sep}"):
                return True
    return False


def _has_cjk(text: str) -> bool:
    return any("一" <= c <= "鿿" for c in text)


def greeting_response(user_input: str) -> str:
    """Return a deterministic greeting without invoking the agent loop."""
    if _has_cjk(user_input):
        return "你好！我是 CodePilot，你的 AI 编程助手。有什么代码或项目上的问题需要帮忙吗？"
    return "Hello! I'm CodePilot, your AI coding assistant. Got any code or project questions I can help with?"


def chat_response(user_input: str) -> str:
    """Return a deterministic short response for help/who-are-you chat prompts."""
    s = user_input.strip().lower()

    if _has_cjk(user_input):
        if any(kw in s for kw in ("帮助", "怎么用", "你能做什么", "你会什么")) or s == "help":
            return (
                "我是 CodePilot，一个终端里的 AI 编程助手。你可以让我：\n"
                "- 分析当前项目：`分析当前项目`\n"
                "- 查找代码：`查找登录逻辑在哪里`\n"
                "- 修改文件：`修复这个报错`\n"
                "- 运行测试：`运行测试并分析失败原因`\n"
                "- 制定计划：`为这个功能制定实现方案`"
            )
        if any(kw in s for kw in ("你是谁", "你叫什么", "介绍一下", "介绍你自己")):
            return "我是 CodePilot，一个运行在终端中的 AI 编程助手，可以帮你阅读、分析、修改和测试代码。"
        return "我在。你可以直接描述代码或项目上的问题，我会帮你处理。"

    if any(kw in s for kw in ("help", "how to use", "what can you do", "what do you do")):
        return (
            "I'm CodePilot, an AI coding assistant in your terminal. You can ask me to:\n"
            "- analyze the current project\n"
            "- search code\n"
            "- edit files\n"
            "- run tests\n"
            "- explain errors\n"
            "- draft implementation plans"
        )
    if "who are you" in s or "introduce yourself" in s:
        return "I'm CodePilot, an AI coding assistant for reading, analyzing, editing, and testing code."

    return "I'm here. Tell me what coding or project task you'd like help with."


def classify_intent(user_input: str) -> str:
    """Classify user intent into: greeting, chat, coding."""
    s = user_input.strip()
    s_lower = s.lower()

    if len(s) <= 1:
        return "greeting"

    normalized = s_lower.rstrip("!！？.。?？，, 、~")

    if normalized in CHAT_PHRASES:
        return "chat"

    if normalized in GREETING_EXACT:
        return "greeting"
    if len(s) <= 3 and normalized in CASUAL_SHORT:
        return "greeting"

    has_coding = any(kw in s_lower for kw in CODING_KEYWORDS)
    has_non_coding = any(kw in s_lower for kw in NON_CODING_TOPICS)
    has_dev_intent = any(kw in s_lower for kw in DEV_KEYWORDS)

    if (
        not has_coding
        and not has_dev_intent
        and len(normalized) <= 80
        and _starts_with_phrase(normalized, GREETING_PREFIXES)
    ):
        return "greeting"

    question_prefixes = ("什么是", "what is ", "what's ", "explain ", "解释",
                         "怎么", "如何", "how ", "为什么", "why ")
    is_knowledge_q = any(s_lower.startswith(m) for m in question_prefixes)
    project_refs = ("这个", "当前", "项目", "project", "repo", "目录", "directory",
                    "文件", "file", "代码", "code", "配置", "config")
    has_project_ref = any(ref in s_lower for ref in project_refs)

    if is_knowledge_q and not has_project_ref and not has_dev_intent:
        return "chat"

    if has_coding or has_dev_intent:
        return "coding"

    if has_non_coding:
        return "chat"

    question_suffixes = ("区别", "difference", "比较", "compare", "对比")
    is_question = (
        any(s_lower.startswith(m) for m in question_prefixes)
        or any(s_lower.endswith(m) for m in question_suffixes)
        or s_lower.endswith(("?", "？"))
    )
    if is_question and not has_coding:
        return "chat"

    return "coding"


def classify_task(user_input: str) -> str:
    """Classify coding intent into specific task types."""
    input_stripped = user_input.strip().lower()
    intent = classify_intent(user_input)

    if intent != "coding":
        return "general_question"

    search_intent = any(kw in input_stripped for kw in [
        "search", "find", "where", "locate", "查找", "搜索", "grep", "在哪里", "位置",
    ])
    read_intent = any(kw in input_stripped for kw in [
        "read", "show", "view", "读取", "查看", "看看",
    ])
    edit_intent = any(kw in input_stripped for kw in ["edit", "修改", "改", "fix", "bug", "修复"])
    apply_optimization_intent = any(kw in input_stripped for kw in [
        "进行优化", "执行优化", "开始优化", "直接优化", "优化当前", "优化这个",
        "进行改进", "执行改进", "改进当前", "apply optimization", "optimize this",
        "make the optimization", "improve this",
    ])
    write_intent = any(kw in input_stripped for kw in [
        "write", "create", "新建", "创建", "implement", "实现",
        "增加", "添加", "完成", "开发", "支持", "加入", "新增",
    ])
    readonly_intent = any(kw in input_stripped for kw in [
        "do not edit", "don't edit", "do not modify", "don't modify",
        "read-only", "readonly", "不要修改", "不修改", "只读",
    ])
    test_intent = any(kw in input_stripped for kw in [
        "test", "tests", "testing", "pytest", "ruff", "lint", "verify", "verification",
        "run the app", "rerun", "re-run", "evaluation report", "test report",
        "测试", "单测", "验证", "重新运行", "运行当前程序", "测试结果", "评估文档",
    ])
    analysis_intent = any(kw in input_stripped for kw in [
        "analyze", "analysis", "assess", "evaluate", "review", "explain",
        "分析", "评估", "评价", "审查", "解释", "总结", "梳理",
        "怎么实现", "如何实现", "怎么工作", "how does",
    ])
    test_evaluation_intent = test_intent and (
        analysis_intent
        or any(kw in input_stripped for kw in [
            "report", "结果", "文档", "效果", "评估", "evaluate", "evaluation",
        ])
    )

    if readonly_intent and analysis_intent:
        return "project_analysis"
    if test_evaluation_intent:
        return "test_evaluation"
    if (search_intent or read_intent) and (readonly_intent or not (edit_intent or write_intent)):
        return "code_search"
    if apply_optimization_intent:
        return "file_edit"
    if edit_intent:
        return "file_edit"
    if analysis_intent:
        return "project_analysis"
    if write_intent:
        return "file_write"
    if search_intent:
        return "code_search"
    if any(kw in input_stripped for kw in ["run", "execute", "执行", "test", "测试"]):
        return "command_run"
    return "file_edit"


def is_greeting(user_input: str) -> bool:
    """Check if input is a greeting."""
    s = user_input.strip()
    if len(s) <= 1:
        return True
    normalized = s.lower().rstrip("!！？.。?？，, 、~")
    if normalized in CHAT_PHRASES:
        return False
    has_coding = any(kw in normalized for kw in CODING_KEYWORDS)
    has_dev_intent = any(kw in normalized for kw in DEV_KEYWORDS)
    return (
        normalized in GREETING_EXACT
        or (len(s) <= 3 and normalized in CASUAL_SHORT)
        or (
            not has_coding
            and not has_dev_intent
            and len(normalized) <= 80
            and _starts_with_phrase(normalized, GREETING_PREFIXES)
        )
    )


def is_dev_intent(user_input: str) -> bool:
    """Check if input has development intent."""
    s_lower = user_input.lower()
    return any(kw in s_lower for kw in DEV_KEYWORDS)


# --- Context-aware intent helpers --------------------------------------------

# Markers that suggest the previous AI message is asking the user to pick or
# confirm a follow-up step. Used both for numeric replies and for short
# affirmative replies that would otherwise be misclassified as greetings.
FOLLOWUP_PROMPT_MARKERS: tuple[str, ...] = (
    "需要我执行其中哪一个",
    "请选择",
    "选哪一个",
    "哪一个",
    "任选",
    "建议操作",
    "建议下一步",
    "下一步",
    "是否继续",
    "是否需要",
    "要不要",
    "需要我",
    "可以继续吗",
    "继续吗",
    "which one",
    "choose one",
    "select one",
    "should i continue",
    "shall i continue",
    "do you want me",
    "would you like",
    "next step",
    "?",
    "？",
)

NUMBERED_OPTION_RE = re.compile(r"(?m)^\s*(?:\[\s*)?([1-9]\d*)(?:\s*\])?[\s.、)]+\S+")
CHOICE_REPLY_RE = re.compile(r"^\s*(?:选|选择|第)?\s*([1-9]\d*)\s*(?:个|项|号)?\s*[.。]?\s*$")

AFFIRMATIVE_REPLIES = frozenset({
    "好", "好的", "可以", "行", "嗯", "嗯嗯", "对", "是", "是的",
    "继续", "继续吧", "请继续", "go", "go on", "go ahead",
    "yes", "y", "yep", "yeah", "sure", "ok", "okay", "k",
    "确认", "确定", "同意", "没问题",
    "proceed", "continue", "fine", "alright",
})

NEGATIVE_REPLIES = frozenset({
    "不", "不要", "别", "停", "停下", "算了", "取消", "no", "nope", "n", "stop",
    "cancel", "skip", "abort",
})


def _previous_ai_text(messages: Sequence[object]) -> str:
    """Return the last AIMessage text content (or empty)."""
    for msg in reversed(messages):
        cls_name = type(msg).__name__
        if cls_name == "AIMessage":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                return content
    return ""


def previous_ai_awaits_followup(messages: Sequence[object]) -> bool:
    """True when the latest AI message looks like it's asking for direction."""
    text = _previous_ai_text(messages)
    if not text:
        return False
    lower = text.lower()
    return any(marker in lower for marker in FOLLOWUP_PROMPT_MARKERS)


def expand_choice_reply(user_input: str, messages: Sequence[object]) -> str:
    """Expand a short reply (numeric or affirmative) when the prior AI asked a question.

    - Numeric `2` after a numbered list -> explicit instruction to execute option 2.
    - Affirmative `好的`/`ok` after a yes/no question -> "继续执行你刚才提议的下一步".
    - Negative `不要`/`no` -> "请不要执行刚才提议的方案，等待我的下一步指令".

    If the prior AI message does not look like a follow-up question, the input
    is returned unchanged.
    """
    if not user_input or not user_input.strip():
        return user_input

    previous_ai = _previous_ai_text(messages)
    if not previous_ai:
        return user_input

    lower_prev = previous_ai.lower()
    has_followup_prompt = any(marker in lower_prev for marker in FOLLOWUP_PROMPT_MARKERS)

    match = CHOICE_REPLY_RE.match(user_input)
    if match:
        option_numbers = set(NUMBERED_OPTION_RE.findall(previous_ai))
        selected = match.group(1)
        if has_followup_prompt and selected in option_numbers and len(option_numbers) >= 2:
            return (
                f"用户选择了上一条建议操作中的第 {selected} 项。\n"
                "请根据上一条消息中的编号选项执行该项；如果该项需要工具调用，请继续调用相应工具。"
            )
        return user_input

    if not has_followup_prompt:
        return user_input

    normalized = user_input.strip().lower().rstrip("!！？.。?？，, 、~")

    if normalized in AFFIRMATIVE_REPLIES:
        return (
            "用户确认继续执行你在上一条消息中提议的方案/下一步。"
            "请直接按你刚才的建议继续，必要时调用相应工具。"
        )
    if normalized in NEGATIVE_REPLIES:
        return (
            "用户拒绝了你在上一条消息中提议的方案。"
            "请不要执行该方案，简短确认并等待用户给出新的指示。"
        )
    return user_input


# Backwards-compat alias used by tests and older call sites.
expand_numbered_choice_reply = expand_choice_reply


def classify_intent_with_context(
    user_input: str,
    messages: Sequence[object] | None = None,
) -> str:
    """Context-aware intent classification.

    Falls back to keyword-based `classify_intent` when there is no prior agent
    turn. When the previous AI message looks like a follow-up question, short
    affirmative or numeric replies are routed to `coding` so they don't trigger
    the canned greeting/chat responses.
    """
    base = classify_intent(user_input)
    if not messages or not previous_ai_awaits_followup(messages):
        return base

    s = user_input.strip()
    if not s:
        return base

    normalized = s.lower().rstrip("!！？.。?？，, 、~")
    if (
        normalized in AFFIRMATIVE_REPLIES
        or normalized in NEGATIVE_REPLIES
        or CHOICE_REPLY_RE.match(s)
    ):
        return "coding"

    # Brief replies (<=8 chars / 6 chars CJK) right after a follow-up prompt
    # are most likely the user steering the agent, not idle chit-chat.
    if base in {"greeting", "chat"} and len(normalized) <= 12:
        return "coding"

    return base


# --- Post-task suggestion -----------------------------------------------------

def build_post_task_prompt(
    task_type: str,
    outcome: str,
    *,
    use_chinese: bool = True,
) -> str:
    """Build a short menu of suggested next steps to show after a task completes.

    Designed to give the user concrete handles instead of an empty prompt — the
    options are surfaced as a numbered list so the user can reply `1`/`2`/`3`
    and `expand_choice_reply` will route the choice back into the agent.
    """
    options = _post_task_options(task_type, outcome, use_chinese=use_chinese)
    if not options:
        return ""

    if use_chinese:
        header = "下一步可以做："
        tail = "回复编号执行对应操作，或直接描述你想做的事。"
    else:
        header = "Suggested next steps:"
        tail = "Reply with a number to run that step, or describe what you want next."

    lines = [header]
    for idx, opt in enumerate(options, 1):
        lines.append(f"{idx} {opt}")
    lines.append("")
    lines.append(tail)
    return "\n".join(lines)


def _post_task_options(task_type: str, outcome: str, *, use_chinese: bool) -> list[str]:
    cn = use_chinese
    if outcome == "error":
        return [
            "查看错误详情并重试" if cn else "Inspect the error and retry",
            "切换到 plan 模式重新分析" if cn else "Switch to plan mode and re-analyse",
            "结束当前任务" if cn else "End the current task",
        ]
    if outcome in {"partial", "timeout"}:
        return [
            "继续完成剩余步骤" if cn else "Continue the remaining steps",
            "总结当前进展并提交已完成部分" if cn else "Summarise progress and commit what's done",
            "切换为 plan-execute 重新规划" if cn else "Replan with plan-execute",
        ]

    if task_type in {"file_edit", "file_write"}:
        return [
            "运行测试 / lint 验证改动" if cn else "Run tests / lint to verify the changes",
            "查看本次改动的 diff" if cn else "Show the diff of this change",
            "提交并推送（git commit & push）" if cn else "Commit and push (git commit & push)",
        ]
    if task_type == "code_search":
        return [
            "对找到的代码进行修改" if cn else "Edit the matched code",
            "查看相关文件的完整内容" if cn else "Read the full files we matched",
            "结束当前任务" if cn else "End the current task",
        ]
    if task_type == "project_analysis":
        return [
            "根据分析给出优化方案" if cn else "Draft an improvement plan from the analysis",
            "选定一个点开始优化（plan-execute）" if cn else "Pick one item and start with plan-execute",
            "结束当前任务" if cn else "End the current task",
        ]
    if task_type == "test_evaluation":
        return [
            "针对失败的测试逐个修复" if cn else "Fix the failing tests one by one",
            "生成评估报告并提交" if cn else "Write an evaluation report and commit",
            "结束当前任务" if cn else "End the current task",
        ]
    if task_type == "command_run":
        return [
            "查看完整输出并继续排查" if cn else "Inspect the full output and keep digging",
            "调整参数重试" if cn else "Adjust parameters and retry",
            "结束当前任务" if cn else "End the current task",
        ]

    return [
        "继续后续工作" if cn else "Keep going on the next step",
        "总结当前结论" if cn else "Summarise current findings",
        "结束当前任务" if cn else "End the current task",
    ]
