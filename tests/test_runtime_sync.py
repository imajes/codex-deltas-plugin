from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import tomlkit


REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from codex_config import shared
from codex_config.commands import analyze_repo
from codex_config.commands import config_file_sync as sync_config_files
from codex_config.commands import config_key_lifecycle as classify_config_keys
from codex_config.commands import config_maintenance as run_config_maintenance
from codex_config.commands import config_validate as validate_config_sync
from codex_config.commands import discover_range
from codex_config.commands import update_state


def make_inventory_entry(
    path: str,
    *,
    classification: str = "new",
    runtime_policy: str = "preserve-or-add",
    default_value=None,
    note: str = "New schema-visible key since comparison baseline.",
    source: str = "schema",
    description: str | None = None,
    canonical_key: str | None = None,
) -> dict[str, object]:
    return {
        "path": path,
        "classification": classification,
        "source": source,
        "default_value": default_value,
        "clean_policy": "active",
        "runtime_policy": runtime_policy,
        "note": note,
        "migration_target": None,
        "is_new": classification == "new",
        "platform_specific": False,
        "description": description,
        "canonical_key": canonical_key,
    }


def test_tomlkit_parses_inter_table_comment_as_previous_table_comment_item() -> None:
    doc = tomlkit.parse(
        """
[audio]
microphone = "system"

# Section link: https://example.com/env
[shell_environment_policy]
inherit = "all"
""".strip()
        + "\n"
    )

    audio_table = doc.body[0][1]
    shell_table = doc.body[1][1]

    assert isinstance(audio_table, tomlkit.items.Table)
    assert isinstance(shell_table, tomlkit.items.Table)
    assert audio_table.trivia.comment == ""
    assert shell_table.trivia.comment == ""
    assert isinstance(audio_table.value.body[2][1], tomlkit.items.Comment)
    assert (
        audio_table.value.body[2][1].trivia.comment
        == "# Section link: https://example.com/env"
    )


def test_split_and_render_moves_inter_table_header_comment_under_next_header() -> None:
    source = """
[audio]
microphone = "system"

# Section link: https://example.com/env
[shell_environment_policy]
inherit = "all"
""".strip() + "\n"

    root_lines, blocks = shared.split_toml_blocks(source)
    rendered = shared.render_toml_blocks(root_lines, blocks)

    assert rendered == (
        "[audio]\n"
        'microphone = "system"\n'
        "\n"
        "[shell_environment_policy]\n"
        "# Section link: https://example.com/env\n"
        'inherit = "all"\n'
    )


def test_runtime_doc_with_tomlkit_migrates_permissions_and_removes_keys() -> None:
    runtime_text = """
# top comment
sandbox_mode = "workspace-write"
experimental_use_freeform_apply_patch = true

[permissions.network]
enabled = true
proxy_url = "http://127.0.0.1:8080"

[projects."/tmp/repo"]
trust_level = "trusted"

[profiles.example]
experimental_use_freeform_apply_patch = true
"""

    output = sync_config_files.runtime_doc_with_tomlkit(
        runtime_text,
        {
            "permissions.workspace.network.proxy_url",
            'projects."/tmp/repo".trust_level',
            "profiles.example.experimental_use_freeform_apply_patch",
        },
    )

    assert output is not None
    parsed = tomlkit.parse(output)

    assert parsed["default_permissions"] == "workspace"
    assert "experimental_use_freeform_apply_patch" not in parsed
    assert "network" not in parsed["permissions"]
    assert parsed["permissions"]["workspace"]["network"]["enabled"] is True
    assert "proxy_url" not in parsed["permissions"]["workspace"]["network"]
    assert "profiles" not in parsed
    assert "projects" not in parsed


def test_runtime_doc_with_tomlkit_merges_legacy_network_into_workspace_network() -> None:
    runtime_text = """
sandbox_mode = "workspace-write"
default_permissions = "full-access"

[permissions.network]
enabled = true
proxy_url = "http://legacy-proxy"

[permissions.workspace.network]
enabled = false
allowed_domains = ["example.com"]
"""

    output = sync_config_files.runtime_doc_with_tomlkit(runtime_text, set())

    assert output is not None
    parsed = tomlkit.parse(output)

    assert parsed["default_permissions"] == "workspace"
    assert "network" not in parsed["permissions"]
    assert parsed["permissions"]["workspace"]["network"]["enabled"] is False
    assert parsed["permissions"]["workspace"]["network"]["proxy_url"] == "http://legacy-proxy"
    assert parsed["permissions"]["workspace"]["network"]["allowed_domains"] == ["example.com"]


