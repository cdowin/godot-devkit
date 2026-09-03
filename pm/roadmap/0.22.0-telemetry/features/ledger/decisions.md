Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.22.0/ledger The ledger — every status flip and every dispatch leaves a timestamped row — decisions

Durable. This log outlives the grain: it is where a choice and its rejected
alternative are recorded, and it survives close.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-09-03 — Append-only is a primitive ledger.py owns; the merge attribute ships from pm init

**Decision:** `ledger.append_row` opens the file in append mode itself and is the ONE writer in
`src/` outside `core/apply.py` allowed to; it never reads, never rewrites a byte. `core.apply` gains no
append plan. `.gitattributes` `pm/roadmap/*/ledger.jsonl merge=union` ships from `pm init`, not
`godot-devkit init`.
**Because:** a read-modify-write drops rows when two appenders collide (two milestone branches, an
async hook and a verb) and rewrites the bytes `merge=union` depends on nobody rewriting; append is a
different contract, not a variant of overwrite. The pattern is built from `[pm] roadmap_dir`, a key
`init.py` does not own, and a tracker-only repo never runs `godot-devkit init`.
**Rejected:** `Plan.append` in `core/apply.py` (a second write path through a module whose contract is
whole-file overwrite); widening `godot-devkit init`'s pinned roster now.
**Costs:** `tests/test_boundaries.py` must name `ledger.py`'s append as the one sanctioned exception
once its `_is_write_open` reads `Path.open` modes correctly (bug filed).
