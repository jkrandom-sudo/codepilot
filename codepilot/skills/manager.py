"""Skill manager for loading and listing built-in and user skills.

Skills are reusable task templates that guide the agent
on how to approach specific problem types.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    description: str = ""
    source: str = "builtin"


class SkillManager:
    def __init__(self, working_dir: str | Path | None = None) -> None:
        self.working_dir = Path(working_dir or os.environ.get("CODEPILOT_WORKING_DIR", ".")).resolve()

    def discover(self) -> list[Skill]:
        skills: dict[str, Skill] = {}
        for source, root in self._roots():
            if not root.exists() or not root.is_dir():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                name = skill_file.parent.name
                skills.setdefault(name, self._skill_from_file(name, skill_file, source))
        return sorted(skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Skill | None:
        for skill in self.discover():
            if skill.name == name:
                return skill
        return None

    def read(self, name: str) -> str:
        skill = self.get(name)
        if skill is None:
            names = ", ".join(s.name for s in self.discover()) or "none"
            return f"Error: Skill '{name}' not found. Available skills: {names}"
        return skill.path.read_text(encoding="utf-8", errors="replace")

    def list_text(self) -> str:
        skills = self.discover()
        if not skills:
            return "No skills found."
        lines = []
        for skill in skills:
            desc = f" — {skill.description}" if skill.description else ""
            lines.append(f"- {skill.name} ({skill.source}){desc}")
        return "\n".join(lines)

    def _roots(self) -> list[tuple[str, Path]]:
        package_root = Path(__file__).parent / "builtin"
        return [
            ("project", self.working_dir / ".codepilot" / "skills"),
            ("claude", self.working_dir / ".claude" / "skills"),
            ("user", Path.home() / ".codepilot" / "skills"),
            ("user-claude", Path.home() / ".claude" / "skills"),
            ("builtin", package_root),
        ]

    def _skill_from_file(self, name: str, path: Path, source: str) -> Skill:
        text = path.read_text(encoding="utf-8", errors="replace")
        return Skill(name=name, path=path, description=_extract_description(text), source=source)


def _extract_description(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped[:160]
    return ""


def get_skill_manager(working_dir: str | Path | None = None) -> SkillManager:
    return SkillManager(working_dir)
