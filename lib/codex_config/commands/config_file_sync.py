from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomlkit
except ModuleNotFoundError:
    tomlkit = None

from codex_config.shared import PLATFORM_FEATURE_KEYS
from codex_config.shared import REMOVED_KEYS
from codex_config.shared import ROOT_PINNED_COMMENT
from codex_config.shared import TomlBlock
from codex_config.shared import build_feature_comment
from codex_config.shared import collect_assignment_groups
from codex_config.shared import codex_home
from codex_config.shared import gather_inline_comment_lookup
from codex_config.shared import extract_new_since
from codex_config.shared import legacy_key_matches
from codex_config.shared import load_feature_specs
from codex_config.shared import load_json
from codex_config.shared import load_legacy_feature_aliases
from codex_config.shared import parse_key_name
from codex_config.shared import read_text
from codex_config.shared import render_toml_blocks
from codex_config.shared import split_header_path
from codex_config.shared import sort_block_body_lines
from codex_config.shared import sort_block_groups
from codex_config.shared import sort_root_scalar_lines
from codex_config.shared import split_toml_blocks
from codex_config.shared import trim_repeated_blank_lines
from codex_config.shared import write_text


@dataclass(frozen=True)
class PreservedRuntimeBlocks:
    ordered_headers: list[str]
    comment_only_blocks: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthesize Codex config artifacts from config findings.")
    parser.add_argument("--findings", dest="inventory", type=Path)
    parser.add_argument("--features-lib", type=Path)
    parser.add_argument("--legacy-features", type=Path)
    parser.add_argument("--config-clean", type=Path, required=True)
    parser.add_argument("--config-runtime", type=Path, required=True)
    parser.add_argument("--output-clean", type=Path, required=True)
    parser.add_argument("--output-runtime", type=Path, required=True)
    parser.add_argument("--layout-only", action="store_true")
    return parser.parse_args()


def find_block(blocks: list[TomlBlock], header: str) -> TomlBlock | None:
    for block in blocks:
        if block.header == header:
            return block
    return None


def replace_or_add_block(blocks: list[TomlBlock], header: str, body_lines: list[str]) -> None:
    existing = find_block(blocks, header)
    if existing is not None:
        existing.body_lines = body_lines
        return
    blocks.append(TomlBlock(header=header, header_line=f"[{header}]", body_lines=body_lines))


def ensure_default_permissions(root_lines: list[str]) -> list[str]:
    output: list[str] = []
    inserted = False
    for line in root_lines:
        if line.strip().startswith("default_permissions"):
            output.append(
                'default_permissions = "workspace"'.ljust(120)
                + "# string; default named permissions profile from `[permissions]`."
            )
            inserted = True
            continue
        output.append(line)
        if line.strip().startswith("sandbox_mode") and not inserted:
            output.append(
                'default_permissions = "workspace"'.ljust(120)
                + "# string; default named permissions profile from `[permissions]`."
            )
            inserted = True
    if not inserted:
        output.extend(
            [
                'default_permissions = "workspace"'.ljust(120)
                + "# string; default named permissions profile from `[permissions]`."
            ]
        )
    if ROOT_PINNED_COMMENT not in output:
        output = [ROOT_PINNED_COMMENT, ""] + output
    return trim_repeated_blank_lines(output)


def comment_out_root_legacy_aliases(root_lines: list[str]) -> list[str]:
    output: list[str] = []
    aliases = {
        "experimental_use_freeform_apply_patch": "# bool; legacy alias for freeform apply_patch.",
        "experimental_use_unified_exec_tool": "# bool; legacy alias for unified exec.",
    }
    seen = set()
    for line in root_lines:
        key_name = parse_key_name(line)
        if key_name in aliases:
            seen.add(key_name)
        if key_name in aliases and not line.lstrip().startswith("#"):
            output.append(f"# {key_name} = false".ljust(120) + aliases[key_name])
            continue
        output.append(line)
    for key_name in sorted(aliases):
        if key_name not in seen:
            output.append(f"# {key_name} = false".ljust(120) + aliases[key_name])
    return output


