# Analyze Config Rules

- Feature truth comes from `codex-rs/features/src/lib.rs`, not from the schema alone.
- Legacy feature aliases come from `codex-rs/features/src/legacy.rs`.
- Schema-visible removed feature keys must still be treated as removed if their `FeatureSpec.stage` is `Removed`.
- `apps.<id>.disabled_reason` is the primary known pre-schema key today.
- `permissions.<profile>.network.*` is not a blanket pre-schema family.
- `memories.phase_1_model`, `memories.phase_2_model`, and `memories.max_raw_memories_for_global` are removed, not pre-schema.
