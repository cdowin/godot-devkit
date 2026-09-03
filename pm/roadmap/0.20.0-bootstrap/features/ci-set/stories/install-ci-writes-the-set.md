---
id: 0.20.0/ci-set/install-ci-writes-the-set
feature: 0.20.0/ci-set
milestone: "0.20.0"
name: install-ci writes verify, uid-guard, semver-gate and auto-tag
status: done
owner: developer
depends_on: []
---

# install-ci writes verify, uid-guard, semver-gate and auto-tag

## Goal
`install-ci` writes `verify.yml`, `uid-guard.yml`, `semver-gate.yml`, `auto-tag.yml`; `--diff` shows drift per file.
## Port
nullbound + trail `.github/workflows/{auto-tag,semver-gate,uid-guard}.yml` — diff the two copies first; where they differ, the devkit version is the union with a documented variable, never a project name.
## Verification
`make test` (install + diff round-trip on a fixture); `make gates`.
## Commit prefix
`feat(0.20.0/ci-set/S1):`
## Size
s

## Done

done: 60ad75c, b40af10 — the four workflows on `install-ci`. Unions: trail's
`contents: read` + `${X:-0}` version defaulting; `${{ }}` moved into `env:` so a
version string cannot be read as shell; the release dispatch is `RELEASE_WORKFLOW`
and its absence is a green "tagged only". `make tres-scan` dropped — `check tres`
is already in `check all`. Self-hosting is PARTIAL (only verify.yml applies here).
31 cases on a minimal indentation reader — the stdlib has no YAML parser — plus a
cross-check that every `run: make <target>` is one Makefile.devkit defines.
