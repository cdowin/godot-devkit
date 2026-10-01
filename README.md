# godot-devkit

**godot-devkit** is scene tooling and eight static gates for Godot 4.x projects, shipped as a
**pinned-tag, stdlib-only** Python package. It reads `.tscn`/`.tres` files without loading them,
edits them without reformatting them, and gates the silent-failure classes Godot drops without a
word — renamed exports, uid drift, path-only refs. Nothing here boots Godot: every verb is pure text
parsing, safe anywhere, anytime, in parallel.

> **Any change you can make to a scene by hand, you should be able to make through one
> deterministic command that touches nothing else — and prove it, without ever reading the file.**

For a human, the editor stops being mandatory for mechanical work and diffs stay reviewable. For an
LLM: a small stable vocabulary of verbs instead of a bespoke `sed`; determinism, because a tool that
reformats what it was not asked to touch hides its damage inside a legitimate diff; and token
reduction, because a tile-heavy scene costs 100k+ tokens to read where `scene` costs a few hundred
and a write verb costs zero. The commitments: **refuse rather than mangle** (the worst outcome is
never an error, it is silent partial success); **read output is write input**; **idempotence**,
because models retry; **bounded blast radius**; and **`scene-diff`**, so an edit is provable
without re-reading the file.

## Install — two pins

