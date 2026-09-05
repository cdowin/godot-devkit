# 0.23.0 — telemetry: release-gate review

Reviewer run 2026-09-04 over `v0.22.0..7033fea` on `feat/0.23.0-integration` (73 commits, 95 files,
+14,571 / −125), in the `godot-devkit-telemetry-int` worktree. Method: every new and changed source
file read in full (`ledger.py`, `verdict.py`, `report.py`, `cli.py` diff, `validate.py`, `model.py`,
`skills.py`, `install.py`, `test_shape.py`, `integration.sh`, both couriers, the four reviewer
definitions, the self-hosted hooks and `.claude/settings.json`); every gate-semantics claim probed by
running it — against a scratch **clone** of nullbound (145 MB `.git`, `--local`, nothing written to
`~/workspace/nullbound` or `~/workspace/trail`), against real Claude Code transcripts under
`~/.claude/projects/`, and against a stub-vehicle repo for the hook matrix. Targeted `pytest -k`
slices on the 3.11 floor; `make milestone` was the orchestrator's run, not mine.

**Verdict: RELEASE-WITH-FIXES** — the ledger verbs, the couriers and the report hold their contracts
(every path out of a courier is exit 0 with the reason on stderr; the append lands only after the
frontmatter write; no shipped exit code or line shape of a default gate moved). One CONFIRMED rule-4
hole in the gate this release re-plumbed: `check test-shape` prints **PASS over a 0-file roster** when
the consumer's `make integration-list` exits 0 saying nothing (C1, a one-line fix plus a test). Three
MAJORs are contract/doc truths, not code: the verdict grammar has no disposition for "raised, not yet
landed" and this milestone's own four records already misfile around it (M1); the release skill's
`git push origin main` is exactly what the self-hosted `pre-push` blocks the day it is armed (M2); and
the `.gitattributes merge=union` line reaches an existing consumer only by re-running `pm init`,
which no bump step says (M3). Land C1 before the tag; decide M1 before the tag while the grammar is
still free to change; M2/M3 are one-paragraph edits.

## Gates, my run

`check all` on this worktree: `doc` 4 docs / `pm` 10 milestones, 32 features, 72 stories, 21 bugs,
22 refs / `shell` 11 scripts — 3/3 PASS; `check pm` PASS · pytest on **3.11** (`uv run --python
3.11`): `test_verdict test_pm_ledger test_pm_ledger_record test_hooks_payloads test_check_test_shape
test_pm_gate` — **481 passed, 128 subtests, 67 s** · `cc-ledger-subagent.sh --self-test` OK,
`cc-ledger-session.sh --self-test` OK, `shellcheck -x` clean on both · 3.11 imports of
`ledger/verdict/report/cli` OK, `datetime.fromisoformat('…Z')` OK on 3.11 · installed copies
byte-current (`.claude/agents/verification-*`; `tools/hooks/*` differ only in project-config headers).

**On the nullbound clone (pin v0.22.0, `header = true`, one milestone building):** `check test-shape`
before migration → exit 2 naming `integration-list`; after `install-runners --force` → **147 on the
roster, 13 STALE, exit 1 — identical from a plain shell, with `GDK_CAPTURE_GATE_RE=^nothing$
MAKEFLAGS=-n` poisoned into the gate's env, and under `make` with the Makefile's exports** (the
CHANGELOG's 147/13 claim holds; `bash integration.sh --list` direct is 137 either way, so the target
IS what carries the keep-list); the runner's own empty roster → FAIL "boots NOTHING", exit 1.
`pm story done <done-story>` no-op → one row; `pm ledger show` prints it; `pm new bug --caused-by
<feature>` writes `caused_by:` unquoted, `pm validate` + `check pm` PASS (257 refs), escapes section
lists it; a story id / milestone id as `--caused-by` refuses at exit 2 writing nothing; `pm ledger
record --event Stop` on a real **8.1 MB** orchestrator transcript: **0.32 s**, 859 messages, 296 tool
calls; a real subagent transcript → `dispatch` row; **22 of 23** transcripts in the project dir sum
(1 refused: "no assistant record", exit 2); `pm ledger report` over nullbound's 26 review records
(all `NoVerdict`) → exit 0, `--json` parses, `--from HEAD` → `no ledger` (the file is untracked —
correct). **Hook matrix, every case exit 0 with the reason on stderr:** payload not JSON; no
transcript key; cwd not a git repo; no Makefile; unknown `ledger` verb (the v0.22.0-pin day-one
case); silent vehicle named by name; 0 building milestones; 2 building milestones; the ERR trap
(`sed` removed from PATH → "internal error — no ledger row was written"); a transcript path with a
space, a `$` and `é` reaches the verb byte-exact through `Makefile.devkit`'s `SHELL := bash` and the
row is appended end to end.

