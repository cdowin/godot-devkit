# 0.25.0 — the-godot-kit-alone: feature review of `the-agentic-half-leaves`

Reviewer run 2026-09-06 over `v0.24.0..38d7124` on `milestone/0.25.0-the-godot-kit-alone` (35 commits,
173 non-`pm/` files, +6,124 / −36,950). Method: no diff was reasoned about. Every claim below was
produced by breaking something and running the suite, or by running a verb against a scratch tree
built for it. **Twenty-two mutation probes**: a guard deleted from a copy of `src/`, the whole 196-case
suite run, the file restored and `sha256` compared before the next one. Every probe ran in a
`git archive HEAD | tar -x` extraction under `/private/tmp/…/scratchpad/pristine`, never in this
checkout; the same extraction was made at `812a782` (679 cases), `3dbb02f` (576) and `v0.24.0` (1776)
to date every hole rather than assume it. Nothing outside this repository's own checkout was
read or written. This checkout's `src/` and `tests/` are byte-identical to a backup taken before the
first probe (`diff -r` empty, `__pycache__` aside); `git status` is one line, the ledger rows my runs
appended.

**Verdict: RELEASE-WITH-FIXES.** The shed is clean and the criteria that can be proved by running
something are proved. All eight gates FAIL on a zero-file census and exit 2 on a bad config value;
`install-runners` is idempotent, refuses a collision naming every colliding file, and its
`Makefile.tiers` resolves under the pinned `Makefile.devkit` with both tier lists populated; every
retired verb exits 2 naming `agentic-sdlc`; the package is stdlib-only and compiles on a real 3.11.
Every baseline in `2f956ea` re-derives, several of them exactly. Three MAJORs, all one-case or
one-line fixes: **two of `core/config.py`'s refusals lost their only coverage in this range and no
subsumer was named** — the module CLAUDE.md singles out, and deleting either guard leaves 196/196
green; **`check tres` is the one gate of eight whose zero-census FAIL is asserted by nothing**; and
**`[tests] budget`/`cases`, which criterion 4 says hold the numbers, are graded by a verb no rung
runs.**

## Blockers

- `M1` MAJOR `src/godot_devkit/core/config.py:61,70` — `str_tuple`'s empty-list refusal and `text()`'s
  non-string refusal have no covering case; both were covered at v0.24.0 by tests deleted with the
  repo family, shown by `mutate.py C2/C3` → `196 passed` and by coverage contexts at v0.24.0.
- `M2` MAJOR `src/godot_devkit/godot/checks/tres.py:57` — the zero-census FAIL is asserted by nothing;
  7 of 8 gates redden, `tres` does not, shown by `census_mutate.py` (`if not checked:` → `if False:`)
  → `196 passed`.
- `M3` MAJOR `devkit.toml:24` — `[checks] all` omits `budget`, so the ceilings criterion 4 names are
  graded by nothing any rung runs, shown by `grep -c budget .gate-reports/check.log` → `0` and
  `agentic-sdlc close --help` / `steps.py:26-34`.

## Criteria

