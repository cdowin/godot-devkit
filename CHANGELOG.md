# Changelog

## Unreleased

## v3.0.2 — 2026-10-04

- Fix: `__version__` in `src/godot_devkit/__init__.py` now matches `pyproject.toml` and `uv.lock`. v3.0.1 was tagged but never released, because its Release run found `__version__` still at 3.0.0. 3.0.2 carries the 3.0.1 comment fix.
- New test `tests/test_version_sites.py` fails when `pyproject.toml`, `uv.lock` and `__version__` disagree. It runs in `verify`, so a mismatch fails the PR, not the release.

## v3.0.1 — 2026-10-04

Text only, no behavior change. Two comments in the `integration.sh` installable named agentic-sdlc 2.x parts (`pm ledger report`, `Makefile.devkit`); they now describe godot-devkit 3.0 (`make verify`, `Makefile.gates`). No installable matches the games' zero-count grep.

## v3.0.0 — 2026-10-04

Breaking for a consumer Makefile: the gate framework moves here from agentic-sdlc.

- New verb `install-gates` writes `Makefile.gates` (the gate library `gdk_gate` / `gdk_gate_sh`,
  verdict lines, `.gate-reports/` logs, and the targets `help`, `check`, `precommit`, `verify`) and
  `tools/dev/gdk_gate.sh`. A game sets `GDK_CHECKS` in its `Makefile` and includes `Makefile.gates`;
  it needs nothing from agentic-sdlc. `check` runs `shell` (shellcheck over tracked `*.sh`) then each
  target in `GDK_CHECKS`; `precommit` is `check` + `GDK_PRECOMMIT_TIERS`; `verify` is `check` +
  `GDK_VERIFY_TIERS` less `GDK_VERIFY_SKIP`. There is no `pm`, `sdlc`, `budget`, ledger code or
  `GDK_LEDGER_CMD`.
- `make milestone`, `GDK_MILESTONE_TIERS` and `GDK_MILESTONE_SKIP` still work as aliases of `verify`,
  `GDK_VERIFY_TIERS` and `GDK_VERIFY_SKIP`. Remove in 4.0.
- The config file is `godot-devkit.toml` (was `devkit.toml`), and the roster key is `[roster] checks`
  (was `[checks] godot`). 3.x reads both old names and prints one deprecation line on stderr. Remove
  in 4.0. Only godot-devkit sections belong in the file now.
- `install-ci`, `install-agents`, `install-hooks` and `install-sdlc` are unknown commands (they were
  routed to agentic-sdlc, which has no CLI since 3.0). `pm`, `init`, `gates-extra` and
  `check doc|shell|pm|hooks|repo-hygiene` still exit 2.
