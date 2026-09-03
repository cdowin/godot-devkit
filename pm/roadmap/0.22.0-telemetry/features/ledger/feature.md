---
id: 0.22.0/ledger
milestone: "0.22.0"
name: The ledger — every status flip and every dispatch leaves a timestamped row
status: planning
reviewed:
phase: 1
depends_on: []
consumed_by: ["0.22.0/usage-capture", "0.22.0/ledger-report"]
---

# The ledger — every status flip and every dispatch leaves a timestamped row

What it makes true: `pm/ledger/<milestone-id>.jsonl` (D1), append-only, one JSON object per line,
written by the verbs that already touch a grain and by `pm ledger record`. Row kinds:

```
{"ts":"2026-09-03T21:40:12Z","kind":"status","grain":"0.22.0/ledger/status-flips-stamp-the-ledger","from":"todo","to":"wip"}
{"ts":"…","kind":"decision","grain":"0.22.0","entry":"D3","title":"…"}
{"ts":"…","kind":"dispatch","session_id":"…","agent_id":"…","agent_type":"developer","model":"claude-opus-5",
 "started_at":"…","ended_at":"…","duration_s":812,"messages":41,"tool_calls":37,"tools":{"Bash":20,"Edit":9,"Read":8},
 "tool_calls_before_first_write":11,
 "usage":{"input":1200,"output":38000,"cache_creation":210000,"cache_read":9100000},
 "tree":{"milestones_building":["0.22.0"],"features_building":["0.22.0/ledger"],"features_review":[],
         "stories_wip":["0.22.0/ledger/status-flips-stamp-the-ledger"],"stories_review":[]}}
{"ts":"…","kind":"session","session_id":"…","model":"…","started_at":"…","ended_at":"…","messages":…,"tool_calls":…,"tools":{…},"usage":{…},"tree":{…}}
```

`ts` is always full UTC ISO-8601 at second resolution. A `session` row carries cumulative totals for
that session at that stop; the report diffs consecutive rows per `session_id`. Every number is a count
or a sum as recorded; nothing is weighted or estimated (D5). `pm ledger show <grain-id>` prints the
rows that name a grain (in `grain` or anywhere in `tree`), oldest first.

## Existing-construct audit

`decisions.md` is prose and append-only — the ledger is its machine sibling, not a second decisions
log. Frontmatter is NOT the home for timestamps (D2). The file lives outside the milestone directory
because `retire` deletes that directory and the ledger must outlive it (D1). Stock path
`[pm] ledger_dir = "pm/ledger"`; a repo with no `devkit.toml` behaves identically.

## Ship criterion

Every status flip in a milestone appears in `pm/ledger/<ms>.jsonl` with a UTC timestamp; a
`pm ledger record` row round-trips; `pm validate` and `check pm` ignore `pm/ledger/`; `retire` leaves
it in place, proven by a test.
