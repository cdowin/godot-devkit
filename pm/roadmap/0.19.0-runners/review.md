# 0.19.0 — runners: release-gate review

Reviewer run 2026-09-02 over `main..HEAD` on `milestone/0.19.0-runners` (572ff8b … 35139aa).
Method: every shipped file read in full; every claim probed by running it (scratch copies, stub
engine, hook payloads fed as real PreToolUse JSON); seven mutants watched go red.

**Verdict: RELEASE-WITH-FIXES** — no false-PASS path and no contract flip found; one MAJOR
(a red CI run now hides its transcript) is a one-line fix worth landing before the tag.

## Gates, my run

`make gates` 2/2 PASS · `make test` 747 passed, 1 skipped, 3658 subtests · `make smoke` PASS
(20 checks, 2 consumers, both checkouts unchanged — both were clean at run time) ·
`make matrix` PASS on 3.11 3.12 3.13 3.14 · `check pm` PASS (6 milestones, 20 features, 47
stories, 10 bugs). Self-tests: library 29/29, runner 10/10, hook 13 block / 13 allow.
`shellcheck -x` clean on all three installables under bash 3.2.57. Zero `nullbound`/`trail`
hits in the installables. Version 0.19.0 in `__init__.py`, `pyproject.toml`, README ×2.
Worktree clean after `pm init`/`retire`: the only new tracked pm file is `pm/roadmap/ROADMAP.md`
(one row, 0.18.1 → "folded into 0.19.0 — never tagged"); no 0.18.1 directory survives.

## Contract stability (rules 5–6)

Python CLI untouched except `install.py` PLANS/USAGE/_NEXT_STEP data — every existing verb's
exit codes and line shapes are unchanged by construction. Hook exit 0/2 unchanged; its block set
is a strict superset of 0.18.0 (13 block cases, incl. the new `gdk_rebuild_import_cache`).
`install-runners` is idempotent (second run "already current", exit 0); `--diff` exit 0.

## Mutants watched failing (scratch copy of HEAD)

| mutant | result |
|---|---|
| M1 reaper drops the `kill -0` live-pid guard | self-test red: "reap never touches a CONCURRENT run home" |
| M2 hook roster `GDK_BOOT_FUNCTIONS=''` | self-test red: 2 expected-BLOCK cases allowed |
| M3 outcome check `-nt` → `-ot` | runner self-test red 3/10 |
| M4 restore's normalized-diff branch forced true | self-test red: "a real edit was CLOBBERED" |
| M5 loud `make` target appended | `test_makefile_gates` census red naming `['loud']` |
| M6 `GDK_GATE_EXIT="$?"` instead of PIPESTATUS | self-test red: expected 7, actual 0 |
| M7 split-bound fallback disabled (`if false`) | hook self-test red + `test_a_line_past_the_split_bound_still_blocks_a_boot` red |

## Deliberately-broken probes

- Hook (13 payloads via real JSON): `gdk_sandbox_home && godot --headless` BLOCKED (the door
  does not admit a boot behind it); `HOME=/tmp/x gdk_rebuild_import_cache` BLOCKED; a 9,000-char
  quoted line followed by a boot BLOCKED (bound → strict); `source … && gdk_sandbox_home` alone
  ALLOWED; heredoc body ALLOWED. Two false positives found (MINOR-3 below).
- Runner with a stub engine that writes nothing: exit 1, both artifacts named. Stub that writes
  both artifacts after 2s: exit 0, churn report splits `new.gd.uid` from `foo.tres`,
  `project.godot` re-serialization restored. Library moved away: exit 2 naming `GDK_RUNNERS_LIB`.

## Findings

### MAJOR

**MAJOR-1 — `installables/ci-verify.yml` (and this repo's byte-identical `.github/workflows/verify.yml`): a red CI run now loses its transcript.**
`make milestone` routes through `Makefile::gate`, which prints at most `GATE_FAIL_LINES=20`
grep-matched lines plus the verdict and leaves the full stream in `.gate-reports/` — a directory
nobody can open on a GitHub runner. Before this release the whole pytest/matrix output streamed
to the CI log; now a 3.14-only failure shows ≤20 lines shared across four interpreters and no
traceback. Rule 4's "loud failure is a feature" is exactly what CI needs. Fix (one line, in the
installable then `install-ci --force` here): `env: VERBOSE: "1"` on the `make milestone` step, or
an upload-artifact of `.gate-reports/` on failure. Land before the tag.

### MINOR

**MINOR-1 — `gdk_runners.sh::gdk_restore_project_file` reverts a same-line-set REORDER made during the run.**
`_gdk_normalize_project_file` sorts lines, so two files with identical lines in different order —
or a line moved between `[sections]` — compare equal. Repro: snapshot `[autoload] A, B`; during
the run rewrite as `B, A` → "restored … no semantic change" and the file comes back `A, B`.
Autoload order is load order; a cross-section move changes meaning. Only reachable when
`project.godot` changes between `gdk_sandbox_home` and exit — i.e. a peer editing in a shared
tree while a gate runs (the shared-tree case the hooks exist for). Section-aware normalization
(prefix each line with its current `[section]`, sort within) closes it in one `awk`.

**MINOR-2 — `gdk_runners.sh::gdk_gate_capture` under `set -euo pipefail` exits before any verdict.**
The pipeline `"$@" | head -c` fails under pipefail, `-e` kills the wrapper on that line, and
`GDK_GATE_EXIT` is never read: exit 3, nothing printed (VERBOSE=1 shows only the stream). The
header documents "read GDK_GATE_EXIT, never `$?`" but not "never `-e` with pipefail". nullbound's
wrappers use `set -eu` (no pipefail) and the Makefile uses pipefail without `-e`, so both live
callers are safe by accident. Either state the rule in the project-config header or make the
capture `-e`-proof (`if "$@" … | head …; then :; fi` keeps PIPESTATUS readable).

