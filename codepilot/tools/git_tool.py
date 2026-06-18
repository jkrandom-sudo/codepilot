"""Git operation tools (status, diff, log).

Thin wrappers around git CLI for agent-accessible
version control operations.
"""
from __future__ import annotations

import os
import subprocess

from langchain_core.tools import tool

from codepilot.utils.truncate import truncate_output


def _git(args: list[str]) -> str:
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\n{result.stderr.strip()}"
        return output or "(no output)"
    except Exception as e:
        return f"Error: {e}"


@tool
def git_status() -> str:
    """Show git working tree status."""
    return _git(["status", "--short"])


@tool
def git_diff(path: str | None = None) -> str:
    """Show git diff for a file or all changes."""
    args = ["diff"]
    if path:
        args.extend(["--", path])
    return truncate_output(_git(args), max_lines=300, max_chars=20000)


@tool
def git_log(count: int = 10) -> str:
    """Show recent git log."""
    return _git(["log", f"--max-count={count}", "--oneline"])
