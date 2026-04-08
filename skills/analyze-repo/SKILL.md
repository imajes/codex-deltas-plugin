---
name: "analyze-repo"
description: "Use when you need to gather repository-level evidence for a Codex delta run from the discovered range without composing the final report yet."
---

# Analyze Repo

Persist repository findings for the selected Codex delta range.

## Use this skill when

- `run-context.json` already exists
- you need commit and changed-file evidence before writing the report
- you want to rerun repo analysis without rerunning config lanes

## Workflow

1. Start from `run-context.json`.
2. Run:

```bash
uv run codex-delta-analyze-repo --run-context <run-context.json>
```

3. Treat `repo-findings.json` as the canonical repo evidence handoff for report composition.

## Output

- `repo-findings.json`
