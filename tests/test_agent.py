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
        assert "SYNTHESIZE" in prompt

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
