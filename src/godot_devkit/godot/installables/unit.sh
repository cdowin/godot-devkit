#!/usr/bin/env bash
# unit.sh — bounded, sandboxed GUT; JUnit proves every selected script ran.
set -uo pipefail

GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
GDK_GUT_CMDLN="${GDK_GUT_CMDLN:-res://addons/gut/gut_cmdln.gd}"
GDK_GUT_CONFIG="${GDK_GUT_CONFIG-res://.gutconfig.json}"
GDK_GUT_DEFAULT_DIR="${GDK_GUT_DEFAULT_DIR:-tests/unit}"
GDK_GUT_GATE_TAG="${GDK_GUT_GATE_TAG:-UNIT}"
GDK_GUT_GATE_SLOT="${GDK_GUT_GATE_SLOT:-unit}"
GDK_UNIT_TIMEOUT="${GDK_UNIT_TIMEOUT:-180}"

usage() {
	cat <<'USAGE_EOF'
usage: unit.sh [GUT options...] | --help | --self-test

Runs GUT under the project config (default res://.gutconfig.json). GUT options
pass through; -gtest= and -gdir= select scripts. JUnit proves every selected
script loaded and at least one test ran. An empty GDK_GUT_CONFIG disables the
config. GDK_UNIT_TIMEOUT bounds the engine run in seconds.
USAGE_EOF
}

case "${1:-}" in
	--help|-h) [ "$#" -eq 1 ] || exit 2; usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || exit 2
		bash -n "$0" || exit 1
		echo "[$GDK_GUT_GATE_TAG] SELF-TEST OK — 1 case(s)"
		exit 0 ;;
esac
case "$GDK_UNIT_TIMEOUT" in
	''|*[!0-9]*|0) echo "[$GDK_GUT_GATE_TAG] timeout must be positive seconds" >&2; exit 2 ;;
esac
GDIR_OVERRIDE=()
for arg in "$@"; do
	case "$arg" in
		'') echo "[$GDK_GUT_GATE_TAG] empty GUT option; see --help" >&2; exit 2 ;;
		-gconfig*|-gjunit_xml_file*|-gjunit_xml_timestamp*|-gexit*|-gerrors_do_not_cause_failure*)
			echo "[$GDK_GUT_GATE_TAG] $arg is controlled by this gate" >&2; exit 2 ;;
		-gtest|-gtest=*) GDIR_OVERRIDE=(-gdir=) ;;
	esac
done
RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$RUNNER_DIR/../../.." && pwd)" || exit 2
LIB="$RUNNER_DIR/$GDK_RUNNERS_LIB"
[ -f "$LIB" ] || { echo "[$GDK_GUT_GATE_TAG] gdk_runners.sh not found" >&2; exit 2; }
cd "$REPO_ROOT" || exit 2
# shellcheck source=/dev/null
source "$LIB"
[ -f "$GDK_PROJECT_FILE" ] || { echo "[$GDK_GUT_GATE_TAG] project.godot not found" >&2; exit 2; }
[ -f "$RUNNER_DIR/gut_junit.py" ] || { echo "[$GDK_GUT_GATE_TAG] gut_junit.py not installed" >&2; exit 2; }
python3 "$RUNNER_DIR/gut_junit.py" validate "$GDK_GUT_CONFIG" >/dev/null || exit 2

LOG="$(gdk_gate_log "$GDK_GUT_GATE_SLOT")"
JUNIT="${LOG%.log}.xml"
rm -f -- "$JUNIT"
case "$JUNIT" in /*) JUNIT_ARG="$JUNIT" ;; *) JUNIT_ARG="res://$JUNIT" ;; esac

gdk_sandbox_home
RAW="$(gdk_run_bounded "$GDK_UNIT_TIMEOUT" -- \
	"$GDK_GODOT" --path . --headless -s "$GDK_GUT_CMDLN" \
	-gconfig="$GDK_GUT_CONFIG" -gjunit_xml_file="$JUNIT_ARG" \
	-gexit ${GDIR_OVERRIDE[@]+"${GDIR_OVERRIDE[@]}"} "$@" 2>&1)"
STATUS=$?
gdk_gate_publish "$LOG" "$RAW"
if gdk_timeout_is_hang "$STATUS"; then
	gdk_gate_verdict "$GDK_GUT_GATE_TAG" "HANG (${GDK_UNIT_TIMEOUT}s)" "$LOG"
	exit 2
fi
CENSUS="$(python3 "$RUNNER_DIR/gut_junit.py" "$JUNIT" "$GDK_GUT_CONFIG" "$GDK_GUT_DEFAULT_DIR" \
	${GDIR_OVERRIDE[@]+"${GDIR_OVERRIDE[@]}"} "$@" 2>&1)"
CENSUS_STATUS=$?
OUTPUT_STATUS=0
python3 "$RUNNER_DIR/gut_junit.py" output "$LOG" || OUTPUT_STATUS=$?
if [ "$STATUS" -ne 0 ] || [ "$CENSUS_STATUS" -ne 0 ] || [ "$OUTPUT_STATUS" -ne 0 ]; then
	printf '%s\n' "$CENSUS" | sed 's/^/  /'
	gdk_gate_verdict "$GDK_GUT_GATE_TAG" "FAIL (GUT exit $STATUS; $CENSUS)" "$LOG"
	exit 1
fi
gdk_gate_verdict "$GDK_GUT_GATE_TAG" "PASS ($CENSUS)" "$LOG"
