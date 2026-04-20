# Changelog

All notable changes to `codex-deltas` are documented in this file.

This repository does not yet use annotated release tags, so the version sections
below are reconstructed from the committed version metadata and the actual git
history in this repo.

## [0.5.0] - 2026-04-20

This release tightens config comment synthesis so generated config guidance is
actually informative: feature flags now carry source-backed descriptions,
legacy aliases name the preferred canonical key, and unresolved meanings stop
the run instead of silently degrading to boilerplate.

### Changed

- Parsed feature descriptions directly from `codex-rs/features/src/lib.rs` and
  threaded them through config lifecycle inventory, clean config synthesis, and
  runtime proposal generation.
- Replaced the generic feature-registry comment fallback with semantic
  descriptions derived from current code, while still preserving meaningful
  existing inline comments in `config-CLEAN.toml`.
- Strengthened runtime proposal synthesis so generated additions must have a
  meaningful description from schema metadata, curated source-backed overrides,
  or feature-registry semantics.
- Changed unresolved comment generation from a placeholder path into a hard
  failure, so ambiguous additions are surfaced as workflow errors rather than
  misleading prose.
- Updated the config workflow docs to require meaningful descriptions and
  explicit canonical keys for legacy feature aliases.
- Bumped the plugin/package metadata to `0.5.0` in both packaging and plugin
  manifest surfaces.

### Tests

- Extended the runtime sync suite to cover:
  - source-backed feature descriptions in runtime additions
  - legacy feature comments naming the canonical replacement
  - failure when no meaningful description can be derived

## [0.4.0] - 2026-04-20

This release tightens the plugin instructions around how the delta workflow is
actually executed: use the skills as workflow playbooks, keep the report format
stable across runs, and write the report directly from the persisted artifacts.

### Changed

- Clarified the top-level orchestration skill so config work is framed as a
  subworkflow to follow, and report composition is framed as direct report
  writing from persisted artifacts rather than a separate delegated lane.
- Strengthened the compose-report skill with explicit writing expectations:
  - preserve the documented section order and headings
  - treat `config-orchestration-summary.md` and `validation.md` as the primary
    config narrative inputs
  - keep the baseline/runtime visibility diff separate from the actionable
    proposed runtime patch
- Updated the orchestration rules and README so the plugin more clearly
  distinguishes between:
  - skill-owned workflow structure
  - direct execution of the documented `uv run ...` command surfaces
- Reworded the changelog automation template prompt to say “read and follow”
  the orchestration skill, and removed the misleading warning that implied the
  command surface and the skill workflow were mutually exclusive.
- Bumped the plugin/package metadata to `0.4.0` in both packaging and plugin
  manifest surfaces.

## [0.3.0] - 2026-04-14

This release changes runtime proposal synthesis so newly classified
`preserve-or-add` keys are surfaced in the generated artifacts instead of
quietly disappearing when the live runtime file does not already contain them.

### Changed

- Added schema-aware runtime proposal planning for missing
  `runtime_policy = "preserve-or-add"` keys:
  - feature flags with explicit registry defaults are now proposed directly
  - schema-visible scalar keys with explicit defaults are now proposed directly
  - newly introduced structured keys can be surfaced as exemplars or
    comment-only review stubs instead of being omitted
- Added review metadata plumbing from synthesis into orchestration so the config
  lane can explain which runtime additions were proposed automatically and which
  still need manual completion.
- Bumped the plugin/package metadata to `0.3.0` in both packaging and plugin
  manifest surfaces.

### Fixed

- Fixed `proposed-config.toml` generation so missing runtime keys such as:
  - `features.telepathy`
  - `features.use_agent_identity`
  - `tui.notification_condition`
  - `marketplaces`
  - `realtime.transport`
  - `realtime.voice`
  are now surfaced in the proposal according to policy instead of being silently
  ignored.
- Fixed exemplar handling so manual-review additions are called out in both:
  - inline comments inside `proposed-config.toml`
  - a dedicated `## Runtime Additions Requiring Review` section in
    `config-orchestration-summary.md`
- Fixed the ambiguous-key path so new runtime additions without a safe concrete
  default are still brought to the user’s attention as comment-only review
  stubs.

### Tests

- Extended the runtime sync test suite to cover:
  - preserved removals
  - safe-default runtime additions
  - table-shaped exemplars
  - comment-only review stubs for ambiguous additions
  - the orchestration summary review section

## [0.2.0] - 2026-04-14

This release turns the original config-deltas toolchain into a plugin-shaped,
skill-driven Codex delta workflow with mirror-backed range discovery, resumable
artifacts, and installable plugin metadata.

### Added

- A lane-oriented plugin workflow centered on:
  - `orchestrate`
  - `discover-range`
  - `analyze-repo`
  - `orchestrate-config`
  - `compose-report`
  - `update-state`
