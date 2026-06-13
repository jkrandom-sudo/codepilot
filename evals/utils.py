"""Shared utilities for LangSmith evaluation scripts."""
from __future__ import annotations

import os

from langsmith import Client


DEFAULT_PROJECT_NAME = "codepilot"


def get_client_and_project_id(project_name: str = DEFAULT_PROJECT_NAME) -> tuple[Client, str]:
    """Create a LangSmith Client and resolve the project ID.

    The langsmith Client.list_runs(project_name=...) can fail with 401
    on some LangSmith API versions, so we use project_id instead.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY", "")
    api_url = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    if project_name == DEFAULT_PROJECT_NAME:
        project_name = os.environ.get("LANGSMITH_PROJECT", project_name)

    # Try loading from codepilot config if env vars not set
    if not api_key:
        try:
            from codepilot.config.settings import load_config
            config = load_config()
            api_key = config.langsmith.api_key
            api_url = config.langsmith.endpoint
            if project_name == DEFAULT_PROJECT_NAME:
                project_name = config.langsmith.project
            if api_key:
                os.environ["LANGSMITH_API_KEY"] = api_key
            os.environ["LANGSMITH_PROJECT"] = project_name
            os.environ["LANGSMITH_ENDPOINT"] = api_url
        except Exception:
            pass

    client = Client(api_key=api_key, api_url=api_url)

    # Resolve project name to ID
    for p in client.list_projects():
        if p.name == project_name:
            return client, str(p.id)

    raise ValueError(f"Project '{project_name}' not found in LangSmith")
