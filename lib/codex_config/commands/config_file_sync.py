from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomlkit
except ModuleNotFoundError:
    tomlkit = None

from codex_config.shared import PLATFORM_FEATURE_KEYS
from codex_config.shared import REMOVED_KEYS
from codex_config.shared import ROOT_PINNED_COMMENT
from codex_config.shared import SECTION_RE
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
from codex_config.shared import resolve_schema_ref
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


@dataclass(frozen=True)
class RuntimeAdditionRecord:
    path: str
    status: str
    detail: str
    review_note: str
    target_header: str | None = None
    target_key: str | None = None
    rendered_lines: list[str] | None = None


@dataclass(frozen=True)
class RuntimeAdditionReview:
    added_safe_defaults: list[RuntimeAdditionRecord]
    added_exemplars: list[RuntimeAdditionRecord]
    skipped: list[RuntimeAdditionRecord]

    def to_payload(self) -> dict[str, Any]:
        return {
            "added_safe_defaults": [asdict(item) for item in self.added_safe_defaults],
            "added_exemplars": [asdict(item) for item in self.added_exemplars],
            "skipped": [asdict(item) for item in self.skipped],
        }


EXEMPLAR_BLOCK_COMMENT = (
    "# Example values added by codex-deltas; review and configure before applying."
)
MARKETPLACE_EXAMPLE_SOURCE = "https://example.invalid/example-marketplace.git"
MISSING_DEFAULT = object()
PATH_DESCRIPTION_OVERRIDES = {
    "realtime.transport": "Transport used for realtime conversations.",
    "realtime.type": "Session mode used for realtime conversations.",
    "realtime.version": "Protocol version used for realtime conversations.",
    "realtime.voice": "Voice used for realtime conversations.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthesize Codex config artifacts from config findings.")
    parser.add_argument("--findings", dest="inventory", type=Path)
    parser.add_argument("--features-lib", type=Path)
    parser.add_argument("--legacy-features", type=Path)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--config-clean", type=Path, required=True)
    parser.add_argument("--config-runtime", type=Path, required=True)
    parser.add_argument("--output-clean", type=Path, required=True)
    parser.add_argument("--output-runtime", type=Path, required=True)
    parser.add_argument("--review-output", type=Path)
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
            description=spec.description,
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
            description=canonical_spec.description,
            canonical_key=canonical,
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
            description=spec.description,
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


def flatten_active_toml_paths_from_text(text: str) -> set[str]:
    section_parts: list[str] = []
    keys: set[str] = set()
    for raw_line in text.splitlines():
        section_match = SECTION_RE.match(raw_line)
        if section_match:
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


def has_active_block_header(path: str, blocks: list[TomlBlock]) -> bool:
    for block in blocks:
        if not has_active_assignments(block.body_lines):
            continue
        if block.header == path or block.header.startswith(f"{path}."):
            return True
    return False


def schema_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    merged = dict(target)
    for key, value in source.items():
        if key in {"properties", "patternProperties"} and isinstance(value, dict):
            combined = dict(merged.get(key, {}))
            combined.update(value)
            merged[key] = combined
            continue
        if key == "required" and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*merged.get(key, []), *value]))
            continue
        merged[key] = value
    return merged


def normalize_schema_node(schema: dict[str, Any], node: Any) -> dict[str, Any]:
    resolved = resolve_schema_ref(schema, node)
    if not isinstance(resolved, dict):
        return {}
    merged: dict[str, Any] = {}
    for combiner in ("allOf", "anyOf", "oneOf"):
        children = resolved.get(combiner)
        if isinstance(children, list):
            for child in children:
                merged = schema_merge(merged, normalize_schema_node(schema, child))
    for key, value in resolved.items():
        if key in {"allOf", "anyOf", "oneOf"}:
            continue
        merged = schema_merge(merged, {key: value})
    return merged


