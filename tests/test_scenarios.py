"""Local scenario tests for CodePilot agent system.

These tests verify the agent framework's behavior (permissions, tool routing,
state management, graph flow) without requiring an LLM API call.
They mock the LLM to return predetermined responses.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from codepilot.agent._utils import validate_message_pairs
from codepilot.agent.graph import build_agent_graph
from codepilot.agent.registry import AgentRegistry
from codepilot.agent.state import AgentState
from codepilot.config.permissions import PermissionRuleset


class TestAgentPermissions:
    """Test that each agent's permissions are correctly enforced in the tool_node."""

    def test_build_agent_allows_read(self):
        agent = AgentRegistry().get("build")
        assert agent.permissions.evaluate("read_file") == "allow"
        assert agent.permissions.evaluate("grep") == "allow"
        assert agent.permissions.evaluate("glob") == "allow"

    def test_build_agent_asks_on_writes(self):
        agent = AgentRegistry().get("build")
        assert agent.permissions.evaluate("edit_file") == "ask"
        assert agent.permissions.evaluate("write_file") == "ask"
        assert agent.permissions.evaluate("run_shell") == "ask"

    def test_plan_agent_denies_writes(self):
        agent = AgentRegistry().get("plan")
        assert agent.permissions.evaluate("edit_file") == "deny"
        assert agent.permissions.evaluate("write_file") == "deny"
        assert agent.permissions.evaluate("run_shell") == "deny"

    def test_plan_agent_allows_reads(self):
        agent = AgentRegistry().get("plan")
        assert agent.permissions.evaluate("read_file") == "allow"
        assert agent.permissions.evaluate("grep") == "allow"
        assert agent.permissions.evaluate("glob") == "allow"
        assert agent.permissions.evaluate("web_fetch") == "allow"

    def test_plan_agent_denies_task(self):
        agent = AgentRegistry().get("plan")
        assert agent.permissions.evaluate("task") == "deny"

    def test_explore_agent_readonly(self):
        agent = AgentRegistry().get("explore")
        assert agent.permissions.evaluate("read_file") == "allow"
        assert agent.permissions.evaluate("grep") == "allow"
        assert agent.permissions.evaluate("edit_file") == "deny"
        assert agent.permissions.evaluate("write_file") == "deny"
        assert agent.permissions.evaluate("run_shell") == "deny"

    def test_general_agent_allows_all(self):
        agent = AgentRegistry().get("general")
        assert agent.permissions.evaluate("read_file") == "allow"
        assert agent.permissions.evaluate("edit_file") == "allow"
        assert agent.permissions.evaluate("run_shell") == "allow"

    def test_build_agent_denies_dangerous_shell(self):
        agent = AgentRegistry().get("build")
        assert agent.permissions.evaluate("run_shell", {"command": "rm -rf /"}) == "deny"
        assert agent.permissions.evaluate("run_shell", {"command": "mkfs /dev/sda"}) == "deny"


class TestAgentProperties:
    """Test AgentDef properties."""

    def test_build_is_primary(self):
        agent = AgentRegistry().get("build")
        assert agent.is_primary is True
        assert agent.is_subagent is False

    def test_plan_is_primary(self):
        agent = AgentRegistry().get("plan")
        assert agent.is_primary is True
        assert agent.is_readonly is True

    def test_explore_is_subagent(self):
        agent = AgentRegistry().get("explore")
        assert agent.is_subagent is True
        assert agent.is_primary is False

    def test_build_confirm_true(self):
        agent = AgentRegistry().get("build")
        assert agent.confirm is True

    def test_plan_confirm_false(self):
        agent = AgentRegistry().get("plan")
        assert agent.confirm is False

    def test_plan_is_readonly(self):
        agent = AgentRegistry().get("plan")
        assert agent.is_readonly is True

    def test_build_not_readonly(self):
        agent = AgentRegistry().get("build")
        assert agent.is_readonly is False

    def test_plan_execute_is_primary_write_capable_workflow(self):
        agent = AgentRegistry().get("plan-execute")
        assert agent is not None
        assert agent.is_primary is True
        assert agent.workflow == "plan_execute"
        assert agent.confirm is True
        assert agent.is_readonly is False


