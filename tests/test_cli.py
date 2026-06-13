import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from codepilot.cli import (
    _format_non_interactive_error,
    _invoke_graph_with_heartbeat,
    _non_interactive_output,
    _non_interactive_task_metrics,
    _run_non_interactive,
)


class ExplodingRegistry:
    def get_llm(self, _model: str):
        raise AssertionError("chat/help prompts should not initialize an LLM")


class SlowGraph:
    def invoke(self, _graph_input: dict, config: dict | None = None):
        time.sleep(0.03)
        return {"messages": [AIMessage(content="done")]}


class FakeRegistry:
    def get_llm(self, _model: str):
        return object()


def test_non_interactive_output_returns_only_final_ai_message():
    messages = [
        HumanMessage(content="fix the bug"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "run_shell", "args": {}}]),
        ToolMessage(content="failing test output", tool_call_id="tc1"),
        AIMessage(content="Fixed the bug and tests pass."),
    ]

    assert _non_interactive_output(messages) == ["Fixed the bug and tests pass."]


def test_non_interactive_output_ignores_intermediate_plan_when_final_exists():
    messages = [
        HumanMessage(content="fix the bug"),
        AIMessage(content="[Plan-and-Execute Plan]\n1. Inspect\n2. Execute"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {}}]),
        ToolMessage(content="README content", tool_call_id="tc1"),
        AIMessage(content="Final answer"),
    ]

    assert _non_interactive_output(messages) == ["Final answer"]


def test_non_interactive_output_ignores_human_messages():
    messages = [
        HumanMessage(content="hello"),
        AIMessage(content="Hello!"),
    ]

    assert _non_interactive_output(messages) == ["Hello!"]


def test_non_interactive_help_short_circuits_before_llm(capsys):
    _run_non_interactive(ExplodingRegistry(), "test/model", "build", True, "help")

    out = capsys.readouterr().out
    assert "CodePilot" in out
    assert "analyze" in out.lower()


def test_non_interactive_identity_short_circuits_before_llm(capsys):
    _run_non_interactive(ExplodingRegistry(), "test/model", "build", True, "你是谁")

    out = capsys.readouterr().out
    assert "CodePilot" in out
    assert "AI 编程助手" in out


def test_non_interactive_auto_routes_complex_task_to_plan_execute(monkeypatch, capsys):
    captured = {}

    def fake_build_agent_graph(_llm, agent_name: str, **_kwargs):
        captured["agent_name"] = agent_name
        return SlowGraph()

    monkeypatch.setattr("codepilot.agent.graph.build_agent_graph", fake_build_agent_graph)

    _run_non_interactive(
        FakeRegistry(),
        "test/model",
        "auto",
        True,
        "评估当前项目效果，给出优化方案，根据方案进行优化，运行测试并提交",
    )

    captured_io = capsys.readouterr()
    assert captured["agent_name"] == "plan-execute"
    assert "auto→plan-execute" in captured_io.err
    assert "done" in captured_io.out


def test_invoke_graph_with_heartbeat_emits_progress(capsys):
    result = _invoke_graph_with_heartbeat(
        SlowGraph(),
        {"messages": []},
        {},
        heartbeat_interval=0.01,
    )

    captured = capsys.readouterr()
    assert result["messages"][-1].content == "done"
    assert "仍在运行" in captured.err


def test_format_non_interactive_error_for_quota_exceeded():
    err = Exception("coding_plan_month_quota_exceeded: quota has been exceeded")

    message = _format_non_interactive_error(err)

    assert "配额已用尽" in message
    assert "traceback" not in message.lower()


def test_non_interactive_task_metrics_counts_tools_and_tests():
    messages = [
        AIMessage(content="", tool_calls=[{
            "id": "tc1",
            "name": "run_shell",
            "args": {"command": "pytest tests/test_cli.py -q"},
        }]),
        ToolMessage(content="1 passed in 0.01s", tool_call_id="tc1"),
        AIMessage(content="done", response_metadata={"token_usage": {"total_tokens": 12}}),
    ]

    metrics = _non_interactive_task_metrics(messages, elapsed=2.34)

    assert metrics["iteration_count"] == 1
    assert metrics["tool_call_count"] == 1
    assert metrics["tool_distribution"] == {"run_shell": 1}
    assert metrics["did_test"] is True
    assert metrics["tests_passed"] is True
    assert metrics["outcome"] == "success"
    assert metrics["total_tokens"] == 12


def test_non_interactive_task_metrics_counts_input_and_output_tokens():
    messages = [
        AIMessage(
            content="step",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ),
        AIMessage(
            content="done",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 7,
                    "total_tokens": 27,
                }
            },
        ),
    ]

    metrics = _non_interactive_task_metrics(messages, elapsed=1.0)

    assert metrics["input_tokens"] == 30
    assert metrics["output_tokens"] == 12
    assert metrics["total_tokens"] == 42