| # | criterion | verdict | proof |
|---|---|---|---|
| 1 | `repo/` gone; `godot/` + the `core/` it uses remain; CLI routes only the Godot verbs and `check <gate>\|all` | **met** | `ls src/godot_devkit` = `cli.py core data godot`; 8 retired verbs and 5 retired gates each exit 2 naming `agentic-sdlc`; `refs`, `orphans`, `autoloads`, `tiles`, `scene*`, `check <eight>` all route |
| 2 | `install-runners` writes the runners, the sandbox hook, `ci-uid-guard.yml` and `Makefile.tiers`; idempotent, `--diff`, refuses a collision | **met** | scratch consumer: 15 files written; second run byte-identical; a hand-edit → exit 1 naming `Makefile.tiers` and every other collision, nothing written; addition beside a withheld replacement → exit 1 with 1 `wrote` line; `--diff` → exit 0 + the unified diff |
| 3 | `check all` is the eight Godot gates, stock, joined to `make check` through a target `install-runners` writes and `[gates] extra` names | **met** | `bash tools/dev/godot_devkit_on_fixture.sh check all` → eight PASS lines, exit 0; empty project → eight FAIL lines, exit 1; eight bad-config values → exit 2 each; `make -pn` in the scratch consumer resolves `godot-check` and both `GDK_*_TIERS` |
| 4 | what remains bites at the cheapest tier, is proved once, reddens under a probe per gate and write verb; the numbers held by `[tests] budget` / `cases` | **partly** | 12 of the 16 probe rows reproduce naming the case the table names; every baseline re-derives (below). **M1**, **M2**, **M3**, n3 |
| 5 | README, CLAUDE.md, SDLC.md, the seeds and both version sites say 0.25.0; the CHANGELOG names what a consumer loses and the second pin | **met, with m1/m2** | `__init__.py:2` and `pyproject.toml:7` both `0.25.0`; `Makefile.tiers:11` seeds `v0.25.0`; README §Install is the two pins; CHANGELOG bullet 1 is the loss + the second pin. The trim bullet's numbers are two commits stale (m1) and there is no adoption list (m2) |
| 6 | every story, this feature and the milestone close through the pinned belts | **not run** | story 06 is `planning`, the feature is `building`; `close feature` refuses while a finding is `open`, which is this record's job to produce. The orchestrator's, deliberately |

## The baselines, re-derived

Every number `2f956ea` states, measured again. Wall clocks are from a `git archive` extraction on a
quiet machine; the in-place runs are 5-8% slower and are given as well.

| claim | mine |
|---|---|
| collected 196 | **196**, `pytest --collect-only` |
| pyunit slice 40 | **40 / 156 deselected**; `-m shell` is 156/40 — an exact partition |
| `make pyunit` 1.10s gate wall | **1.053s** (ledger row), 2.10s wall including uv |
| `make test` 27.55s gate wall | **27.62s** in scratch — exact. **29.70s** in place (ledger), still under the 35s ceiling |
| src 4542 / tests 2931 statements, ratio 0.65 | **4542 / 2931, 0.645** — exact, three numbers |
| 679 → 576 → 196 | **679** at `812a782`, **576** at `3dbb02f`, **196** at HEAD — exact |
| shell split 156 marked / 40 unmarked | **156 / 40**, and 19 marked modules / 19 that really spawn |
| the sixteen probes | 12 checked directly; all 12 reddened the case the table names (below) |

**The probe table holds where I tested it.** `return 1` → `return 0` in each gate module reddens the
row's own named case for seven of the eight: `uid`→`…_is_reported_not_offered_for_repair`,
`tres`→`test_check_tres_reports_a_path_only_ref_and_censuses_the_gap`,
`props`→`test_a_carve_out_never_leaks_to_another_class`, `rng`→`…_bare_draw_…`,
`tres-comment`→`…_planted_comment_…`, `unit-disk`→`…_user_path_literal_…`,
`test-shape`→`…_new_over_cap_scenario_…`. `defaults` has no `return 1` (it uses `EXIT_FINDINGS`), so I
probed it directly — `findings.append(` → `[].append(` reddens
`Detector::test_gate_fails_on_the_redundant_fixture`, the row's case. `scene_edit`'s `doc.save()` → a
no-op reddens 17 cases including `SetProperty::test_appends_a_new_property_to_the_right_node`;
`tiles_paint`'s reddens 4 including `test_the_same_paint_twice_writes_nothing_the_second_time`. And
the sixteenth: deleting `Walk.__len__`'s refusal reddens
`OneWalkOneApply::test_a_walk_refuses_len_and_names_the_remedy`, alone — the restored case works.

