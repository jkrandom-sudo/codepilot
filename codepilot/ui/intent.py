"""Intent recognition and task classification for REPL."""
from __future__ import annotations


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
