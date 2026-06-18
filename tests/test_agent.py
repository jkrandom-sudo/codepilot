import os


from codepilot.agent.state import AgentState
from codepilot.agent.prompts import build_system_prompt, AGENT_INSTRUCTIONS
from codepilot.context.selector import parse_references


class TestAgentState:
    def test_state_structure(self):
        state: AgentState = {
            "messages": [],
            "working_dir": "/tmp",
            "files_context": [],
            "task_type": "",
            "agent_name": "build",
            "session_id": "test",
        }
        assert state["agent_name"] == "build"
        assert state["messages"] == []


class TestPrompts:
    def test_build_system_prompt_build_confirm(self):
        prompt = build_system_prompt(agent_name="build", confirm=True)
        assert "CONFIRM" in prompt
        assert "CodePilot" in prompt

    def test_build_system_prompt_build_auto(self):
        prompt = build_system_prompt(agent_name="build", confirm=False)
        assert "AUTO" in prompt

    def test_build_system_prompt_plan(self):
        prompt = build_system_prompt(agent_name="plan")
        assert "Plan mode" in prompt or "read-only" in prompt or "READ-ONLY" in prompt

    def test_agent_instructions_all_defined(self):
        assert "confirm" in AGENT_INSTRUCTIONS
        assert "auto" in AGENT_INSTRUCTIONS
        assert "readonly" in AGENT_INSTRUCTIONS

    def test_system_prompt_contains_language_instruction(self):
        prompt = build_system_prompt(agent_name="build")
        assert "语言" in prompt or "Language" in prompt
        assert "中文" in prompt

    def test_system_prompt_contains_retry_guidance(self):
        prompt = build_system_prompt(agent_name="build")
        assert "Retry" in prompt or "重试" in prompt or "失败" in prompt
        assert "换策略" in prompt

    def test_system_prompt_contains_github_hints(self):
        prompt = build_system_prompt(agent_name="build")
        assert "run_shell" in prompt or "GitHub" in prompt or "github" in prompt

    def test_system_prompt_contains_project_analysis(self):
        prompt = build_system_prompt(agent_name="build")
        assert "Project analysis" in prompt
        assert "Deep context mode" in prompt

    def test_system_prompt_cross_checks_stale_reports(self):
        prompt = build_system_prompt(agent_name="build")
        assert "stale/resolved" in prompt
        assert "cross-check" in prompt
        assert "source/config/tests" in prompt
        assert "The report IS the answer" not in prompt
        assert "NEVER read agent source code" not in prompt

    def test_system_prompt_contains_tool_efficiency(self):
        prompt = build_system_prompt(agent_name="build")
        assert "Tool selection" in prompt or "Tool efficiency" in prompt
        assert "read_file" in prompt
        assert "grep" in prompt

    def test_system_prompt_iteration_budget_matches(self):
        prompt = build_system_prompt(agent_name="build")
        assert "迭代预算有限" in prompt

    def test_runtime_prompt_uses_effective_task_budget(self):
        from codepilot.agent.nodes import HARD_ITERATION_LIMIT, TASK_ITERATION_LIMITS, build_system_prompt_with_context
        from codepilot.agent.registry import AgentRegistry

        state: AgentState = {
            "messages": [],
            "working_dir": "/tmp",
            "files_context": [],
            "task_type": "file_edit",
            "agent_name": "build",
            "session_id": "test",
        }
        agent_def = AgentRegistry().get_or_default("build")
        iteration_limit = TASK_ITERATION_LIMITS["file_edit"]
        prompt = build_system_prompt_with_context(
            "Base prompt",
            state,
            agent_def=agent_def,
            iteration_count=iteration_limit - 1,
            total_tool_invocations=20,
            iteration_limit=iteration_limit,
            file_summaries={},
        )

        assert f"{iteration_limit - 1}/{iteration_limit} tool rounds used" in prompt
        assert f"hard limit: {HARD_ITERATION_LIMIT}" in prompt

    def test_runtime_prompt_warns_test_evaluation_requires_real_results(self):
        from codepilot.agent.nodes import build_system_prompt_with_context
        from codepilot.agent.registry import AgentRegistry

        state: AgentState = {
            "messages": [],
            "working_dir": "/tmp",
            "files_context": [],
            "task_type": "test_evaluation",
            "agent_name": "build",
            "session_id": "test",
        }
        agent_def = AgentRegistry().get_or_default("build")
        prompt = build_system_prompt_with_context(
            "Base prompt",
            state,
            agent_def=agent_def,
            iteration_count=3,
            total_tool_invocations=4,
            iteration_limit=20,
            file_summaries={},
        )

        assert "test/evaluation task" in prompt
        assert "real tool result" in prompt
        assert "do not produce" in prompt

    def test_runtime_prompt_enables_deep_context_for_complex_tasks(self):
        from codepilot.agent.nodes import TASK_ITERATION_LIMITS, build_system_prompt_with_context
        from codepilot.agent.registry import AgentRegistry

        state: AgentState = {
            "messages": [],
            "working_dir": "/tmp",
            "files_context": [],
            "task_type": "project_analysis",
            "agent_name": "plan-execute",
            "session_id": "test",
        }
        agent_def = AgentRegistry().get_or_default("plan-execute")
        prompt = build_system_prompt_with_context(
            "Base prompt",
            state,
            agent_def=agent_def,
            iteration_count=0,
            total_tool_invocations=0,
            iteration_limit=TASK_ITERATION_LIMITS["project_analysis"],
            file_summaries={},
        )

        assert "Deep context mode" in prompt
        assert "read multiple relevant source files" in prompt
        assert "Token target" in prompt

    def test_system_prompt_requires_post_edit_verification(self):
        """A core part of closing the gap to Claude Code: the model must run
        verification (tests/lint/re-read) after edits, not skip straight to
        the summary."""
        prompt = build_system_prompt(agent_name="build")
        assert "VERIFY" in prompt
        # Re-reading after an edit is now an expected step, not banned.
        assert "Re-reading a file AFTER you edited it" in prompt
        # Tests / lint after edits are encouraged, not "optional".
        assert "Run tests / lint" in prompt or "Running tests and lint after edits" in prompt

    def test_system_prompt_no_longer_bans_re_reads_outright(self):
        """Old prompt told the model 'AT MOST ONCE' and 'NEVER re-read', which
        was the leading driver of premature stops in our LangSmith data."""
        prompt = build_system_prompt(agent_name="build")
        assert "AT MOST ONCE" not in prompt
        assert "NEVER re-read" not in prompt
        assert "trust your edits" not in prompt

    def test_system_prompt_distinguishes_simple_vs_engineering_stop_conditions(self):
        prompt = build_system_prompt(agent_name="build")
        assert "When to STOP" in prompt
        assert "I shipped a fix AND verified it" in prompt or "shipped" in prompt.lower()


