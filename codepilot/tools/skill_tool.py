from __future__ import annotations

import os

from langchain_core.tools import tool

from codepilot.skills import get_skill_manager


@tool
def skill_list() -> str:
    """List available reusable agent skills.

    Use this before skill_read when a task would benefit from specialized
    workflow guidance such as debugging, testing, refactoring, code review, or docs.
    """
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    return get_skill_manager(working_dir).list_text()


@tool
def skill_read(name: str) -> str:
    """Load the full content of a skill by name.

    Args:
        name: Skill folder name, for example "debug", "testing", or "code-review".
    """
    working_dir = os.environ.get("CODEPILOT_WORKING_DIR", ".")
    return get_skill_manager(working_dir).read(name)
