# KittyLog

Tiny FastAPI app to log cat-care tasks via dashboard or QR codes. Config lives in `config/tasks.yml`, data in SQLite (`data/kittylog.db`).

## Run
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Visit `http://localhost:8000` (history at `/history`). DB and task types are created/updated on startup.

If running over cloudflare:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers 1

## Generate QR codes for tasks
```bash
pip install -r requirements.txt        # if not already installed
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
- Existing installs with a root-level `kittylog.db` are migrated automatically to `data/kittylog.db` (settings are rewritten to point to the new location).

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
