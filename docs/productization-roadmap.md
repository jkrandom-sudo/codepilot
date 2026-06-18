# CodePilot Productization Roadmap

CodePilot is a Python + LangChain + LangGraph CLI coding agent. This roadmap turns it from a capable local project into a tool that is easier to install, diagnose, use safely, evaluate, and release.

## Phase 1: Foundation

**Goal:** Make CodePilot installable, diagnosable, and understandable for first-time users.

**Key work:**

- Keep GitHub, uv, pipx, and editable install paths documented.
- Provide `codepilot --doctor` for environment and configuration checks.
- Document default config, provider API key environment variables, MCP optional dependencies, and development commands.
- Keep README focused on the fastest path from install to first successful run.

**Success criteria:**

- A new user can install CodePilot and run `codepilot --doctor` before calling a model.
- Missing API keys are reported without leaking secrets.
- Optional MCP setup problems are warnings, not blockers.
- Source checkout users can see the local test and lint commands.

**Verification:**

```bash
codepilot --doctor
pytest tests/ -q
ruff check codepilot evals tests
```

## Phase 2: Safety

**Goal:** Make local execution safer and easier to reason about.

**Key work:**

- Document and tighten read, write, shell, MCP, and subagent permission boundaries.
- Expand dangerous command explanations so blocked commands teach the safer alternative.
- Keep sensitive path protection explicit for files such as `.env`, credentials, tokens, SSH keys, and local config.
- Make `--confirm`, `--no-confirm`, readonly agents, and subagents behavior easy to compare.

**Success criteria:**

- Users understand which operations require confirmation and why.
- Auto mode still blocks destructive commands and sensitive file access.
- Permission failures include clear alternatives.

**Verification:**

```bash
pytest tests/test_tools.py -q
pytest tests/test_agent.py -q
```

## Phase 3: Capability

**Goal:** Improve CodePilot's ability to understand and change real repositories.

**Key work:**

- Add a repo map or richer context selection layer inspired by aider.
- Make plan-execute plans trackable during execution.
- Improve test-loop behavior so failures are summarized and fed back reliably.
- Capture trajectories for debugging and later evaluation.

**Success criteria:**

- Multi-file tasks gather enough context before editing.
- Plan-execute runs expose plan progress and final verification status.
- Failed tests produce actionable next steps instead of generic summaries.

**Verification:**

```bash
python -m evals.run_local --model <provider/model>
pytest tests/test_scenarios.py -q
```

## Phase 4: Distribution & Evaluation

**Goal:** Make CodePilot releasable and measurable.

**Key work:**

- Maintain a release checklist for versioning, packaging, tests, lint, docs, and secrets.
- Add CI for tests, lint, and package build checks.
- Build local golden tasks and benchmark datasets.
- Compare model/provider performance with stored metrics and LangSmith traces.

**Success criteria:**

- A release can be prepared using a repeatable checklist.
- Package contents include built-in skills and documentation.
- Regressions are caught by tests or golden tasks before release.

**Verification:**

```bash
python -m build
pytest tests/ -q
ruff check codepilot evals tests
```
