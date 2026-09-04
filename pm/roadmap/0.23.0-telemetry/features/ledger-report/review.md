# Feature Review — 0.23.0/ledger-report

**Commit range:** `4107098..c7214d1` (9 commits)
**Verdict:** SHIP-WITH-FIXES

Three stories, one module (`report.py`, 1521 lines at HEAD), one CLI verb, three test
files. I wrote none of it and came in cold. The lens is hard rule 4's read side: a
number that looks like a measurement and is not. I found three of those and fixed
three; the fourth I could not fix without changing two verbs at once, and it is the
one thing on this page that needs a decision.

## What I ran

- **Baseline**: `tests/test_pm_ledger_report{,_sections,_git}.py` → **74 passed**.
  After this pass: **85 passed** (11 added, 6 of which fail at HEAD). Full suite
  before/after: **1502 → 1503 passed**, 1 skipped, 3739 → 3740 subtests, 158s.
- **`check pm` on this tree**: PASS, 11 milestones / 32 features / 72 stories /
  21 bugs / 22 refs — unchanged before and after.
- **D5 audit, mechanical.** Docstrings and comments stripped, then every operator
  in the remaining code enumerated. The arithmetic is **four sites** and nothing
  else: `running + value` (`report.py:711-714`), `acc['dispatches'] += 1` (`:719`),
  `(end - start).total_seconds()` (`:877`, `:897`), `b - a` (`:1363`). **Zero**
  divisions, moduli, powers, `float(`, `round(` — every `/` in the file is a `Path`
  join or a literal separator in the summary line. Comparisons on a measured number:
  **three**, all `ts > moment` or `len(...) > 1`, none a threshold. `sorted(...)`
  appears 11× and every key is a closed-set order (kind order, grain id, severity
  index, `verdict.VERDICTS` order) — never a measured value, and `reverse=True`
  appears nowhere. Ranking vocabulary (`efficient|worst|best|top|rank|score|weight|
  price|dollar|expensive|leaderboard|percent|ratio|average|median`): **zero hits in
  code**. Every user-visible literal is a census, a column name, a block heading or a
  refusal message; the only three absence words are `no ledger`, `no data`,
  `no verdict block`. `size:` is read once (`:738`) and reaches only a column and a
  JSON key — never an operand. **D5 holds.**
- **Adversarial inputs, run.** 22 hostile fixtures through the CLI: rows out of time
  order; duplicate status rows; a `to` outside the vocabulary; a full
  `review → wip → review → done` reopen; a dispatch naming a story under another
  milestone; a `session` sequence with a decreasing cumulative; a `tree` bucket with
  10,000 ids; a review record with 500 findings; `caused_by` into `zz_archive/`;
  `reviewed:` pointing at a directory (live and at a rev); `--from` at a rev where
  the milestone directory carries a different suffix **and** a story moved between
  features; a ledger line of valid JSON that is an array; `--json` round-trip.
- **Mutation testing, 51 mutants** over `report.py` and `cmd_ledger_report`, each run
  against all three test files. **41 caught, 10 survived**; of the 10, three were
  no-op mutations (equivalent code) and seven were real gate gaps. Five of the seven
  now have tests and are caught; two are recorded below.
- **Scale.** 50,000 rows (25k dispatch + 25k status, 8.4 MB): **live 0.7s**,
  **`--from HEAD` 0.9s**. 500 findings in one record: 0.02s. A 10,000-id `tree`
  bucket: 0.02s. 101 stories × 5,000 dispatch rows: 1.1s.
- **Line shapes.** On this repo's real tree the report prints 5 section headings with
  exactly **two** ` — ` separators and 1 summary line with exactly **one** — the
  shape `tests/support/pm.py::section_of` slices by. With `--from <rev>` the headings
  gain a third and the predicate (`>= 2`) still holds; verified against a real rev.
  `--json` round-trips through `json.loads`: 440 leaves, 210 nulls, **0** `'-'`
  strings — every dash in the table is `null` in the object.
- **`--help`/USAGE** (`cli.py:102`) matches behaviour on all four refusals I drove
  (`--wat`, two ids, `--from` twice, `--from` with no value, `--from` with no id).

## Findings

### MAJOR

**R1 — a ledger whose rows are not in time order fabricates intervals, and
`merge=union` guarantees one exists.** `report.py:859` (`state_seconds`) and `:881`
(`total_seconds`) both read "the interval between two CONSECUTIVE rows" as
consecutive **in the file**. `ledger.read_rows`'s docstring says "oldest first" and
does not sort; D6 marks `pm/roadmap/*/ledger.jsonl` `merge=union`, and a union merge
interleaves two branches' appends **by branch**, not by clock. Repro — three status
rows written 12:00, 10:00, 13:00:

