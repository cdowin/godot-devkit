#!/usr/bin/env bash
# capture.sh — the HEADED visual-capture wrapper, and the render-verify
# counterpart to scenario.sh.
#
# WHY IT IS NOT `scenario.sh --headed`. Headless is BLIND to render: the
# renderer does not rasterize, so a font-coverage bug, a shader that never
# compiled and a draw call that never ran all pass a headless gate. This boots
# WINDOWED — deliberately no `--headless` — so the pixels actually exist, then
# hands control to a capture scenario the same way scenario.sh does. user:// is
# sandboxed either way.
#
# LOCAL-ONLY: it needs a display. A visual-verification AID, never a CI gate —
# the headless scenario tier is the gate; this proves the pixels drew.
#
# THE CONVENTION: a capture scenario saves its PNG to
# res://.capture-reports/<scenario_name>.png. This wrapper OWNS that directory
# — it clears the WHOLE of it before the run and verifies the PNG after, so
# detection never depends on grepping log text and every file in there is
# provably from the latest run. Freshness is STRUCTURAL, not a discipline: a
# consumer's directory reached 131 files going back two months, and a stale PNG
# read as current cost an agent real time. Keeping two captures side by side
# means copying the first one out first.
#
# PARAMETERS: the scenario runner takes exactly one user argument, so a
# parameterized capture reads ENVIRONMENT variables — which this wrapper passes
# through untouched.
#
# Usage: tools/dev/runners/capture.sh <scenario_name>
#        tools/dev/runners/capture.sh --help | --self-test
# Exit:  0 = a PNG was rendered | 1 = none was | 2 = harness/usage error
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
GDK_SCENARIO_SOURCE_DIR="${GDK_SCENARIO_SOURCE_DIR:-tests/integration}"
GDK_CAPTURE_REPORT_DIR="${GDK_CAPTURE_REPORT_DIR:-.capture-reports}"
GDK_SCENARIO_USER_ARG="${GDK_SCENARIO_USER_ARG:---scenario}"
# Env: GDK_CAPTURE_TIMEOUT  seconds bounding the headed boot (default 120)
#      GDK_GODOT            the engine binary (default `godot`)
# -----------------------------------------------------------------------------

GATE_TAG="CAPTURE"
TIMEOUT_SECONDS="${GDK_CAPTURE_TIMEOUT:-120}"
PNG_SUFFIX=".png"
TRANSCRIPT_TAIL_LINES=20

usage() {
	cat <<'USAGE_EOF'
usage: capture.sh <scenario_name>
       capture.sh --help | --self-test

Boots the project WINDOWED (no --headless, so the renderer rasterizes) in a
sandboxed HOME and runs one capture scenario, which must save its PNG to
res://.capture-reports/<scenario_name>.png. This wrapper owns that directory
and clears it before every run, so what is in it afterwards came from this run.

  --self-test   prove the argument handling and the output-path precheck,
                booting nothing
  --help        this message

Env: GDK_CAPTURE_REPORT_DIR   where the PNGs land (gitignore it)
     GDK_CAPTURE_TIMEOUT      seconds bounding the boot (default 120)
     GDK_SCENARIO_SOURCE_DIR  where capture scenarios live
     GDK_SCENARIO_USER_ARG    the user arg carrying the scenario name
     GDK_RUNNERS_LIB          path to gdk_runners.sh, relative to this file
     GDK_GODOT                the engine binary (default `godot`)
Exit: 0 rendered | 1 no PNG | 2 harness/usage error
USAGE_EOF
}

# --- the output-path precheck ------------------------------------------------
# Fail FAST, before a ~30s headed boot, if the scenario does not declare the
# conventional path. The wrapper owns res://<dir>/<name>.png; a bespoke path
# (into a directory that later prunes, say) rots in silence and the run reports
# a render failure that never happened.

# scenario_file <name> <source dir> — the scenario script that answers to
# <name>, or nothing. Matched on the two spellings a runner uses: the user
# argument as written in a comment or doc, and the name returned as a
# StringName.
scenario_file() {
	local name="$1" dir="$2"
	[ -d "$dir" ] || return 0
	grep -rl -- "$GDK_SCENARIO_USER_ARG ${name}\|return &\"${name}\"" "$dir" 2>/dev/null | head -1
}

# declares_output_path <file> <name> — true when the scenario names the
# conventional PNG path. A file we cannot find is NOT a failure: an unfound
# scenario is the runner's problem to report after the boot, not a precheck's
# to guess at.
declares_output_path() {
	local file="$1" name="$2"
	[ -n "$file" ] || return 0
	grep -q "$GDK_CAPTURE_REPORT_DIR/${name}${PNG_SUFFIX}" "$file"
}