**MINOR-3 — `cc-godot-sandbox.sh::split_command_segments` still blocks a quoted MULTI-LINE string.**
The walk keeps a newline inside quotes verbatim, but the `while read -r segment` consumer splits
on it, so the second line becomes a fresh command word. Repro (real JSON payload, stock hook):
`git commit -m "feat: x\n\ngodot --headless is wrapper-only now" -- a.py` → exit 2;
`echo "a\ngodot --headless\nb"` → exit 2. Same false-positive class the 0.18.1 fix targeted, and
it contradicts the header's "a word in quotes can never be a command word" (SDLC §5: adversarial
against the docstring). Strict direction, not a regression from 0.18.0 — but a multi-line `-m`
body is how agents write commit messages. Fix: replace the in-quote newline with a placeholder
inside the walk, as `<<<` already is.

**MINOR-4 — `import_cache.sh::stale_cache_artifacts` is second-granular on bash 3.2.**
bash 3.2's `[ -nt ]` compares whole seconds (verified: stamp + artifact written in the same second
→ "NOT newer"; APFS itself has ns mtimes). A sub-second editor pass reports "FAIL — did not refresh
the cache (0s)" against a refreshed cache. Loud direction (false red, never false green), and the
self-test's own `sleep 1` before each fresh-artifact case is what hides it from the corpus. Real
editor passes take seconds, so this bites only tiny/warm projects — `sleep 1` after the stamp, or
a `find -newer` comparison, closes it.

**MINOR-5 — `gdk_runners.sh::gdk_rebuild_import_cache` silently runs UNBOUNDED with no timeout binary, while `gdk_run_bounded` refuses (exit 2).**
Repro: PATH without `timeout`/`gtimeout` → `import_cache.sh` prints "up to 300s…" then PASS with
no bound at all. Two functions in one library, two policies for the same missing dependency; the
runner's header ("bounded") and its printed line are untrue on a stock macOS without coreutils.
Warn "no timeout binary — UNBOUNDED" at minimum; doctor.sh does not census `timeout` either.

**MINOR-6 — `import_cache.sh` never checks that `REPO_ROOT` is a Godot project.**
`REPO_ROOT_FROM_HERE="../../.."` is a hardcoded depth; installed elsewhere, the runner `cd`s into
an arbitrary ancestor, mints `.headless-userdata/` there and boots `--path .` in it. With a real
engine the outcome check then fails with "either failed or hit the 300s bound — raise
GDK_IMPORT_CACHE_TIMEOUT", which misdiagnoses. The usage text promises "2 = harness error
(unusable repo …)" but no code path produces it for a missing `project.godot`. One `[ -f
"$GDK_PROJECT_FILE" ] || exit 2` after the `cd`.

**MINOR-7 — `cli.py` top-level `--help` "Installers" block does not list `install-runners`.**
`install-runners --help`, README and USAGE do; the CLI's own discovery surface is the one place a
consumer reads first, and the verb is routed (`install_commands()` reads PLANS) but undocumented
there. README says "All five take --force and --diff"; the CLI help still shows three.

**MINOR-8 — `CHANGELOG.md` `## v0.19.0` does not read as one release on the corpus counts.**
The folded 0.18.1 bullet says "11 block / 9 allow stock, 13 / 11 once … SANDBOX_FUNCTION"; the
runners-guard bullet says "11 / 9 → 13 / 13". Shipped: stock 13/13, armed 15/15 (asserted by
`test_the_armed_corpus_grows_by_exactly_the_function_cases`). The "13 / 11" armed figure is stale.

### NIT

- `install-runners` writes both files `-rw-r--r--`; `import_cache.sh`'s header spells its usage
  as a direct exec. `_NEXT_STEP['install-hooks']` mentions the exec bit; `['install-runners']`
  does not (nullbound's target runs `bash …`, so it works there).
- `_gdk_reap_stale_run_homes`: `kill -0` on another user's live pid is EPERM → treated as dead →
  `rm -rf` of a concurrent run's HOME in a shared checkout owned by two users. Narrow.
- `import_cache.sh` churn split: `grep -F ".uid"` is an unanchored substring; anchor `\.uid$`.
- `gdk_sandbox_home` roots the sandbox at `$PWD`, `GDK_PROJECT_FILE` is `$PWD`-relative — a
  wrapper that `cd`s mid-run silently drops the restore (`[ ! -e ]` path). Header says
  "repo-relative"; it is cwd-relative.

## Not verified

- No real engine was booted (rule 2): the runner's boot path was exercised with stub `godot`
  binaries only; the 300s bound and `--kill-after` escalation are proven on `sleep`, not Godot.
- Linux/bash 5 behavior reasoned from the source, not run (CI matrix is the only Linux run and it
  is green; MINOR-4 is a bash-3.2-only artifact).
- S4's consumer half (nullbound/trail install, fork deletion, verdict-line diff) — pending the
  tag by the story's own `## Done`; the consumers' current `_common.sh` forks were read for the
  function-roster comparison only (all 15 ported names present as `gdk_*`; the two
  scenario-report reapers deliberately stayed consumer-side).
- Windows: the installables are bash; nothing here claims otherwise.

## Landed — 2026-09-02

MAJOR-1 landed (CI `VERBOSE: "1"` + `.gate-reports/` uploaded on failure; `--help` lists `install-runners`). The 8 MINOR + 4 NIT are filed as `0.20.0/bugs/review-minors-from-0.19.0` — this record is their source.
