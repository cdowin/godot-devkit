Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.23.0 telemetry — decisions

Durable. This log outlives the grain: it is where a choice and its rejected
alternative are recorded, and it survives close.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-09-03 — The ledger lives at pm/ledger/<milestone-id>.jsonl, never pruned

**Decision:** one JSON-lines file per milestone under `pm/ledger/`, at the tree root beside
`pm/roadmap/`, outside every milestone directory. `retire` never touches it. Rows carry the grain id,
so per-feature and per-story views are filters over the milestone file, not files of their own.
`.gitattributes` marks `pm/ledger/*.jsonl merge=union`. Stock path is `[pm] ledger_dir = "pm/ledger"`.
**Because:** the point is measuring across milestones (Chris, 2026-09-03: "over time we can measure
against these"). The 2026-09-02 plan put the file inside the milestone dir, which `retire` deletes at
the next close — the data would survive only in git, and the git walker was ruled out the same day. One
file per milestone means each milestone branch appends to its own file, so parallel milestones never
conflict on the ledger.
**Rejected:** `pm/roadmap/<ms>/ledger.jsonl` (pruned with the dir). One `pm/ledger.jsonl` for the
whole tree (every branch appends to the same file; union merge would carry it but every close becomes
a ledger merge). Frontmatter fields on the grain (summed and rewritten on every dispatch, clobberable
by `pm set`, pruned with the dir).
**Costs:** a second top-level directory under `pm/`; `pm validate` and `check pm` must ignore it
explicitly; `retire` gains a test proving it leaves `pm/ledger/` alone.

## D2 — 2026-09-03 — Timestamps live in the ledger only, full UTC, one per status flip

**Decision:** every `pm story|feature|milestone|bug <status>` appends
`{ts, kind: "status", grain, from, to}` with `ts` a full UTC ISO-8601 timestamp at second resolution
(`2026-09-03T21:40:12Z`). `pm decide` appends `{ts, kind: "decision", grain, entry, title}`. No
`started_at`/`done_at` on frontmatter; `pm ledger show <grain>` prints a grain's rows, so the start and
end of anything is one command away.
**Because:** one fact, one home. The verb that flips the status writes the row in the same call, at
the same instant, so the ledger IS "written with the actual work" (Chris, 2026-09-03). The resolvers
never read a date, so a frontmatter date would be a field nothing checks. Deriving dates from git
was ruled out the same day.
**Rejected:** stamping `started_at:`/`done_at:` on the grain (second home, `pm set`-able, pruned).
A git walker over `status:` diffs (needs history that retire removes; not "written with the work").
**Costs:** reading a start time needs the ledger, not `cat feature.md` — hence `pm ledger show`. An
idempotent no-op flip (same status) still appends: a no-op is a fact.

## D3 — 2026-09-03 — The grain is the tree's live state at the hook, never inferred from prose or commits

**Decision:** a dispatch row records the tree as the verbs left it at hook time, verbatim:
`tree: {milestones_building, features_building, features_review, stories_wip, stories_review}`,
each a list of ids. No parsing of the dispatch prompt, no commit-prefix search, no `?` sentinel.
Attribution policy belongs to the report, and every candidate is on the row.
**Because:** Chris, 2026-09-03: "we shouldn't estimate or infer where possible". The story that was
`wip` when the developer stopped, the feature that was `building` when the PO stopped, the stories at
`review` when the reviewer stopped — those are facts the verbs already wrote. The 2026-09-02 plan's
inference (prompt id, then commit prefixes, then `?`) is replaced; its story is retired.
**Rejected:** inferring from the prompt text or commits; recording only the single most likely grain.
**Costs:** a dispatch run before anyone flipped a story to `wip` records empty lists. That is a true
statement about process discipline, and the report lists such rows rather than hiding them.

## D4 — 2026-09-03 — The agent transcript is the raw source for tokens and tool calls; the hook reads it through one pm verb

**Decision:** the `SubagentStop` hook receives `agent_transcript_path` (documented in the Claude Code
hooks reference alongside `agent_id`, `agent_type`, `session_id`, `transcript_path`). The hook passes
that path to `pm ledger record --from-transcript <path> --event SubagentStop`; Python (stdlib `json`)
sums `message.usage` over the assistant records (`input_tokens`, `output_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`), counts `tool_use` blocks by tool name,
takes the first and last record `timestamp` as `started_at`/`ended_at`, and records `model`. A `Stop`
hook does the same for the orchestrator session's own transcript (`kind: "session"`, cumulative
totals per stop; the report diffs consecutive rows per `session_id`). Both hooks are `async: true`
and exit 0 unconditionally.
**Because:** the hook payload carries no usage at all, and `last_assistant_message` is the agent's
narration — the one source the devkit SDLC already refuses to trust. The transcript is the raw
record of what the API returned. The 2026-09-02 gotcha ("do not scrape transcripts") predates
reading the reference; the path is a documented interface, not a scrape.
**Rejected:** the agent's self-reported token line; `PostToolUse` on `Agent` (fires in the parent,
sees only the result text); a per-tool `PostToolUse` counter (N hook invocations per dispatch for a
number the transcript already holds).
**Costs:** coupling to the transcript JSONL shape (`type`, `message.usage`,
`message.content[].type == "tool_use"`, `timestamp`); one fixture pins it and a shape change fails
loudly. A field the transcript lacks is omitted from the row, never invented. Parsing a large
orchestrator transcript on every stop is why the hook is async.

