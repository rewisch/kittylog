#!/usr/bin/env bash
set -euo pipefail

# Run KittyLog on a Pi-friendly setup. Creates a persistent secret on first run.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/config/kittylog.env"
VENV_DIR="$REPO_ROOT/.venv"

# Create env file with a strong secret if missing.
if [[ ! -f "$ENV_FILE" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  SECRET="$(python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  {
    echo "KITTYLOG_SECRET_KEY=$SECRET"
    echo "KITTYLOG_SESSION_SECURE=true"
  } >"$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE with a new KITTYLOG_SECRET_KEY (Secure cookies enabled)."
fi

# Load environment (allows manual edits later).
set -a
source "$ENV_FILE"
set +a

# Prefer the project's virtualenv if present.
if [[ -f "$VENV_DIR/bin/activate" ]]; then
  source "$VENV_DIR/bin/activate"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers 1
