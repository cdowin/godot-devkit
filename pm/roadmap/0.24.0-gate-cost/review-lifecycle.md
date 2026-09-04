# 0.24.0 — `the-lifecycle-says-what-it-means`: pre-accept review

Reviewer run 2026-09-04 over `0d3a8ad..HEAD` (6 commits). Method: every gate-semantics claim probed
by RUNNING deliberately-broken input against scratch trees — a full 7×7 D5 feature×story matrix (49
pairs), the milestone walked through all five post-`building` states, 21 transition flips plus
`planning→done` and `done→building`, malformed `devkit.toml` values, a directory name with a space,
CRLF frontmatter, a non-UTF-8 story, a truncated fence, and an empty `.md`.

**This file exists because of M2 below.** `review.md` already carries the release-gate pass's verdict
block, and `verdict.py:467` refuses a second one — appending here would turn `pm ledger report 0.24.0`
from exit 0 into exit 2. Neither record is wrong; the package cannot yet hold the multi-pass review
its own re-ordered protocol produces. Resolve M2, then merge these two records.

## Verdict: RELEASE-WITH-FIXES

The code is right; the rollout is not. Land C1's sequence, M3's guard, M1's `None` and m1's corrected
migration paragraph before the tag. m2/m3/m4 and the NITs can ride the next patch.

## CRITICAL

### C1 — `make milestone` is red on both consumers, and no ordering of pin-bump vs. tree-migration keeps them green

`tools/consumer_smoke.py:818` runs `('check','pm')` against each live checkout and passes only on
`code == 0`; `:754` runs `check all` in the consumer worktree. `make milestone` = `gates
hooks-self-test matrix smoke`. Measured with `PYTHONPATH=<devkit>/src python3 -m godot_devkit.cli`,
byte-identical to `consumer_smoke.devkit()`:

```
trail      pm status 0 · pm validate 0 · check pm 1 (25 findings) · check all 0
nullbound  pm status 0 · pm validate 0 · check pm 1 (47 findings)
```

nullbound's `[checks] all` names `pm`, so its worktree `check all` reds too. trail's default roster
excludes `pm`, but trail's `[gates] extra` runs `check pm` in `make check` — so **both consumers'
pre-push gates red on pin bump**.

The wedge, proven on a scratch copy of nullbound's tree:

- unmigrated tree + **new** devkit → 47 D4 findings, exit 1
- migrated tree + **old, currently-pinned v0.23.0** devkit → 46 D4 findings (`ready`×37, `reviewing`×9), exit 1
- union `[pm] milestone_states/feature_states/story_states` (old ∪ new words) → **exit 0 under both pins**

The union block is the only green path, and nothing in `CHANGELOG.md` or `handoff.md` mentions it —
both say only "migrate `status:` lines".

Why neither prior pass caught it: `git merge-base --is-ancestor c1dfdf1 0d3a8ad` → true, so the
release-gate review's range **ended before this feature's first commit**, and `handoff.md` says in as
many words that `make milestone` has not been run since the lifecycle change landed. CI stays green
because `consumer_smoke.CONSUMERS` is `~/workspace/{trail,nullbound}` and absent consumers SKIP — so
this reds only on the orchestrator's local run, which is the exact run the ship criterion names.

**Unblock options:** (a) land a union `[pm] *_states` block in both consumers before the tag, then
tag → bump pins → migrate statuses → trim the union; (b) ship a `pm migrate` verb; (c) accept a red
`make milestone`, which contradicts this feature's own ship criterion.

## MAJOR

### M1 — `pm ledger report` prints a confident `0 reopen(s)` over ledgers that record reopens

`src/godot_devkit/repo/pm/report.py:1226-1244`. `reopenable` now tests `model.REVIEWING in
cfg.story_states and model.BUILDING in cfg.story_states` — true under the new stock set — so the
column fills with a number. The rows it counts are `from == 'reviewing' and to == 'building'`, but
**every ledger row written before the pin bump uses `review`/`wip`**. The guard was against a renamed
*config*; the miss arrives through *history*.