def lookup_schema_node(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
    node = normalize_schema_node(schema, schema)
    for part in split_header_path(path):
        properties = node.get("properties")
        if isinstance(properties, dict) and part in properties:
            node = normalize_schema_node(schema, properties[part])
            continue

        pattern_properties = node.get("patternProperties")
        if isinstance(pattern_properties, dict):
            match = None
            for pattern, child in pattern_properties.items():
                if re.fullmatch(pattern, part):
                    match = child
                    break
            if match is not None:
                node = normalize_schema_node(schema, match)
                continue

        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            node = normalize_schema_node(schema, additional)
            continue
        return None
    return node


def schema_type_label(node: dict[str, Any]) -> str:
    enum_values = node.get("enum")
    if isinstance(enum_values, list) and enum_values:
        value_types = {type(value).__name__ for value in enum_values}
        if value_types == {"str"}:
            return "enum<string>"
        return "enum"
    node_type = node.get("type")
    if node_type == "boolean":
        return "bool"
    if node_type == "integer":
        return "int"
    if node_type == "number":
        return "number"
    if node_type == "string":
        return "string"
    if node_type == "object":
        return "table"
    if node_type == "array":
        items = node.get("items")
        if isinstance(items, dict):
            item_type = items.get("type")
            if item_type == "string":
                return "array<string>"
            if item_type == "integer":
                return "array<int>"
            if item_type == "boolean":
                return "array<bool>"
        return "array"
    return "value"


def summarize_schema_description(node: dict[str, Any]) -> str:
    description = node.get("description")
    if not isinstance(description, str) or not description.strip():
        return ""
    normalized = " ".join(description.split())
    parts = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)
    return parts[0].strip()


def render_toml_value(value: Any) -> str | None:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        rendered_items: list[str] = []
        for item in value:
            rendered = render_toml_value(item)
            if rendered is None:
                return None
            rendered_items.append(rendered)
        return "[" + ", ".join(rendered_items) + "]"
    return None


def new_since_label(entry: dict[str, Any]) -> str:
    note = str(entry.get("note", ""))
    sha = extract_new_since(note)
    if sha:
        return f"new since {sha}"
    if entry.get("is_new"):
        return "new since comparison baseline"
    return ""


def resolve_meaningful_description(
    entry: dict[str, Any],
    node: dict[str, Any] | None,
    *,
    description_override: str | None = None,
) -> str:
    description = description_override or str(entry.get("description") or "").strip()
    if not description:
        description = PATH_DESCRIPTION_OVERRIDES.get(str(entry.get("path", "")), "")
    if not description:
        description = summarize_schema_description(node or {})
    note = str(entry.get("note") or "").strip()
    if not description and entry.get("classification") == "pre-schema":
        description = note
    if not description and entry.get("source") == "schema":
        if note == "Schema-modeled dynamic key.":
            description = f"schema-defined dynamic setting for `{entry['path']}`"
        elif note == "Schema-visible current key.":
            description = f"schema-defined setting for `{entry['path']}`"
    if not description:
        raise RuntimeError(f"no meaningful description could be derived for `{entry['path']}`")
    return description


def format_runtime_comment(
    entry: dict[str, Any],
    node: dict[str, Any] | None,
    *,
    status: str,
    description_override: str | None = None,
) -> str:
    schema_node = node or {}
    detail_parts: list[str] = [schema_type_label(schema_node)]
    if status == "safe-default":
        detail_parts.append("proposed safe default")
    else:
        detail_parts.append("example value; review before applying")
    detail_parts.append(
        resolve_meaningful_description(
            entry,
            schema_node,
            description_override=description_override,
        )
    )
    new_since = new_since_label(entry)
    if new_since:
        detail_parts.append(new_since)
    return "; ".join(detail_parts)


def block_has_active_key(block: TomlBlock, key_name: str) -> bool:
    for line in block.body_lines:
        if line.lstrip().startswith("#"):
            continue
        if parse_key_name(line) == key_name:
            return True
    return False


def root_has_active_key(root_lines: list[str], key_name: str) -> bool:
    for line in root_lines:
        if line.lstrip().startswith("#"):
            continue
        if parse_key_name(line) == key_name:
            return True
    return False