**The consolidation's own seams hold.** `VerbCase.text()` really re-parses (`TscnDocument(text).text ==
text`) on every read-back, so the two deleted sweeps are asserted by all 25 scene cases. Address
resolution refused ONCE under `set` is right because there is one code path: all nine spellings of an
unknown node across all seven verbs return exit 1, byte-identical, from
`REFUSED … no node at path 'X'`. `--dry-run` is one mechanism in `main` (`scene_edit.py:368`), and six
of seven verbs return exit 0 with bytes unchanged under it, so `rename`'s single case covers it. Six
of eight `core/config.py` guards redden when broken (C1, C4-C8) — M1 is the other two.

## MAJOR

### M1 — two of `core/config.py`'s refusals lost their only coverage in this range, with no subsumer named

`src/godot_devkit/core/config.py:61` (`str_tuple`'s empty-list refusal) and `:70` (`text()`'s
non-string refusal). This is the module CLAUDE.md names by path — *"Every config value goes through
`src/godot_devkit/core/config.py`. Never `tuple(cfg.get(...))` … that is how a silent PASS over an
empty census ships"* — and the file's own docstring says the empty-list case is the one where a value
*"mean[s] the reverse of what it looks like"*.

    $ python3 mutate.py .../pristine        # each guard -> `if False:`, whole suite, then restored
    C1-str_tuple-bare-string:    CAUGHT          test_check_rng.py::…test_a_bad_config_value_is_refused…
    C2-str_tuple-empty-list:     *** SILENT ***  196 passed, 84 subtests passed in 28.95s
    C3-text-non-string:          *** SILENT ***  196 passed, 84 subtests passed in 29.39s
    C4-config_section-non-table: CAUGHT          test_read_verbs.py::…test_a_bad_section_is_exit_2…
    C5-number / C6-flag / C7-str_tuple_table / C8-number_table: CAUGHT

**It is this range's loss, and I dated it.** At `v0.24.0` both lines are covered; coverage contexts
name the four cases:

    L61 <- test_gates_extra.test_a_malformed_value_is_a_config_error_not_a_narrowed_roster
    L61 <- test_pm_gate.ConfigValidation.test_bad_checks_is_a_config_error_not_a_pass
    L61 <- test_pm_gate.EveryConfigSection.test_no_section_accepts_a_malformed_list
    L70 <- test_pm_gate.ConfigValidation.test_other_scalar_type_errors_are_also_exit_2

`tests/test_pm_gate.py` and `tests/test_gates_extra.py` are repo-family modules, deleted with the
family in `621970e`. `EveryConfigSection` was, by its name, the sweep that asked every section of the
one config reader — and `core/config.py` did **not** leave with the repo half. At `812a782` (679
cases, five commits after the deletion and before either trim) both mutations are already silent:
`678 passed, 1 deselected` with the one environmental failure deselected. So the trim did not cause
this; the deletion did, and neither commit accounts for it. That is the checklist's *"a fix that
narrows … instead of reporting"* in its other direction — coverage of surviving code left with the
tests of code that did not survive.

**Measured consequence, real vs guard-removed, on a copy of the fixture project:**

    [unit_disk] roots = []      GUARDED   exit=2  … roots is empty — remove the key to take the default
                                UNGUARDED exit=0  [check:unit-disk] PASS — 7 test file(s) under  …
    [rng] roots = []            GUARDED   exit=2  UNGUARDED exit=0  PASS — 7 script(s) under  …
    [test_shape] scenario_root = 17
                                GUARDED   exit=2  … must be a string, got 17
                                UNGUARDED exit=1  TypeError: expected str, bytes or os.PathLike, not int

`unit-disk`'s declared scope is `tests/unit` — one file here. With the guard gone it silently scans
**seven**, the whole repo, prints a census naming no root (`under  `), and PASSes; `text()`'s loss
turns exit 2 into exit 1, which is the code reserved for findings (rule 6). The guards are correct
today. What is missing is anything that would notice if they stopped being.

**Fix:** one case at function altitude — there is no `tests/test_config.py`, and mechanism 3's
*"config refusals drop to function altitude"* in fact dropped them to *gate* altitude, where each gate
only exercises the readers its one case happens to use. A `str_tuple(sect, 'x', 'k', ('d',))` over
`[]` and a `text(...)` over `17`, both `assertRaises(ConfigError)`, in `test_boundaries.py`'s
`OneWalkOneApply` neighbour class — a call and an assert, no temp tree, no process.

### M2 — `check tres` is the one gate of eight whose zero-census FAIL is asserted by nothing

`src/godot_devkit/godot/checks/tres.py:57`. Disarming each gate's zero-census guard alone, one at a
time, over the whole suite:

    uid          L437 `if not files:`   -> CAUGHT   test_the_configured_exclude_scopes_every_check_and_an_eaten…
    tres         L57  `if not checked:` -> *** SILENT ***  196 passed, 84 subtests passed in 27.28s
    props        L342 `if report.files == 0:` -> CAUGHT   test_empty_scope_names_what_the_exclude_ate
    defaults     L81  `if files == 0:`  -> CAUGHT   test_gate_refuses_to_pass_on_an_empty_census
    rng          L130 -> CAUGHT   test_a_root_holding_no_scripts_fails_loudly
    tres-comment L55  -> CAUGHT   test_an_exclude_that_eats_the_census_fails_and_a_bare_string…
    unit-disk    L153 -> CAUGHT   test_a_root_holding_no_tests_fails_loudly
    test-shape   L384 -> CAUGHT   test_an_infra_list_that_eats_the_census_fails_loudly

Seven gates have a case whose name is the claim; `tres` has none. Coverage agrees from the other side:
`tres.py` lines 57, 63-66 and 67-68 are executed by no in-process test — the one case that reaches
`run()` returns at `:56` on the findings path, and the only run that reaches the PASS line is
`CliRouting`'s `check all`, which is a `subprocess` and measures nothing.

This is not the trim's doing — the same mutation is silent at `3dbb02f` (576 cases) and at `812a782`
(679). What it is: the sixteen-probe table gives `tres` the row *"path-only ref never reported"*, which
is the findings detector, and that row reproduces. The census half of the same gate was never probed,
and rule 4 puts the census half first — *"a gate that scanned nothing FAILS, loudly"*. The gate does
fail loudly today, measured: on an empty project `[check:tres] FAIL — scanned 0 of 0 tracked
.tres/.tscn; check [tres] exclude_prefixes`, exit 1. Nothing holds it there.

**Fix:** amend `TrackedButDeleted::test_check_tres_reports_a_path_only_ref_and_censuses_the_gap` —
it already builds the drifted repo and already runs `tres` in process. A second `run_check(tres)` in a
`temp_repo('uid_repo', only=[])`-shaped tree, asserting exit 1 and `scanned 0 of`, is four lines in the
case that is already the cheapest `tres` run. Its own docstring says *"This is the cheapest tres run,
so it carries the finding"* — it should carry the census too.

### M3 — the ceilings criterion 4 leans on are graded by a verb no rung runs

`devkit.toml:24`. `[tests] budget = { pyunit = 2, test = 35 }` and `cases = { pyunit = 44, test = 215 }`
are real and they really grade — I lowered them in a scratch copy and got the FAIL:

    $ agentic-sdlc check budget                         # as declared
      ok  pyunit — 1.1s of 2s …   ok  test — 29.7s of 35s …   ok  pyunit — 40 of 44 case(s) …
      [check:budget] PASS — within their time budget: pyunit, test; within their case limits: …
    $ …with budget {pyunit=1,test=20}, cases {pyunit=30,test=150}
      OVER BUDGET test — 29.7s against a 20s ceiling (+9.7s) …
      OVER COUNT  test — 196 case(s) against a 150 ceiling (+46) …
      [check:budget] FAIL — 4 tier(s) over budget …

Nothing invokes it. `[checks] all = ["doc", "pm", "shell", "hooks"]`, so `make check` runs four gates
plus `godot-check`, and the orchestrator's own transcript proves it:

    $ grep -c 'budget' .gate-reports/check.log        # from the make check at 11:31
    0

Nor do the belts. `close story` runs `[verify] story` (`make pyunit`); `close feature` checks story
states and the review record; `release`'s `DEFAULT_RELEASE_STEPS` ends in `gate`, whose
`DEFAULT_COMMANDS` is `make milestone` = `check` + `matrix`. `budget` is `KNOWN_GATES['budget'] =
False` in the pinned kit, i.e. opt-in, and this repo did not opt in. So the sentence in CLAUDE.md:95
and in the CHANGELOG — *"graded by `agentic-sdlc check budget`"* — is true of the verb and false of
this tree, and criterion 4's *"held by `[tests] budget` and `[tests] cases`"* is held by a number
nobody reads. It is the 0.24.0/M2 shape one release later: a signal that exists only on the path
nobody is on.

**Fix, one line, proven:** `all = ["doc", "pm", "shell", "hooks", "budget"]` →
`[check:budget] PASS — within their time budget: pyunit, test; within their case limits: pyunit, test`
under `agentic-sdlc check all`. (`grain-shape` is the same shape and I checked it rather than assume:
`[grain_shape] caps` IS read — lowering `story` to 10 turns PASS into `FAIL — 37 finding(s)` naming
each over-cap story — and the tree is inside its declared caps, longest story body 29 lines against 70.
It is also absent from the roster, which is the same one-word fix.)

## MINOR

- **m1 — `## Unreleased` ships the numbers of the commit before last, and the release skill retitles
  it.** `CHANGELOG.md:34-41` says *"679 → 576 collected, `make test` 72s → 47s, test-to-source
  statements 1.15 → 1.10"* and *"Fifteen deliberately-broken probes"*. The tree is **196**, **27.6s**,
  **0.645**, and **sixteen** probes. `git log --oneline v0.24.0..HEAD -- CHANGELOG.md` stops at
  `2d4b7d9`; `git show --stat 2f956ea` touches no changelog. So the second trim — the one that did most
  of the work — is unrepresented, and these four figures ship as 0.25.0's release notes. Same finding
  as 0.24.0 pass 3's m1, and the same reason it must land before the tag: the artifact IS the thing
  being published.
