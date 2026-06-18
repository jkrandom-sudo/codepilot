# CodePilot Productization Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a productization roadmap, release checklist, and `codepilot --doctor` diagnostic command that help users install, diagnose, and prepare CodePilot for release.

**Architecture:** Keep the existing single-command Click CLI and add `--doctor` as an early-exit option. Put all diagnostic logic in a focused `codepilot/doctor.py` module with small data structures that tests can call without invoking the CLI or any LLM. Documentation lives under `docs/` and README links users to the new productization flow.

**Tech Stack:** Python 3.11, Click, pytest, standard library only for doctor checks, existing CodePilot config/provider modules.

## Global Constraints

- Do not refactor the CLI into a Click command group.
- Do not change the LangGraph agent loop, provider runtime, permission semantics, or tool execution logic.
- Do not add new runtime dependencies.
- Do not modify user configuration files under `~/.codepilot`.
- Do not print secrets, API keys, LangSmith keys, or local credential contents.
- Do not add PyPI publishing automation or CI workflow changes in this slice.
- The doctor command must not call an LLM, require network access, write files, or mutate environment variables.

---

## File Structure

- Create `codepilot/doctor.py`: owns diagnostic data structures, checks, rendering, and exit-code calculation.
- Modify `codepilot/cli.py`: adds `--doctor` and exits before provider/model initialization.
- Create `tests/test_doctor.py`: unit tests for doctor checks, rendering, secret redaction, and CLI integration.
- Create `docs/productization-roadmap.md`: four-phase technical roadmap.
- Create `docs/release-checklist.md`: release readiness checklist.
- Modify `README.md`: adds doctor to onboarding and links roadmap/checklist.

---

### Task 1: Doctor Core Module

**Files:**
- Create: `codepilot/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Produces: `DoctorItem` dataclass with fields `severity: str`, `label: str`, `message: str`.
- Produces: `DoctorReport` dataclass with field `items: list[DoctorItem]`, method `has_failures(self) -> bool`, and method `exit_code(self) -> int`.
- Produces: `render_report(report: DoctorReport) -> str`.
- Produces: `run_doctor() -> DoctorReport`.

- [ ] **Step 1: Write failing tests for result structures and rendering**

Add this to `tests/test_doctor.py`:

```python
from codepilot.doctor import DoctorItem, DoctorReport, render_report


def test_doctor_report_exit_code_reflects_failures():
    ok_report = DoctorReport(items=[DoctorItem("OK", "Python", "3.11")])
    fail_report = DoctorReport(items=[DoctorItem("FAIL", "API key", "missing")])

    assert ok_report.has_failures() is False
    assert ok_report.exit_code() == 0
    assert fail_report.has_failures() is True
    assert fail_report.exit_code() == 1


def test_render_report_includes_header_and_items():
    report = DoctorReport(items=[
        DoctorItem("OK", "Python", "3.11"),
        DoctorItem("WARN", "MCP SDK", "optional dependency not installed"),
        DoctorItem("FAIL", "API key", "CODEPILOT_ARC_API_KEY missing"),
    ])

    output = render_report(report)

    assert output.startswith("CodePilot Doctor")
    assert "[OK] Python: 3.11" in output
    assert "[WARN] MCP SDK: optional dependency not installed" in output
    assert "[FAIL] API key: CODEPILOT_ARC_API_KEY missing" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor.py -q`

Expected: FAIL because `codepilot.doctor` does not exist.

- [ ] **Step 3: Create minimal doctor data structures and rendering**

Create `codepilot/doctor.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DoctorItem:
    severity: str
    label: str
    message: str


@dataclass(frozen=True)
class DoctorReport:
    items: list[DoctorItem]

    def has_failures(self) -> bool:
        return any(item.severity == "FAIL" for item in self.items)

    def exit_code(self) -> int:
        return 1 if self.has_failures() else 0


def render_report(report: DoctorReport) -> str:
    lines = ["CodePilot Doctor", ""]
    for item in report.items:
        lines.append(f"[{item.severity}] {item.label}: {item.message}")
    return "\n".join(lines)


def run_doctor() -> DoctorReport:
    return DoctorReport(items=[])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doctor.py -q`

Expected: PASS for the two structure/rendering tests.

---

### Task 2: Runtime, Config, Credential, Git, Tool, and MCP Checks

**Files:**
- Modify: `codepilot/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `DoctorItem`, `DoctorReport`, `render_report(report: DoctorReport) -> str`.
- Produces: `run_doctor(working_dir: str | Path | None = None) -> DoctorReport`.
- Produces: helper functions `_provider_env_var(provider_name: str) -> str` and `_has_provider_api_key(provider_name: str, api_key: str | None, environ: Mapping[str, str]) -> bool` for tests.