Scratch ledger with two real `review → wip` reopens and 1-day dwells:

```
OLD (0d3a8ad~1):  rework — 1 story(s), 2 reopen(s) …  reopens 2  total_s 432000
NEW (HEAD):       rework — 1 story(s), 0 reopen(s) …  reopens 0  every state column "-"  total_s 432000
```

Two defects in one row: the `0` is a measurement nobody made (`report.py:1219-1221` forbids exactly
this sentence under hard rule 4), and `total_s 432000` with every state column `-` is internally
unattributable. The `-`s are honest; the `0` is not. nullbound's live `0.90.3.2/ledger.jsonl` holds
16 status rows, all legacy — this fires on the next report after the bump.
**Fix:** return `None` for `reopens` when the ledger holds no row whose `to` is `model.REVIEWING`.

### M2 — a second review pass appending its verdict block to the shared record makes `pm ledger report` exit 2

`verdict.py:467` refuses a second block; `report.py:1085-1087` turns that into `RecordError` → exit 2.
Three 0.24.0 features carry `reviewed: pm/roadmap/0.24.0-gate-cost/review.md`, and the re-ordered
protocol this feature lands runs three passes over that one record. Reproduced on a scratch copy with
one `cat >>` of a well-formed block: exit 0 → exit 2. Blast radius is `pm ledger report` only (no gate
runs it; the couriers call `pm ledger record`) — but it is a usage error for a workflow the SDLC
produces by design. **Decide:** a separate per-pass record file, or teach `verdict.parse` to accept N
blocks.

### M3 — the ORDER of a consumer's custom `*_states` list is load-bearing, undocumented, and `ledger.py` says the opposite

`model.py:979-992` — `work_started` is `states.index(status) >= states.index(BUILDING)`. Membership
used to be all that mattered. A plausible authoring choice now silently changes what D5 reports, and
can emit a self-contradicting finding:

```toml
[pm] story_states = ["blocked","building","done","planning","ready","reviewing"]   # alphabetical
```
```
  DRIFT  story 0.1/f1/s1 is 'planning' but its feature 0.1/f1 is still 'planning'
         — the story is at work and the feature says it has not started
```

Same word on both sides, reported as a disagreement. Meanwhile `ledger.py:420-422` still tells the
reader the vocabulary is *"a closed SET with no ordering contract"*, flatly contradicting
`model.py:54-56` (*"The ORDER is load-bearing"*) in the same package. **This sits directly on C1's fix
path** — the union block is exactly a hand-ordered custom set.
**Fix:** `if child == parent: return False` in `drift_ahead_of_parent`, one README/`project-devkit.toml`
sentence that a custom set's order IS the lifecycle order, and retire the stale `ledger.py` paragraph.

## MINOR

- **m1 — the shipped migration instruction is already false, and covers stories only.** `CHANGELOG.md`
  `## Unreleased` claims *"its features hold none of the retired words"*; `handoff.md` §4 says *"No
  feature in any tree holds `review`."* Measured: nullbound holds
  `pm/roadmap/0.90.3.2-game-polish/features/pool-is-the-shape/feature.md` at `status: review`, landed
  by `16102812f` **after** the census. Applying the documented story-only mapping to a scratch copy:
  47 findings → **1 residual**, that feature. The mapping table has no row for a feature or milestone
  at a retired word. A consumer following it verbatim ships a red gate.
- **m2 — `SDLC.md`'s ordered Close protocol was not re-ordered**, only its vocabulary line. Step 1 is
  `make milestone` *before any PM flip* — which is exactly where the deadlock lived — and the five
  steps never name a milestone status. The release skill got the re-order; the root operating contract
  did not. `SDLC.md` step 3 also still owns the CHANGELOG retitle that `SKILL.md` step 4 now owns.
