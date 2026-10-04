# CLAUDE.md — godot-devkit

Scene tooling and the eight Godot gates for Godot 4.x, consumed as a **pinned-tag, stdlib-only
Python package** by shipping game repos. Two audiences, humans and LLMs; for the second the
deliverables are a stable verb vocabulary, determinism, and token reduction. The northstar in one
line: *any change you can make to a scene by hand should be makeable through one deterministic
command that touches nothing else — and provable without reading the file.* The why is
[`README.md`](README.md); this file is the enforceable form of it, not a second copy.

godot-devkit has Godot tooling and the gate framework games run (`Makefile.gates`, `Makefile.tiers`);
agentic-sdlc has agent guardrails; neither imports the other. Agent hooks, agents and the model guide
come from the agentic-sdlc plugin. Which repos consume this one is none of its business (rule 8).
Public repo, MIT. **Every change here lands in other projects' commit gates — treat the CLI as a
published API.**

Process: cdowin/signalandecho (README, skills work-intake and branch-plan).
Model guide: cdowin/agentic-sdlc (which agent, which model, when).

## Hard rules

1. **Stdlib only, forever.** Python 3.11+ (`tomllib`), no runtime dependencies — a consumer's
   pre-push hook must never break because of a transitive dep.
2. **Pure parse — never boots Godot.** No tool starts the engine, runs an import or depends on
   `.godot/` cache state; a `.tscn` is text and the write verbs edit it as text — which is what makes
   every verb safe anywhere, anytime, in parallel.
3. **A write verb touches only what it was asked to touch.** Parse → serialise with no mutation is
   byte-identical, proven on a corpus of real scenes; a verb that cannot guarantee a correct result
   refuses and says why, never edits partially, never reformats an adjacent line; the same command
   twice is a no-op the second time — because models retry, and damage hidden inside a
   legitimate-looking diff cannot be reviewed.
4. **Two cardinal sins, one shape.** Read side: a gate that misses real drift and prints PASS. Write
   side: a diff that looks legitimate and is not. Both are worse than a crash because both destroy
   the signal a consumer relies on — an LLM recovers from an error and cannot recover from a lie. So
   every scope, glob and exclude proves its census (count what you scanned), and a gate that scanned
   nothing FAILS, loudly.
5. **Config over forks.** Per-project variation lives in the consumer's `godot-devkit.toml` section with a
   stock default, never in an edit of the tool, and a repo with no `godot-devkit.toml` behaves
   byte-identically to one declaring the defaults — otherwise every consumer carries a fork to police.
6. **Exit codes are contract:** 0 pass, 1 findings, 2 usage or config error. Output line shapes
   (`  DRIFT  …`, `[check:x] PASS — …`) are grepped by consumers, so changing one is a minor bump at
   least.
7. **Semver, enforced by habit** (a version is a release tag made when it ships; a PR need not bump it): patch = fix with identical interface; minor = new verb, flag, config
   key or output shape; major = anything a consumer Makefile or hook must edit to survive.
   `__version__` in `src/godot_devkit/__init__.py` and `version` in `pyproject.toml` move together,
   always — two version sites that disagree ship two products.
8. **This package knows nothing about its consumers.** No file here names a consuming project, reads
   a path outside this checkout, or gates on another repo's state; realistic data is VENDORED under
   `tests/fixtures/`, and a consumer proves its own integration when it bumps its pin — a gate that
   somebody else's uncommitted work can redden is not a gate. Prose names a SHAPE ("a project whose
   `check` carries extra gates"), never a repo.
9. **Test what BITES, the cheapest way that can fail.** A test earns its place by gating something
   that would cost real time if it broke — a scene write verb, one of the eight gates, the runners
   installer, parse→serialise byte-identity, or one of rule 4's two sins; coverage is not the goal.
   Prove it ONCE: a function call before a temp tree, a temp tree before a process — a rule proven at
   two altitudes is one altitude of cost for no coverage. Before a new test, name the one that already
   covers it or can be amended; the default is that a new test is not warranted. A slower tier is a finding.

## Where things live

`ls src/godot_devkit` is the inventory; this is the rule.