## D5 — 2026-09-03 — Raw numbers only: no size weights, no dollar cost, no self-reported backfill

**Decision:** the ledger and the report carry counts, sums and timestamps as recorded. `size:` appears
as a column, never as a divisor. No dollar estimate. No backfill of 2026-09-02's self-reported agent
reports; the `nullbound-baseline` story is dropped and the first hook-captured milestone is the
baseline. `[ledger] size_weights` does not exist.
**Because:** Chris, 2026-09-03: "no need on cost, just give raw data"; "we shouldn't estimate or infer
where possible". A weighted or estimated number cannot be re-derived later when the question changes;
a raw one can.
**Rejected:** s/m/l/xl weights; a price table; `notes: baseline (pre-hook, self-reported)` rows.
**Costs:** no before/after against 0.19.0/0.20.0. Comparisons start at the first captured milestone.

## D6 — 2026-09-03 — SUPERSEDES D1 — the milestone owns its ledger at pm/roadmap/<ms>/ledger.jsonl; history is git

**Decision:** the ledger is `pm/roadmap/<milestone>/ledger.jsonl`, beside `decisions.md` — the
2026-09-02 placement, restored. `retire` removes it with the directory; a retired milestone's rows
are read from git (`git show <prune-anchor>:pm/roadmap/<ms>/ledger.jsonl`, the anchors `ROADMAP.md`'s
prune log already records). No `[pm] ledger_dir` key. `.gitattributes` marks
`pm/roadmap/*/ledger.jsonl merge=union`.
**Because:** Chris, 2026-09-03: a tree-level `pm/ledger/` is "such an easy place to drift" — a
second home beside the milestone that nothing else in the tree reads or retires, and that every
milestone branch appends to. Inside the directory it is one more slot the existing walkers,
templates and `retire` already own, and when the milestone is cleaned it is out of mind. History is
git's job, and the prune log already carries the anchor for exactly this read.
**Rejected:** D1's `pm/ledger/<ms>.jsonl` (survives the prune, but a parallel home nothing else
maintains). One tree-wide file (same objection, worse).
**Costs:** cross-milestone trends need `git show` for retired milestones — `pm ledger report
--from <anchor>` (a ledger-report story) rather than a directory listing.

## D7 — 2026-09-03 — SUPERSEDES D2 — started_at and ended_at live on frontmatter, stamped by the verbs, cascading, warn never refuse

**Decision:** every grain that does work carries two frontmatter timestamps, full UTC ISO-8601 at
second resolution: `started_at:` written on FIRST entry into its working state (milestone
`building`, feature `building`, story `wip`) and `ended_at:` written on `done` (and rewritten on a
later `done` after a reopen). `pm feature done --cascade` stamps the stories it closes. A `done`
with no `started_at` stamps `ended_at` and prints a warning; nothing refuses and `check pm` does not
fail on a missing stamp. The ledger still gets every flip (`review` included), so the frontmatter
tells the simple story and the ledger the whole one.
**Because:** Chris, 2026-09-03: "a simple cascade … easy to tell the whole story by a simple
walk/yaml parse". A start and an end on the grain is what a reader opening the file wants, and it is
what a cross-milestone walk over git can read without parsing JSON lines.
**Rejected:** D2's ledger-only timestamps (right about one home, wrong about which home a person
reads). A stamp per status (`wip_at`, `review_at`, …): the ledger is that.
**Costs:** two fields the resolvers do not read; `pm set` can edit them (a hand edit is a fact about
a team, as with `reviewed:`). Bugs are NOT stamped in this milestone — their machine is
`open → fixed → closed` and nobody asked; add later if wanted.

