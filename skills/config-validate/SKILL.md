---
name: "config-validate"
description: "Use when you need to validate generated Codex config artifacts against ordering, section-link placement, feature defaults, legacy/removed key policy, and runtime migration rules without re-running synthesis."
---

# Config Validate

Validate generated config artifacts. This skill owns policy checks only.

## Use this skill when

- a clean/runtime artifact pair needs policy validation
- you want to review a layout-only alpha-sort pass before adding new keys
- a sync run succeeded structurally but you need to know whether it satisfies config rules

## Workflow

1. Read the generated clean/runtime artifacts.
2. Validate ordering, section comments, and TOML parseability.
3. In full mode, validate feature defaults, removed keys, legacy keys, and runtime permission-shape migrations.
4. Emit one markdown validation summary under `~/.codex/config/deltas/...`.

## Script

```bash
uv run config-validate --help
```

## Boundaries

- Do not rewrite files.
- Do not classify keys.
- Do not generate diffs.
- Do not update the canonical clean file.