- **`core/`** — the floor that knows nothing about Godot: `project.py` finds the repo and loads
  config, `config.py` decides what a config VALUE may be, `walk.py` is the ONE place the package
  enumerates a filesystem and `apply.py` the ONE place it mutates one. Nothing here imports `godot/`.
- **`godot/`** — everything that knows what a `.tscn` is, layered `format/` → `index/` →
  `read/`+`write/` → `checks/`, with the shipped files under `godot/installables/`. A layer imports
  downward, never up. Tool modules own their behaviour and expose `main(argv)` or `run()`; `cli.py`
  only routes.
- **New check** = module in `godot/checks/` + a branch in `_dispatch_check` + a README row + a
  CHANGELOG line, plus the probe below. **New read verb** = module + `cli.py` route + README row +
  CHANGELOG line. **New write verb** = usually a scene subverb — a row in `scene_edit.py`'s `VERBS` +
  `HANDLERS` plus `_build_parser`/`_check_usage`; a new top-level verb is module + route + row + line.
  Either way: a round-trip fidelity case in the corpus, a refusal path with a test proving it declines
  rather than mangles, and an idempotence test. Address nodes by PATH (`parent` + `name`), the way
  Godot does; read output must be valid write input.
- **Every config value goes through `src/godot_devkit/core/config.py`.** Never `tuple(cfg.get(...))` — a bare string
  is iterable, and that is how a silent PASS over an empty census ships.
- **Known gap:** `refs` does not index autoload NAMES (declared in `project.godot`, not via
  `class_name`) — fix upstream here, not in consumers.

## How this repo runs

`Makefile` sets `GDK_CHECKS := godot-check` and includes its own `Makefile.gates`; the Python tiers
live in `Makefile.tiers`, below the Godot roster `install-runners` writes. Never hand-roll an
incantation: `make help` lists every target, and a check that is not a target gets a target first.

| what | command |
|---|---|
| static gate | `make check`: shellcheck, then `godot-devkit check all` from `src/` over `tests/fixtures/godot_project/` (staged by `tools/dev/godot_devkit_on_fixture.sh`) |
| inner loop | `make pyunit`: the suite minus the spawns, seconds |
| per change | `make precommit`: `check` + `test` (the whole suite on the floor interpreter) |
| what CI runs | `make verify`: `check` + `matrix` (every claimed interpreter) |

- **Every gate prints ONE verdict line** naming its transcript under `.gate-reports/`; `VERBOSE=1` streams
  it. A new target routes through `$(call gdk_gate,…)`; never grep a gate's output for its result.
- **Self-hosting.** `Makefile.gates`, `tools/dev/gdk_gate.sh` and the head of `Makefile.tiers` are byte
  copies of the installables; `tests/test_makefile_gates.py` and `tests/test_runners_installable.py`
  hold them current. The runners are proven by installing them into a temp repo, never by this repo's copies.
- **The `shell` mark is derived** per module in `tests/conftest.py` from what the source does; a
  hand-written one is a collection refusal.
- **Verify against source, never a cached wheel:** `PYTHONPATH=src python3 -m godot_devkit.cli …`.
- **A write verb under test writes to scratch, never to a fixture in place.** Round-trip fidelity is
  proven on `tests/fixtures/corpus/`, byte-compared; a construct the corpus lacks gets a scrubbed
  scene VENDORED, which is how coverage grows.
- **A gate-semantics change needs a deliberately-broken probe:** introduce the drift class in a
  scratch copy of a fixture repo and confirm the gate FAILS; prove the config path too — a bad value
  for that section exits 2, and a zero-file census FAILS.
- **Do not boot Godot here** (rule 2). CI runs the same `make verify`.
- **`CHANGELOG.md` is hand-maintained.** A consumer-visible change lands as a bullet under
  `## Unreleased` with the work; the release retitles the section.
- **Release:** bump `version` in `pyproject.toml` and `__version__` together on `main`; `auto-tag.yml` tags it
  and `release.yml` publishes the wheel to the index. Never tag by hand.
- Report in ASD-STE100: numbered NEEDS YOU list first, outcome first, one fact per sentence, numbers not adjectives.
