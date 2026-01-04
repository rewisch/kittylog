#!/usr/bin/env bash
# Manual unblock helper: removes local ban state, logs an UNBAN line, and
# removes the Cloudflare access rule if configured.
set -euo pipefail

if [[ "${1:-}" =~ ^(-h|--help)$ || $# -lt 1 ]]; then
  cat <<'USAGE'
Usage: scripts/security_unblock.sh <ip> [reason]

Clears a ban for the IP from local state and Cloudflare (if CLOUDFLARE_* set),
and appends a SECURITY UNBAN line to the decisions log.

Environment (defaults shown):
  ENV_FILE=config/kittylog.env
  STATE_DIR=var/security
  BAN_FILE=$STATE_DIR/bans.tsv
  DECISIONS_LOG=var/security.decisions.log
  CLOUDFLARE_ZONE_ID=your_zone_id
  CLOUDFLARE_API_TOKEN=your_api_token

Example:
  CLOUDFLARE_ZONE_ID=abc CLOUDFLARE_API_TOKEN=token \\
    bash scripts/security_unblock.sh 1.2.3.4 manual_test
USAGE
  exit 0
fi

IP="$1"
REASON="${2:-manual_unblock}"

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
ENV_FILE=${ENV_FILE:-"$REPO_ROOT/config/kittylog.env"}
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

STATE_DIR=${STATE_DIR:-"$REPO_ROOT/var/security"}
BAN_FILE=${BAN_FILE:-"$STATE_DIR/bans.tsv"}
DECISIONS_LOG=${DECISIONS_LOG:-"$REPO_ROOT/var/security.decisions.log"}
CLOUDFLARE_ZONE_ID=${CLOUDFLARE_ZONE_ID:-${CF_ZONE_ID:-}}
CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}

mkdir -p "$STATE_DIR" "$(dirname "$DECISIONS_LOG")"
touch "$BAN_FILE" "$DECISIONS_LOG"

info() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*" >&2
}

cloudflare_configured() {
  [[ -n "$CLOUDFLARE_ZONE_ID" && -n "$CLOUDFLARE_API_TOKEN" ]]
}

cloudflare_parse_response() {
  python - <<'PY' 2>/dev/null
import json, sys

def fmt_errors(items):
    if not items:
        return ""
    parts = []
    for item in items:
        if isinstance(item, dict):
            parts.append(item.get("message") or item.get("code") or str(item))
        else:
            parts.append(str(item))
    return "; ".join(parts)

try:
    data = json.load(sys.stdin)
except Exception as exc:
    print(f"err||Invalid JSON: {exc}")
    sys.exit(0)

rid = ""
result = data.get("result")
if isinstance(result, dict):
    rid = result.get("id", "")
elif isinstance(result, list) and result:
    first = result[0]
    if isinstance(first, dict):
        rid = first.get("id", "")

status = "ok" if data.get("success") else "err"
msg = fmt_errors(data.get("errors")) or fmt_errors(data.get("messages"))
print(f"{status}|{rid}|{msg}")
PY
}

cloudflare_find_rule_id() {
  local ip="$1" url response parsed status rule_id msg
  cloudflare_configured || return
  url="https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/firewall/access_rules/rules"
  if ! response=$(curl -sS -G "$url" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data-urlencode "configuration.target=ip" \
    --data-urlencode "configuration.value=${ip}" \
    --data-urlencode "mode=block" \
    --data-urlencode "per_page=50"); then
    info "cloudflare lookup failed for $ip (curl error)"
    return
  fi
  parsed=$(cloudflare_parse_response <<<"$response")
  IFS='|' read -r status rule_id msg <<<"$parsed"
  if [[ "$status" == "ok" && -n "$rule_id" ]]; then
    echo "$rule_id"
  else
    info "cloudflare lookup failed for $ip: ${msg:-not found}"
  fi
}

cloudflare_unblock() {
  local ip="$1" rule_id="$2" reason="$3" url response parsed status msg
  cloudflare_configured || return
  [[ -z "$rule_id" ]] && rule_id=$(cloudflare_find_rule_id "$ip")
  [[ -z "$rule_id" ]] && { info "cloudflare unblock skipped for $ip (no rule id)"; return; }
  url="https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/firewall/access_rules/rules/${rule_id}"
  if ! response=$(curl -sS -X DELETE "$url" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json"); then
    info "cloudflare unblock failed for $ip rule_id=$rule_id (curl error)"
    return
  fi
  parsed=$(cloudflare_parse_response <<<"$response")
  IFS='|' read -r status _ msg <<<"$parsed"
  if [[ "$status" == "ok" ]]; then
    info "cloudflare unblock applied: $ip rule_id=$rule_id reason=$reason"
  else
    info "cloudflare unblock failed for $ip rule_id=$rule_id: ${msg:-unknown error}"
  fi
}

current_rule_id=""
tmp_ban="$(mktemp)"
while IFS=$'\t' read -r ip ts rule_id; do
  [[ -z "$ip" ]] && continue
  if [[ "$ip" == "$IP" ]]; then
    current_rule_id="$rule_id"
    continue
  fi
  printf '%s\t%s\t%s\n' "$ip" "$ts" "$rule_id" >>"$tmp_ban"
done <"$BAN_FILE"
mv "$tmp_ban" "$BAN_FILE"

printf '%s SECURITY UNBAN %s reason=%s\n' "$(date --iso-8601=seconds)" "$IP" "$REASON" >>"$DECISIONS_LOG"
info "unban logged and local state cleared for $IP"

cloudflare_unblock "$IP" "$current_rule_id" "$REASON"
