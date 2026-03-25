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

## Script

```bash
python3 "$CODEX_HOME/skills/config-maintenance/scripts/run_config_maintenance.py" --help
```

## References

- rules: `references/rules.md`
