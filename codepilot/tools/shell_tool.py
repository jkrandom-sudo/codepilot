"""Shell execution tool with safety guards.

Provides run_shell with permission checks,
search command detection, and sandboxing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from codepilot.tools.truncation import get_truncation_store

# Whitespace-tolerant regex patterns (matched after collapsing whitespace).
DANGEROUS_PATTERN_REGEXES = [
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|/\*|~|\$HOME)"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if="),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"\bchmod\s+-R\s+777\s+/"),
    re.compile(r"\bshred\b"),
    re.compile(r"\bwipe\b"),
    re.compile(r"\bformat\s"),
    re.compile(r"\brmdir\s+/s\b", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),  # fork bomb
]
DANGEROUS_PATTERNS = [pattern.pattern for pattern in DANGEROUS_PATTERN_REGEXES]

DANGEROUS_COMMAND_BASES = frozenset({
    "rm", "rmdir", "shred", "wipe", "mkfs", "dd",
    "format", "fdisk", "parted",
})

# Separators that introduce a new command clause in shell.
_CLAUSE_SPLIT_RE = re.compile(r"(?:&&|\|\||;|\|)")


def _split_clauses(command: str) -> list[str]:
    """Split a command line into top-level clauses.

    Best-effort: ignores escaping/quoting nuances but covers the common
    bypass patterns (`; && || |`).
    """
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(command) if c.strip()]


def _extract_subshell_bodies(command: str) -> list[str]:
    """Yield bodies of $(...) and `...` subshells (non-nested, best-effort)."""
    bodies = list(re.findall(r"\$\(([^)]+)\)", command))
    bodies.extend(re.findall(r"`([^`]+)`", command))
    return bodies


def _has_dangerous_base(command: str) -> str | None:
    """Recursively scan every clause + subshell for a dangerous base command."""
    for clause in _split_clauses(command):
        first_word = clause.split()[0] if clause.split() else ""
        base = first_word.rsplit("/", 1)[-1]
        base_family = base.split(".", 1)[0]
        if base in DANGEROUS_COMMAND_BASES or base_family in DANGEROUS_COMMAND_BASES:
            return base
        for inner in _extract_subshell_bodies(clause):
            result = _has_dangerous_base(inner)
            if result:
                return result
    return None

SEARCH_COMMAND_PATTERNS = [
    (r'\bgrep\b', 'Use the `grep` tool instead.'),
    (r'\brg\b', 'Use the `grep` tool instead.'),
    (r'\bfind\b', 'Use the `glob` tool instead.'),
    (r'\bcat\b', 'Use the `read_file` tool instead.'),
    (r'\bsed\b', 'Use the `read_file` or `edit_file` tool instead.'),
    (r'\back\b', 'Use the `grep` tool instead.'),
    (r'\bag\b', 'Use the `grep` tool instead.'),
    (r'\bls\b', 'Use the `read_file` tool with a directory path instead.'),
    (r'\bwc\b', 'This is a code search task — use `grep` or `glob` instead.'),
    (r'\bhead\b', 'Use the `read_file` tool with offset/limit instead.'),
    (r'\btail\b', 'Use the `read_file` tool with offset/limit instead.'),
    (r'\bless\b', 'Use the `read_file` tool instead.'),
    (r'\bmore\b', 'Use the `read_file` tool instead.'),
    (r'\bxargs\s+grep\b', 'Use the `grep` tool instead.'),
    (r'\bxargs\s+cat\b', 'Use the `read_file` tool instead.'),
    (r'\bxargs\s+find\b', 'Use the `glob` tool instead.'),
    (r'\bwhich\b', 'This is a search command — not needed for coding tasks.'),
    (r'\btype\b', 'This is a search command — not needed for coding tasks.'),
    (r'\bfile\b', 'Not needed for coding tasks. Use read_file to check file content.'),
    (r'\bstat\b', 'Not needed for coding tasks. Use read_file or glob instead.'),
    (r'\bdu\b', 'Not needed for coding tasks. Use glob to find files.'),
    (r'\bdiff\b', 'Use read_file on both files and compare the content yourself.'),
    (r'\bsort\b', 'Not needed for coding tasks. Process data in your response.'),
    (r'\buniq\b', 'Not needed for coding tasks. Process data in your response.'),
    (r'\bcut\b', 'Not needed for coding tasks. Use read_file with offset/limit.'),
    (r'\btr\b', 'Not needed for coding tasks.'),
    (r'\bawk\b', 'Use grep or read_file instead.'),
    (r'\bperl\b(?!\s+.*-\w*e\w*)', 'Use grep or read_file instead.'),
    (r'\btee\b', 'Not needed for coding tasks. Use write_file instead.'),
    (r'\bxargs\b', 'Use dedicated tools (grep, glob, read_file) instead of xargs pipes.'),
    (r'\bpython[23]?\s+-c\s+.*\bopen\b', 'Use read_file instead of python -c with open().'),
    (r'\bpython[23]?\s+-c\s+.*\bimport.*os\b', 'Use dedicated tools instead of python -c for file inspection.'),
    (r'\bgit\s+grep\b', 'Use the `grep` tool instead.'),
    (r'\bgit\s+log\b', 'Use the `git_log` tool instead.'),
    (r'\bgit\s+diff\b', 'Use the `git_diff` tool instead.'),
    (r'\bgit\s+status\b', 'Use the `git_status` tool instead.'),
]

ALLOWED_SHELL_PREFIXES = [
    "python", "python3", "node", "npm", "pip", "git ", "git\n",
    "make", "cargo", "go ", "rustc", "gcc", "g++",
    "docker", "pytest", "ruff", "mypy", "black", "isort",
    "curl", "wget", "tar", "unzip",
    "echo", "cp", "mv", "mkdir", "touch", "chmod",
    "hatch", "uv ", "poetry", "tox", "pre-commit",
    "npm run", "npx", "yarn", "pnpm",
]

MAX_TIMEOUT = 300

DEFAULT_TIMEOUT = 120


_PIPE_SEARCH_ONLY = {
    "grep", "rg", "ack", "ag", "awk", "sort", "uniq", "cut", "tr", "wc",
    "head", "tail", "less", "more", "diff",
}

_PIPE_DATA_PRODUCERS = {
    "python", "python3", "node", "npm", "pip", "git", "docker", "pytest",
    "ruff", "mypy", "cargo", "go", "make", "echo", "hatch", "uv", "poetry",
    "tox", "npx", "yarn", "pnpm",
}


def _subprocess_env() -> dict[str, str]:
    """Return an environment that can find CodePilot's active Python tools."""
    env = os.environ.copy()
    bin_dir = Path(sys.executable).parent
    path_parts = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
    if str(bin_dir) not in path_parts:
        env["PATH"] = str(bin_dir) + (os.pathsep + env["PATH"] if env.get("PATH") else "")

    venv_dir = bin_dir.parent
    if (venv_dir / "pyvenv.cfg").exists():
        env.setdefault("VIRTUAL_ENV", str(venv_dir))
    return env


