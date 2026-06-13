"""SQLite-based session storage for conversation persistence.

Manages session CRUD, message history, and context restoration
across agent invocations.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from codepilot.storage.models import (
    CompactionPart,
    FilePart,
    SessionInfo,
    StoredMessage,
    TextPart,
    ToolPart,
)

DATA_DIR = Path.home() / ".codepilot" / "data"
DB_FILENAME = "codepilot.db"

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT 'build',
    model TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'confirm',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0.0,
    message_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (parent_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    parts_json TEXT NOT NULL DEFAULT '[]',
    tool_calls_json TEXT,
    tool_call_id TEXT,
    created_at TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
"""


def _ulid() -> str:
    import time
    ts_ms = int(time.time() * 1000)
    import os
    rand = os.urandom(10).hex()
    return f"{ts_ms:013d}{rand}"


class Storage:
    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            db_path = DATA_DIR / DB_FILENAME
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor

    def _execute_many(self, sql: str, params_list: list[tuple]) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executemany(sql, params_list)
            conn.commit()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(_SCHEMA_V1)
            conn.commit()

    def create_session(self, session: SessionInfo) -> None:
        self._execute(
            """INSERT INTO sessions
               (id, parent_id, title, agent, model, mode, created_at, updated_at, token_count, cost, message_count, archived)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.id, session.parent_id, session.title, session.agent,
                session.model, session.mode, session.created_at.isoformat(),
                session.updated_at.isoformat(), session.token_count, session.cost,
                session.message_count, int(session.archived),
            ),
        )

    def get_session(self, session_id: str) -> SessionInfo | None:
        with self._lock:
            row = self._get_conn().execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    def list_sessions(self, limit: int = 50, include_archived: bool = False) -> list[SessionInfo]:
        with self._lock:
            if include_archived:
                rows = self._get_conn().execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = self._get_conn().execute(
                    "SELECT * FROM sessions WHERE archived = 0 ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def update_session(self, session_id: str, **kwargs: Any) -> None:
        if not kwargs:
            return
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = datetime.now().isoformat()
        if "archived" in kwargs:
            kwargs["archived"] = int(kwargs["archived"])
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [session_id]
        self._execute(f"UPDATE sessions SET {sets} WHERE id = ?", tuple(vals))

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

    def save_message(self, msg: StoredMessage) -> None:
        parts_json = json.dumps([p.model_dump() for p in msg.parts], ensure_ascii=False)
        tool_calls_json = json.dumps(msg.tool_calls) if msg.tool_calls else None
        with self._lock:
            conn = self._get_conn()
            existing = conn.execute("SELECT id FROM messages WHERE id = ?", (msg.id,)).fetchone()
            conn.execute(
                """INSERT OR REPLACE INTO messages
                   (id, session_id, role, content, parts_json, tool_calls_json, tool_call_id, created_at, token_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg.id, msg.session_id, msg.role, msg.content,
                    parts_json, tool_calls_json, msg.tool_call_id,
                    msg.created_at.isoformat(), msg.token_count,
                ),
            )
            if not existing:
                conn.execute(
                    "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), msg.session_id),
                )
            conn.commit()

    def replace_session_messages(self, session_id: str, messages: list[StoredMessage]) -> None:
        rows = []
        for msg in messages:
            parts_json = json.dumps([p.model_dump() for p in msg.parts], ensure_ascii=False)
            tool_calls_json = json.dumps(msg.tool_calls) if msg.tool_calls else None
            rows.append((
                msg.id, msg.session_id, msg.role, msg.content,
                parts_json, tool_calls_json, msg.tool_call_id,
                msg.created_at.isoformat(), msg.token_count,
            ))
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("BEGIN")
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                if rows:
                    conn.executemany(
                        """INSERT INTO messages
                           (id, session_id, role, content, parts_json, tool_calls_json, tool_call_id, created_at, token_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        rows,
                    )
                conn.execute(
                    "UPDATE sessions SET message_count = ?, updated_at = ? WHERE id = ?",
                    (len(rows), datetime.now().isoformat(), session_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_messages(self, session_id: str) -> list[StoredMessage]:
        with self._lock:
            rows = self._get_conn().execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def get_latest_session(self) -> SessionInfo | None:
        with self._lock:
            row = self._get_conn().execute(
                "SELECT * FROM sessions WHERE archived = 0 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return self._row_to_session(row) if row else None

    def get_child_sessions(self, parent_id: str) -> list[SessionInfo]:
        with self._lock:
            rows = self._get_conn().execute(
                "SELECT * FROM sessions WHERE parent_id = ? ORDER BY created_at ASC",
                (parent_id,),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionInfo:
        return SessionInfo(
            id=row["id"],
            parent_id=row["parent_id"],
            title=row["title"],
            agent=row["agent"],
            model=row["model"],
            mode=row["mode"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            token_count=row["token_count"],
            cost=row["cost"],
            message_count=row["message_count"],
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> StoredMessage:
        parts_data = json.loads(row["parts_json"]) if row["parts_json"] else []
        part_types = {"text": TextPart, "tool": ToolPart, "file": FilePart, "compaction": CompactionPart}
        parts = []
        for pd in parts_data:
            cls = part_types.get(pd.get("type", "text"), TextPart)
            parts.append(cls(**{k: v for k, v in pd.items() if k in cls.model_fields}))

        tool_calls = json.loads(row["tool_calls_json"]) if row["tool_calls_json"] else None

        return StoredMessage(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            parts=parts,
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            token_count=row["token_count"],
        )


def new_session_id() -> str:
    return _ulid()


def new_message_id() -> str:
    return _ulid()
