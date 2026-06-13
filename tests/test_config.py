import os

import yaml

from codepilot.config.settings import AppSettings, ProviderConfig, DefaultConfig, LangSmithConfig, load_config


class TestAppSettings:
    def test_default_settings(self):
        settings = AppSettings()
        assert settings.agent == "build"
        assert settings.confirm is True
        assert settings.default.provider == "anthropic"

    def test_custom_settings(self):
        settings = AppSettings(
            providers={
                "custom": ProviderConfig(
                    api_key="test-key",
                    base_url="http://localhost:8000/v1",
                    models=["custom-model"],
                    provider_type="openai_compatible",
                )
            },
            default=DefaultConfig(provider="custom", model="custom-model"),
            agent="build",
            confirm=False,
        )
        assert settings.agent == "build"
        assert settings.confirm is False
        assert "custom" in settings.providers
        assert settings.providers["custom"].api_key == "test-key"

    def test_load_config_creates_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codepilot.config.settings.CONFIG_DIR", tmp_path / ".codepilot")
        monkeypatch.setattr("codepilot.config.settings.CONFIG_FILE", tmp_path / ".codepilot" / "config.yaml")

        config = load_config()
        assert isinstance(config, AppSettings)
        assert config.agent == "build"
        assert config.confirm is True
        assert (tmp_path / ".codepilot" / "config.yaml").exists()

    def test_env_var_override(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".codepilot"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({
            "providers": {"openai": {"api_key": "original", "models": ["gpt-4o"], "provider_type": "openai_compatible"}},
            "default": {"provider": "openai", "model": "gpt-4o"},
            "agent": "build",
            "confirm": True,
        }))

        monkeypatch.setattr("codepilot.config.settings.CONFIG_DIR", config_dir)
        monkeypatch.setattr("codepilot.config.settings.CONFIG_FILE", config_file)
        monkeypatch.setenv("CODEPILOT_OPENAI_API_KEY", "env-key")

        config = load_config()
        assert config.providers["openai"].api_key == "env-key"


class TestLangSmithConfig:
    def test_default_enabled(self):
        ls = LangSmithConfig()
        assert ls.enabled is True
        assert ls.api_key == ""
        assert ls.project == "codepilot"

    def test_settings_include_langsmith(self):
        settings = AppSettings()
        assert settings.langsmith.enabled is True
        assert settings.langsmith.project == "codepilot"

    def test_langsmith_env_var_override(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".codepilot"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({
            "providers": {},
            "default": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
            "langsmith": {"enabled": True, "api_key": "", "project": "codepilot"},
            "agent": "build",
            "confirm": True,
        }))

        monkeypatch.setattr("codepilot.config.settings.CONFIG_DIR", config_dir)
        monkeypatch.setattr("codepilot.config.settings.CONFIG_FILE", config_file)
        monkeypatch.setenv("CODEPILOT_LANGSMITH_API_KEY", "ls-test-key")

        config = load_config()
        assert config.langsmith.api_key == "ls-test-key"

    def test_setup_langsmith_enabled_with_key(self, monkeypatch):
        from codepilot.cli import _setup_langsmith
        config = AppSettings(langsmith=LangSmithConfig(enabled=True, api_key="test-key"))
        _setup_langsmith(config)
        assert os.environ.get("LANGSMITH_TRACING") == "true"
        assert os.environ.get("LANGSMITH_API_KEY") == "test-key"

    def test_setup_langsmith_enabled_no_key(self, monkeypatch):
        from codepilot.cli import _setup_langsmith
        config = AppSettings(langsmith=LangSmithConfig(enabled=True, api_key=""))
        _setup_langsmith(config)
        assert os.environ.get("LANGSMITH_TRACING") == "false"

    def test_setup_langsmith_disabled(self, monkeypatch):
        from codepilot.cli import _setup_langsmith
        config = AppSettings(langsmith=LangSmithConfig(enabled=False, api_key="test-key"))
        _setup_langsmith(config)
        assert os.environ.get("LANGSMITH_TRACING") == "false"
