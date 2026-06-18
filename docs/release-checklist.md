# CodePilot Release Checklist

Use this checklist before publishing or tagging a CodePilot release.

## Version and release notes

- [ ] Confirm `pyproject.toml` has the intended version.
- [ ] Confirm `codepilot/__init__.py` reports the same version.
- [ ] Write release notes that describe user-visible changes, compatibility notes, and upgrade guidance.

## Local diagnostics

- [ ] Run `codepilot --doctor` from a normal user shell.
- [ ] Confirm required provider API keys are detected through environment variables or local config.
- [ ] Confirm missing optional MCP dependencies are warnings unless the release specifically requires MCP.

## Tests and lint

- [ ] Run `pytest tests/ -q`.
- [ ] Run `ruff check codepilot evals tests`.
- [ ] Run any release-specific eval command, such as `python -m evals.run_local --model <provider/model>`.

## Package build

- [ ] Build the package with the project build backend.
- [ ] Inspect wheel and sdist contents.
- [ ] Confirm built-in skills under `codepilot/skills/builtin/*/SKILL.md` are included.
- [ ] Install the built package in a clean environment and run `codepilot --version`.
- [ ] Run `codepilot --doctor` from the clean environment.

## Documentation

- [ ] Check README quick start commands still work.
- [ ] Check GitHub, `uv tool install`, `pipx`, and editable install instructions.
- [ ] Check links to `docs/productization-roadmap.md` and this checklist.
- [ ] Confirm CLI options in README match `codepilot --help`.

## Secrets and local paths

- [ ] Search staged changes for API keys, LangSmith keys, tokens, SSH keys, and credentials.
- [ ] Confirm no real `~/.codepilot/config.yaml` contents are committed.
- [ ] Confirm examples use placeholder URLs, provider names, and API key values.
- [ ] Confirm no machine-specific absolute paths are included except in explanatory examples.

## Git and publishing

- [ ] Confirm `git status --short` only shows intentional release changes.
- [ ] Confirm the release commit does not include caches, virtualenv files, or local database files.
- [ ] Tag only after tests, lint, diagnostics, package build, and documentation checks pass.
