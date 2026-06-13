"""Analyze CodePilot traces from LangSmith.

Usage:
    python -m evals.analyze_traces --days 7
    python -m evals.analyze_traces --days 30 --task-type file_edit
    python -m evals.analyze_traces --model deepseek/deepseek-v4-flash
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from langsmith import Client

from evals.utils import get_client_and_project_id


def fetch_root_runs(
    client: Client,
    project_id: str,
    days: int,
    task_type: str | None = None,
    model: str | None = None,
    limit: int = 100,
) -> list:
    """Fetch root runs with optional filtering."""
    start_time = datetime.now() - timedelta(days=days)

    runs = list(client.list_runs(
        project_id=project_id,
        is_root=True,
        start_time=start_time,
        limit=limit,
    ))

    # Post-filter by task_type and model from metadata
    if task_type:
        runs = [r for r in runs if (r.metadata or {}).get("task_type") == task_type]
    if model:
        runs = [r for r in runs if (r.metadata or {}).get("model") == model]

    return runs


def _task_metrics(run) -> dict:
    extra = getattr(run, "extra", None) or {}
    return extra.get("task_metrics") or {}


def _child_tool_metrics(client: Client, project_id: str, run, limit: int) -> tuple[Counter, int]:
    limit = min(limit, 100)
    child_runs = list(client.list_runs(
        project_id=project_id,
        trace_id=run.trace_id or run.id,
        limit=limit,
    ))
    tools = [cr.name for cr in child_runs if cr.run_type == "tool"]
    return Counter(tools), len(tools)


def compute_metrics(
    runs: list,
    client: Client = None,
    project_id: str = None,
    *,
    include_child_runs: bool = False,
    child_run_limit: int = 100,
) -> dict:
    """Compute aggregate metrics from a list of root runs."""
    if not runs:
        return {"total_runs": 0}

    by_task: dict[str, list] = defaultdict(list)
    for run in runs:
        task_type = (run.metadata or {}).get("task_type", "unknown")
        by_task[task_type].append(run)

    by_model: dict[str, list] = defaultdict(list)
    for run in runs:
        model = (run.metadata or {}).get("model", "unknown")
        by_model[model].append(run)

    def group_stats(group_runs: list) -> dict:
        tokens = [r.total_tokens or 0 for r in group_runs]
        latencies = [r.latency or 0 for r in group_runs if r.latency]
        errors = sum(1 for r in group_runs if r.error)
        return {
            "count": len(group_runs),
            "avg_tokens": sum(tokens) / len(tokens) if tokens else 0,
            "median_tokens": sorted(tokens)[len(tokens) // 2] if tokens else 0,
            "avg_latency_s": sum(latencies) / len(latencies) if latencies else 0,
            "error_rate": errors / len(group_runs) if group_runs else 0,
        }

    tool_counter = Counter()
    iteration_counts = []
    for run in runs:
        tm = _task_metrics(run)
        if tm:
            for tool, count in tm.get("tool_distribution", {}).items():
                tool_counter[tool] += count
            iteration_counts.append(tm.get("iteration_count", 0))
        elif include_child_runs and client and project_id:
            # Fallback: extract tool info from child runs when task_metrics is absent
            try:
                child_counter, tool_count = _child_tool_metrics(client, project_id, run, child_run_limit)
                tool_counter.update(child_counter)
                iteration_counts.append(tool_count)
            except Exception:
                iteration_counts.append(0)

    return {
        "total_runs": len(runs),
        "overall": group_stats(runs),
        "by_task_type": {k: group_stats(v) for k, v in by_task.items()},
        "by_model": {k: group_stats(v) for k, v in by_model.items()},
        "tool_distribution": dict(tool_counter.most_common(20)),
        "avg_iterations": sum(iteration_counts) / len(iteration_counts) if iteration_counts else 0,
        "max_iterations": max(iteration_counts) if iteration_counts else 0,
    }


def print_report(metrics: dict) -> None:
    """Print a formatted analysis report."""
    if metrics["total_runs"] == 0:
        print("No runs found.")
        return

    print(f"\n{'=' * 60}")
    print("CodePilot Trace Analysis Report")
    print(f"{'=' * 60}")
    print(f"Total runs: {metrics['total_runs']}")

    overall = metrics["overall"]
    print("\nOverall:")
    print(f"  Avg tokens:     {overall['avg_tokens']:,.0f}")
    print(f"  Median tokens:  {overall['median_tokens']:,.0f}")
    print(f"  Avg latency:    {overall['avg_latency_s']:.1f}s")
    print(f"  Error rate:     {overall['error_rate']:.1%}")
    print(f"  Avg iterations: {metrics['avg_iterations']:.1f}")
    print(f"  Max iterations: {metrics['max_iterations']}")

    print("\nBy Task Type:")
    for task_type, stats in metrics["by_task_type"].items():
        print(f"  {task_type:20s}: n={stats['count']:3d}  "
              f"avg_tokens={stats['avg_tokens']:,.0f}  "
              f"avg_latency={stats['avg_latency_s']:.1f}s  "
              f"error_rate={stats['error_rate']:.1%}")

    print("\nBy Model:")
    for model, stats in metrics["by_model"].items():
        print(f"  {model:30s}: n={stats['count']:3d}  "
              f"avg_tokens={stats['avg_tokens']:,.0f}  "
              f"avg_latency={stats['avg_latency_s']:.1f}s  "
              f"error_rate={stats['error_rate']:.1%}")

    if metrics["tool_distribution"]:
        print("\nTool Distribution:")
        for tool, count in metrics["tool_distribution"].items():
            print(f"  {tool:15s}: {count}")

    print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze CodePilot traces from LangSmith")
    parser.add_argument("--days", type=int, default=7, help="Look back period in days")
    parser.add_argument("--project", type=str, default="codepilot", help="LangSmith project name")
    parser.add_argument("--task-type", type=str, default=None, help="Filter by task type")
    parser.add_argument("--model", type=str, default=None, help="Filter by model")
    parser.add_argument("--limit", type=int, default=100, help="Maximum root runs to fetch")
    parser.add_argument(
        "--include-child-runs",
        action="store_true",
        help="Fetch child runs for legacy traces without task_metrics. Slower.",
    )
    parser.add_argument("--child-run-limit", type=int, default=100, help="Maximum child runs per trace")
    args = parser.parse_args()

    client, project_id = get_client_and_project_id(args.project)
    runs = fetch_root_runs(client, project_id, args.days, args.task_type, args.model, limit=args.limit)
    metrics = compute_metrics(
        runs,
        client,
        project_id,
        include_child_runs=args.include_child_runs,
        child_run_limit=args.child_run_limit,
    )
    print_report(metrics)


if __name__ == "__main__":
    main()
