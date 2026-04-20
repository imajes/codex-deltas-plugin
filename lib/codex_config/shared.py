from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


LEGACY_ALIAS_RE = re.compile(
    r"Alias\s*\{\s*"
    r'legacy_key:\s*"(?P<legacy>[^"]+)",\s*'
    r"feature:\s*Feature::(?P<feature>\w+),",
    re.S,
)
SECTION_RE = re.compile(r"^\s*\[(?P<header>[^\]]+)\]\s*(?:#.*)?$")
KEY_RE = re.compile(r'^\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_-]+))\s*=')
COMMENTED_KEY_RE = re.compile(r'^\s*#\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_-]+))\s*=')

SECTION_LINK_PREFIXES = ("# Section link:", "# Section links:")
HEADER_COMMENT_PREFIXES = SECTION_LINK_PREFIXES + (
    "# Dynamic key pattern:",
    "# Array-of-table pattern",
)
PLATFORM_FEATURE_KEYS = {
    "elevated_windows_sandbox",
    "experimental_windows_sandbox",
    "prevent_idle_sleep",
    "use_legacy_landlock",
    "use_linux_sandbox_bwrap",
}
LEGACY_KEY_PATTERNS = (
    re.compile(r"^experimental_instructions_file$"),
    re.compile(r"^experimental_use_freeform_apply_patch$"),
    re.compile(r"^experimental_use_unified_exec_tool$"),
    re.compile(r"^tools\.web_search$"),
    re.compile(r'^profiles\.[^.]+\.experimental_instructions_file$'),
    re.compile(r'^profiles\.[^.]+\.experimental_use_freeform_apply_patch$'),
    re.compile(r'^profiles\.[^.]+\.experimental_use_unified_exec_tool$'),
    re.compile(r'^profiles\.[^.]+\.include_apply_patch_tool$'),
    re.compile(r'^profiles\.[^.]+\.tools_view_image$'),
    re.compile(r'^profiles\.[^.]+\.tools_web_search$'),
)
REMOVED_KEYS = {
    "agents.max_spawn_depth",
    "features.apps_mcp_gateway",
    "features.powershell_utf8",
    "memories.max_raw_memories_for_global",
    "memories.phase_1_model",
    "memories.phase_2_model",
    "tui.experimental_mode",
}
PRE_SCHEMA_PATTERNS = {
    re.compile(r"^apps\.[^.]+\.disabled_reason$"): {
        "note": "Code-visible app disable reason marker not yet modeled in config schema.",
        "source": "code",
    },
    re.compile(r"^mcp_servers\.[^.]+\.disabled_reason$"): {
        "note": "Code-visible MCP disable reason marker not yet modeled in config schema.",
        "source": "code",
    },
}
DYNAMIC_SCHEMA_SEGMENT_PATTERN = r'(?:[^.]+|"[^"]+"|\'[^\']+\')'
FEATURE_COMMENT_FALLBACK = {
    "Stable": "bool; feature toggle.",
    "Experimental": "bool; experimental feature toggle.",
    "UnderDevelopment": "bool; under-development feature toggle.",
    "Deprecated": "bool; deprecated feature toggle.",
    "Removed": "bool; removed feature toggle.",
}
ROOT_PINNED_COMMENT = (
    "# Pinned top-level startup settings live here on purpose. "
    "Everything after this block is section-sorted alphabetically."
)
NEW_SINCE_RE = re.compile(r"New canonical feature key since (?P<sha>[0-9a-f]{7,40})")
FEATURE_ENTRY_START = "FeatureSpec {"
DEFAULT_REPO_URL = "https://github.com/openai/codex.git"
GENERIC_FEATURE_COMMENTS = {
    "bool; feature toggle.",
    "bool; experimental feature toggle.",
    "bool; under-development feature toggle.",
    "bool; deprecated feature toggle.",
    "bool; removed feature toggle.",
    "legacy alias; prefer canonical feature key.",
}


@dataclass(frozen=True)
class FeatureSpecRecord:
    id_name: str
    key: str
    stage: str
    default_enabled: bool
    description: str


@dataclass
class InventoryEntry:
    path: str
    classification: str
    source: str
    default_value: Any
    clean_policy: str
    runtime_policy: str
    note: str
    migration_target: str | None = None
    is_new: bool = False
    platform_specific: bool = False
    description: str | None = None
    canonical_key: str | None = None


@dataclass(frozen=True)
class PreSchemaHint:
    pattern: re.Pattern[str]
    note: str
    source: str


@dataclass
class TomlBlock:
    header: str
    header_line: str
    body_lines: list[str]


def codex_home() -> Path:
    value = os.environ.get("CODEX_HOME")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".codex"