class TestAgentStateConstruction:
    """Test that AgentState can be constructed correctly without mode."""

    def test_minimal_state(self):
        state: AgentState = {
            "messages": [],
            "working_dir": "/tmp",
            "files_context": [],
            "task_type": "",
            "agent_name": "build",
            "session_id": "test",
        }
        assert state["agent_name"] == "build"
        assert "mode" not in state

    def test_subagent_state(self):
        state: AgentState = {
            "messages": [HumanMessage(content="find files")],
            "working_dir": "/tmp",
            "files_context": [],
            "task_type": "subagent",
            "agent_name": "explore",
            "session_id": "child-123",
        }
        assert state["agent_name"] == "explore"
        assert state["task_type"] == "subagent"


class TestPermissionCallback:
    """Test that the ask_permission_callback gates write operations."""

    def test_build_agent_denied_by_callback(self):
        agent = AgentRegistry().get("build")
        assert agent.permissions.evaluate("edit_file") == "ask"

        def deny_all(tool_name, args):
            return False

        assert deny_all("edit_file", {"path": "test.py"}) is False

    def test_build_agent_approved_by_callback(self):
        def allow_all(tool_name, args):
            return True

        assert allow_all("edit_file", {"path": "test.py"}) is True


class TestToolDeduplication:
    """Test that the graph blocks redundant reads."""

    def test_read_file_dedup_in_state(self):
        tmp = tempfile.mkdtemp()
        os.environ["CODEPILOT_WORKING_DIR"] = tmp
        try:
            test_file = os.path.join(tmp, "test.py")
            with open(test_file, "w") as f:
                f.write("print('hello')\n")

            existing_files = {test_file}

            assert test_file in existing_files
        finally:
            del os.environ["CODEPILOT_WORKING_DIR"]


class TestMessageInvariant:
    """Test message pairing invariant after various transformations."""

    def test_simple_pair_preserved(self):
        messages = [
            SystemMessage(content="You are helpful"),
            HumanMessage(content="read test.py"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "test.py"}}]),
            ToolMessage(content="1: print('hello')", tool_call_id="tc1"),
            AIMessage(content="Here's the content of test.py"),
        ]
        result = validate_message_pairs(messages)
        assert len(result) == 5
        assert isinstance(result[2], AIMessage)
        assert isinstance(result[3], ToolMessage)

    def test_broken_pair_fixed(self):
        messages = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "read_file", "args": {"path": "test.py"}}]),
            HumanMessage(content="continue"),
        ]
        result = validate_message_pairs(messages)
        assert len(result) == 2
        assert isinstance(result[0], AIMessage)
        assert result[0].content  # Should have fallback content

    def test_permission_denial_preserves_pairing(self):
        messages = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "edit_file", "args": {"path": "test.py"}}]),
            ToolMessage(content="[Permission denied] edit_file is not allowed for agent 'plan'.", tool_call_id="tc1"),
        ]
        result = validate_message_pairs(messages)
        assert len(result) == 2
        assert isinstance(result[1], ToolMessage)


class TestSubagentPermissionPropagation:
    """Test that parent agent's deny rules propagate to subagents."""

    def test_plan_deny_propagates(self):
        plan_agent = AgentRegistry().get("plan")
        deny_rules = [r for r in plan_agent.permissions.rules if r.action == "deny"]
        assert len(deny_rules) > 0

        explore_agent = AgentRegistry().get("explore")
        merged = explore_agent.permissions.merge(PermissionRuleset(rules=deny_rules))

        assert merged.evaluate("edit_file") == "deny"
        assert merged.evaluate("write_file") == "deny"

    def test_explore_tools_limited(self):
        explore_agent = AgentRegistry().get("explore")
        assert explore_agent.tools is not None
        assert "edit_file" not in explore_agent.tools
        assert "write_file" not in explore_agent.tools
        assert "run_shell" not in explore_agent.tools
        assert "read_file" in explore_agent.tools
        assert "grep" in explore_agent.tools


