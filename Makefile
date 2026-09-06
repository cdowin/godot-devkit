# godot-devkit — the scripted path.
#
# This file exists because its absence was measurable. With no scripted entry
# point, every agent working on this package invented its own pytest incantation
# and then hand-rolled censuses, replays and fuzzers around it — apparatus that
# ran once inside one agent's context and was thrown away. A target is the
# cheapest possible fix: the work is written down, it is rerunnable, and nobody
# has to be told the command.
#
# The gate FRAMEWORK is not this file's. `check`, `precommit`, `milestone`,
# `pm`, `help` and the `gdk_gate` capture define arrive from Makefile.devkit,
# which `agentic-sdlc install-gates` writes from the pinned tag below — this
# repo is a CONSUMER of agentic-sdlc, the same way its own consumers pin it.
# What is this repo's: the Python it runs (below the pin) and its tiers
# (Makefile.tiers — the seam the include `-include`s).
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
# `env` is load-bearing: the gate helper runs an ARGV, not a shell line, so a
# leading VAR=value assignment needs a command to carry it.
PY          ?= python3
GODOT_DEVKIT ?= env PYTHONPATH=$(CURDIR)/src $(PY) -m godot_devkit.cli

# The pin, and the include that derives `DEVKIT` (the agentic-sdlc command)
# from it. Bumping the tag is the whole adoption; `agentic-sdlc adopt` checks it.
DEVKIT_VERSION := v0.2.0
include Makefile.devkit
