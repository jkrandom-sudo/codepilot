from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class TokenUsageAccumulator:
    """Accumulate token usage once per AI message when a stable message id exists."""

    def __init__(self) -> None:
        self._seen_message_ids: set[str] = set()
        self.total = TokenUsage()

    def add_message(self, msg: AIMessage) -> TokenUsage:
        msg_id = getattr(msg, "id", None)
        key = f"id:{msg_id}" if msg_id else f"object:{id(msg)}"
        if key in self._seen_message_ids:
            return TokenUsage()
        self._seen_message_ids.add(key)

        usage = extract_token_usage(msg)
        self.total += usage
        return usage


def extract_token_usage(msg: AIMessage) -> TokenUsage:
    """Normalize token usage across LangChain provider metadata formats."""
    usage = getattr(msg, "usage_metadata", None)
    if usage:
        normalized = _usage_from_mapping_or_object(usage)
        if normalized.total_tokens or normalized.input_tokens or normalized.output_tokens:
            return normalized

    metadata = getattr(msg, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage", {}) or metadata.get("usage", {})
    return _usage_from_mapping_or_object(token_usage)


def _usage_from_mapping_or_object(usage: Any) -> TokenUsage:
    input_tokens = _get_int(usage, "input_tokens", "prompt_tokens")
    output_tokens = _get_int(usage, "output_tokens", "completion_tokens")
    total_tokens = _get_int(usage, "total_tokens")
    if not total_tokens and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _get_int(source: Any, *keys: str) -> int:
    for key in keys:
        value = None
        if isinstance(source, dict):
            value = source.get(key)
        else:
            value = getattr(source, key, None)
        if value is not None:
            return int(value or 0)
    return 0
