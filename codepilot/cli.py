import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import click
from langchain_core.messages import AIMessage, ToolMessage

from codepilot import __version__
from codepilot.utils.token_usage import TokenUsageAccumulator


NON_INTERACTIVE_HEARTBEAT_INTERVAL = 15.0


@click.command()
@click.version_option(version=__version__, prog_name="codepilot")
@click.option("--model", "-m", default=None, help="Model to use (e.g. gpt-4o, claude-sonnet-4-20250514)")
@click.option(
    "--agent",
    "-a",
    default=None,
    help="Agent to use (build, plan, plan-execute). Use --no-confirm for auto writes.",
)
@click.option(
    "--confirm/--no-confirm",
    default=True,
    help="Require confirmation for write operations (default: yes). Use --no-confirm for auto mode.",
)
@click.option("--prompt", "-p", default=None, help="Non-interactive mode: execute prompt and exit")
@click.option("--resume", "-r", default=None, help="Resume a session by ID")
@click.option("--resume-last", is_flag=True, default=False, help="Resume the most recent session")
def main(model: str | None, agent: str | None, confirm: bool, prompt: str | None, resume: str | None, resume_last: bool) -> None:
    """CodePilot - AI coding agent for the terminal."""
    os.environ.setdefault("CODEPILOT_WORKING_DIR", os.getcwd())

    from codepilot.config.settings import load_config
    from codepilot.config.providers import ProviderRegistry

    config = load_config()
    registry = ProviderRegistry(config)

    _setup_langsmith(config)

    resolved_model = model or f"{config.default.provider}/{config.default.model}"

    if agent:
        resolved_agent = agent
    elif config.agent and config.agent not in {"build", "auto"}:
        resolved_agent = config.agent
    else:
        resolved_agent = "auto"

    if prompt:
        _run_non_interactive(registry, resolved_model, resolved_agent, confirm, prompt)
    else:
        session_id = None
        if resume:
            session_id = resume
        elif resume_last:
            session_id = _get_latest_session_id()
        _run_interactive(registry, resolved_model, resolved_agent, confirm, session_id)


def _get_latest_session_id() -> str | None:
    try:
        from codepilot.storage.db import Storage
        storage = Storage()
        session = storage.get_latest_session()
        storage.close()
        return session.id if session else None
    except Exception:
        return None


def _resolve_effective_agent(agent_name: str, confirm: bool) -> tuple[str, bool]:
    from codepilot.agent.registry import AgentRegistry
    from codepilot.agent.router import AUTO_AGENT
    if agent_name == AUTO_AGENT:
        return AUTO_AGENT, confirm

    registry = AgentRegistry()
    agent_def = registry.get(agent_name)

    if agent_def is None:
        return "build", confirm

    if agent_def.is_readonly:
        return agent_name, False

    return agent_name, confirm


def _run_interactive(registry, model: str, agent_name: str = "build", confirm: bool = True, session_id: str | None = None) -> None:
    from codepilot.agent.graph import build_agent_graph
    from codepilot.agent.registry import AgentRegistry
    from codepilot.config.context_windows import get_usable_context, parse_model_spec
    from codepilot.storage.db import Storage
    from codepilot.ui.repl import REPL

    effective_agent, effective_confirm = _resolve_effective_agent(agent_name, confirm)

    raw_model_name = model.split("/", 1)[-1] if "/" in model else model
    provider_name = model.split("/", 1)[0] if "/" in model else ""
    clean_model_name, suffix_context = parse_model_spec(raw_model_name)
    provider_cfg = registry.config.providers.get(provider_name)
    config_context = provider_cfg.context_window if provider_cfg else None
    context_override = suffix_context or config_context
    context_window = get_usable_context(clean_model_name, context_override)

    llm = registry.get_llm(model)

    agent_def = AgentRegistry().get_or_default(effective_agent)
    graph_permissions = agent_def.permissions
    if not effective_confirm and not agent_def.is_readonly:
        from codepilot.config.permissions import PermissionRuleset
        graph_permissions = PermissionRuleset.auto_ruleset()

    graph = build_agent_graph(
        llm,
        agent_name=effective_agent,
        context_window=context_window,
        custom_permissions=graph_permissions,
    )

    storage = Storage()

    repl = REPL(
        graph, llm=llm, model=model, registry=registry,
        context_window=context_window, agent_name=effective_agent,
        storage=storage, session_id=session_id,
    )
    repl.run()


