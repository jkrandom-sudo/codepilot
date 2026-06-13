from types import SimpleNamespace

from codepilot.ui.commands import CommandHandler, SLASH_COMMANDS


class FakeConsole:
    def __init__(self):
        self.messages = []

    def print(self, message="", *args, **kwargs):
        self.messages.append(str(message))


def test_slash_commands_include_init_and_plan_execute_help_text():
    assert "/init" in SLASH_COMMANDS
    assert "plan-execute" in SLASH_COMMANDS["/agent"]


def test_init_command_creates_agents_md(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    console = FakeConsole()
    handler = CommandHandler(SimpleNamespace(console=console))

    should_exit = handler.handle("/init")

    assert should_exit is False
    assert (tmp_path / "AGENTS.md").exists()
    assert "Created" in "".join(console.messages)
