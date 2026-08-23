# CLAUDE.md — godot-devkit

Headless dev tooling for Godot 4.x, consumed as a **pinned-tag Python package** by shipping game repos (currently *The Appalachian Trail* at `~/workspace/trail` and *nullbound* at `~/workspace/nullbound` — both pin `DEVKIT_VERSION` in their Makefile and route gates through `uvx`). Public repo, MIT. Every change here lands in other projects' commit gates — treat the CLI as a published API.

**The goal, the northstar, and the reasoning behind the rules below live in [`README.md`](README.md).** Read it once before your first change here; this file is the enforceable form, not a second copy of it. One line worth carrying in your head: *any change you can make to a scene by hand should be makeable through one deterministic command that touches nothing else — and provable without reading the file.* Two audiences, humans and LLMs; for the latter the deliverables are a stable verb vocabulary, determinism, and token reduction.

## Hard rules

1. **Stdlib only, forever.** No runtime dependencies. Python 3.11+ (`tomllib`). A consumer's pre-push hook must never break because of a transitive dep.
2. **Pure parse — never boots Godot.** No tool starts the engine, runs an import, or depends on `.godot/` cache state. Safe anywhere, anytime, in parallel. *(This rule used to read "pure parse, read-only". The write verbs — `scene set/rename/add/rm/reparent`, `scene canonicalize` — broadened the scope; they did not weaken the invariant, because the invariant was never read-only. A `.tscn` is text.)*
3. **A write verb touches only what it was asked to touch.** Parse → serialise with no mutation is **byte-identical**, proven against a corpus of real consumer scenes. A verb that cannot guarantee a correct result **refuses and says why** — it never edits partially and never reformats adjacent lines. Writes are idempotent: the same command twice is a no-op the second time.
4. **Two cardinal sins, one shape.** Read side: a gate that misses real drift and prints PASS. Write side: a diff that looks legitimate and is not. Both are worse than a crash because both destroy the signal a consumer relies on. When scoping/globbing/excluding, prove the file census matches intent (count what you scanned; a gate scanning 0 files must say so, loudly). Loud failure is a feature — an LLM can recover from an error and cannot recover from a lie.
5. **Config over forks.** Per-project variation goes in the consumer's `devkit.toml` section with a stock default — never "edit the tool". A repo with NO `devkit.toml` must behave byte-identically to one declaring the defaults.
6. **Exit codes are contract:** 0 pass, 1 findings, 2 usage error. Output line shapes (`  DRIFT  …`, `[check:x] PASS — …`) are grepped by consumers — changing them is a **minor** bump at least.
7. **Semver, enforced by habit:** patch = fix with identical interface; minor = new subcommand/flag/config key or output-format change; major = anything a consumer Makefile/hook must edit to survive. `__version__` in `src/godot_devkit/__init__.py` and `version` in `pyproject.toml` move together, always.

## Layout

```
src/godot_devkit/
  cli.py            # the ONE entry point; subcommand dispatch, no logic
  project.py        # repo_root() (git toplevel of cwd), load_config(), git_lines()
  tscn.py           # shared .tscn/.tres parser (sections, refs, tile_map_data decode)
  scene_summary.py  scene_diff.py  refs.py  orphans.py  autoloads.py
  checks/           # uid.py  tres.py  doc.py  repo_hygiene.py  shell.py
```

Tool modules own their behavior and expose `main(argv)` (introspection) or `run()` (checks); `cli.py` only routes.

- **New check** = module in `checks/` + branch in `_run_check` + README table row + CHANGELOG line.
- **New read verb** = module + `cli.py` route + README table row + CHANGELOG line.
- **New WRITE verb** = all of the above, **plus** a round-trip fidelity case in the corpus, an explicit refusal path with a test that proves it declines rather than mangles, and an idempotence test. Address nodes by PATH (`parent` + `name`) — Godot addresses them that way; format-4 `unique_id` is not the addressing key. Read output must be valid write input: the address `scene` prints is the address the write verbs accept.

## Verification loop

- Parse gate: `python3 -c "import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('src').rglob('*.py')]"`.
- Behavior gate: run `/consumer-smoke` (skill) — executes every READ subcommand against the live consumer checkouts and compares pass-counts/censuses against the repo's own independent census commands. The consumers ARE the read fixtures.
- **Write verbs NEVER run against a live consumer checkout.** Copy the file (or the tree) to scratch first. A smoke run that mutates `~/workspace/nullbound` or `~/workspace/trail` is a broken smoke run, not a thorough one — the consumers are shipping game repos with their own dirty-tree gates.
- Round-trip fidelity is proven on COPIES of real consumer scenes, kept as a corpus. Parse → serialise with no mutation, byte-compared. This is the test that makes every write verb safe; it is not optional and it is not a smoke check.
- A gate-semantics change additionally needs a deliberately-broken probe: introduce the drift class in a scratch copy of a consumer and confirm the gate FAILS (rule 4).

## Releases

Use the `/release` skill — it owns the bump/tag/push sequence and the consumer-pin reminder. Never tag by hand; never let `__init__.py` and `pyproject.toml` versions diverge.

## Provenance

Extracted 2026-07-04 from trail/nullbound (their `docs/specs/cherry-picks/` receipts record the lineage). The `refs` tool has a known blind spot: autoload NAMES (declared in `project.godot`, not via `class_name`) aren't indexed — fix upstream here, not in consumers.
