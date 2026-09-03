---
id: 0.22.0/ledger/start-and-end-stamps-on-frontmatter
feature: 0.22.0/ledger
milestone: "0.22.0"
name: status verbs stamp started_at and ended_at on milestones, features and stories, cascading, warn never refuse
status: todo
owner:
depends_on: []
---

# status verbs stamp started_at and ended_at on milestones, features and stories, cascading, warn never refuse

## Goal
`pm milestone building`, `pm feature building`, `pm story wip` write `started_at: <UTC ISO-8601
seconds>` on the grain if the key is absent or empty (first entry only — a reopen keeps the original;
the ledger has the reopen). `pm milestone done`, `pm feature done`, `pm story done` (and every story
`--cascade` closes) write `ended_at:`, overwriting a previous one. Both through `model.set_fields`
in the SAME write as `status:` — one read, one write, never a half-stamped grain. A `done` with no
`started_at` still lands and prints `warn: <id> has no started_at (moved to done from <from>)`.
`check pm` and `pm validate` never fail on a missing or malformed stamp; a malformed stamp is a
warning line from the verb that reads it. Templates gain the two keys, empty. `pm status` gains
nothing — the stamps are for the file and the walk (D7).
## Gotchas
The stamp is written only when the status write is going to succeed (same write). `pm set started_at`
remains legal — a hand edit is a fact about a team. Bugs are out of scope (D7).
## Verification
`make test`: each verb stamps the right key; first-entry-only for `started_at`; overwrite for
`ended_at`; cascade stamps every closed story; the warning fires and the flip still lands; a grain
with no frontmatter still refuses as today; `check pm` green with stamps absent, present and
malformed. `make gates`.
## Commit prefix
`feat(0.22.0/ledger/S3):`
## Size
s
