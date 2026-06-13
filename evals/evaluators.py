"""Custom evaluators for CodePilot agent evaluation.

Each evaluator returns a dict with 'key', 'score', and 'comment'.
"""
from __future__ import annotations

import re
from collections import Counter

from langchain_core.messages import AIMessage, ToolMessage


def tool_selection_accuracy(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    expected = set(reference_outputs.get("expected_tools", []))
    forbidden = set(reference_outputs.get("forbidden_tools", []))

    messages = outputs.get("messages", [])
    tools_used = set()
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tools_used.add(tc["name"])

    used_forbidden = tools_used & forbidden
    used_expected = tools_used & expected

    if used_forbidden:
        messages = outputs.get("messages", [])
        forbidden_blocked = 0
        forbidden_succeeded = 0
        for msg in messages:
            if isinstance(msg, ToolMessage):
                for tc_msg in messages:
                    if isinstance(tc_msg, AIMessage) and hasattr(tc_msg, "tool_calls"):
                        for tc in tc_msg.tool_calls:
                            if tc["id"] == msg.tool_call_id and tc["name"] in used_forbidden:
                                if "permission denied" in msg.content.lower() or "blocked" in msg.content.lower():
                                    forbidden_blocked += 1
                                else:
                                    forbidden_succeeded += 1

        if forbidden_succeeded > 0:
            score = 0.0
            comment = f"Forbidden tools were executed successfully: {used_forbidden}"
        elif forbidden_blocked > 0:
            if used_expected == expected and expected:
                score = 0.7
                comment = f"Forbidden tools attempted but blocked by permissions: {used_forbidden}. Expected tools all used."
            else:
                score = 0.5
                comment = f"Forbidden tools attempted but blocked by permissions: {used_forbidden}"
        else:
            score = 0.0
            comment = f"Used forbidden tools: {used_forbidden}"
    elif not expected and not used_forbidden:
        score = 1.0
        comment = "Correctly used no tools (none expected)"
    elif expected and used_expected == expected:
        score = 1.0
        comment = f"All expected tools used: {used_expected}"
    elif expected and used_expected:
        score = 0.5
        comment = f"Partial match. Expected: {expected}, Used: {used_expected}"
    else:
        score = 0.3
        comment = f"No expected tools used. Used: {tools_used}"

    return {"key": "tool_selection_accuracy", "score": score, "comment": comment}


def iteration_efficiency(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    max_iterations = reference_outputs.get("max_iterations", 10)

    messages = outputs.get("messages", [])
    iteration_count = sum(
        1 for m in messages
        if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls
    )

    if iteration_count <= max_iterations * 0.5:
        score = 1.0
        comment = f"Very efficient: {iteration_count} iterations (budget: {max_iterations})"
    elif iteration_count <= max_iterations:
        score = 0.7
        comment = f"Within budget: {iteration_count} iterations (budget: {max_iterations})"
    elif iteration_count <= max_iterations * 1.5:
        score = 0.4
        comment = f"Over budget: {iteration_count} iterations (budget: {max_iterations})"
    else:
        score = 0.0
        comment = f"Far over budget: {iteration_count} iterations (budget: {max_iterations})"

    return {"key": "iteration_efficiency", "score": score, "comment": comment}


def task_completion(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    expected_outcome = reference_outputs.get("expected_outcome", "")

    messages = outputs.get("messages", [])
    final_text = ""
    all_text_parts = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            final_text = msg.content
        if hasattr(msg, "content") and msg.content:
            all_text_parts.append(msg.content)

    all_text = " ".join(all_text_parts)

    if not expected_outcome:
        return {"key": "task_completion", "score": 0.5, "comment": "No expected outcome defined"}

    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "has", "have", "had",
        "in", "on", "at", "to", "for", "of", "with", "and", "or", "not",
        "that", "this", "it", "from", "by", "be", "as", "but", "if", "so",
        "can", "do", "will", "would", "could", "should", "may", "might",
    }
    key_terms = set(re.findall(r"\w+", expected_outcome.lower())) - stop_words

    if not key_terms:
        return {"key": "task_completion", "score": 0.5, "comment": "No key terms in expected outcome"}

    synonym_groups = [
        {"hello", "hi", "hey", "你好", "您好", "嗨", "hola"},
        {"help", "assist", "帮忙", "帮助", "协助", "support"},
        {"coding", "code", "编程", "代码", "program"},
        {"project", "项目", "repo"},
        {"welcome", "欢迎", "不客气"},
        {"greet", "greeting", "问候"},
        {"assistant", "助手", "agent"},
        {"cannot", "不能", "无法", "cannot", "不可"},
        {"modify", "edit", "修改", "编辑"},
        {"switch", "change", "切换", "转换"},
        {"build", "构建", "build"},
        {"plan", "计划", "plan"},
        {"mode", "模式", "mode"},
        {"read", "读", "read"},
        {"file", "文件", "file"},
        {"search", "搜索", "查找", "find", "grep"},
        {"add", "添加", "新增", "field", "字段"},
        {"iteration_count", "int"},
        {"rest", "restful", "资源", "resource", "state", "transfer"},
        {"api", "接口", "endpoints", "endpoint"},
        {"decorator", "装饰器", "wrapper", "语法糖"},
        {"git", "版本控制", "version"},
        {"merge", "合并", "merge"},
        {"rebase", "变基", "rebase"},
        {"docker", "容器", "container"},
        {"vm", "虚拟机", "virtual", "machine"},
        {"async", "异步", "asynchronous", "await", "协程", "coroutine"},
        {"cap", "consistency", "availability", "partition", "一致性", "可用性"},
        {"microservice", "微服务", "monolith", "单体"},
        {"architecture", "架构"},
        {"tech", "技术", "stack", "技术栈"},
        {"python", "langchain", "langgraph", "cli"},
        {"count", "数量", "method", "方法"},
        {"thanks", "thank", "感谢", "谢谢", "glad"},
        {"recommend", "推荐", "suggest", "book", "书"},
        {"kernel", "内核", "隔离", "isolation", "轻量", "lightweight"},
        {"linear", "线性", "history", "历史"},
        {"distributed", "分布式"},
        {"deploy", "部署"},
        {"advantage", "优点", "pro", "benefit"},
        {"disadvantage", "缺点", "con", "drawback"},
        {"refactor", "重构", "restructure", "拆分", "split"},
        {"docstring", "文档字符串", "doc", "文档", "注释", "comment"},
        {"permission", "权限", "permission", "allow", "deny", "允许", "拒绝"},
        {"compaction", "压缩", "compact", "prune", "overflow"},
        {"evaluate", "评估", "评估", "judge", "check"},
        {"complexity", "复杂度", "复杂", "complex"},
        {"optimize", "优化", "optimization", "improve"},
        {"extract", "提取", "独立", "separate"},
        {"module", "模块", "module"},
        {"function", "函数", "function", "方法", "method"},
        {"class", "类", "class"},
        {"variable", "变量", "variable"},
        {"import", "导入", "import"},
        {"dependency", "依赖", "dependency"},
    ]

    def _find_synonym_match(term: str, text_lower: str) -> bool:
        if term in text_lower:
            return True
        for group in synonym_groups:
            if term in group:
                for syn in group:
                    if syn in text_lower:
                        return True
        return False

    all_lower = all_text.lower()
    final_lower = final_text.lower()
    matched_all = sum(1 for term in key_terms if _find_synonym_match(term, all_lower))
    matched_final = sum(1 for term in key_terms if _find_synonym_match(term, final_lower))

    coverage = max(matched_all, matched_final) / len(key_terms)

    if coverage >= 0.6:
        score = 1.0
    elif coverage >= 0.4:
        score = 0.8
    elif coverage >= 0.25:
        score = 0.6
    else:
        score = 0.2

    return {
        "key": "task_completion",
        "score": score,
        "comment": f"Coverage: {coverage:.0%} of key terms. Final: {len(final_text)} chars, All: {len(all_text)} chars",
    }


def no_read_redundancy(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    messages = outputs.get("messages", [])

    tool_call_ids_blocked = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            if msg.content.startswith("[BLOCKED]") or msg.content.startswith("[Permission denied]"):
                tool_call_ids_blocked.add(msg.tool_call_id)

    read_paths = []
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] == "read_file" and tc["id"] not in tool_call_ids_blocked:
                    path = tc.get("args", {}).get("path", "")
                    if path:
                        from pathlib import Path as _Path
                        try:
                            path = str(_Path(path).expanduser().resolve())
                        except Exception:
                            pass
                        read_paths.append(path)

    path_counts = Counter(read_paths)
    max_reads = max(path_counts.values()) if path_counts else 0
    duplicate_reads = sum(1 for c in path_counts.values() if c > 1)

    if max_reads <= 1:
        score = 1.0
        comment = "No duplicate file reads"
    elif max_reads == 2:
        score = 0.7
        comment = f"{duplicate_reads} file(s) read twice"
    else:
        score = 0.0
        comment = f"File read {max_reads} times: {[p for p, c in path_counts.items() if c == max_reads]}"

    return {"key": "no_read_redundancy", "score": score, "comment": comment}


def agent_permission_correctness(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Check that the agent's permissions were correctly enforced.

    Verifies that denied tools were not successfully executed
    (i.e., no ToolMessage with successful result for denied tools).
    """
    expected_perms = reference_outputs.get("expected_agent_permissions", {})
    if not expected_perms:
        return {"key": "agent_permission_correctness", "score": 1.0, "comment": "No permission expectations defined"}

    messages = outputs.get("messages", [])
    denied_tool_calls = set()

    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc["name"]
                expected = expected_perms.get(tool_name)
                if expected == "deny":
                    denied_tool_calls.add(tc["id"])

    permission_violations = 0
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id in denied_tool_calls:
            content = msg.content.lower()
            if "permission denied" not in content and "blocked" not in content:
                permission_violations += 1

    if permission_violations == 0:
        score = 1.0
        comment = "All permission denials correctly enforced"
    else:
        score = 0.0
        comment = f"{permission_violations} permission violation(s): denied tools were executed"

    return {"key": "agent_permission_correctness", "score": score, "comment": comment}


def tool_result_quality(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    messages = outputs.get("messages", [])
    tool_results = []
    error_results = 0

    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content or ""
            tool_results.append(content)
            if content.startswith("Error:") and "permission denied" not in content.lower():
                error_results += 1

    total = len(tool_results)
    if total == 0:
        return {"key": "tool_result_quality", "score": 1.0, "comment": "No tool calls made"}

    success_rate = (total - error_results) / total
    if success_rate >= 0.9:
        score = 1.0
    elif success_rate >= 0.7:
        score = 0.7
    else:
        score = 0.3

    return {
        "key": "tool_result_quality",
        "score": score,
        "comment": f"Success rate: {success_rate:.0%} ({total - error_results}/{total} successful)",
    }


def response_conciseness(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    messages = outputs.get("messages", [])
    final_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            final_text = msg.content
            break

    if not final_text:
        return {"key": "response_conciseness", "score": 0.0, "comment": "No final response text"}

    max_iterations = reference_outputs.get("max_iterations", 10)
    tool_call_count = sum(
        1 for m in messages
        if isinstance(m, AIMessage) and hasattr(m, "tool_calls") and m.tool_calls
    )

    if max_iterations == 0:
        if tool_call_count == 0:
            if len(final_text) <= 500:
                score = 1.0
            elif len(final_text) <= 1000:
                score = 0.8
            elif len(final_text) <= 2000:
                score = 0.6
            elif len(final_text) <= 4000:
                score = 0.4
            else:
                score = 0.3
            comment = f"General Q&A: {len(final_text)} chars, 0 tool calls"
        else:
            score = 0.2
            comment = f"General Q&A: unnecessary {tool_call_count} tool calls made"
    else:
        if len(final_text) <= 800:
            score = 1.0
        elif len(final_text) <= 1500:
            score = 0.8
        elif len(final_text) <= 3000:
            score = 0.6
        elif len(final_text) <= 5000:
            score = 0.4
        else:
            score = 0.3
        comment = f"Coding task: {len(final_text)} chars, {tool_call_count} tool calls"

    return {"key": "response_conciseness", "score": score, "comment": comment}
