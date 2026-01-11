# KittyLog

Tiny FastAPI app to log cat-care tasks via web-interface or QR codes. Config lives in `config/tasks.yml`, data in SQLite (`data/kittylog.db`).

## Run
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
sudo pacman -S gcc
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Visit `http://localhost:8000` 

DB and task types are created/updated on startup.

If running over cloudflare:
uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --workers 1

## Server logging
- Uvicorn/app logging is configured in `config/logging.yml`.
- Logs live in the `logs/` directory by default (`logs/kittylog.log`, `logs/kittylog.access.log`, `logs/kittylog.requests.log`). Change the filenames in `config/logging.yml` if you prefer `/var/log/kittylog/` (make sure the process can write there).
- Start the server with logging enabled (add `--reload` for dev):
  ```bash
  uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --access-log \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --log-config config/logging.yml
  ```
- Watch logs in real time: `tail -f logs/kittylog.access.log logs/kittylog.requests.log`.

## Generate QR codes for tasks
```bash
pip install -r requirements.txt
python scripts/generate_qr_codes.py --base-url http://localhost:8000
```
PNG files are written to `scripts/qr_codes`. Scan from a logged-in phone to auto-log the task.

Script options:
```
usage: generate_qr_codes.py [-h] --base-url BASE_URL [--tasks-file TASKS_FILE] [--output-dir OUTPUT_DIR] [--box-size BOX_SIZE] [--border BORDER]

Generate QR codes for KittyLog tasks.

options:
  -h, --help            show this help message and exit
  --base-url BASE_URL   Base URL of the KittyLog server (e.g. http://localhost:8000).
  --tasks-file TASKS_FILE
                        Path to tasks.yml.
  --output-dir OUTPUT_DIR
                        Where to write PNG files.
  --box-size BOX_SIZE   Pixel size per QR box (higher = larger image).
  --border BORDER       Border size in boxes.
```

## Auth
- All routes except `/health` require login at `/login`.
- Set `KITTYLOG_SECRET_KEY` to a long random string (required in prod). Set `KITTYLOG_SESSION_SECURE=true` when served over HTTPS.
- Users file (default `config/users.txt`, override with `KITTYLOG_USERS_FILE`) stores `username:hash:active:failed_attempts`.
- Manage users:
  ```bash
  python scripts/manage_users.py alice            # add
  python scripts/manage_users.py alice --update   # change password/reactivate
  ```

## Migrations
- Startup runs numbered migrations defined in `app/migrations.py` and records them in `config/migrations.yml`.

## Tasks config (`config/tasks.yml`)
```yaml
tasks:
  - slug: feed
    name: "Fed the cat"
    order: 1
    icon: "🍽️"
    color: "blue"
    requires_cat: true  # optional; forces selecting a cat when logging
```
Fields: `slug` (unique), `name`, `order` (integer for sorting), `icon` (emoji/text), `color` (Tailwind color name), `is_active` (optional; defaults true). Edits sync on startup; removed tasks aren’t deleted from DB.

Colors: If you omit `color` (or repeat colors), the app assigns unique colors per task from this palette: `amber`, `blue`, `cyan`, `emerald`, `fuchsia`, `green`, `indigo`, `lime`, `orange`, `pink`, `purple`, `red`, `rose`, `sky`, `teal`, `violet`, `yellow`.

## Push notifications (PWA)
KittyLog supports Web Push for users who add the app to their home screen (iOS 16.4+ / modern Android). Setup:

```bash
sudo pacman -S gcc
pip install -r requirements.txt
./scripts/setup_push_notifications.sh
```

This generates VAPID keys in `config/push_keys.yml`, creates a sample `config/notifications.yml`, and ensures DB tables exist. Edit `config/notifications.yml` to define reminder rules.

Run the dispatcher on a schedule (systemd timer).

After the server is running over HTTPS, add KittyLog to the phone home screen, open the Settings, and click “Enable notifications”.

## Cats
- Manage cats at `/cats` (name, color, birthday, chip ID, optional photo, active flag).
- When a task has `requires_cat: true` in `config/tasks.yml`, the dashboard and QR flow require selecting a cat; logging is rejected if no cat is provided.

## App settings (`config/settings.yml`)
```yaml
default_language: "en"  # options: en, de
```
Defaults to English if the file is missing or the value is unsupported.

## Logging
- Dashboard buttons log tasks with optional `who`/`note`.
- QR confirm: `http://<host>:8000/q/<slug>`
- QR auto: `http://<host>:8000/q/<slug>?auto=1&note=lunch` (uses logged-in user)
- The top-right language toggle writes a `lang` cookie so navigation and forms stay in the chosen language.

## Security banning/whitelist helper
- A bash “brain” at `scripts/security_decider.sh` reads `logs/kittylog.requests.log` + `logs/auth.log`, tracks anonymous hits and failed logins, maintains a dynamic whitelist, and writes synthetic `SECURITY BAN <ip>` lines to `var/security.decisions.log` by default (override with `DECISIONS_LOG`).
- If `CLOUDFLARE_ZONE_ID` and `CLOUDFLARE_API_TOKEN` are set (e.g., in `config/kittylog.env`), bans are pushed directly to Cloudflare firewall access rules; returned rule IDs are stored so they can be deleted automatically after `BAN_DURATION` seconds (default 24h). The log format stays the same for future Fail2ban use.
- Default rules: unauthenticated requests >5 in 15m → ban; login failures >5 in 1h → ban; successful login or API-key use → whitelist IP for 12h. Static allowlist defaults to `var/security/whitelist_static.txt` (one IP per line). State lives in `var/security/` by default (including `bans.tsv` with timestamps + Cloudflare rule IDs); override paths/limits via env vars.
- Run via cron every minute or as a service. For a continuous loop under systemd, set `Environment=LOOP_SLEEP=5` (seconds).
- Fail2ban: drop `config/fail2ban/kittylog-security.conf` into `/etc/fail2ban/jail.d/` and `config/fail2ban/filter.d/kittylog-security.conf` into `/etc/fail2ban/filter.d/`, then `systemctl reload fail2ban`. Default `logpath` is the repo-local `var/security.decisions.log`; adjust if you relocate `DECISIONS_LOG`.
- Manual unblock: you can also delete Cloudflare rules yourself using the stored rule ID in `var/security/bans.tsv` if needed; the decider will remove expired rules automatically after `BAN_DURATION`.