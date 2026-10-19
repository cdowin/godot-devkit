#!/usr/bin/env bash
# parse.sh — native headless import, bounded and isolated from player user://.
# Godot imports assets and registers named classes, then the compile helper
# loads all scripts and boots the main scene. A 4.7.2 probe confirmed import
# alone misses an unloaded script with a syntax error, so the sweep remains.
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
# Env: GDK_PARSE_TIMEOUT bounds the import (default 300 seconds).
# -----------------------------------------------------------------------------
GATE_TAG="PARSE"
GATE_SLOT="parse"
TIMEOUT_SECONDS="${GDK_PARSE_TIMEOUT:-300}"
GDK_PARSE_SWEEP_SCRIPT="${GDK_PARSE_SWEEP_SCRIPT:-res://tools/dev/runners/compile_sweep.gd}"

usage() {
 cat <<'USAGE_EOF'
usage: parse.sh [--help] [--self-test]

Import the project, then compile every script and boot the main scene, all
inside the HOME sandbox. Fail on runtime engine errors, UID drift, missing
sweep results, nonzero exits or timeouts. Exact post-completion shutdown
resource diagnostics stay visible without changing the compile verdict. Writes import caches and sidecars normally.

Env: GDK_PARSE_TIMEOUT seconds bounding the import (default 300)
     GDK_PARSE_SWEEP_SCRIPT compile helper path
     GDK_RUNNERS_LIB   library path relative to this file
     GDK_GODOT         engine binary (default godot)
Exit: 0 clean | 1 findings | 2 harness/usage error
USAGE_EOF
}

self_test() {
	local rc failures=0 cases=0

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

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

if [ "$#" -gt 1 ]; then usage >&2; exit 2; fi
if [ "$#" -eq 1 ]; then
 case "$1" in
  --help|-h) usage; exit 0 ;;
  --self-test) self_test; exit $? ;;
  *) echo "[$GATE_TAG] unknown argument '$1'" >&2; usage >&2; exit 2 ;;
 esac
fi
case "$TIMEOUT_SECONDS" in
 ''|*[!0-9]*|0*) echo "[$GATE_TAG] GDK_PARSE_TIMEOUT must be positive whole seconds" >&2; exit 2 ;;
esac
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$GDK_RUNNERS_LIB"
if [ ! -f "$LIB" ]; then echo "[$GATE_TAG] missing library: $LIB" >&2; exit 2; fi
cd "$REPO_ROOT" || exit 2
# shellcheck source=/dev/null
source "$LIB"
if [ ! -f "$GDK_PROJECT_FILE" ]; then
 echo "[$GATE_TAG] no $GDK_PROJECT_FILE at repo root" >&2; exit 2
fi
gdk_sandbox_home
LOG="$(gdk_gate_log "$GATE_SLOT")"
# Import writes shared cache state, so exclude concurrent engine readers.
export GDK_ENGINE_GATE_WEIGHT=all
export GDK_GATE_VERDICT=FAIL
gdk_gate_capture "$LOG" -- gdk_run_bounded "$TIMEOUT_SECONDS" -- \
 "$GDK_GODOT" --path . --headless --import
ENGINE_EXIT="$GDK_GATE_EXIT"
if gdk_timeout_is_hang "$ENGINE_EXIT"; then
 GDK_GATE_VERDICT=HANG
 gdk_gate_verdict "$GATE_TAG" "FAIL (import timeout)" "$LOG"; exit 1
fi
# Classify editor and sweep output separately; keep both raw phases in the main log.
IMPORT_LOG="${LOG%.log}-import.log"
if ! cp "$LOG" "$IMPORT_LOG"; then
 gdk_gate_verdict "$GATE_TAG" "FAIL (cannot preserve import transcript)" "$LOG"; exit 1
fi
OUTPUT_STATUS=0
python3 "$(dirname "$LIB")/runners/gut_junit.py" import-output "$LOG" || OUTPUT_STATUS=$?
if [ "$ENGINE_EXIT" -ne 0 ] || [ "$OUTPUT_STATUS" -ne 0 ]; then
 gdk_gate_verdict "$GATE_TAG" "FAIL (import exit $ENGINE_EXIT; inspect engine log)" "$LOG"; exit 1
fi
export GDK_SWEEP_MAIN_SCENE=1
SWEEP_LOG="${LOG%.log}-sweep.log"
: > "$SWEEP_LOG"
gdk_gate_capture "$SWEEP_LOG" -- gdk_run_bounded "$TIMEOUT_SECONDS" -- \
 "$GDK_GODOT" --path . --headless -s "$GDK_PARSE_SWEEP_SCRIPT"
SWEEP_EXIT="$GDK_GATE_EXIT"
cat "$SWEEP_LOG" >> "$LOG"
if gdk_timeout_is_hang "$SWEEP_EXIT"; then
 GDK_GATE_VERDICT=HANG
 gdk_gate_verdict "$GATE_TAG" "FAIL (compile/boot timeout)" "$LOG"; exit 1
fi
RESULT="$(gdk_sweep_result_line "$SWEEP_LOG")"
COMPILED="$(gdk_sweep_result_field "$RESULT" 1)"
TOTAL="$(gdk_sweep_result_field "$RESULT" 2)"
OUTPUT_STATUS=0
python3 "$(dirname "$LIB")/runners/gut_junit.py" parse-output "$SWEEP_LOG" || OUTPUT_STATUS=$?
if [ "$SWEEP_EXIT" -ne 0 ] || [ "$OUTPUT_STATUS" -ne 0 ] || grep -qE '^SWEEP_FAIL ' "$SWEEP_LOG" || \
 [[ ! "$TOTAL" =~ ^[1-9][0-9]*$ ]] || [ "$COMPILED" != "$TOTAL" ]; then
 tail -40 "$LOG"
 gdk_gate_verdict "$GATE_TAG" "FAIL (compile/boot exit $SWEEP_EXIT, compiled ${COMPILED:-0}/${TOTAL:-0})" "$LOG"; exit 1
fi
GDK_GATE_VERDICT=PASS
gdk_gate_verdict "$GATE_TAG" "PASS (import, $COMPILED/$TOTAL scripts compiled, main scene booted)" "$LOG"
