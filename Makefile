# godot-devkit — the scripted path.
#
# This file exists because its absence was measurable. With no scripted entry
# point, every agent working on this package invented its own pytest incantation
# and then hand-rolled censuses, replays and fuzzers around it — apparatus that
# ran once inside one agent's context and was thrown away. A target is the
# cheapest possible fix: the work is written down, it is rerunnable, and nobody
# has to be told the command.
#
# EVERY GATE PRINTS ONE LINE. The default output of a target here is its
# verdict, naming the full transcript on disk; `VERBOSE=1` streams the whole
# thing. That is not a local convention — it is `gdk_gate_capture` /
# `gdk_gate_verdict` out of installables/gdk_runners.sh, the library this
# package ships to its consumers, sourced straight from the source tree. The
# devkit is its own first consumer: an agent running `make milestone` here used
# to pipe it through a hand-invented five-shape grep to find the verdicts, and
# a toolkit whose own targets need that has not proven the thing it sells.
#
# GNU make 3.81 (what macOS ships) is the floor. Nothing here needs more.

.DEFAULT_GOAL := help

# The library is bash: arrays, PIPESTATUS, `local`. macOS bash 3.2 is the floor
# and the library holds that line.
SHELL := /bin/bash

# The package is stdlib-only. The TEST run needs one thing it does not ship:
# pytest. 3.11 is the declared floor and where the fast loop runs; the matrix
# is every interpreter the package claims.
PY_FLOOR  ?= 3.11
PY_MATRIX ?= 3.11 3.12 3.13 3.14
UV        ?= uv
TEST_DEPS ?= --with pytest
PYTEST    ?= $(UV) run --python $(PY_FLOOR) $(TEST_DEPS) python -m pytest
PYTEST_Q  ?= -q

# The GATES run the WORKING TREE, never an installed build: a gate that checks
# the last release tells you nothing about the change in front of you. For the
# gates alone: no wheel build, no venv, no network — the package imports from
# src/ with the stdlib. (The test targets above DO use uv, for pytest.)
# `env` is load-bearing: the gate helper runs an ARGV, not a shell line, so a
# leading VAR=value assignment needs a command to carry it.
PY        ?= python3
DEVKIT    ?= env PYTHONPATH=$(CURDIR)/src $(PY) -m godot_devkit.cli

# The shipped library, sourced from source. Self-hosting, the same way
# .github/workflows/verify.yml is installed rather than hand-written: if the
# gate helpers regress, this repo's own targets are the first thing to notice.
RUNNERS_LIB := src/godot_devkit/repo/installables/gdk_runners.sh

# VERBOSE reaches the capture helper as an ENVIRONMENT variable, so exporting
# it here is what makes `make gates VERBOSE=1` work as well as `VERBOSE=1 make
# gates`. Both spellings get typed; neither should silently do nothing.
VERBOSE ?= 0
export VERBOSE

# What a FAILING run shows on the console before its verdict: the lines that
# say what broke, in the tools this repo runs. Everything else stays in the log.
GATE_FAIL_RE   := ^(FAILED|ERROR)|^E +|  DRIFT |\] FAIL|MATRIX FAIL|^  (MISS|FALSE POSITIVE)
GATE_FAIL_LINES := 20

# Each target's one-line summary, read back out of its own transcript. The
# leading `[tag]` a tool prints is stripped: the verdict line supplies the tag.
SUM_PYTEST := grep -aoE '[0-9]+ (passed|failed)[^|]*' "$$log" | tail -1
SUM_GATES  := printf '%s check(s) PASS' "$$(grep -acE '^\[check:[a-z]+\] PASS' "$$log")"
SUM_SMOKE  := tail -1 "$$log" | sed -E 's/^\[[a-z:-]+\] //'
SUM_HOOKS  := printf '%s hook(s) SELF-TEST OK' "$$(grep -ac 'SELF-TEST OK' "$$log")"

