---
name: "update-state"
description: "Use when you need to write the compact automation memory for a Codex delta run after a successful report or a partial failure."
---

# Update State

Persist the compact automation state for the Codex delta workflow.

## Use this skill when

- a run finished successfully and the memory should advance to the reported SHA
- mirror refresh succeeded but later lanes failed and the fetched SHA should still be recorded
- you need to refresh only the compact memory note after reviewing artifacts

## Workflow

1. Start from `run-context.json`.
2. Choose the correct mode:
   - `success`
   - `report-failure`
   - `mirror-failure`
3. Run:

```bash
uv run codex-delta-update-state \
  --run-context <run-context.json> \
  --mode success \
  --status-note "<note>" \
  --apply
```

4. Treat `state-update.json` as the canonical record of what was written.
