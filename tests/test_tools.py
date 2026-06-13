import json
import os
import tempfile

import pytest

from codepilot.tools.file_tools import read_file, write_file, edit_file, glob
from codepilot.tools.search_tools import grep
from codepilot.tools.shell_tool import run_shell
from codepilot.tools.web_fetch_tool import web_fetch
from codepilot.tools.todo_tool import todo_write
from codepilot.tools import get_tools_for_agent


@pytest.fixture
def work_dir(tmp_path):
    os.environ["CODEPILOT_WORKING_DIR"] = str(tmp_path)

    (tmp_path / "hello.py").write_text("print('hello world')\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    return 42\n")

    yield tmp_path
    del os.environ["CODEPILOT_WORKING_DIR"]


class TestReadFile:
    def test_read_file_with_line_numbers(self, work_dir):
        result = read_file.invoke({"path": "hello.py"})
        assert "1:" in result
        assert "hello world" in result

    def test_read_file_with_offset_limit(self, work_dir):
        (work_dir / "multi.py").write_text("line1\nline2\nline3\nline4\nline5\n")
        result = read_file.invoke({"path": "multi.py", "offset": 2, "limit": 2})
        assert "2: line2" in result
        assert "3: line3" in result
        assert "line1" not in result
        assert "line4" not in result

    def test_read_file_offset_works_beyond_default_full_read_truncation(self, work_dir):
        lines = [f"line {i} {'x' * 80}" for i in range(1, 3000)]
        (work_dir / "large.py").write_text("\n".join(lines))

        result = read_file.invoke({"path": "large.py", "offset": 2500, "limit": 2})

        assert "2500: line 2500" in result
        assert "2501: line 2501" in result

    def test_read_file_not_found(self, work_dir):
        result = read_file.invoke({"path": "nonexistent.py"})
        assert "Error" in result

    def test_read_file_fuzzy_suggest(self, work_dir):
        result = read_file.invoke({"path": "helo.py"})
        assert "Did you mean" in result or "Error" in result

    def test_read_directory(self, work_dir):
        result = read_file.invoke({"path": "."})
        assert "hello.py" in result
        assert "src/" in result

    def test_read_directory_filters_noise(self, work_dir):
        (work_dir / ".idea").mkdir()
        (work_dir / "__pycache__").mkdir()
        result = read_file.invoke({"path": "."})
        assert ".idea/" not in result
        assert "__pycache__/" not in result
        assert "hello.py" in result

    def test_read_binary_file(self, work_dir):
        (work_dir / "test.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        result = read_file.invoke({"path": "test.zip"})
        assert "binary" in result.lower()

    def test_path_traversal_blocked(self, work_dir):
        result = read_file.invoke({"path": "/etc/passwd"})
        assert "Error" in result or "Cannot read from /etc" in result

    def test_read_external_file(self, work_dir):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, dir="/tmp") as f:
            f.write("external content")
            ext_path = f.name
        try:
            result = read_file.invoke({"path": ext_path})
            assert "external content" in result
        finally:
            os.unlink(ext_path)


class TestWriteFile:
    def test_write_file(self, work_dir):
        result = write_file.invoke({"path": "new.py", "content": "print('new')\n"})
        assert "Wrote" in result
        assert (work_dir / "new.py").read_text() == "print('new')\n"

    def test_write_file_creates_dirs(self, work_dir):
        result = write_file.invoke({"path": "deep/nested/file.py", "content": "test"})
        assert "Wrote" in result

    def test_write_file_still_restricted(self, work_dir):
        result = write_file.invoke({"path": "/tmp/should_not_write.txt", "content": "test"})
        assert "Error" in result or "outside" in result


class TestEditFile:
    def test_edit_file(self, work_dir):
        result = edit_file.invoke({"path": "hello.py", "old_str": "hello world", "new_str": "hello python"})
        assert "Edited" in result
        assert "hello python" in (work_dir / "hello.py").read_text()

    def test_edit_file_not_found_str(self, work_dir):
        result = edit_file.invoke({"path": "hello.py", "old_str": "nonexistent", "new_str": "x"})
        assert "not found" in result

    def test_edit_file_multiple_match(self, work_dir):
        (work_dir / "dup.py").write_text("aaa\nbbb\naaa\n")
        result = edit_file.invoke({"path": "dup.py", "old_str": "aaa", "new_str": "ccc"})
        assert "2 times" in result or "replace_all" in result

    def test_edit_file_replace_all(self, work_dir):
        (work_dir / "dup.py").write_text("aaa\nbbb\naaa\n")
        result = edit_file.invoke({"path": "dup.py", "old_str": "aaa", "new_str": "ccc", "replace_all": True})
        assert "Edited" in result
        content = (work_dir / "dup.py").read_text()
        assert content.count("ccc") == 2
        assert "aaa" not in content

    def test_edit_file_create_new(self, work_dir):
        result = edit_file.invoke({"path": "new_file.py", "old_str": "", "new_str": "print('new')\n"})
        assert "Created" in result
        assert (work_dir / "new_file.py").exists()

    def test_edit_file_fuzzy_suggest(self, work_dir):
        result = edit_file.invoke({"path": "helo.py", "old_str": "x", "new_str": "y"})
        assert "Did you mean" in result or "Error" in result


