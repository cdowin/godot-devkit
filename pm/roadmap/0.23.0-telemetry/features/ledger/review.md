# Feature Review — 0.23.0/ledger

**Commit range:** `236af3f..HEAD` (`2250e76`, `31b9690`, `7bee4a0`, `3a55fd6` and the
`pm(0.23.0/ledger)` closes), plus the uncommitted working tree at review time.
**Reviewer:** independent, cold. Adversarial input, run — no diff-reading (SDLC § 5).

## What I ran

Everything below is my own run, in a scratch consumer tree built by `pm init` +
`pm new`, never against `~/workspace/trail` or `~/workspace/nullbound`.

- **Transcript refusal matrix, 16 hostile transcripts** through
  `pm ledger record --from-transcript`: `usage` as a string / float / bool → exit 2,
  no row; negative and 10^30 token counts → copied verbatim, row written;
  `timestamp` missing → row with no `started_at`/`ended_at`/`duration_s`; malformed
  `timestamp` → exit 2; a `tool_use` block with no `name` and with an int `name` →
  counted as a call, not attributed to a tool; a line that is valid JSON but not an
  object → exit 2 naming the line; no assistant record and an empty file → exit 2.
  16/16 landed where the docstrings say.
- **`pm ledger record` surface:** two milestones building → refuse naming both; none
  building → refuse; `--from-transcript` + `--grain` → refuse; positional junk →
  refuse; unknown `--event` (`Nope`, lowercase `stop`) → refuse; `--tokens-in` with
  `-3`, `' 7 '`, `1_0`, `٣` → refuse; `--grain` with 300 chars, `ñ`, an embedded NUL,
  `../../etc/passwd`, `0.1/*`, `/etc/passwd`, empty → refuse. 15/15 refused with
  **zero rows written** (ledger byte-compared before and after each).
- **`pm ledger show` against hostile rows:** a line that is valid JSON but not an
  object → exit 2; an unknown `kind` → printed, no arithmetic; `ts` missing and `ts`
  malformed → printed, no gap fabricated; ledger empty and ledger absent → `no rows`,
  exit 0. One case crashed — finding L1.
- **Concurrency:** 20 forked processes × 200 rows into one file = **4000/4000 lines,
  4000 parse-ok, 0 torn or interleaved, 362000 bytes, 0.23 s.** `open('a')` holds.
- **10k rows:** `pm ledger show` over a 10 000-row ledger, three runs:
  **0.32 s / 0.24 s / 0.23 s**, 10 000 lines printed. No pathology.
- **Read-only ledger under a status flip:** `chmod 444 ledger.jsonl` then
  `pm story wip` → frontmatter write lands, exit **0**, and stderr carries
  `[pm] WARNING — …/ledger.jsonl could not be appended to ([Errno 13] …); the write
  itself landed, but this transition is NOT in the ledger`. Rows on disk unchanged.
  This is the right answer under both "never judge" and hard rule 4: the loss is
  loud, and it does not turn a landed flip into a failure.
- **Contract drift vs `origin/main`** (which carries none of this work — no
  `ledger.py`): the same tree, byte-for-byte, through both checkouts.
  `pm validate`, `check pm`, `pm status`, `pm list`, `pm vocabulary`,
  `pm vocabulary --json`, `check doc`, `pm get`, `pm sync --check`, `pm story wip`,
  `pm feature building`, `pm bug fixed`, `pm decide`, `pm new bug`, `pm retire` —
  **stdout, stderr and exit code identical on all 15**. Only `pm --help` differs, and
  additively (the new verb + `--caused-by`). `[check:pm] …`, `  DRIFT  …` and
  `[pm] …` are unchanged.
- **Row shape vs `feature.md`, key for key:** minted one row of each kind and
  compared the emitted key sets against the four documented examples.
  `status`, `decision`, `dispatch`, `session` — **doc-only: none, emitted-only:
  none**, all four kinds.