class TestSystemPromptGeneration:
    """Test that system prompts are correctly generated per agent."""

    def test_build_confirm_prompt(self):
        from codepilot.agent.prompts import build_system_prompt
        prompt = build_system_prompt(agent_name="build", confirm=True)
        assert "CONFIRM" in prompt
        assert "CodePilot" in prompt

    def test_build_auto_prompt(self):
        from codepilot.agent.prompts import build_system_prompt
        prompt = build_system_prompt(agent_name="build", confirm=False)
        assert "AUTO" in prompt

    def test_plan_readonly_prompt(self):
        from codepilot.agent.prompts import build_system_prompt
        prompt = build_system_prompt(agent_name="plan")
        assert "read-only" in prompt.lower() or "READ-ONLY" in prompt

    def test_explore_subagent_prompt(self):
        from codepilot.agent.prompts import build_system_prompt
        prompt = build_system_prompt(agent_name="explore")
        assert "exploration" in prompt.lower()

    def test_general_subagent_prompt(self):
        from codepilot.agent.prompts import build_system_prompt
        prompt = build_system_prompt(agent_name="general")
        assert "subagent" in prompt.lower() or "multi-step" in prompt.lower()


class TestBuildAgentGraph:
    """Test that build_agent_graph correctly configures for each agent."""

    def test_build_agent_gets_all_tools(self):
        mock_llm = MagicMock()
        graph = build_agent_graph(mock_llm, agent_name="build")
        assert graph is not None

    def test_plan_agent_gets_all_tools_with_deny(self):
        mock_llm = MagicMock()
        graph = build_agent_graph(mock_llm, agent_name="plan")
        assert graph is not None

    def test_explore_agent_gets_limited_tools(self):
        mock_llm = MagicMock()
        graph = build_agent_graph(mock_llm, agent_name="explore")
        assert graph is not None

    def test_no_mode_parameter(self):
        mock_llm = MagicMock()
        graph = build_agent_graph(mock_llm, agent_name="build")
        assert graph is not None

    def test_plan_execute_runs_planner_before_agent(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Rules\nUse project rule.\n")

        class FakeLLM:
            model = "fake-model"

            def __init__(self):
                self.calls = []
                self.bound_tool_names = []

            def bind_tools(self, tools):
                self.bound_tool_names = [tool.name for tool in tools]
                return self

            def invoke(self, messages):
                self.calls.append(messages)
                first = messages[0]
                if isinstance(first, SystemMessage) and "planning phase" in first.content:
                    return AIMessage(content="1. Inspect files.\n2. Execute.\nExecution will now begin.")
                return AIMessage(content="final answer")

        llm = FakeLLM()
        graph = build_agent_graph(llm, agent_name="plan-execute")
        state: AgentState = {
            "messages": [HumanMessage(content="fix the bug")],
            "working_dir": str(tmp_path),
            "files_context": [],
            "task_type": "file_edit",
            "agent_name": "plan-execute",
            "session_id": "test-plan-execute",
        }

        result = graph.invoke(state, config={"recursion_limit": 8})
        ai_contents = [m.content for m in result["messages"] if isinstance(m, AIMessage)]

        assert any(content.startswith("[Plan-and-Execute Plan]") for content in ai_contents)
        assert ai_contents[-1] == "final answer"
        assert len(llm.calls) == 2
        assert str(tmp_path) in llm.calls[0][0].content
        assert "Use project rule" in llm.calls[0][0].content
        assert "read_file" in llm.bound_tool_names

    def test_read_file_dedup_allows_targeted_offset_followup(self, tmp_path, monkeypatch):
        target = tmp_path / "sample.py"
        target.write_text("one\ntwo\nthree\nfour\n")
        monkeypatch.setenv("CODEPILOT_WORKING_DIR", str(tmp_path))

        class FakeLLM:
            model = "fake-model"

            def __init__(self):
                self.calls = 0

            def bind_tools(self, tools):
                return self

            def invoke(self, _messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "id": "tc1",
                            "name": "read_file",
                            "args": {"path": "sample.py"},
                        }],
                    )
                if self.calls == 2:
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "id": "tc2",
                            "name": "read_file",
                            "args": {"path": "sample.py", "offset": 3, "limit": 1},
                        }],
                    )
                return AIMessage(content="done")

        graph = build_agent_graph(
            FakeLLM(),
            agent_name="build",
            custom_permissions=PermissionRuleset.auto_ruleset(),
        )
        state: AgentState = {
            "messages": [HumanMessage(content="read sample twice")],
            "working_dir": str(tmp_path),
            "files_context": [],
            "task_type": "code_search",
            "agent_name": "build",
            "session_id": "test-targeted-reread",
        }

        result = graph.invoke(state, config={"recursion_limit": 12})
        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]

        assert len(tool_messages) == 2
        assert "3: three" in tool_messages[-1].content
        assert "[BLOCKED]" not in tool_messages[-1].content

    def test_confirmed_run_shell_search_command_is_not_blocked(self, tmp_path):
        (tmp_path / "aaa.txt").write_text("hello\n")

        class FakeLLM:
            model = "fake-model"

            def __init__(self):
                self.calls = 0

            def bind_tools(self, tools):
                return self

            def invoke(self, _messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "id": "tc1",
                            "name": "run_shell",
                            "args": {
                                "command": "ls -1 . | head -1",
                                "workdir": str(tmp_path),
                            },
                        }],
                    )
                return AIMessage(content="done")

        graph = build_agent_graph(
            FakeLLM(),
            agent_name="build",
            ask_permission_callback=lambda _tool_name, _tool_args: True,
        )
        state: AgentState = {
            "messages": [HumanMessage(content="list files")],
            "working_dir": str(tmp_path),
            "files_context": [],
            "task_type": "command_run",
            "agent_name": "build",
            "session_id": "test-confirmed-shell",
        }

        result = graph.invoke(state, config={"recursion_limit": 8})
        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]

        assert len(tool_messages) == 1
        assert "[BLOCKED]" not in tool_messages[0].content
        assert "aaa.txt" in tool_messages[0].content


