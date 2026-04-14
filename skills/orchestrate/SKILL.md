---
name: "orchestrate"
description: "Use when you need to run the full Codex delta workflow as a plugin-native orchestration lane: discover the range, analyze repo and config deltas, compose the report, and update automation state."
---

# Orchestrate

Run the full Codex delta workflow. This is the top-level plugin skill for automation and ad hoc reruns.

## Use this skill when

- the recurring Codex delta automation is running
- you want the plugin to determine what changed in Codex and assemble the report
- you need to resume from an existing run directory instead of rerunning every lane

## Scope

- This skill owns lane ordering, resume behavior, and final delivery.
- This skill delegates config-specific work to `[$codex-deltas:orchestrate-config](../orchestrate-config/SKILL.md)`.
- This skill keeps nuanced interpretation in the model instead of forcing every edge case into Python heuristics.

## Operating paths

- automation root: supplied via `CODEX_DELTAS_AUTOMATION_ROOT`, `CODEX_AUTOMATION_ROOT`, or `--automation-root`
- repo URL: supplied via `CODEX_DELTAS_REPO_URL`, `CODEX_REPO_URL`, or `--repo-url`
- memory file: `<automation_root>/memory.md`
- default mirror: `/tmp/<automation_name>/<repo_slug>.git`
- artifact root: `$CODEX_HOME/config/deltas/<to_short_sha>/`

## Workflow

1. Run `[$codex-deltas:discover-range](../discover-range/SKILL.md)` to create `run-context.json`.
2. If `run-context.json` says the range is empty, emit a short no-change report and then run `[$codex-deltas:update-state](../update-state/SKILL.md)` in success mode.
3. Run `[$codex-deltas:analyze-repo](../analyze-repo/SKILL.md)` to persist `repo-findings.json`.
4. Run `[$codex-deltas:orchestrate-config](../orchestrate-config/SKILL.md)` to produce config findings, synthesized config artifacts, and validation results.
5. Run `[$codex-deltas:compose-report](../compose-report/SKILL.md)` to create the final report from the persisted artifacts.
6. Run `[$codex-deltas:update-state](../update-state/SKILL.md)` to write the compact automation memory after a successful report.

## Resume rules

- Prefer rerunning the smallest lane that answers the current question.
- If the range is already correct and only config logic changed, reuse `run-context.json` and rerun `[$codex-deltas:orchestrate-config](../orchestrate-config/SKILL.md)`.
- If only the final writeup changed, reuse the existing artifacts and rerun `[$codex-deltas:compose-report](../compose-report/SKILL.md)`.
- If only the compact memory note changed, rerun `[$codex-deltas:update-state](../update-state/SKILL.md)` without redoing the earlier lanes.

## Report contract

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

Required details:

- include `from`, `to`, and commit count
- include classification summary exactly as `new: N, pre-schema: N, legacy: N, removed: N`
- clearly distinguish the baseline/runtime visibility diff from the actionable proposed runtime patch diff
- print the full Markdown report in the conversation
- save the same substance under `$CODEX_HOME/config/deltas/<to_short_sha>/repo-delta-<from_short_sha>.md`

## Reporting rules

- Keep the final report grounded in the actual range and generated artifacts.
- Keep nuance-sensitive config interpretation in the skill reasoning, not in ad hoc rule invention.
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

- If mirror update succeeds but a later lane fails, update `last_successful_fetch_origin_main_sha` and `last_successful_fetch_at`, but do not advance `last_reported_origin_main_sha` or `last_reported_range`.
- If mirror update fails, do not advance fetched or reported SHAs. Keep memory compact and update only the rolling status note with the mirror failure.

## References

- rules: `references/rules.md`
