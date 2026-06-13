import yaml

from codepilot.skills import get_skill_manager
from codepilot.tools.mcp_tool import mcp_call_tool, mcp_list_servers
from codepilot.tools.skill_tool import skill_list, skill_read


def test_builtin_skills_are_discoverable(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEPILOT_WORKING_DIR", str(tmp_path))

    names = {skill.name for skill in get_skill_manager(tmp_path).discover()}
    listing = skill_list.invoke({})

    assert {"debug", "code-review", "testing", "refactor", "docs"}.issubset(names)
    assert "debug" in listing


def test_skill_read_loads_builtin_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEPILOT_WORKING_DIR", str(tmp_path))

    content = skill_read.invoke({"name": "debug"})

    assert "# debug" in content
    assert "Reproduce the failure" in content


def test_project_skill_overrides_builtin(monkeypatch, tmp_path):
    skill_dir = tmp_path / ".codepilot" / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# debug\nProject-specific debug skill.\n")
    monkeypatch.setenv("CODEPILOT_WORKING_DIR", str(tmp_path))

    content = skill_read.invoke({"name": "debug"})

    assert "Project-specific" in content


def test_mcp_list_servers_reads_config(tmp_path, monkeypatch):
    config_dir = tmp_path / ".codepilot"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text(yaml.dump({
        "providers": {},
        "default": {"provider": "openai", "model": "gpt-4o"},
        "mcp": {
            "filesystem": {
                "enabled": True,
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            }
        },
    }))
    monkeypatch.setattr("codepilot.config.settings.CONFIG_FILE", config_file)
    monkeypatch.setattr("codepilot.config.settings.CONFIG_DIR", config_dir)

    result = mcp_list_servers.invoke({})

    assert "filesystem" in result
    assert "stdio" in result


def test_mcp_call_tool_rejects_unknown_server(tmp_path, monkeypatch):
    config_dir = tmp_path / ".codepilot"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text(yaml.dump({
        "providers": {},
        "default": {"provider": "openai", "model": "gpt-4o"},
        "mcp": {},
    }))
    monkeypatch.setattr("codepilot.config.settings.CONFIG_FILE", config_file)
    monkeypatch.setattr("codepilot.config.settings.CONFIG_DIR", config_dir)

    result = mcp_call_tool.invoke({"server": "missing", "tool_name": "x", "arguments": "{}"})

    assert "not found" in result