- **Gate mutation, 30 mutants** across `ledger.py` and `cli.py`'s ledger parts, run
  against `test_pm_ledger.py`, `test_pm_ledger_record.py`, `test_verdict.py`,
  `test_pm_gate.py`, `test_hooks_payloads.py`, `test_boundaries.py`,
  `test_pm_scaffold.py`, `test_init_verb.py`: `'a'`→`'w'`; `TERMINAL_STATE`→`blocked`;
  `terminal_state` ignoring `bug_states`; a no-op flip writing nothing; `bool`
  summing as 1; an empty transcript yielding zeros instead of refusing; U+2028 left
  unescaped; a naive stamp read as local; `_stamp` swallowing its `OSError`;
  `read_rows` skipping an unparseable line; `records_of` skipping a non-JSON line;
  `_gap` returning 0 for an unparseable `ts`; `record` picking the first of two
  building milestones; the tree snapshot including `zz_archive/`; `--grain` not
  needing to resolve; `--from-transcript` accepting a directory; and 14 more.
  **30/30 CAUGHT.** These gates are load-bearing; I found no assertion I could
  delete without a failure elsewhere.
- **Suite:** 1371 passed / 1 skipped / 3737 subtests before my fix; 1397 / 1 / 3737
  after. +4 are mine; the other +22 are a live peer's `test_pm_ledger_report.py`
  landing mid-review.

## Fixed in place (uncommitted — no hash to cite; see the verdict-block note)

**L1 (CRITICAL) — `pm ledger show` tracebacks on a row shape this version never
wrote.** `src/godot_devkit/repo/pm/ledger.py:425` (`row_names`).

Repro before the fix, in any tree:

```text
$ printf '%s\n' \
  '{"ts":"2026-09-01T10:00:00Z","kind":"status","grain":"0.1/alpha/s0","from":"todo","to":"wip"}' \
  '{"ts":"2026-09-01T13:00:00Z","kind":"dispatch","tree":{"stories_wip":[{"a":1}]}}' \
  > pm/roadmap/0.1-first/ledger.jsonl
$ pm ledger show 0.1/alpha/s0
Traceback (most recent call last):
  …
  File ".../pm/ledger.py", line 441, in row_names
    return any(value in names for ids in tree.values()
TypeError: cannot use 'dict' as a set element (unhashable type: 'dict')
exit=1
```

`row.get('grain')` had the same shape (`{"grain": {"a": 1}}` → the same `TypeError`).

Why it matters, not merely that it is ugly: this file is `merge=union` by
`pm init`'s own `.gitattributes`, so rows arrive from another milestone branch, from
a newer version of this package, and from a hand edit — none of which pass through
`usage_row`. `read_rows` deliberately accepts **any JSON object** as a row, which is
the right append-only contract; the matcher above it then assumed every value inside
one was hashable. The consequence is not a bad number, it is the whole timeline
disappearing behind a raw traceback at **exit 1**, which hard rule 6 spells
"findings" — and `ledger.py`'s own read side names every other bad line with a
`LedgerError` and a line number.

**The fix:** type-check before matching, in `ledger.py:436` and `:449-452`. A value
that cannot be a grain id does not name one, so the answer is `False`. Not-crashing
is only half of it — the fix also asserts the match stays `False` for a dict whose
`id` happens to spell the grain, because reading that as a hit would put another
row's cost on this timeline, which is the same lie the crash was hiding.

**The test:** `tests/test_pm_ledger_record.py:459` `RowsThisVersionNeverWrote`, four
cases. **Watched failing at HEAD (4 failed) and passing on the fix (4 passed).**

## Findings

### MINOR

**L2 — `duration_s` is the one field this module DERIVES, and it can be negative.**
`ledger.py:356`. A transcript whose records are not in timestamp order (the last
record older than the first — a resumed or merged transcript) yields
`started_at: 2026-09-03T12:00:00Z`, `ended_at: 2026-09-03T10:00:00Z`,
**`duration_s: -7200`**, and the row is written. Repro: two assistant records with
descending `timestamp`s through `--from-transcript`.

I did **not** fix this and I think it should stay as it is — `started_at` and
`ended_at` are on the row, so nothing is lost and the subtraction is re-derivable —
but the report must not sum `duration_s` blind, and the field deserves one line in
`transcript_summary`'s docstring saying it is a subtraction over two recorded facts
rather than a measured elapsed time. Flagging it so the report author decides
knowingly.

**L3 — `normalise_ts` accepts a bare date, against its own docstring.**
`ledger.py:192-215`. The docstring says the format is "never a local time and never
a bare date"; `datetime.fromisoformat('2026-09-03')` succeeds, so a transcript
carrying `"timestamp": "2026-09-03"` records `2026-09-03T00:00:00Z` and a
`duration_s` computed against midnight. The claim is about this module's OUTPUT
spelling and the output is correct, so this is a docstring that over-promises about
input rather than a defect — but "never a bare date" is exactly the kind of sentence
SDLC § 5 says to generate hostile input against, and it does not hold.

