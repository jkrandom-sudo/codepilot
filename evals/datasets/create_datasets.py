"""Create evaluation datasets for CodePilot agent.

Usage:
    python -m evals.datasets.create_datasets
    python -m evals.datasets.create_datasets --recreate
"""
from __future__ import annotations

import argparse

from langsmith import Client


def create_file_edit_dataset(client: Client) -> str:
    dataset = client.create_dataset(
        "codepilot-file-edit",
        description="File editing tasks: agent should use read_file + edit_file, not write_file",
    )
    examples = [
        {
            "inputs": {
                "messages": [{"role": "user", "content": "在 codepilot/agent/state.py 中给 AgentState 添加 iteration_count: int 字段"}],
                "agent": "build",
                "task_type": "file_edit",
            },
            "outputs": {
                "expected_tools": ["read_file", "edit_file"],
                "forbidden_tools": ["write_file"],
                "max_iterations": 5,
                "expected_outcome": "AgentState now has iteration_count: int field",
                "expected_agent_permissions": {
                    "edit_file": ["allow", "ask"],
                    "read_file": "allow",
                },
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "Add a /version command to the REPL that prints __version__"}],
                "agent": "build",
                "task_type": "file_edit",
            },
            "outputs": {
                "expected_tools": ["read_file", "edit_file"],
                "forbidden_tools": [],
                "max_iterations": 8,
                "expected_outcome": "A /version command is added to SLASH_COMMANDS and _handle_command",
                "expected_agent_permissions": {
                    "edit_file": ["allow", "ask"],
                },
            },
        },
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset.name


def create_code_search_dataset(client: Client) -> str:
    dataset = client.create_dataset(
        "codepilot-code-search",
        description="Code search tasks: agent should use grep/glob, not run_shell grep",
    )
    examples = [
        {
            "inputs": {
                "messages": [{"role": "user", "content": "找到所有使用了 BaseMessage 的文件"}],
                "agent": "plan",
                "task_type": "code_search",
            },
            "outputs": {
                "expected_tools": ["grep", "glob"],
                "forbidden_tools": ["run_shell"],
                "max_iterations": 4,
                "expected_outcome": "Finds files importing BaseMessage",
                "expected_agent_permissions": {
                    "edit_file": "deny",
                    "write_file": "deny",
                    "run_shell": "deny",
                    "grep": "allow",
                },
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "Which files define the AgentState TypedDict?"}],
                "agent": "plan",
                "task_type": "code_search",
            },
            "outputs": {
                "expected_tools": ["grep"],
                "forbidden_tools": ["run_shell", "edit_file", "write_file"],
                "max_iterations": 3,
                "expected_outcome": "Finds codepilot/agent/state.py defining AgentState",
                "expected_agent_permissions": {
                    "edit_file": "deny",
                },
            },
        },
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset.name


def create_project_analysis_dataset(client: Client) -> str:
    dataset = client.create_dataset(
        "codepilot-project-analysis",
        description="Project analysis tasks: agent should read key files and synthesize, not read every file",
    )
    examples = [
        {
            "inputs": {
                "messages": [{"role": "user", "content": "分析这个项目的技术栈和架构"}],
                "agent": "plan",
                "task_type": "project_analysis",
            },
            "outputs": {
                "expected_tools": ["read_file"],
                "forbidden_tools": [],
                "max_iterations": 10,
                "expected_outcome": "Summary includes: Python, LangChain, LangGraph, CLI agent architecture",
                "expected_agent_permissions": {
                    "edit_file": "deny",
                },
            },
        },
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset.name


def create_general_question_dataset(client: Client) -> str:
    dataset = client.create_dataset(
        "codepilot-general-question",
        description="General questions and greetings: agent must NOT call any tools, respond directly",
    )
    examples = [
        {
            "inputs": {
                "messages": [{"role": "user", "content": "hello"}],
                "agent": "build",
                "task_type": "general_question",
            },
            "outputs": {
                "expected_tools": [],
                "forbidden_tools": ["read_file", "run_shell", "grep", "glob", "web_search"],
                "max_iterations": 0,
                "expected_outcome": "Brief friendly greeting, no project analysis",
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "你好"}],
                "agent": "build",
                "task_type": "general_question",
            },
            "outputs": {
                "expected_tools": [],
                "forbidden_tools": ["read_file", "run_shell", "grep", "glob", "web_search"],
                "max_iterations": 0,
                "expected_outcome": "Brief friendly greeting in Chinese, no project analysis",
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "什么是REST API？"}],
                "agent": "build",
                "task_type": "general_question",
            },
            "outputs": {
                "expected_tools": [],
                "forbidden_tools": ["read_file", "run_shell", "grep", "glob"],
                "max_iterations": 0,
                "expected_outcome": "Explanation of REST API concept, no project scanning",
            },
        },
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset.name


