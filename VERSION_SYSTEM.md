# Version System Documentation

## Overview

KittyLog uses an automatic version numbering system that increments with every git commit. The version follows a simple `MAJOR.MINOR` format (e.g., 0.1, 0.2, 0.3).

## How It Works

1. **Version Storage**: The current version is stored in `version.txt` at the project root
2. **Auto-Increment**: A git `post-commit` hook automatically increments the version after each commit
3. **Version Display**: The version appears in the footer of every page (e.g., "KittyLog v0.2")

## Files Involved

- **`version.txt`**: Stores the current version number
- **`app/version.py`**: Python module that reads and exposes the version
- **`.git/hooks/post-commit`**: Git hook that auto-increments version after commits
- **`app/templates/base.html`**: Displays version in the UI footer

## The Post-Commit Hook

The hook runs automatically after every `git commit` and:

1. Reads the current version from `version.txt`
2. Increments the minor version number (0.1 → 0.2)
3. Writes the new version back to `version.txt`
4. Amends the last commit to include the version file change

**Important**: The hook uses `--amend` to include the version bump in your commit, so you won't see separate version bump commits.

## How to Use

### Normal Workflow

Just commit as usual - the version increments automatically:

```bash
git add .
git commit -m "Add new feature"
# Version automatically bumps from 0.1 to 0.2 in this commit
git push
```

### Manual Version Bump

If you want to manually set a version (e.g., for a major release):

1. Edit `version.txt` directly (e.g., change to `1.0`)
2. Commit the change
3. The hook will respect your manual version and continue from there

### Major Version Bumps

To increment the major version (e.g., 0.x → 1.0):

```bash
echo "1.0" > version.txt
git add version.txt
git commit -m "chore: bump to version 1.0"
# Next commit will be 1.1, 1.2, etc.
```

## Checking the Current Version

```bash
# From command line
cat version.txt

# From Python
python -c "from app.version import get_version; print(get_version())"

# In the UI
# Look at the footer of any page: "KittyLog v0.2"
```

## Disabling Auto-Increment

If you want to temporarily disable auto-versioning:

```bash
# Rename or remove the hook
mv .git/hooks/post-commit .git/hooks/post-commit.disabled
```

## Technical Details

### Why Post-Commit Instead of Pre-Push?

- **Post-commit**: Increments version immediately after each commit, included in the same commit via `--amend`
- **Pre-push**: Would create a separate commit for the version bump, requiring a second push

Post-commit is cleaner and ensures every commit has an updated version.

### Preventing Infinite Loops

The hook checks if the current commit message starts with "chore: bump version to" and skips execution to avoid infinite recursion.

### Integration with FastAPI

The version is loaded at application startup and:
- Exposed via `FastAPI(version=get_version())`
- Available in all templates as `{{ app_version }}`
- Displayed in the OpenAPI/Swagger docs at `/docs`

## Troubleshooting

### Version not incrementing?

Check if the hook is executable:
```bash
ls -la .git/hooks/post-commit
chmod +x .git/hooks/post-commit  # If needed
```

### Hook seems to run twice?

Make sure you're not running `git commit` from within the hook itself (infinite loop protection should catch this).

### Want to see version bump commits separately?

Switch to a pre-commit hook that creates separate commits (see git history for the old pre-push hook implementation).
