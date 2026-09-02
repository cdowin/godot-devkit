# 0.20.0 — bootstrap: release-gate review

Reviewer run 2026-09-02 over `main..HEAD` on `milestone/0.20.0-bootstrap` (6a36a5a … e528fe6), in a
scratch worktree. Method: every shipped file read in full; every claim probed by running it — a
fresh Godot 4 fixture stood up with `init` and driven through the real `make` targets (stub engine
where a boot was needed), a seed-equivalence pass over the shipped `devkit.toml`, five mutants in a
git-free copy of HEAD, a wheel build. No consumer checkout was written to.

**Verdict: RELEASE-WITH-FIXES** — no contract flip on an existing verb, and the Python gates hold
rule 4. Three MAJORs, all in the fresh-game path this release exists for: a one-word exec-bit bug
that reddens `make smoke` / `integration*` on every `init`'d project with an empty diagnosis, a
0/0 `PASS` in the unit runner, and a ship criterion (`make precommit` green, zero hand edits) that
is false on the fixture and whose gate is a dry run that cannot see verdicts. Land MAJOR-1 (and the
one-line floor for MAJOR-2) before the tag.

## Gates, my run

`make gates` 2/2 PASS · `make test` 1034 passed, 1 skipped, 3673 subtests · `make matrix` 3.11 /
3.12 1034 passed; **3.13 / 3.14 1 failed** — `test_defaults.py::ConsumerCorpus::test_deletion_only_and_idempotent_over_a_real_tree`,
a `FileNotFoundError` on a nullbound file its developer DELETED mid-run (see NIT-2; the re-run
stays red while that deletion is pending; not 0.20.0 code) · `make smoke` PASS, 25 checks across 2
consumers + the fresh project (the REAL `make doctor` on an `init`'d project exits 0, 6/6 hooks
armed) · `check pm` PASS (7 milestones, 25 features, 59 stories, 11 bugs) · `shellcheck -x` clean
over every installable, bash 3.2.57 · 0 word-bounded `nullbound`/`trail` hits in `installables/` ·
wheel builds; all 41 installables ship, including the extensionless `Makefile.devkit` /
`project-Makefile`, the `.toml` and the `.gd` · self-test counts match the CHANGELOG: parse 10,
lint 8, warnings 8, unit 15, scenario 16, integration 12, capture 10, hermetic 10, library 36,
import-cache 12 · hook corpus 13 block / 16 allow at HEAD, **13 / 13 on `git show
v0.19.0:…/cc-godot-sandbox.sh`** — the v0.19.0 CHANGELOG line is now correct (MINOR-8 closed).

Version 0.20.0 in the four files the release skill names (`__init__.py`, `pyproject.toml`, README
×2 at the install example and the Makefile snippet) plus README's `init` example and
`Makefile.devkit`'s header comment; `uv.lock` agrees. Nullbound was clean when I started and is
dirty from 14:04 with its own developer's throwable/activatables work (21 paths, none under a
devkit-installable path); trail clean throughout.

## Contract stability (rules 5–6)

Default `check all` roster measured on the fixture: `doc props shell tres uid` — unchanged; the
four ported scans are opt-in and `KNOWN_GATES` refuses a typo at exit 2. Every existing verb's
routing is untouched (`cli.py` only ADDS `init` / `gates-extra` / four `_check_module` rows).
`--help` exits 0 on `init`, `gates-extra`, `install-runners` and each new `check` gate.
`install-runners` grows from 2 to 12 files — additive, but a consumer that already carries its own
`tools/dev/runners/*.sh` (both do) now collides and is refused whole without `--force`, as the verb
documents; `--diff` on nullbound (read-only, tree unchanged) shows 6 additions + 6 differing files.

