#!/usr/bin/env bash
# Generate a random API key and write config/api_key.yml if missing or when forced.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${ROOT_DIR}/config/api_key.yml"
FORCE="${FORCE:-false}"

generate_user() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr 'A-Z' 'a-z' | cut -c1-8
  elif [ -r /proc/sys/kernel/random/uuid ]; then
    head -c 8 /proc/sys/kernel/random/uuid
  else
    date +%s%N | sha256sum | cut -c1-8
  fi
}

generate_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | xxd -p -c 64
  fi
}

DYN_USER="cat-device-$(generate_user)"
API_USER="${API_USER:-${DYN_USER}}"

if [[ -f "${TARGET}" && "${FORCE}" != "true" ]]; then
  echo "config/api_key.yml already exists. Set FORCE=true to overwrite."
  exit 0
fi

mkdir -p "$(dirname "${TARGET}")"

KEY="$(generate_key)"

cat > "${TARGET}" <<EOF
api_key: "${KEY}"
api_user: "${API_USER}"
EOF

echo "Wrote ${TARGET}"
