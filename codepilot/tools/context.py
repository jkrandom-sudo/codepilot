from __future__ import annotations

import threading
from typing import Any

from codepilot.config.permissions import PermissionRuleset


class ToolContext:
    __slots__ = (
        "session_id",
        "agent_name",
        "working_dir",
        "files_context",
        "abort",
        "permissions",
        "seen_patterns",
    )

    def __init__(
        self,
        session_id: str = "",
        agent_name: str = "build",
        working_dir: str = "",
        files_context: list[str] | None = None,
        abort: threading.Event | None = None,
        permissions: PermissionRuleset | None = None,
    ):
        self.session_id = session_id
        self.agent_name = agent_name
        self.working_dir = working_dir
        self.files_context = list(files_context) if files_context else []
        self.abort = abort or threading.Event()
        self.permissions = permissions or PermissionRuleset.build_ruleset()
        self.seen_patterns: set[str] = set()

    def check_permission(self, tool_name: str, args: dict[str, Any] | None = None) -> str:
        return self.permissions.evaluate(tool_name, args)

    def track_file(self, path: str) -> None:
        if path and path not in self.files_context:
            self.files_context.append(path)

    def is_file_tracked(self, path: str) -> bool:
        return path in self.files_context
