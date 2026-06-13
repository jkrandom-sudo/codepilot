from langchain_core.messages import AIMessage, ToolMessage

from codepilot.agent.context_manager import (
    AgentContextManager,
    MAX_TOOL_RESULT_CHARS,
    MIN_TOOL_RESULT_CHARS,
)


class DummyStore:
    def __init__(self):
        self.saved = []

    def truncate_and_save(self, content, tool_call_id, max_lines=100, max_chars=1500):
        self.saved.append((content, tool_call_id, max_lines, max_chars))
        return content[:max_chars] + "\n[Output truncated]", "/tmp/full.txt"


def test_context_manager_extracts_read_file_summary():
    manager = AgentContextManager()
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "README.md"}}],
        ),
        ToolMessage(content="1: # CodePilot\n2: CLI agent\n3: details", tool_call_id="tc1"),
    ]

    summaries = manager.extract_file_summaries(messages, ["README.md"])

    assert summaries == {"README.md": "# CodePilot | CLI agent | details"}


def test_context_manager_summary_prefers_structural_code_lines():
    manager = AgentContextManager()
    content = "\n".join([
        "1: # generated header",
        "2: # license",
        "3: ",
        "4: import os",
        "5: from pathlib import Path",
        "6: VALUE = 42",
        "7: ",
        "8: class Runner:",
        "9:     def start(self):",
        "10:         pass",
        "11: async def main():",
    ])
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "runner.py"}}],
        ),
        ToolMessage(content=content, tool_call_id="tc1"),
    ]

    summaries = manager.extract_file_summaries(messages, ["runner.py"])

    summary = summaries["runner.py"]
    assert "import os" in summary
    assert "class Runner" in summary
    assert "def start" in summary
    assert "async def main" in summary


def test_context_manager_renders_files_context_block():
    manager = AgentContextManager()

    block = manager.render_files_context("README.md".split(), {"README.md": "# CodePilot"})

    assert "FILES ALREADY IN CONTEXT" in block
    assert "README.md: # CodePilot" in block
    assert "Do NOT re-read" in block


def test_context_manager_tool_result_limit_scales_with_context_window():
    small = AgentContextManager(context_window=16_000)
    medium = AgentContextManager(context_window=128_000)
    large = AgentContextManager(context_window=1_000_000)

    assert small.tool_result_char_limit() > MIN_TOOL_RESULT_CHARS
    assert medium.tool_result_char_limit() > small.tool_result_char_limit()
    assert large.tool_result_char_limit() == MAX_TOOL_RESULT_CHARS
    assert large.tool_result_line_limit() > small.tool_result_line_limit()


def test_context_manager_compresses_tool_results_with_dynamic_limit():
    store = DummyStore()
    manager = AgentContextManager(context_window=16_000, truncation_store=store)
    content = "x" * (manager.tool_result_char_limit() + 100)
    messages = [
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {}}]),
        ToolMessage(content=content, tool_call_id="tc1"),
    ]

    result = manager.compress_tool_results(messages)

    assert isinstance(result[1], ToolMessage)
    assert "[Output truncated]" in result[1].content
    assert store.saved[0][3] == manager.tool_result_char_limit()
    assert store.saved[0][2] == manager.tool_result_line_limit()
