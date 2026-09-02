#!/usr/bin/env bash
# unit.sh — the GUT unit/contract tier, headless and sandboxed.
#
# THE UNIT TIER: fast, no game boot, isolated by construction. GUT owns
# discovery, assertions and reporting; this runner owns the sandbox, the
# slicing, and the one thing GUT cannot be trusted to report — that every test
# script on disk actually RAN.
#
# Usage:
#   tools/dev/runners/unit.sh                # the whole tier
#   tools/dev/runners/unit.sh stats          # slice: tests/unit/stats/ only
#   tools/dev/runners/unit.sh stats protocol # several slices
#   tools/dev/runners/unit.sh --help | --self-test
#
# OUTPUT: the console gets GUT's totals block, every failing / erroring line
# verbatim, and one verdict line naming .gate-reports/unit.log, which carries
# the whole run. VERBOSE=1 streams everything instead.
#
# GUT's own volume knob (`-glog` 0-3) is deliberately left at its default:
# `p(text, level=0)` prints at EVERY level, so the per-test roster and the
# totals block are unaffected by it, and the only thing level 0 silences is
# orphan reporting. Filtering the console while the file keeps the verbatim
# stream is the honest version.
#
# Exit: 0 = all passed | 1 = failures or a coverage gap | 2 = harness error.
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
GDK_GUT_CMDLN="${GDK_GUT_CMDLN:-res://addons/gut/gut_cmdln.gd}"
# The tier's root, repo-relative. Each positional argument names a subdirectory
# of it.
GDK_UNIT_TEST_ROOT="${GDK_UNIT_TEST_ROOT:-tests/unit}"
# GUT's default test-script prefix + extension. The coverage gate counts these.
GDK_UNIT_TEST_GLOB="${GDK_UNIT_TEST_GLOB:-test_*.gd}"
# THE NO-BOOT GUARD, as an ERE over the tier's source. A unit test that boots
# the game belongs in the integration tier: booting reintroduces exactly the
# global-state bleed this tier exists to avoid. Name YOUR project's boot entry
# points here — and prefer a CONVENTION over a literal roster, because a
# renamed helper leaves a literal behind as a dead string and the guard stops
# catching anything (a consumer's guard silently died that way for months;
# `_for_scenario\(|\.start_game\(` is the shape that replaced it). Empty means
# no guard, and the verdict line says so rather than implying one ran.
GDK_UNIT_BOOT_MARKERS="${GDK_UNIT_BOOT_MARKERS:-}"
# Env: GDK_UNIT_TIMEOUT  seconds bounding the run (default 180)
#      GDK_GODOT         the engine binary (default `godot`)
# -----------------------------------------------------------------------------

GATE_TAG="UNIT"
GATE_SLOT="unit"
TIMEOUT_SECONDS="${GDK_UNIT_TIMEOUT:-180}"

# The console summary. GUT's totals block is the counts line; every failing /
# risky / refused-to-load line is surfaced verbatim, because those are the two
# things a reader came for. The per-test roster and the engine's boot chatter
# stay in the transcript.
#
# The load-failure class is `SCRIPT ERROR: Parse Error` / `Failed to load
# script` — the exact class the coverage gate exists for — NOT a bare
# `SCRIPT ERROR`: GUT's own loader emits one on every single boot, and a marker
# that fires 100% of the time trains a reader to ignore it.
SUMMARY_PATTERN='^(Totals|Scripts|Tests|Passing|Failing|Asserts|Pending)[[:space:]]|\[Failed\]|Tests failed|risky|Failed to load script|SCRIPT ERROR: Parse Error|Ignoring script'
# What GUT logs INSTEAD of failing when a test script will not load.
GUT_SKIP_MARKER='Ignoring script'
# The engine lines that explain WHY a script did not load — including the
# promoted-warning message and its `at: … .gd:NN` follow-up. They are what turn
# this gate's verdict into an actionable diagnosis.
LOAD_DIAGNOSTIC_PATTERN='Failed to load script|SCRIPT ERROR: Parse Error|at: GDScript::reload'

