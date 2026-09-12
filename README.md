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

A consumer sets two pins in its Makefile and includes one file. `agentic-sdlc` is the gate framework
and the SDLC (`check`, `precommit`, `milestone`, hooks, CI, the PM tree, the release belts); this
kit is the Godot tiers and gates.

```make
DEVKIT_VERSION       := v0.2.0      # agentic-sdlc — the framework and the SDLC
GODOT_DEVKIT_VERSION := v1.0.0     # this kit — the Godot tiers and the eight gates
include Makefile.devkit
```

`GODOT_DEVKIT_VERSION` goes ABOVE the include. Then write the two files the include reads, and join
the gates to `make check`:

```sh
uvx --from "git+https://github.com/cdowin/agentic-sdlc@v0.2.0" agentic-sdlc install-gates    # Makefile.devkit
uvx --from "git+https://github.com/cdowin/godot-devkit@v1.0.0" godot-devkit install-runners  # Makefile.tiers + runners
```

```toml
# devkit.toml
[gates]
extra = ["godot-check"]     # `godot-devkit check all`, the target install-runners wrote
```

`make check` now runs agentic-sdlc's gates and then the eight Godot gates; `make precommit` and
`make milestone` run the Godot tiers `Makefile.tiers` declares. Adopting a bump is a read of the
CHANGELOG and `install-runners --diff`, which prints what a re-install would change and writes
nothing. Every machine and CI runs the same gate code because the pin is a tag.

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
| `refs <symbol> [--tests]` | every reference to a symbol, grouped by kind |
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
| `scene canonicalize <file>... [--elide-defaults]` | restore what `PackedScene.pack()` drops — uid-in-refs, the header uid, `index=` on instance children; `--elide-defaults` also removes assignments equal to the script's `@export` default |
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
| `test-shape` | the integration tier | a new scenario over the line cap, a ledgered one that grew, and — with `header = true` — a scenario with no `## covers:`/`## Boots because:` header, asked of the roster `make integration-list` boots | `[test_shape] scenario_root`, `cap`, `infra`, `ledger`, `header`, `header_ledger`, `runner` |

**Exit codes are contract:** `0` pass · `1` findings · `2` usage or config error. A `devkit.toml`
mistake is always `2`, so CI can never read a typo as drift, and a key this package does not honour
is named at exit 2, never ignored.

**Adopting the gates on an existing tree**, in order, because some start red by design: `check uid`
(commit sidecars with their scripts; `--fix` clears stale refs, spellings and orphans) →
migrate to uid-in-refs, then `check tres` → `check props` (findings are real renamed-export bugs) →
`scene canonicalize --elide-defaults`, then `check defaults` → wire `check all`. Steps two and four
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
[rng]
roots = ["systems/run/"]           # stock ".": keep it NARROW — the roots that hold run-scoped randomness
allowlist = { "systems/run/dice.gd:roll" = "a cosmetic jitter; the reason is required" }
baseline = { "systems/run/loot_roll.gd" = 4 }
[tres_comment]
exclude_prefixes = ["addons/"]
baseline = { "data/legacy/tuning.tres" = 12 }
[unit_disk]
roots = ["tests/unit"]
forbidden_calls = { "the live settings autoload" = ["SettingsManager\\.(save|load)_settings\\("] }
min_args = { "SaveService.save" = 2 }
baseline = { "tests/unit/test_save_roundtrip.gd" = 3 }
[test_shape]
scenario_root = "tests/integration"
cap = 300                          # lines; a NEW scenario over it fails
ledger = { "tests/integration/big_flow.gd" = 812 }   # existing debt at its CURRENT size; only shrinks
header = true                      # every booted scenario declares `## covers:` and `## Boots because:`
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

## What `install-runners` writes

Each file once; after that it is the repo's. A differing destination is refused by name (`--force`
overwrites it), `--diff` prints what would change and writes nothing, and the run ends by printing
the `.claude/settings.json` entry that fires the engine-boot guard. It reads `GODOT_DEVKIT_VERSION`
from the Makefile above the include.

```
Makefile.tiers                          the Godot tier roster on the seam Makefile.devkit -includes:
                                        parse lint warnings unit integration integration-all
                                        integration-diff integration-list scenario smoke capture
                                        import-cache godot-check uid-scan hermetic-scan
                                        hooks-self-test runners-self-test, with
                                        GDK_PRECOMMIT_TIERS / GDK_MILESTONE_TIERS
tools/dev/gdk_runners.sh                the sandboxed headless-run library every runner sources
tools/dev/runners/parse.sh              every .gd compiles + the headless boot is clean
tools/dev/runners/compile_sweep.gd      stage 2 of parse.sh (+ its .uid sidecar)
tools/dev/runners/lint.sh               gdlint over every tracked source dir
tools/dev/runners/warnings.sh           the analyzer warnings only the editor shows
tools/dev/runners/unit.sh               the GUT tier, no boot; a census that must reconcile
tools/dev/runners/integration.sh        the scenario fan-out: --all, --diff <ref>, --system <dir>, --list
tools/dev/runners/scenario.sh           one scenario, cold, with the cache-recovery ladder
tools/dev/runners/capture.sh            a headed visual capture to PNG (local, needs a display)
tools/dev/runners/import_cache.sh       rebuild the .godot import cache, sandboxed
tools/dev/runners/hermetic_run_scan.sh  a headless run's sandbox HOME self-destructs
tools/hooks/cc-godot-sandbox.sh         the Claude Code PreToolUse guard: no raw engine boot
.github/workflows/uid-guard.yml         the uid-drift workflow
```

Every runner carries `--help` and a `--self-test` corpus; `make runners-self-test` replays them all
and `make hooks-self-test` replays the guard's. Every gate prints ONE verdict line naming its full
transcript under `.gate-reports/`; `VERBOSE=1` streams the whole thing.

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
