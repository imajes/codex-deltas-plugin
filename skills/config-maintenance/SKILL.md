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

## Workflow

1. Use `config-key-lifecycle` to classify keys when running full sync.
2. Use `config-file-sync` in either `layout-only` or full sync mode.
3. Use `config-validate` to validate the generated outputs.
4. Align inline comments, generate diffs, and emit a manifest-style markdown summary under `~/.codex/config/deltas/<short-sha>/`.
5. In `prepare-changelog-artifacts` mode, source current schema and feature truth from the bare mirror at the exact destination ref instead of trusting a local checkout to be current.
6. Treat `config-maintenance-summary.md` and `validation.md` as canonical even on failure; this workflow must leave usable artifacts behind for higher-level reporting.

## Output contract

- This skill owns config classification, sync, validation, and config diff artifacts.
- This skill does not own repository-change narration or final changelog report formatting.
- Higher-level report workflows should consume the emitted artifacts instead of re-deriving config policy in prompt prose.

## Script

```bash
uv run --project /Users/james/src/codex-hacks/config-deltas python skills/config-maintenance/scripts/run_config_maintenance.py --help
```

## References

- rules: `references/rules.md`
