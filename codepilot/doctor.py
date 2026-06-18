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
from codepilot.config.settings import CONFIG_FILE, load_config


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
    if importlib.util.find_spec("codepilot.agent.graph") is None:
        items.append(DoctorItem("FAIL", "Core modules", "codepilot.agent.graph not importable"))
    else:
        items.append(DoctorItem("OK", "Core modules", "agent graph importable"))

    config = None
    if CONFIG_FILE.exists():
        items.append(DoctorItem("OK", "Config file", str(CONFIG_FILE)))
        try:
            config = load_config()
        except Exception as exc:
            items.append(DoctorItem("FAIL", "Config", f"could not load config: {exc}"))
    else:
        items.append(DoctorItem("WARN", "Config file", f"not found at {CONFIG_FILE}"))
        items.append(DoctorItem("FAIL", "Config", "config file missing; run CodePilot setup or create ~/.codepilot/config.yaml"))

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
