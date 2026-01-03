#!/usr/bin/env bash
# Install the KittyLog fail2ban jail/filter from the repo into /etc/fail2ban.
# Usage: bash scripts/deploy_fail2ban.sh
# Destinations can be overridden via F2B_JAIL_DIR and F2B_FILTER_DIR env vars.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
SRC_JAIL="$REPO_ROOT/config/fail2ban/kittylog-security.conf"
SRC_FILTER="$REPO_ROOT/config/fail2ban/filter.d/kittylog-security.conf"

DEST_JAIL_DIR=${F2B_JAIL_DIR:-/etc/fail2ban/jail.d}
DEST_FILTER_DIR=${F2B_FILTER_DIR:-/etc/fail2ban/filter.d}

# Fail fast if fail2ban is missing (helps on minimal Arch/RPi setups).
if ! command -v fail2ban-client >/dev/null 2>&1; then
  echo "fail2ban is not installed or not on PATH. Install fail2ban (e.g., 'sudo apt install fail2ban' or 'sudo pacman -S fail2ban') and retry." >&2
  exit 1
fi

if [[ ! -f "$SRC_JAIL" || ! -f "$SRC_FILTER" ]]; then
  echo "Fail2ban source files missing under config/fail2ban/. Aborting." >&2
  exit 1
fi

mkdir -p "$DEST_JAIL_DIR" "$DEST_FILTER_DIR"

cp "$SRC_JAIL" "$DEST_JAIL_DIR/kittylog-security.conf"
cp "$SRC_FILTER" "$DEST_FILTER_DIR/kittylog-security.conf"

echo "Installed jail to $DEST_JAIL_DIR/kittylog-security.conf"
echo "Installed filter to $DEST_FILTER_DIR/kittylog-security.conf"
echo "If your repo path differs, adjust logpath in the jail to point at <repo>/var/security.decisions.log."
echo "Reload fail2ban: sudo systemctl reload fail2ban"
