#!/usr/bin/env bash
# capture.sh — run one headed GUT screenshot test and require a fresh PNG.
set -uo pipefail

GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
GDK_CAPTURE_TEST_ROOT="${GDK_CAPTURE_TEST_ROOT:-tests/capture}"
GDK_CAPTURE_REPORT_DIR="${GDK_CAPTURE_REPORT_DIR:-.capture-reports}"
GDK_CAPTURE_POSITION="${GDK_CAPTURE_POSITION:-100000,100000}"
GDK_CAPTURE_TIMEOUT="${GDK_CAPTURE_TIMEOUT:-120}"
GDK_GUT_CMDLN="${GDK_GUT_CMDLN:-res://addons/gut/gut_cmdln.gd}"
GDK_GUT_CONFIG="${GDK_GUT_CONFIG-res://.gutconfig.json}"

usage() {
	cat <<'USAGE_EOF'
usage: capture.sh <name> | --help | --self-test

Runs tests/capture/test_<name>.gd through GUT with a visible
renderer. The test saves res://.capture-reports/<name>.png. A previous PNG
moves to .capture-reports/previous/ before the run; no PNG or no GUT tests is
a failure. CAPTURE_VISIBLE=1 shows the window on screen.
USAGE_EOF
}

case "${1:-}" in
	--help|-h)
		[ "$#" -eq 1 ] || exit 2
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || exit 2
		bash -n "$0" || exit 1
		echo '[CAPTURE] SELF-TEST OK — 1 case(s)'
		exit 0 ;;
esac
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
NAME="$1"
case "$NAME" in
	''|*[!a-zA-Z0-9_-]*|-*) echo "[CAPTURE] invalid test name '$NAME'; see --help" >&2; exit 2 ;;
esac
case "$GDK_CAPTURE_TIMEOUT" in
	''|*[!0-9]*|0) echo '[CAPTURE] GDK_CAPTURE_TIMEOUT must be positive seconds' >&2; exit 2 ;;
esac
case "${CAPTURE_VISIBLE:-0}" in
	0)
		[[ "$GDK_CAPTURE_POSITION" =~ ^-?[0-9]+,-?[0-9]+$ ]] || {
			echo '[CAPTURE] GDK_CAPTURE_POSITION must be x,y' >&2; exit 2;
		}
		POSITION_ARGS=(--position "$GDK_CAPTURE_POSITION") ;;
	1) POSITION_ARGS=() ;;
	*) echo '[CAPTURE] CAPTURE_VISIBLE must be 0 or 1' >&2; exit 2 ;;
esac

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$RUNNER_DIR/../../.." && pwd)" || exit 2
LIB="$RUNNER_DIR/$GDK_RUNNERS_LIB"
[ -f "$LIB" ] || { echo '[CAPTURE] gdk_runners.sh not found' >&2; exit 2; }
cd "$REPO_ROOT" || exit 2
# shellcheck source=/dev/null
source "$LIB"
[ -f "$GDK_PROJECT_FILE" ] || { echo '[CAPTURE] project.godot not found' >&2; exit 2; }
if ! DEFECT="$(gdk_report_dir_defect "$GDK_CAPTURE_REPORT_DIR")"; then
	echo "[CAPTURE] GDK_CAPTURE_REPORT_DIR $DEFECT" >&2
	exit 2
fi
TEST="$GDK_CAPTURE_TEST_ROOT/test_$NAME.gd"
[ -f "$TEST" ] || { echo "[CAPTURE] no test at $TEST" >&2; exit 1; }
[ -f "$RUNNER_DIR/gut_junit.py" ] || { echo '[CAPTURE] gut_junit.py not installed' >&2; exit 2; }
python3 "$RUNNER_DIR/gut_junit.py" validate "$GDK_GUT_CONFIG" >/dev/null || exit 2
OUT="$GDK_CAPTURE_REPORT_DIR/$NAME.png"
mkdir -p "$GDK_CAPTURE_REPORT_DIR/previous" || exit 2
if [ -f "$OUT" ]; then
	mv -f "$OUT" "$GDK_CAPTURE_REPORT_DIR/previous/$NAME.png" || exit 2
fi

gdk_sandbox_home
LOG="$(gdk_gate_log capture)"
JUNIT="${LOG%.log}.xml"
rm -f -- "$JUNIT"
case "$JUNIT" in /*) JUNIT_ARG="$JUNIT" ;; *) JUNIT_ARG="res://$JUNIT" ;; esac
RAW="$(gdk_run_bounded "$GDK_CAPTURE_TIMEOUT" -- \
	"$GDK_GODOT" --path . ${POSITION_ARGS[@]+"${POSITION_ARGS[@]}"} -s "$GDK_GUT_CMDLN" \
	-gconfig="$GDK_GUT_CONFIG" -gdir= -gtest="res://$TEST" -gexit \
	-gjunit_xml_file="$JUNIT_ARG" 2>&1)"
STATUS=$?
gdk_gate_publish "$LOG" "$RAW"
if gdk_timeout_is_hang "$STATUS"; then
	gdk_gate_verdict CAPTURE "HANG (${GDK_CAPTURE_TIMEOUT}s)" "$LOG"
	exit 2
fi
CENSUS="$(python3 "$RUNNER_DIR/gut_junit.py" "$JUNIT" "$GDK_GUT_CONFIG" "$GDK_CAPTURE_TEST_ROOT" \
	-gdir= "-gtest=res://$TEST" 2>&1)"
CENSUS_STATUS=$?
if [ "$STATUS" -ne 0 ] || [ ! -f "$OUT" ] || [ "$CENSUS_STATUS" -ne 0 ] || \
	printf '%s\n' "$RAW" | grep -Eq 'SCRIPT ERROR: Parse Error|Failed to load script|^ERROR:'; then
	gdk_gate_verdict CAPTURE "FAIL ($NAME: engine=$STATUS, $CENSUS, PNG=$OUT)" "$LOG"
	exit 1
fi
gdk_gate_verdict CAPTURE "PASS ($NAME: $CENSUS, PNG=$OUT)" "$LOG"
