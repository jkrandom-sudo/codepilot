# CodePilot Agent Instructions

## Project

CLI coding agent built with Python, LangChain, and LangGraph.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Commands

- Run app: `codepilot`
- Non-interactive: `codepilot -p "prompt"`
- Tests: `pytest tests/ -q`
- Lint: `ruff check codepilot evals tests`

## Project Structure

- `.github/`
- `AGENTS.md`
- `README.md`
- `codepilot/`
- `docs/`
- `evals/`
- `opencode_analysis.pdf`
- `pyproject.toml`

## Agent Notes

- Prefer existing project patterns over new abstractions.
- Use dedicated tools for reading/searching files instead of shell search commands.
- Keep edits scoped and verify with tests when behavior changes.