- **m2 — no "at the pin bump" list, in the BREAKING release.** `## Unreleased` is `CHANGELOG.md:3-43`;
  the *"At the pin bump — the consolidated list, because three review passes asked for it separately"*
  paragraph is at `:46`, inside `## v0.24.0`. An existing consumer must: add `DEVKIT_VERSION` above the
  include; run agentic-sdlc's `install-gates` (this package no longer writes `Makefile.devkit`);
  `install-runners --force` (`Makefile.tiers` is new and `Makefile.devkit` must go); move its Godot
  roster from `[checks] all` to `[checks] godot`; add `[gates] extra = ["godot-check"]`; and expect
  five gates that were outside the aggregate to start reddening. Every one of those is somewhere in
  the five bullets; none is in a list. README §Install covers a NEW consumer, which is a different
  reader. Fourth release running that a review asks for the paragraph.
- **m3 — `core/` still ships the repo half's primitives, and both surviving `walk` callers are
  silent.** Exact grep over `src/` outside the defining module: `walk.children` 0 call sites,
  `walk.matching` 0, `walk.entries` 0, `walk.named` 0, `Walk.census(` **0**, `Walk.disclosures(` 0,
  `Walk.counts(` 0, `Walk.merge(` 0, `config.section_declared` 0, `config.table(` 0. At `v0.24.0` every
  one of those was called, and every caller was under `repo/`. What is left is
  `refs.py:71` and `refs_retarget.py:132`, and both end `return list(found.kept)` — the skipped half
  dropped on the floor. So the module whose docstring says a filter *"cannot be silent by
  construction"* has two callers and both are silent, and `Walk.census()`, the API the type exists to
  force, is dead. `core/apply.py` is the same story: the only `.apply()` caller in `src/` is
  `install.py:490`, which passes `decide=False`, so `apply()`'s all-or-nothing refusal is unreachable —
  disarming `if blocked:` at `:279` leaves **196 passed** while disarming `decide()` itself reddens two
  cases. Coverage reflects it: `core/walk.py` 61%, `core/apply.py` 81%. Nothing here is a live defect;
  it is 100-odd lines of published API with no consumer inside the package it was split for, and it
  makes `test_boundaries.py`'s allowlists guard a primitive nothing routes through any more.

