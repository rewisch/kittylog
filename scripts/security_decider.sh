#!/usr/bin/env bash
# Lightweight decision-maker for KittyLog security: reads app/auth logs, manages
# a dynamic whitelist, and emits synthetic ban lines for Fail2ban or a firewall.


if [[ "${1:-}" =~ ^(-h|--help)$ ]]; then
  cat <<'USAGE'
KittyLog security decider
Reads logs, updates whitelist, and emits SECURITY BAN lines for Fail2ban/firewall.

Environment overrides (defaults shown):
  REQUEST_LOG=logs/kittylog.requests.log
  AUTH_LOG=logs/auth.log
  STATE_DIR=var/security
  DECISIONS_LOG=var/security.decisions.log
  STATIC_WHITELIST=var/security/whitelist_static.txt
  BAN_DURATION=86400 (unban + Cloudflare unblock after seconds)
  CLOUDFLARE_ZONE_ID=your_zone_id
  CLOUDFLARE_API_TOKEN=your_api_token
  LOOP_SLEEP=0   (set >0 to loop forever with sleep seconds)

Values are also read from config/kittylog.env if present.

Run once (cron-style):
  bash scripts/security_decider.sh

Run as a looping service (e.g., systemd):
  LOOP_SLEEP=5 bash scripts/security_decider.sh
USAGE
  exit 0
fi

# Paths (override via env if needed)
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
ENV_FILE=${ENV_FILE:-"$REPO_ROOT/config/kittylog.env"}
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

# Tunables
ANON_LIMIT=${ANON_LIMIT:-15}
ANON_WINDOW=${ANON_WINDOW:-900}          # seconds
LOGIN_FAIL_LIMIT=${LOGIN_FAIL_LIMIT:-5}
LOGIN_FAIL_WINDOW=${LOGIN_FAIL_WINDOW:-3600}
WHITELIST_TTL=${WHITELIST_TTL:-43200}    # 12h
BAN_TTL=${BAN_TTL:-43200}                # avoid spammy duplicate bans
BAN_DURATION=${BAN_DURATION:-86400}      # Cloudflare block lifetime (default 24h)
LOOP_SLEEP=${LOOP_SLEEP:-5}             # >0 to loop forever with sleep seconds
CLOUDFLARE_ZONE_ID=${CLOUDFLARE_ZONE_ID:-${CF_ZONE_ID:-}}
CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN:-${CF_API_TOKEN:-}}

REQUEST_LOG=${REQUEST_LOG:-"$REPO_ROOT/logs/kittylog.requests.log"}
AUTH_LOG=${AUTH_LOG:-"$REPO_ROOT/logs/auth.log"}
STATE_DIR=${STATE_DIR:-"$REPO_ROOT/var/security"}
STATIC_WHITELIST=${STATIC_WHITELIST:-"$STATE_DIR/whitelist_static.txt"}
DYNAMIC_WHITELIST=${DYNAMIC_WHITELIST:-"$STATE_DIR/whitelist_dynamic.tsv"}
ANON_FILE=${ANON_FILE:-"$STATE_DIR/anon_counts.tsv"}
FAIL_FILE=${FAIL_FILE:-"$STATE_DIR/fail_counts.tsv"}
BAN_FILE=${BAN_FILE:-"$STATE_DIR/bans.tsv"}
DECISIONS_LOG=${DECISIONS_LOG:-"$REPO_ROOT/var/security.decisions.log"}
REQUEST_OFFSET=${REQUEST_OFFSET:-"$STATE_DIR/requests.offset"}
AUTH_OFFSET=${AUTH_OFFSET:-"$STATE_DIR/auth.offset"}

mkdir -p "$STATE_DIR" "$(dirname "$DECISIONS_LOG")"
touch "$DECISIONS_LOG" "$ANON_FILE" "$FAIL_FILE" "$DYNAMIC_WHITELIST" "$BAN_FILE" "$REQUEST_OFFSET" "$AUTH_OFFSET"

declare -A STATIC_WL DYN_USER DYN_EXP ANON_COUNT ANON_TS FAIL_COUNT FAIL_TS LAST_BAN BAN_RULE_ID
REQUESTS_SEEN=0
AUTH_SEEN=0

info() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
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

raw = sys.stdin.read()
if not raw.strip():
    print("err||Empty response from API")
    sys.exit(0)

try:
    data = json.loads(raw)
except Exception as exc:
    snippet = raw.strip().replace("\n", " ")[:200]
    print(f"err||Invalid JSON ({exc}); body_snippet={snippet}")
    sys.exit(0)

rid = ""
result = data.get("result")
if isinstance(result, dict):
    rid = result.get("id", "")

status = "ok" if data.get("success") else "err"
msg = fmt_errors(data.get("errors")) or fmt_errors(data.get("messages"))
print(f"{status}|{rid}|{msg}")
PY
}

cloudflare_lookup_rule_id() {
  local ip="$1" url tmp http body parsed status rule_id msg
  cloudflare_configured || return 1
  url="https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/firewall/access_rules/rules"
  url="${url}?mode=block&configuration.target=ip&configuration.value=${ip}&page=1&per_page=50"
  tmp="$(mktemp)"
  if ! http=$(curl -sS -o "$tmp" -w '%{http_code}' -X GET "$url" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json"); then
    info "cloudflare lookup failed for $ip (curl error)"
    rm -f "$tmp"
    return 1
  fi
  body="$(cat "$tmp")"
  rm -f "$tmp"
  if [[ "$http" != "200" ]]; then
    local snippet="${body:0:200}"
    info "cloudflare lookup failed for $ip (http $http, body=${snippet:-<empty>})"
    return 1
  fi
  parsed=$(CLOUDFLARE_LOOKUP_IP="$ip" python - <<'PY' 2>/dev/null
import json, os, sys

ip = os.environ.get("CLOUDFLARE_LOOKUP_IP", "")
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as exc:
    print(f"err||lookup json error: {exc}")
    sys.exit(0)

rid = ""
for item in data.get("result") or []:
    cfg = item.get("configuration") or {}
    if cfg.get("target") == "ip" and cfg.get("value") == ip:
        rid = item.get("id", "") or ""
        break

status = "ok" if data.get("success") and rid else "err"
msg = ""
errors = data.get("errors") or data.get("messages") or []
if errors:
    msg = "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)
print(f"{status}|{rid}|{msg}")
PY
)
  IFS='|' read -r status rule_id msg <<<"$parsed"
  if [[ "$status" == "ok" && -n "$rule_id" ]]; then
    echo "$rule_id"
    return 0
  fi
  info "cloudflare lookup failed for $ip: ${msg:-no rule found}"
  return 1
}

cloudflare_record_existing_block() {
  local ip="$1" reason="$2" body="$3" rule_id
  [[ "$body" == *"duplicate_of_existing"* ]] || return 1
  if rule_id=$(cloudflare_lookup_rule_id "$ip"); then
    BAN_RULE_ID["$ip"]="$rule_id"
    info "cloudflare block already present: $ip rule_id=$rule_id reason=$reason"
  else
    info "cloudflare block already present for $ip but rule id not found"
  fi
  return 0
}

cloudflare_block_ip() {
  local ip="$1" reason="$2" note payload url http body parsed status rule_id msg tmp
  cloudflare_configured || return
  note="kittylog ${reason}"
  payload=$(printf '{"mode":"block","configuration":{"target":"ip","value":"%s"},"notes":"%s"}' "$ip" "$note")
  url="https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/firewall/access_rules/rules"
  tmp="$(mktemp)"
  if ! http=$(curl -sS -o "$tmp" -w '%{http_code}' -X POST "$url" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    --data "$payload"); then
    info "cloudflare block failed for $ip (curl error)"
    rm -f "$tmp"
    return
  fi
  body="$(cat "$tmp")"
  rm -f "$tmp"
  if [[ "$http" != "200" ]]; then
    if cloudflare_record_existing_block "$ip" "$reason" "$body"; then
      return
    fi
    local snippet="${body:0:200}"
    info "cloudflare block failed for $ip (http $http, body=${snippet:-<empty>})"
    return
  fi
  parsed=$(cloudflare_parse_response <<<"$body")
  IFS='|' read -r status rule_id msg <<<"$parsed"
  if [[ "$status" == "ok" && -n "$rule_id" ]]; then
    BAN_RULE_ID["$ip"]="$rule_id"
    info "cloudflare block applied: $ip rule_id=$rule_id reason=$reason"
  elif cloudflare_record_existing_block "$ip" "$reason" "$body"; then
    return
  elif cloudflare_record_existing_block "$ip" "$reason" "duplicate_of_existing"; then
    # fallback for empty/odd responses that might still be duplicates
    return
  else
    info "cloudflare block failed for $ip: ${msg:-unknown error}"
    # final attempt: if we suspect the block exists but parsing failed, try lookup
    if rule_id=$(cloudflare_lookup_rule_id "$ip"); then
      BAN_RULE_ID["$ip"]="$rule_id"
      info "cloudflare block assumed present after lookup: $ip rule_id=$rule_id reason=$reason"
    fi
  fi
}

cloudflare_unblock_ip() {
  local ip="$1" reason="$2" rule_id url http body parsed status msg tmp
  cloudflare_configured || return
  rule_id="${BAN_RULE_ID[$ip]:-}"
  if [[ -n "$rule_id" && ! "$rule_id" =~ ^[A-Za-z0-9]+$ ]]; then
    rule_id=""
  fi
  if [[ -z "$rule_id" ]]; then
    rule_id=$(cloudflare_lookup_rule_id "$ip") || true
    if [[ -z "$rule_id" ]]; then
      info "cloudflare unblock skipped for $ip (no rule id)"
      return
    fi
    BAN_RULE_ID["$ip"]="$rule_id"
  fi
  url="https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/firewall/access_rules/rules/${rule_id}"
  tmp="$(mktemp)"
  if ! http=$(curl -sS -o "$tmp" -w '%{http_code}' -X DELETE "$url" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json"); then
    info "cloudflare unblock failed for $ip rule_id=$rule_id (curl error)"
    rm -f "$tmp"
    return
  fi
  body="$(cat "$tmp")"
  rm -f "$tmp"
  if [[ "$http" != "200" ]]; then
    local snippet="${body:0:200}"
    info "cloudflare unblock failed for $ip rule_id=$rule_id (http $http, body=${snippet:-<empty>})"
    return
  fi
  parsed=$(cloudflare_parse_response <<<"$body")
  IFS='|' read -r status _ msg <<<"$parsed"
  if [[ "$status" == "ok" ]]; then
    info "cloudflare unblock applied: $ip reason=$reason"
    unset BAN_RULE_ID["$ip"]
  else
    info "cloudflare unblock failed for $ip rule_id=$rule_id: ${msg:-unknown error}"
  fi
}

ts_to_epoch() {
  local raw="$1"
  # auth log: 2026-01-03T08:29:50Z; request log: 2026-01-03 12:16:27,683
  local cleaned="${raw/,*/}"
  date -d "$cleaned" +%s 2>/dev/null || date +%s
}

read_new_lines() {
  local file="$1" offset_file="$2"
  [[ -f "$file" ]] || { echo "" >"$offset_file"; return; }
  local offset=0
  [[ -s "$offset_file" ]] && offset=$(cat "$offset_file")
  local size
  size=$(wc -c <"$file" 2>/dev/null || echo 0)
  (( offset > size )) && offset=0
  if (( size > offset )); then
    tail -c +"$((offset + 1))" "$file"
  fi
  echo "$size" >"$offset_file"
  return 0
}

load_static_whitelist() {
  [[ -f "$STATIC_WHITELIST" ]] || return 0
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs)"
    [[ -z "$line" ]] && continue
    STATIC_WL["$line"]=1
  done <"$STATIC_WHITELIST"
}

load_dynamic_whitelist() {
  while IFS=$'\t' read -r ip user expires; do
    [[ -z "$ip" || -z "$expires" ]] && continue
    DYN_USER["$ip"]="$user"
    DYN_EXP["$ip"]="$expires"
  done <"$DYNAMIC_WHITELIST"
}

save_dynamic_whitelist() {
  : >"$DYNAMIC_WHITELIST"
  for ip in "${!DYN_USER[@]}"; do
    echo -e "${ip}\t${DYN_USER[$ip]}\t${DYN_EXP[$ip]}" >>"$DYNAMIC_WHITELIST"
  done
}

prune_dynamic_whitelist() {
  local now="$1"
  for ip in "${!DYN_EXP[@]}"; do
    local exp=${DYN_EXP[$ip]:-0}
    if (( exp <= now )); then
      unset DYN_EXP["$ip"]
      unset DYN_USER["$ip"]
    fi
  done
}

load_counts() {
  local file="$1"; shift
  local -n counts=$1 tsmap=$2
  while IFS=$'\t' read -r ip count last; do
    [[ -z "$ip" || -z "$count" || -z "$last" ]] && continue
    counts["$ip"]="$count"
    tsmap["$ip"]="$last"
  done <"$file"
}

save_counts() {
  local file="$1"; shift
  local -n counts=$1 tsmap=$2
  : >"$file"
  for ip in "${!counts[@]}"; do
    echo -e "${ip}\t${counts[$ip]}\t${tsmap[$ip]}" >>"$file"
  done
}

prune_counts() {
  local -n counts=$1 tsmap=$2
  local window="$3" now="$4"
  for ip in "${!counts[@]}"; do
    local last=${tsmap[$ip]:-0}
    if (( now - last > window )); then
      unset counts["$ip"]
      unset tsmap["$ip"]
    fi
  done
}

load_bans() {
  while IFS=$'\t' read -r ip ts rule_id; do
    [[ -z "$ip" || -z "$ts" ]] && continue
    LAST_BAN["$ip"]="$ts"
    [[ -n "$rule_id" ]] && BAN_RULE_ID["$ip"]="$rule_id"
  done <"$BAN_FILE"
}

save_bans() {
  : >"$BAN_FILE"
  for ip in "${!LAST_BAN[@]}"; do
    echo -e "${ip}\t${LAST_BAN[$ip]}\t${BAN_RULE_ID[$ip]:-}" >>"$BAN_FILE"
  done
}

is_whitelisted() {
  local ip="$1" now="$2"
  [[ -n "${STATIC_WL[$ip]:-}" ]] && return 0
  local exp=${DYN_EXP[$ip]:-0}
  if (( exp > now )); then
    return 0
  fi
  return 1
}

whitelist_ip() {
  local ip="$1" user="$2" now="$3"
  local expires=$(( now + WHITELIST_TTL ))
  local prev_exp=${DYN_EXP[$ip]:-0}
  local action="add"
  (( prev_exp > now )) && action="refresh"
  DYN_USER["$ip"]="$user"
  DYN_EXP["$ip"]="$expires"
  info "whitelist ${action}: $ip user=$user ttl=${WHITELIST_TTL}s"
}

ban_ip() {
  local ip="$1" reason="$2" now="$3"
  is_whitelisted "$ip" "$now" && return
  local last=${LAST_BAN[$ip]:-0}
  local rule_id=${BAN_RULE_ID[$ip]:-}
  if (( now - last < BAN_TTL )); then
    if [[ -z "$rule_id" ]] && cloudflare_configured; then
      cloudflare_block_ip "$ip" "$reason"
    fi
    return
  fi
  if [[ -n "$rule_id" ]] && (( now - last < BAN_DURATION )); then
    return
  fi
  LAST_BAN["$ip"]="$now"
  printf '%s SECURITY BAN %s reason=%s\n' "$(date --iso-8601=seconds)" "$ip" "$reason" >>"$DECISIONS_LOG"
  info "ban emitted: $ip reason=$reason"
  cloudflare_block_ip "$ip" "$reason"
}

expire_bans() {
  local now="$1"
  for ip in "${!LAST_BAN[@]}"; do
    local last=${LAST_BAN[$ip]:-0}
    if (( now - last > BAN_DURATION )); then
      printf '%s SECURITY UNBAN %s reason=expired\n' "$(date --iso-8601=seconds)" "$ip" >>"$DECISIONS_LOG"
      cloudflare_unblock_ip "$ip" "expired"
      unset LAST_BAN["$ip"]
      unset BAN_RULE_ID["$ip"]
    fi
  done
}

process_requests() {
  mapfile -t lines < <(read_new_lines "$REQUEST_LOG" "$REQUEST_OFFSET")
  for line in "${lines[@]}"; do
    (( REQUESTS_SEEN++ ))
    [[ $line =~ ^([0-9-]+)\ ([0-9:.,]+)\ .*kittylog\.requests:\ ([^[:space:]]+)\ ([A-Z]+)\ ([^[:space:]]+)\ ([0-9]{3})\ .*user=([^[:space:]]+) ]] || continue
    local ts="${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
    local ip="${BASH_REMATCH[3]}"
    local path="${BASH_REMATCH[5]}"
    local status="${BASH_REMATCH[6]}"
    local user="${BASH_REMATCH[7]}"
    local now
    now=$(ts_to_epoch "$ts")

    prune_counts ANON_COUNT ANON_TS "$ANON_WINDOW" "$now"
    prune_counts FAIL_COUNT FAIL_TS "$LOGIN_FAIL_WINDOW" "$now"

    if [[ "$user" != "-" ]]; then
      whitelist_ip "$ip" "$user" "$now"
      continue
    fi

    ANON_COUNT["$ip"]=$(( ${ANON_COUNT["$ip"]:-0} + 1 ))
    ANON_TS["$ip"]="$now"
    if (( ANON_COUNT["$ip"] > ANON_LIMIT )); then
      ban_ip "$ip" "unauthenticated_requests" "$now"
    fi
  done
}

process_auth() {
  mapfile -t lines < <(read_new_lines "$AUTH_LOG" "$AUTH_OFFSET")
  for line in "${lines[@]}"; do
    (( AUTH_SEEN++ ))
    IFS=$'\t' read -r ts ip username status reason <<<"$line"
    [[ -z "$ip" || -z "$status" ]] && continue
    local now
    now=$(ts_to_epoch "$ts")
    prune_counts FAIL_COUNT FAIL_TS "$LOGIN_FAIL_WINDOW" "$now"

    if [[ "$status" == "OK" ]]; then
      whitelist_ip "$ip" "$username" "$now"
      continue
    fi

    FAIL_COUNT["$ip"]=$(( ${FAIL_COUNT["$ip"]:-0} + 1 ))
    FAIL_TS["$ip"]="$now"
    if (( FAIL_COUNT["$ip"] > LOGIN_FAIL_LIMIT )); then
      ban_ip "$ip" "login_failures" "$now"
    fi
  done
}

run_once() {
  REQUESTS_SEEN=0
  AUTH_SEEN=0
  load_static_whitelist
  load_dynamic_whitelist
  load_counts "$ANON_FILE" ANON_COUNT ANON_TS
  load_counts "$FAIL_FILE" FAIL_COUNT FAIL_TS
  load_bans

  local now
  now=$(date +%s)
  prune_dynamic_whitelist "$now"

  process_auth
  process_requests

  now=$(date +%s)
  prune_counts ANON_COUNT ANON_TS "$ANON_WINDOW" "$now"
  prune_counts FAIL_COUNT FAIL_TS "$LOGIN_FAIL_WINDOW" "$now"
  expire_bans "$now"

  save_dynamic_whitelist
  save_counts "$ANON_FILE" ANON_COUNT ANON_TS
  save_counts "$FAIL_FILE" FAIL_COUNT FAIL_TS
  save_bans

  if (( LOOP_SLEEP == 0 )) && [[ -t 1 ]] && (( REQUESTS_SEEN == 0 )) && (( AUTH_SEEN == 0 )); then
    echo "No new log lines processed. If running manually, ensure REQUEST_LOG and AUTH_LOG paths are correct or reset offsets."
  elif (( REQUESTS_SEEN > 0 )) || (( AUTH_SEEN > 0 )); then
    info "processed: requests=$REQUESTS_SEEN auth_lines=$AUTH_SEEN"
  fi
}

main() {
  if (( LOOP_SLEEP > 0 )); then
    while true; do
      run_once
      sleep "$LOOP_SLEEP"
    done
  else
    run_once
  fi
}

main "$@"