- [ ] **Step 1: Write failing tests for credential logic and secret redaction**

Append to `tests/test_doctor.py`:

```python
from codepilot.doctor import _has_provider_api_key, _provider_env_var


def test_provider_env_var_uses_uppercase_provider_name():
    assert _provider_env_var("arc") == "CODEPILOT_ARC_API_KEY"
    assert _provider_env_var("deepseek") == "CODEPILOT_DEEPSEEK_API_KEY"


def test_has_provider_api_key_accepts_config_or_environment():
    assert _has_provider_api_key("arc", "config-secret", {}) is True
    assert _has_provider_api_key("arc", "", {"CODEPILOT_ARC_API_KEY": "env-secret"}) is True
    assert _has_provider_api_key("arc", None, {"CODEPILOT_ARC_API_KEY": "env-secret"}) is True
    assert _has_provider_api_key("arc", "", {}) is False


def test_render_report_does_not_include_api_key_values():
    report = DoctorReport(items=[DoctorItem("OK", "API key", "CODEPILOT_ARC_API_KEY found")])
    output = render_report(report)

    assert "config-secret" not in output
    assert "env-secret" not in output
```

- [ ] **Step 2: Write failing tests for run_doctor with monkeypatched config**

Append to `tests/test_doctor.py`:

```python
from types import SimpleNamespace


def test_run_doctor_reports_missing_api_key(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    config = SimpleNamespace(
        default=SimpleNamespace(provider="arc", model="glm-5.1"),
        providers={"arc": SimpleNamespace(api_key="", models=["glm-5.1"])},
    )
    monkeypatch.setattr(doctor, "load_config", lambda: config)
    monkeypatch.setattr(doctor, "CONFIG_PATH", tmp_path / "missing-config.yaml")
    monkeypatch.delenv("CODEPILOT_ARC_API_KEY", raising=False)

    report = doctor.run_doctor(working_dir=tmp_path)

    assert report.exit_code() == 1
    assert any(item.severity == "FAIL" and item.label == "API key" for item in report.items)


def test_run_doctor_accepts_environment_api_key(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    config = SimpleNamespace(
        default=SimpleNamespace(provider="arc", model="glm-5.1"),
        providers={"arc": SimpleNamespace(api_key="", models=["glm-5.1"])},
    )
    monkeypatch.setattr(doctor, "load_config", lambda: config)
    monkeypatch.setattr(doctor, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setenv("CODEPILOT_ARC_API_KEY", "super-secret-value")

    report = doctor.run_doctor(working_dir=tmp_path)
    output = doctor.render_report(report)

    assert any(item.severity == "OK" and item.label == "API key" for item in report.items)
    assert "super-secret-value" not in output


def test_run_doctor_reports_config_load_failure(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    def fail_load_config():
        raise RuntimeError("bad config")

    monkeypatch.setattr(doctor, "load_config", fail_load_config)

    report = doctor.run_doctor(working_dir=tmp_path)

    assert report.exit_code() == 1
    assert any(item.severity == "FAIL" and item.label == "Config" for item in report.items)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_doctor.py -q`

Expected: FAIL because helper functions and real checks are not implemented.

- [ ] **Step 4: Implement doctor checks**

Replace `codepilot/doctor.py` with:

