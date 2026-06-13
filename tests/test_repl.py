from langchain_core.messages import AIMessage, ToolMessage

from codepilot.ui.repl import (
    REPL,
    expand_numbered_choice_reply,
    is_tool_result_error,
    resolve_tool_message,
    tool_result_status,
)


class FakePermissionRenderer:
    def __init__(self):
        self.events = []

    def stop_activity(self, activity):
        self.events.append(("stop", activity))

    def resume_activity(self, activity, message):
        self.events.append(("resume", activity, message))

    def render_choice(self, tool_name, tool_args):
        self.events.append(("choice", tool_name, tool_args))

    def render_permission_result(self, tool_name, allowed, always=False):
        self.events.append(("result", tool_name, allowed, always))


class FakeConsole:
    def print(self, *_args, **_kwargs):
        pass


def test_tool_result_error_ignores_error_text_in_successful_search_hits():
    content = "codepilot/ui/intent.py:12:class ErrorBoundary:\nREADME.md:4:Error handling"

    assert is_tool_result_error("grep", content) is False


def test_tool_result_error_ignores_error_text_in_read_file_content():
    content = "350: def _run_agent(self):\n351:     self.renderer.render_error('Error: display')"

    assert is_tool_result_error("read_file", content) is False


def test_tool_result_error_detects_explicit_tool_failures():
    assert is_tool_result_error("read_file", "Error: File not found: missing.py") is True
    assert is_tool_result_error("edit_file", "[Permission denied] write blocked") is True
    assert is_tool_result_error("run_shell", "pytest failed\nExit code: 1") is True


def test_tool_result_error_allows_successful_shell_with_error_text():
    content = "tests/test_errors.py::test_error_message PASSED\nExit code: 0"

    assert is_tool_result_error("run_shell", content) is False


def test_tool_result_status_marks_blocked_as_warning_state():
    assert tool_result_status("read_file", "[BLOCKED] already in context") == "blocked"
    assert tool_result_status("read_file", "Error: File not found") == "error"
    assert tool_result_status("read_file", "1: from __future__ import annotations") == "success"


def test_resolve_tool_message_uses_stored_tool_call_metadata():
    pending = {"tc1": {"name": "read_file", "args": {"path": "codepilot/ui/repl.py"}}}
    msg = ToolMessage(content="ok", tool_call_id="tc1")

    tool_name, tool_args, _ = resolve_tool_message(pending, msg)

    assert tool_name == "read_file"
    assert tool_args == {"path": "codepilot/ui/repl.py"}
    assert pending == {}


def test_resolve_tool_message_falls_back_to_message_name():
    msg = ToolMessage(content="ok", tool_call_id="tc1", name="grep")

    tool_name, tool_args, _ = resolve_tool_message({}, msg)

    assert tool_name == "grep"
    assert tool_args == {}


def test_permission_prompt_pauses_activity_while_waiting_for_input(monkeypatch):
    repl = REPL.__new__(REPL)
    repl._task_permission_wait_count = 0
    repl._active_activity = "activity"
    repl._activity_paused_for_prompt = False
    repl.renderer = FakePermissionRenderer()
    repl.console = FakeConsole()
    repl.permission = type("Permission", (), {"allowed_tools": set()})()
    monkeypatch.setattr("codepilot.ui.repl.prompt_permission_choice", lambda: "allow")

    allowed = repl._ask_permission("build", "run_shell", {"command": "pytest"})

    assert allowed is True
    assert repl.renderer.events[0] == ("stop", "activity")
    assert repl.renderer.events[1][0] == "choice"
    assert repl.renderer.events[-1][0] == "resume"


def test_permission_prompt_supports_arrow_menu_always_choice(monkeypatch):
    repl = REPL.__new__(REPL)
    repl._task_permission_wait_count = 0
    repl._active_activity = None
    repl._activity_paused_for_prompt = False
    repl.renderer = FakePermissionRenderer()
    repl.console = FakeConsole()
    repl.permission = type("Permission", (), {"allowed_tools": set()})()
    monkeypatch.setattr("codepilot.ui.repl.prompt_permission_choice", lambda: "always")

    allowed = repl._ask_permission("build", "run_shell", {"command": "pytest"})

    assert allowed is True
    assert "run_shell" in repl.permission.allowed_tools
    assert repl.renderer.events[-1] == ("result", "run_shell", True, True)


def test_permission_choice_falls_back_to_numeric_input(monkeypatch):
    from codepilot.ui.permissions import prompt_permission_choice

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert prompt_permission_choice() == "deny"


def test_permission_choice_uses_inline_prompt_session(monkeypatch):
    import codepilot.ui.permissions as permissions

    calls = []

    class FakePromptSession:
        def __init__(self):
            calls.append(("init",))

        def prompt(self, message, **kwargs):
            calls.append(("prompt", message, kwargs))
            return "3"

    def forbidden_dialog(*_args, **_kwargs):
        raise AssertionError("fullscreen dialog should not be used")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("prompt_toolkit.PromptSession", FakePromptSession)
    monkeypatch.setattr("prompt_toolkit.shortcuts.radiolist_dialog", forbidden_dialog)

    assert permissions.prompt_permission_choice() == "always"
    assert calls[0] == ("init",)
    _, message, kwargs = calls[1]
    assert "请选择" in message
    assert kwargs["multiline"] is False
    assert kwargs["bottom_toolbar"] is not None
    assert kwargs["reserve_space_for_menu"] == 0
    toolbar_styles = [style for style, _text in kwargs["bottom_toolbar"]()]
    assert all(style.startswith("class:") for style in toolbar_styles)


def test_numeric_reply_expands_when_previous_ai_asked_numbered_choice():
    previous = AIMessage(content=(
        "建议操作（任选）：\n\n"
        "1 连上公司 VPN / 内网后重试 git fetch origin develop && git checkout develop && git pull\n"
        "2 仅切到本地已有的 develop（不拉新）：git checkout develop\n"
        "3 检查代理/remote：git remote -v、git config --get http.proxy\n\n"
        "需要我执行其中哪一个？"
    ))

    expanded = expand_numbered_choice_reply("2", [previous])

    assert expanded != "2"
    assert "用户选择了上一条建议操作中的第 2 项" in expanded
    assert "请根据上一条消息中的编号选项执行该项" in expanded


def test_numeric_reply_is_unchanged_without_previous_choice_prompt():
    expanded = expand_numbered_choice_reply("2", [AIMessage(content="Hello!")])

    assert expanded == "2"
