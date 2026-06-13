from __future__ import annotations

import fnmatch
from typing import Any, Literal

from pydantic import BaseModel, Field


class PermissionRule(BaseModel):
    tool: str = Field(description="Tool name pattern, e.g. 'edit_file', 'run_shell', '*'")
    pattern: str = Field(default="**", description="Glob pattern for path/command matching")
    action: Literal["allow", "ask", "deny"] = Field(description="Permission action")


class PermissionRuleset(BaseModel):
    rules: list[PermissionRule] = Field(
        default_factory=list,
        description="Ordered rules. Last matching rule wins (like CSS specificity).",
    )

    def evaluate(self, tool_name: str, args: dict[str, Any] | None = None) -> str:
        result = "allow"
        args = args or {}
        best_specificity = -1
        for rule in self.rules:
            matches, specificity = self._matches_tool_with_specificity(rule.tool, tool_name)
            if matches:
                target = self._extract_target(tool_name, args)
                if fnmatch.fnmatch(target, rule.pattern):
                    if specificity >= best_specificity:
                        result = rule.action
                        best_specificity = specificity
        return result

    @staticmethod
    def _matches_tool(pattern: str, tool_name: str) -> bool:
        if pattern == "*":
            return True
        return fnmatch.fnmatch(tool_name, pattern)

    @staticmethod
    def _matches_tool_with_specificity(pattern: str, tool_name: str) -> tuple[bool, int]:
        if pattern == "*":
            return True, 0
        if fnmatch.fnmatch(tool_name, pattern):
            return True, 1
        return False, -1

    @staticmethod
    def _extract_target(tool_name: str, args: dict[str, Any]) -> str:
        if tool_name in ("edit_file", "write_file", "read_file"):
            return args.get("path", "")
        if tool_name == "run_shell":
            return args.get("command", "")
        if tool_name in ("glob", "grep"):
            return args.get("path", args.get("pattern", ""))
        return ""

    def merge(self, other: PermissionRuleset) -> PermissionRuleset:
        return PermissionRuleset(rules=self.rules + other.rules)

    @classmethod
    def build_ruleset(cls) -> PermissionRuleset:
        return cls(rules=[
            PermissionRule(tool="*", pattern="**", action="ask"),
            PermissionRule(tool="read_file", pattern="**", action="allow"),
            PermissionRule(tool="glob", pattern="**", action="allow"),
            PermissionRule(tool="grep", pattern="**", action="allow"),
            PermissionRule(tool="web_search", pattern="**", action="allow"),
            PermissionRule(tool="web_fetch", pattern="**", action="allow"),
            PermissionRule(tool="git_status", pattern="**", action="allow"),
            PermissionRule(tool="git_diff", pattern="**", action="allow"),
            PermissionRule(tool="git_log", pattern="**", action="allow"),
            PermissionRule(tool="todo_write", pattern="**", action="allow"),
            PermissionRule(tool="skill_list", pattern="**", action="allow"),
            PermissionRule(tool="skill_read", pattern="**", action="allow"),
            PermissionRule(tool="mcp_list_servers", pattern="**", action="allow"),
            PermissionRule(tool="mcp_list_tools", pattern="**", action="allow"),
            PermissionRule(tool="run_shell", pattern="rm *", action="deny"),
            PermissionRule(tool="run_shell", pattern="mkfs *", action="deny"),
            PermissionRule(tool="run_shell", pattern="dd *", action="deny"),
        ])

    @classmethod
    def auto_ruleset(cls) -> PermissionRuleset:
        return cls(rules=[
            PermissionRule(tool="*", pattern="**", action="allow"),
            PermissionRule(tool="run_shell", pattern="rm *", action="deny"),
            PermissionRule(tool="run_shell", pattern="mkfs *", action="deny"),
            PermissionRule(tool="run_shell", pattern="dd *", action="deny"),
        ])

    @classmethod
    def plan_ruleset(cls) -> PermissionRuleset:
        return cls(rules=[
            PermissionRule(tool="*", pattern="**", action="allow"),
            PermissionRule(tool="edit_file", pattern="**", action="deny"),
            PermissionRule(tool="write_file", pattern="**", action="deny"),
            PermissionRule(tool="run_shell", pattern="**", action="deny"),
            PermissionRule(tool="task", pattern="**", action="deny"),
            PermissionRule(tool="mcp_call_tool", pattern="**", action="deny"),
        ])

    @classmethod
    def explore_ruleset(cls) -> PermissionRuleset:
        return cls(rules=[
            PermissionRule(tool="read_file", pattern="**", action="allow"),
            PermissionRule(tool="glob", pattern="**", action="allow"),
            PermissionRule(tool="grep", pattern="**", action="allow"),
            PermissionRule(tool="web_search", pattern="**", action="allow"),
            PermissionRule(tool="web_fetch", pattern="**", action="allow"),
            PermissionRule(tool="git_status", pattern="**", action="allow"),
            PermissionRule(tool="git_diff", pattern="**", action="allow"),
            PermissionRule(tool="git_log", pattern="**", action="allow"),
            PermissionRule(tool="skill_list", pattern="**", action="allow"),
            PermissionRule(tool="skill_read", pattern="**", action="allow"),
            PermissionRule(tool="mcp_list_servers", pattern="**", action="allow"),
            PermissionRule(tool="mcp_list_tools", pattern="**", action="allow"),
            PermissionRule(tool="*", pattern="**", action="deny"),
        ])

    @classmethod
    def general_ruleset(cls) -> PermissionRuleset:
        return cls(rules=[
            PermissionRule(tool="*", pattern="**", action="allow"),
            PermissionRule(tool="run_shell", pattern="rm *", action="deny"),
            PermissionRule(tool="run_shell", pattern="mkfs *", action="deny"),
        ])