usage() {
	cat <<'USAGE_EOF'
usage: unit.sh [<slice>...]
       unit.sh --help | --self-test

Runs the GUT unit tier headless in a sandboxed HOME. Each <slice> is a
subdirectory of the tier root; with none, the whole tier runs.

  --self-test   prove the argument handling, the no-boot guard and the
                coverage-count parser against fixtures, booting nothing
  --help        this message

Env: GDK_UNIT_TEST_ROOT      the tier root (default tests/unit)
     GDK_UNIT_TEST_GLOB      the test-script glob the coverage gate counts
     GDK_UNIT_BOOT_MARKERS   ERE naming your boot entry points (no-boot guard)
     GDK_GUT_CMDLN           res:// path to gut_cmdln.gd
     GDK_UNIT_TIMEOUT        seconds bounding the run (default 180)
     GDK_RUNNERS_LIB         path to gdk_runners.sh, relative to this file
     GDK_GODOT               the engine binary (default `godot`)
     VERBOSE=1               stream the transcript to the console too
Exit: 0 all passed | 1 failures or a coverage gap | 2 harness/usage error
USAGE_EOF
}

# --- the coverage gate's parser ----------------------------------------------
# When a test script fails to parse, GUT logs `Ignoring script res://… because
# it does not extend GutTest` and then OMITS it from the totals — the run
# prints "All tests passed!" and exits 0. An unloadable script is, in the
# gate's output, indistinguishable from a script that does not exist. That hid
# 14 scripts / 100 tests (three of them policy scanners) for most of a day in a
# consumer repo.
#
# The check is a COUNT comparison: `test_*.gd` on disk against GUT's
# `Totals → Scripts`. Comparing the on-disk file LIST against the paths NAMED
# in the output does NOT work and must not be reimplemented — a skipped script
# IS named, in the very line announcing the skip.
#
# Both readers take their input on a pipe so the self-test can fire them at a
# fixture transcript with no engine anywhere.

# gut_scripts_run — read a GUT transcript on stdin, print the `Scripts` count
# from its totals block. Empty when there is no totals block at all, which is a
# HARNESS failure and never a pass.
gut_scripts_run() {
	awk '/^Totals/ { seen = 1; next }
	     seen && /^Scripts[[:space:]]+[0-9]+/ { print $2; exit }'
}

# gut_skipped_scripts — read a transcript on stdin, print every line in which
# GUT announced it was refusing to load a script under the tier root.
gut_skipped_scripts() {
	grep -F "$GUT_SKIP_MARKER" | grep -F "$GDK_UNIT_TEST_ROOT" || true
}

# strip_ansi — GUT colours its report block; BSD sed has no \x escape, so ESC
# is built with printf. The transcript on disk keeps the colour.
strip_ansi() {
	local esc
	esc="$(printf '\033')"
	sed -E "s/${esc}\[[0-9;]*m//g"
}

# disk_test_scripts <dir...> — how many test scripts the tier holds, for
# exactly the directories this invocation asked GUT to run.
disk_test_scripts() {
	local dir total=0 found
	for dir in "$@"; do
		[ -d "$dir" ] || continue
		found="$(find "$dir" -type f -name "$GDK_UNIT_TEST_GLOB" | wc -l | tr -d '[:space:]')"
		total=$((total + found))
	done
	printf '%s\n' "$total"
}