`Makefile.devkit::check` on a green roster: `[gates] extra = ["no-such-target"]` → `make[1]: ***
No rule to make target 'no-such-target'`, exit 2; `extra = ["check"]` → exit 2 with "re-entered
through [gates] extra in devkit.toml — …"; a project target two sub-makes down that runs `make
check` → the same refusal; `"lint scan"` → exit 2; `extra = []` → exit 2; a real extra target runs
AFTER the CHECK verdict and the whole thing exits 0. `make -n` succeeds on all 26 targets and
`make -n check` creates no `.gate-reports/` (the `$${MAKE:-make}` spelling holds). `make help`
renders 26 rows under BSD grep. `init` is idempotent (tree hash identical across two runs, 45 files
written), `--force` provably leaves `Makefile` / `devkit.toml` / `CLAUDE.md` alone (md5 unchanged)
while rewriting a hand-edited `Makefile.devkit`; no `project.godot` / no `.git` each exit 2 with
nothing written.

## Mutants (git-free copy of HEAD, one line each, targeted test file)

| mutant | result |
|---|---|
| M1 `gdk_gate_capture` no longer suspends errexit (0.19.0 MINOR-2) | `test_runners_installable` red |
| M2 `gates_extra.TARGET` admits whitespace | `test_gates_extra` red ("two goals in one string") |
| M3 `rng.RANDOMIZE_RE` never matches | `test_check_rng` red |
| M4 `doctor.sh` absent-GUT-dir branch removed (`elif false`) | **survives** `test_init_verb` (24 passed) AND `test_hooks_payloads` (95 passed) |
| M5 `unit.sh` count-mismatch branch removed (`if false`) | **survives** `test_runners_installable` (99 passed); no test in `tests/` names the branch |

## Deliberately-broken probes

- Fresh fixture (`project.godot` + `icon.svg`, `git init`), `init`, tracked and committed, then the
  REAL `make check`: `[check:uid] FAIL — 1 violation across 0 file(s)` (the installed
  `compile_sweep.gd` has no `.gd.uid`), `[check:tres]` / `[check:props]` FAIL on a 0-file census;
  `doc` + `shell` PASS. `make import-cache` mints `compile_sweep.gd.uid` (and re-serializes
  `icon.svg.import`).
- Stub engine printing `[SCENARIO] smoke PASS`: `make smoke` → `0 passed, 1 failed`, FAILURES
  block EMPTY; `chmod +x tools/dev/runners/scenario.sh` → `1 passed`.
- Stub engine printing `Totals / Scripts 0`: `make unit SYS=typo` and `make unit` on an empty tier
  → `[UNIT] PASS (0/0 scripts loaded — full coverage …)`, exit 0.
- `GDK_SCENARIO_REPORT_DIR=. scenario.sh smoke` in a throwaway repo: before `.git README.md bin
  project.godot src tests tools`, after `.headless-userdata smoke.log`. `GDK_CAPTURE_REPORT_DIR=tests
  capture.sh cap`: `tests/` emptied.
- `check rng` on `return randfn(0.0, 1.0)` + `seed(42)` + `return randi()`: one finding (`randi`).
- Seed `devkit.toml` with every key uncommented vs no file, 18 commands: 14 byte-identical;
  `gates-extra` exit 0 → 2, `check test-shape` exit 0 → 2, `check rng` exit 0 → 1 (STALE on the
  example allowlist entry), `check unit-disk` PASS text differs in counts. `[uid] bogus_key = 1`:
  silently ignored, exit 0.
- Hermetic scan with a LIVE run home (`run-<my pid>-live`): stderr `line 407: _gdk_pid_is_live:
  command not found`, then `note: 1 orphaned run home(s)`; verdict still PASS.
- `make scenario NAME=smoke VERBOSE=1` → 1 console line; `scenario.sh -v smoke` → 3.
- `init` with a hand-edited `tools/hooks/pre-push`: install-hooks REFUSED ("nothing was written"),
  then `[init] OK: git core.hooksPath → tools/hooks` — `setup-hooks.sh` ran anyway.

## Findings

### MAJOR

**MAJOR-1 — `installables/integration.sh::fan-out` (line 262) execs `"$SCENARIO_SH"` directly; `install-runners` writes it `-rw-r--r--`, so every scenario exits 126 and `make smoke` / `integration` / `integration-all` are red on every `init`'d project — with an EMPTY diagnosis.**
`Permission denied` matches nothing in `FAILURE_SUMMARY_RE`, so the FAILURES block prints the
scenario name and nothing under it. `Makefile.devkit` and `_NEXT_STEP['install-runners']` both
say "call them as `bash tools/dev/runners/<x>.sh`"; this one caller does not. nullbound's runners
carry the exec bit, which is why its own sweep never saw it. Fix: `bash "$SCENARIO_SH"` (one
word), and either add `Permission denied|command not found` to `FAILURE_SUMMARY_RE` or tail the
job log when no summary line matched. No test drives `integration.sh` past `--self-test` (MINOR-6c).

**MAJOR-2 — `installables/unit.sh::coverage reconcile` prints `PASS (0/0 scripts loaded — full coverage)` when the census is empty.**
`DISK_SCRIPTS = 0` and GUT's `Totals → Scripts 0` (printed unconditionally by `summary.gd::_log_totals`)
reconcile, and the runner's own self-test comment calls that intended. A typo'd `SYS=`, a tier
root moved without `GDK_UNIT_TEST_ROOT` following, or a slice directory deleted is a green gate.
Rule 4: a gate that scanned nothing must say so. Verbatim port of nullbound `unit.sh:188`, so no
consumer regresses — but the runner now ships to every consumer. Fix: `[ "$DISK_SCRIPTS" -gt 0 ]`
or exit 2 naming the root/slice, before the reconcile.

**MAJOR-3 — the milestone's ship criterion is unmet and its gate cannot observe it.**
`milestone.md` and `init-verb/feature.md` say "`make doctor` and `make precommit` green with zero
hand edits". Measured: `make check` (the first member of `precommit`) is red on a just-`init`'d,
committed project — `check uid` flags the devkit's own `compile_sweep.gd` (shipped without a
sidecar; `check uid` CHECK 3 is in the default roster) until `make import-cache` mints one and it
is committed, and `check tres` / `check props` redden on the 0-file census a scene-less project
has (by design). `make smoke` is red by MAJOR-1. `tests/test_fresh_project.py` asserts `make -n
precommit` — recipes echo, verdicts never run — and `consumer_smoke::fresh_project` runs only the
real `make doctor`. The CHANGELOG bullet already says "`make doctor` green … zero hand edits"; the
PM tree still claims `precommit`. Fix: restate the criterion where it is claimed, add `make
import-cache` (commit the sidecar) as `init`'s next-step 1, and — if `precommit` is to stay the
claim — give the smoke probe the real `make check`.

### MINOR

**MINOR-1 — `installables/scenario.sh::reap_stale_scenario_reports` and `capture.sh`'s `rm -rf "${GDK_CAPTURE_REPORT_DIR:?}"` aim `rm -rf` at whatever the `project config` header names.**
`GDK_SCENARIO_REPORT_DIR=.` deleted the probe repo whole, `.git` included, BEFORE the boot;
`GDK_CAPTURE_REPORT_DIR=tests` emptied `tests/`. The scenario docstring's "a mis-set dir cannot aim
rm elsewhere" is exactly the claim SDLC §5 asks to be attacked, and it is false. Requires an
explicit misconfiguration, so no default or consumer is exposed. Fix: refuse `.`, `..`, `/`, `~`,
empty, and any directory under which `git ls-files` lists a tracked path.

**MINOR-2 — `Makefile.devkit::scenario|smoke|integration|integration-all|capture` ignore `VERBOSE=1`; the docs say every gate honours it.**
`scenario.sh` streams only on `-v`, `integration.sh` and `capture.sh` have no streaming path, and
scenario transcripts land in `.scenario-reports/`, not `.gate-reports/<gate>.log`. The seed
`CLAUDE.md`, the include's `help` footer and README all claim otherwise. Fix: pass
`$(if $(VERBOSE),--verbose)` from the target (or read `VERBOSE` in the runner) and correct the
sentence for the three that are not gates.

**MINOR-3 — `installables/hermetic_run_scan.sh:407` calls `_gdk_pid_is_live`, which nothing defines.**
The library exports `gdk_pid_is_live`. Every LIVE concurrent run home prints `command not found`
on stderr and is counted as orphaned — the leak note counts the opposite of what it says. Verdict
unaffected. `shellcheck -x` cannot see an undefined function and the corpus never plants a live
home. One rename.

**MINOR-4 — `installables/project-devkit.toml` is not inert when uncommented as its header invites.**
`extra = []` and `infra = []` are refused by `core.config.str_tuple` (exit 2 from `make check` /
`check test-shape`); the `[rng] allowlist` line is an example that reports STALE; the
`min_args` / `forbidden_calls` / `ledger` lines are examples too. The header's "a key this package
no longer honours is NAMED at exit 2" holds only for `[pm]` (`model.py::RETIRED_KEYS` /
`RETIRED_SECTIONS`); an unknown key in any other section is silently ignored. Rule 5 in the file
that carries it. Fix: write the two empty lists as examples (`# extra = ["my-scan"]`), mark the
example lines as such, and scope or drop the retired-key sentence.

