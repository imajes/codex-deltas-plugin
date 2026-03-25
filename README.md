# codex-config-deltas

Local source-of-truth repo for the Codex config maintenance toolchain.

This repo owns:
- `lib/codex_config/`
- `skills/config-key-lifecycle/`
- `skills/config-file-sync/`
- `skills/config-validate/`
- `skills/config-maintenance/`

The live Codex skill entrypoints under `~/.codex` should point back here via symlinks.