# $(call gate,<log slot>,<TAG>,<summary command>,<argv...>)
# Run a command through the shipped capture helper: quiet by default, the full
# transcript on disk, one verdict line naming it, and the command's own exit
# code preserved (the helper reads PIPESTATUS, so `$$?` would be the cap's).
define gate
@set -o pipefail; . $(RUNNERS_LIB); \
log="$$(gdk_gate_log $(1))"; \
gdk_gate_capture "$$log" -- $(4); \
status="$$GDK_GATE_EXIT"; \
summary="$$($(3))"; \
if [ "$$status" -ne 0 ]; then \
	grep -aE '$(GATE_FAIL_RE)' "$$log" | head -$(GATE_FAIL_LINES) \
		|| tail -$(GATE_FAIL_LINES) "$$log"; \
	summary="FAIL (exit $$status) — $$summary"; \
fi; \
gdk_gate_verdict $(2) "$$summary" "$$log"; \
exit "$$status"
endef

.PHONY: help test matrix fuzz gates hooks-self-test smoke precommit milestone pm

help:
	@echo 'godot-devkit — make targets'
	@echo
	@echo '  make test        the suite on the $(PY_FLOOR) floor'
	@echo '  make matrix      every claimed interpreter ($(PY_MATRIX)): $(PY_FLOOR) runs the whole suite, the rest -m "not shell" (a spawn is not interpreter-sensitive)'
	@echo '  make fuzz        the committed seeded harnesses (differential + replay)'
	@echo '  make gates       godot-devkit check all, on this repo'
	@echo '  make hooks-self-test  the installed hooks that ship a corpus, replayed (sandbox + the two ledger couriers)'
	@echo '  make smoke       check all + autoloads/scene/refs/pm on the consumers (read-only)'
	@echo
	@echo '  make pm ARGS="…"  the pm tracker from SOURCE, never a cached wheel (the ledger couriers call this)'
	@echo
	@echo '  make precommit   gates + hooks-self-test + test           the per-change gate'
	@echo '  make milestone   gates + hooks-self-test + matrix + smoke  the full gate, and what CI runs'
	@echo
	@echo 'Every gate prints ONE verdict line naming its full log under'
	@echo '.gate-reports/. VERBOSE=1 streams the transcript as well.'

# The pm tracker over THIS repo's tree, from source (CLAUDE.md: never verify
# through a cached wheel). .PHONY matters: a pm/ directory at the root would
# otherwise satisfy the target silently and the ledger couriers would record
# nothing (0.23.0/usage-capture, reviewer U1).
pm:
	PYTHONPATH=src python3 -m godot_devkit.cli pm $(ARGS)

test:
	$(call gate,test,TEST,$(SUM_PYTEST),$(PYTEST) $(PYTEST_Q))

# The seeded harnesses on their own, for when one of them is what you changed.
# `make test` runs them too — they are tests, not a side quest, and a fuzz that
# only runs when somebody remembers it is a fuzz that does not run.
fuzz:
	$(call gate,fuzz,FUZZ,$(SUM_PYTEST),$(PYTEST) $(PYTEST_Q) -m fuzz)

gates:
	$(call gate,gates,GATES,$(SUM_GATES),$(DEVKIT) check all)

smoke:
	$(call gate,smoke,SMOKE,$(SUM_SMOKE),$(PY) tools/consumer_smoke.py)

# The hooks this repo self-hosts that ship their own block/allow corpus: the
# raw-engine-boot guard and the two ledger couriers. Replayed here so an edit
# to a guard cannot quietly change a verdict — the same wiring the README asks
# of a consumer (nullbound: a `hooks-self-test` target in `make check`).
HOOKS_WITH_CORPUS := tools/hooks/cc-godot-sandbox.sh tools/hooks/cc-ledger-subagent.sh tools/hooks/cc-ledger-session.sh
hooks-self-test:
	$(call gate,hooks-self-test,HOOKS,$(SUM_HOOKS),sh -c 'for h in $(HOOKS_WITH_CORPUS); do bash "$$h" --self-test || exit 1; done')