def test_restore_missing_runtime_reference_blocks_keeps_comment_only_sections() -> None:
    runtime_text = """
web_search = "live"

[tools]
view_image = true

[tools.web_search]
# allowed_domains = ["example.com"]
# context_size = "medium"

# [tools.web_search.location]
# city = "Chicago"

[skills]
# [[skills.config]]
# path = "/ABS/PATH/to/skill"
# enabled = false

# [skills.bundled]
# enabled = true

[ui]
show_line_numbers = true
"""

    preserved_blocks = sync_config_files.collect_comment_only_reference_blocks(runtime_text)
    output = sync_config_files.runtime_doc_with_tomlkit(
        runtime_text,
        {
            "tools.web_search.city",
            "tools.web_search.country",
            "tools.web_search.region",
            "tools.web_search.timezone",
            "skills.enabled",
            "skills.path",
            "skills.bundled.path",
        },
    )

    assert output is not None
    restored = sync_config_files.restore_missing_runtime_reference_blocks(output, preserved_blocks)
    _, restored_blocks = shared.split_toml_blocks(restored)

    assert 'web_search = "live"' in restored
    assert "[tools.web_search]" in restored
    assert '# [tools.web_search.location]' in restored
    assert "[skills]" in restored
    assert "# [[skills.config]]" in restored
    assert "# [skills.bundled]" in restored
    assert [block.header for block in restored_blocks] == [
        "tools",
        "tools.web_search",
        "skills",
        "ui",
    ]


def test_remove_runtime_doc_path_handles_quoted_project_keys() -> None:
    document = tomlkit.parse(
        """
[projects."/tmp/repo"]
trust_level = "trusted"
"""
    )

    sync_config_files.remove_runtime_doc_path(
        document,
        sync_config_files.split_path('projects."/tmp/repo".trust_level'),
    )

    assert "projects" not in document


def test_flatten_active_toml_paths_handles_inline_section_comments(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[shell_environment_policy.set] # hard-set env vars
TERM = "xterm-256color"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert validate_config_sync.flatten_active_toml_paths(config_path) == {
        "shell_environment_policy.set.TERM"
    }


def test_flatten_schema_paths_marks_dynamic_object_parents() -> None:
    schema = {
        "type": "object",
        "properties": {
            "projects": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "trust_level": {"type": "string"},
                    },
                },
            }
        },
    }

    paths = shared.flatten_schema_paths(schema)

    assert "projects" in paths
    assert "projects.trust_level" not in paths


def test_classify_non_feature_key_marks_disabled_reason_as_pre_schema() -> None:
    classification, source, migration_target = shared.classify_non_feature_key(
        "apps.example.disabled_reason",
        [],
    )

    assert classification == "pre-schema"
    assert source == "code"
    assert migration_target is None


def test_build_pre_schema_hints_does_not_blanket_classify_network_family(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(
        shared,
        "git_show_text",
        lambda repo_path, ref, relative_path, git_dir=False: "NetworkToml default_permissions",
    )

    hints = shared.build_pre_schema_hints(repo, git_dir=True)

    assert not any(
        hint.pattern.pattern.startswith(r"^permissions\.[^.]+\.network\.")
        for hint in hints
    )


def test_build_non_feature_entries_keeps_schema_modeled_network_keys_active() -> None:
    schema = {
        "type": "object",
        "properties": {
            "permissions": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "network": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "allowed_domains": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            }
        },
    }

    schema_paths, schema_dynamic_patterns = shared.build_schema_path_index(schema)
    entries = classify_config_keys.build_non_feature_entries(
        schema_paths,
        schema_dynamic_patterns,
        set(),
        {
            "permissions.workspace.network.enabled",
            "permissions.workspace.network.allowed_domains",
        },
        set(),
        [],
        [
            shared.PreSchemaHint(
                pattern=re.compile(
                    r"^permissions\.[^.]+\.network\.(enabled|allowed_domains)$"
                ),
                note="broad network hint",
                source="code",
            )
        ],
    )
    entry_map = {entry.path: entry for entry in entries}

    assert entry_map["permissions.workspace.network.enabled"].classification == "active"
    assert entry_map["permissions.workspace.network.enabled"].source == "schema"
    assert (
        entry_map["permissions.workspace.network.enabled"].note
        == "Schema-modeled dynamic key."
    )
    assert (
        entry_map["permissions.workspace.network.allowed_domains"].classification
        == "active"
    )


