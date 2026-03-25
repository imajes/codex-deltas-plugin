# Config Maintenance Rules

- The changelog automation uses this skill only for config work; it should not re-implement classification or config synthesis in prompt prose.
- Repository history should come from the bare HTTPS mirror under `~/.codex/automations/codex-git-changelog/repos/openai-codex.git`.
- The live workspace repo is read-only context for schema and feature metadata.
- Write artifacts only under `~/.codex/config/deltas`.
- Update the canonical `config-CLEAN.toml` only after validation passes.
- Never overwrite the live `config.toml`; emit a proposed runtime file plus a patch diff instead.
- Include a short classification summary in every markdown output for full-sync runs: `new`, `pre-schema`, `legacy`, `removed`.
- Stop the automation on mirror update failure; do not report stale ranges as authoritative.
- Prefer a `layout-only` alpha-sort pass before introducing new keys when the clean file is structurally noisy.
