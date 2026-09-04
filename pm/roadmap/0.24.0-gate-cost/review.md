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
