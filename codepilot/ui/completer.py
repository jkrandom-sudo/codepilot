from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class FileIndex:
    """Walks the working directory and maintains a cached list of relative file paths.

    Lazy: the file list is not built until get_files() is first called.
    TTL-based refresh: rebuilds automatically after TTL_SECONDS.
    """

    IGNORE_DIRS = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
        ".idea", ".vscode", "target", ".next", ".nuxt",
        ".ruff_cache", ".cache", ".svn", ".hg",
    }

    IGNORE_EXTENSIONS = frozenset({
        ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".zip", ".tar", ".gz", ".rar", ".7z", ".bz2",
        ".pdf", ".doc", ".docx", ".xlsx", ".pptx",
        ".mp3", ".mp4", ".avi", ".mov", ".wav",
        ".class", ".jar", ".war",
    })

    MAX_FILES = 5000
    TTL_SECONDS = 60

    def __init__(self, working_dir: str | Path = ".") -> None:
        self.working_dir = Path(working_dir).resolve()
        self._files: list[str] = []
        self._last_refresh: float = 0.0

    def get_files(self, force_refresh: bool = False) -> list[str]:
        now = time.time()
        if force_refresh or not self._files or (now - self._last_refresh) > self.TTL_SECONDS:
            self._refresh()
        return self._files

    def _refresh(self) -> None:
        files: list[str] = []
        for root, dirs, filenames in os.walk(self.working_dir):
            dirs[:] = [
                d for d in dirs
                if d not in self.IGNORE_DIRS and not d.startswith(".")
            ]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                if Path(fname).suffix in self.IGNORE_EXTENSIONS:
                    continue
                full_path = Path(root) / fname
                try:
                    rel = str(full_path.relative_to(self.working_dir))
                    files.append(rel)
                except ValueError:
                    continue
                if len(files) >= self.MAX_FILES:
                    break
            if len(files) >= self.MAX_FILES:
                break
        self._files = files
        self._last_refresh = time.time()


class AtFileCompleter(Completer):
    """Custom completer that triggers on @ and offers fuzzy file matches.

    When the user types '@' followed by a partial filename, this completer:
    1. Detects the @ trigger at a word boundary
    2. Extracts the partial text after @ (up to the cursor)
    3. Fuzzy-matches the partial against the FileIndex
    4. Yields Completion objects with relative paths
    """

    EXPLICIT_KEYWORDS = ("file", "url", "git", "dir")

    def __init__(self, file_index: FileIndex) -> None:
        self.file_index = file_index

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterable[Completion]:
        text_before = document.text_before_cursor

        # Find the last @ before cursor
        at_pos = text_before.rfind("@")
        if at_pos < 0:
            return

        # @ must be at a word boundary (start of string or preceded by whitespace)
        if at_pos > 0 and text_before[at_pos - 1] not in (" ", "\t", "\n"):
            return

        # No whitespace between @ and cursor
        text_after_at = text_before[at_pos + 1:]
        if any(c in text_after_at for c in (" ", "\t", "\n")):
            return

        partial = text_after_at
        chars_to_replace = len(text_before) - at_pos
        start_pos = -chars_to_replace

        # Offer explicit keyword completions (@file, @url, @git, @dir)
        if partial == "" or any(kw.startswith(partial) for kw in self.EXPLICIT_KEYWORDS):
            for kw in sorted(self.EXPLICIT_KEYWORDS):
                if partial == "" or kw.startswith(partial):
                    yield Completion(
                        text=f"@{kw} ",
                        start_position=start_pos,
                        display=f"@{kw}",
                        display_meta="reference type",
                    )

        # Offer file completions
        files = self.file_index.get_files()
        matches = _fuzzy_match(partial, files)
        for path, _score in matches:
            yield Completion(
                text=f"@{path}",
                start_position=start_pos,
                display=f"@{path}",
                display_meta="file",
            )


def _fuzzy_match(
    query: str, candidates: list[str], max_results: int = 30
) -> list[tuple[str, tuple]]:
    """Fuzzy match query against candidate file paths.

    Returns (path, score) sorted by relevance.
    Score: (tier, match_start, match_length)
      tier 0 = basename match (best)
      tier 1 = path match
    """
    if not query:
        sorted_candidates = sorted(candidates, key=lambda c: (c.rsplit("/", 1)[-1], c))
        return [(c, (0, 0, 0)) for c in sorted_candidates[:max_results]]

    query_lower = query.lower()
    pat = ".*?".join(map(re.escape, query_lower))
    regex = re.compile(f"(?=({pat}))", re.IGNORECASE)

    results: list[tuple[str, tuple]] = []
    for candidate in candidates:
        candidate_lower = candidate.lower()
        basename = candidate.rsplit("/", 1)[-1]
        basename_start = len(candidate) - len(basename)

        matches = list(regex.finditer(candidate_lower))
        if not matches:
            continue

        best = min(matches, key=lambda m: (m.start(), len(m.group(1))))
        is_basename_match = best.start() >= basename_start
        tier = 0 if is_basename_match else 1
        score = (tier, best.start(), len(best.group(1)))
        results.append((candidate, score))

    results.sort(key=lambda x: x[1])
    return results[:max_results]