class TestIterationBudgets:
    def test_iteration_budgets_are_lifted_for_complex_tasks(self):
        """Budgets were raised to give the model room to run verification
        after edits without hitting the cap."""
        from codepilot.agent.nodes import TASK_ITERATION_LIMITS

        # No regressions vs the prior floor; complex tasks have headroom.
        assert TASK_ITERATION_LIMITS["file_edit"] >= 100
        assert TASK_ITERATION_LIMITS["project_analysis"] >= 80
        assert TASK_ITERATION_LIMITS["test_evaluation"] >= 120
        # Simple lookups still get a small budget — that's fine.
        assert TASK_ITERATION_LIMITS["general_question"] <= 12

    def test_truncate_response_caps_lifted_for_complex_tasks(self):
        """Truncation caps doubled for high-tool-count tasks so structured
        evaluation summaries can actually fit."""
        from codepilot.agent.nodes import truncate_response
        from codepilot.agent.registry import AgentRegistry
        from langchain_core.messages import AIMessage

        agent_def = AgentRegistry().get_or_default("build")

        long_content = "x" * 25000
        msg = AIMessage(content=long_content)
        out = truncate_response(msg, agent_def=agent_def, total_tool_invocations=15)
        # 15 tools => limit >= 22000, so we should NOT be cut to the old 18000 limit.
        assert len(out.content) > 18000

        # 0 tools (simple Q&A) still gets the small cap.
        out_short = truncate_response(msg, agent_def=agent_def, total_tool_invocations=0)
        assert len(out_short.content) <= 11000  # 10000 cap + truncation tail

    def test_explore_agent_prompt_lifts_max_tool_calls(self):
        """The explore subagent used to hard-cap at 6 tool calls — now it
        should accept 8-15 for cross-module investigations."""
        from codepilot.agent.prompts import EXPLORE_AGENT_PROMPT
        assert "Maximum 6 tool calls" not in EXPLORE_AGENT_PROMPT
        assert "8-15" in EXPLORE_AGENT_PROMPT



class TestReferenceParser:
    def test_file_reference(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("print('test')")
        os.environ["CODEPILOT_WORKING_DIR"] = str(tmp_path)

        clean, content = parse_references(f"@file {test_file}")
        assert "test.py" in content or "print" in content
        del os.environ["CODEPILOT_WORKING_DIR"]

    def test_dir_reference(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")

        clean, content = parse_references(f"@dir {tmp_path}")
        assert "a.py" in content
        assert "b.py" in content

    def test_no_references(self):
        clean, content = parse_references("just a normal message")
        assert clean == "just a normal message"
        assert content == ""

    def test_inline_file_reference(self, tmp_path):
        test_file = tmp_path / "main.py"
        test_file.write_text("def main(): pass")

        clean, content = parse_references("help me with @main.py")
        assert "main.py" in clean or "main" in content
