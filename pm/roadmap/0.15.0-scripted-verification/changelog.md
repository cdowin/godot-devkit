Append with `godot-devkit pm changelog <milestone-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.15.0 scripted verification — changelog

Durable. What was built that a player cares about, in the words a player would
use. It survives close: a milestone's notes matter most once it has shipped.

> One entry per thing somebody would notice, and a reference proving it landed.
> The reasoning behind it is a decision, not a release note — that goes in
> `decisions.md`. `pm changelog --render` unions every milestone's log, newest
> first, and this file is the only place its entries come from.

## C1 — 2026-08-29 — one word to verify any repo
**What:** Run `godot-devkit task quick` after a change and `godot-devkit task verify` before a release — in any repo that pins this toolkit, without learning its target names.
**Evidence:** src/godot_devkit/repo/tasks.py

## C2 — 2026-08-29 — a gate on the shortcut itself
**What:** `godot-devkit check tasks` fails the day a project renames a target its [tasks] table still points at, instead of the day an agent needed it.
**Evidence:** tests/test_tasks.py:88

## C3 — 2026-08-29 — consumer smoke is a target
**What:** `make smoke` runs every read verb against the live game checkouts, compares each printed census against an independent count, and fails if it leaves either checkout dirty.
**Evidence:** tools/consumer_smoke.py

## C4 — 2026-08-29 — the fuzzers are code now
**What:** The CommonMark differential (60,000 documents), the log-schema differential (692 logs) and the migration replay run from `make fuzz` in two seconds, instead of being rebuilt on demand.
**Evidence:** tests/test_fuzz_markdown.py
