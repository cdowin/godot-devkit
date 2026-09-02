---
id: 0.20.0/ci-set/install-ci-writes-the-set
feature: 0.20.0/ci-set
milestone: "0.20.0"
name: install-ci writes verify, uid-guard, semver-gate and auto-tag
status: todo
owner:
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
