#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  backup_kittylog.sh [--backup-dir DIR] [--name NAME]
  backup_kittylog.sh --restore [--backup-dir DIR] [--name NAME] [--yes]

Creates a tar.gz backup of the kittylog repo. Restore will mirror the backup
back into the repo (using rsync --delete).

Options:
  --backup-dir DIR  Directory to store backups (default: ~/kittylog_backups)
  --name NAME       Backup name (default: kittylog-YYYYmmdd-HHMMSS)
  --restore         Restore from backup (latest if --name omitted)
  --yes             Skip restore confirmation prompt
USAGE
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${HOME}/kittylog_backups"
NAME=""
DO_RESTORE=0
AUTO_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-dir)
      BACKUP_DIR="$2"
      shift 2
      ;;
    --name)
      NAME="$2"
      shift 2
      ;;
    --restore)
      DO_RESTORE=1
      shift
      ;;
    --yes)
      AUTO_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

mkdir -p "$BACKUP_DIR"

if [[ -z "$NAME" ]]; then
  NAME="kittylog-$(date +%Y%m%d-%H%M%S)"
fi

backup_path="$BACKUP_DIR/${NAME}.tar.gz"

if [[ $DO_RESTORE -eq 0 ]]; then
  if [[ -f "$backup_path" ]]; then
    echo "Backup already exists: $backup_path" >&2
    exit 1
  fi
  tar -czf "$backup_path" -C "$REPO_ROOT" \
    --exclude=".git" \
    --exclude=".venv" \
    --exclude="__pycache__" \
    --exclude="**/__pycache__" \
    .
  echo "Backup created: $backup_path"
  exit 0
fi

if [[ $DO_RESTORE -eq 1 ]]; then
  if [[ ! -f "$backup_path" ]]; then
    latest=$(ls -t "$BACKUP_DIR"/kittylog-*.tar.gz 2>/dev/null | head -n 1 || true)
    if [[ -z "$latest" ]]; then
      echo "No backups found in $BACKUP_DIR" >&2
      exit 1
    fi
    backup_path="$latest"
  fi

  if [[ $AUTO_YES -ne 1 ]]; then
    echo "This will overwrite $REPO_ROOT with backup: $backup_path"
    read -r -p "Continue? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
      echo "Aborted."
      exit 1
    fi
  fi

  temp_dir=$(mktemp -d)
  trap 'rm -rf "$temp_dir"' EXIT

  tar -xzf "$backup_path" -C "$temp_dir"

  if ! command -v rsync >/dev/null 2>&1; then
    echo "rsync is required for restore but is not installed." >&2
    exit 1
  fi

  rsync -a "$temp_dir"/ "$REPO_ROOT"/
  echo "Restore completed from: $backup_path"
fi
