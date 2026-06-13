"""Context and tool-result management for the agent loop."""
from __future__ import annotations

import re

from langchain_core.messages import AIMessage, ToolMessage

from codepilot.tools.truncation import get_truncation_store

DEFAULT_TOOL_RESULT_CHARS = 10000
MIN_TOOL_RESULT_CHARS = 4000
MAX_TOOL_RESULT_CHARS = 128000
TOOL_RESULT_CONTEXT_CHAR_RATIO = 0.35
MIN_TOOL_RESULT_LINES = 300
MAX_TOOL_RESULT_LINES = 6000
TOOL_RESULT_CONTEXT_LINE_RATIO = 0.012
FILE_SUMMARY_MAX_SCAN_LINES = 600
FILE_SUMMARY_MAX_LINES = FILE_SUMMARY_MAX_SCAN_LINES
FILE_SUMMARY_MAX_KEY_LINES = 20
FILE_SUMMARY_MAX_LINE_LEN = 220

_NUMBERED_LINE = re.compile(r"^\s*(\d+):\s?(.*)$")
_STRUCTURAL_PATTERNS = (
    re.compile(r"^\s*(from\s+\S+\s+import\s+|import\s+\S+)"),
    re.compile(r"^\s*(class|def|async\s+def)\s+\w+"),
    re.compile(r"^\s*(const|let|var|function|export\s+(default\s+)?(class|function|const|interface|type))\b"),
    re.compile(r"^\s*(interface|type|enum)\s+\w+"),
    re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}\s*="),
    re.compile(r"^\s*(if\s+__name__\s*==|@[\w.]+)"),
    re.compile(r"^\s*#{1,3}\s+\S+"),
)


class AgentContextManager:
    """Own context-derived summaries and tool-result shaping."""

    def __init__(
        self,
        *,
        context_window: int | None = None,
        truncation_store=None,
        base_tool_result_chars: int = DEFAULT_TOOL_RESULT_CHARS,
    ) -> None:
        self.context_window = context_window
        self.truncation_store = truncation_store or get_truncation_store()
        self.base_tool_result_chars = base_tool_result_chars

    def tool_result_char_limit(self) -> int:
        """Return a context-aware tool-result cap."""
        if not self.context_window:
            return self.base_tool_result_chars
        adaptive = int(self.context_window * TOOL_RESULT_CONTEXT_CHAR_RATIO)
        return max(MIN_TOOL_RESULT_CHARS, min(MAX_TOOL_RESULT_CHARS, adaptive))

    def tool_result_line_limit(self) -> int:
        """Return a context-aware line cap for tool results."""
        if not self.context_window:
            return MIN_TOOL_RESULT_LINES
        adaptive = int(self.context_window * TOOL_RESULT_CONTEXT_LINE_RATIO)
        return max(MIN_TOOL_RESULT_LINES, min(MAX_TOOL_RESULT_LINES, adaptive))

    def compress_tool_results(self, messages: list) -> list:
        """Truncate large ToolMessages and spill full content to disk."""
        limit = self.tool_result_char_limit()
        line_limit = self.tool_result_line_limit()
        result = []
        for msg in messages:
            if isinstance(msg, ToolMessage) and (
                len(msg.content) > limit or msg.content.count("\n") > line_limit
            ):
                truncated, _ = self.truncation_store.truncate_and_save(
                    msg.content,
                    msg.tool_call_id,
                    max_lines=line_limit,
                    max_chars=limit,
                )
                result.append(ToolMessage(content=truncated, tool_call_id=msg.tool_call_id))
            else:
                result.append(msg)
        return result

    def extract_file_summaries(self, messages: list, files_context: list[str]) -> dict[str, str]:
        """Build {file_path: one-line summary} from previous read_file results."""
        if not files_context:
            return {}

        tool_call_info: dict[str, tuple[str, dict]] = {}
        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call_info[tc["id"]] = (tc["name"], tc.get("args", {}))

        files_set = set(files_context)
        summaries: dict[str, str] = {}
        for msg in messages:
            if not isinstance(msg, ToolMessage) or not msg.content:
                continue
            info = tool_call_info.get(msg.tool_call_id)
            if not info or info[0] != "read_file":
                continue
            path = info[1].get("path", "")
            if path not in files_set or path in summaries:
                continue
            if msg.content.startswith("Error") or msg.content.startswith("[BLOCKED]"):
                continue

            summary = self._summarize_file_content(msg.content)
            if summary:
                summaries[path] = summary

        return summaries

    def render_files_context(self, files_context: list[str], file_summaries: dict[str, str]) -> str:
        """Render the system-prompt block that prevents redundant file reads."""
        if not files_context:
            return ""

        parts = ["## FILES ALREADY IN CONTEXT (DO NOT RE-READ):"]
        for path in files_context:
            parts.append(f"  - {path}")

        if file_summaries:
            parts.append("\n### Key content from earlier reads:")
            for path, summary in file_summaries.items():
                parts.append(f"  {path}: {summary}")
            parts.append(
                "\nCRITICAL: Do NOT re-read these files. Context compaction may have "
                "removed full content, but the summaries above contain key information. "
                "Re-reading will be BLOCKED and wastes your iteration budget. "
                "If you need specific details, check your earlier messages or the "
                "[Previous context: ...] summary."
            )
        else:
            parts.append(
                "You already have the content of these files. "
                "Do NOT call read_file or run_shell(cat) on them."
            )
        return "\n".join(parts)

    def _summarize_file_content(self, content: str) -> str:
        lines = content.split("\n")
        structural_lines: list[str] = []
        fallback_lines: list[str] = []

        for line in lines[:FILE_SUMMARY_MAX_SCAN_LINES]:
            stripped = _strip_numbered_prefix(line)
            if not stripped:
                continue
            clipped = stripped[:FILE_SUMMARY_MAX_LINE_LEN]
            if _is_structural_line(stripped):
                if clipped not in structural_lines:
                    structural_lines.append(clipped)
            elif len(fallback_lines) < FILE_SUMMARY_MAX_KEY_LINES:
                fallback_lines.append(clipped)
            if len(structural_lines) >= FILE_SUMMARY_MAX_KEY_LINES:
                break

        key_lines = structural_lines[:FILE_SUMMARY_MAX_KEY_LINES]
        for line in fallback_lines:
            if len(key_lines) >= FILE_SUMMARY_MAX_KEY_LINES:
                break
            if line not in key_lines:
                key_lines.append(line)
        return " | ".join(key_lines)


def _strip_numbered_prefix(line: str) -> str:
    match = _NUMBERED_LINE.match(line)
    if match:
        return match.group(2).strip()
    return line.strip()


def _is_structural_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in _STRUCTURAL_PATTERNS)


def extract_file_summaries(messages: list, files_context: list[str]) -> dict[str, str]:
    return AgentContextManager().extract_file_summaries(messages, files_context)


def compress_tool_results(messages: list, truncation_store=None) -> list:
    return AgentContextManager(truncation_store=truncation_store).compress_tool_results(messages)


def render_files_context_block(files_context: list[str], file_summaries: dict[str, str]) -> str:
    return AgentContextManager().render_files_context(files_context, file_summaries)