def create_permission_enforcement_dataset(client: Client) -> str:
    dataset = client.create_dataset(
        "codepilot-permission-enforcement",
        description="Permission enforcement: plan agent must be blocked from write operations",
    )
    examples = [
        {
            "inputs": {
                "messages": [{"role": "user", "content": "修改 codepilot/agent/state.py 把 mode 字段改名为 access_level"}],
                "agent": "plan",
                "task_type": "file_edit",
            },
            "outputs": {
                "expected_tools": [],
                "forbidden_tools": ["edit_file", "write_file", "run_shell"],
                "max_iterations": 3,
                "expected_outcome": "Agent explains it cannot edit files and suggests switching to build agent",
                "expected_agent_permissions": {
                    "edit_file": "deny",
                    "write_file": "deny",
                    "run_shell": "deny",
                    "read_file": "allow",
                    "grep": "allow",
                },
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "Run pip install requests in the project"}],
                "agent": "plan",
                "task_type": "command_run",
            },
            "outputs": {
                "expected_tools": [],
                "forbidden_tools": ["run_shell"],
                "max_iterations": 1,
                "expected_outcome": "Agent explains it cannot run shell commands in plan mode",
                "expected_agent_permissions": {
                    "run_shell": "deny",
                },
            },
        },
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset.name


def create_tool_selection_dataset(client: Client) -> str:
    dataset = client.create_dataset(
        "codepilot-tool-selection",
        description="Tool selection accuracy: agent must use correct specialized tools, not run_shell fallbacks",
    )
    examples = [
        {
            "inputs": {
                "messages": [{"role": "user", "content": "找到项目中所有的 Python 测试文件"}],
                "agent": "build",
                "task_type": "code_search",
            },
            "outputs": {
                "expected_tools": ["glob"],
                "forbidden_tools": ["run_shell"],
                "max_iterations": 2,
                "expected_outcome": "Lists test files using glob(**/test_*.py)",
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "搜索代码中所有使用 PermissionRuleset 的地方"}],
                "agent": "build",
                "task_type": "code_search",
            },
            "outputs": {
                "expected_tools": ["grep"],
                "forbidden_tools": ["run_shell"],
                "max_iterations": 2,
                "expected_outcome": "Finds files using grep for PermissionRuleset",
            },
        },
        {
            "inputs": {
                "messages": [{"role": "user", "content": "查看 codepilot/tools/__init__.py 的内容"}],
                "agent": "build",
                "task_type": "code_search",
            },
            "outputs": {
                "expected_tools": ["read_file"],
                "forbidden_tools": ["run_shell"],
                "max_iterations": 1,
                "expected_outcome": "Reads file content using read_file, not run_shell(cat)",
            },
        },
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return dataset.name


def main():
    parser = argparse.ArgumentParser(description="Create CodePilot eval datasets")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate datasets")
    args = parser.parse_args()

    client = Client()

    if args.recreate:
        for ds in client.list_datasets():
            if ds.name.startswith("codepilot-"):
                client.delete_dataset(dataset_id=ds.id)
                print(f"Deleted: {ds.name}")

    datasets = [
        create_file_edit_dataset(client),
        create_code_search_dataset(client),
        create_project_analysis_dataset(client),
        create_general_question_dataset(client),
        create_permission_enforcement_dataset(client),
        create_tool_selection_dataset(client),
    ]
    for name in datasets:
        print(f"Created dataset: {name}")


if __name__ == "__main__":
    main()
