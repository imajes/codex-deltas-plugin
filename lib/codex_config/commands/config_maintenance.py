from __future__ import annotations

import argparse
import difflib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from codex_config.shared import automation_root
from codex_config.shared import configured_repo_url
from codex_config.shared import default_automation_mirror_path


CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
DELTA_DIR = CODEX_HOME / "config" / "deltas"
ALIGN_TOOL = CODEX_HOME / "bin" / "align_toml_inline_comments"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Codex delta config orchestration workflow.")
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
    parser.add_argument("--automation-root", type=Path)
    parser.add_argument("--mirror", type=Path)
    parser.add_argument("--repo-url")
    parser.add_argument("--from-sha")
    parser.add_argument("--config-clean", type=Path, default=CODEX_HOME / "config" / "config-CLEAN.toml")
    parser.add_argument("--config-runtime", type=Path, default=CODEX_HOME / "config" / "config.toml")
    return parser.parse_args()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, check=check, text=True)


def run_stdout(command: list[str]) -> str:
    return run(command).stdout.strip()


def render_command(command: list[str]) -> str:
    return shlex.join(command)


def run_stage(stage_results: list[dict[str, object]], name: str, command: list[str]) -> subprocess.CompletedProcess[str]:
    result = run(command, check=False)
    stage_results.append(
        {
            "name": name,
            "command": render_command(command),
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    )
    return result


def ensure_mirror(path: Path, repo_url: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        subprocess.run(
            ["git", "clone", "--mirror", repo_url, str(path)],
            check=True,
        )
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


def resolve_mirror_path(args: argparse.Namespace, repo_url: str) -> Path:
    if args.mirror is not None:
        return args.mirror
    configured_root = args.automation_root or automation_root()
    if configured_root is not None:
        return default_automation_mirror_path(configured_root, repo_url)
    raise RuntimeError(
        "config orchestration requires `--mirror` or an automation root via `--automation-root`, "
        "`CODEX_DELTAS_AUTOMATION_ROOT`, or `CODEX_AUTOMATION_ROOT`."
    )


def materialize_truth_file(git_dir: Path, ref: str, relative_path: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = run_stdout(["git", f"--git-dir={git_dir}", "show", f"{ref}:{relative_path}"])
    output_path.write_text(content, encoding="utf-8")
    return output_path


def materialize_truth_sources(run_dir: Path, git_dir: Path, ref: str) -> dict[str, Path]:
    truth_root = run_dir / "truth-source"
    return {
        "schema": materialize_truth_file(
            git_dir,
            ref,
            "codex-rs/core/config.schema.json",
            truth_root / "codex-rs" / "core" / "config.schema.json",
        ),
        "features_lib": materialize_truth_file(
            git_dir,
            ref,
            "codex-rs/features/src/lib.rs",
            truth_root / "codex-rs" / "features" / "src" / "lib.rs",
        ),
        "legacy_features": materialize_truth_file(
            git_dir,
            ref,
            "codex-rs/features/src/legacy.rs",
            truth_root / "codex-rs" / "features" / "src" / "legacy.rs",
        ),
    }


def script_path(skill: str, relative: str) -> Path:
    return SKILLS_DIR / skill / relative


def align_toml(path: Path) -> subprocess.CompletedProcess[str]:
    column = os.environ.get("CODEX_CONFIG_COMMENT_COLUMN", "120")
    check_result = run(
        [str(ALIGN_TOOL), "--check", "--column", column, str(path)],
        check=False,
    )
    if check_result.returncode == 0:
        return check_result
    return run(
        [str(ALIGN_TOOL), "--column", column, str(path)],
        check=False,
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
    align_result = align_toml(canonical_clean)
    if align_result.returncode != 0:
        raise RuntimeError(
            f"failed to align canonical clean file: {align_result.stderr.strip() or align_result.stdout.strip()}"
        )


def write_placeholder_validation(
    path: Path,
    *,
    clean: Path,
    runtime: Path,
    inventory: dict[str, object],
    failure_stage: str | None,
    failure_message: str,
) -> None:
    summary = inventory.get("summary", {}) if isinstance(inventory, dict) else {}
    lines = [
        "# Config Validation",
        "",
        f"- clean: `{clean}`",
        f"- runtime: `{runtime}`",
        f"- summary: `new={summary.get('new', 0)}` "
        f"`pre-schema={summary.get('pre-schema', 0)}` "
        f"`legacy={summary.get('legacy', 0)}` "
        f"`removed={summary.get('removed', 0)}`",
        "",
        "## Failures",
        "",
        f"- workflow failed before validation{f' during `{failure_stage}`' if failure_stage else ''}",
        f"- {failure_message}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stage_section(lines: list[str], stage_results: list[dict[str, object]]) -> None:
    if not stage_results:
        return
    lines.extend(["## Stages", ""])
    for stage in stage_results:
        lines.append(
            f"- `{stage['name']}` exit `{stage['returncode']}`: `{stage['command']}`"
        )
        if stage["stderr"]:
            lines.append(f"  stderr: `{stage['stderr']}`")
        elif stage["stdout"]:
            lines.append(f"  stdout: `{stage['stdout']}`")
    lines.append("")


def main() -> int:
    args = parse_args()
    DELTA_DIR.mkdir(parents=True, exist_ok=True)
    repo_url = configured_repo_url(args.repo_url)
    mirror_path = resolve_mirror_path(args, repo_url)

    compare_sha = args.from_sha
    current_sha = ensure_mirror(mirror_path, repo_url)
    repo_for_history = mirror_path
    if args.mode != "alpha-sort-only" and not compare_sha:
        raise RuntimeError(
            f"{args.mode} requires `--from-sha` so the workflow always has an explicit "
            "from/to changeset."
        )

    run_dir = DELTA_DIR / current_sha[:7]
    run_dir.mkdir(parents=True, exist_ok=True)
    compare_short = compare_sha[:7] if compare_sha else "current"
    inventory_path = run_dir / f"config-findings-{compare_short}.json"
    clean_output_name = "config-CLEAN-alpha-sorted.toml" if args.mode == "alpha-sort-only" else "config-CLEAN-synced.toml"
    clean_output = run_dir / clean_output_name
    runtime_output = run_dir / "proposed-config.toml"
    validation_output = run_dir / ("validation-layout.md" if args.mode == "alpha-sort-only" else "validation.md")
    baseline_diff = run_dir / ("config-CLEAN-alpha-sort.diff" if args.mode == "alpha-sort-only" else "baseline-vs-runtime.diff")
    proposed_diff = run_dir / ("runtime-proposal.diff" if args.mode == "alpha-sort-only" else "proposed-patch.diff")
    summary_output = run_dir / (
        "layout-summary.md" if args.mode == "alpha-sort-only" else "config-orchestration-summary.md"
    )

    classify = script_path("analyze-config", "scripts/classify_config_keys.py")
    sync = script_path("synthesize-config", "scripts/sync_config_files.py")
    validate = script_path("validate-config", "scripts/validate_config_sync.py")
    truth_sources = None
    if args.mode != "alpha-sort-only":
        truth_sources = materialize_truth_sources(run_dir, mirror_path, current_sha)
        features_lib = truth_sources["features_lib"]
        legacy_features = truth_sources["legacy_features"]
        schema = truth_sources["schema"]

    inventory = {"summary": {}}
    stage_results: list[dict[str, object]] = []
    workflow_failed = False
    failure_stage: str | None = None
    failure_message = ""
    validation_result: subprocess.CompletedProcess[str] | None = None
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
        classify_cmd.append("--git-dir")
        classify_result = run_stage(stage_results, "classify", classify_cmd)
        if classify_result.returncode != 0:
            workflow_failed = True
            failure_stage = "classify"
            failure_message = classify_result.stderr.strip() or classify_result.stdout.strip() or "classification failed"
        else:
            try:
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            except Exception as exc:
                workflow_failed = True
                failure_stage = "classify"
                failure_message = f"failed to parse config findings output: {exc}"
            else:
                sync_cmd.extend(
                    [
                        "--findings",
                        str(inventory_path),
                        "--features-lib",
                        str(features_lib),
                        "--legacy-features",
                        str(legacy_features),
                    ]
                )
                validate_cmd.extend(
                    [
                        "--findings",
                        str(inventory_path),
                        "--features-lib",
                        str(features_lib),
                    ]
                )

    if not workflow_failed:
        sync_result = run_stage(stage_results, "sync", sync_cmd)
        if sync_result.returncode != 0:
            workflow_failed = True
            failure_stage = "sync"
            failure_message = sync_result.stderr.strip() or sync_result.stdout.strip() or "sync failed"

    if not workflow_failed:
        align_clean_result = align_toml(clean_output)
        stage_results.append(
            {
                "name": "align-clean",
                "command": render_command([str(ALIGN_TOOL), "--column", os.environ.get("CODEX_CONFIG_COMMENT_COLUMN", "120"), str(clean_output)]),
                "returncode": align_clean_result.returncode,
                "stdout": align_clean_result.stdout.strip(),
                "stderr": align_clean_result.stderr.strip(),
            }
        )
        if align_clean_result.returncode != 0:
            workflow_failed = True
            failure_stage = "align-clean"
            failure_message = align_clean_result.stderr.strip() or align_clean_result.stdout.strip() or "clean alignment failed"

    if not workflow_failed and args.mode != "alpha-sort-only":
        align_runtime_result = align_toml(runtime_output)
        stage_results.append(
            {
                "name": "align-runtime",
                "command": render_command([str(ALIGN_TOOL), "--column", os.environ.get("CODEX_CONFIG_COMMENT_COLUMN", "120"), str(runtime_output)]),
                "returncode": align_runtime_result.returncode,
                "stdout": align_runtime_result.stdout.strip(),
                "stderr": align_runtime_result.stderr.strip(),
            }
        )
        if align_runtime_result.returncode != 0:
            workflow_failed = True
            failure_stage = "align-runtime"
            failure_message = align_runtime_result.stderr.strip() or align_runtime_result.stdout.strip() or "runtime alignment failed"

    if not workflow_failed:
        validation_result = run_stage(stage_results, "validate", validate_cmd)

    if args.mode == "alpha-sort-only":
        if clean_output.exists():
            write_diff(args.config_clean, clean_output, baseline_diff)
        if runtime_output.exists():
            write_diff(args.config_runtime, runtime_output, proposed_diff)
    else:
        if clean_output.exists():
            write_diff(clean_output, args.config_runtime, baseline_diff)
        if runtime_output.exists():
            write_diff(args.config_runtime, runtime_output, proposed_diff)

    if validation_result is not None and validation_result.returncode == 0 and args.mode != "alpha-sort-only":
        sync_canonical_clean(clean_output, args.config_clean)

    if validation_result is None or not validation_output.exists():
        write_placeholder_validation(
            validation_output,
            clean=clean_output,
            runtime=runtime_output,
            inventory=inventory,
            failure_stage=failure_stage,
            failure_message=(
                failure_message
                or (validation_result.stderr.strip() if validation_result is not None else "")
                or "maintenance workflow failed"
            ),
        )

    validation_exit_code = validation_result.returncode if validation_result is not None else 1

    summary_lines = [
        "# Config Orchestration Summary",
        "",
        f"- mode: `{args.mode}`",
        f"- repo_for_history: `{repo_for_history}`",
        f"- repo_url: `{repo_url}`",
        f"- current_sha: `{current_sha}`",
        f"- compare_sha: `{compare_sha or 'none'}`",
        f"- mirror: `{mirror_path}`",
        f"- artifact_dir: `{run_dir}`",
        f"- classification summary: `new: {inventory['summary'].get('new', 0)}, pre-schema: {inventory['summary'].get('pre-schema', 0)}, legacy: {inventory['summary'].get('legacy', 0)}, removed: {inventory['summary'].get('removed', 0)}`",
        f"- config findings: `{inventory_path if args.mode != 'alpha-sort-only' else 'not generated'}`",
        f"- synchronized clean artifact: `{clean_output}`",
        f"- canonical clean synced: `{'yes' if validation_result is not None and validation_result.returncode == 0 and args.mode != 'alpha-sort-only' else 'no'}`",
        f"- proposed runtime artifact: `{runtime_output}`",
        f"- baseline diff: `{baseline_diff}`",
        f"- proposed patch diff: `{proposed_diff}`",
        f"- validation: `{validation_output}`",
        f"- validation_exit_code: `{validation_exit_code}`",
        "",
    ]
    if workflow_failed:
        summary_lines.extend(
            [
                "## Workflow Failure",
                "",
                f"- stage: `{failure_stage or 'unknown'}`",
                f"- message: `{failure_message or 'maintenance workflow failed'}`",
                "",
            ]
        )
    write_stage_section(summary_lines, stage_results)
    if validation_result is not None and validation_result.stderr.strip():
        summary_lines.extend(["## Validation stderr", "", "```text", validation_result.stderr.strip(), "```", ""])
    summary_lines.extend(validation_output.read_text(encoding="utf-8").rstrip().splitlines())
    summary_output.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(summary_output)
    return validation_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
