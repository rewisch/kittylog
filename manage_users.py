#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from app.auth import encode_password, get_users_file_path, load_users


def write_users(users: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for username, encoded in sorted(users.items()):
            f.write(f"{username}:{encoded}\n")


def prompt_password() -> str:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    if not password:
        raise ValueError("Password must not be empty.")
    return password


def add_or_update_user(username: str, path: Path, *, allow_update: bool) -> None:
    if ":" in username or not username:
        raise ValueError("Username must be non-empty and cannot contain ':'.")

    users = load_users(path)
    if username in users and not allow_update:
        raise ValueError(f"User '{username}' already exists. Use --update to overwrite.")

    password = prompt_password()
    users[username] = encode_password(password)
    write_users(users, path)
    print(f"Saved user '{username}' to {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage KittyLog users")
    parser.add_argument("--file", type=Path, default=get_users_file_path(), help="Path to users file")
    parser.add_argument("username", help="Username to add or update")
    parser.add_argument("--update", action="store_true", help="Update password if user exists")
    args = parser.parse_args(argv)

    try:
        add_or_update_user(args.username, args.file, allow_update=args.update)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