def _run_non_interactive(registry, model: str, agent_name: str, confirm: bool, prompt: str) -> None:
    from codepilot.agent.graph import build_agent_graph, graph_recursion_limit
    from codepilot.agent.registry import AgentRegistry
    from codepilot.agent.router import select_agent_for_task
    from codepilot.config.permissions import PermissionRuleset
    from codepilot.storage.db import new_session_id
    from codepilot.ui.intent import chat_response, classify_intent, classify_task, greeting_response
    from langchain_core.messages import HumanMessage

    intent = classify_intent(prompt)
    if intent == "greeting":
        click.echo(greeting_response(prompt))
        return
    if intent == "chat":
        click.echo(chat_response(prompt))
        return

    effective_agent, _ = _resolve_effective_agent(agent_name, confirm)
    session_id = new_session_id()
    task_type = classify_task(prompt)
    selected_agent = select_agent_for_task(prompt, task_type, effective_agent)
    agent_def = AgentRegistry().get_or_default(selected_agent)
    custom_permissions = (
        agent_def.permissions if agent_def.is_readonly else PermissionRuleset.auto_ruleset()
    )

    try:
        llm = registry.get_llm(model)
        graph = build_agent_graph(
            llm,
            agent_name=selected_agent,
            custom_permissions=custom_permissions,
        )
    except Exception as e:
        raise click.ClickException(_format_non_interactive_error(e)) from None

    click.echo(f"🚀 开始执行任务：{prompt[:120]}", err=True)
    route_suffix = f" (auto→{selected_agent})" if effective_agent == "auto" else ""
    click.echo(f"模型：{model} | Agent：{selected_agent}{route_suffix} | 模式：auto", err=True)
    click.echo("⏳ Agent 正在分析和执行，请稍候...", err=True)
    task_start = time.time()
    graph_input = {
        "messages": [HumanMessage(content=prompt)],
        "working_dir": os.getcwd(),
        "files_context": [],
        "task_type": task_type,
        "agent_name": selected_agent,
        "session_id": session_id,
    }
    graph_config = {
        "recursion_limit": graph_recursion_limit(),
        "run_name": task_type,
        "metadata": {
            "model": model,
            "session_id": session_id,
            "agent_name": selected_agent,
            "requested_agent": effective_agent,
            "confirm": "auto",
            "task_type": task_type,
            "non_interactive": True,
            "user_input_preview": prompt[:200],
        },
        "tags": [
            f"agent:{selected_agent}",
            f"requested_agent:{effective_agent}",
            "confirm:auto",
            f"model:{model}",
            f"task_type:{task_type}",
            "non_interactive",
        ],
    }
    error_messages: list = []
    try:
        result = _invoke_graph_with_heartbeat(graph, graph_input, graph_config)
        _report_non_interactive_to_langsmith(
            session_id=session_id,
            task_start=task_start,
            messages=result.get("messages", []),
            model=model,
            agent_name=selected_agent,
            task_type=task_type,
        )
        click.echo("✅ 任务完成", err=True)
        for content in _non_interactive_output(result.get("messages", [])):
            click.echo(content)
    except Exception as e:
        _report_non_interactive_to_langsmith(
            session_id=session_id,
            task_start=task_start,
            messages=error_messages,
            model=model,
            agent_name=selected_agent,
            task_type=task_type,
            is_error=True,
        )
        raise click.ClickException(_format_non_interactive_error(e)) from None


def _invoke_graph_with_heartbeat(
    graph,
    graph_input: dict,
    graph_config: dict,
    heartbeat_interval: float = NON_INTERACTIVE_HEARTBEAT_INTERVAL,
) -> dict:
    """Invoke a graph while emitting periodic non-interactive progress hints."""
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(graph.invoke, graph_input, config=graph_config)
        while True:
            try:
                return future.result(timeout=heartbeat_interval)
            except TimeoutError:
                elapsed = int(time.monotonic() - start)
                click.echo(f"⏳ 仍在运行... {elapsed}s（模型/工具执行中）", err=True)


def _format_non_interactive_error(error: Exception) -> str:
    from codepilot.config.providers import _is_quota_exceeded_error, _is_rate_limit_error

    detail = str(error).strip()
    if _is_quota_exceeded_error(error):
        return (
            "模型配额已用尽，任务未执行完成。请切换模型、补充配额或稍后再试。"
            f" 原始错误：{_short_error(detail)}"
        )
    if _is_rate_limit_error(error):
        return f"模型请求被限流，重试后仍未成功。请稍后再试或切换模型。原始错误：{_short_error(detail)}"
    return _short_error(detail) or error.__class__.__name__


