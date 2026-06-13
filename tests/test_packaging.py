from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_codepilot_console_script():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert data["project"]["name"] == "codepilot"
    assert data["project"]["scripts"]["codepilot"] == "codepilot.cli:main"


def test_package_version_matches_runtime_version():
    import codepilot

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert data["project"]["version"] == "0.1.1"
    assert codepilot.__version__ == data["project"]["version"]


def test_hatch_build_includes_package_and_builtin_skills():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel["packages"] == ["codepilot"]
    assert "codepilot/skills/builtin/*/SKILL.md" in wheel["artifacts"]


def test_readme_documents_github_install_path():
    readme = (ROOT / "README.md").read_text()

    assert 'uv tool install "git+https://github.com/jkrandom-sudo/codepilot.git"' in readme
    assert 'pipx install "git+https://github.com/jkrandom-sudo/codepilot.git"' in readme
    assert 'python3.11 -m pip install "git+https://github.com/jkrandom-sudo/codepilot.git"' in readme
    assert "pipx upgrade codepilot" in readme
    assert "python3.11 -m pip install --user pipx" not in readme
