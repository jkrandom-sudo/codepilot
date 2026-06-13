from __future__ import annotations

import time
from pathlib import Path

from codepilot.utils.truncate import truncate_output

TRUNCATION_DIR = Path.home() / ".codepilot" / "truncations"
MAX_TRUNCATION_AGE_DAYS = 7


class TruncationStore:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or TRUNCATION_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def truncate_and_save(self, content: str, tool_call_id: str, max_lines: int = 2000, max_chars: int = 50000) -> tuple[str, str | None]:
        needs_truncation = len(content) > max_chars or content.count("\n") > max_lines
        if not needs_truncation:
            return content, None

        truncated = truncate_output(content, max_lines=max_lines, max_chars=max_chars)

        file_path = self._save_full(content, tool_call_id)

        lines_total = content.count("\n") + 1
        truncated += f"\n\n[Output truncated: {lines_total} lines total. Full output saved to {file_path}]"

        return truncated, str(file_path)

    def _save_full(self, content: str, tool_call_id: str) -> Path:
        ts = int(time.time())
        safe_id = tool_call_id.replace("/", "_").replace("\\", "_")
        filename = f"{ts}_{safe_id}.txt"
        file_path = self.base_dir / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def read_full(self, path: str) -> str | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            resolved = p.resolve()
            if not str(resolved).startswith(str(self.base_dir.resolve())):
                return None
            return resolved.read_text(encoding="utf-8")
        except Exception:
            return None

    def cleanup(self, max_age_days: int = MAX_TRUNCATION_AGE_DAYS) -> int:
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        for f in self.base_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        return removed


_truncation_store: TruncationStore | None = None


def get_truncation_store() -> TruncationStore:
    global _truncation_store
    if _truncation_store is None:
        _truncation_store = TruncationStore()
    return _truncation_store
