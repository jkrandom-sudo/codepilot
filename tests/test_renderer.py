from rich.console import Console

from codepilot.ui.renderer import Renderer


def _renderer() -> tuple[Renderer, Console]:
    console = Console(record=True, width=120)
    return Renderer(console=console), console


def test_render_task_start_shows_clear_boundary():
    renderer, console = _renderer()

    renderer.render_task_start(
        "优化当前 agent 输出",
        model="openai/glm-5",
        agent_name="build",
        mode="confirm",
    )

    output = console.export_text()
    assert "开始执行任务" in output
    assert "优化当前 agent 输出" in output
    assert "openai/glm-5" in output
    assert "build" in output


def test_render_tool_call_infers_phase_once():
    renderer, console = _renderer()

    renderer.render_tool_call("grep", {"pattern": "Renderer"}, step=1)
    renderer.render_tool_call("read_file", {"path": "codepilot/ui/renderer.py"}, step=2)

    output = console.export_text()
    assert output.count("检查项目与收集上下文") == 1
    assert "搜索代码" in output
    assert "读取文件" in output


def test_render_waiting_shows_agent_running_hint():
    renderer, console = _renderer()

    renderer.render_waiting()

    output = console.export_text()
    assert "Agent 正在分析和执行" in output
    assert "结果会实时显示" in output


def test_render_choice_shows_inline_keyboard_hints():
    renderer, console = _renderer()

    renderer.render_choice("run_shell", {"command": "pytest tests/test_repl.py -q"})

    output = console.export_text()
    assert "等待确认" in output
    assert "↑/↓ 选择" in output
    assert "Enter 确认" in output
    assert "Esc 取消" in output


def test_activity_helpers_format_running_hint():
    renderer, _ = _renderer()

    assert "正在理解任务" in renderer._activity_text("正在理解任务")
    renderer.update_activity(None, "不会抛错")
    renderer.stop_activity(None)


def test_render_tool_result_summarizes_large_read_output():
    renderer, console = _renderer()

    renderer.render_tool_result("read_file", "\n".join(f"{i}: line" for i in range(20)))

    output = console.export_text()
    assert "完成，返回 20 行内容" in output
    assert "19: line" not in output


def test_render_tool_result_shows_blocked_as_skip():
    renderer, console = _renderer()

    renderer.render_tool_result("read_file", "[BLOCKED] already in context", status="blocked")

    output = console.export_text()
    assert "跳过" in output
    assert "失败" not in output


def test_render_task_summary_marks_partial():
    renderer, console = _renderer()

    renderer.render_task_summary(12.3, 4567, 4, 3, outcome="partial")

    output = console.export_text()
    assert "部分完成" in output
    assert "12.3s" in output
    assert "4,567" in output


def test_render_task_summary_shows_input_and_output_tokens():
    renderer, console = _renderer()

    renderer.render_task_summary(
        3.2,
        total_tokens=42,
        tool_count=1,
        input_tokens=30,
        output_tokens=12,
    )

    output = console.export_text()
    assert "Token 消耗:" in output
    assert "42" in output
    assert "输入 30" in output
    assert "输出 12" in output