def ensure_exemplar_block_comment(block: TomlBlock) -> None:
    prefix: list[str] = []
    body_start = 0
    while body_start < len(block.body_lines):
        line = block.body_lines[body_start]
        if parse_key_name(line):
            break
        prefix.append(line)
        body_start += 1
    if EXEMPLAR_BLOCK_COMMENT in prefix:
        return
    if prefix and prefix[-1] != "":
        prefix.append("")
    prefix.append(EXEMPLAR_BLOCK_COMMENT)
    if body_start < len(block.body_lines):
        prefix.append("")
    block.body_lines = trim_repeated_blank_lines(prefix + block.body_lines[body_start:])


def preferred_enum_value(path: str, enum_values: list[Any]) -> Any | None:
    if not enum_values:
        return None
    last_segment = split_header_path(path)[-1]
    if last_segment == "transport" and "websocket" in enum_values:
        return "websocket"
    if last_segment == "voice" and "alloy" in enum_values:
        return "alloy"
    if last_segment in {"source_type", "type"} and "git" in enum_values:
        return "git"
    return enum_values[0]


def placeholder_value_for_schema(path: str, node: dict[str, Any]) -> Any:
    enum_values = node.get("enum")
    if isinstance(enum_values, list):
        return preferred_enum_value(path, enum_values)
    node_type = node.get("type")
    key_name = split_header_path(path)[-1]
    if node_type == "string":
        if key_name == "source":
            return MARKETPLACE_EXAMPLE_SOURCE
        if key_name == "ref":
            return "main"
        if key_name == "last_updated":
            return None
        if key_name.endswith("_url") or key_name == "url":
            return "https://example.invalid/example"
        if "path" in key_name:
            return "/ABS/PATH/example"
        return None
    if node_type == "array":
        if key_name == "sparse_paths":
            return ["plugins/example"]
    return None


def make_assignment_record(
    entry: dict[str, Any],
    path: str,
    node: dict[str, Any] | None,
    value: Any,
    *,
    status: str,
    description_override: str | None = None,
) -> RuntimeAdditionRecord | None:
    rendered_value = render_toml_value(value)
    if rendered_value is None:
        return None
    parts = split_header_path(path)
    header = ".".join(parts[:-1]) or None
    key_name = parts[-1]
    comment = format_runtime_comment(
        entry,
        node,
        status=status,
        description_override=description_override,
    )
    line = f"{key_name} = {rendered_value}  # {comment}"
    detail = f"`{path}` -> `{rendered_value}` ({comment})"
    review_note = (
        "Added with a safe default."
        if status == "safe-default"
        else "Added as an example value and requires manual review before applying."
    )
    return RuntimeAdditionRecord(
        path=path,
        status=status,
        detail=detail,
        review_note=review_note,
        target_header=header,
        target_key=key_name,
        rendered_lines=[line],
    )


def make_comment_stub_record(
    entry: dict[str, Any],
    path: str,
    node: dict[str, Any] | None,
    *,
    reason: str,
) -> RuntimeAdditionRecord:
    parts = split_header_path(path)
    header = ".".join(parts[:-1]) or None
    key_name = parts[-1]
    schema_node = node or {}
    comment_parts = [
        schema_type_label(schema_node),
        "comment-only review stub",
        "configure manually",
        reason,
    ]
    comment_parts.append(resolve_meaningful_description(entry, schema_node))
    new_since = new_since_label(entry)
    if new_since:
        comment_parts.append(new_since)
    comment = "; ".join(comment_parts)
    line = f"# {key_name} =  # {comment}"
    detail = f"`{path}` surfaced as a comment-only review stub ({comment})"
    return RuntimeAdditionRecord(
        path=path,
        status="exemplar",
        detail=detail,
        review_note="Added as a comment-only stub and requires manual configuration before applying.",
        target_header=header,
        target_key=key_name,
        rendered_lines=[line],
    )


