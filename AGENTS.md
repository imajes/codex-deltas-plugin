# Repository Guidelines

## Purpose & Workflow

This repository is the local source of truth for the `codex-deltas` Codex plugin. It bundles lane-oriented skills, Python helper commands, and an automation template for mirror-based Codex changelog and config-delta workflows. In practice, the top-level skill selects the lane order, the packaged CLIs do the concrete work, and generated artifacts land in the caller’s automation or artifact root rather than in this repo.

## Project Structure & Module Organization

`lib/codex_config/` contains the packaged Python code. Keep CLI entrypoints in `lib/codex_config/commands/` thin, and move reusable logic into shared modules such as `shared.py` or `automation_state.py`. Plugin-facing workflow docs live in `skills/<lane>/`; each lane directory may also include `agents/`, `scripts/`, and `references/`. `skills/orchestrate/` owns top-level lane ordering, while `skills/orchestrate-config/` owns the config-only path. Use `automations/changelog-template/automation.toml` as the template for new automation roots. Tests live under `tests/`, and plugin metadata lives in `.codex-plugin/plugin.json`.

## Build, Test, and Development Commands

Use `uv` for local development and script execution:

- `uv sync` installs the package and dev dependencies into the local environment.
- `uv run --group dev pytest -q` runs the test suite.
- `uv run codex-delta-discover-range --help` checks the range-discovery CLI surface.
- `uv run codex-delta-orchestrate-config --help` inspects the config-only workflow entrypoint.
- `AUTOMATION_ROOT=/path/to/root just sync-automation-template` copies the shipped automation template into a real automation root.

## Coding Style & Naming Conventions

Target Python 3.9+ and use 4-space indentation. Follow the existing naming split: Python modules and functions use `snake_case`, while skill directories use kebab-case such as `skills/analyze-config/`. Prefer explicit type hints on public helpers and command-layer functions. Keep comments brief and factual. For config synthesis, repository policy is strict: emitted comments must be source-backed, and ambiguous keys should fail review rather than receive generic placeholder prose.

## Testing Guidelines

Tests use `pytest`. Add regression coverage next to the existing runtime-sync tests, either in `tests/test_runtime_sync.py` or a new `tests/test_<area>.py` file. Name tests `test_<expected_behavior>`. When changing config sync or validation logic, cover TOML round-tripping, legacy-key cleanup, and failure cases for missing metadata.

## Commit & Pull Request Guidelines

History follows Conventional Commits, usually with a focused scope: `fix(config-sync): ...`, `feat(config-sync): ...`, or `chore: ...`. Keep commits narrow and describe why the change matters in the body when behavior, tests, or release metadata move together. Pull requests should call out affected lanes, exact validation commands run, and any changed artifact roots, baseline SHAs, or generated outputs.

## Security & Configuration Tips

This plugin is mirror-first and automation-driven. Do not treat a mutable checkout as the source of truth for changelog runs; prefer explicit `--from-sha`, `--memory`, and automation-root inputs when reproducing or debugging workflow behavior. Keep plugin-facing metadata aligned when releasing: `pyproject.toml`, `.codex-plugin/plugin.json`, `CHANGELOG.md`, and `uv.lock` should move together.
