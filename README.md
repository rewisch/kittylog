# KittyLog

Tiny FastAPI app to log cat-care tasks via dashboard or QR codes. Config lives in `config/tasks.yml`, data in SQLite (`kittylog.db`).

## Run
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Visit `http://localhost:8000` (history at `/history`). DB and task types are created/updated on startup.

## Auth
- All routes except `/health` require login at `/login`.
- Set `KITTYLOG_SECRET_KEY` to a long random string (required in prod). Set `KITTYLOG_SESSION_SECURE=true` when served over HTTPS.
- Users file (default `config/users.txt`, override with `KITTYLOG_USERS_FILE`) stores `username:hash:active:failed_attempts`.
- Manage users:
  ```bash
  python manage_users.py alice            # add
  python manage_users.py alice --update   # change password/reactivate
  ```

## Tasks config (`config/tasks.yml`)
```yaml
tasks:
  - slug: feed
    name: "Fed the cat"
    icon: "🍽️"
    color: "blue"
```
Fields: `slug` (unique), `name`, `icon` (emoji/text), `color` (Tailwind color name), `is_active` (optional; defaults true). Edits sync on startup; removed tasks aren’t deleted from DB.

## Logging
- Dashboard buttons log tasks with optional `who`/`note`.
- QR confirm: `http://<host>:8000/q/<slug>`
- QR auto: `http://<host>:8000/q/<slug>?auto=1&note=lunch` (uses logged-in user)
- The top-right language toggle writes a `lang` cookie so navigation and forms stay in the chosen language.
