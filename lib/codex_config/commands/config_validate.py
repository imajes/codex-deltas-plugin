from __future__ import annotations

import argparse
from pathlib import Path

from codex_config.shared import InventoryEntry
from codex_config.shared import SECTION_RE
from codex_config.shared import TomlBlock
from codex_config.shared import flatten_toml_paths
from codex_config.shared import load_feature_specs
from codex_config.shared import load_json
from codex_config.shared import parse_key_name
from codex_config.shared import read_text
from codex_config.shared import sort_block_body_lines
from codex_config.shared import sort_block_groups
from codex_config.shared import split_toml_blocks
from codex_config.shared import toml_loads
from codex_config.shared import write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate synced Codex config artifacts.")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--features-lib", type=Path)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layout-only", action="store_true")
    return parser.parse_args()


def find_block(blocks: list[TomlBlock], header: str) -> TomlBlock | None:
    for block in blocks:
        if block.header == header:
            return block
    return None


def parse_active_keys(block: TomlBlock | None) -> dict[str, bool]:
    if block is None:
        return {}
    keys: dict[str, bool] = {}
    for line in block.body_lines:
        if line.lstrip().startswith("#"):
            continue
        key_name = parse_key_name(line)
        if key_name:
            keys[key_name] = toml_loads(line.strip()).get(key_name) is True
    return keys


def flatten_active_toml_paths(path: Path) -> set[str]:
    section_parts: list[str] = []
    keys: set[str] = set()
    for raw_line in read_text(path).splitlines():
        section_match = SECTION_RE.match(raw_line)
        if section_match:
            from codex_config.shared import split_header_path

            section_parts = split_header_path(section_match.group("header"))
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        key_name = parse_key_name(raw_line)
        if key_name:
            if section_parts:
                keys.add(".".join(section_parts + [key_name]))
            else:
                keys.add(key_name)
    return keys


def ensure_sorted(blocks: list[TomlBlock]) -> list[str]:
    failures: list[str] = []
    if [block.header for block in blocks] != [block.header for block in sort_block_groups(blocks)]:
        failures.append("section ordering is not alphabetical")
    for block in blocks:
        normalized = sort_block_body_lines(block.body_lines)
        if normalized != block.body_lines:
            failures.append(f"key ordering/layout drift in [{block.header}]")
    return failures


def validate_section_link_placement(blocks: list[TomlBlock]) -> list[str]:
    failures: list[str] = []
    for block in blocks:
        body = block.body_lines
        for index, line in enumerate(body):
            if line.startswith("# Section link") or line.startswith("# Section links:"):
                if any(other.strip() for other in body[:index]):
                    failures.append(f"section link comments are not first in [{block.header}]")
                break
    return failures


def validate_platform_feature_split(block: TomlBlock | None) -> list[str]:
    if block is None:
        return ["missing [features] block"]
    marker = "# Platform-specific feature flags"
    body = block.body_lines
    if marker not in body:
        return ["[features] is missing platform-specific pseudo-section marker"]
    return []


def validate_runtime_permissions(parsed_runtime, runtime_blocks: list[TomlBlock]) -> list[str]:
    failures: list[str] = []
    if getattr(parsed_runtime, "get", None) is None:
        return failures

    if parsed_runtime.get("default_permissions") != "workspace":
        failures.append('runtime proposal must set `default_permissions = "workspace"`')

    permissions = parsed_runtime.get("permissions")
    if getattr(permissions, "__contains__", None) is not None and "network" in permissions:
        failures.append("runtime proposal still uses [permissions.network]")
    elif find_block(runtime_blocks, "permissions.network") is not None:
        failures.append("runtime proposal still uses [permissions.network]")

    return failures


def main() -> int:
    args = parse_args()
    inventory = {"summary": {}}
    inventory_entries: list[InventoryEntry] = []
    if args.inventory is not None:
        inventory = load_json(args.inventory)
        inventory_entries = [InventoryEntry(**entry) for entry in inventory["entries"]]
    clean_text = read_text(args.clean)
    runtime_text = read_text(args.runtime)
    failures: list[str] = []
    parsed_runtime = None

    try:
        toml_loads(clean_text)
    except Exception as exc:
        failures.append(f"config-CLEAN TOML parse failed: {exc}")
    try:
        parsed_runtime = toml_loads(runtime_text)
    except Exception as exc:
        failures.append(f"proposed runtime TOML parse failed: {exc}")

    clean_root, clean_blocks = split_toml_blocks(clean_text)
    runtime_root, runtime_blocks = split_toml_blocks(runtime_text)
    failures.extend(ensure_sorted(clean_blocks))
    failures.extend(validate_section_link_placement(clean_blocks))
    if not args.layout_only:
        failures.extend(validate_platform_feature_split(find_block(clean_blocks, "features")))

    if not args.layout_only:
        if args.features_lib is None:
            raise SystemExit("--features-lib is required unless --layout-only is set")
        specs = {
            spec.key: spec.default_enabled
            for spec in load_feature_specs(args.features_lib)
            if spec.stage not in {"Removed", "Deprecated"}
        }
        clean_feature_keys = parse_active_keys(find_block(clean_blocks, "features"))
        for key, default_enabled in specs.items():
            if key not in clean_feature_keys:
                failures.append(f"missing canonical feature in clean: {key}")
                continue
            if clean_feature_keys[key] != default_enabled:
                failures.append(f"feature default mismatch in clean: {key}")

        clean_paths = flatten_toml_paths(args.clean)
        clean_active_paths = flatten_active_toml_paths(args.clean)
        runtime_paths = flatten_toml_paths(args.runtime)
        runtime_active_paths = flatten_active_toml_paths(args.runtime)
        for entry in inventory_entries:
            if entry.classification == "removed":
                if entry.path in clean_active_paths:
                    failures.append(f"removed key still present in clean: {entry.path}")
                if entry.path in runtime_active_paths:
                    failures.append(f"removed key still present in runtime proposal: {entry.path}")
            if entry.classification == "legacy":
                if entry.path in clean_active_paths:
                    failures.append(f"legacy key still active in clean: {entry.path}")
                if entry.path in runtime_active_paths:
                    failures.append(f"legacy key still active in runtime proposal: {entry.path}")

        failures.extend(validate_runtime_permissions(parsed_runtime, runtime_blocks))

    summary_lines = [
        "# Config Maintenance Validation",
        "",
        f"- clean: `{args.clean}`",
        f"- runtime: `{args.runtime}`",
        f"- summary: `new={inventory['summary'].get('new', 0)}` "
        f"`pre-schema={inventory['summary'].get('pre-schema', 0)}` "
        f"`legacy={inventory['summary'].get('legacy', 0)}` "
        f"`removed={inventory['summary'].get('removed', 0)}`",
        "",
    ]
    if failures:
        summary_lines.append("## Failures")
        summary_lines.append("")
        for failure in failures:
            summary_lines.append(f"- {failure}")
    else:
        summary_lines.append("## Result")
        summary_lines.append("")
        summary_lines.append("- validation passed")
    write_text(args.output, "\n".join(summary_lines) + "\n")
    print(args.output)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