## NIT

- **n1** — `core/walk.py:32-34` says *"`tests/test_boundaries.py` forbids `len(x.kept)` outside this
  file, so a renderer cannot obtain a number without carrying what the number left out."* No such rule
  exists: `grep -n kept tests/test_boundaries.py` returns three lines, all that file's own uses. And
  both `src/` callers spell `list(found.kept)`, which is the same escape. The sentence describes a
  guard that was never written or left with something.
- **n2** — `tests/test_boundaries.py:59` sets the `_sources()` floor at 20 and says it is *"well under
  the real count (~48)"*. The real count is **41** — the repo family took seven modules and the comment
  did not move. A floor at half the census is house-normal; the parenthetical is stale.
- **n3** — `godot/checks/props.py:337` (`BUG census does not balance … return 2`) is asserted by
  nothing: disarming `if report.accounted != report.seen:` leaves **196 passed**. It is the only exit-2
  self-check in the eight gates and it is the one that would catch a props classifier that stopped
  accounting. Cheap to amend into `test_empty_scope_names_what_the_exclude_ate`, which already runs the
  gate to a verdict.

## QUESTION

- **q1 — `refs` narrows its scope by config and discloses nothing.** On a copy of the fixture project
  with `[refs] exclude_prefixes = ["systems/", "tests/", "scenes/", "data/", "."]`:

      $ godot-devkit refs Mover
      # refs: Mover

      (no references found)                    exit=0, disclosure lines: 0

  Byte-identical output to a symbol that genuinely has no references. `refs.py` and `refs_retarget.py`
  are **byte-identical to v0.24.0** (`git diff --stat v0.24.0..HEAD` over both: empty), so this range
  did not cause it and a read verb is not a gate — but rule 4's *"every scope, glob and exclude proves
  its census"* is not addressed to gates alone, `refs` is the verb an LLM asks before a rename, and
  this range removed every caller that used the disclosure API which would answer it. One
  `found.census('file(s) searched')` line on each of the two callers closes it. Related and smaller: an
  unknown key in `[refs]` is silently ignored (`exclude = [...]` instead of `exclude_prefixes` → exit
  0, same output), where the pinned kit names a retired key at exit 2.
