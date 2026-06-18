"""Project detection and metadata extraction.

Detects project type (Python, Node.js, etc.) and returns
relevant context for the agent.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class ProjectAnalyzer:
    """Analyze project structure for context injection."""

    IGNORE_DIRS = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
        ".idea", ".vscode", "target", ".next", ".nuxt",
    }

    IGNORE_FILES = {
        ".DS_Store", "Thumbs.db", "*.pyc", "*.pyo",
    }

    def __init__(self, working_dir: str = ".") -> None:
        self.working_dir = Path(working_dir).resolve()
        self._cache: str | None = None

    def get_overview(self, force_refresh: bool = False) -> str:
        if self._cache and not force_refresh:
            return self._cache

        parts = [f"Project root: {self.working_dir}"]

        # Directory tree (2 levels deep)
        tree = self._build_tree(max_depth=2)
        if tree:
            parts.append(f"Structure:\n{tree}")

        # Git branch info
        branch = self._get_git_branch()
        if branch:
            parts.append(f"Git branch: {branch}")

        # Key files
        key_files = self._find_key_files()
        if key_files:
            parts.append(f"Key files: {', '.join(key_files)}")

        self._cache = "\n\n".join(parts)
        return self._cache

    def _build_tree(self, max_depth: int = 2) -> str:
        lines = []
        try:
            for root, dirs, files in os.walk(self.working_dir):
                rel_root = Path(root).relative_to(self.working_dir)
                depth = len(rel_root.parts)
                if depth >= max_depth:
                    dirs.clear()
                    continue

                dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith(".")]

                indent = "  " * depth
                for d in sorted(dirs)[:20]:
                    lines.append(f"{indent}{d}/")
                for f in sorted(files)[:20]:
                    lines.append(f"{indent}{f}")

                if len(lines) > 100:
                    lines.append("  ... (truncated)")
                    break
        except Exception:
            pass

        return "\n".join(lines)

    def _get_git_branch(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.working_dir),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _find_key_files(self) -> list[str]:
        key_names = {
            "README.md", "README.rst", "pyproject.toml", "setup.py",
            "package.json", "Cargo.toml", "go.mod", "Makefile",
            "docker-compose.yml", "Dockerfile",
        }
        found = []
        for f in self.working_dir.iterdir():
            if f.name in key_names:
                found.append(f.name)
        return found