- **m3 — three more "at the pin bump" steps**, interacting with the earlier pass's still-open m3: a
  consumer must also run `pm install-skills` (rewrites `.claude/rules/pm-execution.md` +
  `.claude/skills/pm-operations/SKILL.md`; overwrites cleanly, no `--force`), `install-agents` for
  `developer.md`/`po.md`/`tech-writer.md`, and `install-runners --force` for `Makefile.devkit`'s help
  line (both consumers still carry `make pm ARGS="story wip <id>"` at `Makefile.devkit:275`). The
  consolidated paragraph now needs six steps, not three.
- **m4 — the rule-5 escape hatch silently loses two behaviors.** With the legacy words declared:
  `pm feature done --cascade` flips the feature and moves **zero** stories (the cascade keys off
  `model.REVIEWING`); and `pm feature review` falls through `cmd_feature_simple` (`cli.py:573`), so the
  *"N story/ies not at review"* report is gone.

## NIT

- **n1** — `ledger.py:416-425` cites a stock story vocabulary that no longer exists; `[-1]` is now
  `done`, not `blocked`. Same paragraph as M3's contradiction.
- **n2** — `cli.py:844` pads status to width 8; `reviewing` and `packaging` are 9, so `pm status`'s
  feature column no longer aligns. Cosmetic, but `pm status` output is a shape consumers read.
- **n3** — D2's `STALLED_IF_ALL_STORIES_DONE` (`model.py:73`) derives from the stock `LIFECYCLE`, not
  `cfg.feature_states`. With a custom set, a stalled feature draws no D2 finding **and no NOTE**, while
  D5's equivalent blindness *is* disclosed. The feature built the disclosure machinery and did not
  extend it to the rule beside it.
- **n4** — `model.py:587` docstring still narrates `pm story wip <id>`, a spelling the CLI now exits 2 on.

## QUESTION

- **q1** — D6 keys on `building` only, so a milestone parked at `reviewing`/`accepted`/`packaging` with
  every feature `done` is invisible to every rule; the stall window grew from one state to four.
  Defensible and un-fixable without re-creating the deadlock, but nothing now notices a milestone that
  stopped at `packaging` with the changelog written. Intended?
- **q2 — the bump.** Both consumers wire `check pm` into `make check` → pre-push, so 0.24.0 reds two
  pre-push hooks until each rewrites tracked files. Rule 7's letter says MINOR (no consumer
  Makefile/hook *invokes* a retired verb — both trees grepped; only `Makefile.devkit:275`'s help text
  names one). Rule 7's spirit — "anything a consumer must edit to survive" — reads major. The prior
  pass ruled MINOR on the other three features without this one in range.

## What holds

D5's new comparison is correct in both directions, constructed case by case rather than read: silent
on all five normal-path pairs, fires on all ten genuine ones including the five the old equality was
blind to. What it deliberately stopped catching — a `done` story under a `building` feature — is
backstopped by D2 in the diagnosable case and is the normal path otherwise. The committed test class
`D5AStoryAheadOfItsFeature` matches the matrix case for case. D6 needed no logic change; its message no
longer names `done` as the next state, and the deadlock is broken (fires only at `building`, quiet at
the four later states). Transitions are genuinely open: 21/21 accepted, skip works, reversal works,
nothing strands. Malformed config exits 2 naming the key and the fix; a set without `building` disclosed
via `[check:pm] NOTE`, not a silent pass. Defaults ≡ declared-defaults byte-for-byte (rule 5 holds).
Robustness corpus: no crash, everything disclosed. Stdlib-only, no new imports, no 3.12+ syntax.
trail's 8 `active` grains live in `features/*/plans/*.md`, a slot `slot_walk` never visits — the new
set does not change that. `make gates` 4/4 PASS; `make test` 1747 passed, 1 skipped, 3955 subtests, 171 s.

Not verified: `make milestone` and `make matrix` end to end (orchestrator's); `check all` in place on
nullbound (peer agents were live in that tree — composed from `check pm` exit 1 plus `pm` being named
in its `[checks] all`, and `_dispatch_check` returning `max(...)`); Windows/Linux (reasoned from
source; no new platform surface).
