"""Message compaction and pruning for LangGraph context budget.

Three-tier strategy: prune_tool_outputs (reduce large tool results),
compact_messages (LLM-based summarization of old turns),
and overflow_compaction (fallback when still over budget).
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from codepilot.agent._utils import (
    estimate_tokens,
    find_tool_call_pairs,
    validate_message_pairs,
)
from codepilot.plugins.manager import HookType, get_plugin_manager

PRUNE_MINIMUM_TOKENS = 20_000
PRUNE_PROTECT_TOKENS = 40_000
DEFAULT_TAIL_TURNS = 2
MIN_PRESERVE_RECENT_TOKENS = 2_000
MAX_PRESERVE_RECENT_TOKENS = 8_000
MAX_ACTIVE_TAIL_MESSAGES = 14
MIN_ACTIVE_HEAD_MESSAGES = 8
TOOL_COMPACTION_EXCERPT_CHARS = 1200
TOOL_PRUNE_EXCERPT_LINES = 24

COMPACTION_PROMPT = """You are a conversation compaction assistant. Summarize the following conversation history.

Focus on:
1. What the user asked for (original request)
2. FILES READ — for EACH file, include:
   - File path (exact)
   - Key classes/functions defined (with line numbers if shown)
   - Key imports and dependencies
   - Important constants or configuration
   - Any errors or notable findings
3. What changes were made (file paths, function names, exact edits)
4. Errors encountered and resolutions
5. Pending tasks or unresolved issues

Rules:
- Preserve specific file paths, function names, variable names, and error messages exactly
- Do NOT include information about the most recent exchanges — those are preserved separately
- Be concise but complete — every detail that might be needed later should be included
- Use the same language as the user (Chinese/English)
- Output only the summary, no preamble
- The file content summary is CRITICAL — the agent cannot re-read files after compaction

