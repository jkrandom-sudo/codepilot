"""File read/write/edit tools for the agent.

Provides read_file, write_file, and edit_file implementations
with path resolution and safety checks.
"""
from __future__ import annotations

import os
from difflib import get_close_matches
from pathlib import Path

from langchain_core.tools import tool

from codepilot.utils.truncate import truncate_output

NOISE_DIRS = {
    ".idea", ".vscode", "__pycache__", ".git", ".tox",
    ".mypy_cache", ".pytest_cache", "node_modules", ".venv", "venv",
}

BINARY_EXTENSIONS = {
    ".zip", ".exe", ".wasm", ".pyc", ".pyo", ".so", ".dylib", ".dll",
    ".o", ".a", ".lib", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".pdf", ".doc", ".docx", ".xls",
    ".xlsx", ".ppt", ".pptx", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".jar", ".class", ".woff", ".woff2", ".ttf", ".eot", ".sqlite",
    ".db", ".bin", ".dat", ".pkl", ".npy", ".npz",
}

MAX_FILE_BYTES = 200000
MAX_FILE_LINES = 5000
MAX_WRITE_BYTES = 1_000_000
MAX_LINE_LENGTH = 2000


SENSITIVE_PATHS = (
    ".ssh", ".aws", ".gnupg", ".kube", ".config/gcloud",
    ".env", ".npmrc", ".pypirc", ".netrc", ".gitconfig",
    ".docker", ".terraform.d",
)


def _is_sensitive_path(p: Path) -> bool:
    home = Path.home()
    try:
        rel = p.relative_to(home)
        parts_str = str(rel)
        for seg in SENSITIVE_PATHS:
            if parts_str.startswith(seg + "/") or parts_str.startswith(seg + os.sep):
                return True
            if parts_str == seg:
                return True
    except ValueError:
        pass
    name_lower = p.name.lower()
    if name_lower in (".env", ".npmrc", ".pypirc", ".netrc", ".gitconfig", ".htpasswd"):
        return True
    return False


def _resolve_path(path: str, working_dir: str, allow_external: bool = False) -> tuple[Path | None, str | None]:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(working_dir) / p
    p = p.resolve()

    if _is_sensitive_path(p):
        return None, "Error: Cannot read from sensitive path (credentials/config)"

    if allow_external:
        blocked_prefixes = ("/etc", "/private/etc", "/proc", "/sys", "/dev")
        for prefix in blocked_prefixes:
            if str(p).startswith(prefix):
                return None, "Error: Cannot read from system path"
        return p, None

    wd = Path(working_dir).resolve()
    try:
        p.relative_to(wd)
    except ValueError:
        return None, f"Error: Path {p} is outside working directory {wd}"
    return p, None


def _is_binary(p: Path) -> bool:
    if p.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        chunk = p.read_bytes()[:4096]
        if b"\x00" in chunk:
            return True
        try:
            chunk.decode("utf-8")
            return False
        except UnicodeDecodeError as e:
            if e.start >= len(chunk) - 4 and len(chunk) > 4:
                try:
                    chunk[:e.start].decode("utf-8")
                    return False
                except UnicodeDecodeError:
                    pass
        non_printable = sum(
            1 for b in chunk if b > 127 or (b < 32 and b not in (9, 10, 13))
        )
        if len(chunk) > 0 and non_printable / len(chunk) > 0.3:
            return True
    except Exception:
        pass
    return False


def _fuzzy_suggest(p: Path) -> str | None:
    try:
        parent = p.parent
        target = p.name.lower()
        if not parent.exists():
            return None
        siblings = [f.name for f in parent.iterdir() if not f.name.startswith(".")]
        matches = get_close_matches(target, siblings, n=3, cutoff=0.5)
        if matches:
            return f"Did you mean: {', '.join(matches)}?"
    except Exception:
        pass
    return None


