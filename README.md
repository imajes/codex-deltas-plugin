# codex-deltas

Local source-of-truth repo for the Codex delta workflow plugin.

This code lives as the `codex-deltas` local plugin.

This repo owns:
- `lib/codex_config/`
- `skills/orchestrate/`
- `skills/discover-range/`
- `skills/analyze-repo/`
- `skills/orchestrate-config/`
- `skills/analyze-config/`
- `skills/synthesize-config/`
- `skills/validate-config/`
- `skills/compose-report/`
- `skills/update-state/`
- `automations/changelog-template/`

## Automation surfaces

The changelog automation stack for this plugin is split deliberately:

- `skills/orchestrate/` owns top-level lane ordering and resume behavior.
- `skills/orchestrate-config/` owns the config-only subworkflow.
- Leaf lane skills own range discovery, repo analysis, config analysis, config synthesis, config validation, report composition, and state updates.
- `automations/changelog-template/automation.toml` is a prototype template for copying into a real automation root; plugin installation does not auto-register it.

Use the skill docs as the workflow playbooks for this plugin. They define lane
ordering, report structure, and artifact expectations; the actual helper
commands are still run directly through the normal `uv run ...` command surface.

For config maintenance, generated comments are expected to be source-backed.
Feature flags should describe what the feature does, legacy aliases should name
the preferred canonical key, and synthesis should fail rather than emit generic
placeholder prose when the meaning cannot be derived from current schema or
current code.

For changelog runs, the canonical folders are:

- automation root: supplied via `CODEX_DELTAS_AUTOMATION_ROOT`, `CODEX_AUTOMATION_ROOT`, or `--automation-root`
- repo URL: supplied via `CODEX_DELTAS_REPO_URL`, `CODEX_REPO_URL`, or `--repo-url`
- memory file: `<automation_root>/memory.md`
- default mirror: `/tmp/<automation_name>/<repo_slug>.git`
- artifact root: `$CODEX_HOME/config/deltas`

The workflow is mirror-only. It no longer reads current truth from a mutable working checkout.
Seed the baseline from automation memory or pass an explicit `--from-sha`; report runs always operate on a concrete `from..to` range.
If the automation root is unknown, pass explicit `--memory` and `--mirror` paths instead of relying on a baked-in automation name.
If the repo URL is not configured, the plugin falls back to `https://github.com/openai/codex.git`.

## Runtime

Use `uv` for dependency management and script execution.
Use `uv run <project-script>` as the helper-command surface for lane entrypoints.

Examples:

```bash
uv sync
uv run codex-delta-discover-range --help
uv run codex-delta-orchestrate-config --help
uv run --group dev pytest -q
AUTOMATION_ROOT="$CODEX_HOME/automations/openai-codex-src-changelog-deltas" just sync-automation-template
```
