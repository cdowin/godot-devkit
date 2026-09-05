---
id: 0.24.0/bugs/fails-against-head-is-unprovable-by-the-obvious-spelling
milestone: "0.24.0"
name: "`tests/support` forces the worktree onto `sys.path`, so `PYTHONPATH=<old-src> pytest` silently proves nothing — the repo's own bar reports a false PASS"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# fails-against-head-is-unprovable-by-the-obvious-spelling

## Symptom

Found 2026-09-04 by the agent landing M1/M3 of `the-lifecycle-says-what-it-means`. It wrote two
tests, ran them the obvious way against the old source to watch them go red, saw them **pass**, and
only found out why by probing the harness rather than trusting it.

`tests/support/__init__.py:26`:

```python
sys.path.insert(0, str(REPO_ROOT / 'src'))
```

An `insert(0, …)` puts the **worktree's** `src/` ahead of everything, including an explicit
`PYTHONPATH`. So:

```
PYTHONPATH=<old-src> pytest tests/test_pm_ledger_report_sections.py
```

does not run the old source. It runs the edited one, and reports PASS. There is no error, no
warning, and nothing red anywhere — the command looks exactly like the one that would prove the
claim.

## Why this matters more here than in most repos

This package's own contract is that a fix ships with a test **watched red against HEAD**. Nearly
every CHANGELOG bullet in the last four releases states a count of the form *"11 watched red at
`aaec4bd`"*. That claim is produced by a command which, spelled the obvious way, cannot produce it.
Hard rule 4 forbids stating a measurement nobody made; the apparatus that makes the measurement has
been capable of fabricating it.

This is not a claim that any shipped bullet is wrong — the agent that found it did the work
correctly once it knew, and past authors may well have used the right spelling. It is a claim that
nothing in the repo **forces** the right spelling or notices the wrong one.

## The only correct spelling

```
git archive HEAD | tar -x -C <scratch>
cp <edited test modules> <scratch>/tests/
cd <scratch> && pytest tests/...
```

Copy the edited test modules into a clean extraction of HEAD and run there. Nothing on `sys.path`
can then reach the working tree.

## Why it was not fixed in 0.24.0

Deliberate, and the agent's reasoning is adopted. The natural fix is a make target, but an
"expect FAIL" target inverts the verdict line beside four real gates in `make gates`, and this was
found hours before a release tag. Introducing a gate whose PASS means a test FAILED, onto release
surface, on tag day, trades a documentation problem for a semantics problem.

## Fix

Not yet designed. Two candidates, neither costed:

1. **A `make watched-red FILES=…` target** that does the `git archive` dance and reports the
   before/after pair, keeping the inverted verdict inside one target that never joins `[checks] all`.
2. **Make `tests/support` stop forcing the path** — `insert(0, …)` → an `append`, or skip the
   insert when `PYTHONPATH` already names a `godot_devkit`. Smaller, but changes how every existing
   test resolves its import and needs the whole suite re-proven under it.

Whichever lands, the repair belongs with a CHANGELOG line, because the bar it protects is quoted in
every release.
