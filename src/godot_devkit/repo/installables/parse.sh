#!/usr/bin/env bash
# parse.sh — the parse gate, in TWO stages, because either one alone is a
# false claim:
#
#   1. BOOT   — boot the project headless with --quit and read the stream for
#               parse errors and autoload-boot crashes. Proves the BOOT GRAPH
#               only: autoloads, the main scene, and whatever they transitively
#               preload or name by class_name.
#   2. SWEEP  — load every .gd in the project and fail on any the engine
#               refuses to compile, reporting N/N.
#
# Stage 2 exists because GDScript compiles LAZILY. Nothing preloads a test
# tree, an @tool/editor script, a non-autoloaded addon, or anything only
# load()ed by string path — so a parse error in ANY of them is absent from the
# stream stage 1 reads. A consumer shipped a broken integration scenario
# through a green stage-1 gate AND a green precommit for a day. The claim this
# gate makes is "every .gd in the project compiles, and the boot is clean",
# not "the scripts the boot happened to touch compiled".
#
# The sweep is deliberately NOT a list of the directories somebody remembered
# to add: compile_sweep.gd walks the project, so a new unreached corner of the
# tree is covered with no edit here.
#
# OUTPUT: the console gets one verdict line naming the transcript; the full
# boot + sweep stream goes to .gate-reports/parse.log. On a failure the
# offending lines are printed verbatim as well. VERBOSE=1 streams everything.
#
# Usage: tools/dev/runners/parse.sh   (via `make parse`)
#        tools/dev/runners/parse.sh --help | --self-test
# Exit:  0 = boot clean and every script compiled
#        1 = findings (boot errors, or a script that would not compile)
#        2 = harness error (unusable repo, or a usage mistake)
#
# No `set -e`: the engine can exit non-zero on a boot crash, and the contract
# is that EVERY invocation ends in a verdict line. The greps below are the
# authority, not the engine's exit code.
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
# LIB is where `godot-devkit install-runners` put gdk_runners.sh, relative to
# THIS file. The stock layout is tools/dev/runners/parse.sh beside
# tools/dev/gdk_runners.sh.
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
# Depth from this file to the repo root, for the stock layout above.
REPO_ROOT_FROM_HERE="../../.."
# The sweep script travels WITH this runner and is addressed as a res:// path,
# so the two spellings must agree: install-runners writes it beside this file,
# and this is that path seen from the project root.
GDK_PARSE_SWEEP_SCRIPT="${GDK_PARSE_SWEEP_SCRIPT:-res://tools/dev/runners/compile_sweep.gd}"
# Env: GDK_PARSE_BOOT_TIMEOUT   seconds to bound stage 1 (default 120)
#      GDK_PARSE_SWEEP_TIMEOUT  seconds to bound stage 2 (default 300)
#      GDK_GODOT                the engine binary (default `godot`)
# -----------------------------------------------------------------------------

GATE_TAG="PARSE"
GATE_SLOT="parse"

# What stage 1 reads as a boot failure. Anchored on the engine's own two
# shapes: a GDScript parse error, and an engine ERROR naming a .gd.
BOOT_ERROR_PATTERN='SCRIPT ERROR: Parse Error|^ERROR: .*\.gd'

# Stage-2 vocabulary — compile_sweep.gd's machine-readable output contract.
SWEEP_FAIL_PREFIX="SWEEP_FAIL "
SWEEP_RESULT_PREFIX="SWEEP_RESULT "
# The engine lines that say WHY a script would not compile — the actionable
# diagnosis behind each SWEEP_FAIL path.
SWEEP_DIAGNOSTIC_PATTERN='SCRIPT ERROR: Parse Error|Failed to load script|Compile Error|at: GDScript::reload'

BOOT_TIMEOUT_SECONDS="${GDK_PARSE_BOOT_TIMEOUT:-120}"
SWEEP_TIMEOUT_SECONDS="${GDK_PARSE_SWEEP_TIMEOUT:-300}"

usage() {
	cat <<'USAGE_EOF'
usage: parse.sh [--help] [--self-test]

The parse gate: boot the project headless and read the stream for parse
errors, then load EVERY .gd through compile_sweep.gd and report N/N.

  (no argument)  run both stages
  --self-test    prove the argument handling and the sweep-output parser
                 without booting anything
  --help         this message

Env: GDK_PARSE_BOOT_TIMEOUT   seconds bounding stage 1 (default 120)
     GDK_PARSE_SWEEP_TIMEOUT  seconds bounding stage 2 (default 300)
     GDK_PARSE_SWEEP_SCRIPT   res:// path to compile_sweep.gd
     GDK_RUNNERS_LIB          path to gdk_runners.sh, relative to this file
     GDK_GODOT                the engine binary (default `godot`)
     VERBOSE=1                stream the transcript to the console too
Exit: 0 clean | 1 findings | 2 harness/usage error
USAGE_EOF
}