def test_build_non_feature_entries_marks_dynamic_schema_paths_active() -> None:
    schema = {
        "type": "object",
        "properties": {
            "agents": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "config_file": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            }
        },
    }

    schema_paths, schema_dynamic_patterns = shared.build_schema_path_index(schema)
    entries = classify_config_keys.build_non_feature_entries(
        schema_paths,
        schema_dynamic_patterns,
        set(),
        {"agents.default.config_file", "agents.explorer.description"},
        set(),
        [],
        [],
    )
    entry_map = {entry.path: entry for entry in entries}

    assert entry_map["agents.default.config_file"].classification == "active"
    assert entry_map["agents.default.config_file"].source == "schema"
    assert entry_map["agents.default.config_file"].note == "Schema-modeled dynamic key."
    assert entry_map["agents.explorer.description"].classification == "active"


def test_validate_runtime_permissions_requires_workspace_profile_and_new_shape() -> None:
    runtime = tomlkit.parse(
        """
default_permissions = "full-access"

[permissions.network]
enabled = true
"""
    )
    runtime_root, runtime_blocks = shared.split_toml_blocks(tomlkit.dumps(runtime))

    assert 'default_permissions = "full-access"' in runtime_root
    assert validate_config_sync.validate_runtime_permissions(runtime, runtime_blocks) == [
        'runtime proposal must set `default_permissions = "workspace"`',
        "runtime proposal still uses [permissions.network]",
    ]


def test_runtime_additions_preserve_removals_and_add_safe_defaults_and_exemplars() -> None:
    runtime_text = """
sandbox_mode = "workspace-write"
experimental_use_freeform_apply_patch = true

[features]
existing_feature = true
""".strip() + "\n"

    schema = {
        "type": "object",
        "properties": {
            "tui": {
                "type": "object",
                "properties": {
                    "notification_condition": {
                        "type": "string",
                        "default": "unfocused",
                        "description": "Controls when notifications are delivered.",
                    }
                },
            },
            "marketplaces": {
                "type": "object",
                "default": {},
                "description": "User-level marketplace entries keyed by marketplace name.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "source_type": {
                            "type": "string",
                            "enum": ["git"],
                            "description": "Source kind used to install this marketplace.",
                        },
                        "source": {
                            "type": "string",
                            "description": "Source location used when the marketplace was added.",
                        },
                        "ref": {
                            "type": "string",
                            "description": "Git ref to check out when `source_type` is `git`.",
                        },
                        "sparse_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Sparse checkout paths used when `source_type` is `git`.",
                        },
                    },
                },
            },
            "realtime": {
                "type": "object",
                "properties": {
                    "transport": {
                        "type": "string",
                        "enum": ["webrtc", "websocket"],
                    },
                    "voice": {
                        "type": "string",
                        "enum": ["alloy", "verse"],
                    },
                },
            },
        },
    }
    inventory_entries = [
        make_inventory_entry(
            "experimental_use_freeform_apply_patch",
            classification="removed",
            runtime_policy="remove",
            note="Removed from current config model; should not stay in either file.",
            source="compatibility",
        ),
        make_inventory_entry(
            "features.workspace_dependencies",
            default_value=True,
            note="New canonical feature key since 2250fdd (UnderDevelopment).",
            source="feature-registry",
            description="enable workspace dependency support.",
        ),
        make_inventory_entry("tui.notification_condition"),
        make_inventory_entry("marketplaces"),
        make_inventory_entry("realtime.transport"),
        make_inventory_entry("realtime.voice"),
    ]

    runtime_without_removed = sync_config_files.runtime_doc_with_tomlkit(
        runtime_text,
        {"experimental_use_freeform_apply_patch"},
    )
    assert runtime_without_removed is not None

    review = sync_config_files.build_runtime_addition_review(
        inventory_entries,
        schema,
        runtime_without_removed,
    )
    proposed = sync_config_files.apply_runtime_addition_review(runtime_without_removed, review)

    assert "experimental_use_freeform_apply_patch" not in proposed
    assert (
        "workspace_dependencies = true  # bool; proposed safe default; "
        "enable workspace dependency support.; new since 2250fdd"
    ) in proposed
    assert 'notification_condition = "unfocused"' in proposed
    assert "[marketplaces.example]" in proposed
    assert sync_config_files.EXEMPLAR_BLOCK_COMMENT in proposed
    assert 'source_type = "git"' in proposed
    assert 'source = "https://example.invalid/example-marketplace.git"' in proposed
    assert "[realtime]" in proposed
    assert 'transport = "websocket"' in proposed
    assert 'voice = "alloy"' in proposed
    assert [item.path for item in review.added_safe_defaults] == [
        "features.workspace_dependencies",
        "tui.notification_condition",
    ]
    assert [item.path for item in review.added_exemplars] == [
        "marketplaces",
        "realtime.transport",
        "realtime.voice",
    ]


