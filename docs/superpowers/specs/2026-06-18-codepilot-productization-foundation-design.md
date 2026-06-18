# CodePilot Productization Foundation Design

## Overview

CodePilot already has a working LangGraph-based coding agent, permission rules, skills, MCP hooks, session storage, and tests. The next productization step is to make the project easier to install, diagnose, explain, and prepare for release without changing the core agent loop.

This design covers the first Foundation slice: a productization roadmap, a release checklist, a `codepilot --doctor` self-check command, README updates, and tests for the new diagnostic path.

## Goals

- Give users a clear technical roadmap for CodePilot as a self-developed coding agent.
- Add a fast diagnostic command users can run after installation.
- Improve README onboarding by making doctor and productization docs discoverable.
- Add release preparation guidance without introducing CI or publishing automation yet.
- Keep the implementation scoped, testable, and independent from model calls.

## Non-goals

- Do not refactor the CLI into a Click command group.
- Do not change the LangGraph agent loop, provider runtime, permission semantics, or tool execution logic.
- Do not add new runtime dependencies.
- Do not modify user configuration files under `~/.codepilot`.
- Do not print secrets, API keys, LangSmith keys, or local credential contents.
- Do not add PyPI publishing automation or CI workflow changes in this slice.

## Roadmap document

Add `docs/productization-roadmap.md` with four phases:

1. Foundation: installation, configuration, diagnostics, and basic release readiness.
2. Safety: stronger permission boundaries, dangerous command explanations, sensitive path protection, and confirmation behavior documentation.
3. Capability: repo map, context selection, plan execution tracking, test loops, and trajectory capture.
4. Distribution & Evaluation: release checklist, packaging verification, golden tasks, benchmarks, model comparisons, and LangSmith metrics.

Each phase should include goals, key work, success criteria, and verification commands so the roadmap is actionable rather than aspirational.

## Doctor command

Add a top-level `--doctor` option to the existing Click command:

```bash
codepilot --doctor
```

This is intentionally an option rather than a `codepilot doctor` subcommand because the current CLI is a single Click command. Adding an option avoids restructuring the CLI.

The command should call a new `codepilot.doctor` module and exit before model/provider initialization that would perform real LLM work.

### Checks

`--doctor` should report these categories:

- Python runtime: version, executable, and virtual environment status.
- CodePilot package: current version and core module importability.
- Configuration: whether `~/.codepilot/config.yaml` exists, whether `load_config()` succeeds, and whether the default provider/model is defined.
- Provider credentials: whether the default provider has an API key from config or the expected `CODEPILOT_<PROVIDER>_API_KEY` environment variable. The value must never be printed.
- Working directory: current directory, Git repository detection, and dirty worktree warning when Git is available.
- External tools: availability of `git` and `npx`; missing `npx` is a warning because MCP is optional.
- Optional MCP SDK: import availability; missing SDK is a warning because MCP is optional.
- Development hints: when running inside the CodePilot source checkout, show useful verification commands.

### Result severity

Use three severities:

- OK: check passed.
- WARN: optional or advisory issue.
- FAIL: CodePilot is unlikely to work for normal model-backed use.

The overall exit code should be 1 if any FAIL exists, otherwise 0.

Missing API key for the default provider is a FAIL. Missing MCP SDK, missing `npx`, not being in a Git repo, or having a dirty worktree are WARN items.

### Output format

Keep output plain text for easy testing and copy/paste:

```text
CodePilot Doctor

[OK] Python: 3.11.x
[OK] Config: /Users/.../.codepilot/config.yaml
[WARN] MCP SDK: optional dependency not installed
[FAIL] API key: CODEPILOT_ARC_API_KEY missing
```

The doctor module may internally use a small result data structure so tests can validate logic without snapshotting the full CLI output.

## Documentation updates

Update `README.md` to include:

- `codepilot --doctor` in quick start after installation.
- A short productization roadmap section linking to `docs/productization-roadmap.md`.
- A release preparation link to `docs/release-checklist.md`.
- Development commands that include doctor, pytest, and ruff.

Add `docs/release-checklist.md` with checks for:

- Version number and changelog/release notes.
- `codepilot --doctor`.
- `pytest tests/ -q`.
- `ruff check codepilot evals tests`.
- Package build verification.
- Built-in skills included in wheel/sdist.
- README installation commands still valid.
- No committed secrets, API keys, access tokens, or machine-specific paths.

## Testing

Add `tests/test_doctor.py` and minimal CLI coverage.

Tests should cover:

- Doctor returns structured results.
- Missing default provider API key produces a FAIL and exit code 1.
- Optional MCP SDK absence is WARN only.
- Output does not include API key values.
- Config loading errors produce a FAIL item.
- `codepilot --doctor` prints `CodePilot Doctor` and exits consistently with the overall status.

## Implementation boundaries

- The doctor command should not call an LLM.
- The doctor command should not require valid network access.
- The doctor command should not write files.
- The doctor command should not mutate environment variables.
- The doctor command should not depend on a real user config in tests; tests should monkeypatch config paths/loading or call lower-level helpers.

## Success criteria

The slice is complete when:

- `codepilot --doctor` exists and produces useful OK/WARN/FAIL output.
- Missing required provider credentials fail safely without leaking secrets.
- README points users to doctor, roadmap, and release checklist.
- The roadmap and release checklist are committed as project docs.
- New and existing tests pass, or any pre-existing/environmental failures are clearly reported.
