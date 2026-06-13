"""Shared message-processing utilities for the agent graph and REPL.

These helpers are used by both the LangGraph nodes (agent/graph.py,
agent/compaction.py) and the REPL (ui/repl.py). Keeping a single
implementation avoids drift between copies that previously diverged in
argument typing.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """Rough token estimate: chars / 4 plus tool-call argument overhead.

    This is intentionally cheap (no tokenizer dependency) — it's used for
    deciding when to compact, not for billing.
    """
    total = 0
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            total += len(msg.content)
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                total += len(str(tc.get("name", "")))
                total += len(str(tc.get("args", {})))
    return total // 4


def find_tool_call_pairs(messages: list[BaseMessage]) -> list[list[int]]:
    """Return groups of indices [ai_idx, tm_idx, ...] for each tool-call turn.

    A group contains the AIMessage index and every ToolMessage index that
    belongs to it. Single pass, O(N).
    """
    pending: dict[str, int] = {}
    groups: list[list[int]] = []

    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            group = [i]
            for tc in msg.tool_calls:
                pending[tc["id"]] = i
            groups.append(group)
        elif isinstance(msg, ToolMessage):
            ai_idx = pending.get(msg.tool_call_id)
            if ai_idx is None:
                continue
            for g in groups:
                if g[0] == ai_idx:
                    g.append(i)
                    break

    return groups


def validate_message_pairs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Enforce AIMessage(tool_calls) ↔ ToolMessage adjacency invariant.

    LangChain / OpenAI APIs reject conversations where an AIMessage that
    issued tool calls is not immediately followed by the matching
    ToolMessages. After compaction or resume, this invariant can be
    violated — this function repairs it.
    """
    if not messages:
        return messages

    result: list[BaseMessage] = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        if isinstance(msg, AIMessage) and msg.tool_calls:
            required_ids = {tc["id"] for tc in msg.tool_calls}

            immediate_tools: list[ToolMessage] = []
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                immediate_tools.append(messages[j])
                j += 1

            immediate_ids = {tm.tool_call_id for tm in immediate_tools}

            if required_ids.issubset(immediate_ids):
                result.append(msg)
                for tm in immediate_tools:
                    if tm.tool_call_id in required_ids:
                        result.append(tm)
                i = j
            else:
                content = msg.content or ""
                if not content:
                    parts = [f"{tc['name']}({tc.get('args', {})})" for tc in msg.tool_calls]
                    content = "[Tool calls made but results unavailable: " + "; ".join(parts) + "]"
                result.append(AIMessage(content=content))
                for tm in immediate_tools:
                    if tm.tool_call_id not in required_ids:
                        result.append(tm)
                i = j

        elif isinstance(msg, ToolMessage):
            i += 1

        else:
            result.append(msg)
            i += 1

    return result
