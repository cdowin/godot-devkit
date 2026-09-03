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

What it makes true: `pm/roadmap/<milestone>/ledger.jsonl` (D6), beside `decisions.md`, append-only,
one JSON object per line, written by the verbs that already touch a grain and by `pm ledger record`.
The grain's own frontmatter carries `started_at:` and `ended_at:` (D7). Row kinds:

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

`decisions.md` is prose and append-only — the ledger is its machine sibling in the same directory,
not a second decisions log. The ledger is retired with the milestone; git is the archive and the prune
log carries the anchor (D6). The frontmatter stamps are the simple story a reader wants from the file;
the ledger is the whole story (D7). Stdlib, one file per milestone.

## Ship criterion

Every status flip in a milestone appears in its `ledger.jsonl` with a UTC timestamp; every grain that
started and finished carries `started_at`/`ended_at`; a `pm ledger record` row round-trips;
`pm validate` and `check pm` ignore the ledger and never fail on a missing stamp; `retire` removes
the ledger with the directory and the ROADMAP row's anchor resolves it from git.
