#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUSH_KEYS_FILE="$REPO_ROOT/config/push_keys.yml"
RULES_FILE="$REPO_ROOT/config/notifications.yml"

if [[ ! -f "$PUSH_KEYS_FILE" ]]; then
  echo "Generating VAPID keys..."
  python "$REPO_ROOT/scripts/generate_vapid_keys.py" \
    --output "$PUSH_KEYS_FILE" \
    --subject "${KITTYLOG_VAPID_SUBJECT:-mailto:admin@example.com}"
else
  echo "VAPID keys already exist at $PUSH_KEYS_FILE"
fi

if [[ ! -f "$RULES_FILE" ]]; then
  cat <<'RULES' > "$RULES_FILE"
timezone: "Europe/Berlin"
window_minutes: 5
click_url: "/"

groups:
  morning-missing:
    title: "KittyLog reminder"
    message: "Still missing today: {tasks}."

rules:
  - id: "missing-feed-0900"
    time: "09:00"
    task_slug: "feed"
    if_not_logged_today: true
    group: "morning-missing"

  - id: "missing-water-0900"
    time: "09:00"
    task_slug: "water"
    if_not_logged_today: true
    group: "morning-missing"

events:
  - id: "cat-birthday"
    type: "cat_birthday"
    title: "KittyLog"
    message: "Birthday today: {cats}."

  - id: "cat-milestone"
    type: "cat_milestone"
    months: [6, 12, 24, 36, 60, 120]
    title: "KittyLog"
    message: "Milestones today: {items}."
RULES
  echo "Wrote sample rules to $RULES_FILE"
else
  echo "Notifications config already exists at $RULES_FILE"
fi

python - <<'PY'
from app.database import configure_engine, create_db_and_tables
from app.settings import load_settings

settings = load_settings()
configure_engine(settings.db_path)
create_db_and_tables()
print("Database ready for push notifications.")
PY

cat <<'NEXT'

Setup complete.
- Ensure the server is running over HTTPS.
- Add KittyLog to the phone's home screen, then enable notifications in the dashboard.
- Run the dispatcher on a schedule, e.g.:
  */1 * * * * /path/to/kittylog/.venv/bin/python /path/to/kittylog/scripts/dispatch_notifications.py
NEXT
