from langchain_core.messages import ToolMessage

from codepilot.ui.repl import REPL, is_tool_result_error, resolve_tool_message, tool_result_status


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
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    allowed = repl._ask_permission("build", "run_shell", {"command": "pytest"})

    assert allowed is True
    assert repl.renderer.events[0] == ("stop", "activity")
    assert repl.renderer.events[1][0] == "choice"
    assert repl.renderer.events[-1][0] == "resume"
