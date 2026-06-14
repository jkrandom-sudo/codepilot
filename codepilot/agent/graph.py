from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from codepilot.agent._utils import validate_message_pairs
from codepilot.agent.context_manager import AgentContextManager
from codepilot.agent.nodes import (
    HARD_ITERATION_LIMIT,
    GRAPH_RECURSION_LIMIT,
    MAX_TOOL_RESULT_CHARS,
    TASK_ITERATION_LIMITS,
    _tool_round_count,
    build_system_prompt_with_context,
    compress_for_state,
    has_system_message,
    truncate_response,
)
from codepilot.agent.prompts import PLAN_EXECUTE_PLANNER_PROMPT, build_system_prompt, get_project_context
from codepilot.agent.registry import AgentRegistry
from codepilot.agent.state import AgentState
from codepilot.config.permissions import PermissionRuleset
from codepilot.plugins.manager import HookType, get_plugin_manager
from codepilot.tools import ALL_TOOLS
from codepilot.tools.shell_tool import _is_search_command

_registry = AgentRegistry()
READ_FILE_CALL_LIMIT = 80
DEFAULT_SEARCH_CALL_LIMIT = 8
DEEP_SEARCH_CALL_LIMIT = 28
DEFAULT_SHELL_CALL_LIMIT = 10
DEEP_SHELL_CALL_LIMIT = 36


def _is_deep_context_task(task_type: str, agent_name: str) -> bool:
    return task_type in {"project_analysis", "file_edit", "file_write", "test_evaluation", "subagent"} or agent_name == "plan-execute"


def _normalize_path(path: str) -> str:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except Exception:
        pass
    return str(p)


def _compress_tool_results(messages: list, truncation_store=None) -> list:
    return AgentContextManager(
        truncation_store=truncation_store,
        base_tool_result_chars=MAX_TOOL_RESULT_CHARS,
    ).compress_tool_results(messages)