def test_runtime_additions_fail_when_no_meaningful_description_can_be_derived() -> None:
    schema = {
        "type": "object",
        "properties": {
            "realtime": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                },
            }
        },
    }

    with pytest.raises(RuntimeError, match="realtime.mode"):
        sync_config_files.build_runtime_addition_review(
            [make_inventory_entry("realtime.mode")],
            schema,
            'sandbox_mode = "workspace-write"\n',
        )


def test_runtime_additions_pre_schema_without_schema_metadata_become_comment_stub() -> None:
    schema = {
        "type": "object",
        "properties": {
            "apps": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                    },
                },
            }
        },
    }

    review = sync_config_files.build_runtime_addition_review(
        [
            make_inventory_entry(
                "apps.example_connector.disabled_reason",
                classification="pre-schema",
                source="code",
                note="Code-visible app disable reason marker not yet modeled in config schema.",
            )
        ],
        schema,
        'sandbox_mode = "workspace-write"\n',
    )

    assert [item.path for item in review.added_exemplars] == [
        "apps.example_connector.disabled_reason",
    ]
    assert (
        "Code-visible app disable reason marker not yet modeled in config schema."
        in review.added_exemplars[0].detail
    )
    assert review.added_exemplars[0].rendered_lines == [
        "# disabled_reason =  # value; comment-only review stub; configure manually; "
        "not yet modeled in current schema; Code-visible app disable reason marker not yet modeled in config schema."
    ]


def test_runtime_additions_skip_existing_quoted_dotted_key() -> None:
    schema = {
        "type": "object",
        "properties": {
            "notice": {
                "type": "object",
                "properties": {
                    "hide_gpt-5.1-codex-max_migration_prompt": {
                        "type": "boolean",
                        "default": False,
                        "description": "ack gpt-5.1-codex-max migration prompt.",
                    }
                },
            }
        },
    }

    review = sync_config_files.build_runtime_addition_review(
        [
            make_inventory_entry(
                "notice.hide_gpt-5.1-codex-max_migration_prompt",
                classification="active",
                note="Schema-visible current key.",
            )
        ],
        schema,
        '[notice]\n"hide_gpt-5.1-codex-max_migration_prompt" = true\n',
    )

    assert review.added_safe_defaults == []
    assert review.added_exemplars == []
    assert review.skipped == []


def test_runtime_additions_dynamic_schema_key_without_description_uses_schema_fallback() -> None:
    schema = {
        "type": "object",
        "properties": {
            "plugins": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "default": True,
                        }
                    },
                },
            }
        },
    }

    review = sync_config_files.build_runtime_addition_review(
        [
            make_inventory_entry(
                "plugins.example.enabled",
                classification="active",
                source="schema",
                note="Schema-modeled dynamic key.",
            )
        ],
        schema,
        'sandbox_mode = "workspace-write"\n',
    )

    assert [item.path for item in review.added_safe_defaults] == ["plugins.example.enabled"]
    assert (
        "schema-defined dynamic setting for `plugins.example.enabled`"
        in review.added_safe_defaults[0].detail
    )


def test_build_feature_comment_for_legacy_alias_includes_description_and_canonical_key() -> None:
    rendered = shared.build_feature_comment(
        "telepathy",
        "UnderDevelopment",
        False,
        {},
        legacy=True,
        description="Enable the Chronicle sidecar for passive screen-context memories.",
        canonical_key="chronicle",
    )

    assert (
        "# bool; enable the Chronicle sidecar for passive screen-context memories.; "
        "legacy alias for `[features].chronicle`."
    ) in rendered


def test_parse_active_keys_ignores_comment_text_when_reading_false() -> None:
    block = shared.TomlBlock(
        header="features",
        header_line="[features]",
        body_lines=[
            'feature_a = false  # this comment mentions true but should stay false',
            "feature_b = true",
        ],
    )

    assert validate_config_sync.parse_active_keys(block) == {
        "feature_a": False,
        "feature_b": True,
    }


