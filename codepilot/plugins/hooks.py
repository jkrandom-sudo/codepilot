"""Backwards-compatible re-export shim.

The real implementation now lives in `codepilot.plugins.manager` so that
agent graph code can import it without dragging in heavy dependencies.
"""
from __future__ import annotations

from codepilot.plugins.manager import (  # noqa: F401
    HookType,
    PluginHook,
    PluginManager,
    get_plugin_manager,
)