```python
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codepilot import __version__
from codepilot.config.settings import CONFIG_PATH, load_config


@dataclass(frozen=True)
class DoctorItem:
    severity: str
    label: str
    message: str


@dataclass(frozen=True)
class DoctorReport:
    items: list[DoctorItem]

    def has_failures(self) -> bool:
        return any(item.severity == "FAIL" for item in self.items)

    def exit_code(self) -> int:
        return 1 if self.has_failures() else 0


def _provider_env_var(provider_name: str) -> str:
    return f"CODEPILOT_{provider_name.upper()}_API_KEY"


def _has_provider_api_key(
    provider_name: str,
    api_key: str | None,
    environ: Mapping[str, str],
) -> bool:
    if api_key:
        return True
    return bool(environ.get(_provider_env_var(provider_name)))


def _config_provider(config: Any, provider_name: str) -> Any | None:
    providers = getattr(config, "providers", {}) or {}
    if isinstance(providers, dict):
        return providers.get(provider_name)
    return getattr(providers, provider_name, None)


def _is_git_repo(working_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=working_dir,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_dirty(working_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=working_dir,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return bool(result.stdout.strip())


def _inside_source_checkout(working_dir: Path) -> bool:
    return (working_dir / "pyproject.toml").exists() and (working_dir / "codepilot").is_dir()


def run_doctor(working_dir: str | Path | None = None) -> DoctorReport:
    cwd = Path(working_dir or os.getcwd()).resolve()
    items: list[DoctorItem] = []

    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        items.append(DoctorItem("OK", "Python", f"{py_version} at {sys.executable}"))
    else:
        items.append(DoctorItem("FAIL", "Python", f"{py_version}; Python >= 3.11 required"))

    if sys.prefix != sys.base_prefix:
        items.append(DoctorItem("OK", "Virtualenv", sys.prefix))
    else:
        items.append(DoctorItem("WARN", "Virtualenv", "not detected"))

    items.append(DoctorItem("OK", "CodePilot", f"version {__version__}"))

    try:
        config = load_config()
    except Exception as exc:
        items.append(DoctorItem("FAIL", "Config", f"could not load config: {exc}"))
        config = None

    if CONFIG_PATH.exists():
        items.append(DoctorItem("OK", "Config file", str(CONFIG_PATH)))
    else:
        items.append(DoctorItem("WARN", "Config file", f"not found at {CONFIG_PATH}"))

    if config is not None:
        default = getattr(config, "default", None)
        provider_name = getattr(default, "provider", "") if default else ""
        model_name = getattr(default, "model", "") if default else ""
        if provider_name and model_name:
            items.append(DoctorItem("OK", "Default model", f"{provider_name}/{model_name}"))
            provider = _config_provider(config, provider_name)
            if provider is None:
                items.append(DoctorItem("FAIL", "Provider", f"default provider '{provider_name}' not configured"))
            else:
                api_key = getattr(provider, "api_key", None)
                env_var = _provider_env_var(provider_name)
                if _has_provider_api_key(provider_name, api_key, os.environ):
                    items.append(DoctorItem("OK", "API key", f"{env_var} found or config key set"))
                else:
                    items.append(DoctorItem("FAIL", "API key", f"{env_var} missing"))
        else:
            items.append(DoctorItem("FAIL", "Default model", "default provider/model not configured"))

    items.append(DoctorItem("OK", "Working directory", str(cwd)))

    if shutil.which("git"):
        try:
            if _is_git_repo(cwd):
                if _git_dirty(cwd):
                    items.append(DoctorItem("WARN", "Git", "repository has uncommitted changes"))
                else:
                    items.append(DoctorItem("OK", "Git", "repository detected and clean"))
            else:
                items.append(DoctorItem("WARN", "Git", "current directory is not a Git repository"))
        except Exception as exc:
            items.append(DoctorItem("WARN", "Git", f"could not inspect repository: {exc}"))
    else:
        items.append(DoctorItem("WARN", "Git", "git executable not found"))

    if shutil.which("npx"):
        items.append(DoctorItem("OK", "npx", "available"))
    else:
        items.append(DoctorItem("WARN", "npx", "not found; stdio MCP examples may not work"))

    if importlib.util.find_spec("mcp") is None:
        items.append(DoctorItem("WARN", "MCP SDK", "optional dependency not installed"))
    else:
        items.append(DoctorItem("OK", "MCP SDK", "available"))

    if _inside_source_checkout(cwd):
        items.append(DoctorItem("OK", "Development checks", "pytest tests/ -q; ruff check codepilot evals tests"))

    return DoctorReport(items=items)


def render_report(report: DoctorReport) -> str:
    lines = ["CodePilot Doctor", ""]
    for item in report.items:
        lines.append(f"[{item.severity}] {item.label}: {item.message}")
    return "\n".join(lines)
```

- [ ] **Step 5: Run doctor tests**

Run: `pytest tests/test_doctor.py -q`

Expected: PASS.

---

### Task 3: CLI `--doctor` Integration

**Files:**
- Modify: `codepilot/cli.py:16-34`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `run_doctor() -> DoctorReport` and `render_report(report: DoctorReport) -> str` from `codepilot.doctor`.
- Produces: `codepilot --doctor` option that prints the report and exits with `DoctorReport.exit_code()`.

- [ ] **Step 1: Write failing CLI integration tests**

Append to `tests/test_doctor.py`:

```python
from click.testing import CliRunner


def test_cli_doctor_prints_report_and_uses_exit_code(monkeypatch):
    from codepilot.cli import main
    import codepilot.cli as cli
    from codepilot.doctor import DoctorItem, DoctorReport

    def fake_run_doctor():
        return DoctorReport(items=[DoctorItem("FAIL", "API key", "CODEPILOT_ARC_API_KEY missing")])

    monkeypatch.setattr(cli, "run_doctor", fake_run_doctor)
    monkeypatch.setattr(cli, "render_report", lambda report: "CodePilot Doctor\n\n[FAIL] API key: missing")

    result = CliRunner().invoke(main, ["--doctor"])

    assert result.exit_code == 1
    assert "CodePilot Doctor" in result.output
    assert "API key" in result.output


def test_cli_doctor_does_not_initialize_provider_registry(monkeypatch):
    from codepilot.cli import main
    import codepilot.cli as cli
    from codepilot.doctor import DoctorReport

    monkeypatch.setattr(cli, "run_doctor", lambda: DoctorReport(items=[]))
    monkeypatch.setattr(cli, "render_report", lambda report: "CodePilot Doctor")

    def fail_load_config():
        raise AssertionError("load_config should not be called before doctor exits")

    monkeypatch.setattr("codepilot.config.settings.load_config", fail_load_config)

    result = CliRunner().invoke(main, ["--doctor"])

    assert result.exit_code == 0
    assert "CodePilot Doctor" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_doctor.py -q`

Expected: FAIL because `main` does not accept `--doctor` and `codepilot.cli` does not expose the imported functions yet.

- [ ] **Step 3: Modify CLI imports and options**

In `codepilot/cli.py`, add imports near existing imports:

```python
from codepilot.doctor import render_report, run_doctor
```

Add this option above `def main(...)`:

```python
@click.option("--doctor", is_flag=True, default=False, help="Run environment and configuration diagnostics, then exit")
```

Change the function signature from:

```python
def main(model: str | None, agent: str | None, confirm: bool, prompt: str | None, resume: str | None, resume_last: bool, coauthor: bool | None) -> None:
```

to:

```python
def main(model: str | None, agent: str | None, confirm: bool, prompt: str | None, resume: str | None, resume_last: bool, coauthor: bool | None, doctor: bool) -> None:
```

Add this as the first body block after setting `CODEPILOT_WORKING_DIR`:

```python
    if doctor:
        report = run_doctor()
        click.echo(render_report(report))
        raise click.exceptions.Exit(report.exit_code())
```

- [ ] **Step 4: Run CLI doctor tests**

Run: `pytest tests/test_doctor.py -q`

Expected: PASS.

- [ ] **Step 5: Run existing CLI tests**

Run: `pytest tests/test_cli.py -q`

Expected: PASS. If a test fails because Click option ordering changed, update only that test expectation.

---

### Task 4: Productization Roadmap Documentation

**Files:**
- Create: `docs/productization-roadmap.md`

**Interfaces:**
- Produces: stable document linked by README.

- [ ] **Step 1: Create the roadmap document**

Create `docs/productization-roadmap.md`:

```markdown
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
```

- [ ] **Step 2: Check the document has no placeholders**

Run: `grep -n "TBD\|TODO\|fill in\|implement later" docs/productization-roadmap.md`

Expected: no output.

---

### Task 5: Release Checklist Documentation

**Files:**
- Create: `docs/release-checklist.md`

**Interfaces:**
- Produces: stable document linked by README.

- [ ] **Step 1: Create the release checklist**

Create `docs/release-checklist.md`:

