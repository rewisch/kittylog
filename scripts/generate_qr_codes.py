#!/usr/bin/env python3
"""Generate QR codes for all configured tasks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

# Make app package importable when run directly.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from app.config_loader import TaskConfig, load_task_configs


def load_tasks(tasks_file: Path) -> list[TaskConfig]:
    """Load task configs from YAML."""
    if not tasks_file.exists():
        raise FileNotFoundError(f"Tasks file not found: {tasks_file}")
    return load_task_configs(tasks_file)


def build_task_url(base_url: str, slug: str, auto: bool) -> str:
    """Build the QR target URL."""
    trimmed_base = base_url.rstrip("/")
    query = {"auto": 1} if auto else {}
    query_str = f"?{urlencode(query)}" if query else ""
    return f"{trimmed_base}/q/{slug}{query_str}"


def create_qr(payload: str, box_size: int, border: int) -> qrcode.image.base.BaseImage:
    """Create a QR code image with a reasonable printable size."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")


def save_qr_codes(
    tasks: Iterable[TaskConfig],
    base_url: str,
    output_dir: Path,
    box_size: int,
    border: int,
) -> None:
    """Generate and save QR codes for each task."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for task in tasks:
        url = build_task_url(base_url, task.slug, auto=True)
        img = create_qr(url, box_size=box_size, border=border)
        filename = output_dir / f"qr_{task.slug}.png"
        img.save(filename)
        print(f"[ok] {task.slug}: {filename}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate QR codes for KittyLog tasks.")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the KittyLog server (e.g. http://localhost:8000).",
    )
    parser.add_argument(
        "--tasks-file",
        default=Path(__file__).resolve().parent.parent / "config" / "tasks.yml",
        type=Path,
        help="Path to tasks.yml.",
    )
    parser.add_argument(
        "--output-dir",
        default=Path(__file__).resolve().parent / "qr_codes",
        type=Path,
        help="Where to write PNG files.",
    )
    parser.add_argument(
        "--box-size",
        type=int,
        default=8,
        help="Pixel size per QR box (higher = larger image).",
    )
    parser.add_argument(
        "--border",
        type=int,
        default=4,
        help="Border size in boxes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = load_tasks(args.tasks_file)
    save_qr_codes(
        tasks=tasks,
        base_url=args.base_url,
        output_dir=args.output_dir,
        box_size=args.box_size,
        border=args.border,
    )


if __name__ == "__main__":
    main()