def test_run_config_maintenance_writes_summary_artifacts_on_classify_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clean = tmp_path / "config-CLEAN.toml"
    runtime = tmp_path / "config.toml"
    clean.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
    runtime.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    delta_dir = tmp_path / "deltas"
    skills_dir = tmp_path / "skills"
    mirror = tmp_path / "mirror.git"

    monkeypatch.setattr(run_config_maintenance, "DELTA_DIR", delta_dir)
    monkeypatch.setattr(run_config_maintenance, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(run_config_maintenance, "ALIGN_TOOL", tmp_path / "align_toml_inline_comments")
    monkeypatch.setattr(
        run_config_maintenance,
        "parse_args",
        lambda: argparse.Namespace(
            mode="sync-current",
            automation_root=None,
            mirror=mirror,
            repo_url="https://github.com/openai/codex.git",
            from_sha="1234567890abcdef",
            config_clean=clean,
            config_runtime=runtime,
        ),
    )
    monkeypatch.setattr(
        run_config_maintenance,
        "ensure_mirror",
        lambda path, repo_url: "abcdef1234567890",
    )
    monkeypatch.setattr(
        run_config_maintenance,
        "materialize_truth_sources",
        lambda run_dir, git_dir, ref: {
            "schema": tmp_path / "config.schema.json",
            "features_lib": tmp_path / "lib.rs",
            "legacy_features": tmp_path / "legacy.rs",
        },
    )
    (tmp_path / "config.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (tmp_path / "lib.rs").write_text("features", encoding="utf-8")
    (tmp_path / "legacy.rs").write_text("legacy", encoding="utf-8")

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        command_text = " ".join(command)
        if "classify_config_keys.py" in command_text:
            return subprocess.CompletedProcess(command, 1, "", "classification exploded")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_config_maintenance, "run", fake_run)

    exit_code = run_config_maintenance.main()

    run_dir = delta_dir / "abcdef1"
    validation_output = run_dir / "validation.md"
    summary_output = run_dir / "config-orchestration-summary.md"

    assert exit_code == 1
    assert validation_output.exists()
    assert summary_output.exists()
    assert "workflow failed before validation during `classify`" in validation_output.read_text(encoding="utf-8")
    summary_text = summary_output.read_text(encoding="utf-8")
    assert "- stage: `classify`" in summary_text
    assert "classification exploded" in summary_text


def test_run_config_maintenance_summary_includes_runtime_additions_review_section(
    tmp_path: Path,
    monkeypatch,
) -> None:
    clean = tmp_path / "config-CLEAN.toml"
    runtime = tmp_path / "config.toml"
    clean.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
    runtime.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    delta_dir = tmp_path / "deltas"
    skills_dir = tmp_path / "skills"
    mirror = tmp_path / "mirror.git"
    schema_path = tmp_path / "config.schema.json"
    features_path = tmp_path / "lib.rs"
    legacy_path = tmp_path / "legacy.rs"
    schema_path.write_text('{"type":"object"}', encoding="utf-8")
    features_path.write_text("features", encoding="utf-8")
    legacy_path.write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(run_config_maintenance, "DELTA_DIR", delta_dir)
    monkeypatch.setattr(run_config_maintenance, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(run_config_maintenance, "ALIGN_TOOL", tmp_path / "align_toml_inline_comments")
    monkeypatch.setattr(
        run_config_maintenance,
        "parse_args",
        lambda: argparse.Namespace(
            mode="sync-current",
            automation_root=None,
            mirror=mirror,
            repo_url="https://github.com/openai/codex.git",
            from_sha="1234567890abcdef",
            config_clean=clean,
            config_runtime=runtime,
        ),
    )
    monkeypatch.setattr(
        run_config_maintenance,
        "ensure_mirror",
        lambda path, repo_url: "abcdef1234567890",
    )
    monkeypatch.setattr(
        run_config_maintenance,
        "materialize_truth_sources",
        lambda run_dir, git_dir, ref: {
            "schema": schema_path,
            "features_lib": features_path,
            "legacy_features": legacy_path,
        },
    )

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        command_text = " ".join(command)
        if "classify_config_keys.py" in command_text:
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                '{"summary":{"new":3,"pre-schema":0,"legacy":0,"removed":0},"entries":[]}',
                encoding="utf-8",
            )
        elif "sync_config_files.py" in command_text:
            clean_output = Path(command[command.index("--output-clean") + 1])
            runtime_output = Path(command[command.index("--output-runtime") + 1])
            review_output = Path(command[command.index("--review-output") + 1])
            clean_output.parent.mkdir(parents=True, exist_ok=True)
            clean_output.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
            runtime_output.write_text('default_permissions = "workspace"\n', encoding="utf-8")
            review_output.write_text(
                json.dumps(
                    {
                        "added_safe_defaults": [
                            {
                                "path": "features.telepathy",
                                "detail": "`features.telepathy` -> `false`",
                                "review_note": "Added with a safe default.",
                            }
                        ],
                        "added_exemplars": [
                            {
                                "path": "marketplaces",
                                "detail": "`[marketplaces.example]` added as an exemplar",
                                "review_note": "Added as an exemplar and requires manual configuration before applying.",
                            },
                            {
                                "path": "realtime.mode",
                                "detail": "`realtime.mode` surfaced as a comment-only review stub",
                                "review_note": "Added as a comment-only stub and requires manual configuration before applying.",
                            }
                        ],
                        "skipped": [],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        elif "validate_config_sync.py" in command_text:
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("# Config Validation\n\n## Result\n\n- validation passed\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_config_maintenance, "run", fake_run)

    exit_code = run_config_maintenance.main()

    summary_text = (delta_dir / "abcdef1" / "config-orchestration-summary.md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert "## Runtime Additions Requiring Review" in summary_text
    assert "### Added with safe defaults" in summary_text
    assert "### Added as exemplars and requiring manual configuration" in summary_text
    assert "### Skipped because defaults or exemplars were too ambiguous" in summary_text
    assert "`features.telepathy`" in summary_text
    assert "`marketplaces`" in summary_text
    assert "`realtime.mode`" in summary_text


def test_materialize_truth_sources_reads_exact_ref_from_mirror(tmp_path: Path, monkeypatch) -> None:
    mirror = tmp_path / "mirror.git"
    run_dir = tmp_path / "run"
    expected = {
        "codex-rs/core/config.schema.json": '{"type":"object"}',
        "codex-rs/features/src/lib.rs": "pub const FEATURES: &[FeatureSpec] = &[];",
        "codex-rs/features/src/legacy.rs": "pub const LEGACY: &[Alias] = &[];",
    }

    def fake_run_stdout(command: list[str]) -> str:
        assert command[:2] == ["git", f"--git-dir={mirror}"]
        _, _, _, show_spec = command
        ref, relative_path = show_spec.split(":", 1)
        assert ref == "abcdef1234567890"
        return expected[relative_path]

    monkeypatch.setattr(run_config_maintenance, "run_stdout", fake_run_stdout)

    truth_sources = run_config_maintenance.materialize_truth_sources(
        run_dir,
        mirror,
        "abcdef1234567890",
    )

    assert truth_sources["schema"].read_text(encoding="utf-8") == expected["codex-rs/core/config.schema.json"]
    assert truth_sources["features_lib"].read_text(encoding="utf-8") == expected["codex-rs/features/src/lib.rs"]
    assert truth_sources["legacy_features"].read_text(encoding="utf-8") == expected["codex-rs/features/src/legacy.rs"]


def test_prepare_changelog_artifacts_uses_materialized_mirror_truth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mirror = tmp_path / "mirror.git"
    clean = tmp_path / "config-CLEAN.toml"
    runtime = tmp_path / "config.toml"
    clean.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
    runtime.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    delta_dir = tmp_path / "deltas"
    skills_dir = tmp_path / "skills"
    truth_root = tmp_path / "materialized-truth"
    truth_root.mkdir()
    schema_path = truth_root / "config.schema.json"
    features_path = truth_root / "lib.rs"
    legacy_path = truth_root / "legacy.rs"
    schema_path.write_text('{"type":"object"}', encoding="utf-8")
    features_path.write_text("features", encoding="utf-8")
    legacy_path.write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(run_config_maintenance, "DELTA_DIR", delta_dir)
    monkeypatch.setattr(run_config_maintenance, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(run_config_maintenance, "ALIGN_TOOL", tmp_path / "align_toml_inline_comments")
    monkeypatch.setattr(
        run_config_maintenance,
        "parse_args",
        lambda: argparse.Namespace(
            mode="prepare-changelog-artifacts",
            automation_root=None,
            mirror=mirror,
            repo_url="https://github.com/openai/codex.git",
            from_sha="1234567890abcdef",
            config_clean=clean,
            config_runtime=runtime,
        ),
    )
    monkeypatch.setattr(
        run_config_maintenance,
        "ensure_mirror",
        lambda path, repo_url: "abcdef1234567890",
    )
    monkeypatch.setattr(
        run_config_maintenance,
        "materialize_truth_sources",
        lambda run_dir, git_dir, ref: {
            "schema": schema_path,
            "features_lib": features_path,
            "legacy_features": legacy_path,
        },
    )

    commands: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        command_text = " ".join(command)
        if "classify_config_keys.py" in command_text:
            output_index = command.index("--output") + 1
            output_path = Path(command[output_index])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                '{"summary":{"new":0,"pre-schema":0,"legacy":0,"removed":0},"entries":[]}',
                encoding="utf-8",
            )
        elif "validate_config_sync.py" in command_text:
            output_index = command.index("--output") + 1
            output_path = Path(command[output_index])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "# Config Maintenance Validation\n\n## Result\n\n- validation passed\n",
                encoding="utf-8",
            )
        elif "sync_config_files.py" in command_text:
            clean_output = Path(command[command.index("--output-clean") + 1])
            runtime_output = Path(command[command.index("--output-runtime") + 1])
            clean_output.parent.mkdir(parents=True, exist_ok=True)
            clean_output.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
            runtime_output.write_text('default_permissions = "workspace"\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_config_maintenance, "run", fake_run)

    exit_code = run_config_maintenance.main()

    classify_command = next(command for command in commands if "classify_config_keys.py" in " ".join(command))
    assert exit_code == 0
    assert "--git-dir" in classify_command
    assert classify_command[classify_command.index("--repo") + 1] == str(mirror)
    assert classify_command[classify_command.index("--schema") + 1] == str(schema_path)
    assert classify_command[classify_command.index("--features-lib") + 1] == str(features_path)
    assert classify_command[classify_command.index("--legacy-features") + 1] == str(legacy_path)


def test_discover_range_builds_run_context_from_memory_and_mirror(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_path = tmp_path / "memory.md"
    mirror = tmp_path / "mirror.git"
    artifact_root = tmp_path / "deltas"
    memory_path.write_text(
        "\n".join(
            [
                "# delta-run memory",
                "",
                "- last_reported_origin_main_sha: 1234567890abcdef1234567890abcdef12345678",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        discover_range,
        "ensure_mirror",
        lambda path, repo_url: "abcdef1234567890abcdef1234567890abcdef12",
    )
    monkeypatch.setattr(discover_range, "run_stdout", lambda command: "7")

    context, output = discover_range.build_run_context(
        argparse.Namespace(
            automation_root=None,
            memory=memory_path,
            mirror=mirror,
            from_sha=None,
            repo_url="https://github.com/openai/codex.git",
            artifact_root=artifact_root,
            output=None,
        )
    )

    assert output == artifact_root / "abcdef1" / "run-context.json"
    assert context["from_sha"] == "1234567890abcdef1234567890abcdef12345678"
    assert context["to_sha"] == "abcdef1234567890abcdef1234567890abcdef12"
    assert context["range"] == (
        "1234567890abcdef1234567890abcdef12345678.."
        "abcdef1234567890abcdef1234567890abcdef12"
    )
    assert context["commit_count"] == 7
    assert context["config_findings_path"] == str(
        artifact_root / "abcdef1" / "config-findings-1234567.json"
    )


def test_discover_range_requires_explicit_baseline_when_memory_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_path = tmp_path / "memory.md"
    mirror = tmp_path / "mirror.git"
    artifact_root = tmp_path / "deltas"
    memory_path.write_text("# delta-run memory\n", encoding="utf-8")

    monkeypatch.setattr(
        discover_range,
        "ensure_mirror",
        lambda path, repo_url: "abcdef1234567890abcdef1234567890abcdef12",
    )

    try:
        discover_range.build_run_context(
            argparse.Namespace(
                automation_root=None,
                memory=memory_path,
                mirror=mirror,
                from_sha=None,
                repo_url="https://github.com/openai/codex.git",
                artifact_root=artifact_root,
                output=None,
            )
        )
    except RuntimeError as exc:
        assert "requires a baseline SHA" in str(exc)
    else:
        raise AssertionError("expected discover_range.build_run_context to require a baseline SHA")


def test_discover_range_derives_memory_and_mirror_from_automation_root_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    automation_root = tmp_path / "automations" / "delta-run"
    memory_path = automation_root / "memory.md"
    artifact_root = tmp_path / "deltas"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        "\n".join(
            [
                "# delta-run memory",
                "",
                "- last_reported_origin_main_sha: 1234567890abcdef1234567890abcdef12345678",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_DELTAS_AUTOMATION_ROOT", str(automation_root))
    monkeypatch.setenv("CODEX_DELTAS_REPO_URL", "https://github.com/openai/codex.git")

    seen: dict[str, Path] = {}

    def fake_ensure_mirror(path: Path, repo_url: str) -> str:
        seen["mirror"] = path
        return "abcdef1234567890abcdef1234567890abcdef12"

    monkeypatch.setattr(discover_range, "ensure_mirror", fake_ensure_mirror)
    monkeypatch.setattr(discover_range, "run_stdout", lambda command: "7")

    context, output = discover_range.build_run_context(
        argparse.Namespace(
            automation_root=None,
            memory=None,
            mirror=None,
            from_sha=None,
            repo_url="https://github.com/openai/codex.git",
            artifact_root=artifact_root,
            output=None,
        )
    )

    assert output == artifact_root / "abcdef1" / "run-context.json"
    assert context["memory_path"] == str(memory_path)
    assert seen["mirror"] == Path("/tmp") / "delta-run" / "openai-codex.git"


def test_discover_range_derives_repo_specific_mirror_name_from_repo_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    automation_root = tmp_path / "automations" / "delta-run"
    memory_path = automation_root / "memory.md"
    artifact_root = tmp_path / "deltas"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        "\n".join(
            [
                "# delta-run memory",
                "",
                "- last_reported_origin_main_sha: 1234567890abcdef1234567890abcdef12345678",
                "",
            ]
        ),
        encoding="utf-8",
    )

    seen: dict[str, Path] = {}

    def fake_ensure_mirror(path: Path, repo_url: str) -> str:
        seen["mirror"] = path
        seen["repo_url"] = repo_url
        return "abcdef1234567890abcdef1234567890abcdef12"

    monkeypatch.setattr(discover_range, "ensure_mirror", fake_ensure_mirror)
    monkeypatch.setattr(discover_range, "run_stdout", lambda command: "7")

    context, output = discover_range.build_run_context(
        argparse.Namespace(
            automation_root=automation_root,
            memory=None,
            mirror=None,
            from_sha=None,
            repo_url="https://github.com/example/alt-repo.git",
            artifact_root=artifact_root,
            output=None,
        )
    )

    assert output == artifact_root / "abcdef1" / "run-context.json"
    assert context["repo_url"] == "https://github.com/example/alt-repo.git"
    assert seen["repo_url"] == "https://github.com/example/alt-repo.git"
    assert seen["mirror"] == Path("/tmp") / "delta-run" / "example-alt-repo.git"


def test_analyze_repo_builds_findings_from_run_context(monkeypatch) -> None:
    context = {
        "mirror_path": "/tmp/mirror.git",
        "from_sha": "1111111111111111111111111111111111111111",
        "to_sha": "2222222222222222222222222222222222222222",
        "range": "1111111111111111111111111111111111111111..2222222222222222222222222222222222222222",
        "commit_count": 2,
    }

    def fake_run_stdout(command: list[str]) -> str:
        if "--format=%H%x1f%an%x1f%ad%x1f%s%x1f%b%x1e" in command:
            return (
                "aaaa1111\x1fAlice\x1f2026-04-07\x1fFirst subject\x1fBody line\x1e"
                "bbbb2222\x1fBob\x1f2026-04-08\x1fSecond subject\x1f\x1e"
            )
        if "--name-status" in command:
            return "M\tcodex-rs/core/config.rs\nR100\told.txt\tnew.txt\n"
        if "--numstat" in command:
            return "4\t1\tcodex-rs/core/config.rs\n0\t0\tnew.txt\n"
        raise AssertionError(command)

    monkeypatch.setattr(analyze_repo, "run_stdout", fake_run_stdout)

    findings = analyze_repo.build_repo_findings(context)

    assert findings["commit_count"] == 2
    assert findings["commits"][0]["subject"] == "First subject"
    assert findings["changed_files"][1]["previous_path"] == "old.txt"
    assert findings["file_stats"]["codex-rs/core/config.rs"] == {"added": 4, "deleted": 1}


def test_update_state_writes_state_update_and_compact_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    memory_path = tmp_path / "memory.md"
    run_context = tmp_path / "run-context.json"
    state_update_path = tmp_path / "state-update.json"
    run_context.write_text(
        json.dumps(
            {
                "repo_url": "https://github.com/openai/codex.git",
                "mirror_path": "/tmp/mirror.git",
                "memory_path": str(memory_path),
                "state_update_path": str(state_update_path),
                "to_sha": "abcdef1234567890abcdef1234567890abcdef12",
                "range": "111..222",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        update_state,
        "parse_args",
        lambda: argparse.Namespace(
            run_context=run_context,
            memory=None,
            mode="success",
            status_note="fresh report written",
            learnings="range handled through plugin lanes",
            corrections=None,
            feedback="report looked good",
            apply=True,
        ),
    )

    exit_code = update_state.main()

    assert exit_code == 0
    assert state_update_path.exists()
    state_payload = json.loads(state_update_path.read_text(encoding="utf-8"))
    assert (
        state_payload["fields"]["last_reported_origin_main_sha"]
        == "abcdef1234567890abcdef1234567890abcdef12"
    )
    memory_text = memory_path.read_text(encoding="utf-8")
    assert "- status_note: fresh report written" in memory_text
    assert "- feedback: report looked good" in memory_text