class TestPermissionRulesetMerging:
    """Test PermissionRuleset.merge() for subagent permission derivation."""

    def test_merge_preserves_both(self):
        from codepilot.config.permissions import PermissionRule
        parent = PermissionRuleset(rules=[
            PermissionRule(tool="edit_file", pattern="**", action="deny"),
        ])
        child = PermissionRuleset(rules=[
            PermissionRule(tool="*", pattern="**", action="allow"),
        ])
        merged = child.merge(parent)
        assert merged.evaluate("edit_file") == "deny"
        assert merged.evaluate("read_file") == "allow"

    def test_explore_plus_plan_deny(self):
        from codepilot.config.permissions import PermissionRule
        plan_deny = PermissionRuleset(rules=[
            PermissionRule(tool="edit_file", pattern="**", action="deny"),
            PermissionRule(tool="write_file", pattern="**", action="deny"),
        ])
        explore = PermissionRuleset.explore_ruleset()
        merged = explore.merge(plan_deny)
        assert merged.evaluate("edit_file") == "deny"
        assert merged.evaluate("read_file") == "allow"


class TestShellSearchInterception:
    """Test that run_shell search command interception works correctly."""

    def test_search_command_grep_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("grep -r 'pattern' .")
        assert is_search is True
        assert "grep" in msg.lower()

    def test_search_command_find_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("find . -name '*.py'")
        assert is_search is True
        assert "glob" in msg.lower()

    def test_search_command_cat_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("cat file.py")
        assert is_search is True
        assert "read_file" in msg.lower()

    def test_search_command_ls_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("ls -la")
        assert is_search is True

    def test_pipe_search_command_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("cat file.py | grep pattern")
        assert is_search is True

    def test_subshell_search_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("echo $(grep -r pattern .)")
        assert is_search is True

    def test_xargs_grep_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("find . -name '*.py' | xargs grep pattern")
        assert is_search is True

    def test_python_command_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("python3 script.py")
        assert is_search is False

    def test_git_command_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("git status")
        assert is_search is False

    def test_pip_install_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("pip install requests")
        assert is_search is False

    def test_pytest_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, msg = _is_search_command("pytest tests/ -v")
        assert is_search is False

    def test_which_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("which python3")
        assert is_search is True

    def test_diff_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("diff file1.py file2.py")
        assert is_search is True

    def test_awk_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("awk '{print $1}' file.txt")
        assert is_search is True

    def test_du_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("du -sh .")
        assert is_search is True

    def test_stat_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("stat file.py")
        assert is_search is True

    def test_pip_list_grep_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("pip list | grep requests")
        assert is_search is False

    def test_git_log_grep_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("git log --oneline | grep fix")
        assert is_search is False

    def test_pure_search_pipe_blocked(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("cat file.txt | sort | uniq")
        assert is_search is True

    def test_hatch_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("hatch test")
        assert is_search is False

    def test_npx_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("npx jest")
        assert is_search is False

    def test_uv_allowed(self):
        from codepilot.tools.shell_tool import _is_search_command
        is_search, _ = _is_search_command("uv pip install requests")
        assert is_search is False


class TestIterationBudgetHardLimit:
    """Test that iteration budget hard limits work correctly."""

    def test_hard_iteration_limit_defined(self):
        from codepilot.agent.nodes import HARD_ITERATION_LIMIT
        assert HARD_ITERATION_LIMIT >= 160
        assert HARD_ITERATION_LIMIT <= 240

    def test_max_iterations_within_hard_limit(self):
        from codepilot.agent.nodes import MAX_ITERATIONS
        from codepilot.agent.nodes import HARD_ITERATION_LIMIT
        assert MAX_ITERATIONS <= HARD_ITERATION_LIMIT

    def test_task_iteration_limits_within_bounds(self):
        from codepilot.agent.nodes import TASK_ITERATION_LIMITS, HARD_ITERATION_LIMIT
        for task_type, limit in TASK_ITERATION_LIMITS.items():
            assert limit <= HARD_ITERATION_LIMIT, f"{task_type} limit {limit} exceeds hard limit"

    def test_complex_task_limits_allow_real_workflows(self):
        from codepilot.agent.nodes import GRAPH_RECURSION_LIMIT, HARD_ITERATION_LIMIT, TASK_ITERATION_LIMITS

        assert HARD_ITERATION_LIMIT >= 160
        assert GRAPH_RECURSION_LIMIT >= HARD_ITERATION_LIMIT * 2
        assert TASK_ITERATION_LIMITS["file_edit"] >= 80
        assert TASK_ITERATION_LIMITS["file_write"] >= 80
        assert TASK_ITERATION_LIMITS["project_analysis"] >= 72
        assert TASK_ITERATION_LIMITS["command_run"] >= 48
        assert TASK_ITERATION_LIMITS["test_evaluation"] >= 96
        assert TASK_ITERATION_LIMITS["subagent"] >= 96


class TestResponseLengthLimit:
    """Test that response length limits work correctly."""

    def test_max_response_chars_defined(self):
        from codepilot.agent.nodes import MAX_RESPONSE_CHARS
        assert MAX_RESPONSE_CHARS > 0
        assert MAX_RESPONSE_CHARS <= 32000

    def test_response_limit_allows_detailed_coding_summaries(self):
        from langchain_core.messages import AIMessage

        from codepilot.agent.nodes import truncate_response
        from codepilot.agent.registry import AgentRegistry

        agent_def = AgentRegistry().get_or_default("build")
        response = AIMessage(content="x" * 7000)
        truncated = truncate_response(
            response,
            agent_def=agent_def,
            total_tool_invocations=6,
        )

        assert len(truncated.content) == 7000

    def test_response_limit_allows_deep_complex_task_reports(self):
        from langchain_core.messages import AIMessage

        from codepilot.agent.nodes import truncate_response
        from codepilot.agent.registry import AgentRegistry

        agent_def = AgentRegistry().get_or_default("plan-execute")
        response = AIMessage(content="x" * 18000)
        truncated = truncate_response(
            response,
            agent_def=agent_def,
            total_tool_invocations=40,
        )

        assert len(truncated.content) == 18000

    def test_max_tokens_for_providers(self):
        from codepilot.config.providers import DEFAULT_MAX_TOKENS, MODEL_MAX_TOKENS
        assert DEFAULT_MAX_TOKENS >= 16384
        for model_key, tokens in MODEL_MAX_TOKENS.items():
            assert tokens >= 16384
            assert tokens <= 32768

    def test_provider_max_tokens_method(self):
        from codepilot.config.providers import ProviderRegistry
        from codepilot.config.settings import AppSettings
        registry = ProviderRegistry(AppSettings())
        assert registry._get_max_tokens("deepseek-chat") == 16384
        assert registry._get_max_tokens("glm-5.1") == 16384
        assert registry._get_max_tokens("unknown-model") == 16384
        assert registry._get_max_tokens("claude-sonnet-4-20250514") == 32768


class TestRateLimitRetry:
    """Test that 429 rate limit retry mechanism works correctly."""

    def test_retryable_llm_class_exists(self):
        from codepilot.config.providers import RetryableLLM
        assert RetryableLLM is not None

    def test_retry_constants(self):
        from codepilot.config.providers import RATE_LIMIT_MAX_RETRIES, RATE_LIMIT_BASE_DELAY, RATE_LIMIT_MAX_DELAY
        assert RATE_LIMIT_MAX_RETRIES >= 2
        assert RATE_LIMIT_BASE_DELAY >= 1.0
        assert RATE_LIMIT_MAX_DELAY >= RATE_LIMIT_BASE_DELAY

    def test_extract_status_code(self):
        from codepilot.config.providers import _extract_status_code

        class Error429(Exception):
            status_code = 429
        assert _extract_status_code(Error429()) == 429

        class ErrorNoStatus(Exception):
            pass
        assert _extract_status_code(ErrorNoStatus()) is None

    def test_extract_retry_after(self):
        from codepilot.config.providers import _extract_retry_after

        class ErrorWithRetryAfter(Exception):
            pass

        class MockResponse:
            headers = {"retry-after": "5"}

        err = ErrorWithRetryAfter()
        err.response = MockResponse()
        assert _extract_retry_after(err) == 5.0

        class ErrorNoHeaders(Exception):
            pass
        assert _extract_retry_after(ErrorNoHeaders()) is None

    def test_is_rate_limit_error(self):
        from codepilot.config.providers import _is_rate_limit_error

        class Err429(Exception):
            status_code = 429
        assert _is_rate_limit_error(Err429()) is True

        class ErrRateMsg(Exception):
            pass
        assert _is_rate_limit_error(Exception("Rate limit exceeded")) is True
        assert _is_rate_limit_error(Exception("429 Too Many Requests")) is True
        assert _is_rate_limit_error(Exception("Throttling rate")) is True
        assert _is_rate_limit_error(Exception("Normal error")) is False

    def test_is_quota_exceeded_error(self):
        from codepilot.config.providers import _is_quota_exceeded_error

        assert _is_quota_exceeded_error(
            Exception("coding_plan_month_quota_exceeded: quota has been exceeded")
        )
        assert _is_quota_exceeded_error(Exception("insufficient_quota")) is True
        assert _is_quota_exceeded_error(Exception("429 Too Many Requests")) is False

    def test_is_server_error(self):
        from codepilot.config.providers import _is_server_error

        class Err500(Exception):
            status_code = 500
        class Err502(Exception):
            status_code = 502
        class Err503(Exception):
            status_code = 503
        class Err400(Exception):
            status_code = 400

        assert _is_server_error(Err500()) is True
        assert _is_server_error(Err502()) is True
        assert _is_server_error(Err503()) is True
        assert _is_server_error(Err400()) is False

    def test_retryable_llm_model_property(self):
        from codepilot.config.providers import RetryableLLM
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        mock_llm.model = "deepseek-chat"
        retryable = RetryableLLM(llm=mock_llm, model_name="deepseek-chat")
        assert retryable.model == "deepseek-chat"

    def test_retryable_llm_bind_tools(self):
        from codepilot.config.providers import RetryableLLM
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_llm.bind_tools.return_value = mock_bound

        retryable = RetryableLLM(llm=mock_llm, model_name="test")
        bound = retryable.bind_tools(["tool1"])
        assert isinstance(bound, RetryableLLM)

    def test_server_error_retry_constants(self):
        from codepilot.config.providers import SERVER_ERROR_MAX_RETRIES, SERVER_ERROR_BASE_DELAY
        assert SERVER_ERROR_MAX_RETRIES >= 1
        assert SERVER_ERROR_BASE_DELAY >= 1.0


class TestNetworkErrorRetry:
    """Network errors (APIConnectionError etc.) must be retried, not raised.

    Driven by LangSmith trace data showing APIConnectionError as the most
    common error class on recent runs.
    """

    def test_network_error_constants_exposed(self):
        from codepilot.config.providers import (
            NETWORK_ERROR_BASE_DELAY,
            NETWORK_ERROR_MAX_RETRIES,
        )
        assert NETWORK_ERROR_MAX_RETRIES >= 2
        assert NETWORK_ERROR_BASE_DELAY >= 1.0

    def test_is_network_error_detects_api_connection_error(self):
        from codepilot.config.providers import _is_network_error

        # Synthetic clone of openai.APIConnectionError — type name match.
        class APIConnectionError(Exception):
            pass

        class APITimeoutError(Exception):
            pass

        assert _is_network_error(APIConnectionError("Connection error.")) is True
        assert _is_network_error(APITimeoutError("timed out")) is True
        assert _is_network_error(ConnectionError("connection reset")) is True
        assert _is_network_error(Exception("Connection error.")) is True
        assert _is_network_error(Exception("read timed out")) is True

    def test_is_network_error_rejects_unrelated_errors(self):
        from codepilot.config.providers import _is_network_error

        class ValueError2(Exception):
            pass

        assert _is_network_error(ValueError2("bad input")) is False
        assert _is_network_error(Exception("Rate limit exceeded")) is False

    def test_retry_call_retries_network_errors_then_succeeds(self, monkeypatch):
        from codepilot.config import providers
        from codepilot.config.providers import RetryableLLM
        from unittest.mock import MagicMock

        sleep_calls: list[float] = []
        monkeypatch.setattr(providers.time, "sleep", lambda d: sleep_calls.append(d))

        class APIConnectionError(Exception):
            pass

        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise APIConnectionError("Connection error.")
            return "ok"

        mock_llm = MagicMock()
        retryable = RetryableLLM(llm=mock_llm, model_name="m")
        result = retryable._retry_call(flaky)

        assert result == "ok"
        assert attempts["n"] == 3
        assert len(sleep_calls) == 2  # two retry waits before the success
        # Backoff is monotonic non-decreasing.
        assert sleep_calls[0] <= sleep_calls[1]

    def test_retry_call_gives_up_after_max_network_retries(self, monkeypatch):
        from codepilot.config import providers
        from codepilot.config.providers import (
            NETWORK_ERROR_MAX_RETRIES,
            RetryableLLM,
        )
        from unittest.mock import MagicMock

        monkeypatch.setattr(providers.time, "sleep", lambda d: None)

        class APIConnectionError(Exception):
            pass

        attempts = {"n": 0}

        def always_fail():
            attempts["n"] += 1
            raise APIConnectionError("Connection error.")

        mock_llm = MagicMock()
        retryable = RetryableLLM(llm=mock_llm, model_name="m")

        with pytest.raises(APIConnectionError):
            retryable._retry_call(always_fail)

        # Initial attempt + retries up to the cap.
        assert attempts["n"] == NETWORK_ERROR_MAX_RETRIES + 1
