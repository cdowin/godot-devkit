# CLAUDE.md — godot-devkit

Two families, consumed as a **pinned-tag Python package** by shipping game repos: **scene tooling**
for Godot 4.x (introspection, surgery, the `.tscn`/`.tres` gates) and **repo discipline** that has
nothing to do with Godot (`check doc`, `check shell`, `check repo-hygiene`, and `pm` — a
markdown-and-frontmatter project tracker).

Consumed by *The Appalachian Trail* (`~/workspace/trail`) and *nullbound* (`~/workspace/nullbound`),
which pin `DEVKIT_VERSION` in their Makefile and route gates through `uvx`. Public repo, MIT. **Every
change here lands in other projects' commit gates — treat the CLI as a published API.**

**The goal, the northstar, and the reasoning behind the rules below live in [`README.md`](README.md).** Read it once before your first change here; this file is the enforceable form, not a second copy of it. One line worth carrying in your head: *any change you can make to a scene by hand should be makeable through one deterministic command that touches nothing else — and provable without reading the file.* Two audiences, humans and LLMs; for the latter the deliverables are a stable verb vocabulary, determinism, and token reduction.

## Hard rules

1. **Stdlib only, forever.** No runtime dependencies. Python 3.11+ (`tomllib`). A consumer's pre-push hook must never break because of a transitive dep.
2. **Pure parse — never boots Godot.** No tool starts the engine, runs an import, or depends on `.godot/` cache state. Safe anywhere, anytime, in parallel. A `.tscn` is text: the write verbs edit it without ever starting the engine. The `repo/` family does not touch a scene at all: it is here because this is the pinned-tag channel its consumers already share, not because PM tracking is Godot tooling. **If that stops being true, it leaves** — and the layout is what keeps that a real option rather than a sentiment.
3. **A write verb touches only what it was asked to touch.** Parse → serialise with no mutation is **byte-identical**, proven against a corpus of real consumer scenes. A verb that cannot guarantee a correct result **refuses and says why** — it never edits partially and never reformats adjacent lines. Writes are idempotent: the same command twice is a no-op the second time.
4. **Two cardinal sins, one shape.** Read side: a gate that misses real drift and prints PASS. Write side: a diff that looks legitimate and is not. Both are worse than a crash because both destroy the signal a consumer relies on. When scoping/globbing/excluding, prove the file census matches intent (count what you scanned; a gate scanning 0 files must say so, loudly). Loud failure is a feature — an LLM can recover from an error and cannot recover from a lie.
5. **Config over forks.** Per-project variation goes in the consumer's `devkit.toml` section with a stock default — never "edit the tool". A repo with NO `devkit.toml` must behave byte-identically to one declaring the defaults.
6. **Exit codes are contract:** 0 pass, 1 findings, 2 usage error. Output line shapes (`  DRIFT  …`, `[check:x] PASS — …`) are grepped by consumers — changing them is a **minor** bump at least.
7. **Semver, enforced by habit:** patch = fix with identical interface; minor = new subcommand/flag/config key or output-format change; major = anything a consumer Makefile/hook must edit to survive. `__version__` in `src/godot_devkit/__init__.py` and `version` in `pyproject.toml` move together, always.

## Where things live

Two families and a shared floor. The rule, not the inventory — `ls src/godot_devkit`
is the inventory, and it cannot go stale:

- **`core/`** — infrastructure that knows about neither family. `project.py` finds the
  repo and loads config; `config.py` decides what a config VALUE may be. Nothing here
  may import from `godot/` or `repo/`.
- **`godot/`** — everything that knows what a `.tscn` is, layered `format/` → `index/`
  → `read/`+`write/` → `checks/`. A layer may import downward, never up.
- **`repo/`** — repo discipline with no Godot in it: the `pm` tracker and the gates
  that read markdown, shell and git. **Nothing in `repo/` may import `godot/`.** That
  is what keeps rule 2's exit clause real rather than sentimental — check it before
  you add an import, because nothing else will.

A module that fits neither family is a signal worth raising, not a placement problem
to solve quietly. Tool modules own their behavior and expose `main(argv)` or `run()`;
`cli.py` only routes.

- **New check** = module in the right family's `checks/` + branch in `_dispatch_check` +
  README table row + CHANGELOG line.
