# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KittyLog is a FastAPI-based web application for tracking cat care tasks. It features QR code scanning for quick task logging, web push notifications, multi-language support (English/German), and a PWA interface. The app uses SQLite for storage and is designed to run on small hardware like Raspberry Pi.

**Version**: The project uses automatic version numbering (see VERSION_SYSTEM.md). Version auto-increments on every commit via git post-commit hook.

## Development Commands

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the Server
```bash
# Development (with auto-reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Production (with logging and proxy headers)
uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --access-log \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-config config/logging.yml
```

### Testing
```bash
pip install -r requirements-dev.txt
pytest                    # Run all tests
pytest tests/test_auth_and_logging.py  # Run specific test file
pytest -v                 # Verbose output
pytest -k "test_name"     # Run tests matching pattern
```

### Running E2E Tests
```bash
# First-time setup
pip install -r requirements-dev.txt
playwright install chromium

# Run tests
pytest -m e2e                     # Run all E2E tests
pytest tests/e2e/test_e2e_login.py  # Run specific E2E test file
pytest -m "not e2e"               # Run only unit tests (exclude E2E)
HEADED=true pytest -m e2e         # Run with visible browser (for debugging)
```

#### E2E Test Overview

E2E tests use Playwright to test the application in a real browser. Unlike unit tests that use TestClient, E2E tests:
- Start a real uvicorn server on a random port
- Use isolated temporary databases
- Test actual user workflows (clicking, typing, navigation)
- Verify CSRF token handling and session management

**Test Coverage** (38 E2E tests, 100% pass rate):
- `tests/e2e/test_e2e_login.py` - Login/logout flows (2 tests)
- `tests/e2e/test_e2e_navigation.py` - Page navigation (1 test)
- `tests/e2e/test_e2e_task_logging.py` - Dashboard task logging (1 test)
- `tests/e2e/test_e2e_cats.py` - Cat CRUD operations (5 tests)
- `tests/e2e/test_e2e_history.py` - History filtering, CSV export, entry editing (7 tests)
- `tests/e2e/test_e2e_settings.py` - Settings page, language switching (4 tests)
- `tests/e2e/test_e2e_insights.py` - Statistics, date filtering (5 tests)
- `tests/e2e/test_e2e_qr_flows.py` - QR code confirmation and auto-logging (4 tests)
- `tests/e2e/test_e2e_validation.py` - Form validation, auth protection (6 tests)
- `tests/e2e/test_e2e_workflows.py` - Complex multi-step user workflows (3 tests)

#### When to Update E2E Tests

**IMPORTANT**: When making frontend changes, review and update E2E tests if you modify:

1. **HTML Structure Changes**:
   - Changed form action URLs → Update form selectors in tests
   - Renamed CSS classes or data attributes → Update selectors
   - Changed button text or icons → Update text-based selectors
   - Modified navigation links → Update navigation tests

2. **Feature Changes**:
   - Added new pages → Create new E2E tests
   - Modified workflows → Update workflow tests
   - Changed form fields → Update form interaction tests
   - Added/removed task types → Update task logging tests

3. **Selector Examples**:
   ```python
   # Form selectors
   page.click('button[data-cat-toggle-target="cat-create-panel"]')
   page.fill('form[action*="/cats"] input[name="name"]', "Fluffy")

   # Navigation selectors
   page.click('a[href*="/history"]')

   # Task form selectors
   page.click('form:has(input[name="slug"][value="feed"]) button[type="submit"]')
   ```

4. **Common Breakage Points**:
   - Changing `data-*` attributes used for toggles/targets
   - Modifying form action URLs
   - Renaming input field names
   - Changing button text (if tests use `text="Button"` selectors)
   - Updating URL paths or query parameters

#### Debugging E2E Test Failures

```bash
# Run in headed mode to see what's happening
HEADED=true pytest tests/e2e/test_e2e_cats.py -v

# Add debugging to test code
page.screenshot(path="debug.png")  # Capture current state
page.pause()                        # Interactive debugging

# Check selector validity
page.locator('your-selector').count()  # Should be > 0
```


### Dependency Management
```bash
# Update dependencies
pip-compile --upgrade
git diff requirements.txt  # Review changes
pip-sync
pytest                    # Verify tests still pass

# Security audit
pip-audit
```

### User Management
```bash
python scripts/manage_users.py alice           # Add new user
python scripts/manage_users.py alice --update  # Change password/reactivate
```

### QR Code Generation
```bash
python scripts/generate_qr_codes.py --base-url http://localhost:8000
```

### Push Notifications Setup
```bash
./scripts/setup_push_notifications.sh  # Generate VAPID keys and config
python scripts/dispatch_notifications.py  # Run notification dispatcher
```

## Architecture

### Application Structure