def build_object_exemplar_record(
    schema: dict[str, Any],
    entry: dict[str, Any],
    node: dict[str, Any],
) -> RuntimeAdditionRecord | None:
    target_header = entry["path"]
    body_node = node
    if isinstance(node.get("additionalProperties"), dict):
        body_node = normalize_schema_node(schema, node["additionalProperties"])
        target_header = f"{entry['path']}.example"

    properties = body_node.get("properties")
    if not isinstance(properties, dict) or not properties:
        return None

    rendered_lines: list[str] = []
    comment_only_lines: list[str] = []
    exemplar_prefix = target_header
    for key_name in sorted(properties):
        child_node = normalize_schema_node(schema, properties[key_name])
        child_path = f"{exemplar_prefix}.{key_name}"
        child_entry = dict(entry)
        child_entry["path"] = child_path
        default_value = child_node.get("default", MISSING_DEFAULT)
        if default_value is not MISSING_DEFAULT and default_value is not None and child_node.get("type") != "object":
            record = make_assignment_record(
                child_entry,
                child_path,
                child_node,
                default_value,
                status="exemplar",
            )
            if record is not None and record.rendered_lines:
                rendered_lines.extend(record.rendered_lines)
            continue

        placeholder = placeholder_value_for_schema(child_path, child_node)
        if placeholder is not None:
            record = make_assignment_record(
                child_entry,
                child_path,
                child_node,
                placeholder,
                status="exemplar",
            )
            if record is not None and record.rendered_lines:
                rendered_lines.extend(record.rendered_lines)
            continue

        child_type = schema_type_label(child_node)
        child_description = resolve_meaningful_description({"path": child_path}, child_node)
        comment_only_lines.append(
            f"# configure `{key_name}` ({child_type}) manually; {child_description}; no safe exemplar could be derived"
        )

    if not rendered_lines and not comment_only_lines:
        return None

    description = summarize_schema_description(node)
    detail = f"`[{target_header}]` added as an exemplar"
    if description:
        detail += f" ({description})"
    new_since = new_since_label(entry)
    if new_since:
        detail += f"; {new_since}"
    if comment_only_lines and not rendered_lines:
        detail += "; values intentionally omitted because the schema shape is incomplete"

    return RuntimeAdditionRecord(
        path=entry["path"],
        status="exemplar",
        detail=detail,
        review_note="Added as an exemplar and requires manual configuration before applying.",
        target_header=target_header,
        rendered_lines=[*comment_only_lines, *rendered_lines],
    )


def build_runtime_addition_review(
    inventory_entries: list[dict[str, Any]],
    schema: dict[str, Any],
    runtime_text: str,
) -> RuntimeAdditionReview:
    active_paths = flatten_active_toml_paths_from_text(runtime_text)
    _, runtime_blocks = split_toml_blocks(runtime_text)
    safe_defaults: list[RuntimeAdditionRecord] = []
    exemplars: list[RuntimeAdditionRecord] = []
    skipped: list[RuntimeAdditionRecord] = []

    for entry in sorted(inventory_entries, key=lambda item: item["path"]):
        if entry.get("runtime_policy") != "preserve-or-add":
            continue
        if entry.get("classification") not in {"active", "new", "pre-schema"}:
            continue

        path = entry["path"]
        is_new_entry = bool(entry.get("is_new")) or entry.get("classification") == "new"
        if path in active_paths or has_active_block_header(path, runtime_blocks):
            continue

        if path.startswith("features.") and entry.get("default_value") in {True, False}:
            record = make_assignment_record(
                entry,
                path,
                {"type": "boolean"},
                entry["default_value"],
                status="safe-default",
            )
            if record is not None:
                safe_defaults.append(record)
            continue

        schema_node = lookup_schema_node(schema, path)
        if schema_node is None:
            if entry.get("classification") == "pre-schema":
                exemplars.append(
                    make_comment_stub_record(
                        entry,
                        path,
                        None,
                        reason="not yet modeled in current schema",
                    )
                )
                continue
            raise RuntimeError(f"no current schema metadata was available for `{path}`")

        default_value = schema_node.get("default", MISSING_DEFAULT)
        if default_value is not MISSING_DEFAULT and default_value is not None and schema_node.get("type") != "object":
            record = make_assignment_record(
                entry,
                path,
                schema_node,
                default_value,
                status="safe-default",
            )
            if record is not None:
                safe_defaults.append(record)
                continue

        if not is_new_entry:
            continue

        placeholder = placeholder_value_for_schema(path, schema_node)
        if placeholder is not None and schema_node.get("type") != "object":
            record = make_assignment_record(
                entry,
                path,
                schema_node,
                placeholder,
                status="exemplar",
            )
            if record is not None:
                exemplars.append(record)
                continue

        if schema_node.get("type") == "object" or isinstance(schema_node.get("additionalProperties"), dict):
            record = build_object_exemplar_record(schema, entry, schema_node)
            if record is not None:
                exemplars.append(record)
                continue

        exemplars.append(
            make_comment_stub_record(
                entry,
                path,
                schema_node,
                reason="no safe default or exemplar available",
            )
        )

    return RuntimeAdditionReview(
        added_safe_defaults=safe_defaults,
        added_exemplars=exemplars,
        skipped=skipped,
    )


