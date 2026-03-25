from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import tomlkit


REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))


def load_module(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sync_config_files = load_module(
    "sync_config_files",
    "skills/config-file-sync/scripts/sync_config_files.py",
)
shared = load_module(
    "codex_config_shared",
    "lib/codex_config/shared.py",
)
validate_config_sync = load_module(
    "validate_config_sync",
    "skills/config-validate/scripts/validate_config_sync.py",
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