**MINOR-5 — `godot/checks/rng.py::BARE_DRAW_RE` / `RANDOMIZE_RE` miss `randfn(` and `seed(`.**
Both are the global generator (`randfn` a draw, `seed` a re-seed of the same class as
`randomize()`); the probe passed them silently. Census-exact parity with nullbound's
`rng_scan.sh`, which has the same gap, so no consumer regresses. Two alternation entries.

**MINOR-6 — failing-first tests missing on three shipped behaviours.**
(a) `doctor.sh` three GUT states — M4 survives both files that name `doctor.sh`; the story's "each
with a test watched failing at HEAD" is not true for it. (b) `unit.sh`'s count-mismatch branch —
M5 survives; the self-test covers the parsers, not the branch the story calls load-bearing, and no
test names `COVERAGE FAIL`. (c) `integration.sh` is never run past `--self-test`, which is how
MAJOR-1 shipped.

**MINOR-7 — `repo/init.py::main` arms hooks after `install-hooks` REFUSED.**
`_arm_hooks` runs unconditionally: git config `core.hooksPath` is repointed and whatever
`tools/setup-hooks.sh` exists is executed, under a summary that says the verb wrote nothing.
Gate it on the verb's exit code.

### NIT

- `init` on a hand-edited project-owned file (`Makefile`, `devkit.toml`, `CLAUDE.md`) REPORTS
  ("is yours — left alone") and continues at exit 0 rather than refusing; only devkit-owned
  collisions refuse (exit 1). Documented and tested — noted because it differs from the review
  brief's stated expectation, not because it is wrong.