- `unit.sh` fails the tier when the GUT log carries a script parse error, even over a reconciled census
  and a green exit (#51).
- The runners no longer file a cost row: `gdk_runners.sh` drops its ledger shim.
- This repo no longer depends on agentic-sdlc and has no PM tree. Its CI (`make verify`) skips the
  build on a docs-only pull request.

## v2.1.0 — 2026-10-01

- Built and gated with agentic-sdlc 2.2.0; the README's install example pins it.
- `refs <symbol>` finds what Godot wires: a scene `[connection]` naming it as `signal=` or
  `method=` (new bucket `scene connections`), an autoload name declared in `project.godot`
  (indexed like a `class_name`), and a signal or handler named as an argument (`is_connected`,
  `has_signal`, `has_user_signal`, `Signal(obj, "sig")`). A bare autoload or `class_name` in
  code (`var g = GameState`, `if Bus:`, `Player.new()`, `Player.CONST`) is a typed reference,
  and `"/root/Name"` is a dynamic one; `10%Player.MAX` is a use, not a `%` node path. None of
  these reads as unreferenced any more.
- New `refs --rename <old> <new> [--dry-run]` renames a `class_name`, method, signal or
  autoload across `.gd`, `.tscn`, `.tres` and `project.godot` as one plan, or refuses the whole
  rename with every blocking site named (exit 1): a dynamic hit, the name inside a string, an
  occurrence `refs` cannot prove, a scene line naming it outside a connection it rewrites (a
  built-in script, a `NodePath("/root/…")`), a `<new>` already defined or an `<old>` defined
  nowhere. Without types it cannot tell a project symbol from the engine's, so `<old>` or `<new>`
  that is an engine method or signal name (`play`, `pressed`, `_ready`, and common ones such as
  `start`, `get`, `update`) refuses too. A GDScript keyword as `<new>` exits 2. `tests/` is always
  in scope; a matching `res://` path is listed as a `PATH` line, never rewritten; a repeat prints
  `already renamed` and exits 0.
- New `autoloads add <Name> <res://path>` and `autoloads rm <Name>` declare or remove one
  `project.godot` autoload (`Name="*res://path"`), editing only that line. `--dry-run` prints
  the diff, a repeat is a no-op, add then rm restores the file byte for byte. A missing file, a
  non-canonical `res://` path or one whose case differs from the file on disk, a name that is not
  an identifier, an engine class or a project `class_name` (scanned as Godot scans: `addons/`
  counts, dot-directories and `.gdignore`d ones do not), and a name already pointing elsewhere or
  declared disabled each exit 1; a missing or non-UTF-8 `project.godot` exits 2.
- New `stats [<dir>...] [--by dir] [--json]` counts files, lines and code lines per role
  (`.gd` as game, tests, tools or vendored, from the new `[stats]` section, each prefix a
  directory with or without its slash) and for `.gdshader`,
  `.tscn` and `.tres`, with a `func test_` count per tests subdir. Zero files scanned exits 1.
- `check rng` scopes a declared draw's shadow to its own class body, so a `func randf()` in
  one class no longer hides a bare `randf()` in another, and a continuation line (an open
  bracket, a multi-line string, a trailing `\`) never closes a class body early.
- `integration.sh` passes a cache repair's exit 2 through as 2, compares the import cache's age
  to the nanosecond across tracked and untracked-not-ignored sidecars, summarises a scenario
  still red after its rerun from that rerun, says why a warm worker handed back, and refuses a
  near-miss `## Isolated because:` spelling (exit 2, naming the line).
- `make import-cache` lists a rewritten existing `.uid`/`.import` sidecar on its own line
  instead of calling it churn, says what copied the tree and how much, sees a live Godot on a
  project root with a space in it, and puts `--` before paths in every `cp`.
- `scenario.sh` inside a sweep also declines the in-tree editor pass and names
  `make import-cache`; `GDK_LOG_CAP_BYTES` caps each `--suite` slice, and a verdict naming
  another slice is not counted for this one.
- `unit.sh` prints the timeout factor it applied (`timeout 360s (2x, load 4.04 on 4 cpu(s))`)
  and records the bound in its transcript. The runners clear git's own `--local-env-vars` list
  instead of six hand-kept names.
- The release index refuses another project's file, gives only the released tag's files a
  `data-requires-python`, and a re-dispatched tag with an identical wheel rebuilds the index
  instead of refusing; the release workflow sets permissions per job.

## v2.0.0 — 2026-10-01

**Upgrading (major).** Re-install the runners (`install-runners --force`) and edit two things.
Drop `hooks-self-test` from `[gates] extra` and from any recipe: the target is gone, with no
alias. A builder's command is now `make spot SYS=<slice>`, not `make precommit`.

- New `spot` tier, the builder's spot check (gdk#45). `spot.sh` runs gdlint and a compile of only
  the `.gd` files changed vs the merge base of `HEAD` and `BASE` (default `main`), untracked files
  included; `make spot` then runs `unit.sh $(SYS)` and exits with the worse code. No changed `.gd`
  is `[SPOT] PASS — census 0: …`, naming the base. `compile_sweep.gd` takes user arguments
  (`-- res://a.gd …`) and compiles exactly those. `GDK_PRECOMMIT_TIERS` is now `spot`, and
  `make precommit` prints one line that says it is retired.
- Receipts for `warnings`, `integration` (smoke, `--diff`, `--all`, named) and a direct `scenario`
  run (gdk#44). The integration receipt is asked before the engine lease. `GDK_RECEIPT_PATHS` joins
  more paths to a key, so a `## covers:` path in an excluded directory counts. A hit creates the
  file `GDK_GATE_UNMEASURED` names, and `Makefile.tiers` exports it for the `gdk_gate`-wrapped
  scenario targets, so a reused run files no cost row.
- `hooks-self-test` is deleted (agentic-sdlc#122). The guard's corpus is replayed by this kit's
  tests; the hook's comment no longer tells you to wire it into `check`.
- This repo runs agentic-sdlc 2.0.0: build wide, integrate once. Its `[verify]` is `spot` and
  `milestone`, `[integrate]` proves a batch with `check` + `test`, `[tests]` and the `hooks` and
  `budget` gates are gone, and the five retired hooks and eight unshipped agents are removed.

## v1.6.0 — 2026-09-30

- A second engine run waits for the lease instead of exiting 75 (#41). `GDK_ENGINE_GATE_WAIT` bounds the wait in seconds (default 1800); 0 keeps the fail-fast exit.
- unit, parse and lint file a proof receipt on PASS (#42). The key is the tier, its arguments, the engine binary and the tree's content minus prose and the PM tree; never HEAD. Receipts live in the git common dir, so every worktree of a clone shares them. A run over the same inputs prints the recorded verdict marked `reused` and boots nothing. `GDK_RECEIPTS=0` turns it off.

## v1.5.0 — 2026-09-30

- Runner self-tests copy their shared library and isolate stub engine leases. Integration preserves cold and no-rerun options through admission.

- Engine runners share a nonblocking per-user OS lease. Integration holds it across fanout; standalone engine boots refuse competing work with owner context. Read-only verbs remain available. `GDK_ENGINE_GATE_HOME` explicitly selects an isolated admission domain for test fixtures; production defaults to the account home.

- Import scratch copies prune explicit Godot-ignored directories and registered nested worktrees before descent. Ignored runtime addons remain inputs.
- Resource UID lookup reads the target header only. A headerless resource no longer acquires its inner script UID.

## v1.4.0 — 2026-09-30

**Upgrading.** No Makefile or hook edit is required. The README's install section now shows both
kits locked in `uv.lock` (agentic-sdlc 1.0.0 runs only from the lock). One `devkit.toml` edit may be: `[rng]`
allowlist or baseline entries that covered `func randf()`-style declarations (the #30 false
positive) are now reported `STALE`/`SHRUNK` and fail `check rng` until you delete them. Consumers
that grep runner output should note the changed shapes: `SUMMARY: N passed (K flaky[, W
warm-only]), …` (a regex expecting `passed,` right after the number breaks on a flaky run), the new
`FLAKE`, `WARM-ONLY`, `WARM-ABORT` and fixture-selection lines from `integration.sh`, `[UNIT]
timeout Ns (…)` as the unit tier's first line, and the `import_cache.sh` banner and
`dropped N re-serialised files` line (the `the pass wrote into the tree:` line is gone).

- Runners survive several agent lanes on one machine. The `gdk_runners.sh` self-test no longer
  re-initialises the host repo under a git hook (#24). `gdk_pid_is_live` counts a pid as dead only
  on positive evidence (ESRCH), so a sandbox or a hidden process table can no longer make a live
  peer's HOME look reapable (#31). `unit.sh` scales its 180 s bound with load (up to 3x), prints `[UNIT] timeout Ns (…)`
  first, and names `GDK_UNIT_TIMEOUT` on a HARD_TIMEOUT; a `GDK_UNIT_TIMEOUT` that is not a whole
  number of seconds exits 2 (#32). Sourcing the library exports
  `GIT_OPTIONAL_LOCKS=0` (#35).
- `refs` prints signal hits on an untyped receiver under a new `dynamic (untyped receiver)` heading,
  and prints `(no references found)` only when that bucket is empty too (#19). `check rng` no longer
  flags a `func randf()` declaration, or a script's unqualified call to its own draw-named method
  (#30). `install-runners` reads `[checks] godot` through the same roster as `check all`, so where it
  reads the key (a retired `uid-guard.yml` is present) an unknown or malformed value exits 2 there
  too (#28). Every git read the package makes runs with
  `GIT_OPTIONAL_LOCKS=0` (#35).
- `capture.sh` no longer clears its report dir. Before each run it moves the last `<name>.png` to
  `previous/<name>.png`. The window is asked to open off screen (`--position`, `GDK_CAPTURE_POSITION`,
  default `100000,100000`) unless `CAPTURE_VISIBLE=1`; macOS and Windows may clamp part of it back on
  screen, and it can still take focus. A capture run more than 5 times in 10 minutes prints
  one `WARN` (#17, #37).
- `make import-cache` runs the editor import pass in a scratch copy of the whole project (an
  APFS/reflink clone, gitignored inputs included; only `.git/` stays out) and never writes the tree's
  files. `.godot/` comes back by rename. Only new `.uid`/`.import`
  sidecars are copied back; other rewrites are dropped and printed as `dropped N re-serialised files
  (import churn): …`. A killed run leaves the tree byte-identical, and a Godot process holding the
  project gets a `WARN` before the swap (#20, #23).
- `integration.sh --diff` boots only the scenarios that load a touched `tests/support/` fixture,
  following references through other fixtures (`GDK_SCENARIO_FIXTURE_DIR`, validated: a missing or
  absolute root exits 2). A reference is the fixture's `res://` path in any form, its basename after
  a `/` or a quote, its `uid://`, or a `class_name` it declares, searched across the fixture root
  and the whole scenario dir (so a scenario base that loads a fixture counts). A fixture no scenario
  names boots the whole tier and says so (#33). It reruns each failed scenario once, alone: one that
  passes alone prints `  FLAKE  <name> — failed in the sweep, passed alone` and counts green as
  `N passed (K flaky)`. Past max(3, 10% of the slice) failures nothing reruns, and a line says so.
  `--no-rerun` or `GDK_INTEGRATION_RERUN=0` turns this off (#34). Before a
  `--diff`/`--all` sweep boots anything, `import_cache.sh` repairs a stale import cache once (#16).
  The self-test's scratch git repos can no longer write into the host repo under a hook (#24).
- Opt-in warm integration tier (#36): with `GDK_INTEGRATION_WARM=1`, `integration.sh` boots Godot
  once per worker through the new `scenario.sh --suite`, which runs a slice of scenarios against a
  documented START/verdict contract your scenario runner implements. A scenario marked
  `## Isolated because: <reason>` always runs cold, and `--cold` forces the old path for one run.
  The contract requires the runner to exit 0 and to finish each scenario's teardown before its
  verdict line. A crash, a non-zero exit, or an engine error outside a scenario hands the whole
  slice back to the cold path (exit 4, `WARM-ABORT`), as does a stalled scenario. A scenario that fails warm and
  passes cold prints `WARM-ONLY` and counts green (with `--diff`, where the rerun runs). `WARM-ABORT` names a crashed worker, a `WALL:`
  line splits warm from cold time, and `SUMMARY` carries the warm/cold/handed-back census. Unset,
  nothing changes.
- The kit ships as a hash-locked wheel from `https://cdowin.github.io/godot-devkit/simple/`, built
  once per tag by `release.yml`. Add the `pyproject.toml` block that `install-runners` prints
  (a dev dependency plus an `explicit = true` index) and run `uv sync`. When `uv.lock` names
  `godot-devkit`, `Makefile.tiers` runs `uv run --frozen godot-devkit`, so a pulled lock bump takes
  effect without a manual sync. The `GODOT_DEVKIT_VERSION` pin still works exactly as before. With
  both present the pin runs and make warns once. The CI toolchain action runs the same
  `uv run --frozen` when the caller's `uv.lock` names the kit (#38).

## v1.3.0 — 2026-09-28

- `install-runners` writes a composite action, `.github/actions/godot-toolchain`, that installs the
  engine, gdlint and shellcheck at pinned versions and imports the project; `uid-guard.yml` is no
  longer installed. An existing copy is named as retired: safe to delete when `[gates] extra` names
  `godot-check` and `[checks] godot` keeps `uid` (then `check uid` runs in `make check`), and to keep
  otherwise (#26).
- `integration.sh --self-test` reads the sweep once and matches it with no pipe, so a keep-listed
  gate is no longer reported missing on Linux; `warnings.sh` gets the same fix (#27).

## v1.2.0 — 2026-09-12

- `[test_shape] header_ledger` holds a ledgered scenario until it carries BOTH `## Boots because:`
  and `## covers:`; only then is it `HEADED` (drop the entry). A scenario with `covers:` alone —
  what the runner's `--diff` slices by — can now be ledgered instead of failing either way.
- `scenario.sh` (and so `integration.sh`) watches the live engine stream for Godot's GDScript
  parse-error signature and stops the run on the first one not in the noise allowlist — a SIGTERM
  to the bounding `timeout`, which signals the engine's whole group and escalates to SIGKILL after
  `GDK_TIMEOUT_KILL_AFTER` — printing `[SCENARIO] <name> FAIL — GDScript parse error: <line>` and exiting 1 within seconds,
  where it used to sit out `GDK_SCENARIO_HARD_TIMEOUT` and blame a hang (#12). A run that still
  reaches the hard timeout names a parse error in its transcript instead of "likely hang".

## v1.1.0 — 2026-09-12

- README's `devkit.toml` block now shows every key the kit reads with an example of its own shape
  — `[unit_disk] forbidden_literals` (a reason-to-patterns TABLE, not a list) and `[test_shape]
  unit_root`, `infra`, `header_ledger` were missing — and a census test derives the key set from
  the config readers and fails on any key the block lacks or shows in a shape its reader refuses.
- README § Install — two pins names the third step for a repo with a PM tree: `pm init`, then
  `pm vocabulary` to read the flow back, because the flow has no default and a repo that skips it
  has working gates and a `pm` that refuses every work-moving verb; the fresh-repo and
  bumping-consumer paths are written out separately.
- **A gate can be adopted frozen, then paid down.** `tres`, `props`, `defaults`, `rng`,
  `tres-comment` and `unit-disk` each accept a `baseline` in their own `devkit.toml` section —
  `{ "path/rel.tres" = N }`, one entry per file at its current finding count, the shape
  `[test_shape] ledger` already uses. Held findings are not printed; every run with a baseline
  prints `  BASELINED  N finding(s) in M file(s) frozen by [<section>] baseline`. A file whose
  findings grow past its entry fails with all of them listed (`  GREW  …`); an entry above what is
  left fails until lowered (`  SHRUNK  …`) or dropped (`  STALE  …`) — the baseline only shrinks.
  A malformed entry (not a table, a non-integer or `0`, an absolute, `res://` or `..` path) exits
  2. No baseline declared: output is byte-identical to before.
- **Every tier files a cost row, including the four the Makefile does not wrap** (#7). `parse`,
  `lint`, `warnings` and `unit` export `GDK_GATE_VERDICT` — FAIL unless the run reached its PASS,
  HANG on a timeout — and `gdk_runners.sh` hands `gdk_gate_log`/`gdk_gate_verdict` to agentic-sdlc's
  `gdk_gate.sh` (new `GDK_GATE_LIB`, stock: beside it; `Makefile.tiers` exports the include's), so
  the ledger row the wrapper would file is filed without a second wrapper. `unit` also files its
  GUT test count as the census, so `[tests] budget` and `cases` can take a ceiling on the story rung.
- **The scenario tiers are graded on boots** (#8). `integration.sh` prints
  `[INTEGRATION] BOOTS: <n> scenario(s) booted, <cpu>s CPU, <per>s per boot` above its SUMMARY, and
  `integration`, `integration-all`, `integration-diff` and `smoke` pass that count to `gdk_gate` as
  the row's census (`GDK_CENSUS_BOOTS`), so `[tests] cases` on them grades instead of FAILing
  UNCOUNTED. `check test-shape --help` now says it is a readability gate and names boots and
  `[tests] cases` as what governs the tier's cost.
- **`check canonical` and `scene canonicalize --respell` / `--order`** — the two dimensions of `.tres` editor-save churn `check defaults` leaves out, proven by pure parse from the section's own script: floats in the saver's shortest spelling (`0.30` -> `0.3`, emitted only where the 32- and 64-bit forms agree), a bare list on an `Array[T]` export wrapped as `Array[T]([...])`, and a scripted section's properties in declaration order. Line edits only — comments, `uid=` and every untouched line byte-identical, a second run a no-op; an enum element type, an export with an accessor or a section holding an engine property is named or counted, never guessed. The gate is opt-in: not in the stock `check all`, nameable in `[checks] godot`. New config section `[canonical] exclude_prefixes`.

## v1.0.1 — 2026-09-11

**The uid guard follows the branch flow, not `staging`.** The `uid-guard.yml` that `install-runners`
writes used to trigger on pushes to `staging`, a branch that agentic-sdlc's main → milestone branch
→ main flow never creates. It now triggers on a PR into `main` and a push to `main`, the same events
as agentic-sdlc's `verify.yml` (agentic-sdlc #37 made the same move for its own scripts). To guard
pushes to your milestone branches as well, add their glob to `push: branches`. A copy you already
installed is yours: `install-runners --diff` shows the change.

## v1.0.0 — 2026-09-06

First release of godot-devkit as a standalone Godot kit, and the first with a public history of
its own. Earlier versions of this package also carried a repo-discipline half — a PM tracker,
generic gates, installers and release belts — which became [agentic-sdlc](https://github.com/cdowin/agentic-sdlc)
and is consumed from here through a pin, the same way this kit's own consumers pin it. The history
of that period lives in a private archive; nothing in it is required to use or build this package,
and `v1.0.0` is the first tag of the kit as it now is.

**What this is.** Scene tooling and eight Godot gates for Godot 4.x, shipped as a pinned-tag,
**stdlib-only** Python package. It never boots the engine: a `.tscn` is text, and every verb reads
or edits it as text, which is what makes the whole kit safe to run anywhere, any time, in parallel
— in a hook, in CI, across a suite of game repos at once.

**Introspection** — `scene` (a scene's nodes, properties and paths), `scene-diff` (against a git
ref or another file), `refs` (every reference to a symbol, grouped by kind), `orphans`,
`autoloads`, and `tiles` (a TileMapLayer's grid: cell count, bounds, tile-kind histogram).

**Scene surgery** — `scene set | rename | add | rm | reparent | connect | disconnect`,
`refs --retarget` (rewrite every `ext_resource` path and `preload`/`load` literal after a move),
`scene canonicalize` (restore what `PackedScene.pack()` drops) and `tiles paint`. Every write verb
touches only the lines it was asked to, is a no-op the second time, and REFUSES rather than write
a plausible-looking wrong answer. Parse → serialise is byte-identical, proven on a vendored corpus
of real scenes.

**The eight gates** — `check uid | tres | props | defaults | rng | tres-comment | unit-disk |
test-shape`, and `check all` runs the roster. Every one proves its census: a gate that scanned
nothing FAILS loudly, because a false PASS over an empty scope is the one output a consumer cannot
recover from.

**`install-runners`** writes the Godot tier roster (`Makefile.tiers`), the runners, the
engine-boot guard hook and the uid-guard workflow into a consuming project — whole files,
idempotent, `--diff` to preview, and a differing destination refused by name unless `--force`.

**Wiring** — a consumer sets two pins in its Makefile above `include Makefile.devkit`:
`DEVKIT_VERSION` (agentic-sdlc, the gate framework and SDLC) and `GODOT_DEVKIT_VERSION` (this
kit), runs both installers, and joins the eight gates to `make check` with
`[gates] extra = ["godot-check"]`. Per-project variation lives in the consumer's `devkit.toml`;
a repo with no `devkit.toml` behaves byte-identically to one declaring the stock defaults.

**Contract.** Exit codes are 0 pass, 1 findings, 2 usage or config error, and output line shapes
are grepped by consumers — changing one is a minor bump at least. No file here names a consuming
project, reads a path outside its own checkout, or gates on another repo's state; a test enforces
that on every run.

Suite at this release: 201 cases, 43 in the fast tier, `make test` under 30s, with a
deliberately-broken probe per gate, per write verb, the installer, the parse→serialise identity
and the walk-census refusal.