```markdown
# CodePilot Release Checklist

Use this checklist before publishing or tagging a CodePilot release.

## Version and release notes

- [ ] Confirm `pyproject.toml` has the intended version.
- [ ] Confirm `codepilot/__init__.py` reports the same version.
- [ ] Write release notes that describe user-visible changes, compatibility notes, and upgrade guidance.

## Local diagnostics

- [ ] Run `codepilot --doctor` from a normal user shell.
- [ ] Confirm required provider API keys are detected through environment variables or local config.
- [ ] Confirm missing optional MCP dependencies are warnings unless the release specifically requires MCP.

## Tests and lint

- [ ] Run `pytest tests/ -q`.
- [ ] Run `ruff check codepilot evals tests`.
- [ ] Run any release-specific eval command, such as `python -m evals.run_local --model <provider/model>`.

## Package build

- [ ] Build the package with the project build backend.
- [ ] Inspect wheel and sdist contents.
- [ ] Confirm built-in skills under `codepilot/skills/builtin/*/SKILL.md` are included.
- [ ] Install the built package in a clean environment and run `codepilot --version`.
- [ ] Run `codepilot --doctor` from the clean environment.

## Documentation

- [ ] Check README quick start commands still work.
- [ ] Check GitHub, `uv tool install`, `pipx`, and editable install instructions.
- [ ] Check links to `docs/productization-roadmap.md` and this checklist.
- [ ] Confirm CLI options in README match `codepilot --help`.

## Secrets and local paths

- [ ] Search staged changes for API keys, LangSmith keys, tokens, SSH keys, and credentials.
- [ ] Confirm no real `~/.codepilot/config.yaml` contents are committed.
- [ ] Confirm examples use placeholder URLs, provider names, and API key values.
- [ ] Confirm no machine-specific absolute paths are included except in explanatory examples.

## Git and publishing

- [ ] Confirm `git status --short` only shows intentional release changes.
- [ ] Confirm the release commit does not include caches, virtualenv files, or local database files.
- [ ] Tag only after tests, lint, diagnostics, package build, and documentation checks pass.
```

- [ ] **Step 2: Check the document has no placeholders**

Run: `grep -n "TBD\|TODO\|fill in\|implement later" docs/release-checklist.md`

Expected: no output.

---

### Task 6: README Productization Updates

**Files:**
- Modify: `README.md:5-27`
- Modify: `README.md:243-249`

**Interfaces:**
- Consumes: `docs/productization-roadmap.md` and `docs/release-checklist.md`.
- Produces: onboarding text that references `codepilot --doctor`.

- [ ] **Step 1: Update quick start with doctor**

In `README.md`, change the quick start block around lines 7-17 from:

```markdown
cd codepilot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 交互模式
codepilot

# 非交互模式
codepilot -p "列出当前目录文件"
```

to:

```markdown
cd codepilot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 安装后自检
codepilot --doctor

# 交互模式
codepilot

# 非交互模式
codepilot -p "列出当前目录文件"
```

- [ ] **Step 2: Add productization docs section before Development**

Insert this before the existing `## 开发` heading:

```markdown
## 产品化路线图

CodePilot 的自研产品化路线分为 Foundation、Safety、Capability、Distribution & Evaluation 四个阶段。详见：

- [产品化技术路线图](docs/productization-roadmap.md)
- [发布检查清单](docs/release-checklist.md)

安装或升级后建议先运行：

```bash
codepilot --doctor
```
```

- [ ] **Step 3: Update development command block**

Change the development command block from:

```markdown
pytest tests/ -v
ruff check codepilot evals tests
python -m evals.run_local --model deepseek/deepseek-v4-flash
```

to:

```markdown
codepilot --doctor
pytest tests/ -v
ruff check codepilot evals tests
python -m evals.run_local --model deepseek/deepseek-v4-flash
```

- [ ] **Step 4: Verify README links are present**

Run: `grep -n "productization-roadmap\|release-checklist\|codepilot --doctor" README.md`

Expected: output includes all three references.

---

### Task 7: Final Verification

**Files:**
- Verify: all changed files.

**Interfaces:**
- Consumes all previous tasks.
- Produces verified productization foundation slice.

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_doctor.py tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run: `pytest tests/ -q`

Expected: PASS, or record exact environmental/pre-existing failures.

- [ ] **Step 3: Run lint**

Run: `ruff check codepilot evals tests`

Expected: PASS, or fix lint failures in touched files.

- [ ] **Step 4: Run doctor manually**

Run: `python -m codepilot.cli --doctor`

Expected: prints `CodePilot Doctor`. Exit code may be 1 if the local default provider API key is missing; that is acceptable if the output identifies only the env var name and does not reveal secrets.

- [ ] **Step 5: Review diff for secrets and scope**

Run: `git diff -- README.md codepilot/cli.py codepilot/doctor.py tests/test_doctor.py docs/productization-roadmap.md docs/release-checklist.md docs/superpowers/specs/2026-06-18-codepilot-productization-foundation-design.md docs/superpowers/plans/2026-06-18-codepilot-productization-foundation.md`

Expected: diff only includes the planned productization foundation changes and no secret values.

---

## Self-Review

**Spec coverage:** The plan covers the roadmap doc, release checklist, `--doctor` CLI option, separate `codepilot/doctor.py`, README updates, unit tests, CLI tests, secret redaction, no new dependencies, no LLM/network calls, and final verification.

**Placeholder scan:** No TBD/TODO/fill-in placeholders are present. Commands and code snippets are concrete.

**Type consistency:** `DoctorItem`, `DoctorReport`, `render_report`, `run_doctor`, `_provider_env_var`, and `_has_provider_api_key` have consistent names and signatures across tasks.