## CRITICAL

### C1 — `check test-shape` prints PASS over a 0-file roster when `make integration-list` exits 0 silently

`src/godot_devkit/godot/checks/test_shape.py:211-212`. The docstring at :120-130 promises "Raises
RosterUnavailable rather than returning an empty roster"; the code returns `sorted({...})` on
returncode 0, which is `[]` for an empty or blank stdout. The gate then asks the header rule of
nothing, and with an empty `header_ledger` every CHECK 3/4 census is zero.

Scenario: a consumer's root Makefile carries its own `integration-list` (a wrapper, a log redirect,
a pre-0.23.0 hand-rolled roster) — make takes the last definition and warns once. Repro on the clone:
append `integration-list:\n\t@true` to nullbound's Makefile, empty `header_ledger` →
`  roster: 0 scenario(s) the runner would boot` then
`[check:test-shape] PASS — 160 scenario(s) under tests/integration/, … every one off the header
ledger says why it boots (0 the runner would boot)`, **exit 0**. Same with a recipe that echoes one
blank line. The stock path is guarded only by the runner's own empty check (probed: FAIL, exit 1);
the gate's census is a target the consumer owns, and rule 4 says the gate proves its own count.
Fix: `if not roster: raise RosterUnavailable(1, f'{runner} boots NOTHING — `make {ROSTER_TARGET}`
printed no path')` before the return, and a case beside
`test_a_runner_that_boots_nothing_is_a_fail_not_a_pass_over_nothing` (tests/test_check_test_shape.py:532)
whose Makefile overrides the target to `@true`.

## MAJOR

### M1 — the verdict grammar cannot say "raised, not yet landed", so the yield columns misfile from day one

`src/godot_devkit/repo/pm/verdict.py:103,135` — `DISPOSITION_KINDS = (landed, rejected, deferred)`;
`landed` takes a hash or `in-place`. The SDLC's commonest moment is a reviewer who raises a finding
the orchestrator lands later (SDLC §2; this record). Nothing in the closed set names it, so the four
records this milestone shipped already work around it: `review-record-shape/review.md` files R1–R3
as `rejected:` ("in the sense the vocabulary defines — I raised them and chose not to act");
`usage-capture/review.md` files U2 as `rejected:` and omits U1 from the table; `ledger/review.md`
omits L1. Section 2 therefore counts these as `rejected` and `landed` under-counts — the yield number
is wrong on the release's own data, and stays wrong after the fixes land unless someone re-edits the
records. The orchestrator's instruction for THIS record ("disposition left as `open`") produces
`MalformedVerdict line N: unreadable disposition 'open'` (repro: `verdict.parse` on the 3.11 floor);
the block below is therefore unparseable until the landing pass rewrites the column. (It does not
redden anything today: `report.review_records`, report.py:1046-1064, reads feature records only,
never a milestone-level `review.md`.) Fix, before the tag while the grammar is unpublished: a fourth
kind — `open` (or `raised`), a literal token like `in-place` — accepted by `_DISPOSITIONS`, printed
as a fourth column by section 2 (`verdict.DISPOSITION_KINDS` already drives the columns), and named
in the four definitions' paragraph. After the tag the same change is a minor bump.

