from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_config.shared import FeatureSpecRecord
from codex_config.shared import InventoryEntry
from codex_config.shared import build_pre_schema_hints
from codex_config.shared import build_schema_path_index
from codex_config.shared import classify_non_feature_key
from codex_config.shared import codex_home
from codex_config.shared import dump_json
from codex_config.shared import flatten_toml_paths
from codex_config.shared import git_show_text
from codex_config.shared import load_feature_specs
from codex_config.shared import load_feature_specs_at_ref
from codex_config.shared import load_json
from codex_config.shared import load_legacy_feature_aliases
from codex_config.shared import load_legacy_feature_aliases_at_ref
from codex_config.shared import read_text
from codex_config.shared import schema_path_is_modeled
from codex_config.shared import to_inventory_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify Codex config keys.")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--features-lib", type=Path, required=True)
    parser.add_argument("--legacy-features", type=Path, required=True)
    parser.add_argument("--config-clean", type=Path, required=True)
    parser.add_argument("--config-runtime", type=Path, required=True)
    parser.add_argument("--from-sha")
    parser.add_argument("--git-dir", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def build_feature_entries(
    specs: list[FeatureSpecRecord],
    previous_specs: dict[str, FeatureSpecRecord],
    aliases: dict[str, str],
    from_sha: str | None,
) -> list[InventoryEntry]:
    entries: list[InventoryEntry] = []
    specs_by_key = {spec.key: spec for spec in specs}
    for spec in specs:
        classification = "active"
        clean_policy = "active"
        runtime_policy = "preserve-or-add"
        note = f"Feature default comes from FeatureSpec.default_enabled ({spec.stage})."
        if spec.stage == "Removed":
            classification = "removed"
            clean_policy = "omit"
            runtime_policy = "remove"
            note = "Feature is removed in current feature registry."
        elif spec.stage == "Deprecated":
            classification = "legacy"
            clean_policy = "commented"
            runtime_policy = "remove"
            note = "Deprecated canonical feature key; keep comment-only in clean and remove from runtime proposals."
        elif from_sha and spec.key not in previous_specs:
            classification = "new"
            baseline = from_sha[:7] if from_sha else "baseline"
            note = f"New canonical feature key since {baseline} ({spec.stage})."
        entries.append(
            InventoryEntry(
                path=f"features.{spec.key}",
                classification=classification,
                source="feature-registry",
                default_value=spec.default_enabled,
                clean_policy=clean_policy,
                runtime_policy=runtime_policy,
                note=note,
                platform_specific=spec.key
                in {
                    "elevated_windows_sandbox",
                    "experimental_windows_sandbox",
                    "prevent_idle_sleep",
                    "use_legacy_landlock",
                    "use_linux_sandbox_bwrap",
                },
                is_new=classification == "new",
                description=spec.description,
            )
        )
    for legacy_key, canonical in sorted(aliases.items()):
        canonical_spec = specs_by_key[canonical]
        entries.append(
            InventoryEntry(
                path=f"features.{legacy_key}",
                classification="legacy",
                source="feature-registry",
                default_value=False,
                clean_policy="commented",
                runtime_policy="remove",
                note=f"Legacy feature alias for `[features].{canonical}`.",
                migration_target=f"features.{canonical}",
                description=canonical_spec.description,
                canonical_key=canonical,
            )
        )
    return entries


def build_non_feature_entries(
    current_schema: dict,
    schema_paths: set[str],
    schema_dynamic_patterns,
    clean_paths: set[str],
    runtime_paths: set[str],
    previous_schema: dict | None,
    from_schema_paths: set[str],
    from_schema_dynamic_patterns,
    pre_schema_hints,
) -> list[InventoryEntry]:
    all_paths = sorted(schema_paths | clean_paths | runtime_paths)
    entries: list[InventoryEntry] = []
    for path in all_paths:
        if path.startswith("features."):
            continue
        if schema_path_is_modeled(path, schema_paths, schema_dynamic_patterns):
            if from_schema_paths and not schema_path_is_modeled(
                path,
                from_schema_paths,
                from_schema_dynamic_patterns,
            ):
                classification = "new"
                source = "schema"
                migration_target = None
                migration_kind = None
                note = "New schema-visible key since comparison baseline."
            else:
                classification = "active"
                source = "schema"
                migration_target = None
                migration_kind = None
                if path in schema_paths:
                    note = "Schema-visible current key."
                else:
                    note = "Schema-modeled dynamic key."
        else:
            decision = classify_non_feature_key(
                path,
                pre_schema_hints,
                current_schema=current_schema,
                current_schema_paths=schema_paths,
                current_schema_dynamic_patterns=schema_dynamic_patterns,
                previous_schema=previous_schema,
            )
            classification = decision.classification
            source = decision.source
            migration_target = decision.migration_target
            migration_kind = decision.migration_kind
            clean_policy = decision.clean_policy
            runtime_policy = decision.runtime_policy
            note = decision.note
        if schema_path_is_modeled(path, schema_paths, schema_dynamic_patterns):
            clean_policy = "active"
            runtime_policy = "preserve-or-add"
        default_value = None
        entries.append(
            InventoryEntry(
                path=path,
                classification=classification,
                source=source,
                default_value=default_value,
                clean_policy=clean_policy,
                runtime_policy=runtime_policy,
                note=note,
                migration_target=migration_target,
                migration_kind=migration_kind,
                is_new=classification == "new",
            )
        )
    return entries


def main() -> int:
    args = parse_args()
    current_schema = load_json(args.schema)
    current_schema_paths, current_schema_dynamic_patterns = build_schema_path_index(current_schema)
    clean_paths = flatten_toml_paths(args.config_clean)
    runtime_paths = flatten_toml_paths(args.config_runtime)

    current_specs = load_feature_specs(args.features_lib)
    current_aliases = load_legacy_feature_aliases(args.legacy_features, current_specs)
    pre_schema_hints = build_pre_schema_hints(args.repo, git_dir=args.git_dir)

    previous_schema: dict | None = None
    previous_schema_paths: set[str] = set()
    previous_schema_dynamic_patterns = []
    previous_specs: dict[str, FeatureSpecRecord] = {}
    previous_aliases: dict[str, str] = {}
    if args.from_sha:
        previous_schema_text = read_text(args.schema)
        try:
            previous_schema_text = git_show_text(
                args.repo,
                args.from_sha,
                "codex-rs/core/config.schema.json",
                git_dir=args.git_dir,
            )
            previous_schema = json.loads(previous_schema_text)
            previous_schema_paths, previous_schema_dynamic_patterns = build_schema_path_index(previous_schema)
            previous_specs = {
                spec.key: spec
                for spec in load_feature_specs_at_ref(
                    args.repo,
                    args.from_sha,
                    git_dir=args.git_dir,
                )
            }
            previous_aliases = load_legacy_feature_aliases_at_ref(
                args.repo,
                args.from_sha,
                list(previous_specs.values()),
                git_dir=args.git_dir,
            )
        except Exception:
            previous_schema_paths = set()
            previous_schema_dynamic_patterns = []
            previous_specs = {}
            previous_aliases = {}

    feature_entries = build_feature_entries(
        current_specs,
        previous_specs,
        current_aliases,
        args.from_sha,
    )
    non_feature_entries = build_non_feature_entries(
        current_schema,
        current_schema_paths,
        current_schema_dynamic_patterns,
        clean_paths,
        runtime_paths,
        previous_schema,
        previous_schema_paths,
        previous_schema_dynamic_patterns,
        pre_schema_hints,
    )
    payload = to_inventory_payload(
        feature_entries + non_feature_entries,
        {
            "repo": str(args.repo),
            "schema": str(args.schema),
            "config_clean": str(args.config_clean),
            "config_runtime": str(args.config_runtime),
            "from_sha": args.from_sha,
            "feature_count": len(current_specs),
            "legacy_feature_alias_count": len(current_aliases),
            "previous_feature_count": len(previous_specs),
            "previous_alias_count": len(previous_aliases),
        },
    )

    output = args.output
    if output is None:
        output = (
            codex_home()
            / "config"
            / "deltas"
            / "config-findings.json"
        )
    dump_json(output, payload)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
