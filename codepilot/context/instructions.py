from __future__ import annotations

from pathlib import Path

INSTRUCTION_FILENAMES = ("AGENTS.md", "agents.md", "CLAUDE.md", "claude.md")
MAX_INSTRUCTION_BYTES = 25_000
MAX_INSTRUCTION_LINES = 200


def find_instruction_files(working_dir: str | Path) -> list[Path]:
    """Find supported project instruction files in priority order."""
    base = Path(working_dir).expanduser().resolve()
    found: list[Path] = []
    seen: set[tuple[int, int] | str] = set()
    for name in INSTRUCTION_FILENAMES:
        path = base / name
        if path.exists() and path.is_file():
            resolved = path.resolve()
            try:
                stat = path.stat()
                seen_key: tuple[int, int] | str = (stat.st_dev, stat.st_ino)
            except OSError:
                seen_key = str(resolved).lower()
            if seen_key not in seen:
                found.append(resolved)
                seen.add(seen_key)
    return found


def load_project_instructions(working_dir: str | Path) -> str:
    """Load AGENTS.md / CLAUDE.md style project instructions for the system prompt."""
    blocks = []
    for path in find_instruction_files(working_dir):
        content = _read_instruction_file(path)
        if content:
            blocks.append(f"### {path.name}\n{content}")
    if not blocks:
        return ""
    return "Project instructions:\n" + "\n\n".join(blocks)


def _read_instruction_file(path: Path) -> str:
    raw = path.read_bytes()[:MAX_INSTRUCTION_BYTES]
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > MAX_INSTRUCTION_LINES:
        text = "\n".join(lines[:MAX_INSTRUCTION_LINES])
        text += f"\n\n[Instruction file truncated at {MAX_INSTRUCTION_LINES} lines.]"
    elif path.stat().st_size > MAX_INSTRUCTION_BYTES:
        text += f"\n\n[Instruction file truncated at {MAX_INSTRUCTION_BYTES} bytes.]"
    return text.strip()


def build_agents_md(working_dir: str | Path) -> str:
    """Generate a concise AGENTS.md seed from local project metadata."""
    base = Path(working_dir).expanduser().resolve()
    project_name = base.name
    pyproject = base / "pyproject.toml"
    readme = base / "README.md"

    setup_lines = [
        "python3.11 -m venv .venv && source .venv/bin/activate",
        'pip install -e ".[dev]"',
    ]
    test_command = "pytest tests/ -q"
    lint_command = "ruff check codepilot evals tests"

    if pyproject.exists():
        project_name = _extract_project_name(pyproject) or project_name
    if readme.exists():
        first_heading = _first_markdown_heading(readme)
        if first_heading:
            project_name = first_heading

    structure = _top_level_structure(base)
    return (
        f"# {project_name} Agent Instructions\n\n"
        "## Project\n\n"
        "CLI coding agent built with Python, LangChain, and LangGraph.\n\n"
        "## Setup\n\n"
        "```bash\n"
        + "\n".join(setup_lines)
        + "\n```\n\n"
        "## Commands\n\n"
        f"- Run app: `codepilot`\n"
        f"- Non-interactive: `codepilot -p \"prompt\"`\n"
        f"- Tests: `{test_command}`\n"
        f"- Lint: `{lint_command}`\n\n"
        "## Project Structure\n\n"
        + structure
        + "\n\n"
        "## Agent Notes\n\n"
        "- Prefer existing project patterns over new abstractions.\n"
        "- Use dedicated tools for reading/searching files instead of shell search commands.\n"
        "- Keep edits scoped and verify with tests when behavior changes.\n"
    )


def init_agents_file(working_dir: str | Path, force: bool = False) -> tuple[bool, str]:
    """Create AGENTS.md. Returns (created_or_updated, message)."""
    base = Path(working_dir).expanduser().resolve()
    path = base / "AGENTS.md"
    existed = path.exists()
    if path.exists() and not force:
        return False, f"AGENTS.md already exists at {path}. Use /init --force to overwrite."
    path.write_text(build_agents_md(base), encoding="utf-8")
    action = "Updated" if existed else "Created"
    return True, f"{action} {path}"


def _extract_project_name(pyproject: Path) -> str | None:
    for line in pyproject.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("name") and "=" in stripped:
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _first_markdown_heading(readme: Path) -> str | None:
    for line in readme.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    return None


def _top_level_structure(base: Path) -> str:
    entries = []
    skip = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    for path in sorted(base.iterdir()):
        if path.name in skip or path.name.startswith(".DS_Store"):
            continue
        suffix = "/" if path.is_dir() else ""
        entries.append(f"- `{path.name}{suffix}`")
        if len(entries) >= 12:
            break
    return "\n".join(entries) if entries else "- `(empty)`"
