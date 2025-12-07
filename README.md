# KittyLog

KittyLog is a tiny QR-friendly FastAPI app for logging cat-care chores. It reads a YAML config for task types, syncs them to SQLite, and lets two people log events from either the dashboard or QR code URLs.

## Features
- FastAPI + SQLModel + SQLite; no external services required
- Config-driven task types (`config/tasks.yml`)
- QR flow with `auto=1` for one-tap logging and a confirm screen when needed
- Dashboard with quick log form plus last-seen info for each task
- History view with task/date filters
- Designed to run on a Raspberry Pi (or any Linux box) with Uvicorn

## Quickstart
1. Ensure Python 3.10+ is installed.
2. Install dependencies (includes `python-multipart` for form handling):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   # source .venv/bin/activate  # Linux/macOS/RPi
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
4. Open `http://localhost:8000` for the dashboard and `http://localhost:8000/history` for the event log.

The database (`kittylog.db`) is created automatically on first run. Task types from `config/tasks.yml` are created or updated at startup.

## Configuration (`config/tasks.yml`)
Each entry defines a task type:
```yaml
tasks:
  - slug: clean_litter
    name: "Cleaned litter box"
    icon: "🧹"
    color: "amber"
  - slug: feed
    name: "Fed the cat"
    icon: "🍽️"
    color: "blue"
```
- `slug`: unique identifier used in URLs and QR codes
- `name`: label shown in the UI
- `icon`: emoji or short text
- `color`: Tailwind color name (blue, amber, emerald, red, purple, etc.)
- `is_active`: stored in DB; new tasks default to `true`. You can temporarily hide tasks by toggling this column in the database without removing them from the config.

> Startup sync creates missing tasks and updates `name/icon/color` for existing slugs. It does not delete rows when you remove a task from the YAML.

## Logging tasks
- **Dashboard**: Press “Log now” on a card. Optional `who`/`note` fields are captured.
- **QR confirm**: `http://<host>:8000/q/<slug>` renders a confirm button.
- **QR auto**: `http://<host>:8000/q/<slug>?auto=1&who=Alex&note=lunch` instantly records the event.

`who` and `note` are optional in either flow and are saved on the event. Events record `source` as `web` or `qr`.

### Example QR URLs
- Auto-log feed: `http://pi.local:8000/q/feed?auto=1&who=Alex`
- Confirm screen for litter: `http://pi.local:8000/q/clean_litter`
- Auto with note: `http://192.168.1.42:8000/q/give_meds?auto=1&note=evening`

To generate a QR code image locally (no cloud):
```bash
python - <<'PY'
import qrcode
url = "http://pi.local:8000/q/feed?auto=1&who=Alex"
img = qrcode.make(url)
img.save("feed_qr.png")
print("Saved feed_qr.png")
PY
```
(`pip install qrcode[pil]` if you want this helper; not required for the app itself.)

## Run modes (test vs production)
- Local dev/test (hot reload):
  ```bash
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
- Production (no reload):
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
  ```
  Run inside `tmux`/`screen` or as a systemd service for persistence.

## History view
- Route: `/history`
- Filters: dropdown for task type plus start/end date inputs (inclusive)
- Displays relative time, who, note, and source for each event

## Running on Raspberry Pi
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd /path/to/kitty-log
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000  # add --reload during development
```
- Add `--reload` while developing; omit for production.
- Keep the service running with `tmux`/`screen` or a systemd unit (not included).
- Access from your LAN via `http://<pi-ip>:8000`.

## Repository layout
```
kittylog/
  app/
    main.py
    routes.py
    models.py
    database.py
    config_loader.py
    templates/
      base.html
      dashboard.html
      history.html
      qr_confirm.html
      success.html
    static/
      css/custom.css
  config/
    tasks.yml
  requirements.txt
  README.md
  kittylog.db  # created at runtime
```

## Notes
- Health check: `GET /health` returns `{"status":"ok"}`
- Tailwind is loaded via CDN; no Node build step.
- Default mode is dark with rounded cards and gradients; mobile-friendly layout is included.
- Add your own screenshots to `docs/` or the README after running the app (placeholders not committed).