def _truncate_long_lines(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if len(line) > MAX_LINE_LENGTH:
            result.append(line[:MAX_LINE_LENGTH] + "...")
        else:
            result.append(line)
    return result


def _read_as_directory(p: Path) -> str:
    lines = []
    try:
        for item in sorted(p.iterdir()):
            if item.name in NOISE_DIRS:
                continue
            suffix = "/" if item.is_dir() else ""
            lines.append(f"{item.name}{suffix}")
    except PermissionError:
        return f"Error: Permission denied reading directory {p}"

    if not lines:
        return "(empty directory)"
    dirs = sum(1 for item in p.iterdir() if item.is_dir() and item.name not in NOISE_DIRS)
    files = len(lines) - dirs
    header = f"({dirs} dirs, {files} files)" if dirs else f"({files} files)"
    return header + "\n" + "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_file_impl(path: str, offset: int | None = None, limit: int | None = None) -> str:
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    p, err = _resolve_path(path, working_dir, allow_external=True)
    if err:
        return err

    if not p.exists():
        suggestion = _fuzzy_suggest(p)
        msg = f"Error: File not found: {p}"
        if suggestion:
            msg += f"\n{suggestion}"
        return msg

    if p.is_dir():
        result = _read_as_directory(p)
        return truncate_output(result, max_lines=100, max_chars=10000)

    if _is_binary(p):
        return f"Error: Cannot read binary file: {p} (detected as binary via extension or content)"

    try:
        content = p.read_text(errors="replace")
    except PermissionError:
        return f"Error: Permission denied reading {p}"

    original_lines = content.splitlines(keepends=True)
    total_lines = len(original_lines)

    if offset is not None or limit is not None:
        start = (offset or 1) - 1
        if start < 0:
            start = 0
        end = start + (limit or len(original_lines) - start)
        lines = original_lines[start:end]
    else:
        if len(content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
            content = content[:MAX_FILE_BYTES]
            content += f"\n\n[File truncated at {MAX_FILE_BYTES} bytes. Use offset/limit to read further.]"
        lines = content.splitlines(keepends=True)

    numbered = []
    base = (offset or 1)
    for i, line in enumerate(lines):
        line_content = line.rstrip("\n").rstrip("\r")
        if len(line_content) > MAX_LINE_LENGTH:
            line_content = line_content[:MAX_LINE_LENGTH] + "..."
        numbered.append(f"{base + i}: {line_content}")

    result = "\n".join(numbered)
    if offset or limit:
        result += f"\n\n(showing lines {base}-{base + len(lines) - 1} of {total_lines})"

    return truncate_output(result, max_lines=MAX_FILE_LINES, max_chars=MAX_FILE_BYTES)


def write_file_impl(path: str, content: str) -> str:
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    p, err = _resolve_path(path, working_dir)
    if err:
        return err
    if len(content.encode("utf-8", errors="replace")) > MAX_WRITE_BYTES:
        return f"Error: Content too large ({len(content)} chars, max {MAX_WRITE_BYTES} bytes)"
    _atomic_write(p, content)
    return f"Wrote {len(content)} chars to {p}"


def edit_file_impl(path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    p, err = _resolve_path(path, working_dir)
    if err:
        return err

    if not p.exists():
        if old_str == "":
            _atomic_write(p, new_str)
            return f"Created new file {p} with {len(new_str)} chars"
        suggestion = _fuzzy_suggest(p)
        msg = f"Error: File not found: {p}"
        if suggestion:
            msg += f"\n{suggestion}"
        return msg

    if old_str == "":
        return "Error: old_str cannot be empty for existing files (use write_file to overwrite)"

    content = p.read_text()
    count = content.count(old_str)

    if count == 0:
        suggestion = _fuzzy_suggest(p)
        msg = f"Error: old_str not found in {p}"
        if suggestion:
            msg += f"\n{suggestion}"
        return msg

    if count > 1 and not replace_all:
        return (
            f"Error: old_str found {count} times in {p}. "
            f"Either provide more context to make it unique, or set replace_all=true to replace all occurrences."
        )

    if replace_all:
        new_content = content.replace(old_str, new_str)
    else:
        new_content = content.replace(old_str, new_str, 1)

    _atomic_write(p, new_content)
    occurrences = count if replace_all else 1
    return f"Edited {p}: replaced {occurrences} occurrence(s), {len(old_str)} chars with {len(new_str)} chars"


def glob_impl(pattern: str, path: str = ".") -> str:
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    p, err = _resolve_path(path, working_dir)
    if err:
        return err
    if not p.is_dir():
        return f"Error: {p} is not a directory"

    matches = sorted(p.glob(pattern))
    if not matches:
        return f"No files matching '{pattern}' in {p}"

    limited = matches[:100]
    result_lines = [str(m.relative_to(p)) for m in limited]
    result = "\n".join(result_lines)

    if len(matches) > 100:
        result += f"\n\n({len(matches) - 100} more results not shown, refine your pattern)"

    return truncate_output(result, max_lines=150, max_chars=15000)


@tool
def read_file(path: str, offset: int | None = None, limit: int | None = None) -> str:
    """Read file contents with line numbers, or list directory entries if path is a directory.

    Features:
    - Reads files with 1-indexed line numbers (e.g. "1: content")
    - If path is a directory, lists its entries (trailing / for subdirs)
    - Binary detection: rejects binary files via extension and content sampling
    - Fuzzy suggestions: on file-not-found, suggests similar filenames
    - Use offset/limit for large files instead of reading the entire file
    - Can read files outside the working directory for research purposes
    - Cannot read from sensitive system paths (/etc, /proc, /sys, /dev)

    Args:
        path: Absolute or relative path to file or directory
        offset: Line number to start from (1-indexed, inclusive)
        limit: Maximum number of lines to read
    """
    return read_file_impl(path, offset, limit)


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating it and parent directories if needed.

    Args:
        path: Absolute or relative path to the file (must be within working directory)
        content: Content to write to the file
    """
    return write_file_impl(path, content)


@tool
def edit_file(
    path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    """Replace exact string match(es) in a file. For creating new files, use write_file instead.

    Args:
        path: Absolute or relative path to the file
        old_str: The exact text to replace (must be unique unless replace_all=true)
        new_str: The replacement text (must differ from old_str)
        replace_all: If true, replace all occurrences; otherwise requires unique match
    """
    return edit_file_impl(path, old_str, new_str, replace_all)


@tool
def glob(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern. Returns up to 100 results.

    Use this INSTEAD of run_shell("find ..."). Prefer this for:
    - Finding files by extension: glob("**/*.py")
    - Finding files by name: glob("**/test_*.py")
    - Finding config files: glob("**/pyproject.toml")

    Args:
        pattern: Glob pattern (e.g. "**/*.py", "*.toml")
        path: Directory to search in (default: current directory)
    """
    return glob_impl(pattern, path)
