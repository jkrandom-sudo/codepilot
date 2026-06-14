from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import ConfigDict

from codepilot.config.context_windows import parse_model_spec
from codepilot.config.settings import AppSettings, ProviderConfig

logger = logging.getLogger(__name__)

LEGACY_DEFAULT_MAX_TOKENS = 4096
LEGACY_MAX_TOKEN_DEFAULTS = {4096, 8192}
DEFAULT_MAX_TOKENS = 16384

MODEL_MAX_TOKENS: dict[str, int] = {
    "deepseek": 16384,
    "glm": 16384,
    "qwen": 16384,
    "gpt": 16384,
    "claude": 32768,
    "gemini": 32768,
}

RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_BASE_DELAY = 2.0
RATE_LIMIT_MAX_DELAY = 30.0
SERVER_ERROR_MAX_RETRIES = 2
SERVER_ERROR_BASE_DELAY = 5.0
NETWORK_ERROR_MAX_RETRIES = 3
NETWORK_ERROR_BASE_DELAY = 1.5


def _is_rate_limit_error(error: Exception) -> bool:
    error_str = str(error)
    status_code = _extract_status_code(error)
    return bool(
        status_code == 429
        or "rate" in error_str.lower()
        or "429" in error_str
        or "too many requests" in error_str.lower()
        or "throttl" in error_str.lower()
    )


def _is_quota_exceeded_error(error: Exception) -> bool:
    """Return true for non-retryable quota/billing exhaustion errors."""
    error_str = str(error).lower()
    return bool(
        "quota_exceeded" in error_str
        or "quota has been exceeded" in error_str
        or "quota exceeded" in error_str
        or "insufficient_quota" in error_str
        or "month_quota" in error_str
        or "billing" in error_str
    )


def _is_server_error(error: Exception) -> bool:
    status_code = _extract_status_code(error)
    return status_code in (500, 502, 503)


def _is_network_error(error: Exception) -> bool:
    """Return true for transient network/connection errors worth retrying.

    LangSmith trace analysis (last 7 days) shows APIConnectionError is the
    most common error class, accounting for ~4% of root runs. These are
    transient and should not bubble up to the user without a retry.
    """
    type_name = type(error).__name__
    if type_name in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ReadTimeout",
        "ConnectTimeout",
        "ReadError",
        "RemoteProtocolError",
        "ConnectionError",
    }:
        return True
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "connection error",
            "connection reset",
            "connection aborted",
            "connection refused",
            "temporary failure in name resolution",
            "remote end closed",
            "read timed out",
        )
    )


class ProviderRegistry:
    def __init__(self, config: AppSettings) -> None:
        self.config = config

    def get_llm(self, model_spec: str) -> BaseChatModel:
        """Create a LLM instance from a model spec like 'anthropic/claude-sonnet-4-20250514' or just 'gpt-4o'.

        The model name can include a context window suffix like [128k] or [1m],
        which is stripped before creating the LLM instance.
        """
        if "/" in model_spec:
            provider_name, raw_model_name = model_spec.split("/", 1)
        else:
            provider_name = self._find_provider_for_model(model_spec)
            raw_model_name = model_spec

        # Strip context window suffix like [128k] from model name
        model_name, _ = parse_model_spec(raw_model_name)

        if provider_name not in self.config.providers:
            raise ValueError(f"Unknown provider: {provider_name}. Available: {list(self.config.providers.keys())}")

        provider_cfg = self.config.providers[provider_name]
        return self._create_llm_with_retry(provider_name, provider_cfg, model_name)

    def _find_provider_for_model(self, model_name: str) -> str:
        for name, cfg in self.config.providers.items():
            if model_name in cfg.models:
                return name
        # Default to the configured default provider
        return self.config.default.provider

    def _create_llm(self, provider_name: str, cfg: ProviderConfig, model_name: str) -> BaseChatModel:
        pt = cfg.provider_type
        max_tokens = self._get_max_tokens(model_name, cfg)

        if pt == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=model_name,
                api_key=cfg.api_key or None,
                max_tokens=max_tokens,
            )

        if pt == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=cfg.api_key or None,
                max_output_tokens=max_tokens,
            )

        if pt == "bedrock":
            from langchain_community.chat_models import ChatBedrock

            return ChatBedrock(
                model_id=model_name,
            )

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=cfg.api_key or "not-needed",
            base_url=cfg.base_url,
            max_tokens=max_tokens,
        )

    def _get_max_tokens(self, model_name: str, cfg: ProviderConfig | None = None) -> int:
        if (
            cfg is not None
            and cfg.max_tokens
            and cfg.max_tokens not in LEGACY_MAX_TOKEN_DEFAULTS | {DEFAULT_MAX_TOKENS}
        ):
            return cfg.max_tokens
        name_lower = model_name.lower()
        for key, tokens in MODEL_MAX_TOKENS.items():
            if key in name_lower:
                return tokens
        return DEFAULT_MAX_TOKENS

    def _create_llm_with_retry(self, provider_name: str, cfg: ProviderConfig, model_name: str) -> BaseChatModel:
        llm = self._create_llm(provider_name, cfg, model_name)
        return RetryableLLM(llm=llm, model_name=model_name)

    def list_models(self) -> dict[str, list[str]]:
        return {name: cfg.models for name, cfg in self.config.providers.items()}