def make_feature_body(
    section_comments: list[str],
    comment_lookup: dict[str, str],
    specs,
    aliases: dict[str, str],
    entry_map: dict[str, dict],
    *,
    include_links: bool,
) -> list[str]:
    body: list[str] = []
    prefix = list(section_comments)
    if include_links:
        body.extend(prefix)
        if prefix and prefix[-1] != "":
            body.append("")
    active_specs = [spec for spec in specs if spec.stage not in {"Removed", "Deprecated"}]
    deprecated_specs = [spec for spec in specs if spec.stage == "Deprecated"]
    main_lines: list[tuple[str, str]] = []
    platform_lines: list[tuple[str, str]] = []

    for spec in active_specs:
        inventory = entry_map.get(f"features.{spec.key}", {})
        new_since = extract_new_since(inventory.get("note", "")) if inventory.get("is_new") else None
        rendered = build_feature_comment(
            spec.key,
            spec.stage,
            spec.default_enabled,
            comment_lookup,
            new_since=new_since,
        )
        if spec.key in PLATFORM_FEATURE_KEYS:
            platform_lines.append((spec.key, rendered))
        else:
            main_lines.append((spec.key, rendered))

    for legacy_key, canonical in sorted(aliases.items()):
        canonical_is_platform = canonical in PLATFORM_FEATURE_KEYS
        canonical_spec = next(spec for spec in specs if spec.key == canonical)
        rendered = build_feature_comment(
            legacy_key,
            canonical_spec.stage,
            canonical_spec.default_enabled,
            comment_lookup,
            legacy=True,
        )
        if canonical_is_platform:
            platform_lines.append((legacy_key, rendered))
        else:
            main_lines.append((legacy_key, rendered))

    for spec in deprecated_specs:
        rendered = build_feature_comment(
            spec.key,
            spec.stage,
            spec.default_enabled,
            comment_lookup,
            legacy=True,
            legacy_reason="deprecated canonical feature; avoid new use.",
        )
        if spec.key in PLATFORM_FEATURE_KEYS:
            platform_lines.append((spec.key, rendered))
        else:
            main_lines.append((spec.key, rendered))

    for _, rendered in sorted(main_lines, key=lambda item: item[0]):
        body.append(rendered)

    if platform_lines:
        body.extend(["", "# Platform-specific feature flags"])
        for _, rendered in sorted(platform_lines, key=lambda item: item[0]):
            body.append(rendered)
    return body


def build_section_prefix(block: TomlBlock | None) -> list[str]:
    if block is None:
        return []
    prefix: list[str] = []
    for line in block.body_lines:
        if parse_key_name(line):
            break
        prefix.append(line)
    return trim_repeated_blank_lines(prefix)


def clean_generic_block(block: TomlBlock) -> None:
    filtered: list[str] = []
    for line in block.body_lines:
        key_name = parse_key_name(line)
        full_path = f"{block.header}.{key_name}" if key_name else ""
        if full_path in REMOVED_KEYS:
            continue
        if legacy_key_matches(full_path) and not line.lstrip().startswith("#"):
            filtered.append(f"# {line}".rstrip())
            continue
        filtered.append(line)
    block.body_lines = sort_block_body_lines(filtered)


def rename_block_header(blocks: list[TomlBlock], old: str, new: str) -> None:
    block = find_block(blocks, old)
    if block is None:
        return
    block.header = new
    block.header_line = f"[{new}]"


def migrate_runtime_permissions(root_lines: list[str], blocks: list[TomlBlock]) -> list[str]:
    root_lines = ensure_default_permissions(root_lines)
    rename_block_header(blocks, "permissions.network", "permissions.workspace.network")
    return root_lines


def remove_runtime_root_aliases(root_lines: list[str]) -> list[str]:
    return [
        line
        for line in root_lines
        if parse_key_name(line)
        not in {
            "experimental_use_freeform_apply_patch",
            "experimental_use_unified_exec_tool",
        }
    ]


def remove_runtime_lines(block: TomlBlock, keys: set[str]) -> None:
    prefix: list[str] = []
    index = 0
    while index < len(block.body_lines):
        if parse_key_name(block.body_lines[index]):
            break
        prefix.append(block.body_lines[index])
        index += 1
    groups, suffix = collect_assignment_groups(block.body_lines, index)
    filtered = list(prefix)
    for key_name, group in groups:
        if f"{block.header}.{key_name}" in keys:
            continue
        filtered.extend(group)
    filtered.extend(suffix)
    block.body_lines = filtered


