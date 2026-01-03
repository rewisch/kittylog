#!/usr/bin/env bash
set -euo pipefail

# Create and start a systemd service for KittyLog.

SERVICE_NAME="kittylog"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${KITTYLOG_SERVICE_USER:-kittylog}"
SERVICE_GROUP="${SERVICE_USER}"
LOG_DIR="${REPO_ROOT}/logs"
DATA_DIR="${REPO_ROOT}/data"
CONFIG_DIR="${REPO_ROOT}/config"
SERVICE_ROOT="${REPO_ROOT}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script needs sudo to write ${SERVICE_FILE} and manage systemd." >&2
  echo "Re-run with: sudo $0" >&2
  exit 1
fi

# Create a dedicated, least-privilege service account if missing.
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${REPO_ROOT}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

# Ensure writable dirs for the service user.
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 750 "${LOG_DIR}" "${DATA_DIR}" "${CONFIG_DIR}"
if [[ -f "${CONFIG_DIR}/kittylog.env" ]]; then
  chown "${SERVICE_USER}:${SERVICE_GROUP}" "${CONFIG_DIR}/kittylog.env"
fi

# Ensure the service account owns the entire install root (e.g., /srv/kittylog).
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${SERVICE_ROOT}"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=KittyLog FastAPI service
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
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
