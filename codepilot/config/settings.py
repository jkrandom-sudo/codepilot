from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


CONFIG_DIR = Path.home() / ".codepilot"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)
    provider_type: str = "openai_compatible"  # "anthropic" | "openai_compatible" | "google" | "bedrock"
    context_window: int | None = None  # Override context window size (tokens) for all models in this provider
    max_tokens: int = 4096  # Max output tokens per response


class DefaultConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"


class LangSmithConfig(BaseModel):
    enabled: bool = True
    api_key: str = ""
    project: str = "codepilot"
    endpoint: str = "https://api.smith.langchain.com"


class MCPServerConfig(BaseModel):
    enabled: bool = True
    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""


class AppSettings(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    default: DefaultConfig = Field(default_factory=DefaultConfig)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)
    mcp: dict[str, MCPServerConfig] = Field(default_factory=dict)
    agent: str = "build"
    confirm: bool = True


DEFAULT_CONFIG = AppSettings(
    providers={
        "openai": ProviderConfig(
            api_key="",
            base_url="https://api.openai.com/v1",
            models=["gpt-4o", "gpt-4o-mini"],
            provider_type="openai_compatible",
        ),
        "anthropic": ProviderConfig(
            api_key="",
            models=["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"],
            provider_type="anthropic",
        ),
        "deepseek": ProviderConfig(
            api_key="",
            base_url="https://api.deepseek.com/v1",
            models=["deepseek-chat", "deepseek-coder"],
            provider_type="openai_compatible",
        ),
        "ollama": ProviderConfig(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
            models=["codellama"],
            provider_type="openai_compatible",
        ),
    },
    default=DefaultConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
    langsmith=LangSmithConfig(
        enabled=True,
        api_key="",
        project="codepilot",
        endpoint="https://api.smith.langchain.com",
    ),
    agent="build",
    confirm=True,
)


def load_config() -> AppSettings:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _write_default_config()
        return DEFAULT_CONFIG.model_copy()

    with open(CONFIG_FILE) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    # Override API keys from environment variables: CODEPILOT_<PROVIDER>_API_KEY
    providers_raw = raw.get("providers", {})
    for name, pdata in providers_raw.items():
        env_key = f"CODEPILOT_{name.upper()}_API_KEY"
        if env_key in os.environ:
            pdata["api_key"] = os.environ[env_key]

    # Override LangSmith API key from environment variable
    langsmith_raw = raw.get("langsmith", {})
    if "CODEPILOT_LANGSMITH_API_KEY" in os.environ:
        langsmith_raw["api_key"] = os.environ["CODEPILOT_LANGSMITH_API_KEY"]

    return AppSettings.model_validate(raw)


def _write_default_config() -> None:
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(DEFAULT_CONFIG.model_dump(), f, default_flow_style=False, sort_keys=False)