# --- --self-test -------------------------------------------------------------
self_test() {
	local scratch rc out failures=0 cases=0

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --nope >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an unknown flag should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --self-test extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — --self-test takes no argument, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EMPTY slice should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	# A slice name is a directory under the tier root, never a path: `../..`
	# would point GUT out of the tier and, worse, out of the project.
	cases=$((cases + 1))
	rc=0; bash "$0" ../../etc >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — a slice with a path separator should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	# --- the coverage parser, against a real GUT report block ---------------
	cases=$((cases + 1))
	out="$(printf '%s\n' \
		'Running tests...' \
		'Totals' \
		'Scripts           14' \
		'Tests            100' \
		'Passing          100' \
		| gut_scripts_run)"
	[ "$out" = "14" ] \
		|| { echo "  MISS — the Scripts count must parse as 14, got '$out'" >&2; failures=$((failures + 1)); }

	# `Scripts` BEFORE the totals block is GUT's own progress chatter, not the
	# count. A parser that took the first match would read the wrong number and
	# reconcile a coverage gap into a pass.
	cases=$((cases + 1))
	out="$(printf '%s\n' \
		'Scripts            1' \
		'Totals' \
		'Scripts           14' \
		| gut_scripts_run)"
	[ "$out" = "14" ] \
		|| { echo "  MISS — the count must come from the TOTALS block, got '$out'" >&2; failures=$((failures + 1)); }

	# The cardinal case: NO totals block. Empty, so the caller treats it as a
	# harness error — a parser defaulting to 0 here would reconcile with an
	# empty tier and report a pass over a run that never happened.
	cases=$((cases + 1))
	out="$(printf 'the engine crashed on boot\n' | gut_scripts_run)"
	[ -z "$out" ] \
		|| { echo "  MISS — a transcript with no totals block must parse as empty, got '$out'" >&2; failures=$((failures + 1)); }

	# The colour GUT writes must not hide the block from the parser.
	cases=$((cases + 1))
	out="$(printf '\033[32mTotals\033[0m\n\033[32mScripts           14\033[0m\n' \
		| strip_ansi | gut_scripts_run)"
	[ "$out" = "14" ] \
		|| { echo "  MISS — colour hid the totals block, got '$out'" >&2; failures=$((failures + 1)); }

	# The belt: an explicit skip line is a failure on its own, whatever the
	# counts say. It must be recognised UNDER THE TIER ROOT and nowhere else —
	# GUT announces skips for its own addon scripts too.
	cases=$((cases + 1))
	out="$(printf '%s\n' \
		"Ignoring script res://$GDK_UNIT_TEST_ROOT/stats/test_a.gd because it does not extend GutTest" \
		'Ignoring script res://addons/gut/thing.gd because it does not extend GutTest' \
		| gut_skipped_scripts | grep -c .)"
	[ "$out" = "1" ] \
		|| { echo "  MISS — the skip belt matched $out line(s), expected 1" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(printf 'All tests passed!\n' | gut_skipped_scripts | grep -c . || true)"
	[ "$out" = "0" ] \
		|| { echo "  MISS — a clean run reported $out skip(s)" >&2; failures=$((failures + 1)); }

	# --- the on-disk census, and the no-boot guard --------------------------
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-unit-selftest.XXXXXX")" || return 1
	mkdir -p "$scratch/tier/stats" "$scratch/tier/protocol"
	: > "$scratch/tier/stats/test_a.gd"
	: > "$scratch/tier/stats/test_b.gd"
	: > "$scratch/tier/stats/helper.gd"          # not a test script
	: > "$scratch/tier/protocol/test_c.gd"

	cases=$((cases + 1))
	out="$(disk_test_scripts "$scratch/tier")"
	[ "$out" = "3" ] \
		|| { echo "  MISS — the tier census must be 3, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(disk_test_scripts "$scratch/tier/stats")"
	[ "$out" = "2" ] \
		|| { echo "  MISS — a SLICE census must count only that slice, got '$out'" >&2; failures=$((failures + 1)); }

	# A slice that does not exist contributes nothing rather than erroring —
	# GUT reports the empty -gdir itself, and the counts still reconcile.
	cases=$((cases + 1))
	out="$(disk_test_scripts "$scratch/tier/nope")"
	[ "$out" = "0" ] \
		|| { echo "  MISS — an absent slice must count 0, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	printf 'func test_x():\n\tGameManager.start_game()\n' > "$scratch/tier/stats/test_b.gd"
	out="$(grep -rlE '_for_scenario\(|\.start_game\(' "$scratch/tier" --include='*.gd' 2>/dev/null | grep -c .)"
	[ "$out" = "1" ] \
		|| { echo "  MISS — the no-boot guard's grep found $out offender(s), expected 1" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

# --- argument surface --------------------------------------------------------
# `--help` / `--self-test` are exclusive verbs; everything else is a slice name.
case "${1:-}" in
	--help|-h)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --help takes no argument" >&2; exit 2; }
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --self-test takes no argument. See --help." >&2; exit 2; }
		self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
esac
for slice in "$@"; do
	# A slice is a DIRECTORY NAME under the tier root. An empty one is an unset
	# variable at the call site, and anything carrying a separator would aim
	# GUT outside the tier — both are the caller's bug, said out loud.
	case "$slice" in
		''|*/*|..|.|-*)
			echo "[$GATE_TAG] '$slice' is not a slice: name a directory under $GDK_UNIT_TEST_ROOT. See --help." >&2
			exit 2 ;;
	esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$GDK_RUNNERS_LIB"
if [ ! -f "$LIB" ]; then
	echo "[$GATE_TAG] gdk_runners.sh not found at '$LIB' — set GDK_RUNNERS_LIB" >&2
	exit 2
fi
cd "$REPO_ROOT" || exit 2

# shellcheck source=/dev/null
source "$LIB"

if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "[$GATE_TAG] $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	exit 2
fi

# --- No-boot guard (the tier's cardinal rule, enforced BEFORE the run) --------
GUARD_NOTE=""
if [ -z "$GDK_UNIT_BOOT_MARKERS" ]; then
	GUARD_NOTE="; no-boot guard not configured"
elif [ -d "$GDK_UNIT_TEST_ROOT" ]; then
	OFFENDERS="$(grep -rlE "$GDK_UNIT_BOOT_MARKERS" "$GDK_UNIT_TEST_ROOT" \
		--include='*.gd' 2>/dev/null || true)"
	if [ -n "$OFFENDERS" ]; then
		echo "[$GATE_TAG] GUARD FAIL — these unit tests boot the game (move them to the integration tier):"
		printf '%s\n' "$OFFENDERS" | sed 's/^/    /'
		exit 2
	fi
fi

# user:// sandbox — GUT boots the engine, and the engine writes to user://.
gdk_sandbox_home

LOG="$(gdk_gate_log "$GATE_SLOT")"

# Build the -gdir args. SCAN_DIRS mirrors them on disk so the coverage gate
# counts exactly the scripts this invocation asked GUT to run.
GDIR_ARGS=()
SCAN_DIRS=()
if [ "$#" -eq 0 ]; then
	GDIR_ARGS+=("-gdir=res://$GDK_UNIT_TEST_ROOT")
	SCAN_DIRS+=("$GDK_UNIT_TEST_ROOT")
else
	for slice in "$@"; do
		GDIR_ARGS+=("-gdir=res://$GDK_UNIT_TEST_ROOT/$slice")
		SCAN_DIRS+=("$GDK_UNIT_TEST_ROOT/$slice")
	done
fi

RAW="$(gdk_run_bounded "$TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path . --headless -s "$GDK_GUT_CMDLN" \
		"${GDIR_ARGS[@]}" -ginclude_subdirs -gexit 2>&1)"
GODOT_EXIT=$?

PLAIN="$(printf '%s\n' "$RAW" | strip_ansi)"
gdk_gate_publish "$LOG" "$RAW"

# The summary: counts, plus anything that failed, refused to load, or went risky.
printf '%s\n' "$PLAIN" | grep -E "$SUMMARY_PATTERN" | sed 's/^/  /' || true

if gdk_timeout_is_hang "$GODOT_EXIT"; then
	gdk_gate_verdict "$GATE_TAG" \
		"HARD_TIMEOUT — exceeded ${TIMEOUT_SECONDS}s, killed" "$LOG"
	exit 2
fi

DISK_SCRIPTS="$(disk_test_scripts "${SCAN_DIRS[@]}")"
RAN_SCRIPTS="$(printf '%s\n' "$PLAIN" | gut_scripts_run)"

print_load_diagnostics() {
	printf '%s\n' "$PLAIN" | grep -E "$LOAD_DIAGNOSTIC_PATTERN" | sed 's/^/    /' || true
}

# Belt: any explicit skip line is a failure on its own, whatever the counts say.
SKIPPED="$(printf '%s\n' "$PLAIN" | gut_skipped_scripts)"
if [ -n "$SKIPPED" ]; then
	echo "[$GATE_TAG] COVERAGE FAIL — GUT refused to load these unit scripts (parse error?):"
	printf '%s\n' "$SKIPPED" | sed 's/^/    /'
	print_load_diagnostics
	gdk_gate_verdict "$GATE_TAG" "COVERAGE FAIL (refused to load)" "$LOG"
	exit 1
fi

# Braces: the count must reconcile even if GUT ever drops a script silently.
if [ -z "$RAN_SCRIPTS" ]; then
	echo "[$GATE_TAG] COVERAGE FAIL — no GUT 'Totals → Scripts' line in the run output;"
	echo "    cannot prove the suite ran ${DISK_SCRIPTS} script(s). Treating as a harness error."
	gdk_gate_verdict "$GATE_TAG" "COVERAGE FAIL (no totals line)" "$LOG"
	exit 2
fi
if [ "$DISK_SCRIPTS" -ne "$RAN_SCRIPTS" ]; then
	echo "[$GATE_TAG] COVERAGE FAIL — ${DISK_SCRIPTS} test script(s) on disk, ${RAN_SCRIPTS} run."
	echo "    A script that contributes zero counted tests is NOT a benign category —"
	echo "    prove why each one is zero: a parse error reads here as 'absent'."
	print_load_diagnostics
	gdk_gate_verdict "$GATE_TAG" "COVERAGE FAIL (script count mismatch)" "$LOG"
	exit 1
fi

# GUT's -gexit returns non-zero when any test fails or errors; 0 on all-pass.
if [ "$GODOT_EXIT" -eq 0 ]; then
	gdk_gate_verdict "$GATE_TAG" \
		"PASS (${RAN_SCRIPTS}/${DISK_SCRIPTS} scripts loaded — full coverage${GUARD_NOTE})" "$LOG"
	exit 0
fi
gdk_gate_verdict "$GATE_TAG" "FAIL (gut exit $GODOT_EXIT)${GUARD_NOTE:+ —${GUARD_NOTE#;}}" "$LOG"
exit 1
