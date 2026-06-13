from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

if TYPE_CHECKING:
    from codepilot.ui.repl import REPL


SLASH_COMMANDS = {
    "/model": "查看或切换模型",
    "/agent": "切换或查看 Agent (build/plan/plan-execute)",
    "/context": "查看上下文使用情况",
    "/compact": "压缩对话历史",
    "/clear": "清除对话历史",
    "/add": "添加文件到上下文",
    "/diff": "查看未提交的变更",
    "/undo": "撤销上次文件修改",
    "/trace": "开启/关闭 LangSmith 追踪 (on|off)",
    "/refresh": "刷新文件索引",
    "/sessions": "列出历史会话",
    "/resume": "恢复历史会话",
    "/init": "初始化 AGENTS.md 项目指令文件",
    "/help": "显示帮助",
    "/quit": "退出 CodePilot",
    "/exit": "退出 CodePilot",
}


class CommandHandler:
    def __init__(self, repl: "REPL") -> None:
        self.repl = repl

    def handle(self, cmd: str) -> bool:
        parts = cmd.split(maxsplit=1)
        command = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/quit": self._quit,
            "/exit": self._quit,
            "/help": self._help,
            "/model": self._model,
            "/add": self._add,
            "/clear": self._clear,
            "/compact": self._compact,
            "/context": self._context,
            "/refresh": self._refresh,
            "/diff": self._diff,
            "/undo": self._undo,
            "/trace": self._trace,
            "/agent": self._agent,
            "/sessions": self._sessions,
            "/resume": self._resume,
            "/init": self._init,
        }

        handler = handlers.get(command)
        if handler:
            return handler(arg)

        self.repl.console.print(f"[yellow]未知命令: {command}[/yellow]")
        return False

    def _quit(self, arg: str) -> bool:
        self.repl.console.print("[dim]Goodbye![/dim]")
        return True

    def _help(self, arg: str) -> bool:
        for cmd_name, desc in SLASH_COMMANDS.items():
            self.repl.console.print(f"  {cmd_name:12s} {desc}")
        return False

    def _model(self, arg: str) -> bool:
        if arg:
            old_model = self.repl.model
            self.repl.model = arg
            from codepilot.config.context_windows import get_usable_context, parse_model_spec
            raw_model_name = arg.split("/", 1)[-1] if "/" in arg else arg
            clean_name, suffix_ctx = parse_model_spec(raw_model_name)
            self.repl._context_window = get_usable_context(clean_name, suffix_ctx)
            if self.repl.registry:
                try:
                    self.repl.llm = self.repl.registry.get_llm(arg)
                    self.repl._get_or_build_graph()
                except Exception as e:
                    self.repl.console.print(f"[red]模型切换失败: {e}[/red]")
                    self.repl.model = old_model
                    return False
            self.repl.console.print(f"[green]模型: {arg}[/green]  [dim]上下文: {self.repl._context_window:,} tokens[/dim]")
        else:
            self.repl.console.print(f"当前: {self.repl.model}  上下文: {self.repl._context_window:,} tokens")
        return False

    def _add(self, arg: str) -> bool:
        if not arg:
            self.repl.console.print("[red]用法: /add <文件路径>[/red]")
            return False

        from pathlib import Path
        from codepilot.tools.file_tools import _is_sensitive_path, MAX_FILE_BYTES

        p = Path(arg).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            p = p.resolve()
        except Exception:
            self.repl.renderer.render_error(f"无法解析路径: {arg}")
            return False

        if _is_sensitive_path(p):
            self.repl.console.print(f"[red]禁止: {p} 是敏感路径（凭证/配置）[/red]")
            return False

        for prefix in ("/etc", "/private/etc", "/proc", "/sys", "/dev"):
            if str(p).startswith(prefix):
                self.repl.console.print(f"[red]禁止: 系统路径 {p}[/red]")
                return False

        if not p.exists():
            self.repl.renderer.render_error(f"文件不存在: {p}")
            return False
        if p.is_dir():
            self.repl.renderer.render_error(f"{p} 是目录，请指定文件")
            return False

        try:
            size = p.stat().st_size
            if size > MAX_FILE_BYTES * 4:
                self.repl.renderer.render_error(f"文件过大: {size} bytes (max {MAX_FILE_BYTES * 4})")
                return False
            content = p.read_text(errors="replace")
            from langchain_core.messages import HumanMessage
            self.repl.messages.append(HumanMessage(content=f"[Added file: {p}]\n{content}"))
            self.repl._update_context_stats()
            self.repl.console.print(f"[green]+ {p}[/green]")
            self.repl._show_context_bar()
        except Exception as e:
            self.repl.renderer.render_error(str(e))
        return False

    def _clear(self, arg: str) -> bool:
        self.repl.messages.clear()
        self.repl._update_context_stats()
        self.repl.console.print("[green]已清除上下文[/green]")
        return False

    def _compact(self, arg: str) -> bool:
        self.repl._compact_messages()
        return False

    def _context(self, arg: str) -> bool:
        self.repl._show_context_detail()
        return False

    def _refresh(self, arg: str) -> bool:
        if hasattr(self.repl, "_file_index") and self.repl._file_index:
            self.repl._file_index.get_files(force_refresh=True)
            count = len(self.repl._file_index._files)
            self.repl.console.print(f"[green]文件索引已刷新 ({count} 个文件)[/green]")
        else:
            self.repl.console.print("[yellow]文件索引未初始化[/yellow]")
        return False

    def _diff(self, arg: str) -> bool:
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                self.repl.renderer.render_diff(result.stdout)
            else:
                self.repl.console.print("[dim]无未提交的变更[/dim]")
        except Exception as e:
            self.repl.renderer.render_error(str(e))
        return False

    def _undo(self, arg: str) -> bool:
        if not self.repl.file_stack:
            self.repl.console.print("[dim]无可撤销的操作[/dim]")
            return False
        path, original = self.repl.file_stack.pop()
        with open(path, "w") as f:
            f.write(original)
        self.repl.console.print(f"[green]已还原 {path}[/green]")
        return False

    def _trace(self, arg: str) -> bool:
        if arg == "on":
            self.repl._trace_enabled = True
            import os
            os.environ["LANGSMITH_TRACING"] = "true"
            self.repl.console.print("[green]LangSmith 追踪已开启[/green]")
        elif arg == "off":
            self.repl._trace_enabled = False
            import os
            os.environ["LANGSMITH_TRACING"] = "false"
            self.repl.console.print("[green]LangSmith 追踪已关闭[/green]")
        else:
            status = "开启" if self.repl._trace_enabled else "关闭"
            self.repl.console.print(f"LangSmith 追踪: {status}  用法: /trace on|off")
        return False

    def _agent(self, arg: str) -> bool:
        from codepilot.agent.registry import AgentRegistry
        registry = AgentRegistry()

        if not arg:
            self.repl.console.print(f"当前 Agent: {self.repl.agent_name} ({self.repl._confirm_label})")
            self.repl.console.print("\n可用 Primary Agents:")
            for a in registry.list_primary():
                confirm_str = "confirm" if a.confirm else ("readonly" if a.is_readonly else "auto")
                marker = " ←" if a.name == self.repl.agent_name else ""
                self.repl.console.print(f"  {a.name:10s} {a.display_name} [{confirm_str}]{marker}")
            self.repl.console.print("\n可用 Subagents (via task tool):")
            for a in registry.list_subagents():
                self.repl.console.print(f"  {a.name:10s} {a.display_name}")
            self.repl.console.print("\n用法: /agent <name>")
            return False

        agent_def = registry.get(arg)
        if not agent_def:
            self.repl.console.print(f"[red]未知 Agent: {arg}[/red]")
            return False

        if agent_def.is_subagent:
            self.repl.console.print(f"[yellow]子 Agent '{arg}' 不能直接切换，请通过 task 工具调用[/yellow]")
            return False

        old_agent = self.repl.agent_name
        self.repl.agent_name = arg
        self.repl._agent_def = agent_def
        self.repl.permission.set_ruleset(agent_def.permissions)

        self.repl._get_or_build_graph()

        self.repl.console.print(f"[green]Agent: {old_agent} → {arg} ({agent_def.display_name}, {self.repl._confirm_label})[/green]")
        if self.repl.storage and self.repl._session_id:
            self.repl.storage.update_session(self.repl._session_id, agent=arg, mode=self.repl._confirm_label)
        return False

    def _sessions(self, arg: str) -> bool:
        if not self.repl.storage:
            self.repl.console.print("[yellow]会话存储不可用[/yellow]")
            return False

        sessions = self.repl.storage.list_sessions(limit=20)
        if not sessions:
            self.repl.console.print("[dim]无历史会话[/dim]")
            return False

        table = Table(show_header=True, box=None, padding=(0, 2))
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("标题", max_width=30)
        table.add_column("Agent", max_width=8)
        table.add_column("消息数", justify="right")
        table.add_column("更新时间", style="dim", max_width=19)

        for s in sessions:
            marker = " ←" if s.id == self.repl._session_id else ""
            table.add_row(
                s.id[:8] + marker,
                s.title[:30] or "(untitled)",
                s.agent,
                str(s.message_count),
                s.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            )

        self.repl.console.print(table)
        self.repl.console.print("\n[dim]恢复会话: /resume <session-id>[/dim]")
        return False

    def _resume(self, arg: str) -> bool:
        if not self.repl.storage:
            self.repl.console.print("[yellow]会话存储不可用[/yellow]")
            return False

        if not arg:
            self.repl.console.print("[dim]用法: /resume <session-id>[/dim]")
            return False

        session = self.repl.storage.get_session(arg)
        if not session:
            self.repl.console.print(f"[red]会话不存在: {arg}[/red]")
            return False

        self.repl._persist_messages()

        from codepilot.storage.resume import load_messages
        from codepilot.agent.registry import AgentRegistry
        self.repl._session_id = session.id
        self.repl.messages = load_messages(self.repl.storage, session.id)
        self.repl.agent_name = session.agent
        self.repl._agent_def = AgentRegistry().get_or_default(self.repl.agent_name)
        self.repl.permission.set_ruleset(self.repl._agent_def.permissions)
        self.repl._update_context_stats()

        self.repl.console.print(f"[green]已恢复会话 {session.id[:8]}... ({session.message_count} 条消息)[/green]")
        return False

    def _init(self, arg: str) -> bool:
        from codepilot.context.instructions import init_agents_file

        force = arg.strip() == "--force"
        changed, message = init_agents_file(".", force=force)
        if changed:
            self.repl.console.print(f"[green]{message}[/green]")
        else:
            self.repl.console.print(f"[yellow]{message}[/yellow]")
        return False
