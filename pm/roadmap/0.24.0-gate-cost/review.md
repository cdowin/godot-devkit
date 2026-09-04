# 0.24.0 — gate-cost: release-gate review

Reviewer run 2026-09-04 over `bfcf63a..c1dfdf1` on `milestone/0.24.0-gate-cost` (49 commits, 47
files, +4,752 / −371 excluding `pm/`). Method: every new and changed source file read in full
(`tests/conftest.py`, `repo/checks/hooks.py`, `repo/install.py` diff, `tools/consumer_smoke.py`,
`installables/scenario.sh` + `integration.sh` diffs, `installables/doctor.sh` diff,
`installables/ci-verify.yml`, both couriers, `scene_canonicalize.py`, `verdict.py`, `ledger.py`,
`cli.py`, the `Makefile` matrix recipe, and the diffs of the five migrated unit-test modules); every
gate-semantics claim probed by RUNNING it — against a `--local` clone of trail (38 MB `.git`),
against a stub-Godot scenario project built for the cache ladder, against a stub `uv` capturing the
matrix's argv, against scratch repos for `install-hooks` and `check hooks`, and against two mutated
copies of `src/` for the canonicalize guard. Nothing was written into `~/workspace/trail` or
`~/workspace/nullbound` (both verified `git worktree list`-identical and `git status`-clean after
the run). Targeted slices and the whole suite on the 3.11 floor; `make milestone` and `make matrix`
end to end are the orchestrator's, not mine.

**Verdict: RELEASE-WITH-FIXES.** The three features hold their contracts under adversarial input,
and the two riskiest new powers — `rm -rf .godot` inside a gate, and `git worktree add` on a live
consumer — are bounded, announced, and already covered by committed tests that I re-ran rather than
re-read. The derived `shell` mark is exact in the direction that matters: **0 real process spawns**
in the 265-test `not shell` slice, measured under `sys.addaudithook`, and an empty selection is
pytest exit 5, so a mark that stopped selecting reds the matrix rather than printing PASS over
nothing. One MAJOR: the new `check hooks` gate names `make hooks` as its repair in four different
findings, and **no consumer has that target** — not `Makefile.devkit`, not the `init` seed
Makefile, not nullbound (`make: *** No rule to make target 'hooks'`); only this repo's own root
Makefile has it, and the committed test that guards the repair reads only this repo's Makefile.
That is one line to fix and it should land before the tag. Three MINORs and two NITs are
deferrable.

## Gates, my run

`check all` on this tree: `doc` 4 docs / `pm` 11 milestones, 35 features, 76 stories, 31 bugs,
27 refs / `shell` 11 scripts / **`hooks` armed at `tools/hooks`, 8 hooks, 6 fail open, 2 parse** —
4/4 PASS. `pm validate` VALID (122 grains, 27 refs). Full suite on the **3.11 floor**: **1712
passed, 1 skipped, 3901 subtests, 170.9 s** (the skip is `test_pm_verbs.py:1017`,
case-insensitive filesystem). `-m "not shell"` on **3.12 and 3.14**: 265 passed, 3643 subtests,
**3.2 s each**. `bash tools/hooks/cc-ledger-session.sh --self-test`, `cc-ledger-subagent.sh
--self-test`, `cc-godot-sandbox.sh --self-test` (13 block / 16 allow) all OK; `shellcheck -x` clean
on both couriers and `scenario.sh`. `/bin/dash` is present here, so the couriers' non-bash-vehicle
case really ran rather than SKIPping.

**The matrix, measured against a stub `uv` that records its argv.** The floor is handed
`run --python 3.11 --with pytest python -m pytest -q` (9 elements, no `-m`); 3.12 / 3.13 / 3.14 each
get 11 elements ending `[-m] [not shell]` — `not shell` survives make's expansion, the continued
recipe line and word splitting as ONE argv element. Verdict line byte-identical:
`[MATRIX] PASS on 3.11 3.12 3.13 3.14`. `PY_FLOOR=3.99` → `[MATRIX] REFUSED: PY_FLOOR "3.99" is not
in PY_MATRIX …`, exit 2, **zero interpreters spawned**. A stub that fails on 3.13 →
`[MATRIX] FAIL on 3.13`, exit 1.

