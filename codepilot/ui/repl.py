from __future__ import annotations

import os
import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import ThreadedCompleter, WordCompleter, merge_completers
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel

from codepilot.agent._utils import validate_message_pairs
from codepilot.context.selector import parse_references
from codepilot.ui.completer import AtFileCompleter, FileIndex
from codepilot.ui.commands import SLASH_COMMANDS, CommandHandler
from codepilot.ui.intent import (
    build_post_task_prompt,
    chat_response,
    classify_intent_with_context,
    classify_task,
    expand_choice_reply,
    expand_numbered_choice_reply,
    greeting_response,
)
from codepilot.ui.permissions import PermissionHandler, prompt_permission_choice
from codepilot.ui.renderer import Renderer
from codepilot.utils.token_usage import TokenUsageAccumulator, extract_token_usage


TOOL_ERROR_PREFIXES = (
    "error:",
    "error ",
    "[error]",
    "[blocked]",
    "blocked:",
    "[permission denied]",
    "permission denied",
)


def tool_result_status(tool_name: str, content: str) -> str:
    """Classify a tool result for UI rendering."""
    text = str(content or "").strip().lower()
    if text.startswith(("[blocked]", "blocked:")):
        return "blocked"
    return "error" if is_tool_result_error(tool_name, content) else "success"


def is_tool_result_error(tool_name: str, content: str) -> bool:
    """Return true only for explicit tool failure signals, not matched source text."""
    text = str(content or "").strip()
    if not text:
        return False

    lower = text.lower()
    if lower.startswith(TOOL_ERROR_PREFIXES):
        return True
    if "permission denied by user" in lower:
        return True

    if tool_name == "run_shell":
        for line in lower.splitlines():
            line = line.strip()
            if not line.startswith("exit code:"):
                continue
            code = line.removeprefix("exit code:").strip().split(maxsplit=1)[0]
            return code != "0"
        return lower.startswith(("command failed", "command timed out"))

    return False


def resolve_tool_message(tool_calls_by_id: dict[str, dict], msg: ToolMessage) -> tuple[str, dict, dict]:
    """Resolve a ToolMessage back to its tool call metadata."""
    tc_info = tool_calls_by_id.pop(msg.tool_call_id, {})
    tool_name = tc_info.get("name") or getattr(msg, "name", None) or "unknown"
    tool_args = tc_info.get("args", {})
    return tool_name, tool_args, tc_info


def token_display_for_tool_call(round_tokens: int, tool_call_index: int) -> int:
    """Display model-round token usage on the first tool call only."""
    return round_tokens if tool_call_index == 0 else 0


