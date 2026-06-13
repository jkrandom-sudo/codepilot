from __future__ import annotations

import json

from rich.console import Console
from rich.markdown import Markdown
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


# Tool intent descriptions
TOOL_INTENT = {
    "read_file": "读取文件",
    "write_file": "写入文件",
    "edit_file": "编辑文件",
    "glob": "查找文件",
    "run_shell": "执行命令",
    "grep": "搜索代码",
    "web_search": "网页搜索",
    "web_fetch": "获取网页",
    "todo_write": "任务列表",
    "git_status": "Git 状态",
    "git_diff": "Git 差异",
    "git_log": "Git 日志",
    "task": "子任务",
}

# Phase grouping
READ_PHASE_TOOLS = {"read_file", "glob", "grep", "web_search", "web_fetch", "git_status", "git_diff", "git_log"}
WRITE_PHASE_TOOLS = {"edit_file", "write_file", "run_shell"}
VERIFY_COMMAND_HINTS = ("pytest", "test", "ruff", "mypy", "tox", "pre-commit")


class Renderer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.step_counter = 0
        self.last_phase = ""

    def reset_task(self) -> None:
        """Reset per-task rendering state."""
        self.step_counter = 0
        self.last_phase = ""

    def render_task_start(
        self,
        prompt: str,
        model: str = "",
        agent_name: str = "",
        mode: str = "",
    ) -> None:
        """Show a clear task boundary before execution begins."""
        self.reset_task()
        self.console.print()
        self.console.print("[bold cyan]🚀 开始执行任务[/bold cyan]")
        task = prompt.strip().replace("\n", " ")
        self.console.print(f"[dim]任务：{task[:120]}[/dim]")
        meta = []
        if model:
            meta.append(f"模型: {model}")
        if agent_name:
            meta.append(f"Agent: {agent_name}")
        if mode:
            meta.append(f"模式: {mode}")
        if meta:
            self.console.print("[dim]" + " | ".join(meta) + "[/dim]")

    def render_waiting(self, message: str = "Agent 正在分析和执行，结果会实时显示...") -> None:
        """Show an immediate waiting hint while the first model event is pending."""
        self.console.print(f"[yellow]⏳ {message}[/yellow]")

    def activity(self, message: str = "正在理解任务并准备上下文...") -> Status:
        """Create a live status spinner for long-running agent work."""
        return self.console.status(self._activity_text(message), spinner="dots")

    def start_activity(self, message: str = "正在理解任务并准备上下文...") -> Status:
        """Start a live status spinner and return it for later updates."""
        activity = self.activity(message)
        activity.start()
        return activity

    def update_activity(self, activity: Status | None, message: str) -> None:
        """Update a live status spinner if one is active."""
        if activity is not None:
            activity.update(self._activity_text(message))

    def resume_activity(self, activity: Status | None, message: str) -> None:
        """Resume a paused live status spinner with fresh text."""
        if activity is not None:
            activity.update(self._activity_text(message))
            activity.start()

    def stop_activity(self, activity: Status | None) -> None:
        """Stop a live status spinner if one is active."""
        if activity is not None:
            activity.stop()

    def render_phase_header(self, phase: str) -> None:
        """Show a new execution phase separator."""
        if phase == self.last_phase:
            return
        self.console.print()
        self.console.print(f"[bold blue]▶ {phase}[/bold blue]")
        self.console.print("[dim]" + "─" * 48 + "[/dim]")
        self.last_phase = phase

    def infer_phase(self, tool_name: str, tool_args: dict | None = None) -> str:
        """Map low-level tool calls to user-facing execution phases."""
        args = tool_args or {}
        if tool_name in {"read_file", "glob", "grep", "git_status", "git_diff", "git_log"}:
            return "检查项目与收集上下文"
        if tool_name in {"edit_file", "write_file"}:
            return "修改文件"
        if tool_name == "run_shell":
            command = str(args.get("command", "")).lower()
            if any(hint in command for hint in VERIFY_COMMAND_HINTS):
                return "验证结果"
            return "执行命令"
        if tool_name in {"web_search", "web_fetch"}:
            return "查询外部资料"
        if tool_name == "todo_write":
            return "更新任务计划"
        if tool_name == "task":
            return "执行子任务"
        return "执行工具"

    def render_tool_call(
        self,
        tool_name: str,
        tool_args: dict,
        step: int = 0,
        total: int = 0,
        elapsed: float = 0,
        tokens: int = 0,
    ) -> None:
        """Show tool call with intent, step counter, target, elapsed time and tokens."""
        self.render_phase_header(self.infer_phase(tool_name, tool_args))
        intent = TOOL_INTENT.get(tool_name, tool_name)
        icon = self._tool_icon(tool_name)
        target = self._tool_target(tool_name, tool_args)

        step_str = f"{step}/{total}" if total > 0 else str(step)
        meta = []
        if elapsed:
            meta.append(f"{elapsed:.1f}s")
        if tokens:
            meta.append(f"{tokens:,} tokens")

        target_text = f" [dim]{target}[/dim]" if target else ""
        meta_text = f" [dim]({' | '.join(meta)})[/dim]" if meta else ""
        self.console.print(f"  [dim]{step_str}[/dim] {icon} [bold]{intent}[/bold]{target_text}{meta_text}")

    def render_tool_result(
        self,
        tool_name: str,
        result: str,
        elapsed: float = 0,
        success: bool = True,
        status: str = "success",
    ) -> None:
        """Show tool result with concise status."""
        if status == "blocked":
            msg = result.strip().split("\n")[0][:120]
            self.console.print(f"    [yellow]⚠ 跳过[/yellow] [dim]{msg}[/dim]")
            return

        if not success:
            err = result.strip().split("\n")[0][:120]
            self.console.print(f"    [red]✘ 失败[/red] [dim]{err}[/dim]")
            return

        summary = self._result_summary(tool_name, result, elapsed)
        self.console.print(f"    [green]✓[/green] [dim]{summary}[/dim]")

    def render_edit_diff(self, old_str: str, new_str: str, path: str = "") -> None:
        """Show before/after diff for code modifications."""
        import difflib

        old_lines = old_str.splitlines(keepends=True)
        new_lines = new_str.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile="原文件", tofile="修改后")

        diff_text = "".join(diff)
        if diff_text:
            self.console.print(f"    [dim]📄 {path}[/dim]")
            self.console.print(Syntax(diff_text, "diff", theme="monokai"))

    def render_task_summary(
        self,
        total_time: float,
        total_tokens: int,
        tool_count: int,
        step_count: int = 0,
        outcome: str = "success",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Show task completion summary."""
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim", justify="right")
        table.add_column(style="bold")
        table.add_row("执行时间:", f"{total_time:.1f}s")
        if input_tokens or output_tokens:
            table.add_row(
                "Token 消耗:",
                f"{total_tokens:,} [dim](输入 {input_tokens:,} / 输出 {output_tokens:,})[/dim]",
            )
        else:
            table.add_row("Token 消耗:", f"{total_tokens:,}")
        table.add_row("工具调用:", f"{tool_count} 次")
        if step_count > 0:
            table.add_row("执行步骤:", f"{step_count} 步")
        self.console.print()
        if outcome == "success":
            self.console.print("[bold green]✅ 任务完成[/bold green]")
        elif outcome == "partial":
            self.console.print("[bold yellow]⚠ 部分完成[/bold yellow]")
        else:
            self.console.print("[bold red]✘ 任务未完成[/bold red]")
        self.console.print(table)

    def render_model_usage(
        self,
        label: str,
        total_tokens: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Show token usage for a model round that is not otherwise tied to one tool step."""
        if not total_tokens:
            return
        details = ""
        if input_tokens or output_tokens:
            details = f" [dim](输入 {input_tokens:,} / 输出 {output_tokens:,})[/dim]"
        self.console.print(f"  [dim]🧠 {label}: {total_tokens:,} tokens{details}[/dim]")

    def render_message(self, content: str) -> None:
        self.console.print(Markdown(content))

    def render_thinking(self, text: str) -> None:
        self.console.print(Text(text, style="italic dim"))

    def render_code(self, code: str, language: str = "python") -> None:
        self.console.print(Syntax(code, language, theme="monokai", line_numbers=True))

    def render_diff(self, diff_text: str) -> None:
        self.console.print(Syntax(diff_text, "diff", theme="monokai"))

    def render_error(self, error: str) -> None:
        self.console.print(f"[bold red]Error:[/bold red] {error}")

    def render_info(self, info: str) -> None:
        self.console.print(f"[dim]{info}[/dim]")

    def render_choice(self, tool_name: str, tool_args: dict) -> None:
        """Show confirmation context before the inline prompt takes focus."""
        intent = TOOL_INTENT.get(tool_name, tool_name)
        target = self._tool_target(tool_name, tool_args)
        desc = f"{intent} {target}" if target else intent

        self.console.print()
        self.console.print(f"  [bold yellow]⏸ 等待确认：{desc}[/bold yellow]")
        self.console.print("  " + "─" * 40)

        if tool_name == "edit_file":
            old_str = tool_args.get("old_str", "")
            new_str = tool_args.get("new_str", "")
            path = tool_args.get("path", "")
            if old_str or new_str:
                self.console.print(f"  [dim]文件:[/dim] {path}")
                if old_str:
                    self.console.print(f"  [dim]旧内容:[/dim] {old_str[:80]}{'...' if len(old_str) > 80 else ''}")
                if new_str:
                    self.console.print(f"  [dim]新内容:[/dim] {new_str[:80]}{'...' if len(new_str) > 80 else ''}")
                self.render_edit_diff(old_str, new_str, path)
        elif tool_name == "write_file":
            content = tool_args.get("content", "")
            path = tool_args.get("path", "")
            preview = content[:200] + ("..." if len(content) > 200 else "")
            self.console.print(f"  [dim]写入 {path} ({len(content)} chars):[/dim]")
            self.console.print(Syntax(preview, "python", theme="monokai"))
        elif tool_name == "run_shell":
            cmd = tool_args.get("command", "")
            self.console.print(f"  [dim]命令:[/dim] [bold]{cmd}[/bold]")

        self.console.print("  " + "─" * 40)
        self.console.print(
            "  [bold green][1][/bold green] 允许执行  "
            "[bold red][2][/bold red] 拒绝执行  "
            "[bold blue][3][/bold blue] 始终允许  "
            "[dim]↑/↓ 选择，Enter 确认，Esc 取消[/dim]"
        )
        self.console.print()

    def render_permission_result(self, tool_name: str, allowed: bool, always: bool = False) -> None:
        """Show whether a permission prompt allowed execution to continue."""
        intent = TOOL_INTENT.get(tool_name, tool_name)
        if allowed:
            suffix = "，后续同类操作自动允许" if always else ""
            self.console.print(f"  [green]▶ 继续执行：{intent}{suffix}[/green]")
        else:
            self.console.print(f"  [yellow]任务已暂停：用户拒绝 {intent}[/yellow]")

    def _render_edit_summary(self, result: str) -> None:
        """Extract and show edit summary from tool result."""
        # Result format: "Edited /path: replaced X chars with Y chars"
        self.console.print(f"  [green]✔[/green] [dim]{result.strip()[:80]}[/dim]")

    def _result_summary(self, tool_name: str, result: str, elapsed: float = 0) -> str:
        """Return a stable one-line summary for a tool result."""
        text = result.strip()
        if tool_name in {"read_file", "grep", "glob"}:
            if "No matches" in text or "No files" in text:
                return text.split("\n")[0][:100]
            lines = len(text.splitlines()) if text else 0
            return f"完成，返回 {lines} 行内容"
        if tool_name in {"edit_file", "write_file"}:
            first = text.split("\n")[0] if text else "文件已更新"
            return first[:100]
        if tool_name == "run_shell":
            if "failed" in text.lower() or "Exit code:" in text:
                first = text.split("\n")[0] if text else "命令执行结束"
                return first[:100]
            if " passed" in text or " passed in " in text:
                return "测试通过"
            first = text.split("\n")[0] if text else "命令执行完成"
            return first[:100]
        if tool_name == "todo_write":
            return "任务计划已更新"
        if tool_name == "task":
            first = text.split("\n")[0] if text else "子任务完成"
            return first[:100]
        if text:
            return text.split("\n")[0][:100]
        if elapsed:
            return f"完成，用时 {elapsed:.1f}s"
        return "完成"

    def _tool_icon(self, tool_name: str) -> str:
        return {
            "read_file": "📄",
            "write_file": "📝",
            "edit_file": "✏️",
            "glob": "🔎",
            "grep": "🔍",
            "run_shell": "⚙️",
            "web_search": "🌐",
            "web_fetch": "🌍",
            "todo_write": "📋",
            "git_status": "🌿",
            "git_diff": "🧾",
            "git_log": "📜",
            "task": "🤖",
        }.get(tool_name, "🔧")

    def _activity_text(self, message: str) -> str:
        return f"[yellow]⏳ {message}[/yellow]"

    def _tool_target(self, tool_name: str, args: dict) -> str:
        """Extract the primary target of a tool call for display."""
        if tool_name in ("read_file", "write_file", "edit_file"):
            return args.get("path", "")
        if tool_name == "glob":
            return f"{args.get('pattern', '')} in {args.get('path', '.')}"
        if tool_name == "run_shell":
            cmd = args.get("command", "")
            return cmd if len(cmd) <= 50 else cmd[:47] + "..."
        if tool_name == "grep":
            return f"'{args.get('pattern', '')}'"
        if tool_name in ("web_search",):
            return args.get("query", "")
        if tool_name == "web_fetch":
            return args.get("url", "")
        if tool_name == "todo_write":
            return f"{len(json.loads(args.get('todos', '[]')))} items" if args.get("todos") else ""
        if tool_name in ("git_status", "git_diff", "git_log"):
            extra = args.get("path", "") or args.get("count", "")
            return str(extra) if extra else ""
        return ""
