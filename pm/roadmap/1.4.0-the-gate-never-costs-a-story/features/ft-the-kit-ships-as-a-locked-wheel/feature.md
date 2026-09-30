---
id: ft-the-kit-ships-as-a-locked-wheel
kind: feature
milestone: "1.4.0"
name: the kit ships as a locked wheel
status: done
reviewed: docs/reviews/2026-09-29-1.4.0-the-kit-ships-as-a-locked-wheel.md
depends_on: []
consumed_by: []
changelog: The kit ships as a hash-locked wheel on a GitHub Pages index; Makefile.tiers runs uv run --frozen godot-devkit when uv.lock names it (#38).
---

# the kit ships as a locked wheel

Issues: #38.

Today a consumer runs `uvx --from "git+https://github.com/cdowin/godot-devkit@vX.Y.Z" godot-devkit`
from a `GODOT_DEVKIT_VERSION` pin. That has four costs:
- every machine and CI run builds the kit from source;
- nothing is hash-locked, so a moved tag changes the bits silently;
- dependency bots cannot see the pin;
- the PyPI name is taken, so the kit cannot publish there.

This feature ships the kit as a wheel built once per tag and publishes it to a PEP 503 index on this
repo's GitHub Pages. A consumer locks it with uv.

## Decided (do not re-plan)

- **Host (Chris, 2026-09-30):** GitHub Pages of THIS repo, public, no token. The index URL is
  `https://cdowin.github.io/godot-devkit/simple/`. Consumers declare it with `explicit = true`, so
  the name never resolves from PyPI.
- **`.github/workflows/release.yml`** (new, this repo's own file, not an installable). It triggers
  on `push: tags: ["v*"]` and on `workflow_dispatch` with a `tag` input. The input matters because
  the installed `auto-tag.yml` already dispatches `RELEASE_WORKFLOW: release.yml` with
  `-f tag=<tag>`, and a tag it pushes triggers no workflow. Steps:
  1. Check out the tag. Refuse (fail) when the tag's version does not equal `version` in
     `pyproject.toml` and `__version__` in `src/godot_devkit/__init__.py`.
  2. `uv build`, then `sha256sum`.
  3. Create the GitHub Release for the tag with the wheel and sdist as assets. **Refuse a re-tag:**
     if the release already carries a `.whl`, fail naming it and never overwrite.
  4. Regenerate the whole static index from ALL releases' assets (the GitHub API, via `gh`). This
     is deterministic, so one lost run is repaired by the next. The files are `simple/index.html`
     and `simple/godot-devkit/index.html` (PEP 503 normalised name), with links to the release asset
     URLs carrying `#sha256=<hex>`. Publish with `actions/upload-pages-artifact` +
     `actions/deploy-pages` (Pages source: GitHub Actions; the orchestrator enables Pages).
     Permissions: `contents: write`, `pages: write`, `id-token: write`.
  - The index generator is a small stdlib Python script under `tools/release/` (not in the package,
    not installed). It reads a JSON list of assets with their sha256 and writes the two HTML files.
    It has a unit test under `tests/` that runs it on a canned list: the output is byte-stable, the
    name is PEP 503 normalised, and every href carries its hash. Hashes come from the release step's
    own `sha256sum` for new assets, and from a download for older ones. Keep it simple: download
    every asset and hash it.
- **`Makefile.tiers` (installable) resolves the kit in this order:**
  1. `GODOT_DEVKIT` set by the caller: used as is, as today.
  2. `.venv/bin/godot-devkit` exists and `GODOT_DEVKIT_VERSION` is unset: use it (the locked shape).
  3. `GODOT_DEVKIT_VERSION` set and no venv binary: the legacy `uvx --from git+…` path, unchanged.
  4. BOTH present: `$(error)` naming both, and saying to delete the `GODOT_DEVKIT_VERSION` line
     (two pins of one tool ship two products).
  5. Neither: the existing error, extended to name the locked shape first.
  This repo's `Makefile.tiers` prefix stays byte-identical to the installable
  (`tests/test_runners_installable.py`). This repo itself keeps `GODOT_DEVKIT ?= bash
  tools/dev/godot_devkit_on_fixture.sh` (case 1).
- **Every other reader of `GODOT_DEVKIT_VERSION`** learns the locked shape: `godot/install.py`
  (`:155`, `:178`, the printed next-steps and the sandbox-guard text), and anything the
  installables print. `install-runners` prints the consumer's `pyproject.toml` block (the
  dependency-groups entry, the `[[tool.uv.index]]` block with `explicit = true`, and
  `[tool.uv.sources]`, exactly as in #38) as its recommended shape. The `uvx` pin stays documented
  as the legacy path, which still works. Minor bump: nothing a consumer must edit.
- **CI.** The installed `ci-godot-toolchain.yml` composite action gains an optional step: when the
  caller's `uv.lock` names `godot-devkit`, run `uv sync --frozen --only-group dev` (or the
  narrowest `uv sync` that installs the dev group). The index is public, so there is no token.
- **README:** a "Consume it locked" section (the pyproject block, `uv sync`, the upgrade path
  `uv add --dev godot-devkit==X.Y.Z` followed by agentic-sdlc's adopt belt, and a note that
  Renovate/Dependabot can see the pin). The install table names both shapes.
- Not in scope: agentic-sdlc's `adopt` or `make doctor` learning this shape. They are that kit's.
  Note it for the orchestrator to file there.

## Ship criterion

- `tests/` exercises the index generator on a canned list: byte-stable, hashes present, name
  normalised.
- `Makefile.tiers` resolution is proven in a temp tree with `make -n godot-check` (or `make -pn`)
  for the five cases, in the existing runners-installable test module.
- `release.yml` passes `actionlint` if it is installed; otherwise say so under NOT verified. The
  workflow cannot run before the tag, which the orchestrator verifies at release.

## Proof budget

  cases: 2 (index generator; five-way resolution table as one parametrised case)
  tier: pyunit / the installable test module
  lands in: tests/test_release_index.py (new), tests/test_runners_installable.py
  what already covers this: the Makefile.tiers prefix identity test; amend it
