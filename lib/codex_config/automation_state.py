from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


DEFAULT_FIELD_ORDER = [
    "repo_url",
    "mirror_path",
    "last_successful_fetch_origin_main_sha",
    "last_reported_origin_main_sha",
    "last_reported_range",
    "last_successful_fetch_at",
    "status_note",
    "learnings",
    "corrections",
    "feedback",
]


def parse_markdown_memory(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        key, sep, value = line[2:].partition(":")
        if not sep:
            continue
        data[key.strip()] = value.strip()
    return data


def read_markdown_memory(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return parse_markdown_memory(path.read_text(encoding="utf-8"))


def render_markdown_memory(
    title: str,
    data: Mapping[str, str | None],
    *,
    field_order: list[str] | None = None,
) -> str:
    lines = [f"# {title}", ""]
    used: set[str] = set()
    for key in field_order or DEFAULT_FIELD_ORDER:
        value = data.get(key)
        if value is None:
            continue
        lines.append(f"- {key}: {value}")
        used.add(key)
    for key in sorted(k for k in data.keys() if k not in used):
        value = data[key]
        if value is None:
            continue
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def write_markdown_memory(
    path: Path,
    title: str,
    data: Mapping[str, str | None],
    *,
    field_order: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_markdown_memory(title, data, field_order=field_order),
        encoding="utf-8",
    )
