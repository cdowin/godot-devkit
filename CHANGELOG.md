# Changelog

## Unreleased

- **A gate can be adopted frozen, then paid down.** `tres`, `props`, `defaults`, `rng`,
  `tres-comment` and `unit-disk` each accept a `baseline` in their own `devkit.toml` section —
  `{ "path/rel.tres" = N }`, one entry per file at its current finding count, the shape
  `[test_shape] ledger` already uses. Held findings are not printed; every run with a baseline
  prints `  BASELINED  N finding(s) in M file(s) frozen by [<section>] baseline`. A file whose
  findings grow past its entry fails with all of them listed (`  GREW  …`); an entry above what is
  left fails until lowered (`  SHRUNK  …`) or dropped (`  STALE  …`) — the baseline only shrinks.
  A malformed entry (not a table, a non-integer or `0`, an absolute, `res://` or `..` path) exits
  2. No baseline declared: output is byte-identical to before.

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
