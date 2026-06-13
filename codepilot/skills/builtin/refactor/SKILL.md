# refactor

Use this skill when improving structure without changing intended behavior.

Workflow:
- Characterize current behavior with existing tests or a small new regression test.
- Move code in small steps and preserve public interfaces where practical.
- Keep compatibility wrappers when other modules or tests import old function names.
- Run tests after each meaningful structural change.
- Document the new boundary if it becomes part of the architecture.
