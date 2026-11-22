#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${AUTOSOCIAL_APP_DIR:-/opt/autosocial/app}"
VENV_DIR="${AUTOSOCIAL_VENV_DIR:-/opt/autosocial/venv}"
STATE_DIR="${AUTOSOCIAL_STATE_DIR:-/var/lib/autosocial}"
CONFIG_DIR="${AUTOSOCIAL_CONFIG_DIR:-/etc/autosocial}"
REPO_URL="${AUTOSOCIAL_REPO_URL:-}"
BRANCH="${AUTOSOCIAL_BRANCH:-main}"

sudo mkdir -p "$(dirname "$APP_DIR")"

if [[ ! -d "$APP_DIR/.git" ]]; then
  if [[ -z "$REPO_URL" ]]; then
    echo "No .git directory found in $APP_DIR and AUTOSOCIAL_REPO_URL is empty." >&2
    exit 1
  fi
  if [[ -e "$APP_DIR" ]]; then
    backup_dir="${APP_DIR}.pre-git.$(date -u +%Y%m%dT%H%M%SZ)"
    sudo mv "$APP_DIR" "$backup_dir"
    echo "Moved existing app directory to $backup_dir"
  fi
  sudo -H -u autosocial git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
sudo -H -u autosocial git fetch origin "$BRANCH"
sudo -H -u autosocial git reset --hard "origin/$BRANCH"

for linked_name in data runtime templates 附件 student_profile.md; do
  if [[ -e "$APP_DIR/$linked_name" && ! -L "$APP_DIR/$linked_name" ]]; then
    echo "Refusing to replace real application data at $APP_DIR/$linked_name. Back it up and migrate it to $STATE_DIR before updating." >&2
    exit 1
  fi
done
sudo rm -f "$APP_DIR/data" "$APP_DIR/runtime" "$APP_DIR/templates" "$APP_DIR/附件" "$APP_DIR/student_profile.md"
sudo ln -sfn "$STATE_DIR/data" "$APP_DIR/data"
sudo ln -sfn "$STATE_DIR/runtime" "$APP_DIR/runtime"
sudo ln -sfn "$STATE_DIR/templates" "$APP_DIR/templates"
sudo ln -sfn "$STATE_DIR/attachments" "$APP_DIR/附件"
sudo ln -sfn "$STATE_DIR/student_profile.md" "$APP_DIR/student_profile.md"
sudo chown -h autosocial:autosocial "$APP_DIR/data" "$APP_DIR/runtime" "$APP_DIR/templates" "$APP_DIR/附件" "$APP_DIR/student_profile.md"

sudo -H -u autosocial "$VENV_DIR/bin/pip" install -r requirements.txt
sudo -H -u autosocial bash -lc "cd '$APP_DIR/frontend' && npm ci && npm run build"

# Upgrade old installations before restarting: existing unit files and .env
# files may predate authentication. No credential is printed to the terminal.
sudo mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/autosocial.env" ]]; then
  sudo install -m 0640 "$APP_DIR/deploy/env.production.example" "$CONFIG_DIR/autosocial.env"
fi
sudo python3 "$APP_DIR/deploy/scripts/configure_auth.py" "$CONFIG_DIR/autosocial.env"
sudo chown root:autosocial "$CONFIG_DIR/autosocial.env"

# Keep existing path overrides when installing the updated service definition.
unit_file="$(mktemp)"
trap 'rm -f "$unit_file"' EXIT
python3 - "$APP_DIR/deploy/systemd/autosocial.service" "$APP_DIR" "$VENV_DIR" "$STATE_DIR" "$CONFIG_DIR" > "$unit_file" <<'PY'
from pathlib import Path
import sys

template, app_dir, venv_dir, state_dir, config_dir = sys.argv[1:]

def quote(value):
    if "\n" in value or "\r" in value:
        raise SystemExit("Service paths cannot contain newlines.")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

replacements = {
    "WorkingDirectory=": "WorkingDirectory=" + quote(app_dir),
    "EnvironmentFile=": "EnvironmentFile=" + quote(config_dir + "/autosocial.env"),
    "ExecStart=": "ExecStart=/usr/bin/env AUTOSOCIAL_REQUIRE_AUTH=true " + quote(venv_dir + "/bin/python") + " -m uvicorn server.main:app --host 127.0.0.1 --port 8000",
    "ReadWritePaths=": "ReadWritePaths=" + quote(state_dir) + " " + quote(app_dir + "/frontend/dist"),
}
for line in Path(template).read_text().splitlines():
    print(next((value for key, value in replacements.items() if line.startswith(key)), line))
PY
sudo install -m 0644 "$unit_file" /etc/systemd/system/autosocial.service
sudo systemctl daemon-reload
sudo systemctl restart autosocial
sudo systemctl status autosocial --no-pager
echo "Owner credentials are stored in $CONFIG_DIR/autosocial.env (read with sudo)."
