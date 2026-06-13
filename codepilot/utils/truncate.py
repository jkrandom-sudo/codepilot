from __future__ import annotations


def truncate_output(text: str, max_lines: int = 300, max_chars: int = 20000) -> str:
    """Truncate output to fit within token limits."""
    if not text:
        return text

    # Truncate by character count first
    if len(text) > max_chars:
        text = text[:max_chars]

    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    kept = lines[:max_lines]
    remaining = len(lines) - max_lines
    kept.append(f"... ({remaining} more lines truncated)")
    return "\n".join(kept)
