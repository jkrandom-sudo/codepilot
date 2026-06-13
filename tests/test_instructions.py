from codepilot.context.instructions import (
    build_agents_md,
    find_instruction_files,
    init_agents_file,
    load_project_instructions,
)


def test_load_project_instructions_supports_agents_and_claude(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Agent Rules\nUse pytest.\n")
    (tmp_path / "CLAUDE.md").write_text("# Claude Rules\nUse ruff.\n")

    files = find_instruction_files(tmp_path)
    loaded = load_project_instructions(tmp_path)

    assert [p.name for p in files] == ["AGENTS.md", "CLAUDE.md"]
    assert "Use pytest" in loaded
    assert "Use ruff" in loaded


def test_init_agents_file_creates_seed(tmp_path):
    (tmp_path / "README.md").write_text("# Demo\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')

    changed, message = init_agents_file(tmp_path)

    assert changed is True
    assert "Created" in message
    content = (tmp_path / "AGENTS.md").read_text()
    assert "# Demo Agent Instructions" in content
    assert "pytest tests/ -q" in content


def test_init_agents_file_does_not_overwrite_without_force(tmp_path):
    (tmp_path / "AGENTS.md").write_text("custom")

    changed, message = init_agents_file(tmp_path)

    assert changed is False
    assert "already exists" in message
    assert (tmp_path / "AGENTS.md").read_text() == "custom"


def test_build_agents_md_includes_project_structure(tmp_path):
    (tmp_path / "codepilot").mkdir()

    content = build_agents_md(tmp_path)

    assert "Project Structure" in content
    assert "`codepilot/`" in content
