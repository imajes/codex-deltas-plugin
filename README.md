# codex-config-deltas

Local source-of-truth repo for the Codex config maintenance toolchain.

This code now lives as the `config-deltas` local plugin under `plugins/config-deltas`.
The old `src/config-deltas` path is preserved as a compatibility symlink so existing
absolute references continue to resolve while the plugin path becomes canonical.

This repo owns:
- `lib/codex_config/`
- `skills/config-key-lifecycle/`
- `skills/config-file-sync/`
- `skills/config-validate/`
- `skills/config-maintenance/`
- `skills/codex-git-changelog/`
- `automations/codex-git-changelog/`

The live Codex skill entrypoints under `~/.codex` should point back here via symlinks.
Codex plugin discovery is registered through `.agents/plugins/marketplace.json`.

## Automation surfaces

The changelog automation stack for this plugin is split deliberately:

- `skills/config-maintenance/` owns classify, sync, validate, and config diff artifacts.
- `skills/codex-git-changelog/` owns mirror-backed range handling, final report composition, and automation-memory updates.
- `automations/codex-git-changelog/automation.toml` should stay thin and point the agent at the plugin plus the operating directories.

For changelog runs, the canonical folders are:

- plugin root: current plugin checkout (`.`)
- codex repo checkout: `/Users/james/src/artificial_intelligence/codex`
- automation state: `$CODEX_HOME/automations/codex-git-changelog`
- mirror: `$CODEX_HOME/automations/codex-git-changelog/repos/openai-codex.git`
- artifact root: `$CODEX_HOME/config/deltas`

## Runtime

Use `uv` for dependency management and script execution.
Use `uv run <project-script>` as the stable CLI surface for script entrypoints.

Examples:

```bash
uv sync
uv run config-maintenance --help
uv run config-maintenance prepare-changelog-artifacts --help
uv run --group dev pytest -q
just sync-codex-git-changelog-automation
```
