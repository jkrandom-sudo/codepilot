# testing

Use this skill when adding, repairing, or evaluating automated tests.

Workflow:
- Identify the behavior contract before writing tests.
- Prefer focused unit tests for narrow logic and scenario tests for agent workflows.
- Add regression tests for bugs before or alongside fixes.
- Run the smallest relevant test first, then broaden if risk remains.
- Keep tests deterministic and independent of external services unless explicitly evaluating integrations.
