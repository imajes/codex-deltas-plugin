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

## Workflow

1. Read automation memory from `$CODEX_HOME/automations/codex-git-changelog/memory.md`.
2. Use only the bare HTTPS mirror under `~/.codex/automations/codex-git-changelog/repos/openai-codex.git` for range truth.
3. Determine `from` from memory and determine `to` from `refs/heads/main` after mirror update.
4. If the range is empty, emit a short no-change report and update memory accordingly.
5. For non-empty ranges, invoke [$config-maintenance](/Users/james/src/codex-hacks/config-deltas/skills/config-maintenance/SKILL.md) as the only config workflow.
6. Build the final report from repository changes plus generated config artifacts, preferring the maintenance summary and validation outputs over raw diff improvisation.
7. Save the final report under `~/.codex/config/deltas/<to_short_sha>/` and compact automation memory after the run.

## Output contract

- This skill owns the final report sections and report-writing behavior.
- This skill owns success/failure memory updates for the changelog automation.
- This skill must not replace or duplicate config classification, sync, or validation logic that belongs to `config-maintenance`.

## References

- rules: `references/rules.md`
