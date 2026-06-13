"""Convert a problematic LangSmith trace into an evaluation dataset example.

Usage:
    python -m evals.trace_to_eval --run-id <run_uuid> --dataset codepilot-file-edit
    python -m evals.trace_to_eval --run-id <run_uuid> --new-dataset "codepilot-regression-20260606"
"""
from __future__ import annotations

import argparse

from langsmith import Client


def trace_to_eval(client: Client, run_id: str, dataset_name: str) -> None:
    """Convert a trace into an evaluation example."""
    run = client.read_run(run_id)

    inputs_data = run.inputs or {}
    messages = inputs_data.get("messages", [])

    user_input = ""
    for msg in messages:
        if msg.get("type") == "human" or msg.get("role") == "user":
            user_input = msg.get("content", "")
            break

    if not user_input:
        print("No human input found in the trace.")
        return

    metadata = run.metadata or {}
    mode = metadata.get("user_mode", "confirm")

    example = {
        "inputs": {
            "messages": [{"role": "user", "content": user_input}],
            "mode": mode,
        },
        "outputs": {
            "expected_tools": [],
            "forbidden_tools": [],
            "max_iterations": 10,
            "expected_outcome": "",
        },
    }

    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
    except Exception:
        dataset = client.create_dataset(
            dataset_name,
            description=f"Created from problematic trace {run_id}",
        )

    client.create_example(
        inputs=example["inputs"],
        outputs=example["outputs"],
        dataset_id=dataset.id,
    )

    print(f"Added example to dataset '{dataset_name}':")
    print(f"  Input: {user_input[:100]}...")
    print("  Note: Fill in expected_tools and expected_outcome in the LangSmith UI.")


def main():
    parser = argparse.ArgumentParser(description="Convert a trace to an eval example")
    parser.add_argument("--run-id", type=str, required=True, help="LangSmith run ID")
    parser.add_argument("--dataset", type=str, default=None, help="Existing dataset name")
    parser.add_argument("--new-dataset", type=str, default=None, help="Create new dataset with this name")
    args = parser.parse_args()

    dataset_name = args.dataset or args.new_dataset
    if not dataset_name:
        print("Must specify --dataset or --new-dataset")
        return

    client = Client()
    trace_to_eval(client, args.run_id, dataset_name)


if __name__ == "__main__":
    main()
