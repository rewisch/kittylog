#!/usr/bin/env bash
set -euo pipefail

# Create and start a systemd service for KittyLog.

SERVICE_NAME="kittylog"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$(whoami)}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script needs sudo to write ${SERVICE_FILE} and manage systemd." >&2
  echo "Re-run with: sudo $0" >&2
  exit 1
fi

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=KittyLog FastAPI service
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_ROOT}
Environment="PATH=${REPO_ROOT}/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=${REPO_ROOT}/scripts/run_server.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager
echo "Service ${SERVICE_NAME} installed and started."
