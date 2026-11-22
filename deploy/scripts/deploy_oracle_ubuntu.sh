#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="/opt/autosocial"
APP_DIR="$APP_ROOT/app"
VENV_DIR="$APP_ROOT/venv"
STATE_DIR="/var/lib/autosocial"
CONFIG_DIR="/etc/autosocial"
SERVICE_USER="autosocial"
SITE_ADDRESS=":80"
INSTALL_CADDY="true"
INSTALL_NODE="true"

usage() {
  cat <<'EOF'
Usage:
  sudo bash deploy/scripts/deploy_oracle_ubuntu.sh [options]

Options:
  --domain DOMAIN       Public domain for Caddy HTTPS, for example autosocial.example.com.
                        If omitted, Caddy listens on :80 without automatic HTTPS.
  --site-address ADDR   Raw Caddy site address. Overrides --domain. Example: :80
  --no-caddy            Skip Caddy installation and Caddyfile update.
  --no-node             Skip Node.js installation.
  -h, --help            Show this help.

Run this script from the project root after copying or cloning AutoSocial to the VM.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      SITE_ADDRESS="${2:?Missing domain}"
      shift 2
      ;;
    --site-address)
      SITE_ADDRESS="${2:?Missing site address}"
      shift 2
      ;;
    --no-caddy)
      INSTALL_CADDY="false"
      shift
      ;;
    --no-node)
      INSTALL_NODE="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run with sudo or as root." >&2
  exit 1
fi

if [[ ! -f /etc/os-release ]]; then
  echo "Unsupported OS: /etc/os-release not found." >&2
  exit 1
fi

. /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *"ubuntu"* && "${ID_LIKE:-}" != *"debian"* ]]; then
  echo "This installer targets Ubuntu/Debian systems." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/server/main.py" || ! -f "$REPO_ROOT/frontend/package.json" ]]; then
  echo "Cannot find AutoSocial project root. Run this script from a complete project copy." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl gettext-base gnupg rsync sqlite3 python3 python3-venv python3-pip

if [[ "$INSTALL_NODE" == "true" ]]; then
  node_major="0"
  if command -v node >/dev/null 2>&1; then
    node_major="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
    node_major="${node_major:-0}"
  fi
  if [[ "$node_major" -lt 20 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
  fi
fi

if [[ "$INSTALL_CADDY" == "true" ]]; then
  if ! command -v caddy >/dev/null 2>&1; then
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
    install -d -m 0755 /usr/share/keyrings
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    chmod 0644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy
  fi
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_DIR" "$VENV_DIR" "$STATE_DIR/data" "$STATE_DIR/runtime" "$STATE_DIR/attachments" "$STATE_DIR/backups" "$STATE_DIR/templates" "$CONFIG_DIR"

rsync -a --delete \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude 'frontend/*.tsbuildinfo' \
  --exclude 'runtime' \
  --exclude 'data' \
  --exclude '附件' \
  --exclude 'student_profile.md' \
  --exclude 'templates' \
  "$REPO_ROOT/" "$APP_DIR/"

seed_file() {
  local source="$1"
  local target="$2"
  if [[ -f "$source" && ! -e "$target" ]]; then
    cp -a "$source" "$target"
  fi
}

seed_file "$REPO_ROOT/data/user_preferences.json" "$STATE_DIR/data/user_preferences.json"
seed_file "$REPO_ROOT/data/discovery_prompts.json" "$STATE_DIR/data/discovery_prompts.json"
seed_file "$REPO_ROOT/data/interests.txt" "$STATE_DIR/data/interests.txt"
seed_file "$REPO_ROOT/data/target_schools.csv" "$STATE_DIR/data/target_schools.csv"
seed_file "$REPO_ROOT/data/autosocial.db" "$STATE_DIR/data/autosocial.db"
seed_file "$REPO_ROOT/student_profile.md" "$STATE_DIR/student_profile.md"
seed_file "$REPO_ROOT/student_profile.example.md" "$STATE_DIR/student_profile.md"

if [[ -d "$REPO_ROOT/templates" && ! -f "$STATE_DIR/templates/email_template.md" ]]; then
  cp -a "$REPO_ROOT/templates/." "$STATE_DIR/templates/"
fi

if [[ -d "$REPO_ROOT/附件" ]]; then
  cp -an "$REPO_ROOT/附件/." "$STATE_DIR/attachments/" || true
fi

rm -rf "$APP_DIR/data" "$APP_DIR/runtime" "$APP_DIR/templates" "$APP_DIR/附件" "$APP_DIR/student_profile.md"
ln -s "$STATE_DIR/data" "$APP_DIR/data"
ln -s "$STATE_DIR/runtime" "$APP_DIR/runtime"
ln -s "$STATE_DIR/templates" "$APP_DIR/templates"
ln -s "$STATE_DIR/attachments" "$APP_DIR/附件"
ln -s "$STATE_DIR/student_profile.md" "$APP_DIR/student_profile.md"

if [[ ! -f "$CONFIG_DIR/autosocial.env" ]]; then
  cp "$APP_DIR/deploy/env.production.example" "$CONFIG_DIR/autosocial.env"
fi

# Provision authentication before starting the service. The helper preserves a
# configured strong password and writes generated credentials only to this file.
python3 "$APP_DIR/deploy/scripts/configure_auth.py" "$CONFIG_DIR/autosocial.env"

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT" "$STATE_DIR"
chown root:"$SERVICE_USER" "$CONFIG_DIR/autosocial.env"
chmod 640 "$CONFIG_DIR/autosocial.env"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

cd "$APP_DIR/frontend"
npm ci
npm run build

install -m 0755 "$APP_DIR/deploy/scripts/backup_sqlite.sh" /usr/local/bin/autosocial-backup
install -m 0644 "$APP_DIR/deploy/systemd/autosocial.service" /etc/systemd/system/autosocial.service
install -m 0644 "$APP_DIR/deploy/systemd/autosocial-backup.service" /etc/systemd/system/autosocial-backup.service
install -m 0644 "$APP_DIR/deploy/systemd/autosocial-backup.timer" /etc/systemd/system/autosocial-backup.timer

if [[ "$INSTALL_CADDY" == "true" ]]; then
  AUTOSOCIAL_SITE_ADDRESS="$SITE_ADDRESS" envsubst < "$APP_DIR/deploy/caddy/Caddyfile.template" > /etc/caddy/Caddyfile
  systemctl enable caddy >/dev/null 2>&1 || true
fi

DATABASE_PATH="$(grep -E '^DATABASE_PATH=' "$CONFIG_DIR/autosocial.env" | tail -n 1 | cut -d= -f2-)"
export DATABASE_PATH
cd "$APP_DIR"
"$VENV_DIR/bin/python" -m autosocial init-db

systemctl daemon-reload
systemctl enable --now autosocial
systemctl enable --now autosocial-backup.timer

if [[ "$INSTALL_CADDY" == "true" ]]; then
  caddy fmt --overwrite /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
fi

if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

echo
echo "AutoSocial deployed."
echo "App directory: $APP_DIR"
echo "State directory: $STATE_DIR"
echo "Config file: $CONFIG_DIR/autosocial.env"
echo "Owner login: read AUTOSOCIAL_USERNAME and AUTOSOCIAL_PASSWORD in the config file with sudo."
echo "Service: systemctl status autosocial"
if [[ "$INSTALL_CADDY" == "true" ]]; then
  echo "Public site address: $SITE_ADDRESS"
fi
