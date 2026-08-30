# CLAUDE.md — godot-devkit

Two families, consumed as a **pinned-tag Python package** by shipping game repos: **scene tooling**
for Godot 4.x (introspection, surgery, the `.tscn`/`.tres` gates) and **repo discipline** that has
nothing to do with Godot (`check doc`, `check shell`, `check repo-hygiene`, `check agents`, and
`pm` — a markdown-and-frontmatter project tracker).

Consumed by *The Appalachian Trail* (`~/workspace/trail`) and *nullbound* (`~/workspace/nullbound`),
which pin `DEVKIT_VERSION` in their Makefile and route gates through `uvx`. Public repo, MIT. **Every
change here lands in other projects' commit gates — treat the CLI as a published API.**

**The goal, the northstar, and the reasoning behind the rules below live in [`README.md`](README.md).** Read it once before your first change here; this file is the enforceable form, not a second copy of it. One line worth carrying in your head: *any change you can make to a scene by hand should be makeable through one deterministic command that touches nothing else — and provable without reading the file.* Two audiences, humans and LLMs; for the latter the deliverables are a stable verb vocabulary, determinism, and token reduction.

## Hard rules

1. **Stdlib only, forever.** No runtime dependencies. Python 3.11+ (`tomllib`). A consumer's pre-push hook must never break because of a transitive dep.
2. **Pure parse — never boots Godot.** No tool starts the engine, runs an import, or depends on `.godot/` cache state. Safe anywhere, anytime, in parallel. *(This rule used to read "pure parse, read-only". The write verbs — `scene set/rename/add/rm/reparent`, `scene canonicalize` — broadened the scope; they did not weaken the invariant, because the invariant was never read-only. A `.tscn` is text.)* The `repo/` family does not touch a scene at all: it is here because this is the pinned-tag channel its consumers already share, not because PM tracking is Godot tooling. **If that stops being true, it leaves** — and the layout is what keeps that a real option rather than a sentiment.
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

- **New check** = module in the right family's `checks/` + branch in `_run_check` +
  README table row + CHANGELOG line.
- **New read verb** = module + `cli.py` route + README table row + CHANGELOG line.
- **New WRITE verb** = all of the above, **plus** a round-trip fidelity case in the
  corpus, an explicit refusal path with a test proving it declines rather than
  mangles, and an idempotence test. Address nodes by PATH (`parent` + `name`) —
  Godot addresses them that way; format-4 `unique_id` is not the addressing key.
  Read output must be valid write input.
- **Every config value goes through `src/godot_devkit/core/config.py`.** Never `tuple(cfg.get(...))` —
  a bare string is iterable, and that is how seven gates shipped a silent PASS over an
  empty census in v0.9.0.

## How we work

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

- Behavior gate: `make smoke` — every READ subcommand against the live consumer
  checkouts, censuses compared against independent counts. The consumers ARE the read
  fixtures. Read-only, and it fails if it leaves either checkout dirty.
- Differential + replay harnesses: `make fuzz`. Seeded, so a divergence reproduces
  exactly rather than being re-derived; `make test` runs them too.
- **Write verbs NEVER run against a live consumer checkout.** Copy the file (or the tree) to scratch first. A smoke run that mutates `~/workspace/nullbound` or `~/workspace/trail` is a broken smoke run, not a thorough one — the consumers are shipping game repos with their own dirty-tree gates.
- Round-trip fidelity is proven on COPIES of real consumer scenes, kept as a corpus. Parse → serialise with no mutation, byte-compared. This is the test that makes every write verb safe; it is not optional and it is not a smoke check.
- A gate-semantics change additionally needs a deliberately-broken probe: introduce the drift class in a scratch copy of a consumer and confirm the gate FAILS (rule 4). Prove the **config** path too: a bad value for that gate's section must exit 2, and a zero-file census must FAIL rather than pass.
- **Never verify through `uvx --from <path>`.** uv caches the built wheel by version, so an unchanged
  version number serves stale code and a fixed bug still reproduces. Run `PYTHONPATH=src python3 -m
  godot_devkit.cli …`, or `uv cache clean godot-devkit` first.

## Self-hosting

This package runs its own tooling on its own tree, and that is a gate, not a demo.

- `pm/roadmap/` is a real PM tree scaffolded by `pm new`, and `devkit.toml` turns on **every** rule this package ships except D8 (which encodes bump-at-START; we bump at close). Both `godot-devkit check all` and `godot-devkit check pm` must exit 0 here.
- CI is `.github/workflows/verify.yml`, whose one job runs `make milestone` — the same target the local full gate is, so the two cannot drift.
- The review + build contract under `.claude/agents/verification-*.md` is an ordinary committed file, and this repo's own `check doc` + `check agents` run over it — a contract that reddens the gates it sits beside gets deleted by the first person who runs them.
- **`CHANGELOG.md` is hand-maintained**, like every other project's. A consumer-visible change goes into its `## Unreleased` section as a bullet as the work lands, and the release skill retitles that section to the tag. Rationale with a rejected alternative is a decision — `pm decide` opens the heading — not a release note.
- If a rule fails when pointed at this repo, the finding gets fixed. Turning the rule off is only right when the rule encodes a flow this package does not run, and that goes in `decisions.md` with what was rejected.

## Releases

Use the `/release` skill — it owns the bump/tag/push sequence and the consumer-pin reminder. Never tag by hand; never let `__init__.py` and `pyproject.toml` versions diverge.

## Provenance

Extracted 2026-07-04 from trail/nullbound (their `docs/specs/cherry-picks/` receipts record the lineage). The `refs` tool has a known blind spot: autoload NAMES (declared in `project.godot`, not via `class_name`) aren't indexed — fix upstream here, not in consumers.
