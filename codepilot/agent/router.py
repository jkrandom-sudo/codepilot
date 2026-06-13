from __future__ import annotations


AUTO_AGENT = "auto"

READONLY_MARKERS = (
    "do not edit", "don't edit", "do not modify", "don't modify", "read-only", "readonly",
    "不要修改", "不修改", "只读", "仅分析", "只分析",
)

COMPLEX_MARKERS = (
    "架构", "重构", "多文件", "多模块", "全局", "完整", "全面", "生产级", "持续",
    "多轮", "多维度", "端到端", "评估", "优化方案", "根据方案", "测试并",
    "提交", "推送", "langsmith", "mcp", "skill", "claude code", "open code",
    "architecture", "refactor", "multi-file", "end-to-end", "production",
    "evaluate", "evaluation", "optimize", "plan", "test and", "commit", "push",
)

ACTION_MARKERS = (
    "分析", "评估", "方案", "优化", "改进", "实现", "添加", "支持", "测试", "验证",
    "提交", "推送", "修复", "运行",
    "analyze", "evaluate", "plan", "optimize", "improve", "implement", "add",
    "support", "test", "verify", "commit", "push", "fix", "run",
)

SEQUENCE_MARKERS = ("并", "然后", "再", "同时", "以及", "根据", "after", "then", "and")


def is_auto_agent(agent_name: str | None) -> bool:
    return not agent_name or agent_name == AUTO_AGENT


def select_agent_for_task(user_input: str, task_type: str, requested_agent: str | None = AUTO_AGENT) -> str:
    """Choose the primary agent for a user task.

    Simple tasks stay on the default ReAct build agent. Complex tasks use the
    Plan-and-Execute primary agent, whose execution loop is still ReAct. Explicit
    read-only plan requests stay read-only.
    """
    requested = requested_agent or AUTO_AGENT
    if requested == "plan":
        return "plan"
    if requested == "plan-execute":
        return "plan-execute"

    text = user_input.strip().lower()
    if any(marker in text for marker in READONLY_MARKERS):
        return "plan"

    if task_type in {"code_search", "general_question", "command_run"} and not _looks_complex(text):
        return "build"

    if task_type in {"test_evaluation"}:
        return "plan-execute"

    if task_type in {"file_edit", "file_write", "project_analysis"} and _looks_complex(text):
        return "plan-execute"

    return "build"


def _looks_complex(text: str) -> bool:
    marker_hits = sum(1 for marker in COMPLEX_MARKERS if marker in text)
    action_hits = sum(1 for marker in ACTION_MARKERS if marker in text)
    sequence_hits = sum(1 for marker in SEQUENCE_MARKERS if marker in text)
    long_request = len(text) >= 80
    return marker_hits >= 1 or action_hits >= 3 or (action_hits >= 2 and sequence_hits >= 1) or long_request