- **`app/main.py`**: FastAPI app initialization, middleware setup (sessions, security headers, request logging), and lifespan management (runs migrations and syncs task configs on startup)
- **`app/routes.py`**: All HTTP routes (dashboard, history, QR logging, cats, settings, push subscriptions)
- **`app/models.py`**: SQLModel definitions for TaskType, Cat, TaskEvent, PushSubscription, UserNotificationPreference, NotificationLog
- **`app/database.py`**: Engine configuration, session management, and legacy column migration helpers
- **`app/auth.py`**: PBKDF2-based password hashing, user file management (config/users.txt), rate limiting, CSRF token generation/validation
- **`app/config_loader.py`**: Loads and syncs task definitions from config/tasks.yml to the database
- **`app/migrations.py`**: Numbered migrations that run on startup (e.g., moving DB to data/ directory, normalizing usernames)
- **`app/i18n.py`**: Translation system supporting English and German
- **`app/settings.py`**: Loads config/settings.yml (db_path, default_language)
- **`app/push_config.py`**: Loads VAPID keys from config/push_keys.yml

### Data Flow

1. **Startup**: `lifespan()` in main.py runs migrations, loads settings, configures DB engine, creates tables, and syncs task configs from YAML
2. **Task Configuration**: config/tasks.yml defines task types (slug, name, icon, color, order, requires_cat). On startup, `sync_task_types()` creates/updates TaskType records and deactivates removed tasks
3. **Authentication**: Users stored in config/users.txt (username:hash:active:failed_attempts). Session middleware maintains login state. CSRF tokens protect state-changing requests
4. **Task Logging**: Routes accept form submissions (dashboard buttons) or QR scans (/q/&lt;slug&gt;). TaskEvent records link to TaskType and optionally to Cat
5. **Migrations**: Numbered migrations in migrations.py run once and are tracked in config/migrations.yml

### Key Patterns

- **Config over code**: Task types, notifications, and settings defined in YAML files under config/
- **Session-based auth**: SessionMiddleware with secure cookies (7-day expiry)
- **CSRF protection**: All POST routes validate CSRF tokens from session
- **Responsive design**: Jinja2 templates use Tailwind CSS (via CDN) for mobile-first UI
- **Progressive Web App**: Service worker and manifest enable installation and push notifications
- **i18n**: Language resolved from query param, cookie, or config; templates call `t(key, lang)`
- **Color assignment**: If tasks don't specify colors or reuse colors, config_loader assigns unique colors from a palette
- **Cat requirement**: Tasks with `requires_cat: true` enforce cat selection in UI and validation

### Database Schema Notes

- SQLite database defaults to data/kittylog.db
- TaskType.sort_order determines dashboard button order
- TaskEvent.deleted soft-deletes entries (hidden from history but retained)
- Cat.is_active flag filters active cats in dropdowns
- PushSubscription tracks Web Push endpoints per user
- NotificationLog deduplicates scheduled reminders per day/rule/group

### Security Considerations

- PBKDF2 with 310k iterations for password hashing (balanced for Raspberry Pi performance)
- Rate limiting: 10 attempts per 60 seconds per IP, 5 failed login attempts before account lockout
- CSRF tokens required for all POST requests
- Security headers: CSP, X-Frame-Options, HSTS, Referrer-Policy, X-Content-Type-Options
- Session cookies use secure flag when KITTYLOG_SESSION_SECURE=true
- User files (config/users.txt, config/kittylog.env) have restrictive permissions (0o600)

### Configuration Files

- **config/tasks.yml**: Task definitions (slug, name, icon, color, order, requires_cat)
- **config/settings.yml**: App settings (db_path, default_language)
- **config/users.txt**: User credentials (username:hash:active:failed_attempts)
- **config/kittylog.env**: Secret key and session security flag (auto-generated if missing)
- **config/logging.yml**: Uvicorn/app logging configuration
- **config/notifications.yml**: Push notification rules (created by setup script)
- **config/push_keys.yml**: VAPID public/private keys (created by setup script)
- **config/migrations.yml**: Tracks completed migrations

### Testing

Tests use pytest with fixtures in tests/conftest.py. Common patterns:
- FastAPI TestClient for route testing
- Temporary directories and databases for isolation
- Mock configuration files
- Session management helpers for authenticated requests

## Common Development Tasks

### Adding a New Task Type
1. Edit config/tasks.yml and add entry with slug, name, icon, order (optional color, requires_cat)
2. Restart server (changes sync automatically on startup)
3. No code changes needed

### Adding a New Route
1. Add route handler in app/routes.py
2. Use `require_user()` dependency for authenticated routes
3. Use `validate_csrf_token()` for state-changing POST requests
4. Templates go in app/templates/, static files in app/static/
5. Add translations to app/i18n.py TRANSLATIONS dict for both en/de

### Modifying the Database Schema
1. Update model in app/models.py
2. For new columns on existing tables: add migration in app/migrations.py or add to `_ensure_legacy_columns()` in database.py
3. SQLModel.metadata.create_all() handles new tables automatically
4. Run tests to verify schema changes work

### Changing Security Settings
- Password hashing iterations: Adjust ITERATIONS in app/auth.py
- Rate limits: Modify RATE_LIMIT_WINDOW, RATE_LIMIT_ATTEMPTS, MAX_FAILED_ATTEMPTS in app/auth.py
- Session duration: Change max_age in SessionMiddleware setup (app/main.py:95)
- CSP policy: Edit security_headers middleware in app/main.py

### Debugging
- Server logs: tail -f logs/kittylog.log logs/kittylog.access.log logs/kittylog.requests.log
- Request details logged with duration, user, IP in request_logger (app/main.py)
- Auth events logged to config/auth.log
- Use pytest -v for detailed test output
