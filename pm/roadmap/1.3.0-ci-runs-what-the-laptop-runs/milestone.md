---
id: "1.3.0"
kind: milestone
name: ci runs what the laptop runs
status: building
depends_on: []
branch: milestone/1.3.0-ci-runs-what-the-laptop-runs
mode: parallel
version: 1.3.0
changelog: A consumer's CI installs the Godot toolchain the local gate runs, pinned, and imports the project before the gate; the integration self-test no longer fails on Linux when grep exits early.
---

# 1.3.0 — ci runs what the laptop runs

Found getting a consumer's `verify` green in CI for the first time (cdowin/nullbound#75,
2026-09-28). The same `make milestone` answered differently on the runner: apt's shellcheck is
older than the laptop's, a fresh checkout has no `.godot/` import cache, and a self-test pipe
under `pipefail` misses on Linux. GitHub #26, #27. Since 0.25.0 the verify workflow is
agentic-sdlc's `install-ci`, whose toolchain slot this kit never filled.

## Ship criterion

- `install-runners` writes `.github/actions/godot-toolchain/action.yml`, and one `uses:` line in
  the toolchain slot of agentic-sdlc's verify workflow installs the engine, gdlint and
  shellcheck at pinned versions and imports the project.
- `integration.sh --self-test` passes on Linux with keep-listed gates that sort early.
- `make milestone` green on this tree.