A consumer pins two kits and includes one file. `agentic-sdlc` is the gate framework and the SDLC
(`check`, `precommit`, `milestone`, hooks, CI, the PM tree, the release belts; its overview is
[on DeepWiki](https://deepwiki.com/cdowin/agentic-sdlc)); this kit is the Godot tiers and gates. `Makefile.tiers` finds this kit in one of two shapes; keep one:

| shape | the pin | what `make` runs |
|---|---|---|
| **locked** (recommended) | `godot-devkit==X.Y.Z` in `pyproject.toml`, hash-pinned in `uv.lock` — [below](#consume-it-locked) | `uv run --frozen godot-devkit` — uv syncs `.venv` to the lock first |
| legacy | `GODOT_DEVKIT_VERSION := vX.Y.Z` in the Makefile, ABOVE the include | `uvx --from git+…@vX.Y.Z godot-devkit`, built from the tag |

"Locked" means `uv.lock` names `godot-devkit`; what `.venv` happens to hold decides nothing. With
both, the legacy pin runs, as it did before the lock existed, and `make` warns you to delete the
`GODOT_DEVKIT_VERSION` line (two pins of one tool ship two products). Neither is refused at parse
time. `GODOT_DEVKIT` set to a command overrides both.

Both kits lock the same way: a dev dependency from each kit's own index, hash-pinned in `uv.lock`.
agentic-sdlc runs only from the lock since its 1.0.0 (no `DEVKIT_VERSION` line), so the Makefile
is the include plus your own targets:

```make
include Makefile.devkit      # runs the agentic-sdlc version uv.lock pins
```

```sh
uv add --dev agentic-sdlc==1.0.0 --index agentic-sdlc=https://cdowin.github.io/agentic-sdlc/simple/
uv add --dev godot-devkit==1.5.0 --index cdowin=https://cdowin.github.io/godot-devkit/simple/
# then add `explicit = true` to both [[tool.uv.index]] tables `uv add` wrote
uv run agentic-sdlc install-gates     # Makefile.devkit
uv run godot-devkit install-runners   # Makefile.tiers + runners
```

The legacy shape for this kit is `GODOT_DEVKIT_VERSION := v1.5.0` above the include and
`uvx --from "git+https://github.com/cdowin/godot-devkit@v1.5.0" godot-devkit install-runners`.
Then join the gates to `make check`:

```toml
# devkit.toml
[gates]
extra = ["godot-check"]     # `godot-devkit check all`, the target install-runners wrote
```

`make check` now runs agentic-sdlc's gates and then the eight Godot gates; `make milestone` runs
the Godot tiers `Makefile.tiers` declares. A builder runs `make spot SYS=<slice>`: gdlint and a
compile of only the `.gd` files changed against `BASE` (default `main`), then that unit slice. Every machine and CI runs the same
gate code because `uv.lock` pins the bits.

**A repo with a PM tree has a third step.** agentic-sdlc's flow — the states `pm` moves work
through, `[pm.states.*]` in `devkit.toml` — has no default, so a repo that skips this step has a
working gate set and a `pm` that refuses every verb that moves work:

```sh
make pm ARGS='init'         # writes the flow; a fresh repo can run `agentic-sdlc init` instead,
                            # which is this plus install-gates, devkit.toml and the rest
make pm ARGS='vocabulary'   # reads back the states it wrote, by category
```

- **A fresh repo:** the two pins, `install-gates` (or `agentic-sdlc init`) and `install-runners`,
  `[gates] extra`, then `pm init` and `pm vocabulary`.
- **A consumer bumping a pin:** read both CHANGELOGs; re-run `pm init` once, then `pm vocabulary`;
  `install-runners --diff` prints what a re-install would change and writes nothing;
  `agentic-sdlc adopt <version>` proves the bump.

### Consume it locked

Every `v*` tag is built once into a wheel and an sdist, attached to its GitHub Release (a re-tag is
refused), and listed on a static PEP 503 index on this repo's GitHub Pages,
`https://cdowin.github.io/godot-devkit/simple/` — public, no token. The PyPI name is someone
else's, so the index is declared `explicit` and the kit never resolves from PyPI. `install-runners`
prints this block at the version that ran it:

```toml
# pyproject.toml
[dependency-groups]
dev = ["godot-devkit==X.Y.Z"]

[[tool.uv.index]]
name = "cdowin"
url = "https://cdowin.github.io/godot-devkit/simple/"
explicit = true

[tool.uv.sources]
godot-devkit = { index = "cdowin" }
```

`uv sync` writes `uv.lock`, which records the version and the wheel's hash, so every machine and CI
run gets the same bits and a moved tag cannot change them. Delete the `GODOT_DEVKIT_VERSION` line:
once `uv.lock` names the kit, `Makefile.tiers` runs `uv run --frozen godot-devkit`, which syncs
`.venv` to the lock before it runs, so a lock bump you pull takes effect on the next `make` with no
`uv sync` to forget, and never rewrites the lock. In CI the installed `godot-toolchain` action runs
the same command, `--version`, whenever `uv.lock` names the kit.

- **Upgrade:** `uv add --dev godot-devkit==X.Y.Z`, then agentic-sdlc's adopt belt
  (`agentic-sdlc adopt <version>`).
- **Bots:** the pin lives in `pyproject.toml` and `uv.lock`, where Renovate and Dependabot can see it
  and open the bump PR themselves.

## Quickstart

From inside a Godot repo. See a scene's structure without loading it, then change one thing and
prove the change:

```sh
godot-devkit scene scenes/world/hub.tscn                  # node tree, ext_resources, a few hundred tokens
godot-devkit scene scenes/world/hub.tscn --props          # every [resource]/[sub_resource] value, ids verbatim
godot-devkit scene set scenes/world/hub.tscn Player/Camera zoom "Vector2(2, 2)"
godot-devkit scene-diff scenes/world/hub.tscn --git HEAD  # the one line that changed, and nothing else
godot-devkit check all                                    # the eight gates, one census and verdict each
```

Every write verb takes `--dry-run` (prints a unified diff, writes nothing) and is idempotent: the
same command twice is a no-op the second time.

## Verbs

**Introspection** (pure parse):

| verb | what it answers |
|---|---|
| `scene <file> [--props] [--paths]` | a `.tscn`/`.tres`'s node tree and resources; `--props` every `[resource]`/`[sub_resource]` property value, packed data elided, each id verbatim — the address the write verbs take |
| `scene-diff <file> [--git <ref>]` · `scene-diff <old> <new>` | a structural diff — nodes, properties, resources, reparents — keyed the way the write verbs address them |
| `refs <symbol> [--tests]` | every reference to a symbol, grouped by kind; signal hits on a receiver the index cannot type (`x.sig.connect(`, `emit_signal(&"sig"`, `connect("sig"`) print under `dynamic (untyped receiver)`, and `(no references found)` prints only when that bucket is empty too |
| `orphans [--tests]` | tracked files nothing references |
| `autoloads` | the `project.godot` autoload census, grouped by suffix, layout flagged |
| `tiles <file> [--layer NAME] [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]` | a `TileMapLayer`'s grid: cell count, bounds, tile-kind histogram, per-column/row counts |

**Scene surgery** (edits only the lines it was asked to, or refuses and says why):

| verb | what it does |
|---|---|
| `scene set <file> <node-path> <prop> <value>` | replace or append one property on one node |
| `scene set <file> --resource <prop> <value>` · `--sub-resource <id> <prop> <value>` | the same on a `.tres`'s `[resource]` body or a `[sub_resource]` by the id `scene --props` prints |
| `scene rename <file> <node-path> <new-name>` | rename a node and every NodePath, `parent=` and animation track that references it — never prose, never an export name |
| `scene add <file> <parent-path> <name> <type> [--script res://x.gd]` | add a node; a `--script` ref is minted uid-in-refs from the sidecar, or refused |
| `scene add <file> <parent-path> <name> --instance res://x.tscn` | add an instance node; its ref is minted from the scene's own uid, or refused |
| `scene rm <file> <node-path>` | remove a node with its descendants, connections and editable markers; prunes an ext_resource nothing else uses |
| `scene reparent <file> <node-path> <new-parent>` | move a subtree and fix its NodePaths |
| `scene connect <file> <signal> <from> <to> <method> [--flags N]` · `scene disconnect …` | author or remove one `[connection]`; ambiguous matches are refused, `--flags` names one |
| `scene canonicalize <file>... [--elide-defaults] [--respell] [--order]` | restore what `PackedScene.pack()` drops — uid-in-refs, the header uid, `index=` on instance children; `--elide-defaults` also removes assignments equal to the script's `@export` default; `--respell` re-spells floats in the saver's shortest form and wraps a bare list on an `Array[T]` export as `Array[T]([...])`; `--order` puts a scripted section's properties in declaration order — line edits only, anything unprovable named and left alone | <!-- doc-scan:allow -->
| `refs --retarget <old-res-path> <new-res-path> [--dry-run]` | after a `git mv`: rewrite every `ext_resource` path and exact `preload`/`load` literal naming the old path; anything unprovable is SKIPPED with a reason, and skips exit 1 |
| `tiles paint <file> --layer NAME --region X0,Y0,X1,Y1 --tile SRC/AX,AY[/ALT]` · `tiles erase …` | fill or clear a rectangle of one `TileMapLayer`; only that property's base64 is regenerated |

**The installer:** `install-runners [--force] [--diff]` — see [below](#what-install-runners-writes).

**The gates:** `check <gate>` for one, `check all` for the eight, `check <gate> --help` for that
gate's contract, config and scope. `check uid --fix` applies the repairs the gate already computes.

## The eight gates

Every gate prints a **census** of what it scanned, then a verdict — on the FAIL line as much as the
PASS line. Read the census first: a gate that scanned fewer files than you expected is telling you
your config is wrong, not that your tree is clean. A zero-file census FAILS rather than passing, a
file that could not be decoded is reported and dropped from the count, and nothing is a finding
unless the whole picture resolved — anything unresolvable is censused `UNVERIFIED`, never failed.

| gate | scans | fails on | config |
|---|---|---|---|
| `uid` | tracked `.tscn`/`.tres` Script refs against `.gd.uid` sidecars; new `.gd` (untracked or staged); tracked sidecars | a stale ref uid, a script with no sidecar, an orphan sidecar, a non-canonical uid spelling — `--fix` repairs what has a should-be value | `[uid] exclude_prefixes` |
| `tres` | tracked `.tscn`/`.tres` `ext_resource` lines | a path-only ref (no `uid=`), which Godot 4.4+ rewrites silently on the next editor pass | `[tres] exclude_prefixes`, `baseline` |
| `props` | every property assignment in tracked scenes, against the script's `@export`s and Godot's ClassDB | an assignment to a property that does not exist (a renamed export, a mistyped built-in) | `[props] exclude_prefixes`, `extra_properties`, `baseline` |
| `defaults` | tracked `.tres` assignments against the script's declared `@export` defaults | an assignment equal to its default — the churn Godot's writer omits and a hand-authored file spells out | `[defaults] exclude_prefixes`, `baseline` |
| `rng` | `.gd` under the configured roots | a bare `randi()`/`randf()`/`randi_range()`/`randf_range()` or any `randomize()` — a draw a seeded run does not own | `[rng] roots`, `allowlist`, `baseline` |
| `tres-comment` | tracked `.tscn`/`.tres` | a line opening with `;` — a comment Godot's serializer drops on the next save | `[tres_comment] exclude_prefixes`, `baseline` |
| `unit-disk` | `.gd` under the unit-test roots | a `user://` literal, a forbidden call, or a save/settings call given fewer arguments than its real-root default needs | `[unit_disk] roots`, `forbidden_literals`, `forbidden_calls`, `min_args`, `baseline` |
| `canonical` (opt-in) | tracked `.tres` values and property order against what Godot's saver writes, where a parse can prove it | a float the saver spells shorter (`0.30` -> `0.3`), a bare list on an `Array[T]` export, a scripted section out of declaration order — the churn an editor save of a hand-authored resource makes | `[canonical] exclude_prefixes`; not in the stock `check all` — name it in `[checks] godot` |
| `test-shape` | the integration tier | a new scenario over the line cap, a ledgered one that grew, and — with `header = true` — a scenario with no `## covers:`/`## Boots because:` header (a ledgered one is held until it carries both), asked of the roster `make integration-list` boots | `[test_shape] scenario_root`, `cap`, `infra`, `ledger`, `header`, `header_ledger`, `runner` |

**Exit codes are contract:** `0` pass · `1` findings · `2` usage or config error. A `devkit.toml`
mistake is always `2`, so CI can never read a typo as drift, and a key this package does not honour
is named at exit 2, never ignored.

**Adopting the gates on an existing tree**, in order, because some start red by design: `check uid`
(commit sidecars with their scripts; `--fix` clears stale refs, spellings and orphans) →
migrate to uid-in-refs, then `check tres` → `check props` (findings are real renamed-export bugs) →
`scene canonicalize --elide-defaults`, then `check defaults` → `scene canonicalize --respell --order`,
then `check canonical` (add it to `[checks] godot`) → wire `check all`. Steps two and four
are also the cure for `.tscn`/`.tres` churn — files you did not edit turning up in every commit.

**Adopting a gate frozen.** Six gates — `tres`, `props`, `defaults`, `rng`, `tres-comment`,
`unit-disk` — take a `baseline` in their own section: one entry per file, at the number of findings
it carries today. Those findings are held, and every run prints `  BASELINED  N finding(s) in M
file(s) frozen by [<section>] baseline` so the debt stays visible. A file whose findings grow past
its entry fails with every one of them listed; a file that now carries fewer fails until its entry
is lowered (`SHRUNK`) or dropped (`STALE`) — the baseline only shrinks. It is per file on purpose:
a single total would let a fix in one file pay for new drift in another. `test-shape` has the same
ratchet as its `ledger`, measured in lines.

**Migrating to uid-in-refs:** for a target whose header has no uid at all, mint one with Godot's own
`ResourceUID.create_id()` in a headless pass (never hand-author a uid string — an invalid uid
poisons the cache); inject each target's uid into the referencing `ext_resource` lines; prove it
cold — delete `.godot/`, run a headless `--import`, confirm zero `invalid UID` warnings.

## Configuration — `devkit.toml`

Optional, at the repo root. Every tool works with stock defaults; a section overrides only what it
names, and a repo with no `devkit.toml` behaves byte-identically to one declaring the defaults.
`check <gate> --help` prints each gate's section in full.

```toml
[checks]
godot = ["uid", "tres", "props"]   # narrows `check all` for THIS repo (stock: all eight);
                                   # an unknown name exits 2. `[checks] all` is agentic-sdlc's
                                   # roster in the same file — two kits, two keys.
[gates]
extra = ["godot-check"]            # joins `check all` to `make check`

[uid]
exclude_prefixes = ["addons/"]     # scopes every uid check
[tres]
exclude_prefixes = ["addons/"]
baseline = { "scenes/legacy/hub.tscn" = 7 }   # existing debt, per file at its CURRENT finding
                                   # count; held and counted every run, and only shrinks
[props]
exclude_prefixes = ["addons/"]
baseline = { "scenes/legacy/hub.tscn" = 2 }
extra_properties = { MyWidget = ["virtual_prop"] }   # a `_get_property_list` shape the scanner
                                   # cannot see; the key is the class_name (or an ancestor's) or
                                   # the engine type, and the carve-out applies only to it
[defaults]
exclude_prefixes = ["addons/"]
baseline = { "data/enemies/grunt.tres" = 3 }
[canonical]                         # opt-in: name it in [checks] godot to run it in `check all`
exclude_prefixes = ["addons/"]
[rng]
roots = ["systems/run/"]           # stock ".": keep it NARROW — the roots that hold run-scoped randomness
allowlist = { "systems/run/dice.gd:roll" = "a cosmetic jitter; the reason is required" }
baseline = { "systems/run/loot_roll.gd" = 4 }
[tres_comment]
exclude_prefixes = ["addons/"]
baseline = { "data/legacy/tuning.tres" = 12 }
[unit_disk]
roots = ["tests/unit"]
forbidden_literals = { "a real save path" = ["user://saves/", "user://settings\\.json"] }
                                   # a TABLE, reason = [regexes], like forbidden_calls — not a
                                   # list; stock { "a real user:// path" = ["user://"] }
forbidden_calls = { "the live settings autoload" = ["SettingsManager\\.(save|load)_settings\\("] }
min_args = { "SaveService.save" = 2 }
baseline = { "tests/unit/test_save_roundtrip.gd" = 3 }
[test_shape]
scenario_root = "tests/integration"
unit_root = "tests/unit"           # the other side of the tier-balance line
cap = 300                          # lines; a NEW scenario over it fails
infra = ["scenario_base.gd"]       # basenames of the tier's shared harness, not priced as scenarios
ledger = { "tests/integration/big_flow.gd" = 812 }   # existing debt at its CURRENT size; only shrinks
header = true                      # every booted scenario declares `## covers:` and `## Boots because:`
header_ledger = ["tests/integration/big_flow.gd"]    # scenarios exempt until they carry both lines; only shrinks
runner = "tools/dev/runners/integration.sh"

[autoloads]
suffixes = { Manager = "emits", Registry = "inert" }
expected_prefixes = ["autoloads/core/", "autoloads/presentation/"]
[refs]
exclude_prefixes = [".git/", ".godot/", "addons/"]
[orphans]
vendored_prefixes = ["addons/"]
entry_point_prefixes = ["tools/"]
auto_discovered_prefixes = ["tests/", "data/"]
convention_files = ["default_bus_layout.tres"]
```

## Parallel engine work

The runners share an OS-owned, nonblocking admission lease under the account home.
Integration owns it across cache repair and worker fanout. Standalone engine boots also require admission.
A competing gate exits promptly with its owner's PID and check. Read-only verbs remain available.
The lock remains held while any admitted descendant runs, including after a parent dies.
`GDK_ENGINE_GATE_HOME` explicitly selects an isolated admission domain for stub test fixtures.
Production callers must share one domain across checkouts.

Import copying prunes registered nested worktrees and explicit Godot-ignored directories before descent.
It preserves runtime addons, ordinary Git-cloned addons, and the exact manifest through rsync or the clone-aware fallback.

## What `install-runners` writes

Each file once; after that it is the repo's. A differing destination is refused by name (`--force`
overwrites it), `--diff` prints what would change and writes nothing, and the run ends by printing
the `.claude/settings.json` entry that fires the engine-boot guard, after the `pyproject.toml` block
that locks the kit. It runs `uv run --frozen godot-devkit` when `uv.lock` names the kit, or the
legacy `GODOT_DEVKIT_VERSION` from the Makefile above the include, which wins with a warning when
both are present.

```
Makefile.tiers                          the Godot tier roster on the seam Makefile.devkit -includes:
                                        parse lint spot warnings unit integration integration-all
                                        integration-diff integration-list scenario smoke capture
                                        import-cache godot-check uid-scan hermetic-scan
                                        runners-self-test, with
                                        GDK_PRECOMMIT_TIERS / GDK_MILESTONE_TIERS
tools/dev/gdk_runners.sh                the sandboxed headless-run library every runner sources
tools/dev/runners/parse.sh              every .gd compiles + the headless boot is clean
tools/dev/runners/compile_sweep.gd      stage 2 of parse.sh (+ its .uid sidecar)
tools/dev/runners/lint.sh               gdlint over every tracked source dir
tools/dev/runners/spot.sh               gdlint + a compile of only the .gd changed vs BASE
tools/dev/runners/warnings.sh           the analyzer warnings only the editor shows
tools/dev/runners/unit.sh               the GUT tier, no boot; a census that must reconcile
tools/dev/runners/integration.sh        the scenario fan-out: --all, --diff <ref>, --system <dir>, --list;
                                        warm (one boot per worker) under GDK_INTEGRATION_WARM=1
tools/dev/runners/scenario.sh           one scenario, cold, with the cache-recovery ladder; --suite <name>...
                                        is the warm worker: one boot, several scenarios
tools/dev/runners/capture.sh            a headed visual capture to PNG (local, needs a display); the window
                                        is placed off screen unless CAPTURE_VISIBLE=1 (a desktop may clamp it to the edge), and the last PNG of a
                                        name moves to previous/ for a before/after
tools/dev/runners/import_cache.sh       rebuild the .godot import cache, sandboxed, in a scratch copy:
                                        .godot/ comes back by rename, new .uid/.import sidecars
                                        are copied back, other rewrites are dropped and counted
tools/dev/runners/hermetic_run_scan.sh  a headless run's sandbox HOME self-destructs
tools/hooks/cc-godot-sandbox.sh         the Claude Code PreToolUse guard: no raw engine boot
.github/actions/godot-toolchain/action.yml
                                        the CI toolchain: engine, gdlint, shellcheck, import
```

**CI.** The workflow is agentic-sdlc's `install-ci`; its toolchain slot is empty. Fill it with one
step, after `setup-uv` (the run prints it as a `next:` line):

```yaml
      - uses: ./.github/actions/godot-toolchain
        with: { godot-patch: "<n>" }
```

The action reads the engine's MAJOR.MINOR from `project.godot` `config/features` and adds
`godot-patch`; it installs gdlint (`gdtoolkit-version`, default `4.5.0`) and shellcheck
(`shellcheck-version`, default `0.11.0`, from the release tarball), then imports the project and
fails when `.godot/global_script_class_cache.cfg` is absent. `install-runners` no longer writes
`.github/workflows/uid-guard.yml`. An existing copy stays, and the run names it as retired. It is
safe to delete only when `[gates] extra` names `godot-check` and `[checks] godot` keeps `uid`: then `check uid` runs in `make check`,
and so in `make milestone`. `uid-scan` is not a milestone tier, so without `godot-check` the run
says `check uid` is not in the repo's gate and tells you to keep the file.

**The diff slice.** `integration.sh --diff <ref>` (`make integration-diff`) boots the scenarios
whose `## covers:` header names a touched path, plus smoke. A touched file under
`GDK_SCENARIO_FIXTURE_DIR` (default `tests/support/`) selects every scenario whose text names it,
followed through other fixtures. A fixture is named by its `res://` path in any quote or none, by
its own `uid://`, or by a `class_name` it declares, so no call form can drop a scenario out of the
slice. Each fixture prints how many scenarios it selected. A touched fixture that no scenario names
boots the whole tier with the line `fixture <path> is referenced by no scenario — booting the
tier`. A fixture root that is not a directory under the repo exits 2. With the root set elsewhere,
a touch under `tests/support/` (1.3.0's ground) still boots the tier. Only the runners and the scenario base/runner scripts are the tier's
ground (`GDK_SCENARIO_SUBSTRATE_RE`; a value you set is kept). After the sweep, `--diff` reruns each
failed scenario once, alone. One that passes alone counts green and prints `  FLAKE  <name> —
failed in the sweep, passed alone`, and the summary reads `N passed (K flaky)`. `--no-rerun` or
`GDK_INTEGRATION_RERUN=0` turns the rerun off; `--all` and named runs never rerun. Before a
`--diff`/`--all` sweep boots anything, a stale import cache (`.godot/uid_cache.bin` missing, or
older than a tracked `*.uid`, `*.import` or `project.godot`) is repaired once by `import_cache.sh`.
If the repair fails, the sweep does not start (exit 1).

**Warm mode (opt-in).** Every scenario is one cold engine boot, 13-15 s of CPU before its first
assertion. With `GDK_INTEGRATION_WARM=1`, `integration.sh --all|--diff|--system` splits the roster
(after `--diff` slicing) into `GDK_JOBS` slices, balanced by count, and runs each through ONE
`scenario.sh --suite a b c`, so the engine boots once per worker. Unset (the default), every path is
the cold one, byte for byte; `--cold` forces it for one run, and a value other than 0 or 1 exits 2.
Turn it on only once your scenario runner implements the contract:

1. Booted with `-- <GDK_SCENARIO_SUITE_ARG> a,b,c` (default `--scenarios`, comma-separated), print
   `[SCENARIO] <name> START` before each scenario: a line matching `<GDK_SCENARIO_START_RE> <name>
   START`, where the ERE defaults to `\[SCENARIO\]` like `GDK_SCENARIO_RESULT_RE`.
2. Run it against a fresh World, with the reset your `scenario_base` owns (autoload state, World,
   player).
3. Finish the scenario's teardown, THEN print your usual verdict line: `GDK_SCENARIO_RESULT_RE`,
   then `PASS` or `FAIL` as a word. The verdict closes the scenario; nothing it causes may follow.
4. Exit 0 after the last one. A FAIL is carried by its verdict line, never by the exit code.

The single-scenario `--scenario <name>` path is unchanged. The worker splits the stream at the START
markers. A scenario's slice runs from its START to the next one, with the boot preamble in front,
and is published to `.scenario-reports/<name>.log`. An engine error in the slice upgrades that
scenario's PASS to FAIL, exactly as a cold run would, and each scenario gets one console line, as
today. A worker is killed when no new START or verdict arrives within `GDK_SCENARIO_HARD_TIMEOUT`
seconds (a per-scenario bound). A hang hands back the scenario in progress and every one that never
started, unrun: `  WARM-ABORT  after <last finished> — N scenario(s) handed back`, and
`scenario.sh --suite` exits 4. Two findings belong to no scenario, so they hand back EVERY member,
even ones with a verdict, and the WARM-ABORT line names the reason after a colon. The first is an
engine exit that is non-zero and not the hang kill (`: the engine exited 139`), even after the last
verdict. The second is an engine error after a verdict and before the next START or the exit
(`: engine errors after the last verdict`), which is where exit-time leak warnings land. A passing
slice that carries the cold-import-cache warning is handed back too, so the cold path's recovery
ladder gets it. Every handed-back scenario then runs cold.

A scenario whose header carries `## Isolated because: <reason>` never runs warm. An empty reason
exits 2 and names the file. With `--diff`, a warm failure is rerun cold and alone. One that passes
prints `  WARM-ONLY  <name> — failed warm, passed cold: it leans on process state; mark it "##
Isolated because:" or fix its reset`, and counts green. `--no-rerun` leaves it red. The summary
reads `N passed (K flaky, W warm-only), F failed (of T); warm A, cold B, handed back C`. A, B and C
must sum to the roster, and every scenario must have a result. Otherwise the run FAILS and names
what is missing. `[INTEGRATION] WALL: warm workers Xs, cold remainder Ys` splits the wall clock,
and `BOOTS` counts one boot per worker. Compare before and after in your own ledger.

Every runner carries `--help` and a `--self-test` corpus; `make runners-self-test` replays them all.
The guard's corpus (`bash tools/hooks/cc-godot-sandbox.sh --self-test`) is replayed by this kit's
own tests, so do not add it to `[gates] extra`. Every gate prints ONE verdict line naming its full
transcript under `.gate-reports/`; `VERBOSE=1` streams the whole thing.

**The spot check.** `make spot SYS=<slice>` is a builder's whole proof. `spot.sh` runs gdlint and
`compile_sweep.gd` over the `.gd` files that differ from the merge base of `HEAD` and `BASE`
(`GDK_SPOT_BASE`, default `main`): committed, staged and unstaged edits, and untracked files. The
sweep takes the list as user arguments (`-- res://a.gd …`) and walks nothing else. When no `.gd`
changed, the verdict is `[SPOT] PASS — census 0: no .gd changed vs merge-base <sha> with <base>`.
Then `unit.sh $(SYS)` runs, and the exit is the worse of the two. `GDK_PRECOMMIT_TIERS` is `spot`,
so `make precommit` runs `check` + `spot` and its first line says it is retired.

**Receipts.** A tier that passes files a receipt keyed on its inputs, and a run over the same inputs
prints the recorded verdict with `; reused — receipt <id>` and boots nothing. `parse`, `lint`,
`spot`, `unit`, `warnings` (keyed on `GDK_WARNING_CATEGORIES` too), `integration` and a direct
`scenario` file them. The integration key holds the arguments, the roster env, the tree of the
`--diff` ref, and the roster files with every `## covers:` path, and it is asked before the engine
lease. A `scenario` run inside a sweep, under `--suite` or with `-v` files none. A path a runner
names in `GDK_RECEIPT_PATHS` joins the key even inside a `GDK_RECEIPT_EXCLUDE` directory. A reused
run files no cost row: the `gdk_gate`-wrapped targets export `GDK_GATE_UNMEASURED`, and a hit
creates that file. `GDK_RECEIPTS=0` runs every tier.

**Several lanes on one machine.** `unit.sh` bounds its run at 180 s times `ceil(1-minute load /
cpus)`, clamped to 1-3, and opens with the bound it chose and why (`[UNIT] timeout 360s (load
1.4x)`); an explicit `GDK_UNIT_TIMEOUT` is used as given, and a `HARD_TIMEOUT` names the value to
rerun with. Sourcing `gdk_runners.sh` exports `GIT_OPTIONAL_LOCKS=0`, so a gate killed mid-`git
status` leaves no `.git/index.lock`. A pid counts as dead only on positive evidence (`kill -0`
says `No such process`, or a visible process table lacks it), so the HOME reaper never deletes a
peer's live run. Where a sandbox hides pid 1 from `ps`, the library's self-test prints `SKIP — …`
for its two foreign-pid cases instead of failing them.

**What a tier costs.** Every tier files a cost row in agentic-sdlc's ledger, so `pm ledger report` shows
what each one costs: `parse`, `lint`, `warnings` and `unit` file theirs from inside the runner
(`unit` with its GUT test count as the census), and the scenario tiers carry a census of **boots**.
A scenario file is one cold engine boot whatever its length, so the scenario tier's cost is its
file count: merging two scenarios saves a boot, trimming lines saves nothing. The boots
census on `integration-all` / `integration-diff` rows is that cost; `check test-shape`'s line cap
is a readability gate, not a cost one.

## Development

`make help` lists every target; never hand-roll an incantation. `make check` is the static gate,
`make pyunit` the inner loop (the suite minus the spawns, seconds), `make test` the whole suite on
the floor interpreter, `make milestone` the full gate and what CI runs (`check` + `matrix`, every
claimed interpreter). Verify against source — `PYTHONPATH=src python3 -m godot_devkit.cli …` —
never through `uvx --from <path>`, which caches a wheel by version.

Nothing here reads a path outside its own checkout or names a project that consumes it. Realistic
data is vendored: `tests/fixtures/` holds purpose-built repos, a committed clean Godot project the
gates run over, and a scrubbed real-world scene corpus every write verb round-trips byte for byte.

`check props` compares against a snapshot of Godot's ClassDB in `src/godot_devkit/data/classdb.json`;
reading it boots nothing. Regenerate when the engine minor moves:

```sh
godot --headless --dump-extension-api      # writes ./extension_api.json
python3 tools/gen_classdb.py extension_api.json
```

## Requirements

Python 3.11+ (stdlib only) and git. Godot 4.4+ text-resource format for the uid/tres gates; the
parser handles any Godot 4.x `.tscn`/`.tres`.

## License

MIT — see [LICENSE](LICENSE).
