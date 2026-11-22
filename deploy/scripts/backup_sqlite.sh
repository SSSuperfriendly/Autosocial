#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${AUTOSOCIAL_APP_DIR:-/opt/autosocial/app}"
STATE_DIR="${AUTOSOCIAL_STATE_DIR:-/var/lib/autosocial}"
BACKUP_DIR="${AUTOSOCIAL_BACKUP_DIR:-$STATE_DIR/backups}"
RETENTION_DAYS="${AUTOSOCIAL_BACKUP_RETENTION_DAYS:-14}"
DB_PATH="${DATABASE_PATH:-$STATE_DIR/data/autosocial.db}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
work_dir="$(mktemp -d)"
archive="$BACKUP_DIR/autosocial-$timestamp.tar.gz"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"

if [[ -f "$DB_PATH" ]]; then
  mkdir -p "$work_dir/data"
  sqlite3 "$DB_PATH" ".backup '$work_dir/data/autosocial.db'"
fi

copy_if_exists() {
  local source="$1"
  local target="$2"
  if [[ -e "$source" ]]; then
    mkdir -p "$(dirname "$target")"
    cp -a "$source" "$target"
  fi
}

copy_if_exists "$STATE_DIR/data/user_preferences.json" "$work_dir/data/user_preferences.json"
copy_if_exists "$STATE_DIR/data/discovery_prompts.json" "$work_dir/data/discovery_prompts.json"
copy_if_exists "$STATE_DIR/data/interests.txt" "$work_dir/data/interests.txt"
copy_if_exists "$STATE_DIR/data/target_schools.csv" "$work_dir/data/target_schools.csv"
copy_if_exists "$STATE_DIR/student_profile.md" "$work_dir/student_profile.md"

if [[ -d "$STATE_DIR/templates" ]]; then
  mkdir -p "$work_dir/templates"
  cp -a "$STATE_DIR/templates/." "$work_dir/templates/"
fi

if [[ -d "$STATE_DIR/attachments" ]]; then
  mkdir -p "$work_dir/attachments"
  cp -a "$STATE_DIR/attachments/." "$work_dir/attachments/"
fi

tar -czf "$archive" -C "$work_dir" .
chmod 600 "$archive"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'autosocial-*.tar.gz' -mtime +"$RETENTION_DAYS" -delete

echo "$archive"
