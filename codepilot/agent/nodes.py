"""Helpers for the LangGraph agent_node.

These are pulled out of `graph.py` so the node body itself stays small
and the construction of the system prompt / response truncation /
iteration budget is testable in isolation.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage

from codepilot.agent._utils import estimate_tokens
from codepilot.agent.compaction import (
    compact_messages,
    overflow_compaction,
    prune_tool_outputs,
)
from codepilot.agent import context_manager as agent_context
from codepilot.agent.context_manager import (
    extract_file_summaries,
    render_files_context_block,
)
from codepilot.agent.prompts import get_project_context
from codepilot.agent.registry import AgentDef
from codepilot.agent.state import AgentState
from codepilot.plugins.manager import HookType, get_plugin_manager

# Budget tuning: keep enough room for real development tasks while relying on
# task routing, tool dedup, truncation and stop-early prompt rules to control waste.
MAX_MESSAGES = 48
MAX_TOOL_RESULT_CHARS = agent_context.DEFAULT_TOOL_RESULT_CHARS
MAX_ITERATIONS = 40
HARD_ITERATION_LIMIT = 80
GRAPH_RECURSION_LIMIT = 180
MAX_RESPONSE_CHARS = 6000
FILE_SUMMARY_MAX_LINES = agent_context.FILE_SUMMARY_MAX_LINES
FILE_SUMMARY_MAX_KEY_LINES = agent_context.FILE_SUMMARY_MAX_KEY_LINES
FILE_SUMMARY_MAX_LINE_LEN = agent_context.FILE_SUMMARY_MAX_LINE_LEN

TASK_ITERATION_LIMITS: dict[str, int] = {
    "code_search": 12,
    "project_analysis": 24,
    "general_question": 4,
    "file_edit": 30,
    "file_write": 30,
    "command_run": 20,
    "test_evaluation": 32,
    "subagent": 36,
}
DEFAULT_TASK_ITERATION_LIMIT = MAX_ITERATIONS


def _extract_file_summaries(messages: list, files_context: list[str]) -> dict[str, str]:
    """Compatibility wrapper around AgentContextManager."""
    return extract_file_summaries(messages, files_context)


def _tool_round_count(messages: list) -> tuple[int, int]:
    """Return (iteration_count, total_tool_invocations) over message history."""
    iteration_count = 0
    total = 0
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            iteration_count += 1
            total += len(m.tool_calls)
    return iteration_count, total


def compress_for_state(
    messages: list,
    *,
    context_window: int,
    llm,
) -> list:
    """Apply three-tier compaction in the right order."""
    compact_threshold = int(context_window * 0.8)
    overflow_threshold = int(context_window * 0.95)

    if estimate_tokens(messages) > overflow_threshold:
        messages = overflow_compaction(messages, llm=llm, hard_limit=overflow_threshold)

    if estimate_tokens(messages) > compact_threshold:
        messages = prune_tool_outputs(messages, usable_context=context_window)

    if len(messages) > MAX_MESSAGES or estimate_tokens(messages) > compact_threshold:
        messages = compact_messages(messages, llm=llm, usable_context=context_window)

    return messages


def build_system_prompt_with_context(
    base_prompt: str,
    state: AgentState,
    *,
    agent_def: AgentDef,
    iteration_count: int,
    total_tool_invocations: int,
    iteration_limit: int,
    file_summaries: dict[str, str],
    files_context_block: str | None = None,
) -> str:
    """Construct the full system prompt for an agent turn."""
    project_ctx = get_project_context()
    full_system = f"{base_prompt}\n\n{project_ctx}"

    files_ctx = state.get("files_context", [])
    if files_ctx:
        block = files_context_block
        if block is None:
            block = render_files_context_block(files_ctx, file_summaries)
        full_system += f"\n\n{block}"

    if agent_def.name != "build":
        full_system += f"\n\n## Current Agent: {agent_def.display_name}\n"
        if agent_def.description:
            full_system += f"{agent_def.description}\n"

    remaining = iteration_limit - iteration_count
    if iteration_count > 0:
        full_system += (
            f"\n\n## Iteration Budget: {iteration_count}/{iteration_limit} tool rounds used "
            f"({total_tool_invocations} total invocations, hard limit: {HARD_ITERATION_LIMIT}). "
            f"{remaining} rounds remaining."
        )
    if remaining <= 5 and remaining > 0:
        full_system += (
            f"\n\n## WARNING: Only {remaining} tool call(s) remaining. "
            f"Prioritize the most important operation. Do NOT re-read files."
        )
    if state.get("task_type") == "test_evaluation":
        full_system += (
            "\n\n## Test/evaluation task completion contract:\n"
            "- This is a test/evaluation task: run the requested app/test/lint commands when permitted.\n"
            "- do not produce an evaluation report until at least one relevant command has a real tool result.\n"
            "- If tool execution is denied, blocked, unavailable, or the iteration limit is reached before verification, "
            "state that the evaluation is incomplete and name the exact missing command/result.\n"
            "- Never treat \"results unavailable\" or an uncalled command as evidence of pass/fail."
        )
    if total_tool_invocations >= HARD_ITERATION_LIMIT - 3 and total_tool_invocations < HARD_ITERATION_LIMIT:
        full_system += (
            f"\n\n## CRITICAL: You have made {total_tool_invocations} total tool invocations. "
            f"Hard limit is {HARD_ITERATION_LIMIT}. You MUST summarize now with no more tool calls."
        )

    pm = get_plugin_manager()
    if pm.has_hooks(HookType.SYSTEM_PROMPT_TRANSFORM):
        full_system = pm.emit(
            HookType.SYSTEM_PROMPT_TRANSFORM,
            {"prompt": full_system, "state": state},
        )["prompt"]

    return full_system


def truncate_response(
    response: AIMessage,
    *,
    agent_def: AgentDef,
    total_tool_invocations: int,
) -> AIMessage:
    """Cap the response content size based on agent type and usage."""
    if not (hasattr(response, "content") and isinstance(response.content, str)):
        return response
    if getattr(response, "tool_calls", None):
        return response

    if agent_def.is_readonly:
        response_limit = 5000
    elif total_tool_invocations >= 10:
        response_limit = 5000
    elif total_tool_invocations >= 3:
        response_limit = 8000
    else:
        response_limit = MAX_RESPONSE_CHARS

    if len(response.content) > response_limit:
        truncated = response.content[:response_limit]
        truncated += (
            f"\n\n[Response truncated: {len(response.content)} chars → {response_limit} chars. "
            f"Be more concise.]"
        )
        return AIMessage(
            content=truncated,
            tool_calls=getattr(response, "tool_calls", None),
            id=getattr(response, "id", None),
        )
    return response


def has_system_message(messages: list) -> bool:
    return any(isinstance(m, SystemMessage) for m in messages)