# --- the sweep-output parser -------------------------------------------------
# compile_sweep.gd's contract is two line shapes in a stream that also carries
# every engine warning the boot produced. These read that contract and nothing
# else, so the self-test can fire them at a fixture transcript in CI — which is
# the only way this runner's own logic is provable where no engine exists.

# sweep_result_line <log> — the LAST SWEEP_RESULT line, or empty when the sweep
# produced none. Empty is a HARNESS failure, never a pass: a sweep that printed
# no result proves nothing compiled.
sweep_result_line() {
	grep -F "$SWEEP_RESULT_PREFIX" "$1" 2>/dev/null | tail -n 1
}

# sweep_result_field <result line> <1|2> — compiled count, then total.
sweep_result_field() {
	printf '%s' "$1" | awk -v n="$2" '{print $(n + 1)}'
}

# sweep_failed_paths <log> — every script the sweep could not compile, one
# res:// path per line, with the marker stripped.
sweep_failed_paths() {
	grep -F "$SWEEP_FAIL_PREFIX" "$1" 2>/dev/null | sed "s/^${SWEEP_FAIL_PREFIX}//"
}

# --- --self-test -------------------------------------------------------------
# Two stages of this runner boot an engine, and this package never does (and a
# consumer's CI may have none). So the corpus covers what the runner OWNS: how
# it reads its arguments, and whether it reads a sweep transcript correctly —
# including the transcript shape that must NOT be read as a pass.
self_test() {
	local scratch log line rc failures=0 cases=0

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --what >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an unknown argument should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --help extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EXTRA argument should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EMPTY argument should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-parse-selftest.XXXXXX")" || return 1
	log="$scratch/sweep.log"

	# A clean sweep, buried in the engine chatter a real transcript carries.
	cat > "$log" <<'FIXTURE_EOF'
Godot Engine v4.6.stable - https://godotengine.org
WARNING: something the importer says
SWEEP_RESULT 412 412
FIXTURE_EOF
	cases=$((cases + 1))
	line="$(sweep_result_line "$log")"
	[ "$(sweep_result_field "$line" 1)/$(sweep_result_field "$line" 2)" = "412/412" ] \
		|| { echo "  MISS — a clean sweep must parse as 412/412, got '$line'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	[ -z "$(sweep_failed_paths "$log")" ] \
		|| { echo "  MISS — a clean sweep must name no failures" >&2; failures=$((failures + 1)); }

	# A sweep with failures. The count and the named paths must agree, and the
	# marker must be stripped so the report reads as paths.
	cat > "$log" <<'FIXTURE_EOF'
SCRIPT ERROR: Parse Error: Identifier "nope" not declared in the current scope.
   at: GDScript::reload (res://tests/integration/broken.gd:12)
SWEEP_FAIL res://tests/integration/broken.gd
SWEEP_FAIL res://addons/thing/tool.gd
SWEEP_RESULT 410 412
FIXTURE_EOF
	cases=$((cases + 1))
	line="$(sweep_result_line "$log")"
	[ "$(sweep_result_field "$line" 1)/$(sweep_result_field "$line" 2)" = "410/412" ] \
		|| { echo "  MISS — a failing sweep must parse as 410/412, got '$line'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	[ "$(sweep_failed_paths "$log")" = "res://tests/integration/broken.gd
res://addons/thing/tool.gd" ] \
		|| { echo "  MISS — the failed paths did not come back stripped, got '$(sweep_failed_paths "$log")'" >&2; failures=$((failures + 1)); }

	# The cardinal case: a transcript with NO result line. A parser that
	# defaulted to 0/0 here would report a clean sweep over a sweep that never
	# ran — the false PASS this whole gate exists to make impossible.
	cases=$((cases + 1))
	printf 'Godot Engine v4.6.stable\nERROR: the editor died\n' > "$log"
	[ -z "$(sweep_result_line "$log")" ] \
		|| { echo "  MISS — a transcript with no SWEEP_RESULT must parse as empty" >&2; failures=$((failures + 1)); }

	# A LATER result line wins: the wrapper appends both stages to one
	# transcript, and a cold-cache retry can leave two.
	cases=$((cases + 1))
	printf '%s\n' "${SWEEP_RESULT_PREFIX}1 2" "${SWEEP_RESULT_PREFIX}412 412" > "$log"
	line="$(sweep_result_line "$log")"
	[ "$(sweep_result_field "$line" 1)" = "412" ] \
		|| { echo "  MISS — the LAST result line must win, got '$line'" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

# The whole argument surface: nothing, --help, or --self-test. An extra
# argument is refused rather than ignored — a caller passing one believes this
# takes options it does not, and an EMPTY one is an unset variable, not
# "nothing".
if [ "$#" -gt 1 ]; then
	echo "[$GATE_TAG] one argument at most — got $#" >&2
	usage >&2
	exit 2
fi
if [ "$#" -eq 1 ]; then
	case "$1" in
		--help|-h) usage; exit 0 ;;
		--self-test) self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
		*) echo "[$GATE_TAG] unknown argument '$1'" >&2; usage >&2; exit 2 ;;
	esac
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$GDK_RUNNERS_LIB"
if [ ! -f "$LIB" ]; then
	echo "[$GATE_TAG] gdk_runners.sh not found at '$LIB' — set GDK_RUNNERS_LIB" >&2
	exit 2
fi
cd "$REPO_ROOT" || exit 2

# Shared sandbox / bounded-run / gate-output contract.
# shellcheck source=/dev/null
source "$LIB"

if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "[$GATE_TAG] $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	echo "[$GATE_TAG] REPO_ROOT_FROM_HERE ('$REPO_ROOT_FROM_HERE') is the depth from" >&2
	echo "[$GATE_TAG] this file to the project root; fix it, or move the runner back." >&2
	exit 2
fi

# user:// sandbox — both stages boot the project's full autoload stack.
gdk_sandbox_home

# ONE transcript for both stages, published where a reader can still open it
# after the run (the sandbox HOME self-destructs, so it cannot live there).
LOG="$(gdk_gate_log "$GATE_SLOT")"

# --- Stage 1: boot -----------------------------------------------------------
gdk_gate_capture "$LOG" -- gdk_run_bounded "$BOOT_TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path . --headless --quit
BOOT_EXIT="$GDK_GATE_EXIT"

if gdk_timeout_is_hang "$BOOT_EXIT"; then
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL — the boot exceeded ${BOOT_TIMEOUT_SECONDS}s, killed" "$LOG"
	exit 1
fi

if grep -qE "$BOOT_ERROR_PATTERN" "$LOG"; then
	echo "[$GATE_TAG] FAIL — boot errors:"
	grep -E "$BOOT_ERROR_PATTERN" "$LOG" | sed 's/^/    /'
	gdk_gate_verdict "$GATE_TAG" "FAIL (boot)" "$LOG"
	exit 1
fi

[ "${VERBOSE:-0}" = "0" ] \
	|| echo "[$GATE_TAG] boot clean — sweeping every .gd for compile errors"

# --- Stage 2: full-project compile sweep -------------------------------------
# `-s` runs the sweep as the MainLoop (autoloads still boot, hence the sandbox
# above). A repo-wide load pass emits one engine error block per broken script;
# the gate reports those, plus the N/N line, and the rest joins the transcript.
gdk_gate_capture "$LOG" -- gdk_run_bounded "$SWEEP_TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path . --headless -s "$GDK_PARSE_SWEEP_SCRIPT"
SWEEP_EXIT="$GDK_GATE_EXIT"

if gdk_timeout_is_hang "$SWEEP_EXIT"; then
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL — the compile sweep exceeded ${SWEEP_TIMEOUT_SECONDS}s, killed" "$LOG"
	exit 1
fi

RESULT_LINE="$(sweep_result_line "$LOG")"
if [ -z "$RESULT_LINE" ]; then
	echo "[$GATE_TAG] FAIL — the compile sweep produced no result line; it cannot prove anything compiled."
	echo "    Is $GDK_PARSE_SWEEP_SCRIPT where GDK_PARSE_SWEEP_SCRIPT says it is?"
	tail -n 40 "$LOG" | sed 's/^/    /'
	gdk_gate_verdict "$GATE_TAG" "FAIL (no sweep result)" "$LOG"
	exit 1
fi

COMPILED="$(sweep_result_field "$RESULT_LINE" 1)"
TOTAL="$(sweep_result_field "$RESULT_LINE" 2)"
FAILED_PATHS="$(sweep_failed_paths "$LOG")"

if [ -n "$FAILED_PATHS" ]; then
	echo "[$GATE_TAG] FAIL — ${COMPILED}/${TOTAL} scripts compiled; these did not:"
	printf '%s\n' "$FAILED_PATHS" | sed 's/^/    /'
	echo "  why:"
	grep -E "$SWEEP_DIAGNOSTIC_PATTERN" "$LOG" | sed 's/^/    /' || true
	gdk_gate_verdict "$GATE_TAG" "FAIL (compile sweep)" "$LOG"
	exit 1
fi

gdk_gate_verdict "$GATE_TAG" \
	"PASS (boot clean; ${COMPILED}/${TOTAL} scripts compiled)" "$LOG"
exit 0