```
grain         …  todo    wip  review  blocked  total_s
0.1/alpha/s0  …     -  10800   -7200        -     3600
```

`review` is billed **negative 7200 seconds**; `wip` is billed 10800 for a state the
story spent 7200 in; `total_s` is 3600 for a life of 10800. Three numbers that look
like measurements, none of which is one. `state_seconds`'s own docstring says "a
fabricated interval is worse than a missing one", and this is that interval.

**Fixed in place.** New `report.in_time_order` (`report.py:834`), called once in
`build` (`:1541`) so all five sections read one ordering. Stable, so two rows in the
same second keep the file's order; a row whose `ts` will not parse sorts last and
contributes no arithmetic — where before it silently destroyed the two intervals it
sat between. Sorting is not inference: `ts` is on every row, written by the verb that
wrote the row. Test:
`test_rows_out_of_time_order_never_fabricate_an_interval` — fails at HEAD on the
`-7200`, passes after.

**R2 — `no ledger` suppressed two sections that never read the ledger, and `--json`
printed them for the same tree.** `cli.py`, the old short-circuit before `build`.
Sections 2 and 4 read the **review records** and the **bug frontmatter** — documents
`ledger.jsonl` has nothing to do with, and which `feature.md` names as sources in as
many words. A milestone with no ledger, one review record carrying a real verdict
block and one bug naming a cause printed exactly:

```
[ledger:report] 0.1 — no ledger
```

while `--json` on the identical tree returned `yield.totals = {records: 1,
findings: 1}` and `escapes.totals = {bugs: 1, features: 1}`. The reader is told there
is nothing measured while a yield and an escape sit in the tree, and the two output
modes disagree about it — hard rule 4's read side, phrased as a line about a
different file.

**Fixed in place.** `report.beyond_ledger` (`report.py:1549`) + `cli.py:1844`. The
`no ledger` line still prints — it is a true statement about section 1's source — and
the rest of the report follows it **only** when something outside the ledger was
measured. Deliberately narrow: a record with no verdict block is a row saying so and
not a measurement, so a milestone nobody has recorded anything for keeps its one
quiet line, and both existing `no ledger` cases (live and `--from`) stay green
untouched. Test: `test_no_ledger_still_reports_what_the_ledger_never_held` — fails at
HEAD, passes after. The architect may want the predicate wider; widening it is one
`or`.

### WARNING

**R3 — L4 reproduces here: `total_s` is a span from the first row that merely NAMES
the grain, and on this repo's own tree it is 2.3× the grain's life.**
`report.py:927` (`mine = [r for r in rows if ledger.row_names(r.data, names)]`) feeding
`total_seconds` at `:940`. `row_names` matches a row's `grain` field **or** any id in
its `tree` snapshot, so a decision row or a dispatch row that merely had the grain
live can become `rows[0]`. Live evidence, `pm ledger report` on this worktree:

| grain | measured state time | `total_s` |
|---|---|---|
| `0.23.0/ledger` | `review 1799` | **4222** |

The feature's own status rows span 22:32:54 → 23:02:53 = 1799s. The 4222 runs from
its first **decision** row (D1, 21:52:31) to its `done` row. In a hook-captured
milestone the `tree`-matched dispatch rows widen it further — which is exactly the
shape L4 described for `pm ledger show`.

I did **not** fix this, and the reason is the docstring at `report.py:885`: the row
set is `show`'s row set on purpose, "so one grain cannot have two durations depending
on which verb asked". Changing it here alone creates precisely the divergence that
sentence exists to prevent, and a test pins the current behaviour (mutating `mine` to
status-rows-only reddens the suite). The honest fix changes `report.total_seconds`
**and** `cmd_ledger_show` together, or adds one sentence to both outputs — either way
a two-verb contract decision, not a local correction. **Deferred to `0.23.0` with a
recommendation: switch both to the first STATUS row.** "First row" is what the story
says and the number is honest under that reading; no reader will read a column headed
`total_s`, sitting beside four per-state columns, as anything but the grain's life.

### MINOR

**R4 — a grain whose only row is its own terminal flip printed `total_s 0`.**
`report.py:881`. One row, so there is no span — but the subtraction of the row from
itself yields `0`, and `0` in that column reads as "finished in no time at all". Every
state column beside it correctly printed `-`. This repo's own tree printed it:
`0.23.0/review-record-shape/the-verdict-block`, all states `-`, `total_s 0`.
**Fixed in place** (`report.py:898`, `if rows[0] is status[-1]: return None`); that
grain now prints `-`. Test: `test_one_row_is_an_instant_and_never_a_zero_second_total`
— fails at HEAD, passes after.

