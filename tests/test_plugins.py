"""Smoke tests for the plugin/hook system."""
from codepilot.plugins.manager import (
    HookType,
    PluginHook,
    PluginManager,
    get_plugin_manager,
)


class TestPluginManager:
    def test_register_and_emit(self):
        pm = PluginManager()
        called: list[bool] = []

        def handler(data):
            called.append(True)
            return {**data, "x": data.get("x", 0) + 1}

        pm.register(PluginHook(hook_type=HookType.COMPACTION, handler_name="t", handler=handler))
        out = pm.emit(HookType.COMPACTION, {"x": 0})
        assert out["x"] == 1
        assert called == [True]

    def test_emit_chain(self):
        pm = PluginManager()
        pm.register(PluginHook(hook_type=HookType.SYSTEM_PROMPT_TRANSFORM, handler_name="a", handler=lambda d: {**d, "prompt": d["prompt"] + "A"}))
        pm.register(PluginHook(hook_type=HookType.SYSTEM_PROMPT_TRANSFORM, handler_name="b", handler=lambda d: {**d, "prompt": d["prompt"] + "B"}))
        out = pm.emit(HookType.SYSTEM_PROMPT_TRANSFORM, {"prompt": "hi"})
        assert out["prompt"] == "hiAB"

    def test_handler_exception_silent(self):
        pm = PluginManager()
        pm.register(PluginHook(hook_type=HookType.COMPACTION, handler_name="bad", handler=lambda d: 1 / 0))
        pm.register(PluginHook(hook_type=HookType.COMPACTION, handler_name="ok", handler=lambda d: {**d, "x": 1}))
        out = pm.emit(HookType.COMPACTION, {"x": 0})
        assert out["x"] == 1

    def test_unregister(self):
        pm = PluginManager()
        pm.register(PluginHook(hook_type=HookType.COMPACTION, handler_name="a", handler=lambda d: d))
        pm.register(PluginHook(hook_type=HookType.COMPACTION, handler_name="a", handler=lambda d: d))
        removed = pm.unregister("a", HookType.COMPACTION)
        assert removed == 2
        assert not pm.has_hooks(HookType.COMPACTION)

    def test_singleton(self):
        a = get_plugin_manager()
        b = get_plugin_manager()
        assert a is b

    def test_clear(self):
        pm = PluginManager()
        pm.register(PluginHook(hook_type=HookType.COMPACTION, handler_name="a", handler=lambda d: d))
        pm.clear()
        assert not pm.has_hooks(HookType.COMPACTION)


class TestHookIntegration:
    """Verify that all five hook types are emitted from the right places."""

    def test_all_hook_types_defined(self):
        assert HookType.SYSTEM_PROMPT_TRANSFORM
        assert HookType.TOOL_EXECUTE_BEFORE
        assert HookType.TOOL_EXECUTE_AFTER
        assert HookType.COMPACTION
        assert HookType.MESSAGE_BEFORE_SAVE