# --- --self-test -------------------------------------------------------------
self_test() {
	local scratch rc failures=0 cases=0 found

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — no scenario name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" a b >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — two names should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EMPTY name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	# The name becomes a FILE NAME under a directory this wrapper deletes
	# wholesale. `../..` must never reach that path join.
	cases=$((cases + 1))
	rc=0; bash "$0" ../escape >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — a name carrying a separator should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --self-test extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — --self-test takes no argument, got $rc" >&2; failures=$((failures + 1)); }

	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-capture-selftest.XXXXXX")" || return 1
	mkdir -p "$scratch/src"
	printf 'const OUTPUT_PNG := "res://%s/good_capture%s"\nfunc name(): return &"good_capture"\n' \
		"$GDK_CAPTURE_REPORT_DIR" "$PNG_SUFFIX" > "$scratch/src/good_capture.gd"
	printf 'const OUTPUT_PNG := "res://pm/somewhere/else.png"\nfunc name(): return &"bad_capture"\n' \
		> "$scratch/src/bad_capture.gd"

	cases=$((cases + 1))
	found="$(scenario_file good_capture "$scratch/src")"
	[ "$found" = "$scratch/src/good_capture.gd" ] \
		|| { echo "  MISS — the scenario file was not found, got '$found'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	declares_output_path "$(scenario_file good_capture "$scratch/src")" good_capture \
		|| { echo "  MISS — a conforming scenario was rejected by the precheck" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	declares_output_path "$(scenario_file bad_capture "$scratch/src")" bad_capture \
		&& { echo "  MISS — a scenario saving elsewhere passed the precheck" >&2; failures=$((failures + 1)); }

	# An unfound scenario is NOT a precheck failure: refusing here would block
	# every capture whose name this grep cannot spell, and the boot reports the
	# real problem a moment later.
	cases=$((cases + 1))
	declares_output_path "$(scenario_file nobody "$scratch/src")" nobody \
		|| { echo "  MISS — an unfound scenario was refused by the precheck" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

case "${1:-}" in
	--help|-h)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --help takes no argument" >&2; exit 2; }
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --self-test takes no argument. See --help." >&2; exit 2; }
		self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
esac
if [ "$#" -ne 1 ]; then
	echo "[$GATE_TAG] exactly one scenario name — got $#. See --help." >&2
	usage >&2
	exit 2
fi
NAME="$1"
case "$NAME" in
	''|*/*|.|..|-*)
		echo "[$GATE_TAG] '$NAME' is not a scenario name. See --help." >&2
		exit 2 ;;
esac

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

OUT="$GDK_CAPTURE_REPORT_DIR/${NAME}${PNG_SUFFIX}"

SCENARIO_FILE="$(scenario_file "$NAME" "$GDK_SCENARIO_SOURCE_DIR")"
if ! declares_output_path "$SCENARIO_FILE" "$NAME"; then
	echo "[$GATE_TAG] ${NAME} FAIL — $SCENARIO_FILE does not save to res://$OUT" >&2
	echo "          (this wrapper owns that path; fix the scenario before running)" >&2
	exit 1
fi

# user:// sandbox — a headed boot runs the same autoload stack a headless one
# does, and writes the same saves.
gdk_sandbox_home

rm -rf "${GDK_CAPTURE_REPORT_DIR:?}"
mkdir -p "$GDK_CAPTURE_REPORT_DIR"

LOG="$(gdk_sandbox_tmpfile capture.XXXXXX)"

# HEADED — deliberately NO --headless, so the renderer rasterizes. Bounded so a
# window that never closes cannot run forever. The engine's exit code is not
# the verdict: the PNG is.
gdk_run_bounded "$TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path . -- "$GDK_SCENARIO_USER_ARG" "$NAME" > "$LOG" 2>&1 || true

if [ -f "$OUT" ]; then
	echo "[$GATE_TAG] ${NAME} PASS — PNG: ${OUT}  (open it to verify the render)"
	exit 0
fi

{
	echo "[$GATE_TAG] ${NAME} FAIL — no PNG at ${OUT}."
	echo "          A capture scenario must run HEADED (this wrapper drops --headless)"
	echo "          and save_png to res://$OUT. Transcript tail:"
	echo "---- $LOG (tail) ----"
	tail -n "$TRANSCRIPT_TAIL_LINES" "$LOG"
} >&2
exit 1
