from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from codex_config.automation_state import read_markdown_memory, write_markdown_memory


DEFAULT_TIMEZONE = ZoneInfo("America/Chicago")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persist the compact automation state for a codex delta run."
    )
    parser.add_argument("--run-context", type=Path, required=True)
    parser.add_argument("--memory", type=Path)
    parser.add_argument(
        "--mode",
        choices=["success", "report-failure", "mirror-failure"],
        default="success",
    )
    parser.add_argument("--status-note", required=True)
    parser.add_argument("--learnings")
    parser.add_argument("--corrections")
    parser.add_argument("--feedback")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def memory_title(path: Path) -> str:
    return f"{path.parent.name} memory"


def build_state_payload(args: argparse.Namespace, context: dict[str, object]) -> dict[str, str]:
    now_text = datetime.now(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    payload = {
        "repo_url": str(context["repo_url"]),
        "mirror_path": str(context["mirror_path"]),
        "status_note": args.status_note,
    }
    if args.learnings:
        payload["learnings"] = args.learnings
    if args.corrections:
        payload["corrections"] = args.corrections
    if args.feedback:
        payload["feedback"] = args.feedback

    to_sha = str(context["to_sha"])
    range_expr = context.get("range")
    if args.mode in {"success", "report-failure"}:
        payload["last_successful_fetch_origin_main_sha"] = to_sha
        payload["last_successful_fetch_at"] = now_text
    if args.mode == "success":
        payload["last_reported_origin_main_sha"] = to_sha
        if range_expr:
            payload["last_reported_range"] = str(range_expr)
    return payload


def main() -> int:
    args = parse_args()
    context = json.loads(args.run_context.read_text(encoding="utf-8"))
    memory_path = args.memory or Path(str(context["memory_path"]))
    current = read_markdown_memory(memory_path)
    payload = build_state_payload(args, context)
    merged = {**current, **payload}

    state_update_path = Path(str(context["state_update_path"]))
    state_update_path.parent.mkdir(parents=True, exist_ok=True)
    state_update_path.write_text(
        json.dumps({"mode": args.mode, "memory_path": str(memory_path), "fields": merged}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    if args.apply:
        write_markdown_memory(memory_path, memory_title(memory_path), merged)

    print(state_update_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