class TestGlob:
    def test_glob(self, work_dir):
        result = glob.invoke({"pattern": "**/*.py"})
        assert "hello.py" in result
        assert "main.py" in result

    def test_glob_no_match(self, work_dir):
        result = glob.invoke({"pattern": "**/*.rs"})
        assert "No files" in result

    def test_glob_result_limit(self, work_dir):
        for i in range(150):
            (work_dir / f"file_{i:03d}.txt").write_text("x")
        result = glob.invoke({"pattern": "*.txt"})
        assert "more results" in result


class TestShellTool:
    def test_run_shell(self, work_dir):
        result = run_shell.invoke({"command": "echo hello"})
        assert "hello" in result

    def test_run_shell_timeout(self, work_dir):
        result = run_shell.invoke({"command": "sleep 60", "timeout": 1})
        assert "timed out" in result

    def test_dangerous_command_blocked(self, work_dir):
        result = run_shell.invoke({"command": "rm -rf /"})
        assert "blocked" in result.lower() or "dangerous" in result.lower()

    def test_run_shell_description(self, work_dir):
        result = run_shell.invoke({"command": "echo hello", "description": "test echo"})
        assert "hello" in result

    def test_run_shell_workdir(self, work_dir):
        result = run_shell.invoke({"command": "pwd", "workdir": str(work_dir)})
        assert str(work_dir) in result

    def test_run_shell_uses_active_python_environment(self, work_dir):
        result = run_shell.invoke({"command": "python -c \"import sys; print(sys.executable)\""})
        assert ".venv" in result

    def test_run_shell_user_confirmed_search_command_executes(self, work_dir):
        (work_dir / "aaa.txt").write_text("hello\n")

        result = run_shell.invoke({
            "command": "ls -1 . | head -1",
            "workdir": str(work_dir),
            "allow_search_commands": True,
        })

        assert "[BLOCKED]" not in result
        assert "aaa.txt" in result

    def test_dangerous_patterns_legacy_alias_exists(self):
        from codepilot.tools.shell_tool import DANGEROUS_PATTERNS

        assert any("mkfs" in pattern for pattern in DANGEROUS_PATTERNS)

    @pytest.mark.parametrize("command", [
        "echo x; rm -rf /tmp",
        "/bin/rm -rf /foo",
        "mkfs.ext4 /dev/sdb",
        "`rm -rf /tmp`",
    ])
    def test_dangerous_base_detection_catches_clause_and_variant_bypasses(self, command):
        from codepilot.tools.shell_tool import _has_dangerous_base

        assert _has_dangerous_base(command) is not None

    @pytest.mark.parametrize("command", [
        "pytest tests/test_grep.py",
        "python ls_tool.py",
    ])
    def test_search_detection_ignores_search_words_in_filenames(self, command):
        from codepilot.tools.shell_tool import _is_search_command

        is_search, _ = _is_search_command(command)
        assert is_search is False


class TestGrep:
    def test_grep(self, work_dir):
        result = grep.invoke({"pattern": "hello", "path": "."})
        assert "hello" in result

    def test_grep_no_match(self, work_dir):
        result = grep.invoke({"pattern": "zzzznonexistent", "path": "."})
        assert "No matches" in result

    def test_grep_include(self, work_dir):
        result = grep.invoke({"pattern": "def", "path": ".", "include": "*.py"})
        assert "def" in result


