---
id: 0.24.0/the-lifecycle-says-what-it-means
milestone: "0.24.0"
name: A grain says which half of its life it is in
status: reviewing
reviewed:
phase: 3
depends_on: []
consumed_by: []
---

# A grain says which half of its life it is in

`done` currently means *the features are closed* — reached with the changelog unwritten and the
release unreviewed, because the release protocol says so out loud: step 3 is **"Close the milestone —
before the render, not after"**, with the retitle at step 4 and the tag at step 5.

Chris, 2026-09-04: *"The milestone should only be moved to `done` after EVERYTHING is finished.
Changelog written, reviewers all done. Done."*

## `done` does NOT mean shipped, and it cannot

Chris settled this and it is the load-bearing definition here:

> *"done and shipped always have this weird relationship. `done` gets flipped when everything is
> done. Changelog written, reviewers all done. Done does not necessarily mean shipped — that's a
> branching/PR/push thing that's outside the scope of the pm tree."*

**The flip is itself a commit that has not shipped at the moment it is written.** `pm milestone done`
edits a string in a file; that edit needs a commit and a push. So a `done` that meant *shipped* would
be unrepresentable — the tree can never observe its own release.

So the terminal state means: **everything inside the PM tree's authority is finished.** Changelog
written, reviews closed, findings landed, gates green, nothing left to do. Branch, PR, merge and tag
are git events, outside the tree, after `done`.

That is what makes the lifecycle work rather than just longer: `packaging` is where the changelog and
version work HAPPENS, `done` says that work is COMPLETE, and the ship follows. Neither state has to
lie.

**One vocabulary, seven states, across milestone / feature / story:**

```
planning → ready → building → reviewing → accepted → packaging → done
```

Transitions stay open — this package has never had a transition graph and does not grow one here. A
grain uses the states it needs and skips the rest: *"packaging a feature is different from packaging
a milestone. A story may skip packaging."*

## The deadlock this fixes, reproduced 2026-09-04

Closing 0.24.0 with all three features `done` and the milestone still `building`, `make milestone`
failed in **1.1 seconds** at `gates`, before the matrix or the smoke ran:

```
DRIFT  milestone 0.24.0 is 'building' but all 3 features are done (should be done)
[GATES] FAIL (exit 1) — 3 check(s) PASS
```

So the release gate could not run until the milestone was flipped `done` — the decision that gate
exists to inform. Filed as `bugs/the-release-gate-cannot-run-before-the-close-it-gates`; this feature
is its fix.

## D5 is the rule that actually breaks, and D6 is only a message

Scoped against `checks/pm.py`. The model's own comment says what is enforced:
*"no rule checks an EDGE … What IS checked is END STATE, by D3/D4/D5."*

- **D4** (`status in cfg.*_states`) — pure vocabulary. Extending the sets is free.
- **D3** (`mstat == 'done' and feature != 'done'`) — survives, and gets STRONGER: a milestone cannot
  be `done` unless every feature is, and `done` now means shipped.
- **D5** (`sstat == 'done' and feature != 'done'`) — **breaks.** Under the new lifecycle a story
  reaches `done` while its feature is still `reviewing` / `accepted` / `packaging`. That is the
  normal path, and D5 would report it as drift on every feature in every tree.

**D5's fix is the payoff of using ONE vocabulary for all three grains.** Today a story's `wip` and a
feature's `building` are different words, so "is this story ahead of its feature?" cannot be asked.
With one ordered vocabulary it becomes a well-defined comparison — a grain is drifting when it sits
AHEAD of its parent, not when it fails to equal it. D5 becomes:

> a story at `done` under a feature still at `planning` or `ready` is two places disagreeing;
> `building` onward is not.

D3 reads the same way, one grain up. Neither rule needs a transition graph — both stay end-state
checks, which is what this package already committed to.

**D6 needs no new logic.** `checks/pm.py:188` keys off the literal string:

```python
if ('D6' in enabled and mstat == 'building' and feat_total > 0 and feat_done_n == feat_total):
```

The moment a milestone moves to `reviewing`, D6 goes quiet and the gate runs. Its message must stop
saying "should be done" — the truthful reading is *you finished the features and are still calling
it building*.

## The migration, measured across all three trees

| from | to | grains | why |
|---|---|---|---|
| `todo` (story) | `ready` | 66 | These are PO-written, dispatch-ready stories. `planning` would assert they are still being shaped, which is less true than `ready`. |
| `review` (feature) | `reviewing` | 9 | Rename only. |
| `wip` (story) | `building` | **0** | Transient; none in any tree right now. |
| `blocked` (story) | — | **0** | Declared and never used in any of the three trees. It dies with its last reader — which there never was. |
| `done` | `done` | 427 | Untouched. |

Bug states (`open` / `fixed` / `closed`) are a different machine and do **not** change.

**Not ours:** trail carries 8 grains at `active`, a status in no devkit default set — pre-existing
drift in that repo, surfaced by this census and left for trail's own session.

## Scope

| File | Action | Purpose |
|---|---|---|
| `repo/pm/model.py` | MODIFY | The three `DEFAULT_*_STATES` become the one seven-state vocabulary. |
| `repo/checks/pm.py` | MODIFY | D6's message stops claiming `done` is the only next state. |
| `repo/pm/cli.py` | MODIFY | `pm vocabulary` reports the new sets; usage text follows. |
| `.claude/skills/release/SKILL.md` | MODIFY | Re-ordered, not re-worded: run the gate at `accepted`, render the notes at `packaging`, flip `done` when that work is complete, THEN branch/PR/merge/tag. Step 3's "close before the render" inverts and becomes the last PM action rather than an early one. |
| this repo's own `pm/roadmap/**` | MODIFY | 4 `todo` grains migrate. |
| `tests/` | MODIFY | The vocabulary, D6's wording, and the migration mapping. |

## Ship criterion

`0.24.0` itself walks `building → reviewing → accepted → packaging → done`, with **`make milestone`
green at `accepted`** — before the notes are rendered and before anything closes, which is the whole
point: the gate that informs the ship decision runs while the decision is still open.

`done` is flipped last, when the changelog is written and every finding is landed. The tag comes
after, outside the tree. **0.24.0 is the first milestone whose `done` is true when it is written.**

## Gotchas

1. **A state a consumer's tree already uses cannot vanish under it.** Every consumer's `status:` line
   is validated against these sets; a set that drops a word a tree holds turns every one of those
   grains into a `check pm` finding on upgrade day. `blocked` and `wip` are safe only because the
   census says zero — re-run it rather than trusting this table.
2. **The consumer migration is a follow-up, not part of this.** nullbound holds 38 `todo` and 8
   `review`; adopting v0.24.0 means bumping the pin AND rewriting those lines. Name it in the release
   notes' consumer-follow-up list or it will be discovered as a red gate.
3. **`pm feature done --cascade` moves stories at `review`.** If features go to `reviewing`, the
   cascade's source state moves with it.