def apply_runtime_addition_review(
    runtime_text: str,
    review: RuntimeAdditionReview,
) -> str:
    if not review.added_safe_defaults and not review.added_exemplars:
        return runtime_text

    root_lines, runtime_blocks = split_toml_blocks(runtime_text)
    touched_headers: set[str] = set()
    touched_root = False

    for record in review.added_safe_defaults:
        if not record.rendered_lines:
            continue
        if record.target_header is None:
            if record.target_key and root_has_active_key(root_lines, record.target_key):
                continue
            root_lines.extend(record.rendered_lines)
            touched_root = True
            continue
        block = find_block(runtime_blocks, record.target_header)
        if block is None:
            block = TomlBlock(
                header=record.target_header,
                header_line=f"[{record.target_header}]",
                body_lines=[],
            )
            runtime_blocks.append(block)
        if record.target_key and block_has_active_key(block, record.target_key):
            continue
        block.body_lines.extend(record.rendered_lines)
        touched_headers.add(block.header)

    exemplar_headers: set[str] = set()
    for record in review.added_exemplars:
        if not record.rendered_lines or record.target_header is None:
            continue
        block = find_block(runtime_blocks, record.target_header)
        if block is None:
            block = TomlBlock(
                header=record.target_header,
                header_line=f"[{record.target_header}]",
                body_lines=[],
            )
            runtime_blocks.append(block)
        ensure_exemplar_block_comment(block)
        if record.target_key and block_has_active_key(block, record.target_key):
            continue
        for line in record.rendered_lines:
            if line not in block.body_lines:
                block.body_lines.append(line)
        touched_headers.add(block.header)
        exemplar_headers.add(block.header)

    if touched_root:
        root_lines = sort_root_scalar_lines(root_lines, add_root_comment=False)
    for block in runtime_blocks:
        if block.header in touched_headers:
            block.body_lines = sort_block_body_lines(block.body_lines)
            if block.header in exemplar_headers:
                ensure_exemplar_block_comment(block)

    return render_toml_blocks(root_lines, runtime_blocks)


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

    if args.inventory is None or args.features_lib is None or args.legacy_features is None or args.schema is None:
        raise SystemExit(
            "--findings, --features-lib, --legacy-features, and --schema are required unless --layout-only is set"
        )

    inventory = load_json(args.inventory)
    inventory_entries = inventory["entries"]
    entry_map = {entry["path"]: entry for entry in inventory_entries}
    runtime_remove_paths = {
        entry["path"]
        for entry in inventory_entries
        if entry["runtime_policy"] == "remove"
    }
    schema = load_json(args.schema)
    runtime_addition_review = build_runtime_addition_review(
        inventory_entries,
        schema,
        runtime_text,
    )

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
    runtime_output = apply_runtime_addition_review(
        runtime_output,
        runtime_addition_review,
    )
    runtime_output = restore_missing_runtime_reference_blocks(
        runtime_output,
        preserved_runtime_blocks,
    )
    write_text(args.output_runtime, runtime_output)
    if args.review_output is not None:
        write_text(
            args.review_output,
            json.dumps(runtime_addition_review.to_payload(), indent=2, sort_keys=True) + "\n",
        )

    print(args.output_clean)
    print(args.output_runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
