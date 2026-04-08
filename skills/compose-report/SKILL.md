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
2. Keep nuanced interpretation in the report text, especially for dynamic config structures and migration intent.
3. Write the final markdown to the report path recorded in `run-context.json`.
4. Print the same report substance in the conversation.

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
