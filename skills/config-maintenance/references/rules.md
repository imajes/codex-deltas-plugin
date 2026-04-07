# Config Maintenance Rules

- The changelog automation uses this skill only for config work; it should not re-implement classification or config synthesis in prompt prose.
- Repository history should come from the bare HTTPS mirror under `~/.codex/automations/codex-git-changelog/repos/openai-codex.git`.
- In `prepare-changelog-artifacts` mode, current schema and feature truth must be sourced from the bare mirror at the exact destination ref.
- A local workspace checkout may still exist for manual runs, but it is not authoritative for automation-time current truth.
- Write artifacts only under `~/.codex/config/deltas`.
- Update the canonical `config-CLEAN.toml` only after validation passes.
- Never overwrite the live `config.toml`; emit a proposed runtime file plus a patch diff instead.
- Include a short classification summary in every markdown output for full-sync runs: `new`, `pre-schema`, `legacy`, `removed`.
- Stop the automation on mirror update failure; do not report stale ranges as authoritative.
- Prefer a `layout-only` alpha-sort pass before introducing new keys when the clean file is structurally noisy.
- If classify, sync, align, or validate fails, still emit `config-maintenance-summary.md` and `validation.md` so higher-level automation can report the failure without improvising config conclusions.
- The canonical command is `config-maintenance`.
- From within the plugin tree, invoke it as `uv run config-maintenance ...`.
