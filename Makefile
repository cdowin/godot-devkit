# godot-devkit — the scripted path.
#
# This file exists because its absence was measurable. With no scripted entry
# point, every agent working on this package invented its own pytest incantation
# and then hand-rolled censuses, replays and fuzzers around it — apparatus that
# ran once inside one agent's context and was thrown away. A target is the
# cheapest possible fix: the work is written down, it is rerunnable, and nobody
# has to be told the command.
#
# The gate FRAMEWORK is this repo's own Makefile.gates, the file
# `godot-devkit install-gates` writes: `check`, `precommit`, `verify`, `help`
# and the `gdk_gate` capture define. This repo is a consumer of its own
# installables, the same way a game is. What is this repo's: the Python it runs
# (below) and its tiers (Makefile.tiers — the seam the include `-include`s).
#
# EVERY GATE PRINTS ONE LINE. The default output of a target here is its
# verdict, naming the full transcript under .gate-reports/; `VERBOSE=1` streams
# the whole thing. That is `gdk_gate_capture` / `gdk_gate_verdict` out of
# tools/dev/gdk_gate.sh, sourced by every recipe — never a hand-invented grep
# over a gate's output to find its result.
#
# GNU make 3.81 (what macOS ships) is the floor. Nothing here needs more.

# The package is stdlib-only. The TEST run needs one thing it does not ship:
# pytest. 3.11 is the declared floor and where the fast loop runs; the matrix
# is every interpreter the package claims.
PY_FLOOR  ?= 3.11
PY_MATRIX ?= 3.11 3.12 3.13 3.14
UV        ?= uv
TEST_DEPS ?= --with pytest
PYTEST    ?= $(UV) run --python $(PY_FLOOR) $(TEST_DEPS) python -m pytest
PYTEST_Q  ?= -q

# The package's OWN gates run the WORKING TREE, never an installed build: a
# gate that checks the last release tells you nothing about the change in
# front of you. No wheel build, no venv, no network — the package imports from
# src/ with the stdlib. (The test targets above DO use uv, for pytest.)
#
# GODOT_DEVKIT is what Makefile.tiers' `godot-check` and `uid-scan` run (a
# consumer resolves it from its uv.lock (`uv run --frozen`), or the legacy
# GODOT_DEVKIT_VERSION pin; this tree sets it ahead of the include, so the tier
# file resolves nothing). It is the package from src/ INSIDE a scratch copy of
# the committed clean Godot project — this tree is not a Godot project, and the
# self-hosting proof is the eight gates over something committed here, not a
# 0-file census over the repo itself.
PY          ?= python3
GODOT_DEVKIT ?= bash tools/dev/godot_devkit_on_fixture.sh

# What `make check` runs after `shell`: the eight Godot gates over the fixture.
GDK_CHECKS := godot-check

include Makefile.gates
