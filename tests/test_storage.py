from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from codepilot.storage.db import Storage, new_session_id
from codepilot.storage.models import SessionInfo
from codepilot.storage.resume import load_messages, save_messages


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(db_path=tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def session_id(storage: Storage) -> str:
    sid = new_session_id()
    storage.create_session(SessionInfo(
        id=sid,
        title="test",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    ))
    return sid


class TestRoundTrip:
    def test_round_trip_basic(self, storage: Storage, session_id: str):
        messages = [
            SystemMessage(content="you are a helper"),
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
        save_messages(storage, messages, session_id)
        loaded = load_messages(storage, session_id)
        assert len(loaded) == 3
        assert isinstance(loaded[0], SystemMessage)
        assert isinstance(loaded[1], HumanMessage)
        assert isinstance(loaded[2], AIMessage)
        assert loaded[1].content == "hi"
        assert loaded[2].content == "hello"

    def test_round_trip_with_tool_calls(self, storage: Storage, session_id: str):
        messages = [
            HumanMessage(content="list files"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "glob", "args": {"pattern": "*.py"}}],
            ),
            ToolMessage(content="a.py\nb.py", tool_call_id="call_1"),
            AIMessage(content="found 2 files"),
        ]
        save_messages(storage, messages, session_id)
        loaded = load_messages(storage, session_id)
        assert len(loaded) == 4
        assert isinstance(loaded[1], AIMessage)
        assert loaded[1].tool_calls and loaded[1].tool_calls[0]["name"] == "glob"
        assert isinstance(loaded[2], ToolMessage)
        assert loaded[2].tool_call_id == "call_1"
        assert "a.py" in loaded[2].content

    def test_repeated_save_does_not_duplicate(self, storage: Storage, session_id: str):
        messages = [HumanMessage(content="hi"), AIMessage(content="hello")]
        for _ in range(5):
            save_messages(storage, messages, session_id)

        loaded = load_messages(storage, session_id)
        assert len(loaded) == 2

        session = storage.get_session(session_id)
        assert session is not None
        assert session.message_count == 2

    def test_save_appends_then_replaces(self, storage: Storage, session_id: str):
        save_messages(storage, [HumanMessage(content="first")], session_id)
        assert len(load_messages(storage, session_id)) == 1

        save_messages(
            storage,
            [HumanMessage(content="first"), AIMessage(content="reply")],
            session_id,
        )
        loaded = load_messages(storage, session_id)
        assert len(loaded) == 2
        assert loaded[0].content == "first"
        assert loaded[1].content == "reply"

        session = storage.get_session(session_id)
        assert session.message_count == 2

    def test_compaction_shrinks_session(self, storage: Storage, session_id: str):
        long = [HumanMessage(content=f"msg {i}") for i in range(10)]
        save_messages(storage, long, session_id)
        assert storage.get_session(session_id).message_count == 10

        compacted = [HumanMessage(content="[summary]"), HumanMessage(content="latest")]
        save_messages(storage, compacted, session_id)
        loaded = load_messages(storage, session_id)
        assert len(loaded) == 2
        assert storage.get_session(session_id).message_count == 2

    def test_ordering_preserved(self, storage: Storage, session_id: str):
        msgs = [HumanMessage(content=str(i)) for i in range(20)]
        save_messages(storage, msgs, session_id)
        loaded = load_messages(storage, session_id)
        assert [m.content for m in loaded] == [str(i) for i in range(20)]


class TestStorage:
    def test_save_message_increments_count_once(self, storage: Storage, session_id: str):
        from codepilot.storage.db import new_message_id
        from codepilot.storage.models import StoredMessage, TextPart

        msg = StoredMessage(
            id=new_message_id(),
            session_id=session_id,
            role="user",
            content="hi",
            parts=[TextPart(content="hi")],
            created_at=datetime.now(),
        )
        storage.save_message(msg)
        storage.save_message(msg)
        storage.save_message(msg)
        session = storage.get_session(session_id)
        assert session.message_count == 1

    def test_delete_session_removes_messages(self, storage: Storage, session_id: str):
        save_messages(storage, [HumanMessage(content="x")], session_id)
        assert len(storage.get_messages(session_id)) == 1
        storage.delete_session(session_id)
        assert storage.get_session(session_id) is None
        assert storage.get_messages(session_id) == []
