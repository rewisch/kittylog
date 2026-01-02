from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Dict, TypedDict, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

# PBKDF2 parameters chosen to be slow enough for brute-force resistance while
# remaining fast for interactive logins on small hardware like a Raspberry Pi.
ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 310_000
SALT_BYTES = 16
MAX_FAILED_ATTEMPTS = 5
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_ATTEMPTS = 10


class UserRecord(TypedDict):
    encoded: str
    active: bool
    failed_attempts: int


_rate_limit_cache: dict[str, list[float]] = {}


def get_users_file_path() -> Path:
    """Return configured users file path (env override or config/users.txt)."""
    env_path = os.getenv("KITTYLOG_USERS_FILE")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / "config" / "users.txt"


def encode_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_hex(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"{ALGORITHM}${iterations}${salt}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iter_str, salt, stored_hash = encoded.split("$", 3)
        iterations = int(iter_str)
    except ValueError:
        return False
    if algo != ALGORITHM or iterations <= 0 or not salt or not stored_hash:
        return False

    computed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(computed.hex(), stored_hash)


def load_users(path: Path | None = None) -> Dict[str, UserRecord]:
    """Return {username: UserRecord} mapping; ignores malformed lines."""
    users_path = path or get_users_file_path()
    if not users_path.exists():
        return {}

    users: Dict[str, UserRecord] = {}
    with _locked(users_path, "r") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            parts = line.split(":", maxsplit=3)
            if len(parts) < 2:
                continue
            username, encoded = parts[0].strip(), parts[1].strip()
            active = True
            failed_attempts = 0
            if len(parts) >= 3 and parts[2]:
                active = parts[2].strip() != "0"
            if len(parts) == 4 and parts[3]:
                try:
                    failed_attempts = int(parts[3].strip())
                except ValueError:
                    failed_attempts = 0
            if username and encoded:
                users[username] = {
                    "encoded": encoded,
                    "active": active,
                    "failed_attempts": max(failed_attempts, 0),
                }
    return users


def save_users(users: Dict[str, UserRecord], path: Path | None = None) -> None:
    users_path = path or get_users_file_path()
    users_path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(users_path, "w") as f:
        for username, record in sorted(users.items()):
            active_flag = "1" if record["active"] else "0"
            fails = max(record.get("failed_attempts", 0), 0)
            f.write(f"{username}:{record['encoded']}:{active_flag}:{fails}\n")


def authenticate_user(username: str, password: str) -> bool:
    """Check provided credentials against the user store."""
    if ":" in username or not username:
        return False
    users = load_users()
    record = users.get(username)
    if not record or not record["active"]:
        return False
    if verify_password(password, record["encoded"]):
        if record["failed_attempts"] != 0:
            record["failed_attempts"] = 0
            save_users(users)
        return True

    record["failed_attempts"] += 1
    if record["failed_attempts"] > MAX_FAILED_ATTEMPTS:
        record["active"] = False
    save_users(users)
    return False


def check_rate_limit(key: str) -> bool:
    """Return True if under limit; False if blocked."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    history = _rate_limit_cache.get(key, [])
    history = [ts for ts in history if ts >= window_start]
    if len(history) >= RATE_LIMIT_ATTEMPTS:
        _rate_limit_cache[key] = history
        return False
    history.append(now)
    _rate_limit_cache[key] = history
    return True


def log_auth_event(username: str, ip: str, success: bool, reason: str | None = None) -> None:
    """Append a simple audit line to config/auth.log (best-effort)."""
    log_path = Path(__file__).resolve().parent.parent / "config" / "auth.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{ip}\t{username}\t{'OK' if success else 'FAIL'}"
    if reason:
        line += f"\t{reason}"
    line += "\n"
    try:
        with _locked(log_path, "a") as f:
            f.write(line)
    except OSError:
        pass


class _LockedFile:
    def __init__(self, path: Path, mode: str):
        self.path = path
        self.mode = mode
        self.handle: Optional[object] = None

    def __enter__(self):
        self.handle = self.path.open(self.mode, encoding="utf-8")
        if fcntl:
            lock_type = fcntl.LOCK_SH if "r" in self.mode else fcntl.LOCK_EX
            fcntl.flock(self.handle, lock_type)
        return self.handle

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            if fcntl:
                fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


def _locked(path: Path, mode: str) -> _LockedFile:
    return _LockedFile(path, mode)
