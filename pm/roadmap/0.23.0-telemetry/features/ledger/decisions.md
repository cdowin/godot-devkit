Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.23.0/ledger The ledger — every status flip and every dispatch leaves a timestamped row — decisions

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

## D2 — 2026-09-03 — The terminal state show totals to is done for milestones, features and stories, and bug_states[-1] for bugs

**Decision:** `ledger.terminal_state(cfg, kind)` names `done` for the three grains and reads
`cfg.bug_states[-1]` for bugs. D8 said "the last state of its configured vocabulary"; the stock story
vocabulary is `todo wip review done blocked`, whose last entry is `blocked`.
**Because:** a total for a story that stalled and none for one that finished is the read-side sin
(Hard rule 4). `done` is what D2/D3/D5 already treat as terminal, so `show` agrees with the gate.
Reordering the tuple would change `pm vocabulary` output, a consumer contract.
**Rejected:** `[-1]` as built; reordering `DEFAULT_STORY_STATES`; a new config key.
**Costs:** a consumer whose story vocabulary lacks `done` never sees a total line.

## D3 — 2026-09-04 — `<synthetic>` is dropped from the model list at record time — a spelling, not a judgement

**Decision:** `transcript_summary` skips `message.model == "<synthetic>"` when it builds the model
list. The record is otherwise untouched: it counts as a `messages`, its `usage` sums, its blocks
count. A transcript whose ONLY assistant records are synthetic has no `model` key on its row — the
absence rule already in force for every field the source did not state. The exact token, never the
`<…>` shape.
**Because:** D4 ("the transcript is the raw record; never interpret `message.model`") is about not
second-guessing a real model identifier. `<synthetic>` is not one: Claude Code writes it on an
assistant record IT generated rather than received — an API-error notice, carrying an all-zero
`usage` and `isApiErrorMessage: true`. A bracketed pseudo-name is a spelling artifact, so excluding
it is not a judgement about which model ran, and it spares every future by-model consumer from
having to know the pseudo-name. Caught by the v0.23.0 release review (n2): a real orchestrator
transcript summed to `model: ["claude-fable-5-1", "<synthetic>"]`.
**Rejected:** keeping it raw and teaching a future by-model grouping to skip it (every consumer then
has to know the pseudo-name, and the first one that forgets reports a model that never ran).
Dropping the `<…>` SHAPE — a census of 734 real transcripts under `~/.claude/projects` found
`<synthetic>` (31 records) and no other bracketed value in this position, and a shape rule would
make the next pseudo-name vanish from the one field that would have reported it: narrowing the
census instead of reading it. Also rejected: dropping the whole RECORD, which would make a session's
`messages` quietly short.
**Costs:** one string this module knows by name, coupled to a Claude Code spelling — the same
coupling D4 already accepted, and the fixture pins it. A NEW pseudo-name will appear in a `model`
list until someone decides it here.
