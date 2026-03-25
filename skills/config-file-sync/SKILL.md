---
name: "config-file-sync"
description: "Use when you need to rewrite `~/.codex/config/config-CLEAN.toml`, generate a proposed `config.toml` patch, enforce feature default values, sort sections and keys, migrate legacy shapes, and produce deterministic config diff artifacts."
---

# Config File Sync

Rewrite the clean baseline and proposed runtime config from a lifecycle inventory. This skill owns deterministic formatting, ordering, and migration only.

## Use this skill when

- `config-CLEAN.toml` is missing keys or has wrong defaults
- runtime config needs a migration patch
- a layout-only alpha-sort pass is needed before adding new keys

## Workflow

1. Start from a lifecycle inventory JSON.
2. In `layout-only` mode, normalize ordering without adding or removing keys.
3. In full mode, rewrite `config-CLEAN.toml` canonically and rewrite a proposed runtime file with targeted normalization only.
4. Keep deprecated/legacy keys commented in clean and absent from runtime proposals.
5. Hand the outputs to `config-validate`.

## Scripts

```bash
uv run --project /Users/james/src/codex-hacks/config-deltas python skills/config-file-sync/scripts/sync_config_files.py --help
```

## Boundaries

- Do not classify keys.
- Do not decide policy validity.
- Do not generate changelog summaries or own git history selection.

## References

- rules: `references/rules.md`
