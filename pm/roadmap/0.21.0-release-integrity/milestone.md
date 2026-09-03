---
id: "0.21.0"
name: release-integrity
status: building
depends_on: []
branch: claude/godot-headless-sandbox-297qpr
---

# 0.21.0 — release-integrity

**Theme.** Filed 2026-09-03 from a nullbound cloud session. Two things a consumer's release loop did
that nobody could act on: `make check` — and so the pre-push hook — was red on every Linux container
because the import-cache runner's own self-test compared timestamps strictly and Linux stamps
same-tick files identically; and the shipped semver gate read three fields, so a hotfix
`0.90.3 → 0.90.3.1` compared as equal, a letter suffix crashed it, and a release that reached main
wearing the NEXT milestone's number (nullbound PR #56) was waved through. When this ships a Linux
container pushes through the same gate a Mac does, a merge to main must be a closed milestone or a
hotfix, and D8 lets a hotfix branch exist.

## Features

- `linux-cache-freshness` — `import_cache.sh` freshness is at-or-after, at nanosecond resolution.
- `release-gates` — `ci-semver-gate.yml` compares any length and admits a done milestone or a
  hotfix and nothing else; `check pm` D8 admits `<id>.N` on a released milestone.
- `ci-green` — `make milestone` is green under `make` and with shellcheck present, as CI runs it.
