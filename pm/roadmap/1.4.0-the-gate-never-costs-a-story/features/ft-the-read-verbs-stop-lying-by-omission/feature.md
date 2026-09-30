---
id: ft-the-read-verbs-stop-lying-by-omission
kind: feature
milestone: "1.4.0"
name: the read verbs stop lying by omission
status: building
reviewed: docs/reviews/2026-09-29-1.4.0-the-read-verbs-stop-lying-by-omission.md
depends_on: []
consumed_by: []
changelog:
---

# the read verbs stop lying by omission

Issues: #19, #28, #30, #35 (Python side).

The Python side has three rule-4 defects and one lock:

- **#19** `refs spawn_handler_changed` reported ZERO references. The live subscriber connects
  `entity.spawn_handler_changed` on an untyped parameter. A reviewer filed a delete finding on that
  zero.
- **#30** `check rng` flags `func randf() -> float:` (a DECLARATION on a seeded-stream owner) as a
  bare draw.
- **#28** `install.retired_line()` reads `[checks] godot` with its own fallback `('uid',)`, so it
  disagrees with `cli.all_roster()`, whose default is all eight gates and which refuses unknown
  names. The review's MN4: the install-runners exit-2 refusal on a malformed value has no test.
- **#35** The Python git reads (`core/project.py`, `read/orphans.py`, `read/scene_diff.py`) can take
  the optional index lock.

## Decided (do not re-plan)

- **refs (#19).** Add a bucket for textual hits the typed index cannot resolve:
  `<expr>.<name>.connect(`, `<expr>.<name>.disconnect(`, `<expr>.<name>.emit(`,
  `emit_signal(&"<name>"` / `emit_signal("<name>"`, and `connect("<name>"`. They print under their
  own heading (`dynamic (untyped receiver)`). The bucket skips a hit already counted as a typed
  reference, so nothing is double-counted. A zero verdict prints only when BOTH buckets are empty;
  when only the dynamic one has hits, the summary says the typed count is zero and names the
  dynamic count. Read output must stay valid write input: `--retarget` does not act on dynamic
  hits and says so. README row and CHANGELOG. Minor bump.
- **rng (#30).** A `func <name>(` declaration line is never a draw. Inside a script that DECLARES
  `func randf` (or any other draw name), an unqualified `randf()` calls the script's own method and
  is not flagged either. Qualified `_rng.randf()` is unchanged, and so is a bare `randf()` in a
  script that does not declare it. A stale `[rng] allowlist` entry naming such a line is then
  reported stale by the existing CHECK 3, which is the intended prune path.
- **roster (#28).** Move `KNOWN_GATES`, `OPT_IN_GATES` and `all_roster()` out of `cli.py` into a
  module under `godot/` (for example `godot/checks/roster.py`, your call) that both `cli.py` and
  `godot/install.py` import. `retired_line()` uses `all_roster()`, so a malformed or unknown
  `[checks] godot` exits 2 there exactly as `check all` does, and an absent key means all eight
  (which includes `uid`). Add the MN4 row to `tests/test_runners_installable.py`.
- **locks (#35).** Every git subprocess the package spawns runs with `GIT_OPTIONAL_LOCKS=0` in its
  env. If one helper already runs git, put it there. Otherwise add the smallest shared helper in
  `core/`. Rule: `core/` imports nothing from `godot/`.
- One test per defect, the cheapest altitude (a function call, not a process): the refs dynamic
  bucket, rng declaration + self-method, roster agreement, and the MN4 exit 2.

## Ship criterion

- `refs <signal>` on a fixture where the only subscriber is `untyped.<signal>.connect(` prints it
  under the dynamic bucket and does not print a zero verdict.
- `check rng` on the #30 repro file reports nothing; a bare `randf()` elsewhere still reports.
- `[checks] godot = ["uid", "tress"]` makes install-runners exit 2 exactly as `check all` does.
- `make pyunit` green.

## Proof budget

  cases: 4 (one per defect; #35 is proven by reading the code, not by a test)
  tier: pyunit
  lands in: tests/test_refs*.py, tests/test_check_rng*.py (or the existing module), tests/test_runners_installable.py
  what already covers this: refs typed cases and rng bare-draw cases; amend those modules
