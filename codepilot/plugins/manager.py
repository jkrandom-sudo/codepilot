"""Plugin manager — singleton access point.

The hooks system lets third-party code inject behaviour at well-defined
points in the agent lifecycle without subclassing. Each `HookType` is
emitted by a specific part of the runtime; handlers receive a `data`
dict and return a (possibly modified) `data` dict.

Public API:
- `HookType` — enum of hook points
- `PluginHook` — registered handler with name and callable
- `get_plugin_manager()` — process-wide singleton

Hook contracts:
- `MESSAGE_BEFORE_SAVE` — `{"message": BaseMessage}` → `{"message": ...}`
- `SYSTEM_PROMPT_TRANSFORM` — `{"prompt": str, "state": AgentState}` → `{"prompt": str}`
- `TOOL_EXECUTE_BEFORE` — `{"tool_name": str, "args": dict, "state": AgentState}` → same shape
- `TOOL_EXECUTE_AFTER` — `{"tool_name": str, "args": dict, "result": str, "state": AgentState}` → `{"result": str}`
- `COMPACTION` — `{"messages": list[BaseMessage], "summary": str}` → `{"summary": str}`

Handlers must be idempotent and exception-safe — the manager swallows
exceptions to keep the agent running.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class HookType(Enum):
    MESSAGE_BEFORE_SAVE = "message_before_save"
    SYSTEM_PROMPT_TRANSFORM = "system_prompt_transform"
    TOOL_EXECUTE_BEFORE = "tool_execute_before"
    TOOL_EXECUTE_AFTER = "tool_execute_after"
    COMPACTION = "compaction"


class PluginHook(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    hook_type: HookType
    handler_name: str = ""
    handler: Any = None


class PluginManager:
    def __init__(self) -> None:
        self._hooks: dict[HookType, list[PluginHook]] = {}

    def register(self, hook: PluginHook) -> None:
        if hook.hook_type not in self._hooks:
            self._hooks[hook.hook_type] = []
        self._hooks[hook.hook_type].append(hook)

    def unregister(self, handler_name: str, hook_type: HookType) -> int:
        removed = 0
        if hook_type not in self._hooks:
            return 0
        kept = []
        for hook in self._hooks[hook_type]:
            if hook.handler_name == handler_name:
                removed += 1
                continue
            kept.append(hook)
        self._hooks[hook_type] = kept
        return removed

    def emit(self, hook_type: HookType, data: dict) -> dict:
        hooks = self._hooks.get(hook_type, [])
        result = data
        for hook in hooks:
            if hook.handler and callable(hook.handler):
                try:
                    result = hook.handler(result)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Hook %s raised %s: %s", hook.handler_name, type(e).__name__, e
                    )
        return result

    def has_hooks(self, hook_type: HookType) -> bool:
        return bool(self._hooks.get(hook_type, []))

    def clear(self) -> None:
        self._hooks.clear()


_global_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _global_plugin_manager
    if _global_plugin_manager is None:
        _global_plugin_manager = PluginManager()
    return _global_plugin_manager