def build_agent_graph(
    llm: Any,
    agent_name: str = "build",
    context_window: int | None = None,
    custom_permissions: PermissionRuleset | None = None,
    custom_tools: list[str] | None = None,
    storage: Any | None = None,
    ask_permission_callback: Callable[[str, dict], bool] | None = None,
    coauthor: bool = True,
) -> StateGraph:
    if context_window is None:
        from codepilot.config.context_windows import get_usable_context
        model_name = getattr(llm, "model", "") or ""
        context_window = get_usable_context(model_name)

    agent_def = _registry.get_or_default(agent_name)
    iteration_limit = agent_def.steps
    permissions = custom_permissions or agent_def.permissions
    confirm = agent_def.confirm

    if custom_tools is not None:
        tools = [t for t in ALL_TOOLS if t.name in custom_tools]
    elif agent_def.tools is not None:
        tool_names = set(agent_def.tools)
        tools = [t for t in ALL_TOOLS if t.name in tool_names]
    else:
        tools = list(ALL_TOOLS)

    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    system_prompt = build_system_prompt(agent_name=agent_name, confirm=confirm, coauthor=coauthor)
    context_manager = AgentContextManager(
        context_window=context_window,
        base_tool_result_chars=MAX_TOOL_RESULT_CHARS,
    )

    _ask_permission_callback = ask_permission_callback
    _latest_file_summaries: dict[str, str] = {}

    def agent_node(state: AgentState) -> dict:
        messages = state["messages"]
        files_ctx = state.get("files_context", [])

        file_summaries = context_manager.extract_file_summaries(messages, files_ctx)
        nonlocal _latest_file_summaries
        _latest_file_summaries = file_summaries

        messages = compress_for_state(messages, context_window=context_window, llm=llm)
        messages = context_manager.compress_tool_results(messages)
        messages = validate_message_pairs(messages)

        iteration_count, total_tool_invocations = _tool_round_count(state["messages"])

        task_type = state.get("task_type", "")
        effective_iteration_limit = TASK_ITERATION_LIMITS.get(task_type, iteration_limit)

        full_system = build_system_prompt_with_context(
            system_prompt,
            state,
            agent_def=agent_def,
            iteration_count=iteration_count,
            total_tool_invocations=total_tool_invocations,
            iteration_limit=effective_iteration_limit,
            file_summaries=file_summaries,
            files_context_block=context_manager.render_files_context(files_ctx, file_summaries),
        )

        if has_system_message(messages):
            all_messages = messages
        else:
            all_messages = [SystemMessage(content=full_system)] + messages

        response = llm_with_tools.invoke(all_messages)
        response = truncate_response(
            response,
            agent_def=agent_def,
            total_tool_invocations=total_tool_invocations,
        )

        return {"messages": [response]}

    def planner_node(state: AgentState) -> dict:
        messages = validate_message_pairs(state["messages"])
        planner_system = PLAN_EXECUTE_PLANNER_PROMPT
        project_context = get_project_context(state.get("working_dir"))
        if project_context:
            planner_system += "\n\n" + project_context
        plan_messages = [SystemMessage(content=planner_system)] + messages
        response = llm.invoke(plan_messages)
        content = getattr(response, "content", "") or str(response)
        plan = AIMessage(content=f"[Plan-and-Execute Plan]\n{content}")
        return {"messages": [plan]}

    def tool_node(state: AgentState) -> dict:
        from codepilot.tools.context import ToolContext

        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage):
            return {"messages": []}

        tool_ctx = ToolContext(
            session_id=state.get("session_id", ""),
            agent_name=agent_name,
            working_dir=state.get("working_dir", os.getcwd()),
            files_context=list(state.get("files_context", [])),
            permissions=permissions,
        )

        for msg in state["messages"]:
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["name"] in ("glob", "grep"):
                        pat = tc.get("args", {}).get("pattern", "")
                        p = tc.get("args", {}).get("path", "")
                        tool_ctx.seen_patterns.add(f"{tc['name']}:{pat}:{p}")

        tool_results = []
        new_files = list(tool_ctx.files_context)
        existing_files = set(new_files)
        existing_files_normalized = {_normalize_path(f) for f in existing_files}

        prior_read_file_count = 0
        prior_run_shell_count = 0
        for m in state["messages"]:
            if isinstance(m, AIMessage) and m.tool_calls:
                for tc in m.tool_calls:
                    name = tc.get("name")
                    if name == "read_file":
                        prior_read_file_count += 1
                    elif name == "run_shell":
                        prior_run_shell_count += 1

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call.get("args", {})
            tool_id = tool_call["id"]
            user_confirmed = False
            task_type = state.get("task_type", "")
            deep_context = _is_deep_context_task(task_type, agent_name)

            perm = permissions.evaluate(tool_name, tool_args)
            if perm == "deny":
                alt = ""
                if tool_name in ("edit_file", "write_file", "run_shell"):
                    alt = " Switch to build agent to perform this action, or describe what needs to be done."
                tool_results.append(ToolMessage(
                    content=f"[Permission denied] {tool_name} is not allowed for agent '{agent_name}'.{alt}",
                    tool_call_id=tool_id,
                ))
                continue
            if perm == "ask" and not _ask_permission_callback:
                tool_results.append(ToolMessage(
                    content=f"[Permission denied] {tool_name} requires confirmation (non-interactive mode). "
                            f"Use --no-confirm flag for auto mode.",
                    tool_call_id=tool_id,
                ))
                continue
            if perm == "ask" and _ask_permission_callback:
                if not _ask_permission_callback(tool_name, tool_args):
                    tool_results.append(ToolMessage(
                        content="Permission denied by user",
                        tool_call_id=tool_id,
                    ))
                    continue
                user_confirmed = True

            if tool_name == "task":
                try:
                    from codepilot.tools.task_tool import run_subagent
                    result = run_subagent(
                        prompt=tool_args.get("prompt", ""),
                        subagent_type=tool_args.get("subagent_type", "general"),
                        parent_session_id=state.get("session_id", ""),
                        parent_agent_name=agent_name,
                        parent_permissions=permissions,
                        parent_working_dir=state.get("working_dir", os.getcwd()),
                        parent_files_context=list(state.get("files_context", [])),
                        llm=llm,
                        storage=storage,
                    )
                    tool_results.append(ToolMessage(content=result, tool_call_id=tool_id))
                except Exception as e:
                    tool_results.append(ToolMessage(
                        content=f"Error executing subagent: {e}",
                        tool_call_id=tool_id,
                    ))
                continue

            if tool_name == "read_file":
                path = tool_args.get("path", "")
                path_normalized = _normalize_path(path) if path else ""
                targeted_read = tool_args.get("offset") is not None or tool_args.get("limit") is not None
                read_file_limit = READ_FILE_CALL_LIMIT if deep_context else 24
                if prior_read_file_count > read_file_limit:
                    tool_results.append(ToolMessage(
                        content=f"[BLOCKED] Too many read_file calls ({prior_read_file_count}). "
                                f"You have read enough files. Summarize and answer from what you have. "
                                f"If a specific detail is missing, use one targeted offset/limit read only.",
                        tool_call_id=tool_id,
                    ))
                    continue
                if (
                    path
                    and not targeted_read
                    and (path in existing_files or (path_normalized and path_normalized in existing_files_normalized))
                ):
                    blocked_hint = ""
                    for f, summary in _latest_file_summaries.items():
                        if _normalize_path(f) == path_normalized:
                            blocked_hint = f"\nKey content from your earlier read: {summary}"
                            break
                    tool_results.append(ToolMessage(
                        content=f"[BLOCKED] {path} is ALREADY in your context from a previous read_file call. "
                                f"You MUST use that content. Re-reading is forbidden and wastes your iteration budget. "
                                f"Check your earlier messages for the full content."
                                f" If you need exact missing lines, call read_file once with offset/limit."
                                f"{blocked_hint}",
                        tool_call_id=tool_id,
                    ))
                    continue

            if tool_name in ("glob", "grep"):
                pattern = tool_args.get("pattern", "")
                path = tool_args.get("path", "")
                seen_key = f"{tool_name}:{pattern}:{path}"
                same_pattern_count = sum(1 for k in tool_ctx.seen_patterns if k == seen_key)
                tool_ctx.seen_patterns.add(seen_key)
                call_count = sum(1 for k in tool_ctx.seen_patterns if k.startswith(f"{tool_name}:"))
                same_pattern_limit = 4 if deep_context else 2
                search_call_limit = DEEP_SEARCH_CALL_LIMIT if deep_context else DEFAULT_SEARCH_CALL_LIMIT
                if same_pattern_count >= same_pattern_limit:
                    tool_results.append(ToolMessage(
                        content=f"[Blocked] You've called {tool_name} with pattern='{pattern}' "
                                f"{same_pattern_count} times. It keeps returning the same results. "
                                f"Try a DIFFERENT, more specific pattern, or summarize from what you have. "
                                f"Do NOT fall back to run_shell — it will also be BLOCKED for search commands.",
                        tool_call_id=tool_id,
                    ))
                    continue
                if call_count > search_call_limit:
                    tool_results.append(ToolMessage(
                        content=f"[Blocked] Too many {tool_name} calls ({call_count}). "
                                f"Stop searching and answer from what you have. "
                                f"Do NOT fall back to run_shell — search commands are BLOCKED.",
                        tool_call_id=tool_id,
                    ))
                    continue

            if tool_name == "run_shell":
                cmd = tool_args.get("command", "")
                if isinstance(cmd, str):
                    shell_call_limit = DEEP_SHELL_CALL_LIMIT if deep_context else DEFAULT_SHELL_CALL_LIMIT
                    if prior_run_shell_count > shell_call_limit:
                        tool_results.append(ToolMessage(
                            content="[BLOCKED] Too many run_shell calls. "
                                    "You have used run_shell excessively. Switch to dedicated tools "
                                    "(grep, glob, read_file) or summarize what you have.",
                            tool_call_id=tool_id,
                        ))
                        continue
                    is_search, search_msg = _is_search_command(cmd)
                    if is_search and not user_confirmed:
                        tool_results.append(ToolMessage(
                            content=f"[BLOCKED] run_shell with search command is forbidden. {search_msg}",
                            tool_call_id=tool_id,
                        ))
                        continue
                    if user_confirmed:
                        tool_args = {**tool_args, "allow_search_commands": True}

                    cat_match = None
                    cmd_stripped = cmd.strip()
                    if cmd_stripped.startswith("cat "):
                        parts = cmd_stripped.split()
                        for p in parts[1:]:
                            if not p.startswith("-"):
                                cat_match = p
                                break
                    elif cmd_stripped.startswith("sed "):
                        parts = cmd_stripped.split()
                        if len(parts) >= 3 and not parts[-1].startswith("'") and not parts[-1].startswith("-"):
                            cat_match = parts[-1]

                    if cat_match and (_normalize_path(cat_match) in existing_files_normalized or cat_match in existing_files):
                        tool_results.append(ToolMessage(
                            content=f"[BLOCKED] {cat_match} is already in context. "
                                    f"Use read_file content you already have, not run_shell.",
                            tool_call_id=tool_id,
                        ))
                        continue

            if tool_name not in tools_by_name:
                tool_results.append(ToolMessage(
                    content=f"Error: Unknown tool '{tool_name}'",
                    tool_call_id=tool_id,
                ))
                continue

            tool = tools_by_name[tool_name]
            try:
                if tool_name == "todo_write":
                    tool_args["session_id"] = state.get("session_id", "")

                pm = get_plugin_manager()
                if pm.has_hooks(HookType.TOOL_EXECUTE_BEFORE):
                    hooked = pm.emit(
                        HookType.TOOL_EXECUTE_BEFORE,
                        {
                            "tool_name": tool_name,
                            "args": tool_args,
                            "state": state,
                        },
                    )
                    tool_args = hooked.get("args", tool_args)

                    # Re-check permissions after hook may have modified args
                    perm_after = permissions.evaluate(tool_name, tool_args)
                    if perm_after == "deny":
                        tool_results.append(ToolMessage(
                            content=f"[Permission denied] {tool_name} args modified by hook failed permission check.",
                            tool_call_id=tool_id,
                        ))
                        continue

                result = tool.invoke(tool_args)

                if pm.has_hooks(HookType.TOOL_EXECUTE_AFTER):
                    hooked = pm.emit(
                        HookType.TOOL_EXECUTE_AFTER,
                        {
                            "tool_name": tool_name,
                            "args": tool_args,
                            "result": result,
                            "state": state,
                        },
                    )
                    result = hooked.get("result", result)

                tool_results.append(ToolMessage(content=result, tool_call_id=tool_id))

                if tool_name == "read_file" and not result.startswith("Error"):
                    path = tool_args.get("path", "")
                    if path and path not in existing_files:
                        new_files.append(path)
                        existing_files.add(path)
                        existing_files_normalized.add(_normalize_path(path))
            except Exception as e:
                tool_results.append(ToolMessage(
                    content=f"Error executing {tool_name}: {e}",
                    tool_call_id=tool_id,
                ))

        tool_results = context_manager.compress_tool_results(tool_results)
        update = {"messages": tool_results}
        if new_files != list(state.get("files_context", [])):
            update["files_context"] = new_files
        return update

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if not (isinstance(last_message, AIMessage) and last_message.tool_calls):
            return END

        iteration_count, total_tool_invocations = _tool_round_count(state["messages"])

        if total_tool_invocations > HARD_ITERATION_LIMIT:
            return "force_end"

        task_type = state.get("task_type", "")
        effective_limit = TASK_ITERATION_LIMITS.get(task_type, iteration_limit)
        if iteration_count > effective_limit:
            return "summarize"

        return "tools"

    def summarize_node(state: AgentState) -> dict:
        task_type = state.get("task_type", "")
        iteration_limit_val = TASK_ITERATION_LIMITS.get(task_type, iteration_limit)
        if task_type == "test_evaluation":
            content = (
                f"[System: 已达迭代上限（{iteration_limit_val} 轮工具调用）。"
                "这是测试/评估任务：只能基于已经出现的真实工具结果总结。"
                "如果没有看到实际命令输出、退出码或工具结果，不要产出通过/失败结论，"
                "必须明确标记为“未完成验证”，并列出缺失的命令或结果。"
                "不要再调用工具，也不要要求用户重置迭代上限或稍后 ping 你。]"
            )
        else:
            content = (
                f"[System: 已达迭代上限（{iteration_limit_val} 轮工具调用）。"
                "请根据已收集的信息给出尽可能完整的当前结论、已完成项、未完成项和下一步。"
                "不要再调用工具，也不要要求用户重置迭代上限或稍后 ping 你。]"
            )
        hint = HumanMessage(
            content=content
        )
        messages = validate_message_pairs(state["messages"])
        messages = messages + [hint]
        response = llm.invoke(messages)
        return {"messages": [hint, response]}

    def force_end_node(state: AgentState) -> dict:
        return {"messages": [AIMessage(
            content="[System: 已达硬性迭代上限，强制终止。请根据以上信息总结结果。]"
        )]}

    graph = StateGraph(AgentState)
    if agent_def.workflow == "plan_execute":
        graph.add_node("planner", planner_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("force_end", force_end_node)
    if agent_def.workflow == "plan_execute":
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "agent")
    else:
        graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools", "summarize": "summarize", "force_end": "force_end", END: END
    })
    graph.add_edge("tools", "agent")
    graph.add_edge("summarize", END)
    graph.add_edge("force_end", END)

    return graph.compile()


def graph_recursion_limit() -> int:
    """Return the runtime recursion limit used by top-level graph invocations."""
    return GRAPH_RECURSION_LIMIT
