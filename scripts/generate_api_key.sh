#!/usr/bin/env bash
# Generate a random API key and write config/api_key.yml if missing or when forced.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${ROOT_DIR}/config/api_key.yml"
FORCE="${FORCE:-false}"
API_USER="${API_USER:-api}"

if [[ -f "${TARGET}" && "${FORCE}" != "true" ]]; then
  echo "config/api_key.yml already exists. Set FORCE=true to overwrite."
  exit 0
fi

mkdir -p "$(dirname "${TARGET}")"

KEY="$(python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"

cat > "${TARGET}" <<EOF
api_key: "${KEY}"
api_user: "${API_USER}"
EOF

echo "Wrote ${TARGET}"
