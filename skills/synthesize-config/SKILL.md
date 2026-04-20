---
name: "synthesize-config"
description: "Use when you need to regenerate the synced clean config, the proposed runtime config, and the config diffs from a config findings artifact."
---

# Synthesize Config

Rewrite the clean baseline and proposed runtime config from a lifecycle inventory. This skill owns deterministic formatting, ordering, and migration only.

## Use this skill when

- `config-CLEAN.toml` is missing keys or has wrong defaults
- runtime config needs a migration patch
- a layout-only alpha-sort pass is needed before adding new keys

## Workflow

1. Start from a config findings JSON.
2. In `layout-only` mode, normalize ordering without adding or removing keys.
3. In full mode, rewrite `config-CLEAN.toml` canonically and rewrite a proposed runtime file with targeted normalization only.
4. Keep deprecated/legacy keys commented in clean and absent from runtime proposals.
5. Hand the outputs to `[$codex-deltas:validate-config](../validate-config/SKILL.md)`.
6. Emit meaningful comments for generated additions and feature flags; do not preserve or invent boilerplate descriptions.
7. If a generated comment cannot be backed by current schema metadata or current code semantics, fail the run instead of emitting a placeholder.

## Scripts

```bash
uv run codex-delta-synthesize-config --help
```

## Boundaries

- Do not classify keys.
- Do not decide policy validity.
- Do not generate changelog summaries or own git history selection.

## References

- rules: `references/rules.md`
