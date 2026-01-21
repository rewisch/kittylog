#!/usr/bin/env python3
"""
Bump version utility for KittyLog - similar to 'npm version'

Usage:
    python scripts/bump_version.py patch   # 0.1.0 -> 0.1.1
    python scripts/bump_version.py minor   # 0.1.0 -> 0.2.0
    python scripts/bump_version.py major   # 0.1.0 -> 1.0.0
    python scripts/bump_version.py         # Show current version
"""
import sys
import subprocess
from pathlib import Path


def get_version_file() -> Path:
    """Get path to version.txt"""
    return Path(__file__).resolve().parent.parent / "version.txt"


def read_version() -> tuple[int, int, int]:
    """Read and parse current version"""
    version_file = get_version_file()
    content = version_file.read_text().strip()
    parts = content.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {content}. Expected MAJOR.MINOR.PATCH")
    return int(parts[0]), int(parts[1]), int(parts[2])


def write_version(major: int, minor: int, patch: int) -> None:
    """Write new version to file"""
    version_file = get_version_file()
    version_str = f"{major}.{minor}.{patch}"
    version_file.write_text(version_str + "\n")
    return version_str


def bump_version(bump_type: str) -> str:
    """Bump version according to type (major, minor, patch)"""
    major, minor, patch = read_version()
    old_version = f"{major}.{minor}.{patch}"

    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid bump type: {bump_type}. Use: major, minor, or patch")

    new_version = write_version(major, minor, patch)
    print(f"Version bumped: {old_version} -> {new_version}")
    return new_version


def git_commit_version(version: str) -> None:
    """Create a git commit for the version bump"""
    try:
        subprocess.run(["git", "add", "version.txt"], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: bump version to {version}"],
            check=True
        )
        print(f"Created commit for version {version}")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Could not create git commit: {e}", file=sys.stderr)


def main():
    if len(sys.argv) == 1:
        # Show current version
        major, minor, patch = read_version()
        print(f"Current version: {major}.{minor}.{patch}")
        return

    bump_type = sys.argv[1].lower()
    if bump_type not in ("major", "minor", "patch"):
        print("Usage: python scripts/bump_version.py [major|minor|patch]")
        print("  major  - Bump major version (1.0.0 -> 2.0.0)")
        print("  minor  - Bump minor version (0.1.0 -> 0.2.0)")
        print("  patch  - Bump patch version (0.1.0 -> 0.1.1)")
        sys.exit(1)

    try:
        new_version = bump_version(bump_type)

        # Ask if user wants to commit
        if "--no-commit" not in sys.argv:
            response = input("Create git commit? [Y/n] ").strip().lower()
            if response in ("", "y", "yes"):
                git_commit_version(new_version)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
