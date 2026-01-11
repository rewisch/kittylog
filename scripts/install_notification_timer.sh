#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: install_notification_timer.sh [--repo PATH] [--interval-min N]

Creates a systemd timer that runs the notification dispatcher as the kittylog user.
Must be run as root so it can create/configure the kittylog user.

Options:
  --repo PATH        KittyLog repo path (default: current repo)
  --interval-min N   Interval in minutes (default: 1)
USAGE
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "This script must be run as root (to create/configure the kittylog user)." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL_MIN=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_ROOT="$2"
      shift 2
      ;;
    --interval-min)
      INTERVAL_MIN="$2"
      shift 2
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

if ! id kittylog >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /home/kittylog --shell /usr/sbin/nologin kittylog
fi

if [[ ! -d "$REPO_ROOT" ]]; then
  echo "Repo path not found: $REPO_ROOT" >&2
  exit 1
fi

SERVICE_PATH="/etc/systemd/system/kittylog-notify.service"
TIMER_PATH="/etc/systemd/system/kittylog-notify.timer"

cat <<SERVICE > "$SERVICE_PATH"
[Unit]
Description=KittyLog push notification dispatcher
After=network.target

[Service]
Type=oneshot
User=kittylog
Group=kittylog
WorkingDirectory=$REPO_ROOT
ExecStart=$REPO_ROOT/.venv/bin/python $REPO_ROOT/scripts/dispatch_notifications.py

[Install]
WantedBy=multi-user.target
SERVICE

cat <<TIMER > "$TIMER_PATH"
[Unit]
Description=Run KittyLog notification dispatcher every ${INTERVAL_MIN} minute(s)

[Timer]
OnCalendar=*:0/${INTERVAL_MIN}
Persistent=true
AccuracySec=30s

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable --now kittylog-notify.timer

cat <<'DONE'
Installed systemd timer.
Check status with:
  systemctl status kittylog-notify.timer
DONE
