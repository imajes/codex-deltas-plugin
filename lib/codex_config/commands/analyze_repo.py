from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze repository changes for a discovered changelog range."
    )
    parser.add_argument("--run-context", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def run_stdout(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, check=True, text=True).stdout


def parse_commits(raw_text: str) -> list[dict[str, str]]:
    commits: list[dict[str, str]] = []
    for record in raw_text.split("\x1e"):
        if not record.strip():
            continue
        sha, author, date, subject, body = (record.rstrip("\n").split("\x1f") + [""])[:5]
        commits.append(
            {
                "sha": sha,
                "author": author,
                "date": date,
                "subject": subject,
                "body": body.strip(),
            }
        )
    return commits


def parse_name_status(raw_text: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        entry: dict[str, str] = {"status": status}
        if status.startswith("R") and len(parts) >= 3:
            entry["previous_path"] = parts[1]
            entry["path"] = parts[2]
        elif len(parts) >= 2:
            entry["path"] = parts[1]
        files.append(entry)
    return files


def parse_numstat(raw_text: str) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        added, deleted, path = line.split("\t", 2)
        stats[path] = {
            "added": 0 if added == "-" else int(added),
            "deleted": 0 if deleted == "-" else int(deleted),
        }
    return stats


def build_repo_findings(context: dict[str, object]) -> dict[str, object]:
    mirror = str(context["mirror_path"])
    from_sha = context.get("from_sha")
    to_sha = str(context["to_sha"])
    range_expr = str(context["range"]) if context.get("range") else None

    if not from_sha or not range_expr:
        return {
            "from_sha": from_sha,
            "to_sha": to_sha,
            "range": range_expr,
            "commit_count": 0,
            "commits": [],
            "changed_files": [],
            "file_stats": {},
        }

    commits_raw = run_stdout(
        [
            "git",
            f"--git-dir={mirror}",
            "log",
            "--reverse",
            "--date=short",
            "--format=%H%x1f%an%x1f%ad%x1f%s%x1f%b%x1e",
            range_expr,
        ]
    )
    changed_files_raw = run_stdout(
        ["git", f"--git-dir={mirror}", "diff", "--name-status", "-M", range_expr]
    )
    numstat_raw = run_stdout(
        ["git", f"--git-dir={mirror}", "diff", "--numstat", range_expr]
    )

    return {
        "from_sha": from_sha,
        "to_sha": to_sha,
        "range": range_expr,
        "commit_count": int(context.get("commit_count") or 0),
        "commits": parse_commits(commits_raw),
        "changed_files": parse_name_status(changed_files_raw),
        "file_stats": parse_numstat(numstat_raw),
    }


def main() -> int:
    args = parse_args()
    context = json.loads(args.run_context.read_text(encoding="utf-8"))
    output = args.output or Path(str(context["repo_findings_path"]))
    findings = build_repo_findings(context)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