- Dedicated command surfaces for the new lane model, including:
  - `codex-delta-discover-range`
  - `codex-delta-analyze-repo`
  - `codex-delta-analyze-config`
  - `codex-delta-synthesize-config`
  - `codex-delta-validate-config`
  - `codex-delta-orchestrate-config`
  - `codex-delta-update-state`
- Persisted automation artifacts for reruns and resumability, including:
  - `run-context.json`
  - `repo-findings.json`
  - `state-update.json`
  - config findings, validation, and report artifacts under `$CODEX_HOME/config/deltas/...`
- Plugin app and MCP manifest files needed for Codex to resolve the plugin surface correctly.

### Changed

- Renamed and restructured the project from the earlier config-deltas workflow into the `codex-deltas` plugin surface.
- Moved the delta workflow fully into plugin skills so the top-level automation prompt can stay thin and delegate behavior to the skill graph.
- Made the changelog workflow mirror-only:
  - removed checkout-backed range discovery for report generation
  - required explicit `from..to` baselines for non-layout runs
  - treated the bare mirror as the source of truth for history and current-ref file materialization
- Generalized automation-root handling:
  - derive automation state from `--automation-root`, `CODEX_DELTAS_AUTOMATION_ROOT`, or `CODEX_AUTOMATION_ROOT`
  - replaced the fixed `codex-git-changelog` automation directory with a reusable changelog template
  - updated the sync helper to target an explicitly chosen automation root
- Generalized repository identity handling:
  - derive repo identity from `--repo-url`, `CODEX_DELTAS_REPO_URL`, or `CODEX_REPO_URL`
  - derive default mirror filenames from repo URL slugs instead of hardcoding `openai-codex.git`
  - normalize actionable skill/prompt path language around `$CODEX_HOME`
- Bumped the plugin/package metadata to `0.2.0` in both packaging and plugin manifest surfaces.

### Fixed

- Fixed plugin metadata resolution so Codex can load the plugin shape correctly, including the app and MCP pointers.
- Fixed config classification and runtime artifact generation to continue respecting the new lane boundaries after the plugin rewrite.
- Extended the runtime-sync test suite to cover the new discover-range, repo-analysis, automation-root, and repo-url behaviors.

### Key Commits

- `eba580d` `feat(plugin): restructure codex delta workflow into lanes`
- `e090d5b` `fix: resolve the config properly`
- `36c3062` `refactor(changelog): make delta workflow mirror-only`
- `03a6039` `refactor(automation): generalize automation root handling`
- `ab71775` `refactor(paths): derive mirror identity from repo url`
- `f50ae40` `chore(release): bump plugin version to 0.2.0`

## [0.1.0] - 2026-03-25

Initial packaged release line for the standalone Codex config maintenance
toolchain that this plugin was later built from.

### Added

- The initial repo-owned config maintenance toolchain:
  - shared `codex_config` library
  - lifecycle classification
  - clean/runtime sync generation
  - config validation
  - maintenance-oriented skills and scripts
- `uv`-managed project metadata and lockfile support for repeatable local execution.
- First-class test coverage for runtime sync behavior and permission-shape migration rules.
- A repo-local `just` helper for syncing the automation prototype back into Codex home after app-side rewrites.
- Packaged CLI entrypoints for the original config tools once the repo became a real `uv` package.

### Changed

- Switched runtime proposal generation to structured TOML editing with `tomlkit` instead of relying on fragile text-only rewrites.
- Moved changelog policy and failure-handling guidance out of prompt prose and into repo-owned skills.
- Materialized schema and feature truth from the bare mirror at the exact destination ref during changelog artifact preparation.
- Reorganized the command implementations under `lib/codex_config/commands/` while keeping skill-local script paths as compatibility shims.

### Fixed

- Hardened runtime validation so proposals must preserve `default_permissions = "workspace"` and migrate away from legacy `[permissions.network]`.
- Preserved failure artifacts even when classify, sync, or alignment stages fail early.
- Correctly handled schema-modeled dynamic config keys so they are not misclassified as pre-schema or removed.
- Preserved comment-only reference block ordering during no-op runtime syncs, including `[tools.web_search]` and `[skills]` adjacency.

### Key Commits

- `23deb37` `feat(config-deltas): bootstrap config maintenance toolchain`
- `ece507f` `feat(runtime): manage config tooling with uv and tomlkit`
- `3d887b1` `fix(config-deltas): harden runtime sync validation`
- `33e5dec` `fix(maintenance): preserve failure artifacts`
- `d53b9ab` `refactor(maintenance): source truth from mirror ref`
- `0cf5eab` `docs(skills): move changelog policy into repo skills`
- `d7879e5` `chore(automation): add justfile sync helper`
- `f4fbe2b` `fix(classifier): respect schema-modeled dynamic config keys`
- `af167b0` `fix(runtime-sync): preserve comment-only reference block order`
- `97c597b` `feat(cli): expose config tools as uv project scripts`
