# Version System Documentation

## Overview

KittyLog uses **semantic versioning (semver)** with the format `MAJOR.MINOR.PATCH` (e.g., 0.1.0, 1.2.3).

This is the industry-standard approach used by npm, Python packages, and most modern software projects. Versions are bumped **manually** when you're ready to release, not automatically on every commit.

## Semantic Versioning

- **MAJOR** (X.0.0): Breaking changes, incompatible API changes
- **MINOR** (0.X.0): New features, backwards-compatible
- **PATCH** (0.0.X): Bug fixes, backwards-compatible

Example: `0.1.0` → `0.1.1` (bug fix) → `0.2.0` (new feature) → `1.0.0` (major release)

## Files Involved

- **`version.txt`**: Stores the current version (e.g., `0.1.0`)
- **`app/version.py`**: Python module that reads and exposes the version
- **`scripts/bump_version.py`**: Utility script to bump version (like `npm version`)
- **`app/templates/base.html`**: Displays version in the UI footer

## How to Bump Version

### Using the bump_version.py Script

```bash
# Show current version
python scripts/bump_version.py

# Bump patch version (0.1.0 -> 0.1.1) - for bug fixes
python scripts/bump_version.py patch

# Bump minor version (0.1.0 -> 0.2.0) - for new features
python scripts/bump_version.py minor

# Bump major version (0.1.0 -> 1.0.0) - for breaking changes
python scripts/bump_version.py major
```

The script will:
1. Update `version.txt`
2. Ask if you want to create a git commit
3. Create commit with message: `chore: bump version to X.Y.Z`

### Manual Version Update

You can also edit `version.txt` directly:

```bash
echo "1.0.0" > version.txt
git add version.txt
git commit -m "chore: release version 1.0.0"
```

## Typical Workflow

### For a Bug Fix Release

```bash
# Fix the bug
git add .
git commit -m "fix: resolve issue with cat selection"

# Bump patch version when ready to release
python scripts/bump_version.py patch
# Creates: "chore: bump version to 0.1.1"

git push
```

### For a New Feature

```bash
# Add the feature
git add .
git commit -m "feat: add dark mode support"

# Bump minor version when ready to release
python scripts/bump_version.py minor
# Creates: "chore: bump version to 0.2.0"

git push
```

### For a Major Release

```bash
# Make breaking changes
git add .
git commit -m "refactor!: redesign API endpoints"

# Bump major version
python scripts/bump_version.py major
# Creates: "chore: bump version to 1.0.0"

git push
```

## When to Bump Version

**DO bump version:**
- Before deploying to production
- When releasing to users
- After completing a feature or bug fix that's ready for release
- Following your release schedule (weekly, sprint-based, etc.)

**DON'T bump version:**
- On every commit (that's what git commits are for)
- For work-in-progress code
- During development before features are complete

## Checking Current Version

```bash
# From command line
cat version.txt

# Using the script
python scripts/bump_version.py

# From Python
python -c "from app.version import get_version; print(get_version())"

# In the UI
# Look at the footer of any page: "KittyLog v0.1.0"

# In API docs
# Visit /docs - version shown in OpenAPI spec
```

## Integration with CI/CD

If you use GitHub Actions or similar:

```yaml
# Example: Auto-bump patch version on push to main
- name: Bump version
  run: |
    python scripts/bump_version.py patch --no-commit
    git add version.txt
    git commit -m "chore: auto-bump version [skip ci]"
    git push
```

## Comparison to Other Approaches

### ✓ Manual Semver (Current)
- **Pros**: Industry standard, meaningful versions, full control
- **Cons**: Requires manual action
- **Best for**: Production software, user-facing apps

### ✗ Auto-increment on Every Commit (Previous)
- **Pros**: Fully automatic
- **Cons**: Version loses meaning, can cause loops, non-standard
- **Best for**: Internal build numbers only

### ✓ Git Tags
- **Pros**: Tied to git history, standard practice
- **Cons**: Requires separate tag management
- **Best for**: GitHub releases, open source projects

### ✓ Build Numbers from CI
- **Pros**: Automatic in CI/CD, unique per build
- **Cons**: Build numbers != version numbers
- **Best for**: Internal builds, combined with semver

## Advanced Usage

### Skip Git Commit

```bash
python scripts/bump_version.py patch --no-commit
# Updates version.txt but doesn't create commit
```

### Pre-release Versions

Edit `version.txt` manually for pre-release versions:
```
0.2.0-beta.1
0.2.0-rc.1
1.0.0-alpha
```

### Git Tags (Recommended for Releases)

```bash
# After bumping version
git tag v0.1.0
git push --tags
```

## Why This Approach?

1. **Industry Standard**: Same as npm, pip, cargo, etc.
2. **Meaningful**: Version numbers convey information about changes
3. **Controlled**: You decide when to bump, not the computer
4. **Simple**: Easy to understand and maintain
5. **Flexible**: Works with any workflow or CI/CD system

---

**Previous system note**: The old auto-increment-on-commit hook has been removed because it caused version loops and doesn't follow industry best practices.
