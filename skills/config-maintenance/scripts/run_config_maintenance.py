#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
from pathlib import Path


CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
SKILLS_DIR = CODEX_HOME / "skills"
DELTA_DIR = CODEX_HOME / "config" / "deltas"
AUTOMATION_DIR = CODEX_HOME / "automations" / "codex-git-changelog"
MIRROR_PATH = AUTOMATION_DIR / "repos" / "openai-codex.git"
REMOTE_URL = "https://github.com/openai/codex.git"
ALIGN_TOOL = CODEX_HOME / "bin" / "align_toml_inline_comments"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex config maintenance workflow.")
    parser.add_argument(
        "mode",
        choices=[
            "alpha-sort-only",
            "sync-current",
            "prepare-changelog-artifacts",
            "touch-features",
            "repair-runtime",
        ],
        default="sync-current",
        nargs="?",
    )
    parser.add_argument("--repo", type=Path, default=Path("/Users/james/src/artificial_intelligence/codex"))
    parser.add_argument("--mirror", type=Path, default=MIRROR_PATH)
    parser.add_argument("--from-sha")
    parser.add_argument("--config-clean", type=Path, default=CODEX_HOME / "config" / "config-CLEAN.toml")
    parser.add_argument("--config-runtime", type=Path, default=CODEX_HOME / "config" / "config.toml")
    return parser.parse_args()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=check, text=True)


def run_stdout(command: list[str]) -> str:
    return run(command).stdout.strip()


def ensure_mirror(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        subprocess.run(
            ["git", "clone", "--mirror", REMOTE_URL, str(path)],
            check=True,
        )
    else:
        subprocess.run(
            ["git", f"--git-dir={path}", "remote", "set-url", "origin", REMOTE_URL],
            check=True,
        )
    subprocess.run(
        ["git", f"--git-dir={path}", "remote", "update", "--prune"],
        check=True,
    )
    return run_stdout(["git", f"--git-dir={path}", "rev-parse", "refs/heads/main"])


def script_path(skill: str, relative: str) -> Path:
    return SKILLS_DIR / skill / relative


def align_toml(path: Path) -> None:
    column = os.environ.get("CODEX_CONFIG_COMMENT_COLUMN", "120")
    check_result = run(
        [str(ALIGN_TOOL), "--check", "--column", column, str(path)],
        check=False,
    )
    if check_result.returncode == 0:
        return
    subprocess.run(
        [str(ALIGN_TOOL), "--column", column, str(path)],
        check=True,
    )


def write_diff(before: Path, after: Path, output: Path) -> None:
    before_lines = before.read_text(encoding="utf-8").splitlines(keepends=True)
    after_lines = after.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=str(before),
        tofile=str(after),
    )
    output.write_text("".join(diff), encoding="utf-8")


def sync_canonical_clean(versioned_clean: Path, canonical_clean: Path) -> None:
    shutil.copyfile(versioned_clean, canonical_clean)
    align_toml(canonical_clean)