def _is_search_command(command: str) -> tuple[bool, str]:
    """Detect if a command is a search/file-inspection command that should
    be redirected to dedicated tools.

    Strategy: only inspect the *first token* of each top-level clause and
    each pipeline segment. This avoids false positives on filename
    arguments such as `pytest tests/test_grep.py` or `python ls_tool.py`.
    """
    cmd = command.strip()
    # Recurse into subshells first.
    for inner in _extract_subshell_bodies(cmd):
        is_search, msg = _is_search_command(inner)
        if is_search:
            return True, f"Subshell contains search command. {msg}"

    # Pipeline: handle producer-leading pipelines.
    if "|" in cmd:
        parts = [p.strip() for p in cmd.split("|") if p.strip()]
        if len(parts) >= 2:
            first_word = parts[0].split()[0] if parts[0].split() else ""
            first_base = first_word.rsplit("/", 1)[-1]
            if first_base in _PIPE_DATA_PRODUCERS:
                return False, ""
            for part in parts:
                pw = part.split()[0] if part.split() else ""
                pw_base = pw.rsplit("/", 1)[-1]
                if pw_base in _PIPE_SEARCH_ONLY:
                    continue
                hit = _match_first_token_pattern(pw_base)
                if hit:
                    return True, f"Pipe contains search command. {hit}"
            all_search = all(
                ((p.split()[0] if p.split() else "").rsplit("/", 1)[-1])
                in _PIPE_SEARCH_ONLY
                for p in parts
            )
            if all_search:
                return True, "Pipeline consists entirely of search/filter commands. Use grep/glob/read_file instead."
        return False, ""

    # Allowed prefix fast-path.
    for prefix in ALLOWED_SHELL_PREFIXES:
        if cmd.startswith(prefix):
            return False, ""

    # Inspect each top-level clause's first token only.
    for clause in _split_clauses(cmd):
        first_word = clause.split()[0] if clause.split() else ""
        first_base = first_word.rsplit("/", 1)[-1]
        hit = _match_first_token_pattern(first_base)
        if hit:
            return True, hit
        # Detect `git grep` / `git log` / `git diff` / `git status` / `xargs grep`.
        tokens = clause.split()
        if len(tokens) >= 2:
            two = f"{first_base} {tokens[1]}"
            hit2 = _SEARCH_TWO_TOKEN.get(two)
            if hit2:
                return True, hit2
        # Detect `python -c` patterns that read files.
        if first_base in {"python", "python3", "python2"} and "-c" in tokens:
            try:
                idx = tokens.index("-c")
                code = " ".join(tokens[idx + 1:])
                if "open(" in code or re.search(r"\bimport\s+os\b", code):
                    return True, "Use read_file/glob instead of python -c for file inspection."
            except ValueError:
                pass
    return False, ""


