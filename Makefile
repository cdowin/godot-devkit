# godot-devkit — the scripted path.
#
# This file exists because its absence was measurable. With no scripted entry
# point, every agent working on this package invented its own pytest incantation
# and then hand-rolled censuses, replays and fuzzers around it — apparatus that
# ran once inside one agent's context and was thrown away. A target is the
# cheapest possible fix: the work is written down, it is rerunnable, and nobody
# has to be told the command.
#
# The two roles in devkit.toml `[tasks]` point HERE — `quick = "make precommit"`
# and `verify = "make milestone"` — so an agent learns one word and this file
# owns the vocabulary. `godot-devkit check tasks` asserts that pointer resolves.
#
# GNU make 3.81 (what macOS ships) is the floor. Nothing here needs more.

.DEFAULT_GOAL := help

# The package is stdlib-only. The TEST run needs two things it does not ship:
# pytest, and PyYAML — `install-ci` generates a GitHub workflow, and the only
# honest way to assert a generator emits parseable YAML is to parse it. Without
# it that test skips, and a skipped test reports nothing while looking green.
# 3.11 is the declared floor and where the fast loop runs; the matrix is every
# interpreter the package claims.
PY_FLOOR  ?= 3.11
PY_MATRIX ?= 3.11 3.12 3.13 3.14
UV        ?= uv
TEST_DEPS ?= --with pytest --with pyyaml
PYTEST    ?= $(UV) run --python $(PY_FLOOR) $(TEST_DEPS) python -m pytest
PYTEST_Q  ?= -q

# The gates run the WORKING TREE, never an installed build: a gate that checks
# the last release tells you nothing about the change in front of you. No wheel
# build, no venv, no network — the package imports from src/ with the stdlib.
PY        ?= python3
DEVKIT    ?= PYTHONPATH=$(CURDIR)/src $(PY) -m godot_devkit.cli

.PHONY: help test matrix fuzz gates smoke precommit milestone

help:
	@echo 'godot-devkit — make targets'
	@echo
	@echo '  make test        the suite on the $(PY_FLOOR) floor'
	@echo '  make matrix      the suite on every claimed interpreter ($(PY_MATRIX))'
	@echo '  make fuzz        the committed seeded harnesses (differential + replay)'
	@echo '  make gates       godot-devkit check all, on this repo'
	@echo '  make smoke       every verb against the live consumer checkouts (read-only)'
	@echo
	@echo '  make precommit   gates + test          ([tasks] quick)'
	@echo '  make milestone   gates + matrix + smoke ([tasks] verify — what CI runs)'
	@echo
	@echo 'Agents: run `godot-devkit task quick` / `task verify` instead of naming'
	@echo 'these targets, so the same word works in every repo.'

test:
	$(PYTEST) $(PYTEST_Q)

# Every interpreter in one target, and it reports which one failed. A matrix
# that stops at the first failure hides the difference between "3.14 only" and
# "everywhere", which is the whole question a matrix is asked.
matrix:
	@fail=''; for v in $(PY_MATRIX); do \
	  echo "=== python $$v ==="; \
	  $(UV) run --python $$v $(TEST_DEPS) python -m pytest $(PYTEST_Q) || fail="$$fail $$v"; \
	done; \
	if [ -n "$$fail" ]; then echo "MATRIX FAIL on:$$fail"; exit 1; fi; \
	echo "MATRIX PASS on $(PY_MATRIX)"

# The seeded harnesses on their own, for when one of them is what you changed.
# `make test` runs them too — they are tests, not a side quest, and a fuzz that
# only runs when somebody remembers it is a fuzz that does not run.
fuzz:
	$(PYTEST) $(PYTEST_Q) -m fuzz

gates:
	$(DEVKIT) check all

smoke:
	$(PY) tools/consumer_smoke.py

# The per-change gate. Gates first: they take under a second and they are what
# catches a doc or a PM-tree edit that the suite has no opinion about.
precommit: gates test

# The full gate, and what CI runs. The matrix subsumes `test`, so it is not
# listed twice.
milestone: gates matrix smoke