{previous_summary}"""


def prune_tool_outputs(messages: list[BaseMessage], usable_context: int) -> list[BaseMessage]:
    if not messages:
        return messages

    total_tokens = estimate_tokens(messages)
    if total_tokens <= usable_context - PRUNE_MINIMUM_TOKENS:
        return messages

    result = list(messages)
    protected_budget = min(PRUNE_PROTECT_TOKENS, int(usable_context * 0.25))

    tool_msg_indices = []
    for i, msg in enumerate(result):
        if isinstance(msg, ToolMessage) and msg.content:
            estimated = len(msg.content) // 4
            tool_msg_indices.append((i, estimated))

    tool_msg_indices.reverse()

    recent_tokens = 0
    protected_indices: set[int] = set()
    for idx, est in tool_msg_indices:
        if recent_tokens >= protected_budget:
            break
        protected_indices.add(idx)
        recent_tokens += est

    pair_groups = find_tool_call_pairs(result)
    for group in pair_groups:
        if any(idx in protected_indices for idx in group):
            protected_indices.update(group)

    new_messages = []
    for i, msg in enumerate(result):
        if isinstance(msg, ToolMessage) and i not in protected_indices:
            lines = msg.content.split("\n")
            total_lines = len(lines)
            if total_lines > 3:
                excerpt = _tool_excerpt(
                    msg.content,
                    max_lines=TOOL_PRUNE_EXCERPT_LINES,
                    max_chars=TOOL_COMPACTION_EXCERPT_CHARS,
                )
                compressed = (
                    f"[Tool output pruned: {total_lines} lines, {len(msg.content)} chars]\n"
                    f"{excerpt}"
                )
                new_messages.append(ToolMessage(content=compressed, tool_call_id=msg.tool_call_id))
            else:
                new_messages.append(msg)
        else:
            new_messages.append(msg)

    return new_messages


def compact_messages(
    messages: list[BaseMessage],
    llm: object | None = None,
    tail_turns: int = DEFAULT_TAIL_TURNS,
    usable_context: int | None = None,
) -> list[BaseMessage]:
    if len(messages) <= 8:
        return messages

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_system) <= 6:
        return messages

    tail_count = 0
    tail_start = len(non_system)
    newest_human_idx: int | None = None
    for i in range(len(non_system) - 1, -1, -1):
        if isinstance(non_system[i], HumanMessage):
            if newest_human_idx is None:
                newest_human_idx = i
            tail_count += 1
            if tail_count >= tail_turns:
                tail_start = i
                break
    if tail_count > 0 and tail_count < tail_turns:
        tail_start = newest_human_idx if newest_human_idx is not None else tail_start

    if (
        tail_start == 0
        and len(non_system) > MAX_ACTIVE_TAIL_MESSAGES + MIN_ACTIVE_HEAD_MESSAGES
    ):
        tail_start = len(non_system) - MAX_ACTIVE_TAIL_MESSAGES

    pair_groups = find_tool_call_pairs(non_system)
    protected: set[int] = set(range(tail_start, len(non_system)))
    for group in pair_groups:
        if any(idx in protected for idx in group):
            protected.update(group)

    head = [m for i, m in enumerate(non_system) if i not in protected]
    tail = [m for i, m in enumerate(non_system) if i in protected]

    if not head:
        return messages

    original_request = ""
    for m in reversed(head):
        if isinstance(m, HumanMessage) and not m.content.startswith("[Previous context:"):
            original_request = m.content[:300]
            break

    head_tool_count = sum(1 for m in head if isinstance(m, ToolMessage))
    head_msg_count = len(head)

    if llm is not None:
        try:
            summary = _llm_compact(llm, head)
        except Exception:
            summary = None
    else:
        summary = None

    if summary:
        summary_text = summary
    else:
        parts = [f"[Previous context: {head_msg_count} messages, {head_tool_count} tool results omitted"]
        if original_request:
            parts.append(f"Original user request: {original_request}")
        parts.append("Continue the task from where you left off.]")
        summary_text = "\n".join(parts)

    pm = get_plugin_manager()
    if pm.has_hooks(HookType.COMPACTION):
        summary_text = pm.emit(
            HookType.COMPACTION,
            {"messages": head, "summary": summary_text},
        )["summary"]

    summary_msg = HumanMessage(content=summary_text)
    return validate_message_pairs(system_msgs + [summary_msg] + tail)


def _llm_compact(llm: object, head_messages: list[BaseMessage]) -> str | None:
    from langchain_core.messages import SystemMessage as LCSystemMessage
    from langchain_core.messages import HumanMessage as LCHumanMessage

    compact_system = LCSystemMessage(content=COMPACTION_PROMPT.format(previous_summary=""))

    text_parts = []
    for m in head_messages:
        if isinstance(m, HumanMessage):
            text_parts.append(f"User: {m.content[:500]}")
        elif isinstance(m, AIMessage):
            if m.content:
                text_parts.append(f"Assistant: {m.content[:500]}")
            if m.tool_calls:
                for tc in m.tool_calls:
                    text_parts.append(f"Assistant called: {tc['name']}({str(tc.get('args', {}))[:200]})")
        elif isinstance(m, ToolMessage):
            text_parts.append(
                f"Tool result ({m.tool_call_id}): "
                f"{_tool_excerpt(m.content, max_lines=18, max_chars=TOOL_COMPACTION_EXCERPT_CHARS)}"
            )

    conversation_text = "\n\n".join(text_parts)
    if not conversation_text.strip():
        return None

    compact_input = LCHumanMessage(content=f"Conversation to summarize:\n\n{conversation_text}")

    try:
        response = llm.invoke([compact_system, compact_input])
        return response.content if hasattr(response, "content") else str(response)
    except Exception:
        return None


def overflow_compaction(
    messages: list[BaseMessage],
    llm: object | None = None,
    hard_limit: int = 200_000,
) -> list[BaseMessage]:
    if not messages:
        return messages

    total_tokens = estimate_tokens(messages)
    if total_tokens <= hard_limit:
        return messages

    stripped = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and len(msg.content) > 5000:
            lines = msg.content.split("\n")
            total_lines = len(lines)
            if total_lines > 20:
                head = "\n".join(lines[:5])
                tail = "\n".join(lines[-5:])
                compressed = f"{head}\n... ({total_lines - 10} lines stripped for overflow) ...\n{tail}"
                stripped.append(ToolMessage(content=compressed, tool_call_id=msg.tool_call_id))
            else:
                first_line = lines[0] if lines else ""
                compressed = f"{first_line}\n... (content stripped for overflow)"
                stripped.append(ToolMessage(content=compressed, tool_call_id=msg.tool_call_id))
        else:
            stripped.append(msg)

    if estimate_tokens(stripped) <= hard_limit:
        return stripped

    replay_idx = 0
    for i in range(len(stripped) - 1, -1, -1):
        msg = stripped[i]
        if isinstance(msg, HumanMessage) and not msg.content.startswith("[Previous context:"):
            replay_idx = i
            break

    if replay_idx > 0:
        head = stripped[:replay_idx]
        tail = stripped[replay_idx:]

        head_count = len(head)
        head_tools = sum(1 for m in head if isinstance(m, ToolMessage))

        summary = HumanMessage(
            content=f"[Overflow compaction: {head_count} messages, {head_tools} tool results stripped. "
                    f"Continue from where you left off.]"
        )
        result = [summary] + tail

        result = validate_message_pairs(result)
        return result

    return stripped


def _tool_excerpt(content: str, *, max_lines: int, max_chars: int) -> str:
    """Return a head/tail excerpt that preserves both setup and final signal."""
    if len(content) <= max_chars and content.count("\n") + 1 <= max_lines:
        return content

    lines = content.splitlines()
    if not lines:
        return content[:max_chars]

    if len(lines) > max_lines:
        head_count = max(1, int(max_lines * 0.7))
        tail_count = max(1, max_lines - head_count)
        omitted = len(lines) - head_count - tail_count
        lines = (
            lines[:head_count]
            + [f"... ({omitted} lines omitted during context pruning) ..."]
            + lines[-tail_count:]
        )

    excerpt = "\n".join(lines)
    if len(excerpt) <= max_chars:
        return excerpt

    omitted_chars = len(excerpt) - max_chars
    head_chars = max_chars * 7 // 10
    tail_chars = max_chars - head_chars
    return (
        excerpt[:head_chars]
        + f"\n... ({omitted_chars} chars omitted during context pruning) ...\n"
        + excerpt[-tail_chars:]
    )
