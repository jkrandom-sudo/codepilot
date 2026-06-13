"""Compare CodePilot trace metrics between two groups.

Usage:
    python -m evals.compare_runs --period1 7 --period2 30
    python -m evals.compare_runs --model1 "anthropic/claude-sonnet-4-20250514" --model2 "deepseek/deepseek-v4-flash"
    python -m evals.compare_runs --mode1 plan --mode2 auto
"""
from __future__ import annotations

import argparse


from evals.analyze_traces import compute_metrics, fetch_root_runs
from evals.utils import get_client_and_project_id


def main():
    parser = argparse.ArgumentParser(description="Compare CodePilot trace metrics")
    parser.add_argument("--project", type=str, default="codepilot")
    parser.add_argument("--period1", type=int, default=7, help="Days for group 1")
    parser.add_argument("--period2", type=int, default=30, help="Days for group 2")
    parser.add_argument("--model1", type=str, default=None)
    parser.add_argument("--model2", type=str, default=None)
    parser.add_argument("--mode1", type=str, default=None)
    parser.add_argument("--mode2", type=str, default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--include-child-runs",
        action="store_true",
        help="Fetch child runs for legacy traces without task_metrics. Slower.",
    )
    args = parser.parse_args()

    client, project_id = get_client_and_project_id(args.project)

    if args.model1 and args.model2:
        runs_a = fetch_root_runs(client, project_id, 90, model=args.model1, limit=args.limit)
        runs_b = fetch_root_runs(client, project_id, 90, model=args.model2, limit=args.limit)
        label_a, label_b = args.model1, args.model2
    elif args.mode1 and args.mode2:
        all_runs = fetch_root_runs(client, project_id, 90, limit=args.limit)
        runs_a = [
            r for r in all_runs
            if f"mode:{args.mode1}" in (r.tags or []) or f"confirm:{args.mode1}" in (r.tags or [])
        ]
        runs_b = [
            r for r in all_runs
            if f"mode:{args.mode2}" in (r.tags or []) or f"confirm:{args.mode2}" in (r.tags or [])
        ]
        label_a, label_b = f"mode:{args.mode1}", f"mode:{args.mode2}"
    else:
        runs_a = fetch_root_runs(client, project_id, args.period1, limit=args.limit)
        runs_b = fetch_root_runs(client, project_id, args.period2, limit=args.limit)
        label_a, label_b = f"last {args.period1}d", f"last {args.period2}d"

    metrics_a = compute_metrics(
        runs_a,
        client,
        project_id,
        include_child_runs=args.include_child_runs,
    )
    metrics_b = compute_metrics(
        runs_b,
        client,
        project_id,
        include_child_runs=args.include_child_runs,
    )

    print(f"\n{'=' * 60}")
    print(f"Comparison: {label_a} vs {label_b}")
    print(f"{'=' * 60}")

    for label, m in [(label_a, metrics_a), (label_b, metrics_b)]:
        print(f"\n--- {label} ---")
        if m["total_runs"] == 0:
            print("  No runs found.")
            continue
        o = m["overall"]
        print(f"  Runs:           {m['total_runs']}")
        print(f"  Avg tokens:     {o['avg_tokens']:,.0f}")
        print(f"  Avg latency:    {o['avg_latency_s']:.1f}s")
        print(f"  Error rate:     {o['error_rate']:.1%}")
        print(f"  Avg iterations: {m['avg_iterations']:.1f}")

    if metrics_a["total_runs"] > 0 and metrics_b["total_runs"] > 0:
        print(f"\n--- Deltas ({label_a} -> {label_b}) ---")

        def pct_change(a, b):
            if a == 0:
                return "N/A"
            return f"{((b - a) / a) * 100:+.1f}%"

        print(f"  Avg tokens:  {pct_change(metrics_a['overall']['avg_tokens'], metrics_b['overall']['avg_tokens'])}")
        print(f"  Avg latency: {pct_change(metrics_a['overall']['avg_latency_s'], metrics_b['overall']['avg_latency_s'])}")
        print(f"  Error rate:  {pct_change(metrics_a['overall']['error_rate'], metrics_b['overall']['error_rate'])}")
        print(f"  Avg iters:   {pct_change(metrics_a['avg_iterations'], metrics_b['avg_iterations'])}")

    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