**The `shell` census, three ways.** Collection: 1713 total, `-m shell` 1448, `-m "not shell"` 265 —
an exact partition. `-m "shell and not shell"` (an empty selection) → pytest **exit 5**, which the
matrix loop treats as a failing interpreter. And the runtime measurement the AST cannot give: the
whole `not shell` slice under an audit hook watching `subprocess.Popen` / `os.exec*` /
`os.posix_spawn` / `os.system` made **REAL SPAWNS: 0**. The census that pins it
(`test_shell_mark.py::Census`, `MARKED_MODULES = 36` + 8 named unmarked) is itself in the `shell`
slice, so the floor runs it and an over-marking regression reddens there.

**On the trail clone (pin as installed, `--local` clone of `~/workspace/trail`):** the full
`consumer_smoke.smoke()` — **18 rows, 0 failed**. `runners ahead 2 file(s) … scenario.sh,
integration.sh` (the count computed from the installable bodies + destination modes agreed with the
install's own `[install] wrote` lines); `check all exit 0 against the release's runners`;
`check tres`/`check uid` censuses both 241 against `git ls-files` 241; `autoloads` 60 vs 60;
`check props findings 0 DEAD, ceiling 30`; `scene round trip 265 .tscn/.tres byte-identical (floor
100)`; `uid codec differential 1252 uid(s) (floor 200), both formulations agreed`;
`canonicalize round trip design_system.tscn: 85 degraded line(s) restored byte-for-byte`;
`defaults elision 125 .tres copied, 6 elided, deletion-only and idempotent`;
`checkout unchanged clean`; `worktree list unchanged 1 worktree(s), the same before and after`, and
`.git/worktrees` gone entirely afterwards.

**The parked bug's own census reproduces exactly.** `canonicalize invents no index` on the clone:
`116 scene(s): 0 invented, 5/17 authored index= restored, 12 not derivable (10 scene(s) not
index-identical)` — the same five numbers its table states for trail.

## MAJOR

### M1 — `check hooks` names `make hooks` as its repair, and no consumer has that target

`src/godot_devkit/repo/checks/hooks.py:63` (`ARM_COMMAND = 'make hooks'`), printed in four findings
(`UNARMED`, `MISDIRECTED`, `NOT EXECUTABLE`, and the no-directory FAIL at :134). The target exists
in **this repo's own root `Makefile`** (added by 5e1320d) and nowhere this package ships:

    $ grep -nE '^[a-z][a-z0-9-]*:' src/godot_devkit/repo/installables/Makefile.devkit | grep hooks
    169:hooks-self-test: ## The engine-boot guard's own block/allow corpus …
    $ grep -rn '^hooks:' src/ tools/          # the installables + the init seed Makefile
    $ make -C ~/workspace/nullbound -n hooks
    make: *** No rule to make target `hooks'.  Stop.

    $ (cd <trail clone> && godot-devkit check hooks)
      UNARMED        core.hooksPath is unset, so git runs nothing under tools/hooks/ whatever is
                     in it — `make hooks`
    [check:hooks] FAIL — 1 finding(s) across 9 hook(s) under tools/hooks/, 1 path(s) excluded …

trail passes only because trail hand-rolled its own `hooks:` target years ago; nullbound has none,
and neither does the `Makefile` that `godot-devkit init` writes (`project-Makefile` is
`DEVKIT_VERSION` + `include Makefile.devkit` and nothing else). So every freshly-`init`'d project
and one of the two live consumers get an instruction that fails. The gate is reachable without any
opt-in — `godot-devkit check hooks` is in the CLI help this release added (cli.py:87) and
`KNOWN_GATES` frames it as "for a repo that HAS decided" — so "stock OFF" bounds who *reddens*, not
who reads the sentence.

The committed guard cannot catch it: `tests/test_check_hooks.py:210`
(`test_the_repair_the_gate_names_is_the_target_that_performs_it`) reads `REPO_ROOT / 'Makefile'` —
the one Makefile where the target happens to exist. `doctor.sh:241,244` gets the same repair right
(`bash tools/setup-hooks.sh`), so the two shipped surfaces disagree.

This is the shipped bug (`self-hosting-has-no-arm-or-verify-target`, "there was no target to run and
none that looked") reproduced one layer out. Fix, either: (a) add `hooks: ## Arm the tracked git
hooks` → `@bash tools/setup-hooks.sh` to `Makefile.devkit` and extend the test to assert it there
too — which also makes the self-hosting claim true for consumers; or (b) make `ARM_COMMAND` `bash
tools/setup-hooks.sh`, the file `install-hooks` actually writes into every consumer, and point the
test at the installable roster instead of this repo's Makefile.

## MINOR

### m1 — `make smoke` runs `git worktree prune` in a live consumer, cannot clean its own leak, and reds on somebody else's dead registration

`tools/consumer_smoke.py:744-746`. The `finally` is `worktree remove --force` → `worktree prune` →
`shutil.rmtree(holder)`. Because `prune` runs *before* the holder is removed, a failed removal
leaves our directory on disk and `prune` skips it — so the call can never clean this run's own leak
by construction. Its only reachable effect is on registrations that are already prunable, i.e.
**somebody else's**, in a repo this file's header calls read-only.

Repro on the clone, simulating a crashed prior smoke (Ctrl-C, or macOS reaping `/var/folders/`):

    $ git -C <clone> worktree add --detach -q /tmp/crashed/wt HEAD && rm -rf /tmp/crashed
    $ python3 -c 'consumer_smoke.against_the_release_runners(<clone>, report)'
    FAIL  worktree list unchanged  the worktree list changed and none of it is this run's:
                                   appeared [], left ['/tmp/crashed/wt']

`make smoke` is in `make milestone`, so a release gate reds for a condition the gate itself caused,
one row after four green ones. The leak-detection half is sound and I proved it separately (below).
Fix: drop the `prune` call — it cannot clean ours, and the leak row is what reports one.

### m2 — a deleted test's body was grafted onto an unrelated test, so the case lost its name

`tests/test_pm_ledger_record.py:270-286`, from 3a7d81a. The five new `<synthetic>` methods were
inserted at the `def` line of `test_a_dispatch_that_never_wrote_reports_its_whole_tool_count`, and
that test's body — `tool_calls == 2`, `tool_calls_before_first_write == 2` — ended up as the tail of
`test_only_the_exact_token_is_the_pseudo_name`, after its `for` loop and unrelated to its docstring.

    $ pytest -q --collect-only -k "never_wrote or whole_tool_count"
    no tests collected (1713 deselected)

The assertions still execute, so no coverage is lost — but the case is invisible by name, a
regression in it would be diagnosed as "the exact token is the pseudo name" failing, and it dies
silently if that test is ever rewritten. It is also the one of the eight removed test names in this
range that a "no test deleted" audit cannot account for by pointing at a replacement. Fix: split
lines 280-286 back into their own `def`.

### m3 — no consolidated "at the pin bump" list for 0.24.0, which is 0.23.0/M3 one release later

`CHANGELOG.md` `## Unreleased` carries eleven bullets and no adoption paragraph; the steps are
spread across three of them. A consumer bumping the pin needs, precisely: (1) `install-runners
--force` — else `scenario.sh` keeps the single-rung cache recovery and `integration.sh` never sets
`GDK_SCENARIO_IN_SWEEP`; (2) `install-ci --force` — else `verify.yml` still runs `make milestone`
with no engine, gdlint or shellcheck, which is the bug `ci-verify-installs-no-godot` was filed for;
(3) `install-hooks` (no `--force` needed now) if they want the additions this release lands beside
their edited headers. Nothing is red without them, which is exactly why the list needs to exist —
0.23.0's M3 was the same finding and it was fixed with one paragraph.

## NIT

- **n1** `tools/consumer_smoke.py:506` — `canonicalize_invents_no_index` discards the verb's exit
  code, and its PASS condition is `invented == 0`, which a canonicalize that refused every file also
  satisfies (the row would print `0 invented, 0/N authored index= restored`). The sibling
  `canonicalize round trip` row would catch a total no-op, so the direction is guarded jointly, not
  by this row alone. One `if code != 0: faults.append(...)` closes it.
- **n2** `installables/doctor.sh` — a Godot project with a built `.godot` and zero tracked `.uid`
  sidecars prints `ok uid index covers 0 tracked .uid sidecar(s)` and `[DOCTOR] PASS`. Reproduced on
  a scratch repo with a real-layout empty `uid_cache.bin`. The zero is disclosed in the line, and
  "nothing to be stale about" is a true answer, so this is a NIT and not the 0.23.0/C1 shape — but
  it is the one PASS-over-0 in the release and worth naming next to rule 4.

## QUESTION

- **q1** `GDK_SCENARIO_IN_SWEEP` is set by exactly one caller (`integration.sh:766`, the only
  invocation of `$SCENARIO_SH`, asserted by `test_the_fan_out_tells_every_job_it_has_peers`). Two
  *hand* runs in one tree — `make scenario NAME=a` and `make scenario NAME=b`, which this SDLC's
  parallel-agent dispatch produces — are peers too, and neither sets it, so rung 2 would `rm -rf
  .godot` under the other. The same file already handles that population for report splicing ("two
  runs of the same scenario … a sweep alongside a hand run, two agents in one tree"). Is the sweep
  marker the right shape, or should rung 2 key off something a hand run also sees? I have no repro
  that shows harm — the escalation needs a stale index, and the loser re-runs rung 1 — so this is a
  question, not a finding.

## The open bug's release posture

**Defensible, and I would ship it.** `bugs/index-is-derivable-under-an-instanced-parent` is refused
on measurement rather than on argument, and I checked the three things that make "refused" different
from "not looked at":

1. **The census reproduces.** My independent run of the smoke row on the trail clone returned trail
   116 / 0 invented / 5 of 17 restored / 12 not derivable / 10 not index-identical — every number in
   the bug's table, unchanged.
2. **The guard is live, not a census of zero.** I mutated a copy of `src/` so `_restore_indexes`
   writes `index="7"` on every created node with a parent, and ran the row against it:
   `FAIL  canonicalize invents no index  1378 invented over 116 scene(s):
   scenes/about/about.tscn [node name="Bg" parent="." instance=ExtResource("2_paper")] -> index="7";
   …` — it reds, it counts, and it names culprits. The `if not files: report.skipped` branch means
   an empty roster is a loud skip and never a pass.
3. **The direction is the safe one.** The refused rule takes nullbound from 0 failing scenes to 26
   and invents 87; shipping nothing invents 0 across 310 scenes on both trees. The blocking
   experiment is named with a file, and all four of its outcomes are pre-mapped to decisions, so
   whoever runs it does not re-read the bug.

One honest scoping note on the bug's own evidence, offered as a caveat rather than a finding: I did
**not** reproduce its specific mutation figures (38 / 87 / 4). My first attempt at "the rule as
filed" — deleting the `type=`/`instance=` skip — invented nothing at all, because that skip is not
the whole rule; reproducing 38 needs the parent-resolution and fallback the bug implemented and did
not commit. I proved the guard with my own mutation instead, which establishes the property that
matters (the row reds on invention and names it). If anyone later needs those three numbers back
they will have to re-derive them; the committed artifact is the row, not the rules.

## Probed with deliberately-broken input

**The cache ladder** (stub `godot` in a scratch Godot project, counting engine invocations): a tree
whose uid class never clears → rung 1 rebuild + retry, rung 2 `REMOVING .godot/` announced BEFORE
the act, rebuild + retry, then stop — **3 boots / 2 imports, `.godot` gone, bounded**. Same tree with
`GDK_SCENARIO_IN_SWEEP=1` → **2 boots / 1 import, `.godot` marker still present**, and the run prints
`rm -rf .godot && make import-cache` instead of doing it. `godot_exit` is a global assigned inside
`run_scenario`, so rung 2 re-evaluates fresh values; the `rm` operand is a literal and `cd
"$REPO_ROOT"` + `[ ! -f project.godot ] && exit 2` run before anything, so it can only fire inside a
verified project root. Committed cases already cover all of this
(`test_runners_installable.py:494-562`) including a genuinely failing scenario costing **1 boot / 0
remedies**.

**The worktree phase**, sabotaged by locking the worktree so `remove --force` cannot succeed:
`FAIL  worktree list unchanged  LEAKED a worktree into a live repo: /var/…/wt — 'git worktree remove
--force' exit 128: fatal: cannot remove a locked working tree` — loud, named, never retried blind.

**`install-hooks` partial writes**, on a scratch repo: one hook body-edited outside the header and
one hook deleted → **exit 1**, `[install] wrote tools/hooks/cc-ledger-subagent.sh`, `pre-push` still
carrying the local edit, and `1 file(s) with nothing in the way was written; it was withheld and no
existing file was overwritten`. An addition beside a withheld replacement cannot exit 0 (`return 1
if collisions else 0`, and the committed
`test_an_addition_beside_a_withheld_replacement_still_exits_1` asserts it). Header-only edit →
`differs ONLY inside its project-config header … leave it as yours`, still exit 1, nothing written;
`--diff` on the same tree → exit 0 and one `differs ONLY inside its project-config header` line.
A DEFECT still refuses the whole command before anything is written, and `pm install-skills` still
calls `collision_refusal` without `wrote`, so it keeps the all-or-nothing sentence.

**`check hooks`** on six scratch trees: empty `tools/hooks/` → `FAIL — 0 hook(s) … so this reports
on nothing`; a directory holding only `_lib.sh` and `x.local` → `FAIL — 0 hook(s) …, 2 path(s)
excluded from scope` (the filter disclosed, not subtracted); a non-executable `cc-` hook → `NOT
EXECUTABLE`; a `cc-` hook that dies on `set -u` → `DEAD … exited 1 on a payload it cannot read` with
bash's own error; an unparseable git hook → `DEAD … does not parse`; `core.hooksPath=.githooks` →
`MISDIRECTED` naming both paths. All exit 1. Run against this repo it mutates nothing (`git status`
identical before and after).

**The CI engine derivation**, run as a shell fragment against both live consumers'
`project.godot`: `config/features=PackedStringArray("4.6", "Forward Plus")` → `engine=[4.6]` on
each.

**The migrated rows against the tests they replaced**, assertion by assertion: props (four checks:
`all accounted for`, no `BUG`, ≤30 DEAD, `code == 1 if dead else 0`) — identical; round trip (no
change, `checked > 100`) — identical, and now required *per consumer* where the unit test summed
both; uid differential (decodable, both formulations agree, repair target stable, census floor 200)
— identical, plus a new unit test pinning the smoke's restated predicate against the codec test's on
every corpus uid, the whole encoder id space, and eight hand-written clause vectors; defaults
elision (exit 0, idempotent, deletion-only) — identical, and now run over *both* consumers where the
unit test returned after the first that changed anything; canonicalize round trip (header uid still
absent, body byte-identical) — identical, with the scene picked by a rule (max degradation) rather
than by name. Eight test functions left `tests/` in this range and 110 arrived; seven of the eight
have a named replacement, and the eighth is m2. `grep -rn available_consumers tests/` is empty and
no test skips for a missing consumer, so both of that feature's ship criteria hold.

## Not verified

- `make milestone` and `make matrix` end to end, and therefore the 8-minute ship criterion — the
  orchestrator's run, deliberately. What I can say about the number: the floor's full suite is
  **170.9 s** on a quiet machine and each non-floor slice is **3.2 s**, so the matrix's pytest cost
  is ~180 s. The record's `1045 s → 459 s` does not reproduce at 459 — it reproduces *lower* — and
  the record itself says why (`~177 s of uv environment setup for four interpreters in a cold
  worktree, measured while two agents in another repo were running a parallel headless-Godot
  sweep`). The claim is conservative in the safe direction and its conditions are disclosed; it is
  not a number that fails to reproduce.
- The smoke against **nullbound**: read only. An agent is working in that checkout and its tree
  moves; I ran the full 18-row smoke against a trail clone instead, and only read nullbound's
  `Makefile`, `project.godot` and `git worktree list`. So the nullbound halves of the CHANGELOG's
  live numbers (194 scenes, 39/39, 5,693 files) are unre-derived here.
- `make hooks-self-test` as a target (I ran the three hooks' `--self-test` directly, which is what
  it wraps), and `make gates` / `make test` as targets (I ran `check all` and pytest directly).
- Whether Godot **4.6.2** — `GODOT_PATCH: "2"` against nullbound's and trail's declared `4.6` — is
  a tag `chickensoft-games/setup-godot@v2` can fetch. That is a network fact and this run had no
  reason to reach one.
- Windows and Linux: reasoned from source. The couriers' non-bash-vehicle case did run under real
  `/bin/dash` here.
- `check test-shape`, `check uid --fix`, `pm ledger report`, the four agent definitions and the
  `.claude/` skills — untouched by this range beyond a one-line severity edit in four reviewer
  definitions, and passed by the 0.23.0 review. Not re-litigated.

## The bump

**MINOR holds by rule 7's letter.** `check all`'s stock roster is unchanged — `hooks` lands as
`KNOWN_GATES['hooks'] = False`, so no consumer's `make check` gains a gate on the bump (verified:
`check all` on the trail clone is exit 0 through the release's own runners). `Makefile.devkit` is
untouched, which is where the major line is drawn. `install-hooks`'s exit code on a collision is
still 1; what changed is that additions now land beside the withheld file, which a caller reading
only the code cannot see.

Two things that are not no-ops and belong in m3's list: a consumer who does not run `install-runners
--force` keeps the single-rung cache recovery and a fan-out that never marks its jobs, and one who
does not run `install-ci --force` keeps a `verify.yml` that runs `make milestone` with no engine.
Neither is red — they are silently the old behaviour, which is the argument for saying so in one
paragraph.

The closest thing to a major-line question is `scene canonicalize` no longer writing `[editable
path=]` at all. It is a write verb rather than a default gate, it writes strictly *less*, it does
not remove markers a file already carries (proved: the clone's 116-scene round trip is
byte-identical), and what it stopped doing was inventing authored state on 26 hosts across 10
consumer scenes. MINOR is right.

```text
verdict: RELEASE-WITH-FIXES
| id | severity | disposition |
| M1 | MAJOR | open |
| m1 | MINOR | open |
| m2 | MINOR | open |
| m3 | MINOR | open |
| n1 | NIT | open |
| n2 | NIT | open |
| q1 | QUESTION | open |
```

---

## Second pass — 0.24.0 — `the-lifecycle-says-what-it-means`: pre-accept review

Reviewer run 2026-09-04 over `0d3a8ad..HEAD` (6 commits). Method: every gate-semantics claim probed
by RUNNING deliberately-broken input against scratch trees — a full 7×7 D5 feature×story matrix (49
pairs), the milestone walked through all five post-`building` states, 21 transition flips plus
`planning→done` and `done→building`, malformed `devkit.toml` values, a directory name with a space,
CRLF frontmatter, a non-UTF-8 story, a truncated fence, and an empty `.md`.

**This pass lived in its own file until M2 below was fixed.** `verdict.py` refused a second verdict
block, so appending here turned `pm ledger report 0.24.0` from exit 0 into exit 2 — the package could
not hold the multi-pass review its own re-ordered protocol produces. `parse` now returns one Verdict
per block and the report renders one row per pass, so the two records are one record again, which is
what they always were.

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

```text
verdict: RELEASE-WITH-FIXES
| id | severity | disposition |
| C1 | CRITICAL | landed in-place |
| M1 | MAJOR | landed 9e60f53 |
| M2 | MAJOR | landed in-place |
| M3 | MAJOR | landed 9e60f53 |
| m1 | MINOR | landed 9e60f53 |
| m2 | MINOR | open |
| m3 | MINOR | open |
| m4 | MINOR | open: the window refuses `pm feature review`, so the reviewing report survives the rollout; a project declaring its own `review` still loses it |
| n1 | NIT | landed 9e60f53 |
| n2 | NIT | open |
| n3 | NIT | open |
| n4 | NIT | landed 9e60f53 |
| q1 | QUESTION | open |
| q2 | QUESTION | landed in-place |
```