- **New read verb** = module + `cli.py` route + README table row + CHANGELOG line.
- **New WRITE verb**: the dominant case is a new **scene subverb** — a row in
  `scene_edit.py`'s `VERBS` + `HANDLERS` tables plus `_build_parser`/`_check_usage`,
  no new module and no `cli.py` edit. A new TOP-LEVEL verb is module + `cli.py`
  route + README table row + CHANGELOG line. Either way, **plus** a round-trip fidelity case in the
  corpus, an explicit refusal path with a test proving it declines rather than
  mangles, and an idempotence test. Address nodes by PATH (`parent` + `name`) —
  Godot addresses them that way; format-4 `unique_id` is not the addressing key.
  Read output must be valid write input.
- **Every config value goes through `src/godot_devkit/core/config.py`.** Never `tuple(cfg.get(...))` —
  a bare string is iterable, and that is how seven gates shipped a silent PASS over an
  empty census in v0.9.0.

## How we work

- **The agent SDLC** — milestone branching, the dispatch loop, the model mix, and the roster `install-agents` ships — is [`SDLC.md`](SDLC.md), at the root because it is the operating contract, not auxiliary documentation.
- **The README carries the why; this file carries the enforceable form.** If a change
  makes you want to edit this file, ask first whether it changed *doctrine* or merely
  *contents*. Contents belong in the tree, in `--help`, or in the README. A CLAUDE.md
  that has to be edited whenever code moves is a manifest, and it will lie.
- **The consumers are the fixtures.** Two live repos pin this package. Their real trees
  are the test corpus for every read verb and every gate — which also means a
  regression here breaks two projects' commit gates before anyone notices here.
- **Verify against source, never a cached wheel.** `uvx --from <path>` caches by
  version, so an unchanged version number serves stale code and a fixed bug still
  reproduces. Use `PYTHONPATH=src python3 -m godot_devkit.cli …`.
- **A review is part of a release, not a courtesy.** Every minor bump in this package
  so far has had a pre-release review return NOT RELEASE-SAFE, and each time the
  blocker was a false PASS that would have shipped a permanently-green gate.

### Reporting to Chris

**Every decision he needs to make goes in a numbered `NEEDS YOU` list at the TOP**, so
he can answer "1 yes, 2 delete" without scrolling. Each item is a decision, not an
observation, and it carries the thing being decided **in the message** — a path, a
commit hash, or the content itself. Never "there are three open questions" — name them
A, B, C. When nothing needs him, say "nothing needs you" explicitly.

- **Gate output only when it FAILED, or when you ran it yourself** — one line
  ("157/157, my run"), never a pasted PASS block. A wall of green tells him nothing.
- **Numbers, not adjectives.** "228 files, census unchanged", not "verified thoroughly".
- **Say what you did NOT verify.** A claim with an unstated gap is worse than a gap.

## Verification loop

**Run `make precommit` after a change and `make milestone` before a release. Never
hand-roll an incantation.** `make help` lists every target. If the check you need is not
a target, **add the target**, then run it — apparatus that lives in one agent's context
is apparatus that gets rebuilt.

**`make milestone` runs the matrix, and the matrix proves PYTHON on every interpreter —
bash once.** `PY_FLOOR` runs the whole suite; the other interpreters in `PY_MATRIX` run
`-m "not shell"`. ~85% of this suite's wall clock is `subprocess` — bash, make, git, the
installed hook corpora — and a spawn is not something a Python version changes, so
replaying it four times bought minutes and no information. The `shell` mark is DERIVED
per module in `tests/conftest.py` from what the source does, never hand-applied (a
hand-written one is a collection refusal). A `PY_FLOOR` outside `PY_MATRIX` is refused
by name before the first interpreter starts: a matrix with no full pass would print PASS
over a suite nothing ran. `make test` is unaffected — it runs everything.

**Every gate prints ONE verdict line naming its full transcript under .gate-reports/;
`VERBOSE=1` streams the whole thing.** A new target routes through the shipped
`gdk_gate_capture` / `gdk_gate_verdict` (installables/gdk_runners.sh, sourced from
source — this package is its own first consumer) like the rest; never ask an agent to
grep a gate's output for its result. Enforced by `tests/test_makefile_gates.py`.

- Behavior gate: `make smoke` — `check all`, `autoloads`, `scene`, `refs`, `pm status`,
  `pm validate` and `check pm` against the live consumer checkouts, censuses compared
  against independent counts. The consumers ARE the read fixtures. Read-only, and it
  fails if it leaves either checkout dirty. A read verb it does NOT cover (`orphans`,
  `scene-diff`, `tiles`, `pm list`, `pm get`) is proven by the suite alone.
