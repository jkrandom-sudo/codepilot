"""Pydantic models for session storage.

Defines StoredMessage and related data models
used for serialization and deserialization.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    content: str


class ToolPart(BaseModel):
    type: Literal["tool"] = "tool"
    tool_name: str
    tool_call_id: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    state: Literal["running", "completed", "error"] = "running"
    elapsed_ms: int = 0


class FilePart(BaseModel):
    type: Literal["file"] = "file"
    path: str
    content: str


class CompactionPart(BaseModel):
    type: Literal["compaction"] = "compaction"
    summary: str


MessagePart = TextPart | ToolPart | FilePart | CompactionPart


class StoredMessage(BaseModel):
    model_config = ConfigDict()

    id: str = Field(description="ULID-based message ID")
    session_id: str = Field(description="Parent session ID")
    role: Literal["user", "assistant", "system"] = "user"
    parts: list[MessagePart] = Field(default_factory=list)
    content: str = Field(default="", description="Raw text content for LangChain compatibility")
    tool_calls: list[dict[str, Any]] | None = Field(default=None, description="LangChain tool_calls")
    tool_call_id: str | None = Field(default=None, description="LangChain tool_call_id for ToolMessage")
    created_at: datetime = Field(default_factory=datetime.now)
    token_count: int = 0


class SessionInfo(BaseModel):
    model_config = ConfigDict()
    id: str = Field(description="ULID-based session ID")
    parent_id: str | None = Field(default=None, description="Parent session for sub-agents")
    title: str = ""
    agent: str = "build"
    model: str = ""
    mode: str = "confirm"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    token_count: int = 0
    cost: float = 0.0
    message_count: int = 0
    archived: bool = False
