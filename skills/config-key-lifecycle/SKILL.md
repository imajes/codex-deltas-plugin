---
name: "config-key-lifecycle"
description: "Use when you need to classify Codex config keys in `~/.codex/config/config-CLEAN.toml` or `~/.codex/config/config.toml` as active, new, pre-schema, legacy, or removed using the current Codex feature registry, schema, and compatibility rules."
---

# Config Key Lifecycle

Classify Codex config keys before touching either config file. This skill is the authority for `active` vs `new` vs `pre-schema` vs `legacy` vs `removed`.

## Use this skill when

- a config delta run needs trustworthy key classification
- a feature flag seems missing or wrong in `config-CLEAN.toml`
- you need to prove whether a key is still live in code or only legacy

## Workflow

1. Read current truth from:
   - `codex-rs/features/src/lib.rs`
   - `codex-rs/features/src/legacy.rs`
   - `codex-rs/core/config.schema.json`
2. Compare against `~/.codex/config/config-CLEAN.toml` and `~/.codex/config/config.toml`.
3. Emit one inventory JSON under `~/.codex/config/deltas/`.

## Categories

- `active`: canonical key used by code today
- `new`: active key that did not exist at the comparison SHA
- `pre-schema`: code-visible key not represented in generated schema; prefer over omission when current code still reads the key
- `legacy`: compatibility alias, deprecated canonical key, or deprecated shape kept for migration only
- `removed`: no longer active in current code path

## Policy

- Non-feature keys that are not schema-visible do not default to `active`.
- They must be proven as `pre-schema` by current code or classified as `legacy`/`removed`.
- Deprecated canonical feature keys should be treated as `legacy`, not as fresh active toggles.

## Script

Run:

```bash
python3 "$CODEX_HOME/skills/config-key-lifecycle/scripts/classify_config_keys.py" --help
```

## References

- rules: `references/rules.md`
