from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from codex_config.automation_state import read_markdown_memory
from codex_config.shared import automation_root
from codex_config.shared import default_automation_memory_path
from codex_config.shared import default_automation_mirror_path


CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
DELTA_DIR = CODEX_HOME / "config" / "deltas"
REMOTE_URL = "https://github.com/openai/codex.git"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover the changelog range and persist run context."
    )
    parser.add_argument("--automation-root", type=Path)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--mirror", type=Path)
    parser.add_argument("--from-sha")
    parser.add_argument("--repo-url", default=REMOTE_URL)
    parser.add_argument("--artifact-root", type=Path, default=DELTA_DIR)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def run_stdout(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, check=True, text=True).stdout.strip()


def ensure_mirror(path: Path, repo_url: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        subprocess.run(["git", "clone", "--mirror", repo_url, str(path)], check=True)
    else:
        subprocess.run(
            ["git", f"--git-dir={path}", "remote", "set-url", "origin", repo_url],
            check=True,
        )
    subprocess.run(
        ["git", f"--git-dir={path}", "remote", "update", "--prune"],
        check=True,
    )
    return run_stdout(["git", f"--git-dir={path}", "rev-parse", "refs/heads/main"])


def resolve_automation_inputs(args: argparse.Namespace) -> tuple[Path, Path]:
    configured_root = args.automation_root or automation_root()
    memory_path = args.memory
    mirror_path = args.mirror

    if memory_path is None and configured_root is not None:
        memory_path = default_automation_memory_path(configured_root)
    if mirror_path is None and configured_root is not None:
        mirror_path = default_automation_mirror_path(configured_root)

    if memory_path is None:
        raise RuntimeError(
            "discover-range requires `--memory` or an automation root via `--automation-root`, "
            "`CODEX_DELTAS_AUTOMATION_ROOT`, or `CODEX_AUTOMATION_ROOT`."
        )
    if mirror_path is None:
        raise RuntimeError(
            "discover-range requires `--mirror` or an automation root via `--automation-root`, "
            "`CODEX_DELTAS_AUTOMATION_ROOT`, or `CODEX_AUTOMATION_ROOT`."
        )
    return memory_path, mirror_path


def build_run_context(args: argparse.Namespace) -> tuple[dict[str, object], Path]:
    memory_path, mirror_path = resolve_automation_inputs(args)
    memory = read_markdown_memory(memory_path)
    from_sha = args.from_sha or memory.get("last_reported_origin_main_sha") or None
    if not from_sha:
        raise RuntimeError(
            "discover-range requires a baseline SHA; seed automation memory with "
            "`last_reported_origin_main_sha` or pass `--from-sha`."
        )
    to_sha = ensure_mirror(mirror_path, args.repo_url)
    compare_label = from_sha[:7]
    run_dir = args.artifact_root / to_sha[:7]
    run_dir.mkdir(parents=True, exist_ok=True)
    output = args.output or run_dir / "run-context.json"
    commit_count = int(
        run_stdout(
            ["git", f"--git-dir={mirror_path}", "rev-list", "--count", f"{from_sha}..{to_sha}"]
        )
    )
    range_expr = f"{from_sha}..{to_sha}"

    context = {
        "repo_url": args.repo_url,
        "mirror_path": str(mirror_path),
        "memory_path": str(memory_path),
        "artifact_root": str(args.artifact_root),
        "artifact_dir": str(run_dir),
        "from_sha": from_sha,
        "to_sha": to_sha,
        "to_short_sha": to_sha[:7],
        "compare_label": compare_label,
        "range": range_expr,
        "commit_count": commit_count,
        "range_empty": commit_count == 0,
        "report_path": str(run_dir / f"repo-delta-{compare_label}.md"),
        "config_findings_path": str(run_dir / f"config-findings-{compare_label}.json"),
        "config_summary_path": str(run_dir / "config-orchestration-summary.md"),
        "validation_path": str(run_dir / "validation.md"),
        "repo_findings_path": str(run_dir / "repo-findings.json"),
        "state_update_path": str(run_dir / "state-update.json"),
    }
    return context, output


def main() -> int:
    args = parse_args()
    context, output = build_run_context(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
