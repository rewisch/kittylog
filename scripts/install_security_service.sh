#!/usr/bin/env bash
set -euo pipefail

# Create and start a systemd service that keeps the security_decider loop running.

SERVICE_NAME="kittylog-security-decider"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${KITTYLOG_SERVICE_USER:-kittylog}"
SERVICE_GROUP="${SERVICE_USER}"
LOG_DIR="${REPO_ROOT}/logs"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script needs sudo to write ${SERVICE_FILE} and manage systemd." >&2
  echo "Re-run with: sudo $0" >&2
  exit 1
fi

# Create the service account if it does not exist.
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir "${REPO_ROOT}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

# Ensure the service user can write the repo state/logs the decider uses.
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 750 "${LOG_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${REPO_ROOT}/var"

# Defaults can be overridden via systemctl edit or EnvironmentFile if desired.
cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=KittyLog security decider
After=network.target fail2ban.service
Wants=fail2ban.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${REPO_ROOT}
Environment="LOOP_SLEEP=5"
ExecStart=${REPO_ROOT}/scripts/security_decider.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager
echo "Service ${SERVICE_NAME} installed and started."
