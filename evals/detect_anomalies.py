"""Detect anomalous CodePilot traces (high iterations, excessive tokens, errors).

Usage:
    python -m evals.detect_anomalies --days 7
    python -m evals.detect_anomalies --days 30 --top 20
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from langsmith import Client

from evals.analyze_traces import _child_tool_metrics, _task_metrics
from evals.utils import get_client_and_project_id


def detect_anomalies(
    client: Client,
    project_id: str,
    days: int,
    top: int = 10,
    *,
    limit: int = 100,
    include_child_runs: bool = False,
    child_run_limit: int = 100,
) -> None:
    start_time = datetime.now() - timedelta(days=days)

    runs = list(client.list_runs(
        project_id=project_id,
        is_root=True,
        start_time=start_time,
        limit=limit,
    ))

    if not runs:
        print("No runs found.")
        return

    # Anomaly 1: High token usage
    by_tokens = sorted(runs, key=lambda r: r.total_tokens or 0, reverse=True)[:top]
    print(f"\n{'=' * 60}")
    print(f"Top {top} Highest Token Usage")
    print(f"{'=' * 60}")
    for r in by_tokens:
        meta = r.metadata or {}
        print(f"  {r.name:20s} | tokens={r.total_tokens or 0:>8,} | "
              f"model={meta.get('model', '?'):30s} | "
              f"task_type={meta.get('task_type', '?'):15s} | "
              f"id={r.id}")

    # Anomaly 2: High latency
    by_latency = sorted(runs, key=lambda r: r.latency or 0, reverse=True)[:top]
    print(f"\nTop {top} Highest Latency")
    print(f"{'=' * 60}")
    for r in by_latency:
        meta = r.metadata or {}
        print(f"  {r.name:20s} | latency={r.latency or 0:>8.1f}s | "
              f"model={meta.get('model', '?'):30s} | "
              f"task_type={meta.get('task_type', '?'):15s} | "
              f"id={r.id}")

    # Anomaly 3: Errors
    error_runs = [r for r in runs if r.error]
    print(f"\nError Runs ({len(error_runs)} of {len(runs)} = {len(error_runs) / len(runs):.1%})")
    print(f"{'=' * 60}")
    for r in error_runs[:top]:
        meta = r.metadata or {}
        err_preview = (r.error or "")[:100]
        print(f"  {r.name:20s} | model={meta.get('model', '?'):30s} | error={err_preview}")

    # Anomaly 4: High iteration count (from task_metrics)
    high_iter = []
    for r in runs:
        tm = _task_metrics(r)
        if not tm and include_child_runs:
            child_counter, tool_count = _child_tool_metrics(client, project_id, r, child_run_limit)
            tm = {
                "iteration_count": tool_count,
                "tool_call_count": tool_count,
                "tool_distribution": dict(child_counter),
                "total_tokens": r.total_tokens or 0,
            }
        if tm and tm.get("iteration_count", 0) >= 15:
            high_iter.append((r, tm))

    if high_iter:
        high_iter.sort(key=lambda x: x[1]["iteration_count"], reverse=True)
        print("\nHigh Iteration Runs (>=15 iterations)")
        print(f"{'=' * 60}")
        for r, tm in high_iter[:top]:
            meta = r.metadata or {}
            print(f"  {r.name:20s} | iters={tm['iteration_count']:>3d} | "
                  f"tools={tm.get('tool_call_count', 0):>3d} | "
                  f"tokens={tm.get('total_tokens', 0):>8,} | "
                  f"model={meta.get('model', '?'):30s}")

    # Anomaly 5: Repeated tool calls
    dedup_runs = []
    for r in runs:
        tm = _task_metrics(r)
        if not tm and include_child_runs:
            child_counter, tool_count = _child_tool_metrics(client, project_id, r, child_run_limit)
            tm = {
                "iteration_count": tool_count,
                "tool_call_count": tool_count,
                "tool_distribution": dict(child_counter),
                "total_tokens": r.total_tokens or 0,
            }
        if tm:
            tool_dist = tm.get("tool_distribution", {})
            for tool_name, count in tool_dist.items():
                if count >= 5:
                    dedup_runs.append((r, tool_name, count))

    if dedup_runs:
        print("\nRepeated Tool Calls (same tool >=5 times)")
        print(f"{'=' * 60}")
        for r, tool_name, count in sorted(dedup_runs, key=lambda x: x[2], reverse=True)[:top]:
            meta = r.metadata or {}
            print(f"  {tool_name:15s} x{count:<3d} | {r.name:20s} | "
                  f"model={meta.get('model', '?'):30s}")

    print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="Detect anomalous CodePilot traces")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--project", type=str, default="codepilot")
    parser.add_argument("--top", type=int, default=10, help="Number of top anomalies to show")
    parser.add_argument("--limit", type=int, default=100, help="Maximum root runs to fetch")
    parser.add_argument(
        "--include-child-runs",
        action="store_true",
        help="Fetch child runs for legacy traces without task_metrics. Slower.",
    )
    parser.add_argument("--child-run-limit", type=int, default=100, help="Maximum child runs per trace")
    args = parser.parse_args()

    client, project_id = get_client_and_project_id(args.project)
    detect_anomalies(
        client,
        project_id,
        args.days,
        args.top,
        limit=args.limit,
        include_child_runs=args.include_child_runs,
        child_run_limit=args.child_run_limit,
    )


if __name__ == "__main__":
    main()
