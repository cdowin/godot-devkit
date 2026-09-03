Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.22.0/review-record-shape A review record carries a machine-readable verdict block — decisions

Durable. This log outlives the grain: it is where a choice and its rejected
alternative are recorded, and it survives close.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-09-03 — check pm sees a dangling caused_by the way it sees a dangling depends_on

**Decision:** both readers — `pm validate` and `check pm` — walk a bug for its `caused_by:` ref and
report one that resolves to nothing with V4's line shape. The story's "check pm unchanged" is
withdrawn.
**Because:** a ref naming nothing is an integrity fact, the class the devkit keeps as a gate; whether
a resolving `caused_by` is an escape is the report's judgement (Chris, 2026-09-03: judgement is the
caller's). One reader seeing a lie the other passes is the split D-rules exist to prevent.
**Rejected:** an opt-in `bugs=True` for `pm validate` only (built first, removed).
**Costs:** a consumer's pre-push goes red on a typo in `caused_by:` — the same cost `depends_on`
already carries.
