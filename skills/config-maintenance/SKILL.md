---
name: "config-maintenance"
description: "Use when you need to run the Codex config maintenance workflow end to end: classify config keys, regenerate `config-CLEAN.toml`, produce a proposed `config.toml` patch, validate ordering/defaults/migrations, and emit deterministic diff artifacts for changelog automation."
---

# Config Maintenance

Run the full config-maintenance pipeline. This skill orchestrates config work only.

## Use this skill when

- a changelog run needs config artifacts and validation
- `config-CLEAN.toml` and `config.toml` need to be reconciled safely
- you need a mirror-backed config delta workflow that does not depend on the main workspace git state

## Scope

- This skill owns config classification, sync, validation, and config diff artifacts.
- This skill does not own repository-change narration or final changelog report formatting.
- Higher-level report workflows must consume the emitted artifacts instead of re-deriving config policy in prompt prose.

## Operating paths

- plugin root: current plugin checkout (`.`)
- command: `config-maintenance`
- default repo checkout: `/Users/james/src/artificial_intelligence/codex`
- automation state: `$CODEX_HOME/automations/codex-git-changelog`
- default bare mirror: `$CODEX_HOME/automations/codex-git-changelog/repos/openai-codex.git`
- canonical clean config: `$CODEX_HOME/config/config-CLEAN.toml`
- live runtime config: `$CODEX_HOME/config/config.toml`
- artifact root: `$CODEX_HOME/config/deltas/<to_short_sha>/`

## Workflow

1. Use `config-key-lifecycle` to classify keys when running full sync.
2. Use `config-file-sync` in either `layout-only` or full sync mode.
3. Use `config-validate` to validate the generated outputs.
4. Align inline comments, generate diffs, and emit a manifest-style markdown summary under `~/.codex/config/deltas/<short-sha>/`.
5. In `prepare-changelog-artifacts` mode, source current schema and feature truth from the bare mirror at the exact destination ref instead of trusting a local checkout to be current.
6. Treat `config-maintenance-summary.md` and `validation.md` as canonical even on failure; this workflow must leave usable artifacts behind for higher-level reporting.

## Modes

- `alpha-sort-only`: layout cleanup only; do not classify or add/remove keys.
- `sync-current`: classify and sync against the current checkout.
- `prepare-changelog-artifacts`: classify and sync for changelog automation using mirror-backed current truth at the destination ref.
- `touch-features` and `repair-runtime`: maintenance helper modes exposed by the runner; use only when the task explicitly calls for them.

## Behavioral rules

- For changelog automation, this is the only config workflow. Do not hand-roll classify/sync/validate logic outside the runner.
- In `prepare-changelog-artifacts` mode, repository history and truth sources come from the bare mirror, not workspace git state.
- Write outputs only under `$CODEX_HOME/config/deltas/<short_sha>/`.
- Update the canonical `config-CLEAN.toml` only after validation passes.
- Never overwrite the live `config.toml`; emit `proposed-config.toml` and `proposed-patch.diff` instead.
- Prefer `config-maintenance-summary.md` and `validation.md` as the source of truth for downstream reporting, including failure cases.

## Command

`config-maintenance`

## Invocation

From within the plugin tree:

```bash
uv run config-maintenance --help
```

Prepare changelog artifacts with the normal repo-local invocation:

```bash
uv run config-maintenance prepare-changelog-artifacts \
  --repo /Users/james/src/artificial_intelligence/codex \
  --mirror "$CODEX_HOME/automations/codex-git-changelog/repos/openai-codex.git" \
  --from-sha <from_sha>
```

## Produced artifacts

- `config-key-inventory-<from_short_or_current>.json`
- `config-CLEAN-synced.toml`
- `proposed-config.toml`
- `baseline-vs-runtime.diff`
- `proposed-patch.diff`
- `validation.md`
- `config-maintenance-summary.md`

## References

- rules: `references/rules.md`