**L4 — `pm ledger show`'s total may span a row that is not this grain's.**
`cli.py:1697`, `total = _gap(rows[0], status[-1])`. `rows` is everything
`row_names` matched, and a `dispatch` row matches through `tree` — so a dispatch
that merely had the story in `stories_wip` can precede the story's own first status
row and become `rows[0]`. The printed `first row → terminal row: Ns` is then longer
than the grain's life. "First row" is literally what the story says, and the number
is honest under that reading; a reader will read it as the grain's lifetime. One
sentence in the output or a switch to the first STATUS row resolves it.

### NIT

**L5 — the only `pm` message line with no `[pm] ` prefix.** `cli.py:1699` prints
`first row → terminal row: 1200s`. The row lines above it are data and prefix-free
by the same convention `pm list` uses, which is right; this one is a message. Rule 6
makes line shapes a contract, and this shape is new, so it costs nothing now and
costs a minor bump later.

### QUESTION

**L6 — the milestone id `0.23.0` is already a released tag.** `origin/main` is at
`a9b4291`, one commit past `ffd8bc0 release: v0.23.0 — a scenario declares its
coverage: …`, and is opening `0.22.1`. This branch's `pm/roadmap/0.23.0-telemetry/`
is a second, different 0.23.0. `__init__.py` here reads `0.21.0` (bump-at-close, per
CLAUDE.md), so the collision is not visible from inside the branch — it surfaces at
the bump. Not a defect in any of the three features; it needs a decision before
close, and it is the kind of thing a reviewer who says nothing is failing at.

## Passed

- Append-only holds under real contention: 4000 concurrent appends, zero loss, zero
  tearing. The `open('a')` primitive and D1's rejection of a `core.apply` plan are
  both vindicated by measurement, not argument.
- The U+2028/U+2029 escape works end to end: a tool name carrying U+2028 round-trips
  as `Ba sh` inside **one** line, and `read_rows` splits on `'\n'` rather than
  `splitlines()` so the read side agrees with the write side. Both halves were
  needed; both are there.
- `terminal_state` naming `done` instead of `story_states[-1]` is right, and D2
  explains why in the decision rather than in a comment nobody would find.
- `retire` removes the ledger with the directory, and `pm validate` / `check pm`
  report `1 UNVERIFIABLE — the ref names a milestone no longer in the tree` instead
  of a false failure. That is rule 4 answered on the read side: it says what it
  could not check.
- The refusals are input hygiene only. Nothing in the ledger path labels, ranks,
  weights or infers — no `?`, no `unattributed`, no zero standing in for an absent
  field. I went looking for a judgement to object to and did not find one.

## Not verified

- `make milestone`, `make smoke`, `make gates` — not run (out of scope for this
  pass; the orchestrator's).
- Behaviour against the live consumer checkouts (`~/workspace/trail`,
  `~/workspace/nullbound`) — deliberately untouched.
- `pm ledger report` and `report.py` — a live peer owns them; read, not exercised,
  not edited. L2 and L4 are the two findings that land on that surface.
- Transcripts at real orchestrator scale (tens of MB). I timed the READ side at
  10 000 ledger rows; I did not time `--from-transcript` against a multi-megabyte
  `Stop` transcript, which is the case `async: true` exists for.
- Cross-branch `merge=union` behaviour under an actual `git merge` — I proved the
  attribute ships and that concurrent appends do not tear, not that git resolves two
  branches' ledgers as a union.

## Note on the verdict block

Three of my findings were fixed **in place and uncommitted** — SDLC § 2 says a
builder never commits and the orchestrator commits per feature by pathspec, so no
hash exists to cite. `verdict.py`'s `landed` disposition takes a 7–40 character hex
hash and nothing else (I checked: `landed in place, uncommitted` raises
`MalformedVerdict`), so those fixes are described in prose above and the table
carries only the findings I did not land. That gap is itself a finding, raised as R2
in the `review-record-shape` record.

```text
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| L2 | MINOR | rejected: started_at and ended_at are both on the row, so the subtraction is re-derivable; the report must not sum it blind |
| L3 | MINOR | rejected: the docstring over-promises about input, the output spelling it claims is correct |
| L4 | MINOR | deferred: 0.23.0/ledger-report |
| L5 | NIT | rejected: a new verb's output shape, free to change now, a minor bump later |
| L6 | QUESTION | deferred: 0.23.0 |
```