def normalize_runtime_features(block: TomlBlock, remove_keys: set[str]) -> None:
    remove_runtime_lines(block, remove_keys)
    block.body_lines = sort_block_body_lines(block.body_lines)


def apply_runtime_removals(blocks: list[TomlBlock], remove_paths: set[str]) -> None:
    for block in blocks:
        remove_runtime_lines(block, remove_paths)
        block.body_lines = sort_block_body_lines(block.body_lines)


def strip_quotes(segment: str) -> str:
    if len(segment) >= 2 and segment[0] == segment[-1] and segment[0] in {'"', "'"}:
        return segment[1:-1]
    return segment


def split_path(path: str) -> list[str]:
    return [strip_quotes(part) for part in split_header_path(path)]


def merge_toml_tables(target, source) -> None:
    for key, value in source.items():
        if key not in target:
            target[key] = value
            continue
        existing = target[key]
        if hasattr(existing, "items") and hasattr(value, "items"):
            merge_toml_tables(existing, value)


def runtime_doc_with_tomlkit(
    runtime_text: str,
    remove_paths: set[str],
):
    if tomlkit is None:
        return None
    document = tomlkit.parse(runtime_text)

    for key_name in (
        "experimental_use_freeform_apply_patch",
        "experimental_use_unified_exec_tool",
    ):
        document.pop(key_name, None)

    if "default_permissions" not in document:
        sandbox_mode = "sandbox_mode" in document
        if sandbox_mode:
            items = list(document.items())
            document.clear()
            for key, value in items:
                document[key] = value
                if key == "sandbox_mode":
                    document["default_permissions"] = "workspace"
        else:
            document["default_permissions"] = "workspace"
    else:
        document["default_permissions"] = "workspace"

    permissions = document.get("permissions")
    if permissions is not None and "network" in permissions:
        network = permissions.pop("network")
        workspace = permissions.get("workspace")
        if workspace is None:
            workspace = tomlkit.table()
            permissions["workspace"] = workspace
        workspace_network = workspace.get("network")
        if workspace_network is None:
            workspace["network"] = network
        else:
            merge_toml_tables(workspace_network, network)

    for path in sorted(remove_paths):
        remove_runtime_doc_path(document, split_path(path))

    return tomlkit.dumps(document)


def remove_runtime_doc_path(node, path_parts: list[str]) -> None:
    if not path_parts:
        return
    if len(path_parts) == 1:
        node.pop(path_parts[0], None)
        return
    child = node.get(path_parts[0])
    if child is None:
        return
    remove_runtime_doc_path(child, path_parts[1:])
    if hasattr(child, "items") and not list(child.items()):
        node.pop(path_parts[0], None)


def has_active_assignments(lines: list[str]) -> bool:
    return any(parse_key_name(line) and not line.lstrip().startswith("#") for line in lines)


def collect_comment_only_reference_blocks(runtime_text: str) -> PreservedRuntimeBlocks:
    _, runtime_blocks = split_toml_blocks(runtime_text)
    ordered_headers = [block.header for block in runtime_blocks]
    preserved: dict[str, str] = {}
    for block in runtime_blocks:
        if has_active_assignments(block.body_lines):
            continue
        preserved[block.header] = "\n".join([block.header_line, *block.body_lines]).rstrip()
    return PreservedRuntimeBlocks(
        ordered_headers=ordered_headers,
        comment_only_blocks=preserved,
    )


def parse_preserved_runtime_block(block_text: str) -> TomlBlock:
    _, blocks = split_toml_blocks(block_text.rstrip() + "\n")
    if len(blocks) != 1:
        raise RuntimeError("expected exactly one preserved runtime block")
    return blocks[0]