class RetryableLLM(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    llm: Any
    model_name: str = ""

    @property
    def _llm_type(self) -> str:
        return f"retryable-{getattr(self.llm, '_llm_type', 'unknown')}"

    @property
    def model(self) -> str:
        return getattr(self.llm, "model", self.model_name)

    def _generate(self, messages: list, stop: list[str] | None = None, **kwargs: Any) -> Any:
        return self._retry_call(
            lambda: self.llm._generate(messages, stop=stop, **kwargs),
            max_retries=RATE_LIMIT_MAX_RETRIES,
        )

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._retry_call(
            lambda: self.llm.invoke(input, config=config, **kwargs),
            max_retries=RATE_LIMIT_MAX_RETRIES,
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        bound = self.llm.bind_tools(tools, **kwargs)
        return RetryableLLM(llm=bound, model_name=self.model_name)

    def _retry_call(self, fn: Any, max_retries: int = RATE_LIMIT_MAX_RETRIES) -> Any:
        last_error = None
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as e:
                if _is_quota_exceeded_error(e):
                    raise
                if _is_rate_limit_error(e):
                    if attempt >= max_retries:
                        raise
                    delay = min(
                        RATE_LIMIT_BASE_DELAY * (2 ** attempt),
                        RATE_LIMIT_MAX_DELAY,
                    )
                    retry_after = _extract_retry_after(e)
                    if retry_after:
                        delay = min(retry_after, RATE_LIMIT_MAX_DELAY)
                    logger.warning(
                        f"Rate limit hit for {self.model_name} "
                        f"(attempt {attempt + 1}/{max_retries}). Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    attempt += 1
                    last_error = e
                elif _is_server_error(e):
                    if attempt >= SERVER_ERROR_MAX_RETRIES:
                        raise
                    delay = min(
                        SERVER_ERROR_BASE_DELAY * (2 ** attempt),
                        RATE_LIMIT_MAX_DELAY,
                    )
                    logger.warning(
                        f"Server error for {self.model_name} "
                        f"(attempt {attempt + 1}/{SERVER_ERROR_MAX_RETRIES}). Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    attempt += 1
                    last_error = e
                elif _is_network_error(e):
                    if attempt >= NETWORK_ERROR_MAX_RETRIES:
                        raise
                    delay = min(
                        NETWORK_ERROR_BASE_DELAY * (2 ** attempt),
                        RATE_LIMIT_MAX_DELAY,
                    )
                    logger.warning(
                        f"Network error for {self.model_name} "
                        f"({type(e).__name__}, attempt {attempt + 1}/{NETWORK_ERROR_MAX_RETRIES}). "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    attempt += 1
                    last_error = e
                else:
                    raise
        raise last_error  # type: ignore[misc]


def _extract_status_code(error: Exception) -> int | None:
    if hasattr(error, "status_code"):
        return error.status_code
    resp = getattr(error, "response", None)
    if resp is not None:
        return getattr(resp, "status_code", None)
    return None


def _extract_retry_after(error: Exception) -> float | None:
    resp = getattr(error, "response", None)
    if resp is None:
        return None
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except (ValueError, TypeError):
        return None
