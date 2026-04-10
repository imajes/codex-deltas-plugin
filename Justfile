set shell := ["bash", "-euo", "pipefail", "-c"]

default:
  @just --list

sync-automation-template:
  #!/usr/bin/env bash
  src="{{justfile_directory()}}/automations/changelog-template/automation.toml"
  codex_home="${CODEX_HOME:-$HOME/.codex}"
  automation_root="${AUTOMATION_ROOT:-${CODEX_DELTAS_AUTOMATION_ROOT:-}}"

  if [[ -z "$automation_root" ]]; then
    echo "Set AUTOMATION_ROOT or CODEX_DELTAS_AUTOMATION_ROOT before syncing the template." >&2
    exit 1
  fi

  dest_dir="$automation_root"
  dest="$dest_dir/automation.toml"

  test -f "$src"
  mkdir -p "$dest_dir"

  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
    echo "Automation already up to date: $dest"
    exit 0
  fi

  cp "$src" "$dest"
  echo "Synced automation: $src -> $dest"