**R5 — a status row whose `to` is outside the configured vocabulary drops its
measured seconds with no census line.** `report.py:938` builds `states` from
`state_columns(cfg, kind)` only, so a fixture with `todo → banana → wip` measures
3600s of `banana` and prints nothing anywhere — no column, no total, no note. The
vocabulary is closed and `pm story banana` refuses, so only a hand edit or a foreign
version produces it, and `check pm` reports the frontmatter separately. But the
report's own rule is that a census which saw something says so. **Not fixed** — a new
column or a trailing "seconds in states this vocabulary does not name" block is an
output-format change (hard rule 6, minor bump), not a correction.

**R6 — `escapes_data` reaches past the one-home function for the terminal state.**
`report.py:1332` compares `fstatus == ledger.TERMINAL_STATE` where every other site in
the module asks `ledger.terminal_state(cfg, kind)` (`:855`, `:890`). Identical today —
`terminal_state` returns `TERMINAL_STATE` for every non-bug kind — so this is latent,
not live: if features ever gain a configurable terminal state, `feature_done` is the
one site that will not follow. `cfg` is already in scope at that line. **Not fixed**:
a change with no behaviour delta has no test that can fail first, which is this pass's
rule for landing anything.

**R7 — `size` prints an empty cell where every other absent value prints `-`.**
`report.py:1022` (`entry['size'] or ''`), against `--json`'s `'size': … or None`. The
module's own comment at `:73` says `-` "is the same character `pm list` already prints
for an unowned story" — an unowned story's owner is a string, not a number, so the
cited precedent is precisely this case. Visible on this tree: all 19 grains print a
blank `size` column, because these stories carry `## Size` in the body rather than
`size:` in frontmatter. Text and JSON disagree about the same absence. **Rejected**:
a test pins the blank, so changing it is an output-format decision for the architect,
not a correction.

