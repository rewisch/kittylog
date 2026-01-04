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
  LOOP_SLEEP=0   (set >0 to loop forever with sleep seconds)

Run once (cron-style):
  bash scripts/security_decider.sh

Run as a looping service (e.g., systemd):
  LOOP_SLEEP=5 bash scripts/security_decider.sh
USAGE
  exit 0
fi

# Tunables
ANON_LIMIT=${ANON_LIMIT:-15}
ANON_WINDOW=${ANON_WINDOW:-900}          # seconds
LOGIN_FAIL_LIMIT=${LOGIN_FAIL_LIMIT:-5}
LOGIN_FAIL_WINDOW=${LOGIN_FAIL_WINDOW:-3600}
WHITELIST_TTL=${WHITELIST_TTL:-43200}    # 12h
BAN_TTL=${BAN_TTL:-43200}                # avoid spammy duplicate bans
LOOP_SLEEP=${LOOP_SLEEP:-5}             # >0 to loop forever with sleep seconds

# Paths (override via env if needed)
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
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

declare -A STATIC_WL DYN_USER DYN_EXP ANON_COUNT ANON_TS FAIL_COUNT FAIL_TS LAST_BAN
REQUESTS_SEEN=0
AUTH_SEEN=0

info() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
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
  while IFS=$'\t' read -r ip ts; do
    [[ -z "$ip" || -z "$ts" ]] && continue
    LAST_BAN["$ip"]="$ts"
  done <"$BAN_FILE"
}

save_bans() {
  : >"$BAN_FILE"
  for ip in "${!LAST_BAN[@]}"; do
    echo -e "${ip}\t${LAST_BAN[$ip]}" >>"$BAN_FILE"
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
  if (( now - last < BAN_TTL )); then
    return
  fi
  LAST_BAN["$ip"]="$now"
  printf '%s SECURITY BAN %s reason=%s\n' "$(date --iso-8601=seconds)" "$ip" "$reason" >>"$DECISIONS_LOG"
  info "ban emitted: $ip reason=$reason"
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