# Every interpreter in one target, and it reports which one failed. A matrix
# that stops at the first failure hides the difference between "3.14 only" and
# "everywhere", which is the whole question a matrix is asked. It writes its own
# loop rather than $(call gate,...) because it captures N runs into ONE
# transcript — but it ends the same way, with one verdict line naming that log.
#
# The FLOOR runs the whole suite; every other interpreter runs `-m "not shell"`.
# ~85% of this suite's wall clock is `subprocess` — bash, make, git, the
# installed hook corpora — and a spawn is not something a Python version
# changes, so four interpreters replaying it bought minutes and no information.
# The `shell` mark is DERIVED per module in tests/conftest.py from what the
# source does, never a list here: a roster in this file is a roster that goes
# stale, and a module that quietly leaves it stops running on three
# interpreters with nothing going red.
#
# A PY_FLOOR that is not in PY_MATRIX is refused BEFORE the first interpreter —
# the slice would then be run by nobody and the matrix would print PASS over a
# suite that never ran, which is worse than the sixteen minutes this saves.
# Membership is decided by the same word splitting the loop uses, so the guard
# and the run cannot disagree; a `case` pattern would call a 3.1 floor a member
# of a 3.11 matrix. (PY_FLOOR/PY_MATRIX are operator configuration: the guard
# is against bumping one and not the other, not against shell injection
# through a make variable.)
matrix:
	@set -o pipefail; . $(RUNNERS_LIB); \
	log="$$(gdk_gate_log matrix)"; fail=''; floor=''; full=''; \
	for v in $(PY_MATRIX); do [ "$$v" = "$(PY_FLOOR)" ] && floor="$$v"; done; \
	if [ -z "$$floor" ]; then \
		echo 'PY_FLOOR "$(PY_FLOOR)" is not in PY_MATRIX "$(PY_MATRIX)"' >> "$$log"; \
		gdk_gate_verdict MATRIX 'REFUSED: PY_FLOOR "$(PY_FLOOR)" is not in PY_MATRIX "$(PY_MATRIX)", so no interpreter would run the whole suite' "$$log"; \
		exit 2; \
	fi; \
	for v in $(PY_MATRIX); do \
		if [ -z "$$full" ] && [ "$$v" = "$(PY_FLOOR)" ]; then \
			full="$$v"; slice=(); ran='the whole suite'; \
		else \
			slice=(-m 'not shell'); ran='-m "not shell"'; \
		fi; \
		echo "=== python $$v ($$ran) ===" >> "$$log"; \
		[ "$$VERBOSE" = "0" ] || echo "=== python $$v ($$ran) ==="; \
		gdk_gate_capture "$$log" -- \
			$(UV) run --python $$v $(TEST_DEPS) python -m pytest $(PYTEST_Q) "$${slice[@]}" || true; \
		[ "$$GDK_GATE_EXIT" -eq 0 ] || fail="$$fail $$v"; \
	done; \
	if [ -n "$$fail" ]; then \
		grep -aE '$(GATE_FAIL_RE)' "$$log" | head -$(GATE_FAIL_LINES) || true; \
		gdk_gate_verdict MATRIX "FAIL on$$fail" "$$log"; \
		exit 1; \
	fi; \
	gdk_gate_verdict MATRIX "PASS on $(PY_MATRIX)" "$$log"

# The per-change gate. Gates first: they take under a second and they are what
# catches a doc or a PM-tree edit that the suite has no opinion about. A
# composition prints its members' verdicts — one line each, nothing of its own.
precommit: gates hooks-self-test test

# The full gate, and what CI runs. The matrix subsumes `test`, so it is not
# listed twice.
milestone: gates hooks-self-test matrix smoke
