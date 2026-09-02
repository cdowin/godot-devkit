---
id: 0.20.0/bugs/review-minors-from-0.20.0
milestone: "0.20.0"
name: the 0.20.0 release review's deferred MINORs and NITs
status: open
caught_in: "0.20.0"
fix_milestone: 0.21.0
---

# review-minors-from-0.20.0

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

Nine findings from the 0.20.0 release-gate review, held together rather than split into nine
files: none reddens a gate today, none has a consumer complaining, and every one is a small,
independent edit. Source record: `pm/roadmap/0.20.0-bootstrap/review.md` (RELEASE-WITH-FIXES,
2026-09-02). The three MAJORs, MINOR-1, MINOR-2, MINOR-3 and MINOR-6b/6c landed before the tag;
these are what was deferred. `fix_milestone: 0.21.0` — 0.21.0's tree lives on another branch, so
this is filed under the milestone that CAUGHT it and moves when that branch exists.

## Root cause

Nine, one per item.

**MINOR-4 — `installables/project-devkit.toml` is not inert when uncommented, as its own header
invites.** `extra = []` and `infra = []` are refused by `core.config.str_tuple` (exit 2 from `make
check` / `check test-shape`); the `[rng] allowlist` line is an example that reports STALE; the
`min_args` / `forbidden_calls` / `ledger` lines are examples too. The header's "a key this package
no longer honours is NAMED at exit 2" holds only for `[pm]` (`model.py::RETIRED_KEYS` /
`RETIRED_SECTIONS`); an unknown key in any other section is silently ignored. Rule 5 in the file
that carries it. Fix: write the two empty lists as examples (`# extra = ["my-scan"]`), mark the
example lines as such, and scope or drop the retired-key sentence.

**MINOR-5 — `godot/checks/rng.py::BARE_DRAW_RE` / `RANDOMIZE_RE` miss `randfn(` and `seed(`.**
Both are the global generator (`randfn` a draw, `seed` a re-seed of the same class as
`randomize()`); a probe passed them silently. Census-exact parity with nullbound's `rng_scan.sh`,
which has the same gap, so no consumer regresses. Two alternation entries.

**MINOR-6a — `doctor.sh`'s three GUT states have no test.** Mutant M4 (`elif false` over the
absent-GUT-dir branch) survives both `test_init_verb` (24 passed) and `test_hooks_payloads` (95
passed). The story's "each with a test watched failing at HEAD" is not true for it. 6b (unit.sh's
count-mismatch branch, mutant M5) and 6c (`integration.sh` never run past `--self-test`) were
closed before the tag.

**MINOR-7 — `repo/init.py::main` arms hooks after `install-hooks` REFUSED.** `_arm_hooks` runs
unconditionally: git config `core.hooksPath` is repointed and whatever `tools/setup-hooks.sh`
exists is executed, under a summary that says the verb wrote nothing. Gate it on the verb's exit
code.

**NIT-1 — `init` on a hand-edited project-owned file (`Makefile`, `devkit.toml`, `CLAUDE.md`)
REPORTS ("is yours — left alone") and continues at exit 0** rather than refusing; only
devkit-owned collisions refuse (exit 1). Documented and tested — noted because it differs from the
review brief's stated expectation, not because it is wrong.

**NIT-2 — `tests/test_defaults.py::ConsumerCorpus` reads every tracked consumer file and
tracebacks on a tracked-but-DELETED one.** The gates have treated that as a disclosed `UNVERIFIED`
skip since v0.17.0 and the corpus sweep should too. It is what reddened the 3.13 / 3.14 matrix in
the review run, on a nullbound file its own developer deleted mid-run.

**NIT-3 — the installed `ci-verify.yml` runs `make milestone` with only checkout + setup-uv.** On
a fresh project every member boots Godot or gdlint, so the first push is a red badge and `init`'s
next-steps do not say so. Both consumers carry their own engine setup.

**NIT-4 — `install-runners` on nullbound / trail refuses without `--force`** (both own
`tools/dev/runners/*.sh`). Expected; the S3 adoption stories are still `todo`. Listed so the
adoption work does not rediscover it as a defect.

**PM-1 — `pm new story` under `[pm] story_ordinal_prefix = true` mints the file WITHOUT the
`NN-` prefix.** The 0.18.0 fix kept the ordinal out of the `id:`, which was right, but the FILE is
minted as `<slug>.md` and every consumer story is then hand-renamed to `NN-<slug>.md` after
scaffolding — nullbound, 2026-09-02, three POs and the orchestrator each did it by hand. Expected:
the file is minted as `<next-ordinal>-<slug>.md` (the ordinal derived from the feature's existing
stories) and the id stays bare. Caught in this session, not in the review record.

## Fix

Nine independent edits, each with a test watched failing at HEAD, in 0.21.0. MINOR-5 and PM-1 are
the two a consumer feels today — a randomness gate with a hole in it, and a rename every story
author performs by hand.
