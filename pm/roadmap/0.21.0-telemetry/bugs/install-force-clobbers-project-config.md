---
id: 0.21.0/bugs/install-force-clobbers-project-config
milestone: "0.21.0"
name: install-hooks --force silently reverts a hook's documented project-config values, and four adoption defects found with it
status: open
caught_in: "0.21.0"
fix_milestone: "0.21.0"
---

# install-force-clobbers-project-config

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

Found adopting v0.20.0 in a consumer (2026-09-02):
(a) `install-hooks --force` reverted the hook's documented project-config values —
`WRAPPER_ROSTER`, `GATE_STATIC`, `PUSH_GATE`, `TRAILER` — with no warning; the consumer restored
all four by hand. A file that documents a project-config header must preserve it on re-install
(or refuse with a diff naming the values).
(b) the stock `WRAPPER_ROSTER` omits `make capture`, which `Makefile.devkit` itself defines.
(c) `verify.yml` installs uv only, then runs `make milestone`, which boots Godot and shells to
gdlint + shellcheck — green nowhere it is installed; the consumer added the toolchain steps.
(d) README documents `[rng] allowlist = {…}` / `[unit_disk] forbidden_calls` as inline tables
across lines — invalid TOML; a real allowlist needs `[rng.allowlist]` sub-table syntax the README
never shows.
(e) `check` has `[gates] extra`; `milestone` has no config hook, so a close-time-only gate
(`repo-hygiene`, which fails on any dirty tree and so cannot join `check`) has no sanctioned home.

## Root cause

Each its own; (a) is the one that loses data. Fix (a) with a preserved header block + a test that re-installs over an edited config and asserts the values survive; (b)–(e) one commit each with a test.

## Fix
