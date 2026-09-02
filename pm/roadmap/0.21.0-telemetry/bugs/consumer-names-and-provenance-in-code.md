---
id: 0.21.0/bugs/consumer-names-and-provenance-in-code
milestone: "0.21.0"
name: Code and comments name consumers and provenance — they must describe the utility, nothing else
status: open
caught_in: "0.21.0"
fix_milestone: "0.21.0"
---

# consumer-names-and-provenance-in-code

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

Chris, 2026-09-02: *"comments that reference things like 'trail's copy was the 115-line ancestor'.
We need to have code be project-agnostic. Comments and code should just be what is, and should
describe the utility."* Measured on `main` at v0.20.0 (word-bounded `nullbound`/`trail`, outside
`pm/` and `CHANGELOG.md`, which are history):

- `src/godot_devkit/repo/gates_extra.py` module docstring — "nullbound has …"
- `src/godot_devkit/repo/install.py` — the `install-hooks` next-step text twice: "(nullbound: a
  `hooks-self-test` target in …)"
- `README.md` — the `install-hooks` row cites a consumer's target by name
- 8 test files, 10 docstring/comment hits (e.g. `test_install.py` — "trail chmods `cc-*.sh` by
  glob, nullbound named two files") that explain a test by which consumer did what
- `installables/` — clean of names (the tests assert it) but the port-era comments say WHERE a
  function came from rather than WHAT it does; audit for "ported from", "the consumer's copy",
  "was the … ancestor" phrasing and rewrite to the utility.

## Root cause

The 0.19.0/0.20.0 ports were written as "port, don't redesign" and carried their provenance into
the text; the consumer-name assertion covers `installables/` only. Fix: (1) rewrite every hit to
describe the utility — a consumer's name never appears in `src/`, `README.md`, `USAGE.md` or a
test's prose (fixtures that deliberately model a consumer tree are data, named `consumer_a`-style,
never a real project); (2) widen the assertion to `src/**`, `README.md`, `USAGE.md`, and test
prose (docstrings + comments, not fixture paths) so it is a gate; (3) one line under `CLAUDE.md`
§ Provenance: comments describe what a thing does and why it is shaped so, never where it came
from or which consumer asked — git history is the provenance. `pm/` and `CHANGELOG.md` are
history and stay as written.

## Fix
