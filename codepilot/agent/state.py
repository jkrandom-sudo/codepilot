"""Typed agent state definition for LangGraph.

Defines the AgentState TypedDict used across
all graph nodes for message passing.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing import TypedDict


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    working_dir: str
    files_context: list[str]
    task_type: str  # e.g. "code_search", "project_analysis", "file_edit", "subagent"
    agent_name: str  # e.g. "build", "plan", "explore", "general" — single source of truth
    session_id: str  # Session identifier for persistence
