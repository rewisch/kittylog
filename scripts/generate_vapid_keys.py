#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import base64
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.push_config import DEFAULT_PUSH_KEYS_PATH  # noqa: E402


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_keys() -> tuple[str, str]:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: WPS433
    except ImportError as exc:
        raise RuntimeError("cryptography is required. Install requirements first.") from exc

    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.private_numbers()
    private_bytes = numbers.private_value.to_bytes(32, "big")
    public_numbers = numbers.public_numbers
    x = public_numbers.x.to_bytes(32, "big")
    y = public_numbers.y.to_bytes(32, "big")
    public_bytes = b"\x04" + x + y
    return _b64url(public_bytes), _b64url(private_bytes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate VAPID keys for KittyLog push")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PUSH_KEYS_PATH,
        help="Path to write push_keys.yml",
    )
    parser.add_argument(
        "--subject",
        default="mailto:admin@example.com",
        help="VAPID subject (mailto: or https URL)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing keys")
    args = parser.parse_args(argv)

    output_path: Path = args.output
    if output_path.exists() and not args.force:
        print(f"{output_path} already exists. Use --force to overwrite.")
        return 0

    public_key, private_key = generate_keys()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "vapid_public_key": public_key,
        "vapid_private_key": private_key,
        "vapid_subject": args.subject,
    }
    output_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    print(f"Wrote VAPID keys to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
