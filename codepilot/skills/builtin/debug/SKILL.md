# debug

Use this skill when investigating failing tests, exceptions, runtime errors, regressions, or confusing behavior.

Workflow:
- Reproduce the failure with the smallest relevant command.
- Read the exact error and the nearest code paths.
- Form one concrete hypothesis at a time.
- Apply the smallest fix that addresses the root cause.
- Re-run the targeted test or command.

Avoid broad refactors while debugging unless the failure proves the design is wrong.