def main() -> int:
    args = parse_args()
    DELTA_DIR.mkdir(parents=True, exist_ok=True)

    compare_sha = args.from_sha
    repo_for_history = args.repo
    current_sha = run_stdout(["git", "-C", str(args.repo), "rev-parse", "HEAD"])
    if args.mode == "prepare-changelog-artifacts":
        current_sha = ensure_mirror(args.mirror)
        repo_for_history = args.mirror

    run_dir = DELTA_DIR / current_sha[:7]
    run_dir.mkdir(parents=True, exist_ok=True)
    compare_short = compare_sha[:7] if compare_sha else "current"
    inventory_path = run_dir / f"config-key-inventory-{compare_short}.json"
    clean_output_name = "config-CLEAN-alpha-sorted.toml" if args.mode == "alpha-sort-only" else "config-CLEAN-synced.toml"
    clean_output = run_dir / clean_output_name
    runtime_output = run_dir / "proposed-config.toml"
    validation_output = run_dir / ("validation-layout.md" if args.mode == "alpha-sort-only" else "validation.md")
    baseline_diff = run_dir / ("config-CLEAN-alpha-sort.diff" if args.mode == "alpha-sort-only" else "baseline-vs-runtime.diff")
    proposed_diff = run_dir / ("runtime-proposal.diff" if args.mode == "alpha-sort-only" else "proposed-patch.diff")
    summary_output = run_dir / ("alpha-sort-summary.md" if args.mode == "alpha-sort-only" else "config-maintenance-summary.md")

    classify = script_path("config-key-lifecycle", "scripts/classify_config_keys.py")
    sync = script_path("config-file-sync", "scripts/sync_config_files.py")
    validate = script_path("config-validate", "scripts/validate_config_sync.py")
    features_lib = args.repo / "codex-rs" / "features" / "src" / "lib.rs"
    legacy_features = args.repo / "codex-rs" / "features" / "src" / "legacy.rs"
    schema = args.repo / "codex-rs" / "core" / "config.schema.json"

    inventory = {"summary": {}}
    sync_cmd = [
        sys.executable,
        str(sync),
        "--config-clean",
        str(args.config_clean),
        "--config-runtime",
        str(args.config_runtime),
        "--output-clean",
        str(clean_output),
        "--output-runtime",
        str(runtime_output),
    ]
    validate_cmd = [
        sys.executable,
        str(validate),
        "--clean",
        str(clean_output),
        "--runtime",
        str(runtime_output),
        "--output",
        str(validation_output),
    ]
    if args.mode == "alpha-sort-only":
        sync_cmd.append("--layout-only")
        validate_cmd.append("--layout-only")
    else:
        classify_cmd = [
            sys.executable,
            str(classify),
            "--repo",
            str(repo_for_history),
            "--schema",
            str(schema),
            "--features-lib",
            str(features_lib),
            "--legacy-features",
            str(legacy_features),
            "--config-clean",
            str(args.config_clean),
            "--config-runtime",
            str(args.config_runtime),
            "--output",
            str(inventory_path),
        ]
        if compare_sha:
            classify_cmd.extend(["--from-sha", compare_sha])
        if args.mode == "prepare-changelog-artifacts":
            classify_cmd.append("--git-dir")
        subprocess.run(classify_cmd, check=True)
        inventory = __import__("json").loads(inventory_path.read_text(encoding="utf-8"))
        sync_cmd.extend(
            [
                "--inventory",
                str(inventory_path),
                "--features-lib",
                str(features_lib),
                "--legacy-features",
                str(legacy_features),
            ]
        )
        validate_cmd.extend(
            [
                "--inventory",
                str(inventory_path),
                "--features-lib",
                str(features_lib),
            ]
        )

    subprocess.run(sync_cmd, check=True)

    align_toml(clean_output)
    if args.mode != "alpha-sort-only":
        align_toml(runtime_output)

    validate_result = run(validate_cmd, check=False)

    if args.mode == "alpha-sort-only":
        write_diff(args.config_clean, clean_output, baseline_diff)
        write_diff(args.config_runtime, runtime_output, proposed_diff)
    else:
        write_diff(clean_output, args.config_runtime, baseline_diff)
        write_diff(args.config_runtime, runtime_output, proposed_diff)

    if validate_result.returncode == 0 and args.mode != "alpha-sort-only":
        sync_canonical_clean(clean_output, args.config_clean)

    summary_lines = [
        "# Config Maintenance Summary",
        "",
        f"- mode: `{args.mode}`",
        f"- repo: `{args.repo}`",
        f"- repo_for_history: `{repo_for_history}`",
        f"- current_sha: `{current_sha}`",
        f"- compare_sha: `{compare_sha or 'none'}`",
        f"- mirror: `{args.mirror}`",
        f"- artifact_dir: `{run_dir}`",
        f"- classification summary: `new: {inventory['summary'].get('new', 0)}, pre-schema: {inventory['summary'].get('pre-schema', 0)}, legacy: {inventory['summary'].get('legacy', 0)}, removed: {inventory['summary'].get('removed', 0)}`",
        f"- inventory: `{inventory_path if args.mode != 'alpha-sort-only' else 'not generated'}`",
        f"- synchronized clean artifact: `{clean_output}`",
        f"- canonical clean synced: `{'yes' if validate_result.returncode == 0 and args.mode != 'alpha-sort-only' else 'no'}`",
        f"- proposed runtime artifact: `{runtime_output}`",
        f"- baseline diff: `{baseline_diff}`",
        f"- proposed patch diff: `{proposed_diff}`",
        f"- validation: `{validation_output}`",
        f"- validation_exit_code: `{validate_result.returncode}`",
        "",
    ]
    if validate_result.stderr.strip():
        summary_lines.extend(["## Validation stderr", "", "```text", validate_result.stderr.strip(), "```", ""])
    summary_lines.extend(validation_output.read_text(encoding="utf-8").rstrip().splitlines())
    summary_output.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(summary_output)
    return validate_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
