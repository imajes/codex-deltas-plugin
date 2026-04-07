---
name: "codex-git-changelog"
description: "Use when you need to generate the Codex repository delta report from automation memory plus the bare mirror, while delegating all config work to `config-maintenance`."
---

# Codex Git Changelog

Generate the Codex repository delta report. This skill owns the report workflow, range handling, and automation-memory behavior.

## Use this skill when

- the recurring Codex git changelog automation is running
- you need a mirror-exact range report for the Codex repository
- you need to combine repository changes with config-maintenance artifacts without re-deriving config policy in prompt prose

## Scope

- This skill owns the final report sections and report-writing behavior.
- This skill owns success/failure memory updates for the changelog automation.
- This skill must not replace or duplicate config classification, sync, or validation logic that belongs to `config-maintenance`.

## Operating paths

- plugin root: current plugin checkout (`.`)
- command: `config-maintenance`
- codex repo checkout: `/Users/james/src/artificial_intelligence/codex`
- automation memory: `$CODEX_HOME/automations/codex-git-changelog/memory.md`
- bare mirror: `$CODEX_HOME/automations/codex-git-changelog/repos/openai-codex.git`
- artifact root: `$CODEX_HOME/config/deltas/<to_short_sha>/`

## Workflow

1. Read automation memory from `$CODEX_HOME/automations/codex-git-changelog/memory.md`.
2. Use only the bare HTTPS mirror under `$CODEX_HOME/automations/codex-git-changelog/repos/openai-codex.git` for repo history, commit ranges, and destination SHA selection.
3. Update the mirror with `git --git-dir=<mirror> remote update --prune` before deriving `to`. If mirror update fails, stop immediately and produce a failure-only report.
4. Determine `from` from memory field `last_reported_origin_main_sha`. Determine `to` from `refs/heads/main` in the bare mirror after update.
5. If the range is empty, emit a short no-change report and update memory accordingly.
6. For non-empty ranges, invoke [$config-maintenance](../config-maintenance/SKILL.md) as the only config workflow, using `prepare-changelog-artifacts`.
7. Build the final report from repository changes plus generated config artifacts, preferring `config-maintenance-summary.md` and `validation.md` over raw diff improvisation.
8. Save the final report under `$CODEX_HOME/config/deltas/<to_short_sha>/repo-delta-<from_or_init>.md` and compact automation memory after the run.

## Config workflow command

`config-maintenance`

## Config workflow invocation

Use the normal repo-local invocation:

```bash
uv run config-maintenance prepare-changelog-artifacts \
  --repo /Users/james/src/artificial_intelligence/codex \
  --mirror "$CODEX_HOME/automations/codex-git-changelog/repos/openai-codex.git" \
  --from-sha <from_sha>
```

## Report contract

Report sections are:

- `## Range`
- `## TL;DR`
- `## User-Facing Changes`
- `## Config & Feature Flags`
- `## API/Library/Internal`
- `## Risk Summary`
- `## Config Diff (Baseline vs Runtime)`
- `## Proposed Config Patch (Current vs Proposed)`
- `## No-Change Note` only when the range is empty
- `## Failure` only when the run fails

Required report details:

- include `from`, `to`, and commit count
- include classification summary exactly as `new: N, pre-schema: N, legacy: N, removed: N`
- clearly distinguish the baseline/runtime visibility diff from the actionable proposed runtime patch diff
- print the full Markdown report in the conversation
- save the same substance under `$CODEX_HOME/config/deltas/<to_short_sha>/repo-delta-<from_or_init>.md`

## Reporting rules

- Keep the final report grounded in the actual range and generated artifacts.
- Do not re-derive config lifecycle or schema policy in report prose.
- Summarize user-facing changes, config evolution, API/library/internal changes, and breaking or behavioral risks.
- Ignore CI-only and test-only churn unless it changes user-visible behavior.
- Use GitHub MCP as needed for PR metadata.

## Memory updates

On full success, compact automation memory to these fields only:

- `repo_url`
- `mirror_path`
- `last_successful_fetch_origin_main_sha`
- `last_reported_origin_main_sha`
- `last_reported_range`
- `last_successful_fetch_at`
- short rolling status note
- any learnings or corrections derived from the run
- any feedback from the user for the run

Failure behavior:

- If mirror update succeeds but report generation or config-maintenance fails, update `last_successful_fetch_origin_main_sha` and `last_successful_fetch_at`, but do not advance `last_reported_origin_main_sha` or `last_reported_range`.
- If mirror update fails, do not advance fetched or reported SHAs. Keep memory compact and update only the rolling status note with the mirror failure.

## References

- rules: `references/rules.md`
