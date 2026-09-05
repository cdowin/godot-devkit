---
id: 0.24.0/bugs/consumer-names-and-provenance-in-code
milestone: "0.24.0"
name: Code and comments name consumers and provenance — they must describe the utility, nothing else
status: fixed
caught_in: "0.23.0"
fix_milestone: "0.24.0"
---

# consumer-names-and-provenance-in-code

## FIXED in 0.24.0 — and the two-day gap is the lesson

Filed 2026-09-02 against 0.23.0. **0.23.0 shipped without fixing it**, and 0.24.0 was built on top.
Chris, 2026-09-04, arriving at the same place from the other direction — a release blocked because a
consumer's in-flight work reddened `make smoke`:

> *"delete/remove ANYTHING that knows anything about nullbound or trail. This is a completely project
> agnostic tool. Why did this EVER even creep in? That's insane. Should be in CLAUDE.md, should be a
> rule. This is a UTILITY for MANY projects."*

All three things this bug asked for landed together: every hit rewritten, the assertion widened into a
**gate** (`tests/test_consumer_independence.py` — 8 tests, watched red against HEAD, which named 25+
sites), and the rule written into `CLAUDE.md`. `tools/consumer_smoke.py` went with them — 971 lines
that made two private game repos a precondition for this package's tag.

**Why prose was not enough**, and why the gate is the actual fix: this bug WAS filed, WAS assigned a
fix milestone, and that milestone released anyway. Nothing checked. The guard found two more things on
its first run that no human pass had — a local variable named for a project in `pm/validate.py`'s cycle
walker, and the fact that its own patterns do not self-match.


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
