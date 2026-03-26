set shell := ["bash", "-euo", "pipefail", "-c"]

default:
  @just --list

sync-codex-git-changelog-automation:
  #!/usr/bin/env bash
  src="{{justfile_directory()}}/automations/codex-git-changelog/automation.toml"
  codex_home="${CODEX_HOME:-$HOME/.codex}"
  dest_dir="$codex_home/automations/codex-git-changelog"
  dest="$dest_dir/automation.toml"

  test -f "$src"
  mkdir -p "$dest_dir"

  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
    echo "Automation already up to date: $dest"
    exit 0
  fi

  cp "$src" "$dest"
  echo "Synced automation: $src -> $dest"
