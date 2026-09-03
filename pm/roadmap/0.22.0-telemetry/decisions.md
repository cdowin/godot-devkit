Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.22.0 telemetry — decisions

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