- `tests/test_defaults.py::ConsumerCorpus` reads every tracked consumer file and tracebacks on a
  tracked-but-deleted one; the gates treat that as a disclosed `UNVERIFIED` skip since v0.17.0 and
  the corpus sweep should too. It is what reddened the 3.13/3.14 matrix in my run.
- The installed `ci-verify.yml` runs `make milestone` with only checkout + setup-uv; on a fresh
  project every member boots Godot or gdlint, so the first push is a red badge and `init`'s
  next-steps do not say so. Both consumers carry their own engine setup.
- `install-runners` on nullbound / trail will refuse without `--force` (both own
  `tools/dev/runners/*.sh`) — expected; the S3 adoption stories are still `todo`.

## 0.19.0 review record — status

All 12 closed. MINOR-1 (section-aware normalization: `index_in`, 2 new self-test cases), MINOR-2
(errexit suspend — M1 proves the test bites), MINOR-3 (in-quote newline: 3 new allow cases,
corpus 13/16), MINOR-4 (`find -prune -newer` + a same-second case), MINOR-5 (`UNBOUNDED` warning +
case), MINOR-6 (`import_cache.sh` exit 2 without `project.godot`), the four NITs (exec bit named
in `_NEXT_STEP`; `gdk_pid_is_live` with `ps -p`; `\.uid$` anchored; `_GDK_PROJECT_TARGET` pinned
absolute), MINOR-7 (shipped in v0.19.0), MINOR-8 (v0.19.0 corpus line reads 13 / 13, measured on
the tagged file). None open.