### M2 — the release skill pushes `main` directly; the self-hosted `pre-push` blocks exactly that, the day it is armed

`.claude/skills/release/SKILL.md:9,23` ("on `main`" … `git tag vX.Y.Z && git push origin main
--tags`) vs `tools/hooks/pre-push:22,50` (`PROTECTED_BRANCHES="main"`, exact-match block, stage 1
ALWAYS runs) vs `CLAUDE.md:123` ("`bash tools/setup-hooks.sh` arms the git hooks") and `SDLC.md:17`
("`main` is merge-commit-only"). Today `git config core.hooksPath` is **unset** in this worktree and
the shared `.git`, so no hook is armed anywhere and the skill will run — but that means the sentence
"D9 + D10 in `[pm] checks` are what hold this tree" is true and the hook half of "IS self-hosted"
is files on disk. The first person who runs `setup-hooks.sh` (as CLAUDE.md tells them to) gets
`BLOCKED: Direct push to main` at step 5, and the only way past is `--no-verify`, which CLAUDE.md
forbids. Fix: reword steps 1/4/5 to what this release actually did — release commit on the milestone
branch (`6e4785a`), PR → merge-commit to `main`, tag the merge commit, `git push origin vX.Y.Z`
(a tag-only push carries no `refs/heads/` line, so stage 1 passes and stage 2 skips).

### M3 — `merge=union` reaches an existing consumer only via a `pm init` re-run, and no bump step says so

