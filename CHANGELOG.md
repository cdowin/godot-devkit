# Changelog

## Unreleased

- `scenario.sh` (and so `integration.sh`) watches the live engine stream for Godot's GDScript
  parse-error signature and stops the engine on the first one not in the noise allowlist — SIGTERM,
  then SIGKILL after `GDK_TIMEOUT_KILL_AFTER`, through the new library helper `gdk_stop_bounded` —
  printing `[SCENARIO] <name> FAIL — GDScript parse error: <line>` and exiting 1 within seconds,
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
