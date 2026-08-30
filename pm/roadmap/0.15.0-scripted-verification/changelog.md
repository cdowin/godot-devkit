Append with `godot-devkit pm changelog <milestone-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.15.0 scripted verification — changelog

Durable. What was built that a player cares about, in the words a player would
use. It survives close: a milestone's notes matter most once it has shipped.

> One entry per thing somebody would notice, and a reference proving it landed.
> The reasoning behind it is a decision, not a release note — that goes in
> `decisions.md`. `pm changelog --render` unions every milestone's log, newest
> first, and this file is the only place its entries come from.

## C1 — 2026-08-29 — one word to verify any repo
**What:** Run `godot-devkit task quick` after a change and `godot-devkit task verify` before a release — in any repo that pins this toolkit, without learning its target names.
**Evidence:** src/godot_devkit/repo/tasks.py

## C2 — 2026-08-29 — a gate on the shortcut itself
**What:** `godot-devkit check tasks` fails the day a project renames a target its [tasks] table still points at, instead of the day an agent needed it.
**Evidence:** tests/test_tasks.py:88

## C3 — 2026-08-29 — consumer smoke is a target
**What:** `make smoke` runs every read verb against the live game checkouts, compares each printed census against an independent count, and fails if it leaves either checkout dirty.
**Evidence:** tools/consumer_smoke.py

## C4 — 2026-08-29 — the fuzzers are code now
**What:** The CommonMark differential (60,000 documents), the log-schema differential (692 logs) and the migration replay run from `make fuzz` in two seconds, instead of being rebuilt on demand.
**Evidence:** tests/test_fuzz_markdown.py

## C5 — 2026-08-29 — closing a milestone no longer needs inside knowledge
**What:** The close verb refuses a review record that the retention rule would delete, and `pm collapse` performs the close-time trim that used to be a hand edit.
**Evidence:** tests/test_pm_close_protocol.py

## C6 — 2026-08-29 — the review contract is installable
**What:** `godot-devkit install-agents` drops the review and build contract into a repo — run adversarial input, ship a test that failed against HEAD, print before and after.
**Evidence:** src/godot_devkit/repo/installables/verification-reviewer.md

## C7 — 2026-08-29 — the release protocol points at the targets
**What:** The release and consumer-smoke skills now start from `task verify` and `make smoke` instead of describing commands to retype, and name the collapse verb the close step needs.
**Evidence:** .claude/skills/release/SKILL.md

## C8 — 2026-08-30 — check tasks states its finding once
**What:** The no-[tasks]-table failure printed the same sentence twice, which reads as two findings. Exit 1 is unchanged — asking to check something unconfigured is a real finding.
**Evidence:** tests/test_tasks.py:114

## C9 — 2026-08-30 — an install happens whole, or not at all
**What:** A collision on the second file used to leave the first one installed while reporting nothing was written. Every destination is decided before the first write, and one refusal names them all.
**Evidence:** tests/test_install.py:232

## C10 — 2026-08-30 — the generated workflow can actually run
**What:** install-ci renders the trigger and setup steps a repo declares in devkit.toml [ci] — so a verify role needing Godot gets it provisioned. A malformed [ci] is exit 2, not a broken workflow.
**Evidence:** tests/test_install.py:295

## C11 — 2026-08-30 — pm collapse refuses an uncommitted log
**What:** pm collapse now refuses a decisions.md that is untracked or has uncommitted changes: it deletes the collapsed entries' prose and its pointer claims git history holds them.
**Evidence:** 26577d0

## C12 — 2026-08-30 — a collapsed decision id is never re-minted
**What:** The collapse pointer carries an 'Ids spent' list that pm decide reads, so a collapsed id is never re-minted into the same log; check pm reports a re-mint or a pointer naming none.
**Evidence:** 26577d0

## C13 — 2026-08-30 — check tasks says what make -n runs
**What:** check tasks now states that resolving a make role parses your Makefile, so parse-time $(shell) and +-prefixed recipe lines run. The mechanism is unchanged; the claim that it ran nothing was false.
**Evidence:** 26577d0

## C14 — 2026-08-30 — generated workflow keys are quoted
**What:** install-ci quotes action-input keys, so an input named on/yes/no/123 is no longer read as a YAML 1.1 boolean or integer (on and yes collided into one key).
**Evidence:** 26577d0

## C15 — 2026-08-30 — install verbs refuse instead of tracebacking
**What:** install-ci, install-agents and pm install-skills refuse a destination that is a directory, read-only or non-UTF-8 before writing anything, instead of raising a traceback mid-install.
**Evidence:** 26577d0

## C16 — 2026-08-30 — the log-schema fuzz tests its boundaries
**What:** The log-schema fuzz corpus now lands exactly at the title and value caps and one either side, so an off-by-one at a cap fails the run instead of surviving it.
**Evidence:** 26577d0

## C17 — 2026-08-30 — the review-slot refusal resolves symlinks
**What:** pm feature done judges --review-record through symlinks, so a link named durable.md pointing at the transient review.md is refused and a dangling link does not raise.
**Evidence:** 26577d0

## C18 — 2026-08-30 — one walk
**What:** Filesystem enumeration moves into core/walk.py, which returns what it KEPT and what it SKIPPED under a closed-enum reason; Walk has no length, so a census cannot reach a count without its disclosures.
**Evidence:** 6ac90c3

## C19 — 2026-08-30 — the two allowlists
**What:** An AST test asserts glob/rglob/iterdir/os.walk live only in core/walk.py and write_text/open-for-write/rename/unlink/rmtree/mkdir only in core/apply.py, naming file:line otherwise.
**Evidence:** tests/test_boundaries.py

## C20 — 2026-08-30 — one apply
**What:** Filesystem mutation moves into core/apply.py: a Plan is an explicit list of Steps, decide() names every obstruction from a closed enum before anything runs, and Applied says which landed.
**Evidence:** 7134e72
