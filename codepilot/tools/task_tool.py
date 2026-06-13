from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from codepilot.agent.registry import AgentRegistry
from codepilot.agent.state import AgentState
from codepilot.config.permissions import PermissionRuleset
from codepilot.storage.db import Storage, new_session_id
from codepilot.storage.models import SessionInfo

_registry = AgentRegistry()


def run_subagent(
    prompt: str,
    subagent_type: str,
    parent_session_id: str,
    parent_agent_name: str,
    parent_permissions: PermissionRuleset,
    parent_working_dir: str,
    parent_files_context: list[str],
    llm: Any = None,
    storage: Storage | None = None,
) -> str:
    agent_def = _registry.get(subagent_type)
    if agent_def is None:
        available = [a.name for a in _registry.list_subagents()]
        return f"Error: Unknown subagent type '{subagent_type}'. Available: {available}"

    if agent_def.is_primary:
        return f"Error: '{subagent_type}' is a primary agent and cannot be used as a subagent."

    if llm is None:
        return "Error: No LLM available for subagent execution"

    child_session_id = new_session_id()

    if storage is not None:
        try:
            child_session = SessionInfo(
                id=child_session_id,
                parent_id=parent_session_id,
                title=f"Subagent: {agent_def.display_name}",
                agent=subagent_type,
                model="",
                mode=subagent_type,
            )
            storage.create_session(child_session)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Failed to create subagent session %s", child_session_id)

    from codepilot.agent.graph import build_agent_graph
    from codepilot.config.context_windows import get_usable_context

    model_name = getattr(llm, "model", "") or ""
    context_window = get_usable_context(model_name)

    parent_deny_rules = [
        r for r in parent_permissions.rules
        if r.action in ("deny", "ask")
    ]
    subagent_permissions = agent_def.permissions
    if parent_deny_rules:
        subagent_permissions = subagent_permissions.merge(
            PermissionRuleset(rules=parent_deny_rules)
        )

    try:
        graph = build_agent_graph(
            llm=llm,
            agent_name=subagent_type,
            context_window=context_window,
            custom_permissions=subagent_permissions,
            custom_tools=agent_def.tools,
        )
    except Exception as e:
        return f"Error building subagent graph: {e}"

    child_state: AgentState = {
        "messages": [HumanMessage(content=prompt)],
        "working_dir": parent_working_dir,
        "files_context": list(parent_files_context),
        "task_type": "subagent",
        "agent_name": subagent_type,
        "session_id": child_session_id,
    }

    try:
        final_state = graph.invoke(
            child_state,
            config={
                "recursion_limit": agent_def.steps * 2 + 10,
                "run_name": f"subagent_{subagent_type}",
            },
        )
    except Exception as e:
        return f"Subagent error: {e}"

    result_messages = final_state.get("messages", [])
    final_ai = None
    for msg in reversed(result_messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            final_ai = msg.content
            break

    return final_ai or "Subagent completed with no output."


@tool
def task(
    prompt: str,
    subagent_type: Literal["explore", "general"] = "general",
) -> str:
    """Launch a subagent to handle a complex, multi-step task.

    Subagents run in their own context with independent iteration limits.
    Use 'explore' for fast read-only codebase search, 'general' for multi-step tasks.

    Args:
        prompt: The task description for the subagent
        subagent_type: Which subagent to use - 'explore' (read-only search) or 'general' (full access)
    """
    return ""


SUBAGENT_TOOL_NAME = "task"
