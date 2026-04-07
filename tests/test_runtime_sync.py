from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import tomlkit


REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from codex_config import shared
from codex_config.commands import config_file_sync as sync_config_files
from codex_config.commands import config_key_lifecycle as classify_config_keys
from codex_config.commands import config_maintenance as run_config_maintenance
from codex_config.commands import config_validate as validate_config_sync


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
    repo = tmp_path / "repo"
    repo.mkdir()
    clean = tmp_path / "config-CLEAN.toml"
    runtime = tmp_path / "config.toml"
    clean.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
    runtime.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    delta_dir = tmp_path / "deltas"
    automation_dir = tmp_path / "automations"
    skills_dir = tmp_path / "skills"
    mirror = tmp_path / "mirror.git"

    monkeypatch.setattr(run_config_maintenance, "DELTA_DIR", delta_dir)
    monkeypatch.setattr(run_config_maintenance, "AUTOMATION_DIR", automation_dir)
    monkeypatch.setattr(run_config_maintenance, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(run_config_maintenance, "MIRROR_PATH", mirror)
    monkeypatch.setattr(run_config_maintenance, "ALIGN_TOOL", tmp_path / "align_toml_inline_comments")
    monkeypatch.setattr(
        run_config_maintenance,
        "parse_args",
        lambda: argparse.Namespace(
            mode="sync-current",
            repo=repo,
            mirror=mirror,
            from_sha=None,
            config_clean=clean,
            config_runtime=runtime,
        ),
    )
    monkeypatch.setattr(run_config_maintenance, "run_stdout", lambda command: "abcdef1234567890")

    def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        command_text = " ".join(command)
        if "classify_config_keys.py" in command_text:
            return subprocess.CompletedProcess(command, 1, "", "classification exploded")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_config_maintenance, "run", fake_run)

    exit_code = run_config_maintenance.main()

    run_dir = delta_dir / "abcdef1"
    validation_output = run_dir / "validation.md"
    summary_output = run_dir / "config-maintenance-summary.md"

    assert exit_code == 1
    assert validation_output.exists()
    assert summary_output.exists()
    assert "workflow failed before validation during `classify`" in validation_output.read_text(encoding="utf-8")
    summary_text = summary_output.read_text(encoding="utf-8")
    assert "- stage: `classify`" in summary_text
    assert "classification exploded" in summary_text


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
    repo = tmp_path / "stale-repo"
    repo.mkdir()
    mirror = tmp_path / "mirror.git"
    clean = tmp_path / "config-CLEAN.toml"
    runtime = tmp_path / "config.toml"
    clean.write_text("[features]\nfeature_a = true\n", encoding="utf-8")
    runtime.write_text('sandbox_mode = "workspace-write"\n', encoding="utf-8")

    delta_dir = tmp_path / "deltas"
    automation_dir = tmp_path / "automations"
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
    monkeypatch.setattr(run_config_maintenance, "AUTOMATION_DIR", automation_dir)
    monkeypatch.setattr(run_config_maintenance, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(run_config_maintenance, "MIRROR_PATH", mirror)
    monkeypatch.setattr(run_config_maintenance, "ALIGN_TOOL", tmp_path / "align_toml_inline_comments")
    monkeypatch.setattr(
        run_config_maintenance,
        "parse_args",
        lambda: argparse.Namespace(
            mode="prepare-changelog-artifacts",
            repo=repo,
            mirror=mirror,
            from_sha="1234567890abcdef",
            config_clean=clean,
            config_runtime=runtime,
        ),
    )
    monkeypatch.setattr(run_config_maintenance, "ensure_mirror", lambda path: "abcdef1234567890")
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
