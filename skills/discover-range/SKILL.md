---
name: "discover-range"
description: "Use when you need to read automation state, refresh the mirror, determine the next Codex delta range, and persist a run-context artifact."
---

# Discover Range

Discover the next Codex delta range and persist the run context for downstream lanes.

## Use this skill when

- you are starting a new Codex delta run
- you need to confirm `from` and `to` before rerunning downstream lanes
- you need to recover the run context for an existing artifact directory

## Workflow

1. Read the compact automation memory from `$CODEX_HOME/automations/codex-git-changelog/memory.md`.
2. Use only the bare mirror at `/tmp/codex-git-changelog/openai-codex.git` for range truth.
3. Run:

```bash
uv run codex-delta-discover-range
```

4. If automation memory does not already contain `last_reported_origin_main_sha`, rerun with `--from-sha <sha>`.
5. Treat the emitted `run-context.json` as the canonical handoff for downstream lanes.

## Output

- `run-context.json`
