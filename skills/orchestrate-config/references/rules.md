# Orchestrate Config Rules

- This skill owns only the config subworkflow.
- Repository history should come from the bare mirror under `/tmp/codex-git-changelog/openai-codex.git`.
- Current schema and feature truth must be sourced from the bare mirror at the exact destination ref.
- Do not depend on a local workspace checkout for current truth in this workflow.
- Write artifacts only under `~/.codex/config/deltas`.
- Update the canonical `config-CLEAN.toml` only after validation passes.
- Never overwrite the live `config.toml`; emit a proposed runtime file plus a patch diff instead.
- Include a short classification summary in every markdown output for full-sync runs: `new`, `pre-schema`, `legacy`, `removed`.
- Full-sync modes require an explicit `from` SHA.
- Stop the automation on mirror update failure; do not report stale ranges as authoritative.
- Prefer a `layout-only` alpha-sort pass before introducing new keys when the clean file is structurally noisy.
- If classify, sync, align, or validate fails, still emit `config-orchestration-summary.md` and `validation.md` so higher-level automation can report the failure without improvising config conclusions.
- The canonical composite command is `codex-delta-orchestrate-config`.
