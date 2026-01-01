from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Dict


# PBKDF2 parameters chosen to be slow enough for brute-force resistance while
# remaining fast for interactive logins on small hardware like a Raspberry Pi.
ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 310_000
SALT_BYTES = 16


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


def load_users(path: Path | None = None) -> Dict[str, str]:
    """Return {username: encoded_password} mapping; ignores malformed lines."""
    users_path = path or get_users_file_path()
    if not users_path.exists():
        return {}

    users: Dict[str, str] = {}
    with users_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            username, encoded = line.split(":", 1)
            username = username.strip()
            encoded = encoded.strip()
            if username and encoded:
                users[username] = encoded
    return users


def authenticate_user(username: str, password: str) -> bool:
    """Check provided credentials against the user store."""
    if ":" in username or not username:
        return False
    users = load_users()
    encoded = users.get(username)
    if not encoded:
        return False
    return verify_password(password, encoded)