class REPL:
    def __init__(
        self,
        graph,
        llm=None,
        model: str = "",
        context_window: int | None = None,
        agent_name: str = "build",
        storage=None,
        session_id: str | None = None,
        registry=None,
    ) -> None:
        self.graph = graph
        self.llm = llm
        self.model = model
        self.agent_name = agent_name
        self.renderer = Renderer()
        self.console = Console()
        self.messages: list[BaseMessage] = []
        self.file_stack: list[tuple[str, str]] = []
        self._trace_enabled: bool = os.environ.get("LANGSMITH_TRACING") == "true"
        self.storage = storage
        self._session_id = session_id
        self.registry = registry
        self._cmd_handler = CommandHandler(self)

        from codepilot.agent.registry import AgentRegistry
        self._agent_def = AgentRegistry().get_or_default(agent_name)
        self.permission = PermissionHandler(ruleset=self._agent_def.permissions, ask_fn=self._ask_permission)

        if context_window and context_window > 0:
            self._context_window = context_window
        else:
            from codepilot.config.context_windows import get_usable_context, parse_model_spec
            raw_model_name = model.split("/", 1)[-1] if "/" in model else model
            clean_name, suffix_ctx = parse_model_spec(raw_model_name)
            self._context_window = get_usable_context(clean_name, suffix_ctx)

        self._task_tokens: int = 0
        self._task_input_tokens: int = 0
        self._task_output_tokens: int = 0
        self._task_token_accumulator = TokenUsageAccumulator()
        self._task_tools: int = 0
        self._task_tool_names: list[str] = []
        self._task_denied_count: int = 0
        self._task_iteration_count: int = 0
        self._task_steps: int = 0
        self._task_user_input: str = ""
        self._task_had_error: bool = False
        self._task_start: float = 0
        self._task_did_edit: bool = False
        self._task_did_test: bool = False
        self._task_tests_passed: bool | None = None
        self._task_permission_wait_count: int = 0
        self._task_first_tool_at: float = 0
        self._task_first_visible_at: float = 0
        self._task_effective_agent: str = agent_name
        self._active_activity = None
        self._activity_paused_for_prompt = False

        self._recent_tool_calls: list[tuple[str, str]] = []

        self._context_tokens: int = 0
        self._context_messages: int = 0
        self._files_context: list[str] = []

        self._graph_cache_key: tuple | None = None
        self._init_session()

    @property
    def _confirm_label(self) -> str:
        if self._agent_def.is_readonly:
            return "readonly"
        return "confirm" if self._agent_def.confirm else "auto"

    def _init_session(self) -> None:
        from codepilot.storage.db import Storage, new_session_id
        from codepilot.storage.models import SessionInfo
        from codepilot.storage.resume import load_messages

        if self.storage is None:
            self.storage = Storage()

        if self._session_id:
            existing = self.storage.get_session(self._session_id)
            if existing:
                self.messages = load_messages(self.storage, self._session_id)
                self.agent_name = existing.agent
                from codepilot.agent.registry import AgentRegistry
                self._agent_def = AgentRegistry().get_or_default(self.agent_name)
                self.permission.set_ruleset(self._agent_def.permissions)
                self._update_context_stats()
            else:
                self._session_id = None

        if not self._session_id:
            self._session_id = new_session_id()
            session_info = SessionInfo(
                id=self._session_id,
                title="New Session",
                agent=self.agent_name,
                model=self.model,
                mode=self._confirm_label,
            )
            self.storage.create_session(session_info)

    def _persist_messages(self) -> None:
        if not self.storage or not self._session_id:
            return
        try:
            from codepilot.plugins.manager import HookType, get_plugin_manager
            from codepilot.storage.resume import save_messages

            pm = get_plugin_manager()
            if pm.has_hooks(HookType.MESSAGE_BEFORE_SAVE):
                for msg in self.messages:
                    hooked = pm.emit(
                        HookType.MESSAGE_BEFORE_SAVE,
                        {"message": msg},
                    )
                    msg = hooked.get("message", msg)

            save_messages(self.storage, self.messages, self._session_id)
            self.storage.update_session(
                self._session_id,
                message_count=len(self.messages),
            )
        except Exception:
            pass

    def run(self) -> None:
        history_file = os.path.expanduser("~/.codepilot/history")
        os.makedirs(os.path.dirname(history_file), exist_ok=True)

        self._file_index = FileIndex(working_dir=os.getcwd())
        slash_completer = WordCompleter(list(SLASH_COMMANDS.keys()), WORD=True)
        at_file_completer = AtFileCompleter(self._file_index)
        completer = ThreadedCompleter(merge_completers([slash_completer, at_file_completer]))

        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            buffer = event.app.current_buffer
            state = buffer.complete_state
            if state and state.completions:
                completion = state.current_completion
                if completion and completion.text.startswith("@"):
                    buffer.apply_completion(completion)
                    return
                for c in state.completions:
                    if c.text.startswith("@"):
                        buffer.apply_completion(c)
                        return
            buffer.validate_and_handle()

        session: PromptSession = PromptSession(
            history=FileHistory(history_file),
            completer=completer,
            complete_while_typing=True,
            key_bindings=kb,
        )

        def _on_completions_changed(buf):
            state = buf.complete_state
            if not state or not state.completions:
                return
            if state.complete_index is not None:
                return
            for i, c in enumerate(state.completions):
                if c.text.startswith("@"):
                    state.go_to_index(i)
                    break

        session.default_buffer.on_completions_changed += _on_completions_changed

        self._print_welcome()

        while True:
            try:
                user_input = session.prompt(f"[{self.agent_name}:{self._confirm_label}] > ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]Goodbye![/dim]")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                if self._handle_command(user_input):
                    break
                continue

            clean_input, ref_content = parse_references(user_input)
            clean_input = expand_choice_reply(clean_input, self.messages)
            full_input = clean_input
            if ref_content:
                full_input = f"{clean_input}\n\n--- Referenced content ---\n{ref_content}"

            intent = classify_intent_with_context(full_input, self.messages)
            if intent == "greeting":
                response = greeting_response(full_input)
                self.console.print(response)
                self.messages.extend([HumanMessage(content=full_input), AIMessage(content=response)])
                continue
            if intent == "chat":
                response = chat_response(full_input)
                self.console.print(response)
                self.messages.extend([HumanMessage(content=full_input), AIMessage(content=response)])
                continue

            self.messages.append(HumanMessage(content=full_input))

            self._task_start = time.time()
            self._task_tokens = 0
            self._task_input_tokens = 0
            self._task_output_tokens = 0
            self._task_token_accumulator = TokenUsageAccumulator()
            self._task_tools = 0
            self._task_tool_names.clear()
            self._task_denied_count = 0
            self._task_iteration_count = 0
            self._task_user_input = clean_input
            self._task_had_error = False
            self._task_did_edit = False
            self._task_did_test = False
            self._task_tests_passed = None
            self._task_permission_wait_count = 0
            self._task_first_tool_at = 0
            self._task_first_visible_at = 0
            self._recent_tool_calls.clear()

            try:
                intent = classify_intent_with_context(clean_input, self.messages)
                if intent == "greeting":
                    self._handle_greeting()
                elif intent == "chat":
                    self._handle_chat()
                else:
                    self._run_agent()
            except Exception as e:
                self._task_had_error = True
                err_msg = str(e)
                if "GraphRecursionError" in err_msg or "recursion_limit" in err_msg:
                    self.console.print("\n[yellow]已达迭代上限，Agent 已停止。输入继续对话。[/yellow]")
                else:
                    self.renderer.render_error(err_msg)
            finally:
                self._report_task_to_langsmith()
                self._update_context_stats()

            elapsed = time.time() - self._task_start
            if self._task_tools > 0:
                outcome = self._task_outcome(elapsed)
                self.renderer.render_task_summary(
                    elapsed,
                    self._task_tokens,
                    self._task_tools,
                    self._task_steps,
                    outcome=outcome,
                    input_tokens=self._task_input_tokens,
                    output_tokens=self._task_output_tokens,
                )
                self._render_post_task_suggestions(outcome)

            if self._context_tokens > 0:
                self._show_context_bar()

    def _print_welcome(self) -> None:
        from codepilot.agent.registry import AgentRegistry
        registry = AgentRegistry()
        agent_def = registry.get_or_default(self.agent_name)
        self.console.print(Panel.fit(
            "[bold]CodePilot[/bold] - AI 编程助手\n"
            f"模型: {self.model} | Agent: {agent_def.display_name} | 模式: {self._confirm_label} | 上下文: {self._context_window:,} tokens\n"
            f"会话: {self._session_id[:8]}...\n"
            "输入 /help 查看命令, /agent 切换Agent, /quit 退出",
            border_style="green",
        ))

    def _extract_tokens(self, msg: AIMessage) -> int:
        return extract_token_usage(msg).total_tokens

    def _estimate_context_tokens(self) -> int:
        total_chars = 0
        for msg in self.messages:
            content = getattr(msg, "content", None)
            if content:
                total_chars += len(content)
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    total_chars += len(str(tc.get("name", "")))
                    total_chars += len(str(tc.get("args", {})))
        return total_chars // 4

    def _update_context_stats(self) -> None:
        self._context_tokens = self._estimate_context_tokens()
        self._context_messages = len(self.messages)

    def _get_or_build_graph(self, context_window: int | None = None):
        """Return a compiled graph, rebuilding only when key inputs change."""
        from codepilot.agent.graph import build_agent_graph

        cw = context_window if context_window is not None else self._context_window
        graph_agent_name = getattr(self, "_task_effective_agent", self.agent_name)
        cache_key = (
            id(self.llm),
            graph_agent_name,
            cw,
            id(self.permission.ruleset),
        )
        if self._graph_cache_key == cache_key and self.graph is not None:
            return self.graph
        self.graph = build_agent_graph(
            self.llm,
            agent_name=graph_agent_name,
            context_window=cw,
            ask_permission_callback=self.permission.check_permission,
            storage=self.storage,
        )
        self._graph_cache_key = cache_key
        return self.graph

    def _ask_permission(self, _ruleset_name: str, tool_name: str, tool_args: dict) -> bool:
        self._task_permission_wait_count += 1
        self._pause_activity_for_prompt()
        try:
            self.renderer.render_choice(tool_name, tool_args)

            choice = prompt_permission_choice()
            if choice == "allow":
                self.renderer.render_permission_result(tool_name, allowed=True)
                return True
            if choice == "always":
                self.permission.allowed_tools.add(tool_name)
                self.renderer.render_permission_result(tool_name, allowed=True, always=True)
                return True
            self.renderer.render_permission_result(tool_name, allowed=False)
            return False
        finally:
            self._resume_activity_after_prompt()

    def _pause_activity_for_prompt(self) -> None:
        if self._active_activity is None or self._activity_paused_for_prompt:
            return
        self.renderer.stop_activity(self._active_activity)
        self._activity_paused_for_prompt = True

    def _resume_activity_after_prompt(self) -> None:
        if self._active_activity is None or not self._activity_paused_for_prompt:
            return
        self.renderer.resume_activity(self._active_activity, "已收到确认，继续执行工具...")
        self._activity_paused_for_prompt = False

    def _run_agent(self) -> None:
        from codepilot.agent.graph import graph_recursion_limit
        from codepilot.agent.registry import AgentRegistry
        from codepilot.agent.router import select_agent_for_task

        task_type = classify_task(self._task_user_input)
        effective_agent = select_agent_for_task(self._task_user_input, task_type, self.agent_name)
        self._task_effective_agent = effective_agent
        effective_def = AgentRegistry().get_or_default(effective_agent)
        route_label = (
            f"{effective_agent} (auto)"
            if self.agent_name == "auto" and effective_agent != self.agent_name
            else effective_agent
        )

        self.renderer.render_task_start(
            self._task_user_input,
            model=self.model,
            agent_name=route_label,
            mode=self._confirm_label,
        )
        self.renderer.render_waiting()
        self._task_first_visible_at = time.time()
        self._inject_dedup_hint()
        self._get_or_build_graph()

        new_messages: list[BaseMessage] = []
        tool_calls_by_id: dict[str, dict] = {}
        tool_start: float = 0

        callbacks = []
        if self._trace_enabled:
            try:
                from langchain_core.tracers import LangChainTracer
                tracer = LangChainTracer(
                    project_name=os.environ.get("LANGSMITH_PROJECT", "codepilot"),
                )
                callbacks.append(tracer)
            except Exception:
                pass

        # Capture the root run synchronously via collect_runs so we can attach
        # task_metrics without polling LangSmith (which is async/batched and
        # frequently misses the run when queried right after the stream ends).
        run_collector_cm = None
        run_collector_handler = None
        if self._trace_enabled:
            try:
                from langchain_core.tracers.context import collect_runs as _collect_runs
                run_collector_cm = _collect_runs()
                run_collector_handler = run_collector_cm.__enter__()
            except Exception:
                run_collector_cm = None
                run_collector_handler = None
        self._task_run_collector_cm = run_collector_cm
        self._task_run_collector = run_collector_handler
        self._task_root_run_id = None

        step = 0
        current_phase = ""
        activity = self.renderer.start_activity("正在请求模型，等待第一步计划...")
        self._active_activity = activity

        for event in self._stream_with_activity(self.graph.stream(
            {
                "messages": self._validate_messages_for_api(list(self.messages)),
                "working_dir": os.getcwd(),
                "files_context": list(self._files_context),
                "task_type": task_type,
                "agent_name": effective_agent,
                "session_id": self._session_id or "",
            },
            config={
                "recursion_limit": graph_recursion_limit(),
                "run_name": task_type,
                "callbacks": callbacks,
                "metadata": {
                    "model": self.model,
                    "session_id": self._session_id or "",
                    "agent_name": effective_agent,
                    "requested_agent": self.agent_name,
                    "workflow": effective_def.workflow,
                    "confirm": self._confirm_label,
                    "task_type": task_type,
                    "user_input_preview": self._task_user_input[:200],
                },
                "tags": [
                    f"agent:{effective_agent}",
                    f"requested_agent:{self.agent_name}",
                    f"workflow:{effective_def.workflow}",
                    f"confirm:{self._confirm_label}",
                    f"model:{self.model}",
                    f"task_type:{task_type}",
                    "prompt:v7",
                ],
            },
        ), activity):
            for node_name, node_state in event.items():
                if "messages" not in node_state:
                    continue

                for msg in node_state["messages"]:
                    if isinstance(msg, AIMessage):
                        self._update_activity(activity, "模型已返回下一步，正在处理...")
                        usage = self._task_token_accumulator.add_message(msg)
                        tokens_used = usage.total_tokens
                        self._task_tokens = self._task_token_accumulator.total.total_tokens
                        self._task_input_tokens = self._task_token_accumulator.total.input_tokens
                        self._task_output_tokens = self._task_token_accumulator.total.output_tokens

                        if msg.tool_calls:
                            self._task_iteration_count += 1
                            tool_start = time.time()
                            if not self._task_first_tool_at:
                                self._task_first_tool_at = tool_start
                            for tool_call_index, tc in enumerate(msg.tool_calls):
                                step += 1
                                tool_calls_by_id[tc["id"]] = {
                                    "name": tc["name"],
                                    "args": tc.get("args", {}),
                                    "step": step,
                                }
                                tool_name = tc["name"]
                                tool_args = tc.get("args", {})

                                self._update_activity(
                                    activity,
                                    f"准备{self.renderer.infer_phase(tool_name, tool_args)}...",
                                )
                                self.renderer.render_tool_call(
                                    tool_name,
                                    tool_args,
                                    step=step,
                                    elapsed=0,
                                    tokens=token_display_for_tool_call(tokens_used, tool_call_index),
                                )
                                self._update_activity(activity, "等待工具执行结果...")

                        elif msg.content:
                            self._update_activity(activity, "正在输出最终回复...")
                            if current_phase != "summary":
                                current_phase = "summary"
                                self.renderer.render_phase_header("总结与下一步")
                            self.renderer.render_message(msg.content)
                            self.renderer.render_model_usage(
                                "最终回复",
                                total_tokens=usage.total_tokens,
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                            )

                        new_messages.append(msg)

                    elif isinstance(msg, ToolMessage):
                        self._update_activity(activity, "收到工具结果，正在整理下一步...")
                        elapsed = time.time() - tool_start if tool_start else 0
                        self._task_tools += 1

                        tool_name, tool_args, _tc_info = resolve_tool_message(tool_calls_by_id, msg)

                        status = tool_result_status(tool_name, msg.content)
                        is_error = status in {"error", "blocked"}

                        self.renderer.render_tool_result(
                            tool_name,
                            msg.content,
                            elapsed=elapsed,
                            success=not is_error,
                            status=status,
                        )

                        if tool_name == "edit_file" and not is_error:
                            self._task_did_edit = True
                            old_str = tool_args.get("old_str", "")
                            new_str = tool_args.get("new_str", "")
                            path = tool_args.get("path", "")
                            if old_str and new_str:
                                self.renderer.render_edit_diff(old_str, new_str, path)
                            if path:
                                try:
                                    original = open(path).read()
                                    self.file_stack.append((path, original))
                                except Exception:
                                    pass

                        if tool_name == "write_file" and not is_error:
                            self._task_did_edit = True
                            path = tool_args.get("path", "")
                            if path:
                                try:
                                    from pathlib import Path
                                    p = Path(path).expanduser()
                                    if not p.is_absolute():
                                        p = Path(os.getcwd()) / p
                                    if p.exists():
                                        original = p.read_text()
                                        self.file_stack.append((str(p), original))
                                except Exception:
                                    pass

                        new_messages.append(msg)

                        content_str = msg.content if isinstance(msg.content, str) else ""
                        if (
                            tool_name == "read_file"
                            and not content_str.startswith("[Blocked]")
                            and not content_str.startswith("Error")
                        ):
                            path = tool_args.get("path", "")
                            if path and path not in self._files_context:
                                self._files_context.append(path)

                        self._task_tool_names.append(tool_name)
                        self._update_task_verification(tool_name, tool_args, content_str, is_error)

                        args_summary = str(tool_args)[:100]
                        self._recent_tool_calls.append((tool_name, args_summary))
                        if len(self._recent_tool_calls) > 20:
                            self._recent_tool_calls = self._recent_tool_calls[-20:]

        self._task_steps = step
        self.messages.extend(new_messages)
        self._update_context_stats()

        if self._context_tokens >= self._context_window * 0.9:
            self.console.print("\n[yellow]⚠ 上下文接近上限，自动压缩...[/yellow]")
            self._compact_messages()

        self._persist_messages()

    def _update_activity(self, activity, message: str) -> None:
        self._active_activity = activity
        if self._activity_paused_for_prompt:
            return
        self.renderer.update_activity(activity, message)

    def _handle_command(self, cmd: str) -> bool:
        return self._cmd_handler.handle(cmd)

    def _validate_messages_for_api(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        return validate_message_pairs(messages)

    def _stream_with_activity(self, stream, activity):
        try:
            for event in stream:
                yield event
        finally:
            self.renderer.stop_activity(activity)
            if self._active_activity is activity:
                self._active_activity = None
                self._activity_paused_for_prompt = False

    def _inject_dedup_hint(self) -> None:
        if not self._recent_tool_calls:
            return

        from collections import Counter
        call_counts = Counter(self._recent_tool_calls)
        for (tool_name, args_summary), count in call_counts.items():
            if count >= 3:
                hint = f"[System: 你已经调用 {tool_name}({args_summary}) {count} 次，不要再重复，换一种方式。]"
                self.messages.append(HumanMessage(content=hint))
                break

    def _compact_messages(self) -> None:
        if len(self.messages) <= 4:
            self.console.print("[dim]消息不足，无需压缩[/dim]")
            return

        kept_count = 6
        recent = self.messages[-kept_count:]

        for i, msg in enumerate(self.messages[:-kept_count]):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                tc_ids = {tc["id"] for tc in msg.tool_calls}
                for r in recent:
                    if isinstance(r, ToolMessage) and r.tool_call_id in tc_ids:
                        kept_count = len(self.messages) - i
                        recent = self.messages[-kept_count:]
                        break

        compressed_kept = []
        for msg in recent:
            if isinstance(msg, ToolMessage) and len(msg.content) > 500:
                first_line = msg.content.strip().split("\n")[0]
                total = len(msg.content.split("\n"))
                compressed_kept.append(ToolMessage(
                    content=f"{first_line}\n... ({total} lines)",
                    tool_call_id=msg.tool_call_id,
                ))
            else:
                compressed_kept.append(msg)

        older_count = len(self.messages) - kept_count
        tool_count = sum(1 for m in self.messages[:-kept_count] if isinstance(m, ToolMessage))

        original_request = ""
        for m in self.messages[:-kept_count]:
            if isinstance(m, HumanMessage) and not m.content.startswith("[Previous context:"):
                original_request = m.content[:200]
                break

        summary_parts = [f"[Previous context: {older_count} messages, {tool_count} tool results removed"]
        if original_request:
            summary_parts.append(f"Original user request: {original_request}")
        summary_parts.append("Continue the task from where you left off.]")
        summary = "\n".join(summary_parts)
        self.messages = self._validate_messages_for_api([HumanMessage(content=summary)] + compressed_kept)
        self._update_context_stats()
        self.console.print(f"[green]已压缩 ({older_count} 条消息)[/green]")
        self._show_context_bar()

    def _show_context_bar(self) -> None:
        pct = self._context_tokens / self._context_window
        if pct >= 0.8:
            color = "red"
        elif pct >= 0.5:
            color = "yellow"
        else:
            color = "green"

        bar_width = 20
        filled = int(pct * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        self.console.print(
            f"  [dim]上下文[/dim] [{color}]{bar}[/{color}] "
            f"[dim]{self._context_tokens:,} / {self._context_window:,} tokens "
            f"({pct:.0%}) | {self._context_messages} 条消息[/dim]"
        )

        if pct >= 0.85:
            self.console.print("  [yellow]⚠ 上下文接近上限，建议输入 /compact 压缩[/yellow]")

    def _show_context_detail(self) -> None:
        from codepilot.config.context_windows import RESERVE_RATIO, get_context_window, parse_model_spec

        raw_model_name = self.model.split("/", 1)[-1] if "/" in self.model else self.model
        clean_name, suffix_ctx = parse_model_spec(raw_model_name)
        total_window = get_context_window(clean_name, suffix_ctx)
        reserve = int(total_window * RESERVE_RATIO)

        pct = self._context_tokens / self._context_window

        human_count = sum(1 for m in self.messages if isinstance(m, HumanMessage))
        ai_count = sum(1 for m in self.messages if isinstance(m, AIMessage))
        tool_count = sum(1 for m in self.messages if isinstance(m, ToolMessage))

        human_tokens = sum(len(m.content) // 4 for m in self.messages if isinstance(m, HumanMessage) and m.content)
        ai_tokens = sum(len(m.content) // 4 for m in self.messages if isinstance(m, AIMessage) and m.content)
        tool_tokens = sum(len(m.content) // 4 for m in self.messages if isinstance(m, ToolMessage) and m.content)

        if pct >= 0.8:
            color = "red"
        elif pct >= 0.5:
            color = "yellow"
        else:
            color = "green"

        bar_width = 30
        filled = int(pct * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        self.console.print()
        self.console.print(f"[bold]上下文使用情况[/bold]  [dim]模型: {self.model}[/dim]")
        self.console.print(f"[{color}]{bar}[/{color}] {pct:.0%}")
        self.console.print()

        from rich.table import Table
        table = Table(show_header=True, box=None, padding=(0, 2))
        table.add_column("类型", style="dim")
        table.add_column("消息数", justify="right")
        table.add_column("估算 tokens", justify="right")
        table.add_column("占比", justify="right", style="dim")

        total = max(self._context_tokens, 1)
        table.add_row("用户消息", str(human_count), f"{human_tokens:,}", f"{human_tokens / total:.0%}")
        table.add_row("AI 回复", str(ai_count), f"{ai_tokens:,}", f"{ai_tokens / total:.0%}")
        table.add_row("工具结果", str(tool_count), f"{tool_tokens:,}", f"{tool_tokens / total:.0%}")
        table.add_row("[bold]消息合计[/bold]", str(self._context_messages), f"[bold]{self._context_tokens:,}[/bold]", "")
        self.console.print(table)
        self.console.print()

        info_table = Table(show_header=True, box=None, padding=(0, 2))
        info_table.add_column("", style="dim")
        info_table.add_column("", justify="right")
        info_table.add_row("模型上下文窗口", f"{total_window:,} tokens")
        info_table.add_row("预留响应空间", f"{reserve:,} tokens ({RESERVE_RATIO:.0%})")
        info_table.add_row("[bold]可用上下文[/bold]", f"[bold]{self._context_window:,} tokens[/bold]")
        info_table.add_row("已使用", f"{self._context_tokens:,} tokens ({pct:.0%})")
        info_table.add_row("剩余空间", f"{max(0, self._context_window - self._context_tokens):,} tokens")
        self.console.print(info_table)

        if pct >= 0.85:
            self.console.print("\n[yellow]⚠ 上下文接近上限！建议：[/yellow]")
            self.console.print("[dim]  /compact  — 压缩历史消息，保留最近上下文[/dim]")
            self.console.print("[dim]  /clear    — 清除所有上下文，重新开始[/dim]")
        elif pct >= 0.6:
            self.console.print("\n[dim]💡 上下文使用较多，可输入 /compact 压缩[/dim]")
        else:
            self.console.print("\n[dim]💡 上下文充裕[/dim]")

        self.console.print()

    def _handle_greeting(self) -> None:
        from langchain_core.messages import AIMessage

        reply = greeting_response(self._task_user_input)
        self.renderer.render_message(reply)
        self.messages.append(AIMessage(content=reply))

    def _handle_chat(self) -> None:
        from langchain_core.messages import AIMessage

        reply = chat_response(self._task_user_input)
        self.renderer.render_message(reply)
        self.messages.append(AIMessage(content=reply))

    def _render_post_task_suggestions(self, outcome: str) -> None:
        """Show a numbered next-step menu after a coding task completes.

        Persists the menu as the trailing AI message so the next user turn —
        even a brief reply like ``好的`` or ``2`` — gets routed back through the
        agent instead of the canned greeting/chat responses.
        """
        if outcome in {"no_op"}:
            return

        task_type = classify_task(self._task_user_input or "")
        use_chinese = self._reply_in_chinese()
        prompt = build_post_task_prompt(task_type, outcome, use_chinese=use_chinese)
        if not prompt:
            return

        self.console.print()
        self.console.print(prompt)

        if self.messages and isinstance(self.messages[-1], AIMessage):
            existing = self.messages[-1]
            existing_content = existing.content if isinstance(existing.content, str) else ""
            joined = f"{existing_content}\n\n{prompt}" if existing_content else prompt
            self.messages[-1] = AIMessage(content=joined)
        else:
            self.messages.append(AIMessage(content=prompt))
        self._update_context_stats()
        self._persist_messages()

    def _reply_in_chinese(self) -> bool:
        text = (self._task_user_input or "").strip()
        if not text:
            return True
        return any("一" <= c <= "鿿" for c in text)

    def _update_task_verification(
        self,
        tool_name: str,
        tool_args: dict,
        content: str,
        is_error: bool,
    ) -> None:
        if tool_name != "run_shell":
            return
        command = str(tool_args.get("command", "")).lower()
        if not any(hint in command for hint in ("pytest", "test", "ruff", "mypy", "tox")):
            return

        self._task_did_test = True
        lower = content.lower()
        if is_error or " failed" in lower or "failed," in lower or "exit code:" in lower:
            self._task_tests_passed = False
        elif " passed" in lower or " passed in " in lower or "all checks passed" in lower:
            self._task_tests_passed = True

    def _task_outcome(self, elapsed: float | None = None) -> str:
        if elapsed is not None and elapsed < 1.0 and self._task_tools == 0:
            return "partial"
        if self._task_had_error:
            return "error"
        if self._task_tools == 0 and self._task_iteration_count == 0:
            return "no_op"
        from codepilot.agent.nodes import TASK_ITERATION_LIMITS

        task_type = classify_task(self._task_user_input)
        task_limit = TASK_ITERATION_LIMITS.get(task_type)
        if task_limit is not None and self._task_iteration_count > task_limit:
            return "timeout"
        if self._task_did_test and self._task_tests_passed is False:
            return "partial"
        return "success"

    def _report_task_to_langsmith(self) -> None:
        # Always close the collect_runs context if it was opened, even when
        # tracing is disabled mid-task or the run aborted before _run_agent
        # returned. Capture the root run id from traced_runs to skip the
        # racy list_runs() poll.
        if getattr(self, "_task_run_collector_cm", None) is not None:
            try:
                self._task_run_collector_cm.__exit__(None, None, None)
                handler = getattr(self, "_task_run_collector", None)
                traced = getattr(handler, "traced_runs", None) if handler else None
                if traced:
                    self._task_root_run_id = str(traced[0].id)
            except Exception:
                pass
            finally:
                self._task_run_collector_cm = None
                self._task_run_collector = None

        if not self._trace_enabled or self._task_start == 0:
            return
        try:
            from collections import Counter
            from datetime import datetime, timezone, timedelta

            from langsmith import Client

            client = Client()
            elapsed = time.time() - self._task_start
            tool_dist = dict(Counter(self._task_tool_names))

            outcome = self._task_outcome(elapsed)
            time_to_first_tool = (
                round(self._task_first_tool_at - self._task_start, 2)
                if self._task_first_tool_at else None
            )
            time_to_first_visible = (
                round(self._task_first_visible_at - self._task_start, 2)
                if self._task_first_visible_at else None
            )

            root_run_id = getattr(self, "_task_root_run_id", None)
            if not root_run_id:
                # Fallback to the legacy time-window poll. LangSmith ingestion
                # is async, so this often misses very-recent runs; the
                # collect_runs path above is the primary route.
                task_start_utc = datetime.fromtimestamp(self._task_start, tz=timezone.utc)
                runs = list(client.list_runs(
                    project_name=os.environ.get("LANGSMITH_PROJECT", "codepilot"),
                    is_root=True,
                    start_time=task_start_utc - timedelta(seconds=2),
                    limit=10,
                ))
                root_run = None
                best_delta = float("inf")
                for r in runs:
                    if r.start_time:
                        delta = abs((r.start_time - task_start_utc).total_seconds())
                        if delta < best_delta:
                            best_delta = delta
                            root_run = r
                if root_run:
                    root_run_id = str(root_run.id)

            if root_run_id:
                client.create_feedback(
                    run_id=root_run_id,
                    key="task_outcome",
                    score=1.0 if outcome == "success" else (0.5 if outcome in ("partial", "aborted") else 0.0),
                    comment=f"outcome={outcome}, iterations={self._task_iteration_count}, "
                            f"tools={self._task_tools}, tokens={self._task_tokens}, "
                            f"input_tokens={self._task_input_tokens}, "
                            f"output_tokens={self._task_output_tokens}, "
                            f"elapsed={elapsed:.1f}s",
                )
                client.update_run(
                    run_id=root_run_id,
                    extra={
                        "task_metrics": {
                            "iteration_count": self._task_iteration_count,
                            "tool_call_count": self._task_tools,
                            "tool_distribution": tool_dist,
                            "denied_count": self._task_denied_count,
                            "input_tokens": self._task_input_tokens,
                            "output_tokens": self._task_output_tokens,
                            "total_tokens": self._task_tokens,
                            "elapsed_seconds": round(elapsed, 2),
                            "outcome": outcome,
                            "did_edit": self._task_did_edit,
                            "did_test": self._task_did_test,
                            "tests_passed": self._task_tests_passed,
                            "permission_wait_count": self._task_permission_wait_count,
                            "time_to_first_tool": time_to_first_tool,
                            "time_to_first_visible_update": time_to_first_visible,
                            "final_user_visible_status": outcome,
                        },
                    },
                )
        except Exception:
            pass
