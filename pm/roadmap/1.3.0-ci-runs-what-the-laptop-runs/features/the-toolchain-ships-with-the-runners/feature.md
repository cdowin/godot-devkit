---
id: 1.3.0/the-toolchain-ships-with-the-runners
milestone: "1.3.0"
name: the toolchain ships with the runners
status: done
reviewed: docs/reviews/2026-09-28-1.3.0-the-toolchain-ships-with-the-runners.md
phase:
depends_on: []
consumed_by: []
changelog: `install-runners` writes a composite action, `.github/actions/godot-toolchain`, that installs the engine, gdlint and shellcheck at pinned versions and imports the project; `uid-guard.yml` is no longer installed, and an existing copy is named as retired: safe to delete when `[gates] extra` names `godot-check` (then `check uid` runs in `make check`), and to keep otherwise (#26).
---

# the toolchain ships with the runners

Issues: #26.

The verify workflow moved to agentic-sdlc's `install-ci` in 0.25.0. Its toolchain slot is empty, so
a Godot consumer either hand-rolls the engine steps or keeps a pre-0.25.0 file this kit wrote.
nullbound kept the old file, and it failed three ways the laptop never sees: apt's shellcheck
(SC2015 on three scripts that 0.11.0 passes), `gdtoolkit==4.*`, and no import pass, so
`class_name` globals and a tracked `.ttf` did not resolve.

## Decided (do not re-plan)

- **New installable `ci-godot-toolchain.yml` → `.github/actions/godot-toolchain/action.yml`**,
  in `install.py`'s table, written by `install-runners` like the rest (same --force/--diff rules).
  A composite action (`runs: using: composite`, every `run` step `shell: bash`). Inputs:
  `godot-patch` (required, no default: the part `project.godot` does not carry),
  `gdtoolkit-version` (default `4.5.0`), `shellcheck-version` (default `0.11.0`).
  Steps, in order:
  1. Derive the engine: the first MAJOR.MINOR entry of `config/features` in `project.godot`, plus
     the patch input. Every unreadable case is refused BY NAME and emits nothing (port the step
     from nullbound's `.github/workflows/verify.yml`, "Godot version, from project.godot").
  2. `chickensoft-games/setup-godot@v2` with that version, `include-templates: false`,
     `use-dotnet: false`.
  3. `uv tool install "gdtoolkit==${{ inputs.gdtoolkit-version }}"` (the caller's workflow ran
     setup-uv before the slot; the action's header says so).
  4. shellcheck from the release tarball: `koalaman/shellcheck` `v$V/shellcheck-v$V.linux.x86_64.tar.xz`
     into `$RUNNER_TEMP`, `sudo install` to `/usr/local/bin`, then `shellcheck --version`.
  5. Import: `"$GODOT" --path . --headless --import || echo "::warning::…"`, then
     `test -f .godot/global_script_class_cache.cfg` (the assert is the gate; the import's own exit
     is noisy).
- **The consumer's line.** `install-runners` prints, as a `next:` line, the step to paste into the
  toolchain slot of `.github/workflows/verify.yml`:
  `- uses: ./.github/actions/godot-toolchain` / `with: { godot-patch: "<n>" }`. README says the same
  in the install section.
- **Retire `ci-uid-guard.yml` from the installer.** `uid-scan` is a tier of `make milestone`
  (Makefile.tiers), so the workflow is a second run of a check the full gate already runs. Remove
  the table row and the installable; `install-runners` no longer writes it and does NOT delete a
  consumer's existing copy — it prints one line naming it as retired and safe to delete.
- Minor bump (a new installed file, a retired one). The orchestrator bumps at close.

## Ship criterion

- `install-runners` into a scratch project writes `.github/actions/godot-toolchain/action.yml`
  holding the three inputs with those defaults and the import assert, and writes no
  `.github/workflows/uid-guard.yml`.
- A scratch project already holding `uid-guard.yml` keeps it and gets the retired line.

## Proof budget

  cases: 2 (amend the installable census case; one case for the retired-file line)
  tier: unit (a temp tree, no process)
  lands in: tests/test_runners_installable.py
  what already covers this: the installable table census; it names uid-guard.yml today.
