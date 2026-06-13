"""Run automated evaluations for CodePilot agent.

Usage:
    python -m evals.run_eval --dataset codepilot-file-edit
    python -m evals.run_eval --dataset codepilot-code-search --model deepseek/deepseek-v4-flash
    python -m evals.run_eval --dataset codepilot-all
"""
from __future__ import annotations

import argparse
import os

from langchain_core.messages import HumanMessage
from langsmith import Client

from codepilot.agent.graph import build_agent_graph, graph_recursion_limit
from codepilot.config.providers import ProviderRegistry
from codepilot.config.settings import load_config

from evals.evaluators import (
    agent_permission_correctness,
    iteration_efficiency,
    no_read_redundancy,
    task_completion,
    tool_selection_accuracy,
)


def target(inputs: dict) -> dict:
    config = load_config()
    registry = ProviderRegistry(config)

    model = os.environ.get("CODEPILOT_EVAL_MODEL", f"{config.default.provider}/{config.default.model}")
    agent_name = inputs.get("agent", "build")

    llm = registry.get_llm(model)
    graph = build_agent_graph(llm, agent_name=agent_name)

    user_content = inputs["messages"][0]["content"]
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=user_content)],
            "working_dir": os.getcwd(),
            "files_context": [],
            "task_type": inputs.get("task_type", ""),
            "agent_name": agent_name,
            "session_id": "eval-session",
        },
        config={"recursion_limit": graph_recursion_limit()},
    )

    return {"messages": result.get("messages", [])}


def main():
    parser = argparse.ArgumentParser(description="Run CodePilot evaluations")
    parser.add_argument("--dataset", type=str, required=True, help="Dataset name")
    parser.add_argument("--model", type=str, default=None, help="Model to evaluate")
    parser.add_argument("--project", type=str, default="codepilot", help="LangSmith project name")
    parser.add_argument("--max-concurrency", type=int, default=1, help="Max concurrency")
    args = parser.parse_args()

    if args.model:
        os.environ["CODEPILOT_EVAL_MODEL"] = args.model

    client = Client()

    evaluators = [
        tool_selection_accuracy,
        iteration_efficiency,
        task_completion,
        no_read_redundancy,
        agent_permission_correctness,
    ]

    experiment_prefix = f"codepilot-{args.dataset}"
    if args.model:
        experiment_prefix += f"-{args.model.replace('/', '-')}"

    results = client.evaluate(
        target,
        data=args.dataset,
        evaluators=evaluators,
        experiment_prefix=experiment_prefix,
        max_concurrency=args.max_concurrency,
    )

    print(f"\nExperiment: {results.experiment_name}")
    print(f"Results: {results}")


if __name__ == "__main__":
    main()
