from __future__ import annotations

import re
import subprocess
from pathlib import Path

import httpx


# Patterns for @ references
FILE_PATTERN = re.compile(r"@file\s+(\S+)")
URL_PATTERN = re.compile(r"@url\s+(\S+)")
GIT_PATTERN = re.compile(r"@git\s+(\S+)")
DIR_PATTERN = re.compile(r"@dir\s+(\S+)")
# Inline @file without keyword (e.g., "@src/main.py", "@graph")
INLINE_FILE_PATTERN = re.compile(r"@(\S+)")


def parse_references(text: str) -> tuple[str, str]:
    """Parse @ references from user input.

    Returns:
        (clean_text, referenced_content) - the text with @ syntax removed and the gathered content.
    """
    parts: list[str] = []
    clean = text

    # @file references
    for match in FILE_PATTERN.finditer(text):
        path = match.group(1)
        content = _read_file_ref(path)
        if content:
            parts.append(f"[File: {path}]\n{content}")
        clean = clean.replace(match.group(0), "")

    # @url references
    for match in URL_PATTERN.finditer(text):
        url = match.group(1)
        content = _fetch_url(url)
        if content:
            parts.append(f"[URL: {url}]\n{content[:5000]}")
        clean = clean.replace(match.group(0), "")

    # @git references
    for match in GIT_PATTERN.finditer(text):
        commit = match.group(1)
        content = _git_show(commit)
        if content:
            parts.append(f"[Git: {commit}]\n{content}")
        clean = clean.replace(match.group(0), "")

    # @dir references
    for match in DIR_PATTERN.finditer(text):
        path = match.group(1)
        content = _list_dir_ref(path)
        if content:
            parts.append(f"[Directory: {path}]\n{content}")
        clean = clean.replace(match.group(0), "")

    # Inline @file (e.g., @src/main.py, @graph)
    # Applied to clean text (after explicit @file/@url/@git/@dir removed)
    for match in INLINE_FILE_PATTERN.finditer(clean):
        path = match.group(1)
        # Skip bare keywords (e.g., user typed just @file without a path)
        if path in ("file", "url", "git", "dir"):
            continue
        content = _read_file_ref(path)
        if content:
            parts.append(f"[File: {path}]\n{content}")
        clean = clean.replace(match.group(0), f"({path})")

    return clean.strip(), "\n\n".join(parts)


def _read_file_ref(path: str) -> str | None:
    try:
        p = Path(path).expanduser()
        if p.exists() and p.is_file():
            return p.read_text(errors="replace")[:10000]
    except Exception:
        pass
    return None


def _fetch_url(url: str) -> str | None:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text[:10000]
    except Exception:
        return None


def _git_show(commit: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", commit],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout[:10000]
    except Exception:
        pass
    return None


def _list_dir_ref(path: str) -> str | None:
    try:
        p = Path(path).expanduser()
        if p.exists() and p.is_dir():
            lines = []
            for item in sorted(p.iterdir())[:50]:
                suffix = "/" if item.is_dir() else ""
                lines.append(f"{item.name}{suffix}")
            return "\n".join(lines)
    except Exception:
        pass
    return None
