from codepilot.utils.truncate import truncate_output


class TestTruncate:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert truncate_output(text) == text

    def test_empty_text(self):
        assert truncate_output("") == ""

    def test_truncate_by_lines(self):
        text = "\n".join(f"line {i}" for i in range(500))
        result = truncate_output(text, max_lines=100)
        assert "400 more lines truncated" in result
        assert result.count("\n") <= 101

    def test_truncate_by_chars(self):
        text = "a" * 50000
        result = truncate_output(text, max_chars=1000)
        assert len(result) <= 1000

    def test_custom_limits(self):
        text = "\n".join(f"line {i}" for i in range(20))
        result = truncate_output(text, max_lines=10)
        assert "10 more lines truncated" in result

    def test_exact_line_limit(self):
        text = "\n".join(f"line {i}" for i in range(10))
        result = truncate_output(text, max_lines=10)
        assert "truncated" not in result
