"""Model context window size registry.

Maps model names to their maximum context window sizes (in tokens).
Used by the REPL and agent graph to manage context compaction.

Users can override these defaults via config.yaml:
  providers:
    openai:
      models: [glm-5.1]
      context_window: 128000

Or inline in the model name:
  model: deepseek-v4-pro[128k]   → 128,000 tokens
  model: glm-5.1[1m]             → 1,000,000 tokens
  model: claude-sonnet-4[200k]   → 200,000 tokens

The [suffix] is stripped from the model name before API calls.
"""
from __future__ import annotations

import re

# Pattern to extract context window suffix from model name: [128k], [1m], [200000]
_CONTEXT_SUFFIX_PATTERN = re.compile(r"\[(\d+(?:[km])?)\]\s*$", re.IGNORECASE)

# Default context window when model is unknown
DEFAULT_CONTEXT_WINDOW = 128_000

# Reserve ratio: we only use (1 - reserve) of the context window
# to leave room for the system prompt and response generation.
RESERVE_RATIO = 0.15

# Known model context window sizes (in tokens).
# Keyed by model name substring — matched via `in` check.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic Claude
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-haiku": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4-0125": 128_000,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    # DeepSeek
    "deepseek-v4": 128_000,
    "deepseek-v3": 128_000,
    "deepseek-chat": 128_000,
    "deepseek-coder": 16_000,
    # GLM (Baidu Qianfan / Zhipu)
    "glm-5": 128_000,
    "glm-4": 128_000,
    # Kimi
    "kimi-k2": 128_000,
    "moonshot": 128_000,
    # ERNIE
    "ernie-4": 128_000,
    "ernie-3": 32_000,
    # Google
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.0": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
    # Ollama / local
    "codellama": 16_000,
    "llama3": 8_000,
    "llama-3": 8_000,
    "qwen2": 32_000,
    "mistral": 32_000,
    "mixtral": 32_000,
}


def get_context_window(model_name: str, override: int | None = None) -> int:
    """Get the context window size for a model.

    Args:
        model_name: Model name (e.g. "glm-5.1", "claude-sonnet-4-20250514").
        override: User-configured override from config.yaml, takes precedence.

    Returns:
        Context window size in tokens.
    """
    if override and override > 0:
        return override

    model_lower = model_name.lower()

    # Try exact match first (most specific)
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if key == model_lower:
            return window

    # Try substring match (e.g. "claude-sonnet-4-20250514" matches "claude-sonnet-4")
    best_match = ""
    best_window = DEFAULT_CONTEXT_WINDOW
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if key in model_lower and len(key) > len(best_match):
            best_match = key
            best_window = window

    return best_window


def get_usable_context(model_name: str, override: int | None = None) -> int:
    """Get the usable context window (total minus reserve for response).

    This is the limit we enforce for message history.
    """
    total = get_context_window(model_name, override)
    return int(total * (1 - RESERVE_RATIO))


def parse_model_spec(model_spec: str) -> tuple[str, int | None]:
    """Parse a model spec with optional context window suffix.

    Supported suffixes:
        [128k]  → 128,000 tokens
        [1m]    → 1,000,000 tokens
        [200000]→ 200,000 tokens (plain number)
        [64K]   → 64,000 tokens (case-insensitive)

    Args:
        model_spec: Model name like "deepseek-v4-pro[128k]" or "glm-5.1"

    Returns:
        (clean_model_name, context_window_override_or_None)
    """
    match = _CONTEXT_SUFFIX_PATTERN.search(model_spec)
    if not match:
        return model_spec, None

    suffix = match.group(1).lower()
    if suffix.endswith("k"):
        context = int(suffix[:-1]) * 1_000
    elif suffix.endswith("m"):
        context = int(suffix[:-1]) * 1_000_000
    else:
        context = int(suffix)

    clean_name = model_spec[:match.start()].strip()
    return clean_name, context
