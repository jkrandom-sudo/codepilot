from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from codepilot.storage.db import Storage, new_message_id
from codepilot.storage.models import StoredMessage, TextPart, ToolPart


def stored_to_langchain(messages: list[StoredMessage]) -> list[BaseMessage]:
    result: list[BaseMessage] = []
    pending_tool_call_ids: set[str] = set()

    for msg in messages:
        if msg.role == "system":
            content = msg.content
            if not content and msg.parts:
                content = "\n".join(p.content for p in msg.parts if isinstance(p, TextPart))
            result.append(SystemMessage(content=content or ""))
            continue

        if msg.role == "user":
            content = msg.content
            if not content and msg.parts:
                content = "\n".join(p.content for p in msg.parts if isinstance(p, TextPart))
            result.append(HumanMessage(content=content or ""))
            continue

        if msg.role == "assistant":
            if msg.tool_call_id:
                tc_id = msg.tool_call_id
                output = msg.content or ""
                for p in msg.parts:
                    if isinstance(p, ToolPart) and p.tool_call_id == tc_id:
                        output = p.output or output
                        break
                result.append(ToolMessage(content=output, tool_call_id=tc_id))
                pending_tool_call_ids.discard(tc_id)
                continue

            tool_calls = msg.tool_calls
            content = msg.content or ""

            if msg.parts:
                text_parts = [p.content for p in msg.parts if isinstance(p, TextPart)]
                tool_parts = [p for p in msg.parts if isinstance(p, ToolPart)]

                if tool_parts and not tool_calls:
                    tool_calls = []
                    for tp in tool_parts:
                        if tp.state in ("running", "completed", "error"):
                            tc_id = tp.tool_call_id
                            tool_calls.append({
                                "id": tc_id,
                                "name": tp.tool_name,
                                "args": tp.args,
                            })
                            pending_tool_call_ids.add(tc_id)

                if not content and text_parts:
                    content = "\n".join(text_parts)

            if tool_calls:
                result.append(AIMessage(content=content, tool_calls=tool_calls))
            else:
                result.append(AIMessage(content=content))

            for tp in (msg.parts or []):
                if isinstance(tp, ToolPart) and tp.state == "completed" and tp.output is not None:
                    if tp.tool_call_id not in pending_tool_call_ids:
                        continue
                    pending_tool_call_ids.discard(tp.tool_call_id)
                    result.append(ToolMessage(
                        content=tp.output,
                        tool_call_id=tp.tool_call_id,
                    ))
            continue

    return result


def langchain_to_stored(
    messages: list[BaseMessage],
    session_id: str,
) -> list[StoredMessage]:
    base_time = datetime.now()

    result: list[StoredMessage] = []
    for idx, msg in enumerate(messages):
        msg_id = new_message_id()
        created_at = base_time + timedelta(microseconds=idx)

        if isinstance(msg, SystemMessage):
            result.append(StoredMessage(
                id=msg_id, session_id=session_id, role="system",
                content=msg.content or "",
                parts=[TextPart(content=msg.content or "")],
                created_at=created_at,
            ))

        elif isinstance(msg, HumanMessage):
            result.append(StoredMessage(
                id=msg_id, session_id=session_id, role="user",
                content=msg.content or "",
                parts=[TextPart(content=msg.content or "")],
                created_at=created_at,
            ))

        elif isinstance(msg, AIMessage):
            parts = []
            if msg.content:
                parts.append(TextPart(content=msg.content))
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append(ToolPart(
                        tool_name=tc["name"],
                        tool_call_id=tc["id"],
                        args=tc.get("args", {}),
                    ))

            result.append(StoredMessage(
                id=msg_id, session_id=session_id, role="assistant",
                content=msg.content or "",
                parts=parts,
                tool_calls=msg.tool_calls if msg.tool_calls else None,
                created_at=created_at,
            ))

        elif isinstance(msg, ToolMessage):
            result.append(StoredMessage(
                id=msg_id, session_id=session_id, role="assistant",
                content=msg.content or "",
                parts=[ToolPart(
                    tool_name="unknown",
                    tool_call_id=msg.tool_call_id or "",
                    output=msg.content,
                    state="completed",
                )],
                tool_call_id=msg.tool_call_id,
                created_at=created_at,
            ))

    return result


def save_messages(storage: Storage, messages: list[BaseMessage], session_id: str) -> int:
    stored = langchain_to_stored(messages, session_id)
    storage.replace_session_messages(session_id, stored)
    return len(stored)


def load_messages(storage: Storage, session_id: str) -> list[BaseMessage]:
    stored = storage.get_messages(session_id)
    return stored_to_langchain(stored)
