---
name: "orchestrate-config"
description: "Use when you need to rerun or resume the config-specific lanes of the Codex delta workflow: analyze config deltas, synthesize config outputs, and validate the results."
---

# Orchestrate Config

Run the config-only subworkflow. This skill coordinates the config lanes but does not own range discovery, repo analysis, or final report writing.

## Use this skill when

- a Codex delta run needs config findings or regenerated config artifacts
- you changed config analysis or synthesis logic and want to rerun only those lanes
- `config-CLEAN.toml` and `config.toml` need to be reconciled from an existing run context

## Scope

- This skill owns config findings, synthesized config outputs, and config validation.
- This skill may use the composite command, but lane-by-lane reruns are preferred when you only need part of the config flow.
- This skill does not own repo findings, final report prose, or automation memory policy.

## Operating paths

- composite command: `codex-delta-orchestrate-config`
- automation state: `$CODEX_HOME/automations/codex-git-changelog`
- default bare mirror: `/tmp/codex-git-changelog/openai-codex.git`
- canonical clean config: `$CODEX_HOME/config/config-CLEAN.toml`
- live runtime config: `$CODEX_HOME/config/config.toml`
- artifact root: `$CODEX_HOME/config/deltas/<to_short_sha>/`

## Workflow

1. Use `[$codex-deltas:analyze-config](../analyze-config/SKILL.md)` to emit config findings.
2. Use `[$codex-deltas:synthesize-config](../synthesize-config/SKILL.md)` to build the synced clean config, proposed runtime config, and diffs.
3. Use `[$codex-deltas:validate-config](../validate-config/SKILL.md)` to validate the generated artifacts.
4. Treat `config-orchestration-summary.md` and `validation.md` as canonical config artifacts even on failure.

## Modes

- `alpha-sort-only`: layout cleanup only; do not classify or add/remove keys.
- `sync-current`: classify and sync against mirror `main` at the current destination ref.
- `prepare-changelog-artifacts`: classify and sync for changelog automation using mirror-backed current truth at the destination ref.
- `touch-features` and `repair-runtime`: maintenance helper modes exposed by the runner; use only when the task explicitly calls for them.

## Behavioral rules

- Use lane skills when you want a targeted rerun.
- Use the composite command when you intentionally want the entire config subworkflow in one shot.
- Repository history and current truth sources come from the bare mirror, not workspace git state.
- Full-sync modes require `--from-sha` so the workflow always has an explicit `from..to` comparison.
- Write outputs only under `$CODEX_HOME/config/deltas/<short_sha>/`.
- Update the canonical `config-CLEAN.toml` only after validation passes.
- Never overwrite the live `config.toml`; emit `proposed-config.toml` and `proposed-patch.diff` instead.
- Prefer `config-orchestration-summary.md` and `validation.md` as the source of truth for downstream reporting, including failure cases.

## Command

`codex-delta-orchestrate-config`

## Invocation

From within the plugin tree:

```bash
uv run codex-delta-orchestrate-config --help
```

Prepare changelog artifacts with the normal repo-local invocation:

```bash
uv run codex-delta-orchestrate-config prepare-changelog-artifacts \
  --mirror /tmp/codex-git-changelog/openai-codex.git \
  --from-sha <from_sha>
```

## Produced artifacts

- `config-findings-<from_short_or_current>.json`
- `config-CLEAN-synced.toml`
- `proposed-config.toml`
- `baseline-vs-runtime.diff`
- `proposed-patch.diff`
- `validation.md`
- `config-orchestration-summary.md`

## References

- rules: `references/rules.md`
