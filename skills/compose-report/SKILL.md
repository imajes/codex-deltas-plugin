---
name: "compose-report"
description: "Use when you need to combine persisted repo findings and config artifacts into the final Codex delta report."
---

# Compose Report

Write the final Codex delta report from the persisted lane artifacts.

## Use this skill when

- `run-context.json` and `repo-findings.json` already exist
- the config subworkflow has produced its artifacts
- you need to regenerate the report without rerunning analysis lanes

## Inputs

- `run-context.json`
- `repo-findings.json`
- `config-orchestration-summary.md`
- `validation.md`
- `config-findings-<compare>.json`
- `baseline-vs-runtime.diff`
- `proposed-patch.diff`

## Workflow

1. Read the persisted artifacts before re-querying git or config files.
2. Write the report directly in the model from those artifacts; this lane does not require a dedicated helper command.
3. Keep nuanced interpretation in the report text, especially for dynamic config structures and migration intent.
4. Preserve the documented section order and heading text exactly so recurring reports remain comparable.
5. Write the final markdown to the report path recorded in `run-context.json`.
6. Print the same report substance in the conversation.

## Report sections

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

## Writing Expectations

- Treat `config-orchestration-summary.md` and `validation.md` as the primary config narrative inputs.
- Treat relocation entries as part of the top-line `legacy` count, but use the summary artifact's lifecycle and runtime-migration subsections to distinguish true removals, plain legacy aliases, and relocations.
- Keep the baseline/runtime visibility diff clearly separate from the actionable proposed runtime patch.
- Keep the prose stable enough that repeated runs read like the same report format, not a new essay each time.
- If config validation failed, keep the failure grounded in the recorded artifacts instead of improvising a fix narrative.