## D8 — 2026-09-03 — SUPERSEDES D7 — no frontmatter stamps; every transition of every grain, bugs included, is a ledger row, and the terminal-state row is the end

**Decision:** timestamps live in the ledger only. Every `pm milestone|feature|story|bug <status>`
appends `{ts, kind: "status", grain, from, to}`; `pm feature done --cascade` appends one row per
story it closes. A grain's start is its first row into a working state and its end is its row into
the LAST state of its configured vocabulary (`done` for milestones, features and stories; the last
entry of `[pm] bug_states` for bugs — `closed` stock). `pm ledger show <grain>` prints the rows
oldest first with the seconds spent in each state, so "A → B → C, and how long in each" is one
command. No `started_at:`/`ended_at:` on frontmatter; the stamps story is withdrawn.
**Because:** Chris, 2026-09-03: "the ledger needs to mark the timestamp of each transition … so we
can measure time in each phase and figure out which ones are taking the most time", and "ended_at
should be stamped at done for everything — reviews are still part of the process; if a review takes
3 days, that's data I want." A start/end pair on the grain cannot carry `review`, and a second home
for a subset of the ledger's facts is the drift D6 exists to avoid.
**Rejected:** D7's frontmatter pair (a subset, a second home); stamping `review` as an end (review
time is the data).
**Costs:** a reader wanting a grain's dates runs `pm ledger show` instead of opening the file.

## D9 — 2026-09-03 — Renumbered 0.22.0 -> 0.23.0: v0.22.0 was released upstream mid-build; the ledger rows were rewritten to the new ids in the same commit

**Decision:** the milestone is `0.23.0`. `origin/main` tagged `v0.22.0` (scenario-declares-its-
coverage, `ffd8bc0`) and opened `0.22.1` while this branch was building as `0.22.0`. Every id under
the milestone directory, the `branch:` stamp, the commit prefixes in the stories, the review records
and the `grain`/`tree` ids inside `ledger.jsonl` were rewritten `0.22.0` → `0.23.0` in one commit.
Earlier commit messages keep the old prefix; git is the archive of that.
**Because:** a released version is taken (D8's rule, and `check pm` D8 when it is on). A renumber is a
rename of the same grains, not a change of fact, so rewriting the ids inside the ledger is the honest
edit — the alternative leaves rows naming grains that no longer resolve.
**Rejected:** leaving the ledger rows at `0.22.0` (dangling); appending "renamed" rows (a second
name for one fact).
**Costs:** the one deliberate rewrite of an append-only file, done by the orchestrator by hand and
named here. The worktree path still says `godot-devkit-0.22.0`; a path is not an id.

## D10 — 2026-09-03 — consumers-adopt leaves this milestone: a consumer adopts at its own pin bump, in its own PM tree

**Decision:** the `consumers-adopt` feature and its `trail-adopts` story are removed from 0.23.0.
Adoption is what a consumer does when it bumps its `DEVKIT_VERSION` pin: `install-hooks --force`,
the two `.claude/settings.json` entries `install-hooks` prints, and its next milestone captured live.
That work is a story in the consumer's PM tree (trail's, at its 0.28.4 close), not a feature here.
**Because:** `pm milestone done` refuses while any feature is not `done` (D3), and a feature whose
ship criterion is "trail's next milestone reports from live capture" cannot be done before the release
it depends on. The devkit half — the verbs, the couriers, the printed settings — is `usage-capture`
and `ledger`, already done.
**Rejected:** closing the feature with a record that says "the consumer will do it" (a `done` that
is not); keeping the milestone open until trail adopts.
**Costs:** `ledger-report`'s `consumed_by:` loses its one entry.