# First-token search commands (mapped to alternative-tool message).
_SEARCH_FIRST_TOKEN: dict[str, str] = {
    "grep": "Use the `grep` tool instead.",
    "rg": "Use the `grep` tool instead.",
    "ack": "Use the `grep` tool instead.",
    "ag": "Use the `grep` tool instead.",
    "find": "Use the `glob` tool instead.",
    "cat": "Use the `read_file` tool instead.",
    "sed": "Use the `read_file` or `edit_file` tool instead.",
    "ls": "Use the `read_file` tool with a directory path instead.",
    "wc": "This is a code search task — use `grep` or `glob` instead.",
    "head": "Use the `read_file` tool with offset/limit instead.",
    "tail": "Use the `read_file` tool with offset/limit instead.",
    "less": "Use the `read_file` tool instead.",
    "more": "Use the `read_file` tool instead.",
    "which": "This is a search command — not needed for coding tasks.",
    "stat": "Not needed for coding tasks. Use read_file or glob instead.",
    "du": "Not needed for coding tasks. Use glob to find files.",
    "diff": "Use read_file on both files and compare the content yourself.",
    "sort": "Not needed for coding tasks. Process data in your response.",
    "uniq": "Not needed for coding tasks. Process data in your response.",
    "cut": "Not needed for coding tasks. Use read_file with offset/limit.",
    "tr": "Not needed for coding tasks.",
    "awk": "Use grep or read_file instead.",
    "tee": "Not needed for coding tasks. Use write_file instead.",
    "xargs": "Use dedicated tools (grep, glob, read_file) instead of xargs pipes.",
}

_SEARCH_TWO_TOKEN: dict[str, str] = {
    "git grep": "Use the `grep` tool instead.",
    "git log": "Use the `git_log` tool instead.",
    "git diff": "Use the `git_diff` tool instead.",
    "git status": "Use the `git_status` tool instead.",
    "xargs grep": "Use the `grep` tool instead.",
    "xargs cat": "Use the `read_file` tool instead.",
    "xargs find": "Use the `glob` tool instead.",
}


def _match_first_token_pattern(token: str) -> str | None:
    return _SEARCH_FIRST_TOKEN.get(token)


@tool
def run_shell(
    command: str,
    description: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    workdir: str = "",
    allow_search_commands: bool = False,
) -> str:
    """Execute a shell command and return output.

    Args:
        command: The shell command to execute
        description: Brief description (5-10 words) of what the command does
        timeout: Timeout in seconds (default 120)
        workdir: Working directory (default: current working directory)
        allow_search_commands: Internal flag set after explicit user confirmation
            to allow shell search/listing commands.
    """
    working_dir = workdir or os.environ.get("CODEPILOT_WORKING_DIR", ".")

    timeout = min(timeout, MAX_TIMEOUT)

    normalized = re.sub(r"\s+", " ", command).strip()
    for regex in DANGEROUS_PATTERN_REGEXES:
        if regex.search(normalized) or regex.search(normalized.lower()):
            return f"Error: Command blocked (matches dangerous pattern: {regex.pattern})"

    dangerous_base = _has_dangerous_base(command)
    if dangerous_base:
        return f"Error: Command blocked (dangerous base command: {dangerous_base})"

    if not allow_search_commands:
        is_search, alt_msg = _is_search_command(command)
        if is_search:
            return f"[BLOCKED] run_shell with search command is forbidden. {alt_msg}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n--- stderr ---\n" + result.stderr) if output else result.stderr
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"

        if not output:
            return "(no output)"

        store = get_truncation_store()
        truncated, _ = store.truncate_and_save(
            output,
            f"shell_{id(command)}",
            max_lines=300,
            max_chars=20000,
        )
        return truncated
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