- **q2 — the `shell` mark's census of THIS suite is gone.** 0.24.0's `test_shell_mark.py::Census`
  (`MARKED_MODULES = 36` + 8 named unmarked) is not in the 3 surviving cases, which prove the
  derivation over scratch files instead. The module's own docstring names the hazard the census held:
  *"a module that silently leaves the marked side stops running on 3.12/3.13/3.14 and nothing goes
  red."* I measured the property rather than assume it, under `sys.addaudithook`: `-m "not shell"` is
  **0 real spawns** in 0.79s (the 0.24.0 measurement, reproduced at the new scale), and `-m shell` is
  **891 spawns across 19 modules** — every one of the 19 marked modules really spawns, so over-marking
  is zero today. Nothing pins it tomorrow. Deliberate?

## What holds, probed rather than read

**Rule 4, at runtime, all eight gates.** On a git repo holding only a `project.godot`: `uid`, `tres`,
`props`, `defaults` → `FAIL — scanned 0 of 0 tracked …`; `rng`, `unit-disk` → `FAIL — no tracked *.gd
under …`; `tres-comment` → `FAIL — scanned 0 of 0 …`; `test-shape` → `FAIL — scanned 0 of 0 …`. Eight
FAILs, `check all` exit 1, and each names the config key that would explain it. On the committed clean
Godot project the same eight PASS at exit 0, each printing a real census.

**Rule 5 and the config door.** A bare string in each of the eight sections is exit 2 with the
rewrite spelled out (`… must be a list of strings, got 'addons/' — write exclude_prefixes =
['addons/']`); `[test_shape] scenario_root = 17` is exit 2 naming the type. `[checks] godot = "uid"`
is exit 2 (`must be a list of strings`), `["uid","tres!"]` is exit 2 naming `unknown gate(s) tres!`,
and a tree with no `devkit.toml` gives byte-identical `check all` output to one declaring the eight —
that pair is a committed case and it passes.

