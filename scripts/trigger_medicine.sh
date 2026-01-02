#!/usr/bin/env bash
# Trigger the "medicine" task for a specific cat via the QR endpoint using the API key.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
CAT_ID="${1:-2}"
NOTE="${NOTE:-Test Medizin}"
LANG="${LANG:-de}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_KEY="$(python - <<'PY'
import sys, yaml, pathlib
api_path = pathlib.Path("config/api_key.yml")
if not api_path.exists():
    sys.exit("config/api_key.yml missing; set KITTYLOG_API_KEY or create the file.")
data = yaml.safe_load(api_path.read_text()) or {}
key = str(data.get("api_key") or "").strip()
if not key:
    sys.exit("api_key missing in config/api_key.yml")
print(key)
PY
)"

curl -i \
  -H "X-API-Key: ${API_KEY}" \
  "${BASE_URL}/q/medicine?cat_id=${CAT_ID}&note=$(printf '%s' "${NOTE}" | python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip()))')&auto=1&lang=${LANG}"
