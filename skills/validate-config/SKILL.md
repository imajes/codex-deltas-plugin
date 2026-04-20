---
name: "validate-config"
description: "Use when you need to validate generated Codex config artifacts against ordering, section-link placement, feature defaults, legacy or removed key policy, and runtime migration rules without regenerating them."
---

# Validate Config

Validate generated config artifacts. This skill owns policy checks only.

## Use this skill when

- a clean/runtime artifact pair needs policy validation
- you want to review a layout-only alpha-sort pass before adding new keys
- a sync run succeeded structurally but you need to know whether it satisfies config rules

## Workflow

1. Read the generated clean/runtime artifacts.
2. Validate ordering, section comments, and TOML parseability.
3. In full mode, validate feature defaults, removed keys, legacy keys, and runtime permission-shape migrations.
4. Reject generated comments that fall back to generic boilerplate instead of meaningful descriptions.
5. Reject comments that are source-backed but still tautological or too terse to be useful when a conservative current-code expansion was available.
6. Reject editorialized comments that add claims not supported by current schema metadata, current code, or current feature-registry context.
7. Reject legacy feature comments that omit the preferred canonical key.
8. Emit one markdown validation summary under `$CODEX_HOME/config/deltas/...`.

## Script

```bash
uv run codex-delta-validate-config --help
```

## Boundaries

- Do not rewrite files.
- Do not classify keys.
- Do not generate diffs.
- Do not update the canonical clean file.