- Differential + replay harnesses: `make fuzz`. Seeded, so a divergence reproduces
  exactly rather than being re-derived; `make test` runs them too.
- **Write verbs NEVER run against a live consumer checkout.** Copy the file (or the tree) to scratch first. A smoke run that mutates `~/workspace/nullbound` or `~/workspace/trail` is a broken smoke run, not a thorough one — the consumers are shipping game repos with their own dirty-tree gates.
- Round-trip fidelity is proven on a committed corpus of scrubbed copies of real consumer scenes (`tests/fixtures/corpus/` — census-floored and construct-guarded, so it runs everywhere including CI) plus a sweep of every `.tscn`/`.tres` in whichever live consumer checkouts are present. Parse → serialise with no mutation, byte-compared; `load()`/`save()` proven on the same corpus. This is the test that makes every write verb safe; it is not optional and it is not a smoke check.
- A gate-semantics change additionally needs a deliberately-broken probe: introduce the drift class in a scratch copy of a consumer and confirm the gate FAILS (rule 4). Prove the **config** path too: a bad value for that gate's section must exit 2, and a zero-file census must FAIL rather than pass.
- **Never verify through `uvx --from <path>`.** uv caches the built wheel by version, so an unchanged
  version number serves stale code and a fixed bug still reproduces. Run `PYTHONPATH=src python3 -m
  godot_devkit.cli …`, or `uv cache clean godot-devkit` first.

## Self-hosting

This package runs its own tooling on its own tree, and that is a gate, not a demo.

- `pm/roadmap/` is a real PM tree scaffolded by `pm new`, and `devkit.toml` turns on **every** rule this package ships except D8 (which encodes bump-at-START; we bump at close). Both `godot-devkit check all` and `godot-devkit check pm` must exit 0 here.
- Work follows the milestone-branch flow — [`SDLC.md`](SDLC.md) §1 — the same as its consumers: `main` is merge-commit-only, at close. D9 + D10 in `[pm] checks` are what hold this tree to it.
- CI is `.github/workflows/verify.yml`, whose one job runs `make milestone` — the same target the local full gate is, so the two cannot drift. It is INSTALLED by `install-ci`, not hand-written: edit `src/godot_devkit/repo/installables/ci-verify.yml` and re-install with `--force`.
- The review + build contract under `.claude/agents/verification-*.md` is INSTALLED by `install-agents`, not hand-written — edit the source under `src/godot_devkit/repo/installables/` and re-install. A test asserts this repo's copies stay byte-current, and another asserts they pass `check doc` in a fresh consumer, because a contract that reddens the gates it arrives beside gets deleted by the first person who runs them.
- `install-hooks` IS self-hosted since 0.23.0: `tools/hooks/`, `tools/setup-hooks.sh`, `tools/dev/agent-worktree.sh` and `tools/dev/checks/doctor.sh` are the installer's output, and `.claude/settings.json` carries the entries it prints — the two ledger couriers `"async": true`, feeding `pm/roadmap/<building>/ledger.jsonl` through this Makefile's `pm` target. The `project config` headers are this repo's (static gate `make gates`, the hook self-tests standing in for a unit slice, base `main`); `make hooks-self-test` replays the three corpora and is in `precommit`. `bash tools/setup-hooks.sh` arms the git hooks — it writes `core.hooksPath`, which a worktree shares with the main checkout. The installables are still proven by installing them into a temp repo and RUNNING them against real hook payloads.
- **`CHANGELOG.md` is hand-maintained**, like every other project's. A consumer-visible change goes into its `## Unreleased` section as a bullet as the work lands, and the release skill retitles that section to the tag. Rationale with a rejected alternative is a decision — `pm decide` opens the heading — not a release note.
- If a rule fails when pointed at this repo, the finding gets fixed. Turning the rule off is only right when the rule encodes a flow this package does not run, and that goes in `decisions.md` with what was rejected.

## Releases

Use the `/release` skill — it owns the bump/tag/push sequence and the consumer-pin reminder. Never tag by hand; never let `__init__.py` and `pyproject.toml` versions diverge.

## Provenance

Extracted 2026-07-04 from trail/nullbound (their `docs/specs/cherry-picks/` receipts record the lineage). The `refs` tool has a known blind spot: autoload NAMES (declared in `project.godot`, not via `class_name`) aren't indexed — fix upstream here, not in consumers.
