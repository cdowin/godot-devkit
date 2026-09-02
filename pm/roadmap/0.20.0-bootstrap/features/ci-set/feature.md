---
id: 0.20.0/ci-set
milestone: "0.20.0"
name: install-ci writes the workflow set both consumers actually run
status: planning
reviewed:
phase: 2
depends_on: []
consumed_by: ["0.20.0/init-verb"]
---

# install-ci writes the workflow set both consumers actually run

What it makes true: `install-ci` writes the workflow SET both consumers actually run — `verify.yml`
(checkout, uv, `make milestone`), `uid-guard.yml`, `semver-gate.yml`, `auto-tag.yml` — as
devkit-owned files. Release, website, and social workflows (nullbound's `release.yml`,
`dispatch-website.yml`, `post-release-*.yml`) are the project's and are not written.

## Existing-construct audit

`install-ci` exists and writes one file nobody adopted; the three duplicated workflows are the
evidence of what a Godot project needs on push. Extend the verb; do not add a second.

## Ship criterion

Both consumers run the installed set; their hand-rolled `auto-tag` / `semver-gate` / `uid-guard`
are deleted; nullbound's `build-check.yml` and trail's `parse-and-smoke.yml` are either the
installed `verify.yml` or deleted as duplicates.