`src/godot_devkit/repo/pm/skills.py:102-159` — `install_merge_attribute` runs from `cmd_init` only.
Neither consumer has a `.gitattributes` (checked: nullbound, trail). CHANGELOG bullet 1 says "`pm
init` now appends"; README's ledger paragraph and the `pm init` row say nothing about re-running it;
the bump steps live in two other bullets (`install-runners --force`, "drop those lines"). Once the
couriers fire, every branch appends to `pm/roadmap/<building>/ledger.jsonl` on every stop, so the
first two-branch merge after the pin bump conflicts on a file with no conflicting content — the
exact case D6's `merge=union` exists for. Repro: `pm init` on the clone → `wrote .gitattributes:
pm/roadmap/*/ledger.jsonl merge=union`, tree otherwise untouched (it also re-renders the two
GENERATED skill files, pre-existing behaviour). Fix: one "at the pin bump" list in the CHANGELOG
head or README — (1) `install-runners --force`, (2) drop the STALE `header_ledger` lines the gate
names (nullbound: 13), (3) `pm init` once for the attribute, (4) optionally `install-hooks` + the
printed settings block.

## MINOR

### m1 — `install-hooks` refuses whole on both consumers, so the two couriers cannot be added without `--force`

`src/godot_devkit/repo/install.py:567-574`. On the nullbound clone: `--diff` shows the two couriers as
pure additions and 5 files "already current", but the run refuses whole on 4 files that differ only
in their edited `project config` headers (`cc-godot-sandbox.sh`, `cc-stop-gate.sh`, `pre-push`,
`prepare-commit-msg`); trail's tree has the same shape. The documented way through is `--force` then
re-editing four headers, or hand-copying two files out of a uv cache. Suggest: write additions even
when other destinations collide (report the collisions, exit 1, but the new files land), or at least
say in the CHANGELOG bullet that a consumer with edited headers takes `--diff` → `--force` → re-edit.

### m2 — "IS self-hosted" is not yet an armed guard here

`CLAUDE.md:123`. `core.hooksPath` unset in every checkout; this repo's Makefile has no `doctor`/`hooks`
target to arm or verify it, and nothing in `make precommit` notices. Suggest a `make hooks` target
(`bash tools/setup-hooks.sh`) and a doctor-style check so the claim is a gate, not a sentence — after
M2 is resolved, or arming it breaks the release skill.

## NIT

- **n1** `verdict.py:328` — a markdown separator row `|---|---|---|` refuses as "unknown severity
  '---'"; a `|` inside a `rejected:` reason refuses as "4 cell(s)". Both are loud and both are what
  an LLM reviewer writes next; name them in the message and in the definitions' paragraph (which
  says "no separator row" but not "no pipe in the reason").
- **n2** `ledger.py:318` — a real orchestrator transcript sums `model: ["claude-fable-5-1",
  "<synthetic>"]`; D4-correct (copied raw), but a future grouping by model will meet it.
- **n3** `cc-ledger-*.sh:110` — `printf %q` spells a non-ASCII path as `$'…'`, which the vehicle's
  shell must decode: `Makefile.devkit:36` sets `SHELL := bash` so the stock path is right (probed
  end to end); under dash the `$` survives (`od -c` probe) and the verb refuses "is not a file" at
  exit 2, hook exit 0 — a hand-rolled Makefile is the only route there.

## Probed with deliberately-broken input

`check test-shape`: silent `integration-list` (→ **PASS over 0**, C1); blank-line `integration-list`
(→ PASS over 0); runner over an empty tier (→ FAIL); v0.22.0 `Makefile.devkit` (→ exit 2 naming the
target); poisoned `GDK_*`/`MAKEFLAGS` env (→ census unchanged). `pm ledger record`: transcript with
no assistant record (→ exit 2, nothing written); 0 and 2 building milestones (→ exit 2, nothing
written); `--caused-by` a story id (→ exit 2, no file). Couriers: non-JSON payload, missing keys,
non-git cwd, no Makefile, unknown verb, silent vehicle, `sed` missing (ERR trap) — all exit 0.
`verdict.parse`: `open`, `|` in a reason, separator row, two hashes (→ MalformedVerdict); bold
unfenced `**verdict:**` (→ NoVerdict); dotted milestone segment, bug-id deferral, CRLF (→ OK).

## Not verified

- Windows and Linux are reasoned from source (dash quoting probed with `od -c` only); the matrix
  and `make milestone` are the orchestrator's run.
- That live Claude Code delivers `agent_transcript_path` / `agent_type` on `SubagentStop`: the
  fixtures are the evidence; an absent key is an omitted flag, so the failure mode is "no row", said.
- `hooks-self-test` for `cc-godot-sandbox.sh` (in `precommit`, not re-run here).
- Trail beyond facts: pin v0.20.0, `[test_shape] header` off (no roster impact), hooks customized,
  no `.gitattributes`, one building milestone.

## The bump

**MINOR holds by rule 7's letter**: no exit code or line shape of a default gate moved; the two
`check test-shape` shape changes are under opt-in `header = true` and listed. It is not a no-op:
nullbound's `make check` is red after the bump until `install-runners --force` (else exit 2) and 13
`header_ledger` lines are dropped (else exit 1), and `pm init` once (else merge conflicts on the
ledger); trail needs only the `pm init`. The Makefile itself is untouched, which is where the
major line is drawn.

```text
verdict: RELEASE-WITH-FIXES
| id | severity | disposition |
| C1 | CRITICAL | landed 7e490bc |
| M1 | MAJOR | landed c006c69 |
| M2 | MAJOR | landed 8305bb4 |
| M3 | MAJOR | landed 8305bb4 |
| m1 | MINOR | deferred: 0.24.0/bugs/install-hooks-refuses-whole-on-header-edited-consumers |
| m2 | MINOR | deferred: 0.24.0/bugs/self-hosting-has-no-arm-or-verify-target |
| n1 | NIT | deferred: 0.24.0/bugs/verdict-refusals-do-not-name-the-separator-row-or-a-pipe-in-a-reason |
| n2 | NIT | deferred: 0.24.0/bugs/ledger-model-list-carries-synthetic |
| n3 | NIT | deferred: 0.24.0/bugs/courier-path-quoting-needs-a-bash-shell |
```
