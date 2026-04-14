---
name: "analyze-config"
description: "Use when you need to interpret Codex config deltas and classify keys in the clean/runtime config as active, new, pre-schema, legacy, or removed."
---

# Analyze Config

Classify Codex config keys before touching either config file. This skill owns nuanced config interpretation for the delta workflow.

## Use this skill when

- a config delta run needs trustworthy config findings
- a feature flag seems missing or wrong in `config-CLEAN.toml`
- you need to prove whether a key is still live in code or only legacy

## Workflow

1. Read current truth from:
   - `codex-rs/features/src/lib.rs`
   - `codex-rs/features/src/legacy.rs`
   - `codex-rs/core/config.schema.json`
2. Compare against `$CODEX_HOME/config/config-CLEAN.toml` and `$CODEX_HOME/config/config.toml`.
3. Emit one config findings JSON under `$CODEX_HOME/config/deltas/`.

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
- Schema-modeled dynamic keys stay `active` even when their concrete paths are discovered through runtime structure.
- Do not blanket-classify `permissions.<profile>.network.*` as `pre-schema`; those keys may be covered by schema-driven dynamic sections.

## Script

Run:

```bash
uv run codex-delta-analyze-config --help
```

## References

- rules: `references/rules.md`