**R8 — a restarted session id prints a negative token delta.** `report.py:1363`.
Two `session` rows under one `session_id` whose cumulative totals decrease (a session
restarted, D4's assumption broken) print `out -480` / `tool_calls -9` in a column
headed by section 1's word for tokens. **Rejected**: this is a raw subtraction of two
recorded facts, and D5 forbids the module inventing a rule about them; suppressing it
would hide the one signal that says the session restarted. It deserves a sentence in
`_delta`'s docstring saying the delta may be negative and what that means.

### SUGGESTION

**S1 — three sections each re-derive the same attribution; the second and third do it
inside a per-story loop.** `walk_grains` (`report.py:746`) runs **3×** per report —
`spend_data`, `rework_data`, `overhead_data` — and `named_grains` (`:771`) is called
once per (story × dispatch row) in the latter two. Measured: 101 stories × 5,000
dispatch rows → **510,000 `named_grains` calls where 5,000 would do**, a 102×
recomputation, and 3 tree walks where 1 would do. Not a performance problem at any
realistic size (1.1s for that fixture, 0.7s for 50k rows), so this is a shape
observation, not a defect: the registry deliberately makes a section one self-contained
pair of functions, and a shared census would be a fourth thing threaded through
`Section.data`. Flagging it because it is the cross-story pattern this review exists
to see. **Deferred to `0.23.0`.**

**S2 — `_universal` guards a divergence I could not produce.** `report.py:267`. It is
live — `_Blob.read_text` is the ledger read, proven by instrumenting both to raise
(10 tests and the real-tree `--from HEAD` run reached it). But a CRLF `ledger.jsonl`
produces **byte-identical** output with the translation gutted, including the
by-line-number refusal message, because `read_rows` splits on `\n` and `json.loads`
tolerates the trailing `\r`. So the docstring's claim — "a CRLF ledger would read back
as one row shape from disk and another from history" — does not hold today. Keep the
guard (it is cheap insurance if `read_rows` ever stops tolerating `\r`), but the claim
overstates. I added a parity test over a CRLF ledger **and** a CRLF record; it passes
either way, which is the honest state of it. **Rejected.**

**S3 — `GitSource._is_grain_doc` borrows `model._is_grain_doc`, and the borrow is
right while the name is now wrong.** `report.py:554`. The borrow itself should stay:
a second spelling of "is this a grain" is the census-disagrees-with-the-gate defect,
and the second-name smell says the fix for a duplicated definition is never to write
it twice. But a leading underscore imported across a module boundary is a lie about
the surface — the next person to change `model._is_grain_doc`'s signature has no
signal that a second module depends on it, and `report.py` is not in `model.py`'s
family. **Recommend renaming it public (`model.is_grain_doc`), a pure rename with no
behaviour change.** `model.py` is out of this pass's edit scope, so:
**deferred to `0.23.0`.**

### DELTA (docs behind the code — for the tech-writer)

**D1 — `CHANGELOG.md` `## Unreleased`, the `pm ledger report` bullet.** "a milestone
with no `ledger.jsonl` prints one line and exits 0" is now conditional: it prints one
line and exits 0 **when nothing outside the ledger was measured**, and otherwise
prints that line and the report. Drift created by R2's fix. I may not edit
`CHANGELOG.md`; proposed replacement clause:

> a milestone with no `ledger.jsonl` prints one line and exits 0 — and, when the
> review records or a bug's `caused_by:` hold something the ledger never did, that
> line and then the sections that read them

**D2 — `README.md:243`, the `pm ledger report` row.** Two things. (a) The verb column
reads `pm ledger report [<milestone-id>] [--json]` and omits `[--from <rev>]`, which
the row's own prose then describes and which `cli.py:102`'s USAGE does carry. (b) Two
sentences are run together with no separator: "…never exits non-zero on a number
`--from <rev>` reads the same files out of git…". Every other claim in that row I ran
and each holds: the five sections, arithmetic only, never non-zero on a number, the
rev named and never inferred.

## Fixes in place (uncommitted — reviewers here fix in place and never commit)

| # | file:line | what |
|---|---|---|
| R1 | `report.py:834`, `:1541` | `in_time_order`, called once in `build` |
| R2 | `report.py:1549`, `cli.py:1844` | `beyond_ledger`; `no ledger` no longer suppresses sections 2–5 |
| R4 | `report.py:898` | a one-row grain has no span |
| G1 | `tests/test_pm_ledger_report.py` | +6 cases (out-of-order rows; single-row total; unparseable `ts` is `-` not `0`; a foreign snapshot id names nothing; a grain with no `id:` gets its path id; no-ledger-but-records) |
| G2 | `tests/test_pm_ledger_report_git.py` | +3 cases (a directory at the rev is not a file; an absolute `reviewed:` never reads today's disk; CRLF parity) |
| G3 | `tests/test_pm_ledger_report_sections.py` | +2 cases (a renamed story vocabulary dashes `reopens`; the stock one still counts it) |

Six of the eleven fail at HEAD. The other five are gate gaps: they pass at HEAD and
fail against the named mutation, which is the evidence that the gate was missing, not
wrong. Re-run of the seven surviving mutants after the additions: **6 of 7 now
caught** (`named_grains`' kind check; `state_seconds` billing 0 for an unparseable
stamp; `is_file` accepting a tree; `review_record_for` falling back to disk; `_grain`
dropping its path-id fallback; and both new fixes guarded against removal). The
seventh is S2, which no output can distinguish.

## Mutation survivors worth naming

Two mutants still survive and I did not write tests for them, on purpose:

- `review_records`' sort by feature id (`report.py:1082`) — the docstring calls the
  order "a contract of this file", but every fixture has too few features for a
  walker's order to differ from sorted order. A test would need a filesystem whose
  natural order is wrong, which is a fact about a filesystem, not a gate.
- `_after`'s `>` vs `>=` (`report.py:1222`) — the boundary is a dispatch row stamped
  the same second as the story's first `review` row. Unspecified in the story; either
  reading is defensible.

## Passed

- **D5 is not merely obeyed, it is structurally hard to break here.** Four arithmetic
  sites, no division anywhere, `size` unreachable from any operand, and every ordering
  over a closed set. The one place a weight could have crept in — splitting one
  dispatch's tokens across the two grains it names — is refused explicitly at
  `report.py:783-786`, with the consequence (per-grain columns sum to more than the
  totals line) stated rather than smoothed over.
- **Absent-is-not-zero holds under hostile input.** `_blank` starts every sum at
  `None`, `_plus`'s asymmetry is correct (`None + absent` stays `None`, `0 + absent`
  stays `0`), a non-integer value on a row is treated as absent rather than coerced or
  crashed, and `--json` carries 210 nulls and zero `'-'` strings on the real tree. Six
  mutants aimed at this contract were all caught.
- **The reopen case is handled properly.** `review → wip → review → done` yields
  `wip 7200 / review 7200 / total 14400` — both stints summed into each column, the
  reopen counted once, and the dispatch that fell between the two `review` rows
  attributed to `after_review`. This is the case most likely to be silently wrong and
  it is right.
- **The `--from` seam is the same report, proven the hard way.** At a rev where the
  milestone directory carried a different suffix **and** a story had since moved to
  another feature, `--from` output equals the pre-change live output byte-for-byte
  once ` — at <rev>` is stripped, and `git status` is empty afterwards. `Source` is a
  real seam: `DiskSource` is pure delegation to the walkers `check pm` uses, so the
  live census cannot drift from the gate's.
- **Refusals are input-shaped, never number-shaped.** Exit 2 on: a ledger line that is
  not JSON, a line that is a JSON array (`is a list, not a row`, by line number), a
  malformed verdict block (by record and line), an unknown flag, two ids, `--from`
  twice, `--from` with no value, `--from` with no id, a flag-shaped rev, a rev with
  whitespace. Exit 0 on every number I could make hostile.
- **The git seam cannot leak stderr into content.** `_git` uses
  `capture_output=True` (separate pipes), reads stdout as **bytes**, and consults
  stderr only when `returncode != 0`. I could not provoke a warning out of `show`,
  `cat-file`, `ls-tree` or `rev-parse` to demonstrate it empirically — see below.

## Disposition of the two findings deferred here from phase 1/2

- **L4** (`features/ledger/review.md`, "`pm ledger show`'s total may span a row that
  is not this grain's") — **reproduces in the report**, with live numbers on this
  tree. Raised above as **R3** and **deferred to `0.23.0`**, because the fix is a
  two-verb contract change and the current behaviour is deliberate, documented and
  test-pinned. This is the item that needs a decision before close.
- **U4** (`features/usage-capture/review.md`, "the hand form mints a `session` row
  carrying a `grain`") — **the report already answers it, and answers it in writing.**
  `overhead_data`'s docstring (`report.py:1394`) states that session rows are diffed
  per `session_id` "and which grain it was about is a question this row cannot
  answer", and the code matches: no section reads `grain` on a `session` row. Driven
  through the CLI, a hand-minted `session` row carrying a grain, a `tree` snapshot and
  `usage` appears in the overhead census (`1 session row(s)`) and in no table — and
  section 1's summary line is scoped ("across 0 dispatch row(s)"), so nothing claims
  to have counted it. **Rejected**: the decision U4 asked for has been made and is
  written down where the next reader will find it.

## Not verified

- **No live hook-captured milestone.** This tree's ledger has 33 status rows, 5
  decision rows and **zero** dispatch or session rows, so every dispatch- and
  session-shaped assertion above rests on synthetic fixtures, not on the real capture
  path the milestone's ship criterion names. The ship criterion ("a milestone worked
  with the hooks armed and no hand entry") is untested by construction here.
- **Git stderr noise on a successful read.** I could not construct a repo where
  `git show`/`cat-file`/`ls-tree`/`rev-parse` writes to stderr and exits 0 (invalid
  `.gitattributes`, a failing smudge filter and advice configs all produced nothing),
  so the claim is argued from the code — separate pipes, stderr read only on failure —
  and not demonstrated.
- **`make precommit` / `make milestone` / `make smoke` not run** (out of scope for this
  pass, and smoke touches the live consumer checkouts). I ran the full `pytest tests/`
  suite and `check pm` instead.
- **No consumer-tree run.** Nothing here was pointed at `~/workspace/trail` or
  `~/workspace/nullbound`.
- **Non-UTF-8 and permission-denied paths** at a rev: `_text` lets `UnicodeDecodeError`
  propagate by design, and I did not drive a blob that is not UTF-8.
- **Concurrency**: two reports against one tree, or a report racing an append, not
  exercised.
- **`ledger.py`, `model.py`, `verdict.py`** read for context only; not audited.

```text
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| R1 | MAJOR | landed in-place |
| R2 | MAJOR | landed in-place |
| R3 | WARNING | deferred: 0.23.0 |
| R4 | MINOR | landed in-place |
| R5 | MINOR | rejected: a new column or block is an output-format change, not a correction |
| R6 | MINOR | rejected: behaviour-identical today, so no test can fail first |
| R7 | MINOR | rejected: a test pins the blank cell, so the spelling is the architect's call |
| R8 | MINOR | rejected: a raw subtraction of two recorded facts is what D5 asks for |
| S1 | SUGGESTION | deferred: 0.23.0 |
| S2 | SUGGESTION | rejected: the guard is live but no output distinguishes it |
| S3 | SUGGESTION | deferred: 0.23.0 |
| D1 | DELTA | deferred: 0.23.0 |
| D2 | DELTA | deferred: 0.23.0 |
```