def automation_root() -> Path | None:
    for key in ("CODEX_DELTAS_AUTOMATION_ROOT", "CODEX_AUTOMATION_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value).expanduser()
    return None


def configured_repo_url(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for key in ("CODEX_DELTAS_REPO_URL", "CODEX_REPO_URL"):
        value = os.environ.get(key)
        if value:
            return value
    return DEFAULT_REPO_URL


def repo_slug(repo_url: str) -> str:
    value = repo_url.strip().rstrip("/")
    if "://" in value:
        path = urlparse(value).path
    elif ":" in value and "/" in value.split(":", 1)[1]:
        path = value.split(":", 1)[1]
    else:
        path = value
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [segment for segment in re.split(r"[\\/]+", path) if segment]
    slug = "-".join(segments[-2:] if len(segments) >= 2 else segments)
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-.")
    return normalized or "repo"


def default_automation_memory_path(root: Path) -> Path:
    return root / "memory.md"


def default_automation_mirror_path(root: Path, repo_url: str) -> Path:
    automation_name = root.name or "codex-automation"
    return Path("/tmp") / automation_name / f"{repo_slug(repo_url)}.git"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def toml_loads(text: str) -> Any:
    return tomllib.loads(text)


def run_git(repo_path: Path, args: list[str], *, git_dir: bool = False) -> str:
    command = ["git"]
    if git_dir:
        command.extend([f"--git-dir={repo_path}"])
    else:
        command.extend(["-C", str(repo_path)])
    command.extend(args)
    completed = subprocess.run(
        command,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout


def git_show_text(repo_path: Path, ref: str, relative_path: str, *, git_dir: bool = False) -> str:
    return run_git(repo_path, ["show", f"{ref}:{relative_path}"], git_dir=git_dir)


def current_platform_tags() -> set[str]:
    platform = os.uname().sysname.lower()
    tags = {platform}
    if platform == "darwin":
        tags.add("macos")
        tags.add("unix")
    elif platform == "linux":
        tags.add("unix")
    elif platform.startswith("win"):
        tags.add("windows")
    return tags


def split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0
    in_quotes = False
    escape = False
    for char in text:
        if in_quotes:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_quotes = False
            continue
        if char == '"':
            in_quotes = True
            current.append(char)
            continue
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        elif (
            char == delimiter
            and paren_depth == 0
            and brace_depth == 0
            and bracket_depth == 0
        ):
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def evaluate_cfg_inner(expression: str) -> bool:
    expr = expression.strip()
    tags = current_platform_tags()
    if expr.startswith("any(") and expr.endswith(")"):
        return any(evaluate_cfg_inner(part) for part in split_top_level(expr[4:-1]))
    if expr.startswith("all(") and expr.endswith(")"):
        return all(evaluate_cfg_inner(part) for part in split_top_level(expr[4:-1]))
    if expr.startswith("not(") and expr.endswith(")"):
        return not evaluate_cfg_inner(expr[4:-1])
    target_os_match = re.fullmatch(r'target_os\s*=\s*"(?P<value>[^"]+)"', expr)
    if target_os_match:
        return target_os_match.group("value") in tags
    return expr in tags


def evaluate_boolean_expression(expression: str) -> bool:
    expr = expression.strip()
    if expr == "true":
        return True
    if expr == "false":
        return False
    if expr.startswith("!"):
        return not evaluate_boolean_expression(expr[1:])
    cfg_match = re.fullmatch(r"cfg!\((?P<inner>.*)\)", expr, re.S)
    if cfg_match:
        return evaluate_cfg_inner(cfg_match.group("inner"))
    raise RuntimeError(f"unsupported boolean expression: {expression}")


def extract_field_expression(block: str, field_name: str) -> str:
    marker = f"{field_name}:"
    start = block.find(marker)
    if start == -1:
        raise RuntimeError(f"missing field {field_name} in FeatureSpec block")
    index = start + len(marker)
    while index < len(block) and block[index].isspace():
        index += 1
    paren_depth = 0
    brace_depth = 0
    bracket_depth = 0
    in_quotes = False
    escape = False
    expression: list[str] = []
    while index < len(block):
        char = block[index]
        if in_quotes:
            expression.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_quotes = False
            index += 1
            continue
        if char == '"':
            in_quotes = True
            expression.append(char)
            index += 1
            continue
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            if brace_depth == 0:
                break
            brace_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        elif (
            char == ","
            and paren_depth == 0
            and brace_depth == 0
            and bracket_depth == 0
        ):
            break
        expression.append(char)
        index += 1
    return "".join(expression).strip()


def extract_braced_block(text: str, start_index: int) -> tuple[str, int]:
    if text[start_index] != "{":
        raise RuntimeError("expected braced block")
    depth = 0
    in_quotes = False
    escape = False
    index = start_index
    while index < len(text):
        char = text[index]
        if in_quotes:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_quotes = False
        else:
            if char == '"':
                in_quotes = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index + 1 : index], index + 1
        index += 1
    raise RuntimeError("unterminated braced block")


def resolve_stage_kind(expression: str) -> str:
    expr = expression.strip()
    stage_match = re.match(r"Stage::(?P<stage>\w+)", expr)
    if stage_match:
        return stage_match.group("stage")
    if expr.startswith("if "):
        condition_start = expr.find("cfg!(")
        then_start = expr.find("{", condition_start)
        if condition_start == -1 or then_start == -1:
            raise RuntimeError(f"unsupported stage expression: {expression}")
        condition = expr[condition_start:then_start].strip()
        then_body, then_end = extract_braced_block(expr, then_start)
        remainder = expr[then_end:].strip()
        if not remainder.startswith("else"):
            raise RuntimeError(f"unsupported stage expression: {expression}")
        else_start = remainder.find("{")
        else_body, _ = extract_braced_block(remainder, else_start)
        return resolve_stage_kind(then_body if evaluate_boolean_expression(condition) else else_body)
    raise RuntimeError(f"unsupported stage expression: {expression}")


def extract_feature_spec_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    index = text.find("pub const FEATURES")
    if index == -1:
        raise RuntimeError("failed to locate FEATURES array")
    search_start = index
    while True:
        start = text.find(FEATURE_ENTRY_START, search_start)
        if start == -1:
            break
        brace_start = text.find("{", start)
        depth = 0
        in_quotes = False
        escape = False
        position = brace_start
        while position < len(text):
            char = text[position]
            if in_quotes:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_quotes = False
            else:
                if char == '"':
                    in_quotes = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        blocks.append(text[start : position + 1])
                        search_start = position + 1
                        break
            position += 1
        else:
            raise RuntimeError("unterminated FeatureSpec block")
    return blocks


def extract_enum_body(text: str, enum_name: str) -> str:
    anchor = f"pub enum {enum_name} {{"
    start = text.find(anchor)
    if start == -1:
        raise RuntimeError(f"failed to locate enum `{enum_name}`")
    position = start + len(anchor)
    depth = 1
    body_start = position
    while position < len(text):
        char = text[position]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[body_start:position]
        position += 1
    raise RuntimeError(f"unterminated enum `{enum_name}`")


def normalize_doc_sentence(text: str) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0].strip()
    if len(sentence) >= 2 and sentence[0].isalpha() and sentence[1].islower():
        sentence = sentence[0].lower() + sentence[1:]
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def parse_feature_descriptions(text: str) -> dict[str, str]:
    body = extract_enum_body(text, "Feature")
    descriptions: dict[str, str] = {}
    pending_docs: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("///"):
            pending_docs.append(line[3:].strip())
            continue
        variant_match = re.match(r"^(?P<name>[A-Z][A-Za-z0-9_]*)\s*,\s*$", line)
        if variant_match:
            name = variant_match.group("name")
            description = normalize_doc_sentence(" ".join(pending_docs))
            if not description:
                raise RuntimeError(f"missing doc comment for Feature::{name}")
            descriptions[name] = description
            pending_docs = []
            continue
        if line and not line.startswith("//"):
            pending_docs = []
    if not descriptions:
        raise RuntimeError("failed to parse any feature descriptions")
    return descriptions


def parse_feature_specs(text: str) -> list[FeatureSpecRecord]:
    descriptions = parse_feature_descriptions(text)
    specs: list[FeatureSpecRecord] = []
    for block in extract_feature_spec_blocks(text):
        id_match = re.search(r"id:\s*Feature::(?P<id>\w+),", block)
        key_match = re.search(r'key:\s*"(?P<key>[^"]+)",', block)
        if not (id_match and key_match):
            raise RuntimeError(f"failed to parse FeatureSpec block:\n{block}")
        feature_id = id_match.group("id")
        description = descriptions.get(feature_id)
        if not description:
            raise RuntimeError(f"missing parsed description for Feature::{feature_id}")
        stage_expression = extract_field_expression(block, "stage")
        default_expression = extract_field_expression(block, "default_enabled")
        specs.append(
            FeatureSpecRecord(
                id_name=feature_id,
                key=key_match.group("key"),
                stage=resolve_stage_kind(stage_expression),
                default_enabled=evaluate_boolean_expression(default_expression),
                description=description,
            )
        )
    if not specs:
        raise RuntimeError("failed to parse any feature specs")
    return specs


def load_feature_specs(features_lib: Path) -> list[FeatureSpecRecord]:
    return parse_feature_specs(read_text(features_lib))


def load_feature_specs_at_ref(repo_path: Path, ref: str, *, git_dir: bool = False) -> list[FeatureSpecRecord]:
    text = git_show_text(repo_path, ref, "codex-rs/features/src/lib.rs", git_dir=git_dir)
    return parse_feature_specs(text)


def load_legacy_feature_aliases(legacy_file: Path, specs: list[FeatureSpecRecord]) -> dict[str, str]:
    spec_by_id = {spec.id_name: spec.key for spec in specs}
    aliases: dict[str, str] = {}
    for match in LEGACY_ALIAS_RE.finditer(read_text(legacy_file)):
        canonical = spec_by_id.get(match.group("feature"))
        if canonical is None:
            continue
        aliases[match.group("legacy")] = canonical
    return aliases


def load_legacy_feature_aliases_at_ref(
    repo_path: Path,
    ref: str,
    specs: list[FeatureSpecRecord],
    *,
    git_dir: bool = False,
) -> dict[str, str]:
    spec_by_id = {spec.id_name: spec.key for spec in specs}
    text = git_show_text(repo_path, ref, "codex-rs/features/src/legacy.rs", git_dir=git_dir)
    aliases: dict[str, str] = {}
    for match in LEGACY_ALIAS_RE.finditer(text):
        canonical = spec_by_id.get(match.group("feature"))
        if canonical is None:
            continue
        aliases[match.group("legacy")] = canonical
    return aliases


def resolve_schema_ref(schema: dict[str, Any], node: Any) -> Any:
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/"):
            current: Any = schema
            for part in ref[2:].split("/"):
                current = current[part]
            merged = dict(current)
            for key, value in node.items():
                if key != "$ref":
                    merged[key] = value
            return merged
    return node


def build_schema_path_index(schema: dict[str, Any]) -> tuple[set[str], list[re.Pattern[str]]]:
    exact_paths: set[str] = set()
    dynamic_patterns: set[str] = set()

    def record_path(
        literal_parts: tuple[str, ...] | None,
        pattern_parts: tuple[str, ...],
        *,
        has_dynamic: bool,
    ) -> None:
        if not pattern_parts:
            return
        if has_dynamic:
            dynamic_patterns.add("^" + r"\.".join(pattern_parts) + "$")
            return
        if literal_parts is not None:
            exact_paths.add(".".join(literal_parts))

    def walk(
        node: Any,
        literal_parts: tuple[str, ...] | None = (),
        pattern_parts: tuple[str, ...] = (),
        *,
        has_dynamic: bool = False,
    ) -> None:
        node = resolve_schema_ref(schema, node)
        if not isinstance(node, dict):
            return
        for combiner in ("allOf", "anyOf", "oneOf"):
            value = node.get(combiner)
            if isinstance(value, list):
                for child in value:
                    walk(
                        child,
                        literal_parts,
                        pattern_parts,
                        has_dynamic=has_dynamic,
                    )
        properties = node.get("properties")
        if isinstance(properties, dict):
            for key, child in properties.items():
                walk(
                    child,
                    None if literal_parts is None else literal_parts + (key,),
                    pattern_parts + (re.escape(key),),
                    has_dynamic=has_dynamic,
                )

        dynamic_children: list[Any] = []
        additional_properties = node.get("additionalProperties")
        if isinstance(additional_properties, dict):
            dynamic_children.append(additional_properties)
        pattern_properties = node.get("patternProperties")
        if isinstance(pattern_properties, dict):
            dynamic_children.extend(pattern_properties.values())
        for child in dynamic_children:
            walk(
                child,
                None,
                pattern_parts + (DYNAMIC_SCHEMA_SEGMENT_PATTERN,),
                has_dynamic=True,
            )

        node_type = node.get("type")
        if pattern_parts and node_type in {"string", "integer", "number", "boolean", "array", "null"}:
            record_path(literal_parts, pattern_parts, has_dynamic=has_dynamic)
        elif pattern_parts and node_type == "object" and (
            node.get("additionalProperties") is not None
            or node.get("patternProperties") is not None
        ):
            record_path(literal_parts, pattern_parts, has_dynamic=has_dynamic)

    walk(schema)
    return exact_paths, [re.compile(pattern) for pattern in sorted(dynamic_patterns)]


def flatten_schema_paths(schema: dict[str, Any]) -> set[str]:
    exact_paths, _ = build_schema_path_index(schema)
    return exact_paths


def schema_path_is_modeled(
    path: str,
    exact_paths: set[str],
    dynamic_patterns: list[re.Pattern[str]],
) -> bool:
    if path in exact_paths:
        return True
    return any(pattern.fullmatch(path) for pattern in dynamic_patterns)


def flatten_toml_paths(path: Path) -> set[str]:
    section_parts: list[str] = []
    keys: set[str] = set()
    for raw_line in read_text(path).splitlines():
        section_match = SECTION_RE.match(raw_line)
        if section_match:
            section_parts = split_header_path(section_match.group("header"))
            continue
        key_name = parse_key_name(raw_line)
        if key_name:
            if section_parts:
                keys.add(".".join(section_parts + [key_name]))
            else:
                keys.add(key_name)
    return keys


def parse_key_name(line: str) -> str | None:
    match = KEY_RE.match(line)
    if match:
        return next((group for group in match.groups() if group is not None), None)
    match = COMMENTED_KEY_RE.match(line)
    if match:
        return next((group for group in match.groups() if group is not None), None)
    return None


def split_header_path(header: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    quote_char = ""
    for char in header:
        if char in {'"', "'"}:
            if in_quotes and char == quote_char:
                in_quotes = False
                quote_char = ""
            elif not in_quotes:
                in_quotes = True
                quote_char = char
            current.append(char)
            continue
        if char == "." and not in_quotes:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def split_toml_blocks(text: str) -> tuple[list[str], list[TomlBlock]]:
    root_lines: list[str] = []
    blocks: list[TomlBlock] = []
    current_block: TomlBlock | None = None
    for line in text.splitlines():
        section_match = SECTION_RE.match(line)
        if section_match:
            pending_prefix: list[str] = []
            if current_block is not None:
                current_block.body_lines, pending_prefix = extract_trailing_header_comment_run(
                    current_block.body_lines
                )
                while current_block.body_lines and current_block.body_lines[-1] == "":
                    current_block.body_lines.pop()
                blocks.append(current_block)
            else:
                root_lines, pending_prefix = extract_trailing_header_comment_run(root_lines)
            current_block = TomlBlock(
                header=section_match.group("header").strip(),
                header_line=line,
                body_lines=list(pending_prefix),
            )
            continue
        if current_block is None:
            root_lines.append(line)
        else:
            current_block.body_lines.append(line)
    if current_block is not None:
        while current_block.body_lines and current_block.body_lines[-1] == "":
            current_block.body_lines.pop()
        blocks.append(current_block)
    while root_lines and root_lines[-1] == "":
        root_lines.pop()
    return root_lines, blocks


def render_toml_blocks(root_lines: list[str], blocks: list[TomlBlock]) -> str:
    output = list(root_lines)
    if output and output[-1] != "":
        output.append("")
    for index, block in enumerate(blocks):
        output.append(block.header_line)
        output.extend(block.body_lines)
        if index != len(blocks) - 1 and (not output or output[-1] != ""):
            output.append("")
    return "\n".join(output).rstrip() + "\n"


def extract_trailing_header_comment_run(lines: list[str]) -> tuple[list[str], list[str]]:
    if not lines:
        return lines, []
    index = len(lines) - 1
    while index >= 0 and (lines[index].strip() == "" or lines[index].lstrip().startswith("#")):
        index -= 1
    trailing = lines[index + 1 :]
    start = None
    for offset, line in enumerate(trailing):
        if line.startswith(HEADER_COMMENT_PREFIXES):
            start = offset
            break
    if start is None:
        return lines, []
    return trim_repeated_blank_lines(lines[: index + 1]), trim_repeated_blank_lines(trailing[start:])


def move_section_link_comments_into_following_block(
    root_lines: list[str],
    blocks: list[TomlBlock],
) -> tuple[list[str], list[TomlBlock]]:
    root_lines, pending = extract_trailing_header_comment_run(root_lines)
    if pending and blocks:
        blocks[0].body_lines = trim_repeated_blank_lines(pending + [""] + blocks[0].body_lines)
    for index in range(len(blocks) - 1):
        body_lines, pending = extract_trailing_header_comment_run(blocks[index].body_lines)
        blocks[index].body_lines = body_lines
        if pending:
            blocks[index + 1].body_lines = trim_repeated_blank_lines(pending + [""] + blocks[index + 1].body_lines)
    return root_lines, blocks


def update_multiline_string_state(line: str, state: str | None) -> str | None:
    delimiter = state
    for token in ('"""', "'''"):
        count = line.count(token)
        if delimiter is None and count % 2 == 1:
            delimiter = token
        elif delimiter == token and count % 2 == 1:
            delimiter = None
    return delimiter


def collect_assignment_groups(lines: list[str], start_index: int = 0) -> tuple[list[tuple[str, list[str]]], list[str]]:
    groups: list[tuple[str, list[str]]] = []
    buffer: list[str] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        key_name = parse_key_name(line)
        if key_name is None:
            buffer.append(line)
            index += 1
            continue
        group = list(buffer)
        buffer = []
        group.append(line)
        depth = 0
        string_delimiter: str | None = None
        if "=" in line:
            rhs = line.split("=", 1)[1]
            rhs_without_comment = rhs.split("#", 1)[0]
            depth += bracket_delta(rhs_without_comment)
            string_delimiter = update_multiline_string_state(rhs_without_comment, None)
        index += 1
        while index < len(lines) and (depth > 0 or string_delimiter is not None):
            continuation = lines[index]
            group.append(continuation)
            if string_delimiter is None:
                depth += bracket_delta(continuation.split("#", 1)[0])
            string_delimiter = update_multiline_string_state(continuation, string_delimiter)
            index += 1
        groups.append((key_name.lower(), group))
    return groups, buffer


def group_sort_key(block: TomlBlock) -> tuple[Any, ...]:
    parts = [part.strip('"').strip("'").lower() for part in split_header_path(block.header)]
    top_level = parts[0] if parts else ""
    return (top_level, len(parts) != 1, parts)


def sort_block_groups(blocks: list[TomlBlock]) -> list[TomlBlock]:
    groups: dict[str, list[TomlBlock]] = defaultdict(list)
    for block in blocks:
        parts = split_header_path(block.header)
        top_level = parts[0] if parts else ""
        groups[top_level].append(block)
    ordered: list[TomlBlock] = []
    for top_level in sorted(groups):
        ordered.extend(sorted(groups[top_level], key=group_sort_key))
    return ordered


def bracket_delta(text: str) -> int:
    depth = 0
    in_quotes = False
    escape = False
    for char in text:
        if in_quotes:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_quotes = False
            continue
        if char == '"':
            in_quotes = True
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
    return depth


def normalize_section_prefix(lines: list[str]) -> list[str]:
    link_lines: list[str] = []
    other_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(SECTION_LINK_PREFIXES):
            link_lines.append(line)
            index += 1
            while index < len(lines):
                follow = lines[index]
                if follow.startswith("# -") or follow.strip() == "":
                    link_lines.append(follow)
                    index += 1
                    continue
                break
            continue
        other_lines.append(line)
        index += 1
    return link_lines + other_lines


def sort_block_body_lines(lines: list[str]) -> list[str]:
    platform_marker = "# Platform-specific feature flags"
    if platform_marker in lines:
        marker_index = lines.index(platform_marker)
        before = trim_repeated_blank_lines(sort_block_body_lines(lines[:marker_index]))
        after = trim_repeated_blank_lines(sort_block_body_lines(lines[marker_index + 1 :]))
        combined = list(before)
        if combined and combined[-1] != "":
            combined.append("")
        combined.append(platform_marker)
        if after:
            combined.extend(after)
        return trim_repeated_blank_lines(combined)

    prefix: list[str] = []
    index = 0
    while index < len(lines):
        if parse_key_name(lines[index]):
            break
        prefix.append(lines[index])
        index += 1
    prefix = normalize_section_prefix(prefix)

    groups, suffix = collect_assignment_groups(lines, index)

    unique_groups: dict[str, list[str]] = {}
    for key, group in groups:
        unique_groups[key] = group

    sorted_lines = list(prefix)
    for key in sorted(unique_groups):
        group = unique_groups[key]
        sorted_lines.extend(group)
    sorted_lines.extend(suffix)
    return trim_repeated_blank_lines(sorted_lines)


def trim_repeated_blank_lines(lines: list[str]) -> list[str]:
    output: list[str] = []
    for line in lines:
        if line == "" and output and output[-1] == "":
            continue
        output.append(line)
    while output and output[-1] == "":
        output.pop()
    return output


def sort_root_scalar_lines(root_lines: list[str], *, add_root_comment: bool = True) -> list[str]:
    preamble: list[str] = []
    index = 0
    while index < len(root_lines):
        if parse_key_name(root_lines[index]):
            break
        preamble.append(root_lines[index])
        index += 1

    groups, suffix = collect_assignment_groups(root_lines, index)
    if add_root_comment and ROOT_PINNED_COMMENT not in preamble:
        preamble = preamble + ([""] if preamble and preamble[-1] != "" else [])
        preamble.extend([ROOT_PINNED_COMMENT, ""])

    unique_groups: dict[str, list[str]] = {}
    for key, group in groups:
        unique_groups[key] = group

    output = trim_repeated_blank_lines(preamble)
    for key in sorted(unique_groups):
        group = unique_groups[key]
        output.extend(group)
    output.extend(suffix)
    return trim_repeated_blank_lines(output)


def dump_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(read_text(path))


def legacy_key_matches(path: str) -> bool:
    return any(pattern.match(path) for pattern in LEGACY_KEY_PATTERNS)


def build_pre_schema_hints(repo_path: Path, *, git_dir: bool = False) -> list[PreSchemaHint]:
    config_files = [
        "codex-rs/core/src/config/mod.rs",
        "codex-rs/core/src/config/profile.rs",
        "codex-rs/core/src/config/types.rs",
        "codex-rs/core/src/config/managed_features.rs",
    ]
    texts: list[str] = []
    for relative_path in config_files:
        try:
            texts.append(git_show_text(repo_path, "HEAD", relative_path, git_dir=git_dir))
        except Exception:
            candidate = repo_path / relative_path
            if candidate.exists():
                texts.append(read_text(candidate))
    combined = "\n".join(texts)
    hints: list[PreSchemaHint] = []

    dynamic_field_patterns: dict[str, tuple[str, ...]] = {
        "approval_mode": (r"^apps\.[^.]+\.tools\.[^.]+\.approval_mode$",),
        "default_tools_approval_mode": (r"^apps\.[^.]+\.default_tools_approval_mode$",),
        "default_tools_enabled": (r"^apps\.[^.]+\.default_tools_enabled$",),
        "disabled_reason": (
            r"^apps\.[^.]+\.disabled_reason$",
            r"^mcp_servers\.[^.]+\.disabled_reason$",
        ),
        "config_file": (r"^agents\.[^.]+\.config_file$",),
        "description": (r"^agents\.[^.]+\.description$",),
        "trust_level": (r'^projects\..+\.trust_level$',),
    }
    for field_name, patterns in dynamic_field_patterns.items():
        if field_name not in combined:
            continue
        for pattern in patterns:
            hints.append(
                PreSchemaHint(
                    pattern=re.compile(pattern),
                    note=f"Code-visible dynamic config field `{field_name}` is not modeled in generated schema.",
                    source="code",
                )
            )

    for pattern, field_names, marker in [
        (
            r"^apps\.[^.]+\.(destructive_enabled|enabled|open_world_enabled)$",
            ("destructive_enabled", "open_world_enabled", "enabled"),
            "AppsConfigToml",
        ),
        (
            r"^apps\.[^.]+\.tools\.[^.]+\.enabled$",
            ("enabled", "tools", "AppToolConfigToml"),
            "AppToolConfigToml",
        ),
        (
            r"^mcp_servers\.[^.]+\.(args|bearer_token|bearer_token_env_var|command|cwd|disabled_tools|enabled|enabled_tools|env_vars|required|scopes|startup_timeout_ms|startup_timeout_sec|tool_timeout_sec|url)$",
            ("args", "command", "enabled"),
            "McpServer",
        ),
        (
            r"^mcp_servers\.[^.]+\.env\.[^.]+$",
            ("env",),
            "env",
        ),
        (
            r"^mcp_servers\.[^.]+\.env_http_headers\.[^.]+$",
            ("env_http_headers",),
            "env_http_headers",
        ),
        (
            r"^mcp_servers\.[^.]+\.http_headers\.[^.]+$",
            ("http_headers",),
            "http_headers",
        ),
        (
            r"^model_providers\.[^.]+\.(base_url|env_key|env_key_instructions|experimental_bearer_token|name|request_max_retries|requires_openai_auth|stream_idle_timeout_ms|stream_max_retries|supports_websockets|websocket_connect_timeout_ms|wire_api)$",
            ("ModelProviderInfo",),
            "ModelProviderInfo",
        ),
        (
            r"^model_providers\.[^.]+\.(env_http_headers|http_headers|query_params)\.[^.]+$",
            ("ModelProviderInfo",),
            "ModelProviderInfo",
        ),
        (
            r"^profiles\.[^.]+\.(approval_policy|approvals_reviewer|chatgpt_base_url|experimental_compact_prompt_file|js_repl_node_module_dirs|js_repl_node_path|model|model_catalog_json|model_instructions_file|model_provider|model_reasoning_effort|model_reasoning_summary|model_verbosity|oss_provider|personality|plan_mode_reasoning_effort|sandbox_mode|service_tier|web_search|zsh_path)$",
            ("ConfigProfile",),
            "ConfigProfile",
        ),
        (
            r"^profiles\.[^.]+\.analytics\.enabled$",
            ("AnalyticsConfigToml",),
            "AnalyticsConfigToml",
        ),
        (
            r"^profiles\.[^.]+\.features\.[^.]+$",
            ("features_schema",),
            "features_schema",
        ),
        (
            r"^profiles\.[^.]+\.tools\.[^.]+$",
            ("ToolsToml",),
            "ToolsToml",
        ),
        (
            r"^profiles\.[^.]+\.windows\.(sandbox|sandbox_private_desktop)$",
            ("WindowsToml",),
            "WindowsToml",
        ),
        (
            r"^shell_environment_policy\.set\.[^.]+$",
            ("shell_environment_policy", "set"),
            "shell_environment_policy.set",
        ),
        (
            r"^plugins\.[^.]+\.(enabled|path)$",
            ("plugins",),
            "plugins",
        ),
        (
            r"^tui\.model_availability_nux$",
            ("model_availability_nux",),
            "model_availability_nux",
        ),
    ]:
        if all(field_name not in combined for field_name in field_names):
            continue
        hints.append(
            PreSchemaHint(
                pattern=re.compile(pattern),
                note=f"Code-visible dynamic config surface related to `{marker}` is not modeled in generated schema.",
                source="code",
            )
        )

    return hints


def classify_non_feature_key(path: str, pre_schema_hints: list[PreSchemaHint]) -> tuple[str, str, str | None]:
    for pattern, metadata in PRE_SCHEMA_PATTERNS.items():
        if pattern.match(path):
            return ("pre-schema", metadata["source"], None)
    for hint in pre_schema_hints:
        if hint.pattern.match(path):
            return ("pre-schema", hint.source, None)
    if legacy_key_matches(path):
        return ("legacy", "compatibility", None)
    if path in REMOVED_KEYS:
        return ("removed", "compatibility", None)
    return ("removed", "compatibility", None)


def build_feature_comment(
    key: str,
    stage: str,
    default_enabled: bool,
    comment_lookup: dict[str, str],
    *,
    legacy: bool = False,
    legacy_reason: str | None = None,
    new_since: str | None = None,
    description: str | None = None,
    canonical_key: str | None = None,
) -> str:
    lookup_comment = comment_lookup.get(key)
    if lookup_comment in GENERIC_FEATURE_COMMENTS:
        lookup_comment = None
    normalized_description = normalize_doc_sentence(description or "") if description else ""
    base = lookup_comment or (f"bool; {normalized_description}" if normalized_description else None)
    if not base:
        raise RuntimeError(f"missing meaningful feature description for `[features].{key}` ({stage})")
    if legacy:
        suffix = legacy_reason
        if canonical_key:
            suffix = f"legacy alias for `[features].{canonical_key}`."
        if suffix:
            return f"# {key} = {'true' if default_enabled else 'false'}".ljust(120) + f"# {base}; {suffix}"
        return f"# {key} = {'true' if default_enabled else 'false'}".ljust(120) + f"# {base}"
    if new_since:
        return f"{key} = {'true' if default_enabled else 'false'}".ljust(120) + f"# {base} # new since {new_since}"
    return f"{key} = {'true' if default_enabled else 'false'}".ljust(120) + f"# {base}"


def gather_inline_comment_lookup(block: TomlBlock) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for line in block.body_lines:
        key_name = parse_key_name(line)
        if not key_name or "#" not in line:
            continue
        comment = line.split("#", 1)[1].strip()
        if comment:
            lookup[key_name] = re.sub(r"\s+#\s+(new since .+|pre-schema)$", "", comment).strip()
    return lookup


def extract_new_since(note: str) -> str | None:
    match = NEW_SINCE_RE.search(note)
    if match:
        return match.group("sha")[:7]
    return None


def classify_special_key(path: str) -> tuple[str, str, str | None]:
    for pattern, metadata in PRE_SCHEMA_PATTERNS.items():
        if pattern.match(path):
            return ("pre-schema", metadata["source"], None)
    if legacy_key_matches(path):
        return ("legacy", "compatibility", None)
    if path in REMOVED_KEYS:
        return ("removed", "compatibility", None)
    return ("unknown", "unclassified", None)


def inventory_summary(entries: list[InventoryEntry]) -> dict[str, int]:
    counts = {"new": 0, "pre-schema": 0, "legacy": 0, "removed": 0, "active": 0}
    for entry in entries:
        counts[entry.classification] = counts.get(entry.classification, 0) + 1
    return counts


def to_inventory_payload(entries: list[InventoryEntry], metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": metadata,
        "summary": inventory_summary(entries),
        "entries": [asdict(entry) for entry in entries],
    }
