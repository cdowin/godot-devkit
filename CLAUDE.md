# CLAUDE.md — godot-devkit

Headless dev tooling for Godot 4.x, consumed as a **pinned-tag Python package** by shipping game repos (currently *The Appalachian Trail* at `~/workspace/trail` and *nullbound* at `~/workspace/nullbound` — both pin `DEVKIT_VERSION` in their Makefile and route gates through `uvx`). Public repo, MIT. Every change here lands in other projects' commit gates — treat the CLI as a published API.

## Hard rules

1. **Stdlib only, forever.** No runtime dependencies. Python 3.11+ (`tomllib`). A consumer's pre-push hook must never break because of a transitive dep.
2. **Pure parse, read-only.** No tool boots Godot, writes into the consuming repo, or depends on `.godot/` cache state. The only writes ever performed are stdout/stderr.
3. **Config over forks.** Per-project variation goes in the consumer's `devkit.toml` section with a stock default — never "edit the tool". A repo with NO `devkit.toml` must behave byte-identically to one declaring the defaults.
4. **False PASS is the cardinal sin.** A gate that misses real drift and prints PASS is worse than a crash. When scoping/globbing/excluding, prove the file census matches intent (count what you scanned; a gate scanning 0 files must say so, loudly).
5. **Exit codes are contract:** 0 pass, 1 findings, 2 usage error. Output line shapes (`  DRIFT  …`, `[check:x] PASS — …`) are grepped by consumers — changing them is a **minor** bump at least.
6. **Semver, enforced by habit:** patch = fix with identical interface; minor = new subcommand/flag/config key or output-format change; major = anything a consumer Makefile/hook must edit to survive. `__version__` in `src/godot_devkit/__init__.py` and `version` in `pyproject.toml` move together, always.

## Layout

```
src/godot_devkit/
  cli.py            # the ONE entry point; subcommand dispatch, no logic
  project.py        # repo_root() (git toplevel of cwd), load_config(), git_lines()
  tscn.py           # shared .tscn/.tres parser (sections, refs, tile_map_data decode)
  scene_summary.py  scene_diff.py  refs.py  orphans.py  autoloads.py
  checks/           # uid.py  tres.py  doc.py  repo_hygiene.py  shell.py
```

Tool modules own their behavior and expose `main(argv)` (introspection) or `run()` (checks); `cli.py` only routes. New check = new module in `checks/` + a branch in `_run_check` + README table row + CHANGELOG line.

## Verification loop

- Parse gate: `python3 -c "import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('src').rglob('*.py')]"`.
- Behavior gate: run `/consumer-smoke` (skill) — executes every subcommand against the live consumer checkouts and compares pass-counts/censuses against the repo's own independent census commands. There is no mock fixture tree yet; the consumers ARE the fixtures.
- A gate-semantics change additionally needs a deliberately-broken probe: introduce the drift class in a scratch copy of a consumer and confirm the gate FAILS (rule 4).

## Releases

Use the `/release` skill — it owns the bump/tag/push sequence and the consumer-pin reminder. Never tag by hand; never let `__init__.py` and `pyproject.toml` versions diverge.

## Provenance

Extracted 2026-07-04 from trail/nullbound (their `docs/specs/cherry-picks/` receipts record the lineage). The `refs` tool has a known blind spot: autoload NAMES (declared in `project.godot`, not via `class_name`) aren't indexed — fix upstream here, not in consumers.