class TestToolAgent:
    def test_plan_agent_permissions_deny_writes(self):
        from codepilot.agent.registry import AgentRegistry
        agent = AgentRegistry().get("plan")
        assert agent is not None
        assert agent.permissions.evaluate("edit_file") == "deny"
        assert agent.permissions.evaluate("write_file") == "deny"
        assert agent.permissions.evaluate("run_shell") == "deny"
        assert agent.permissions.evaluate("read_file") == "allow"
        assert agent.permissions.evaluate("grep") == "allow"
        assert agent.is_readonly is True

    def test_build_agent_permissions(self):
        from codepilot.agent.registry import AgentRegistry
        agent = AgentRegistry().get("build")
        assert agent is not None
        assert agent.confirm is True
        assert agent.permissions.evaluate("read_file") == "allow"
        assert agent.permissions.evaluate("edit_file") == "ask"

    def test_explore_agent_readonly_tools(self):
        tools = get_tools_for_agent("explore")
        tool_names = {t.name for t in tools}
        assert "read_file" in tool_names
        assert "grep" in tool_names
        assert "edit_file" not in tool_names


class TestWebSearch:
    def test_web_search_returns_results(self, monkeypatch):
        from codepilot.tools.web_tool import web_search

        mock_results = [
            {"title": "Test Project", "href": "https://github.com/test/project", "body": "A test project"},
            {"title": "Another Result", "href": "https://example.com", "body": "Another description"},
        ]

        class MockDDGS:
            def __init__(self, timeout=15):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def text(self, query, max_results=8):
                return mock_results

        import codepilot.tools.web_tool as web_module
        monkeypatch.setattr(web_module, "DDGS", MockDDGS)

        result = web_search.invoke({"query": "test query"})
        assert "Test Project" in result
        assert "https://github.com/test/project" in result
        assert "A test project" in result

    def test_web_search_no_results(self, monkeypatch):
        from codepilot.tools.web_tool import web_search

        class MockDDGS:
            def __init__(self, timeout=15):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def text(self, query, max_results=8):
                return []

        import codepilot.tools.web_tool as web_module
        monkeypatch.setattr(web_module, "DDGS", MockDDGS)

        result = web_search.invoke({"query": "nonexistent xyz123"})
        assert "No results found" in result


class TestWebFetch:
    def test_web_fetch_invalid_url(self):
        result = web_fetch.invoke({"url": "not-a-url"})
        assert "Error" in result

    def test_web_fetch_timeout_range(self):
        result = web_fetch.invoke({"url": "https://example.com", "timeout": 999})
        assert (
            "Error" not in result
            or "timed out" in result.lower()
            or "Connection" in result
            or "Blocked" in result
        )

    def test_web_fetch_blocks_loopback(self):
        result = web_fetch.invoke({"url": "http://127.0.0.1/"})
        assert "Error" in result and "Blocked" in result

    def test_web_fetch_blocks_metadata_endpoint(self):
        result = web_fetch.invoke({"url": "http://169.254.169.254/latest/meta-data/"})
        assert "Error" in result and "Blocked" in result

    def test_web_fetch_blocks_gcp_metadata(self):
        result = web_fetch.invoke({"url": "http://metadata.google.internal/"})
        assert "Error" in result and "Blocked" in result

    def test_web_fetch_blocks_dns_to_private(self, monkeypatch):
        import codepilot.tools.web_fetch_tool as wf
        def fake_getaddrinfo(host, port):
            return [(2, 1, 6, "", ("10.0.0.5", 0))]
        monkeypatch.setattr(wf.socket if hasattr(wf, "socket") else __import__("socket"),
                            "getaddrinfo", fake_getaddrinfo)
        import socket as _socket
        monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)
        result = web_fetch.invoke({"url": "https://attacker.example.test/"})
        assert "Error" in result and ("Blocked" in result or "private" in result.lower())


class TestTodoWrite:
    def test_todo_write_basic(self):
        todos = json.dumps([
            {"content": "Read files", "status": "completed", "priority": "high"},
            {"content": "Edit code", "status": "in_progress", "priority": "medium"},
            {"content": "Run tests", "status": "pending", "priority": "low"},
        ])
        result = todo_write.invoke({"todos": todos})
        assert "Read files" in result
        assert "Edit code" in result
        assert "Run tests" in result

    def test_todo_write_multiple_in_progress_blocked(self):
        todos = json.dumps([
            {"content": "Task A", "status": "in_progress", "priority": "high"},
            {"content": "Task B", "status": "in_progress", "priority": "high"},
        ])
        result = todo_write.invoke({"todos": todos})
        assert "Error" in result or "in_progress" in result

    def test_todo_write_invalid_json(self):
        result = todo_write.invoke({"todos": "not json"})
        assert "Error" in result
