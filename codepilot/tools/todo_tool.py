"""Task list (todo) management tool.

Provides todo_write for managing the agent's
task list within a session.
"""
from __future__ import annotations

import json
import threading
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    content: str = Field(description="Brief task description")
    status: Literal["pending", "in_progress", "completed", "cancelled"] = Field(
        description="Current status: pending, in_progress, completed, or cancelled"
    )
    priority: Literal["high", "medium", "low"] = Field(
        description="Priority level: high, medium, or low"
    )


_session_todos: dict[str, list[TodoItem]] = {}
_todos_lock = threading.Lock()


def get_todos(session_id: str) -> list[TodoItem]:
    with _todos_lock:
        return list(_session_todos.get(session_id, []))


def clear_todos(session_id: str) -> None:
    with _todos_lock:
        _session_todos.pop(session_id, None)


def todo_write_impl(todos: list[dict], session_id: str = "") -> str:
    items = []
    for t in todos:
        try:
            items.append(TodoItem(**t))
        except Exception as e:
            return f"Error: Invalid todo item {t}: {e}"

    in_progress_count = sum(1 for i in items if i.status == "in_progress")
    if in_progress_count > 1:
        return "Error: Only one todo item can be 'in_progress' at a time"

    if session_id:
        with _todos_lock:
            _session_todos[session_id] = items

    lines = []
    for i, item in enumerate(items, 1):
        status_icon = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "completed": "[x]",
            "cancelled": "[-]",
        }.get(item.status, "[?]")
        lines.append(f"{i}. {status_icon} ({item.priority}) {item.content}")
    return "\n".join(lines)


@tool
def todo_write(todos: str, session_id: str = "") -> str:
    """Create and maintain a structured task list for the current session.

    Use proactively when:
    - The task requires 3+ distinct steps
    - The user provides multiple tasks
    - The work is non-trivial and benefits from planning

    Rules:
    - Only one item can be 'in_progress' at a time
    - Mark items 'completed' only after actual work is done
    - Update status in real time; don't batch completions

    Args:
        todos: JSON array of todo items. Each item has:
            - content (string): Brief task description
            - status (string): "pending", "in_progress", "completed", or "cancelled"
            - priority (string): "high", "medium", or "low"
        session_id: Session ID for persistence (auto-filled by tool_node)
    """
    try:
        parsed = json.loads(todos) if isinstance(todos, str) else todos
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON for todos: {e}"
    return todo_write_impl(parsed, session_id)