def restore_missing_runtime_reference_blocks(
    runtime_text: str,
    preserved_blocks: PreservedRuntimeBlocks,
) -> str:
    if not preserved_blocks.comment_only_blocks:
        return runtime_text
    root_lines, runtime_blocks = split_toml_blocks(runtime_text)
    current_by_header = {block.header: block for block in runtime_blocks}
    ordered_blocks: list[TomlBlock] = []
    consumed_headers: set[str] = set()

    for header in preserved_blocks.ordered_headers:
        current_block = current_by_header.get(header)
        if current_block is not None:
            ordered_blocks.append(current_block)
            consumed_headers.add(header)
            continue
        preserved_text = preserved_blocks.comment_only_blocks.get(header)
        if preserved_text is None:
            continue
        ordered_blocks.append(parse_preserved_runtime_block(preserved_text))
        consumed_headers.add(header)

    for block in runtime_blocks:
        if block.header in consumed_headers:
            continue
        ordered_blocks.append(block)

    return render_toml_blocks(root_lines, ordered_blocks)


def main() -> int:
    args = parse_args()
    clean_root, clean_blocks = split_toml_blocks(read_text(args.config_clean))
    runtime_text = read_text(args.config_runtime)
    runtime_root, runtime_blocks = split_toml_blocks(runtime_text)

    if args.layout_only:
        for block in clean_blocks:
            block.body_lines = sort_block_body_lines(block.body_lines)
        clean_root = sort_root_scalar_lines(clean_root, add_root_comment=False)
        clean_blocks = sort_block_groups(clean_blocks)
        write_text(args.output_clean, render_toml_blocks(clean_root, clean_blocks))
        write_text(args.output_runtime, read_text(args.config_runtime))
        print(args.output_clean)
        print(args.output_runtime)
        return 0

    if args.inventory is None or args.features_lib is None or args.legacy_features is None:
        raise SystemExit("--findings, --features-lib, and --legacy-features are required unless --layout-only is set")

    inventory = load_json(args.inventory)
    inventory_entries = inventory["entries"]
    entry_map = {entry["path"]: entry for entry in inventory_entries}
    runtime_remove_paths = {
        entry["path"]
        for entry in inventory_entries
        if entry["runtime_policy"] == "remove"
    }

    specs = load_feature_specs(args.features_lib)
    aliases = load_legacy_feature_aliases(args.legacy_features, specs)

    feature_block = find_block(clean_blocks, "features")
    profile_feature_block = find_block(clean_blocks, "profiles.example.features")
    feature_comments = gather_inline_comment_lookup(feature_block) if feature_block else {}
    profile_feature_comments = (
        gather_inline_comment_lookup(profile_feature_block)
        if profile_feature_block
        else feature_comments
    )

    replace_or_add_block(
        clean_blocks,
        "features",
        make_feature_body(
            build_section_prefix(feature_block),
            feature_comments,
            specs,
            aliases,
            entry_map,
            include_links=True,
        ),
    )
    replace_or_add_block(
        clean_blocks,
        "profiles.example.features",
        make_feature_body(
            build_section_prefix(profile_feature_block),
            profile_feature_comments,
            specs,
            aliases,
            entry_map,
            include_links=False,
        ),
    )

    rename_block_header(clean_blocks, "permissions.network", "permissions.workspace.network")
    clean_root = ensure_default_permissions(clean_root)
    clean_root = comment_out_root_legacy_aliases(clean_root)

    for header in ("memories", "tools", "profiles.example", "profiles.example.tools"):
        block = find_block(clean_blocks, header)
        if block is not None:
            clean_generic_block(block)

    for block in clean_blocks:
        if block.header in {"features", "profiles.example.features"}:
            continue
        clean_generic_block(block)

    clean_root = sort_root_scalar_lines(clean_root)
    clean_blocks = sort_block_groups(clean_blocks)
    write_text(args.output_clean, render_toml_blocks(clean_root, clean_blocks))

    preserved_runtime_blocks = collect_comment_only_reference_blocks(runtime_text)

    runtime_output = runtime_doc_with_tomlkit(runtime_text, runtime_remove_paths)
    if runtime_output is None:
        runtime_root = migrate_runtime_permissions(runtime_root, runtime_blocks)
        runtime_root = remove_runtime_root_aliases(runtime_root)
        apply_runtime_removals(runtime_blocks, runtime_remove_paths)
        runtime_blocks = sort_block_groups(runtime_blocks)
        runtime_output = render_toml_blocks(runtime_root, runtime_blocks)
    runtime_output = restore_missing_runtime_reference_blocks(
        runtime_output,
        preserved_runtime_blocks,
    )
    write_text(args.output_runtime, runtime_output)

    print(args.output_clean)
    print(args.output_runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
