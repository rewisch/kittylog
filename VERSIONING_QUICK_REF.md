# Version Bumping - Quick Reference

## Current Version
```bash
cat version.txt
# or
python scripts/bump_version.py
```

## Bump Version

### Bug Fix (0.1.0 → 0.1.1)
```bash
python scripts/bump_version.py patch
```

### New Feature (0.1.0 → 0.2.0)
```bash
python scripts/bump_version.py minor
```

### Breaking Change (0.1.0 → 1.0.0)
```bash
python scripts/bump_version.py major
```

## Typical Release Workflow

```bash
# 1. Develop and commit your changes
git add .
git commit -m "feat: add awesome feature"

# 2. When ready to release, bump version
python scripts/bump_version.py minor
# This creates: "chore: bump version to 0.2.0"

# 3. Push everything
git push

# 4. (Optional) Tag the release
git tag v0.2.0
git push --tags
```

## Semantic Versioning Cheat Sheet

| Change Type | Example | Bump Type | Result |
|-------------|---------|-----------|--------|
| Bug fix | Fix cat selector | `patch` | 0.1.0 → 0.1.1 |
| New feature | Add dark mode | `minor` | 0.1.0 → 0.2.0 |
| Breaking change | Redesign API | `major` | 0.1.0 → 1.0.0 |

## Notes

- Version is displayed in the footer of all pages
- Version is stored in `version.txt`
- Script will prompt to create a git commit (press Y or Enter)
- Use `--no-commit` flag to skip git commit

---

For full documentation, see [VERSION_SYSTEM.md](VERSION_SYSTEM.md)
