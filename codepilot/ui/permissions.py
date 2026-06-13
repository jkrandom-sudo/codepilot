from __future__ import annotations

import sys
from typing import Callable, Optional

from codepilot.config.permissions import PermissionRuleset


PermissionChoice = str

PERMISSION_CHOICES: list[tuple[PermissionChoice, str]] = [
    ("allow", "允许执行"),
    ("deny", "拒绝执行"),
    ("always", "始终允许"),
]


def _choice_from_text(text: str) -> PermissionChoice | None:
    normalized = text.strip().lower()
    return {
        "1": "allow",
        "allow": "allow",
        "y": "allow",
        "yes": "allow",
        "2": "deny",
        "deny": "deny",
        "n": "deny",
        "no": "deny",
        "cancel": "deny",
        "3": "always",
        "always": "always",
    }.get(normalized)


def prompt_permission_choice() -> PermissionChoice:
    """Prompt for a permission choice inline, falling back to numeric input."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.styles import Style

            selected = {"index": 0}
            kb = KeyBindings()

            def move(delta: int) -> None:
                selected["index"] = (selected["index"] + delta) % len(PERMISSION_CHOICES)

            def finish(event, choice: PermissionChoice) -> None:
                event.app.exit(result=choice)

            @kb.add("up")
            @kb.add("left")
            def _(event) -> None:
                move(-1)
                event.app.invalidate()

            @kb.add("down")
            @kb.add("right")
            def _(event) -> None:
                move(1)
                event.app.invalidate()

            @kb.add("enter")
            def _(event) -> None:
                finish(event, PERMISSION_CHOICES[selected["index"]][0])

            @kb.add("1")
            def _(event) -> None:
                finish(event, "allow")

            @kb.add("2")
            def _(event) -> None:
                finish(event, "deny")

            @kb.add("3")
            def _(event) -> None:
                finish(event, "always")

            @kb.add("escape", eager=True)
            @kb.add("c-c")
            def _(event) -> None:
                finish(event, "deny")

            def toolbar():
                rendered = []
                for idx, (_, label) in enumerate(PERMISSION_CHOICES):
                    prefix = "▶ " if idx == selected["index"] else "  "
                    style = "permission.selected" if idx == selected["index"] else "permission.normal"
                    rendered.append((style, f"{prefix}{idx + 1}. {label}  "))
                rendered.append(("permission.hint", "  ↑/↓ 选择 · Enter 确认 · Esc 取消"))
                return rendered

            session = PromptSession()
            result = session.prompt(
                "  请选择: ",
                key_bindings=kb,
                bottom_toolbar=toolbar,
                style=Style.from_dict({
                    "permission.selected": "bold reverse",
                    "permission.normal": "",
                    "permission.hint": "ansigray",
                }),
                multiline=False,
                reserve_space_for_menu=0,
            )
            choice = result if result in {"allow", "deny", "always"} else _choice_from_text(str(result))
            if choice:
                return choice
            return "deny"
        except (EOFError, KeyboardInterrupt):
            return "deny"
        except Exception:
            pass

    while True:
        response = input("  请选择 [1/2/3]: ").strip()
        choice = _choice_from_text(response)
        if choice:
            return choice
        print("  输入 1(允许) / 2(拒绝) / 3(始终允许)")


class PermissionHandler:
    """Resolves tool-call permissions through a ruleset, optionally asking the user.

    The ask function is injected so the handler doesn't need to know whether
    the call site is prompt_toolkit, headless CI, or a unit test. The default
    fallback uses plain `input()` which is fine for headless tests but
    disruptive in an interactive REPL — the REPL should pass a prompt-aware
    ask function.
    """

    AskFn = Callable[[str, str, dict], bool]

    def __init__(
        self,
        ruleset: PermissionRuleset | None = None,
        allowed_tools: set[str] | None = None,
        ask_fn: Optional[AskFn] = None,
    ) -> None:
        self.allowed_tools: set[str] = allowed_tools or set()
        self.ruleset = ruleset or PermissionRuleset.build_ruleset()
        self._ask_fn = ask_fn

    def check_permission(self, tool_name: str, tool_args: dict) -> bool:
        if tool_name in self.allowed_tools:
            return True

        action = self.ruleset.evaluate(tool_name, tool_args)

        if action == "allow":
            return True
        if action == "deny":
            return False
        if action == "ask":
            return self._ask_confirmation(tool_name, tool_args)

        return True

    def _ask_confirmation(self, tool_name: str, tool_args: dict) -> bool:
        if self._ask_fn is None:
            return self._ask_stdin(tool_name, tool_args)
        return self._ask_fn(self.ruleset_name(), tool_name, tool_args)

    def _ask_stdin(self, tool_name: str, tool_args: dict) -> bool:
        from codepilot.ui.renderer import Renderer
        renderer = Renderer()
        renderer.render_choice(tool_name, tool_args)

        choice = prompt_permission_choice()
        if choice == "allow":
            return True
        if choice == "always":
            self.allowed_tools.add(tool_name)
            return True
        return False

    def ruleset_name(self) -> str:
        return self.ruleset.__class__.__name__

    def set_ruleset(self, ruleset: PermissionRuleset) -> None:
        self.ruleset = ruleset
        self.allowed_tools.clear()

    def set_ask_fn(self, ask_fn: AskFn) -> None:
        self._ask_fn = ask_fn