**Rule 1 and the floor.** AST over `src/`: non-stdlib top-level imports **[]**; `pyproject.toml` has
no `dependencies` key and `requires-python = ">=3.11"`; `compileall` clean on a real 3.11.

**Rule 8.** `tests/test_consumer_independence.py` passes (2 cases, 0.62 s) and is now a DENY-suffix
list with a `FILE_FLOOR = 120` census assertion — the allowlist hole that was 0.24.0's M1 is closed by
construction.

**`install-runners`, seven ways.** First run writes 15 files and prints the `.claude/settings.json`
entry; second run is byte-identical (`shasum` of the tree unchanged) at exit 0; `--diff` over a clean
install is exit 0; a hand-edited `Makefile.tiers` is exit 1 with `Makefile.tiers exists and differs …
move your version aside, or pass --force` plus `nothing was written; every colliding destination is
listed above, not just the first`; two collisions list both, not the first; `--diff` over them prints
the real unified diff and writes nothing; `--force` overwrites at exit 0; and a deleted file beside two
collisions writes the one addition and still **exits 1** — the property 0.24.0 established.

**The tier seam.** In a scratch consumer with `DEVKIT_VERSION := v0.2.0`, `include Makefile.devkit` and
`[gates] extra = ["godot-check"]`, `make -pn` resolves `godot-check`, `uid-scan`, `parse`, `lint`,
`warnings`, `unit`, `integration`, `scenario`, `capture`, `import-cache`, `hermetic-scan`,
`runners-self-test`, `integration-list`, `smoke`, and both `GDK_PRECOMMIT_TIERS := parse lint unit
integration-diff` / `GDK_MILESTONE_TIERS := parse lint warnings unit integration-all`. `make -n
godot-check` expands to `gdk_gate_capture … godot-devkit check all` through the include's own capture,
not a hand-rolled grep.

## Not verified, and why

- **`make milestone` and `make matrix` end to end** — the orchestrator's, deliberately, and they run
  after this review by the ladder. What I can say: the floor's whole suite is 27.6s and the `not shell`
  slice is 0.79s, so the matrix's pytest cost is ~30s.
- **`agentic-sdlc release`, `close feature`, `close story`** — each writes a status. I read
  `--help` and the pinned `conveyor/steps.py` for their check lists and ran neither. Criterion 6 is
  therefore `not run` rather than `not met`.
- **Anything outside this checkout** — rule 8. No path under any sibling consumer checkout
  was read or written, and no git write command was run anywhere.
- **The remaining four probe-table rows** — `refs --retarget`, `scene-diff`, `install-runners` and the
  CRLF round trip. Twelve of sixteen reproduced naming the table's own case; I stopped there rather
  than spend four more full-suite runs on rows whose method had already held twelve times.
- **Windows and Linux** — reasoned from source; nothing in this range adds a platform surface, and the
  3.11 floor was proven on a real CPython 3.11.
- **The 12 deleted `test_pm_gate` / `test_gates_extra` cases other than the four coverage named** —
  they tested `repo/` and left correctly with it. I asked only which of them also covered surviving
  `core/` code, which is M1.
- **Godot itself** — never booted, by rule 2. Every gate here is pure parse and every fixture is text.

Ledger note: my runs appended `pyunit` and `test` gate rows to
`pm/roadmap/0.25.0-the-godot-kit-alone/ledger.jsonl`, which is the only file this review changed
besides itself.

```text
verdict: RELEASE-WITH-FIXES
| id | severity | disposition |
| M1 | MAJOR | landed f5ccf8946 |
| M2 | MAJOR | landed f5ccf8946 |
| M3 | MAJOR | landed f5ccf8946 |
| m1 | MINOR | landed f5ccf8946 |
| m2 | MINOR | landed f5ccf8946 |
| m3 | MINOR | landed f5ccf8946 |
| n1 | NIT | landed f5ccf8946 |
| n2 | NIT | landed f5ccf8946 |
| n3 | NIT | landed f5ccf8946 |
| q1 | QUESTION | landed f5ccf8946 |
| q2 | QUESTION | landed f5ccf8946 |
```
