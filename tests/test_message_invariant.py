"""Tests for the AIMessage(tool_calls) -> ToolMessage invariant.

The API requires that every AIMessage with tool_calls must be followed by
a ToolMessage for each tool_call_id. These tests verify that compaction
and compression algorithms preserve this invariant.
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from codepilot.agent._utils import find_tool_call_pairs
from codepilot.agent.compaction import compact_messages
from codepilot.agent.graph import _compress_tool_results
from codepilot.agent.nodes import MAX_ITERATIONS


def _make_conversation(rounds: int = 3) -> list:
    """Build a realistic conversation with multiple tool call rounds."""
    messages = [SystemMessage(content="You are a helpful assistant.")]

    for i in range(rounds):
        messages.append(HumanMessage(content=f"Task {i}"))
        messages.append(AIMessage(
            content="",
            tool_calls=[{"id": f"tc_{i}_1", "name": "read_file", "args": {"path": f"file_{i}.py"}}],
        ))
        messages.append(ToolMessage(content=f"content of file_{i}.py", tool_call_id=f"tc_{i}_1"))
        messages.append(AIMessage(
            content="",
            tool_calls=[{"id": f"tc_{i}_2", "name": "edit_file", "args": {"path": f"file_{i}.py", "old_str": "old", "new_str": "new"}}],
        ))
        messages.append(ToolMessage(content=f"Edited file_{i}.py", tool_call_id=f"tc_{i}_2"))
        messages.append(AIMessage(content=f"Done with task {i}"))

    return messages


def _check_invariant(messages: list) -> list[str]:
    """Verify that every AIMessage(tool_calls) has matching ToolMessages.

    Returns a list of error descriptions. Empty list means invariant holds.
    """
    errors = []
    # Map tool_call_id -> AIMessage index
    expected_tool_ids: dict[str, int] = {}
    # Map tool_call_id -> ToolMessage index
    found_tool_ids: dict[str, int] = {}

    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                expected_tool_ids[tc["id"]] = i
        elif isinstance(msg, ToolMessage):
            found_tool_ids[msg.tool_call_id] = i

    # Every expected tool_call_id must have a matching ToolMessage
    for tc_id, ai_idx in expected_tool_ids.items():
        if tc_id not in found_tool_ids:
            errors.append(f"AIMessage at index {ai_idx} has tool_call_id '{tc_id}' but no ToolMessage")
        elif found_tool_ids[tc_id] <= ai_idx:
            errors.append(f"ToolMessage for '{tc_id}' at index {found_tool_ids[tc_id]} comes before AIMessage at index {ai_idx}")

    # Every ToolMessage must have a matching AIMessage(tool_call)
    for tc_id, tm_idx in found_tool_ids.items():
        if tc_id not in expected_tool_ids:
            errors.append(f"ToolMessage at index {tm_idx} has tool_call_id '{tc_id}' but no AIMessage with that tool_call")

    return errors


class TestFindToolCallPairs:
    def test_basic_pairing(self):
        messages = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "read_file", "args": {}}]),
            ToolMessage(content="result", tool_call_id="1"),
        ]
        groups = find_tool_call_pairs(messages)
        assert len(groups) == 1
        assert groups[0] == [0, 1]

    def test_multiple_tool_calls(self):
        messages = [
            AIMessage(content="", tool_calls=[
                {"id": "1", "name": "read_file", "args": {}},
                {"id": "2", "name": "edit_file", "args": {}},
            ]),
            ToolMessage(content="result1", tool_call_id="1"),
            ToolMessage(content="result2", tool_call_id="2"),
        ]
        groups = find_tool_call_pairs(messages)
        assert len(groups) == 1
        assert groups[0] == [0, 1, 2]

    def test_multiple_rounds(self):
        messages = _make_conversation(2)
        groups = find_tool_call_pairs(messages)
        # 2 rounds, each with 2 tool calls
        assert len(groups) == 4

    def test_no_tool_calls(self):
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
        ]
        groups = find_tool_call_pairs(messages)
        assert len(groups) == 0


class TestCompactMessagesInvariant:
    def test_short_messages_unchanged(self):
        messages = _make_conversation(1)
        result = compact_messages(messages)
        assert result == messages

    def test_invariant_preserved_after_compaction(self):
        messages = _make_conversation(5)  # 5 rounds = 31 messages
        assert len(messages) > 8

        result = compact_messages(messages)
        errors = _check_invariant(result)
        assert errors == [], f"Invariant violated after compaction: {errors}"

    def test_compaction_keeps_recent_pairs(self):
        """Recent tool call pairs should survive compaction intact."""
        messages = _make_conversation(5)
        result = compact_messages(messages)

        # The last tool call pair should be preserved
        last_ai = None
        for msg in reversed(result):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                last_ai = msg
                break

        assert last_ai is not None, "No AIMessage with tool_calls found after compaction"

        # Check that its ToolMessages exist
        tc_ids = {tc["id"] for tc in last_ai.tool_calls}
        found_ids = set()
        for msg in result:
            if isinstance(msg, ToolMessage) and msg.tool_call_id in tc_ids:
                found_ids.add(msg.tool_call_id)
        assert found_ids == tc_ids, f"Missing ToolMessages for: {tc_ids - found_ids}"

    def test_no_orphaned_tool_messages(self):
        """No ToolMessage should exist without a corresponding AIMessage(tool_calls)."""
        messages = _make_conversation(5)
        result = compact_messages(messages)

        tc_ids_from_ai = set()
        for msg in result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_ids_from_ai.add(tc["id"])

        for msg in result:
            if isinstance(msg, ToolMessage):
                assert msg.tool_call_id in tc_ids_from_ai, \
                    f"Orphaned ToolMessage with tool_call_id '{msg.tool_call_id}'"

    def test_compaction_preserves_pairs_with_multiple_system_messages(self):
        """System messages should not shift non-system tool-pair indexes."""
        messages = [
            SystemMessage(content="base system"),
            SystemMessage(content="runtime system"),
        ]
        for i in range(6):
            messages.extend([
                HumanMessage(content=f"Task {i}"),
                AIMessage(
                    content="",
                    tool_calls=[{
                        "id": f"tc_{i}",
                        "name": "read_file",
                        "args": {"path": f"file_{i}.py"},
                    }],
                ),
                ToolMessage(content=f"content of file_{i}.py", tool_call_id=f"tc_{i}"),
                AIMessage(content=f"Done {i}"),
            ])

        result = compact_messages(messages)
        errors = _check_invariant(result)
        assert errors == [], f"Invariant violated after compaction: {errors}"

    def test_compaction_summarizes_old_pairs_in_single_long_active_turn(self):
        messages = [SystemMessage(content="system"), HumanMessage(content="Fix the project")]
        for i in range(14):
            messages.extend([
                AIMessage(
                    content="",
                    tool_calls=[{
                        "id": f"tc_{i}",
                        "name": "read_file",
                        "args": {"path": f"file_{i}.py"},
                    }],
                ),
                ToolMessage(content=f"{i}: def function_{i}(): pass", tool_call_id=f"tc_{i}"),
            ])

        result = compact_messages(messages, tail_turns=2)

        errors = _check_invariant(result)
        assert errors == [], f"Invariant violated after compaction: {errors}"
        assert len(result) < len(messages)
        assert any(
            isinstance(m, HumanMessage) and "Original user request: Fix the project" in m.content
            for m in result
        )
        assert any(isinstance(m, ToolMessage) and m.tool_call_id == "tc_13" for m in result)
        assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "tc_0" for m in result)


class TestCompressToolResultsInvariant:
    def test_invariant_preserved_after_compression(self):
        messages = _make_conversation(3)
        # Make one tool result very large
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                messages[i] = ToolMessage(content="x" * 5000, tool_call_id=msg.tool_call_id)
                break

        result = _compress_tool_results(messages)
        errors = _check_invariant(result)
        assert errors == [], f"Invariant violated after compression: {errors}"

    def test_compression_preserves_tool_call_id(self):
        messages = [
            AIMessage(content="", tool_calls=[{"id": "abc123", "name": "read_file", "args": {}}]),
            ToolMessage(content="x" * 5000, tool_call_id="abc123"),
        ]
        result = _compress_tool_results(messages)
        assert len(result) == 2
        assert isinstance(result[1], ToolMessage)
        assert result[1].tool_call_id == "abc123"

    def test_head_tail_compression(self):
        """Large tool results should be truncated with disk spill."""
        lines = [f"line {i} " + "x" * 80 for i in range(400)]
        content = "\n".join(lines)
        messages = [
            AIMessage(content="", tool_calls=[{"id": "1", "name": "read_file", "args": {}}]),
            ToolMessage(content=content, tool_call_id="1"),
        ]
        result = _compress_tool_results(messages)
        assert isinstance(result[1], ToolMessage)
        # Should contain head and truncation notice (saved to disk)
        assert "line 0" in result[1].content
        assert "truncated" in result[1].content.lower() or "omitted" in result[1].content.lower() or "Output truncated" in result[1].content


class TestIterationLimit:
    def test_max_iterations_is_reasonable(self):
        assert MAX_ITERATIONS >= 80

    def test_iteration_count_in_conversation(self):
        """Verify we can count iterations from messages."""
        messages = _make_conversation(3)
        iteration_count = sum(
            1 for m in messages
            if isinstance(m, AIMessage) and m.tool_calls
        )
        assert iteration_count == 6  # 3 rounds x 2 tool calls each
