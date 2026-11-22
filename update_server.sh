#!/usr/bin/env bash
# Compatibility entry point. All server updates use the maintained deploy script.
set -euo pipefail

WRAPPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AUTOSOCIAL_APP_DIR="${AUTOSOCIAL_APP_DIR:-${APP_DIR:-$WRAPPER_DIR}}"
export AUTOSOCIAL_BRANCH="${AUTOSOCIAL_BRANCH:-${BRANCH:-main}}"

if [[ -n "${VENV_DIR:-}" && -z "${AUTOSOCIAL_VENV_DIR:-}" ]]; then
  export AUTOSOCIAL_VENV_DIR="$VENV_DIR"
fi
if [[ -n "${STATE_DIR:-}" && -z "${AUTOSOCIAL_STATE_DIR:-}" ]]; then
  export AUTOSOCIAL_STATE_DIR="$STATE_DIR"
fi
if [[ -n "${CONFIG_DIR:-}" && -z "${AUTOSOCIAL_CONFIG_DIR:-}" ]]; then
  export AUTOSOCIAL_CONFIG_DIR="$CONFIG_DIR"
fi
if [[ -n "${REPO_URL:-}" && -z "${AUTOSOCIAL_REPO_URL:-}" ]]; then
  export AUTOSOCIAL_REPO_URL="$REPO_URL"
fi
if [[ -n "${DATA_DIR:-}" && -z "${AUTOSOCIAL_STATE_DIR:-}" ]]; then
  echo "Legacy DATA_DIR layouts are not migrated automatically. Back up the data and configure AUTOSOCIAL_STATE_DIR using the layout in DEPLOY.md." >&2
  exit 1
fi

exec bash "$WRAPPER_DIR/deploy/scripts/deploy_update.sh" "$@"
