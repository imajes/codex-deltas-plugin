# Orchestrate Rules

- Resolve the automation root from `CODEX_DELTAS_AUTOMATION_ROOT`, `CODEX_AUTOMATION_ROOT`, or `--automation-root`.
- Resolve the repo URL from `CODEX_DELTAS_REPO_URL`, `CODEX_REPO_URL`, or `--repo-url`.
- Read automation memory first from `<automation_root>/memory.md`, unless `--memory` was provided explicitly.
- Use only the bare mirror under `/tmp/<automation_name>/<repo_slug>.git` for repository history, commit ranges, and destination SHA selection, unless `--mirror` was provided explicitly.
- Determine `from` from memory field `last_reported_origin_main_sha`.
- If memory does not contain `last_reported_origin_main_sha`, stop and require an explicit `--from-sha` seed rather than inventing an init range.
- Update the mirror before determining `to`. If mirror update fails, stop immediately and produce a failure-only report.
- Prefer persisted lane handoffs over recomputing earlier stages.
- Treat `[$codex-deltas:orchestrate-config](../orchestrate-config/SKILL.md)` as the config subworkflow.
- Treat `[$codex-deltas:compose-report](../compose-report/SKILL.md)` as a report-writing playbook: read the persisted artifacts and write the report directly rather than looking for a dedicated compose command.
- For non-empty ranges, consume config artifacts in this order:
  1. `config-orchestration-summary.md`
  2. `validation.md`
  3. config findings JSON
  4. synced clean file
  5. proposed runtime file
  6. baseline-vs-runtime diff
  7. proposed patch diff
- Do not re-derive config lifecycle or schema policy in the report prompt or prose.
- Report sections are:
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
- Required report details are:
  - include `from`, `to`, and commit count
  - include classification summary exactly as `new: N, pre-schema: N, legacy: N, removed: N`
  - clearly distinguish visibility diff versus actionable proposed patch diff
  - preserve the documented section order and heading text for recurring report consistency
  - print the full Markdown report in the conversation
  - save the same substance to `$CODEX_HOME/config/deltas/<to_short_sha>/repo-delta-<from_short_sha>.md`
- On full success, compact automation memory to:
  - `repo_url`
  - `mirror_path`
  - `last_successful_fetch_origin_main_sha`
  - `last_reported_origin_main_sha`
  - `last_reported_range`
  - `last_successful_fetch_at`
  - short rolling status note
- If mirror update succeeds but a later lane fails:
  - update `last_successful_fetch_origin_main_sha`
  - update `last_successful_fetch_at`
  - do not update `last_reported_origin_main_sha`
  - do not update `last_reported_range`
  - update the rolling status note with failure stage and artifact path
- If mirror update fails:
  - do not advance fetched or reported SHAs
  - keep memory compact
  - update only the rolling status note with the mirror failure