def _short_error(detail: str, limit: int = 300) -> str:
    text = " ".join(detail.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _non_interactive_task_metrics(messages: list, elapsed: float, task_type: str = "") -> dict:
    tool_names: list[str] = []
    token_accumulator = TokenUsageAccumulator()
    iteration_count = 0
    did_test = False
    tests_passed: bool | None = None

    for msg in messages:
        if isinstance(msg, AIMessage):
            token_accumulator.add_message(msg)
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                iteration_count += 1
                for tc in tool_calls:
                    tool_name = tc.get("name", "unknown")
                    tool_names.append(tool_name)
                    args = tc.get("args", {}) or {}
                    command = str(args.get("command", "")).lower()
                    if tool_name == "run_shell" and any(
                        hint in command for hint in ("pytest", "test", "ruff", "mypy", "tox")
                    ):
                        did_test = True
        elif isinstance(msg, ToolMessage):
            content = str(msg.content or "").lower()
            if did_test and tests_passed is None:
                if " failed" in content or "failed," in content or "exit code:" in content:
                    tests_passed = False
                elif " passed" in content or "all checks passed" in content:
                    tests_passed = True

    tool_count = len(tool_names)
    outcome = "success"
    if iteration_count == 0 and tool_count == 0:
        outcome = "no_op"
    if tests_passed is False:
        outcome = "partial"
    if task_type:
        from codepilot.agent.nodes import TASK_ITERATION_LIMITS
        task_limit = TASK_ITERATION_LIMITS.get(task_type)
        if task_limit is not None and iteration_count > task_limit:
            outcome = "timeout"

    return {
        "iteration_count": iteration_count,
        "tool_call_count": tool_count,
        "tool_distribution": dict(Counter(tool_names)),
        "input_tokens": token_accumulator.total.input_tokens,
        "output_tokens": token_accumulator.total.output_tokens,
        "total_tokens": token_accumulator.total.total_tokens,
        "elapsed_seconds": round(elapsed, 2),
        "outcome": outcome,
        "did_edit": any(name in {"edit_file", "write_file"} for name in tool_names),
        "did_test": did_test,
        "tests_passed": tests_passed,
        "non_interactive": True,
    }

def _report_non_interactive_to_langsmith(
    *,
    session_id: str,
    task_start: float,
    messages: list,
    model: str,
    agent_name: str,
    task_type: str,
    is_error: bool = False,
) -> None:
    if os.environ.get("LANGSMITH_TRACING") != "true":
        return
    try:
        from datetime import datetime, timedelta, timezone

        from langsmith import Client

        elapsed = time.time() - task_start
        metrics = _non_interactive_task_metrics(messages, elapsed, task_type)
        if is_error:
            metrics["outcome"] = "error"
        client = Client()
        task_start_utc = datetime.fromtimestamp(task_start, tz=timezone.utc)
        root_run = None
        for attempt in range(4):
            runs = list(client.list_runs(
                project_name=os.environ.get("LANGSMITH_PROJECT", "codepilot"),
                is_root=True,
                start_time=task_start_utc - timedelta(seconds=2),
                limit=10,
            ))
            root_run = next(
                (r for r in runs if (r.metadata or {}).get("session_id") == session_id),
                None,
            )
            if root_run is not None:
                break
            time.sleep(0.5 * (attempt + 1))
        if root_run is None:
            return
        metric_comment = (
            f"outcome={metrics['outcome']}, iterations={metrics['iteration_count']}, "
            f"tools={metrics['tool_call_count']}, tokens={metrics['total_tokens']}, "
            f"input_tokens={metrics['input_tokens']}, output_tokens={metrics['output_tokens']}, "
            f"elapsed={metrics['elapsed_seconds']:.1f}s, model={model}, "
            f"agent={agent_name}, task_type={task_type}"
        )
        client.update_run(
            run_id=root_run.id,
            extra={"task_metrics": metrics},
        )
        feedback_items = [
            ("task_outcome", 1.0 if metrics["outcome"] == "success" else 0.5, metric_comment),
            ("tool_call_count", float(metrics["tool_call_count"]), metric_comment),
            ("iteration_count", float(metrics["iteration_count"]), metric_comment),
        ]
        for key, score, comment in feedback_items:
            try:
                client.create_feedback(
                    run_id=root_run.id,
                    key=key,
                    score=score,
                    comment=comment,
                )
            except Exception:
                pass
    except Exception:
        pass


def _non_interactive_output(messages: list) -> list[str]:
    final_responses = [
        msg.content
        for msg in messages
        if isinstance(msg, AIMessage)
        and msg.content
        and not getattr(msg, "tool_calls", None)
    ]
    if final_responses:
        return [final_responses[-1]]

    fallback = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content:
            fallback.append(msg.content)
    return fallback[-1:] if fallback else []


def _setup_langsmith(config) -> None:
    ls = config.langsmith
    if ls.enabled and ls.api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = ls.api_key
        os.environ["LANGSMITH_PROJECT"] = ls.project
        os.environ["LANGSMITH_ENDPOINT"] = ls.endpoint
    else:
        os.environ["LANGSMITH_TRACING"] = "false"


if __name__ == "__main__":
    main()
