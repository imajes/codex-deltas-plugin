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
- `automations/codex-git-changelog/`

## Automation surfaces

The changelog automation stack for this plugin is split deliberately:

- `skills/orchestrate/` owns top-level lane ordering and resume behavior.
- `skills/orchestrate-config/` owns the config-only subworkflow.
- Leaf lane skills own range discovery, repo analysis, config analysis, config synthesis, config validation, report composition, and state updates.
- `automations/codex-git-changelog/automation.toml` stays thin and points the agent at the top-level orchestration skill.

For changelog runs, the canonical folders are:

- automation state: `$CODEX_HOME/automations/codex-git-changelog`
- mirror: `/tmp/codex-git-changelog/openai-codex.git`
- artifact root: `$CODEX_HOME/config/deltas`

The workflow is mirror-only. It no longer reads current truth from a mutable working checkout.
Seed the baseline from automation memory or pass an explicit `--from-sha`; report runs always operate on a concrete `from..to` range.

## Runtime

Use `uv` for dependency management and script execution.
Use `uv run <project-script>` as the helper-command surface for lane entrypoints.

Examples:

```bash
uv sync
uv run codex-delta-discover-range --help
uv run codex-delta-orchestrate-config --help
uv run --group dev pytest -q
just sync-codex-git-changelog-automation
```
