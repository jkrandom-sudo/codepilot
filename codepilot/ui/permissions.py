"""Interactive permission prompt UI.

Displays tool execution requests to the user
and captures allow/deny/always-allow decisions.
"""
from __future__ import annotations

from typing import Callable, Optional

from codepilot.config.permissions import PermissionRuleset


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

        while True:
            response = input("  请选择 [1/2/3]: ").strip()
            if response == "1":
                return True
            if response == "2":
                return False
            if response == "3":
                self.allowed_tools.add(tool_name)
                return True
            print("  输入 1(允许) / 2(拒绝) / 3(始终允许)")

    def ruleset_name(self) -> str:
        return self.ruleset.__class__.__name__

    def set_ruleset(self, ruleset: PermissionRuleset) -> None:
        self.ruleset = ruleset
        self.allowed_tools.clear()

    def set_ask_fn(self, ask_fn: AskFn) -> None:
        self._ask_fn = ask_fn