## Not verified

- No real engine drove `parse` / `lint` / `warnings` / `unit` / `scenario` (rule 2 — stub binaries
  only); the real boot in my run is smoke's `make doctor`. GUT's `Scripts 0` on an empty tier is
  read from `summary.gd`, not booted.
- Linux / bash 5 reasoned from source; the matrix is macOS-only here.
- The consumer-side halves (generic-runners S3, generic-scans S3, makefile-include S2, ci-set S2)
  are `todo` by the PM tree and were not attempted; nullbound's Makefile still pins v0.19.0 and
  trail's v0.18.0.
- Windows: the installables are bash; nothing here claims otherwise.

## Landed — 2026-09-02

Fixes on `milestone/0.20.0-bootstrap`, forward only, each with a test watched failing at HEAD
(or, where the branch already existed and nothing named it, watched failing on the reviewer's own
mutant).

| commit | finding | what landed |
|---|---|---|
| `56f1b51` | **MAJOR-1** + the exec-bit NIT | `bash "$SCENARIO_SH"` at the fan-out, AND every `.sh` DESTINATION written executable by all four install verbs — the mode is part of the OVERWRITE step in `core.apply`, which owns every mutation here. `chmod +x` exactly (the bit joins the classes that can already read), never a flat 0o755. A byte-current script MISSING the bit is rewritten rather than reported `already current`, because the trees this repairs are the ones already installed at 0644. A failing scenario whose transcript matches no summary pattern now gets its tail instead of an empty block. 7 tests red at HEAD. |
| `72cad44` | **MAJOR-2**, **MINOR-6b** | `DISK_SCRIPTS = 0` is a `COVERAGE FAIL` naming the directories it scanned and the root they came from, before every reconciliation (exit 1). `unit.sh` is now driven end to end against a stub engine: the reconciling control, a 3-on-disk / 2-run mismatch, and the two empty censuses (typo'd slice, empty tier). Mutant **M5 replayed — it now dies.** |
| `65228d8` | **MINOR-3** | `gdk_pid_is_live`, the name the library exports. No second definition: the function already carries the EPERM case the 0.19.0 review named, and a second would be a second name for the same fact. The case drives the real gate over a repo holding a run home owned by the test's own pid; a companion puts the underscore back and asserts both symptoms return. Recorded what is NOT asserted: a genuinely dead home is reaped by the C2 probe's own `gdk_sandbox_home` before the leak loop runs. |
| `6ca02c4` | **MINOR-1** | `gdk_report_dir_defect` in the library both runners already source, beside `_gdk_destroy_run_home` — the same fact about a different directory. Three structural refusals: not absolute / not `~`, no `.` or `..` segment (which makes "under the root, not the root" true by construction without resolving a path that may not exist), and nothing git TRACKS under it — the clause that separates `.scenario-reports` from `tests`. 8 cases red at HEAD (4 values × 2 runners), each also asserting the tree is byte-identical after the refusal; 2 more prove the stock dir is not refused. Both review probes now exit 2 with the tree intact. Library corpus 36 → 46. |
| `927f76f` | **MINOR-2** | `scenario`, `smoke`, `integration`, `integration-all` and `capture` route through `gdk_gate_capture` / `gdk_gate_verdict`, so the sentence four docs already carried is true rather than corrected away. `GDK_SUM_TAIL` reads the last TAGGED line (`scenario.sh` closes with `  full report: …`, which the old spelling would have printed as the gate's summary). 10 red at HEAD. |
| `37b8889` | **MAJOR-3** | `compile_sweep.gd` ships its `.uid` sidecar rather than `check uid` gaining a `tools/dev/` exemption — softening the one gate that sees a missing sidecar, keyed on a prefix any file can move into, is the shape rule 4 exists against. The uid is random, not derived, so it was minted ONCE here and is a constant: canonical under the ported codec, identical on every consumer, which is what keeps the install idempotent. `tests/test_fresh_project.py` and the smoke probe now RUN `make check` (`DEVKIT` overridden to the working tree — the stock value is `uvx --from git+…@<pin>` over the network): no verdict may be a finding about a file the install wrote, and the gates that DO apply to a blank tree must PASS, so the first assertion cannot be satisfied by a roster that scanned nothing. |
| `ab461a5` | the rest | filed. |

**The ship criterion, restated to what is true** (`milestone.md` + `init-verb/feature.md`): an
empty Godot 4 project, `godot-devkit init`, then with zero hand edits `make doctor` is green,
all 26 standard targets resolve against the installed include, and `make check` — run, not
dry-run — has NO finding about anything the install wrote. The only gates that redden on a blank
tree are the three reading `.tscn`/`.tres`, over the 0-file census a project with no scene in it
genuinely has: the stock roster being wrong for the repo, which the seed `devkit.toml` names and
narrows in one line, never a gate to soften. `make precommit` is the criterion the day the project
HAS content — its other members each boot the engine over the project's own files.

**Deferred, filed as one bug:** `pm/roadmap/0.20.0-bootstrap/bugs/review-minors-from-0.20.0.md`
(`fix_milestone: 0.21.0`, this record named as its source) — MINOR-4, MINOR-5, MINOR-6a, MINOR-7,
the four remaining NITs, and one caught while landing these: `pm new story` under
`story_ordinal_prefix` mints the file without the `NN-` prefix, so every consumer story is
hand-renamed after scaffolding. 0.21.0's tree lives on another branch, so the file sits under the
milestone that caught it and moves when that branch exists.

### Gates, my run

`make test` **1072 passed, 1 skipped, 3677 subtests** (was 1034 / 3673) · `make gates` 2/2 PASS ·
`make matrix` **PASS on 3.11 3.12 3.13 3.14** — the 3.13/3.14 red in the review run is gone; it was
NIT-2 tracebacking on a nullbound file its developer had deleted, and that deletion is now
committed, so the corpus reads a consistent tree. NIT-2 itself is unfixed and still filed ·
`make smoke` PASS, **26 checks** across 2 consumers + the fresh project, both checkouts unchanged;
nullbound was CLEAN for this run, not dirty · `shellcheck -x` clean over all 41 installables plus
the two extension-less hooks, bash 3.2.57 · `check pm` PASS (7 milestones, 25 features, 59
stories, 12 bugs).

Measured on a fresh `init`'d fixture: **46 files written** (was 45 — the sidecar), `check uid`
census `0 new .gd / 1 tracked sidecar`, `doc` + `shell` PASS, and the only FAILs are
`scanned 0 of 0 tracked` on `uid` / `tres` / `props`.

### Not verified

- Still no real engine behind `parse` / `lint` / `warnings` / `unit` / `scenario` — `unit.sh` is
  now driven end to end, but against a stub printing a GUT transcript, and the `timeout` bound is
  stubbed too. GUT's `Scripts 0` on an empty tier is read from `summary.gd`, not booted.
- The exec bit is asserted on macOS only; `os.chmod` semantics on Windows are not claimed (the
  installables are bash and nothing here says otherwise).
- The report-dir guard's git clause is softly skipped outside a git checkout; that path is
  reasoned, not exercised on a tarball.
- Linux / bash 5 reasoned from source; the matrix is macOS-only here.
- The consumer-side halves (generic-runners S3, generic-scans S3, makefile-include S2, ci-set S2)
  are still `todo`; nullbound's Makefile pins v0.19.0 and trail's v0.18.0.
