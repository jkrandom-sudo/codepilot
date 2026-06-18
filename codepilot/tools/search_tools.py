"""Code search tools (grep, glob).

File content search (grep) and file name search (glob)
for the agent to navigate codebases.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from codepilot.utils.truncate import truncate_output


def _validate_search_path(path: str, working_dir: str) -> str | None:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(working_dir) / p
    p = p.resolve()
    wd = Path(working_dir).resolve()
    try:
        p.relative_to(wd)
    except ValueError:
        return f"Error: Search path {path} is outside working directory"
    return None


@tool
def grep(
    pattern: str,
    path: str = ".",
    include: str | None = None,
) -> str:
    """Search file contents using regex pattern (like ripgrep/grep).

    Use this INSTEAD of run_shell("grep ..."). Prefer this for:
    - Finding function/class definitions: grep("def my_func")
    - Finding usages: grep("import requests")
    - Finding strings: grep("TODO|FIXME")
    - Filter by file type: grep("class User", include="*.py")
    - Filter by multiple extensions: grep("export", include="*.{ts,tsx}")

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in (default: current directory)
        include: File pattern filter (e.g. "*.py", "*.{ts,tsx}", "*.toml")
    """
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")

    path_err = _validate_search_path(path, working_dir)
    if path_err:
        return path_err

    cmd = ["grep", "-rn", "--color=never", "-E", pattern]
    if include:
        cmd.extend(["--include", include])
    cmd.append(path)

    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            if len(lines) > 100:
                shown = lines[:100]
                output = "\n".join(shown)
                output += f"\n\n... ({len(lines) - 100} more matches, narrow your pattern)"
            else:
                output = "\n".join(lines)
            return truncate_output(output, max_lines=150, max_chars=15000)
        if result.returncode == 1:
            return "No matches found"
        return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: Search timed out"
    except Exception as e:
        return f"Error: {e}"
