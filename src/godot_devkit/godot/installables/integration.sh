#!/usr/bin/env bash
# integration.sh — GUT's second config, optionally one process per test file.
set -uo pipefail

GDK_GUT_INTEGRATION_CONFIG="${GDK_GUT_INTEGRATION_CONFIG-res://.gutconfig.integration.json}"
GDK_INTEGRATION_PER_FILE="${GDK_INTEGRATION_PER_FILE:-0}"
GDK_JOBS="${GDK_JOBS:-2}"
RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$RUNNER_DIR/../../.." && pwd)" || exit 2

usage() {
	cat <<'USAGE_EOF'
usage: integration.sh [GUT options...] | --help | --self-test

Runs GUT's integration config (default res://.gutconfig.integration.json).
GDK_INTEGRATION_PER_FILE=1 gives each test script a fresh sandboxed engine
process; GDK_JOBS bounds concurrent files. GUT options pass through in the
single-process mode.
USAGE_EOF
}
case "${1:-}" in
	--help|-h) [ "$#" -eq 1 ] || exit 2; usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || exit 2
		bash -n "$0" || exit 1
		echo '[INTEGRATION] SELF-TEST OK — 1 case(s)'
		exit 0 ;;
esac
export GDK_GUT_CONFIG="$GDK_GUT_INTEGRATION_CONFIG"
export GDK_GUT_DEFAULT_DIR=tests/integration
export GDK_GUT_GATE_TAG=INTEGRATION
export GDK_GUT_GATE_SLOT=integration
if [ "$GDK_INTEGRATION_PER_FILE" = 0 ]; then
	exec bash "$RUNNER_DIR/unit.sh" "$@"
fi
[ "$GDK_INTEGRATION_PER_FILE" = 1 ] || { echo '[INTEGRATION] GDK_INTEGRATION_PER_FILE must be 0 or 1' >&2; exit 2; }
case "$GDK_JOBS" in ''|*[!0-9]*|0) echo '[INTEGRATION] GDK_JOBS must be positive' >&2; exit 2 ;; esac
[ "$#" -eq 0 ] || { echo '[INTEGRATION] GUT options require single-process mode' >&2; exit 2; }
cd "$REPO_ROOT" || exit 2
[ -f "$RUNNER_DIR/gut_junit.py" ] || { echo '[INTEGRATION] gut_junit.py not installed' >&2; exit 2; }
FILES="$(python3 "$RUNNER_DIR/gut_junit.py" list "$GDK_GUT_CONFIG" "$GDK_GUT_DEFAULT_DIR")" || exit 1
WORK="$(mktemp -d "${TMPDIR:-/tmp}/gdk-integration.XXXXXX")" || exit 2
trap 'rm -rf "$WORK"' EXIT
pids=()
count=0
fail=0
while IFS= read -r file; do
	[ -n "$file" ] || continue
	count=$((count + 1))
	(
		export GDK_GUT_GATE_SLOT="integration-$count"
		bash "$RUNNER_DIR/unit.sh" "-gtest=res://$file" > "$WORK/$count.log" 2>&1
	) &
	pids+=("$!")
	if [ "${#pids[@]}" -ge "$GDK_JOBS" ]; then
		wait "${pids[0]}" || fail=$((fail + 1))
		pids=("${pids[@]:1}")
	fi
done <<< "$FILES"
for pid in ${pids[@]+"${pids[@]}"}; do wait "$pid" || fail=$((fail + 1)); done
[ "$count" -gt 0 ] || { echo '[INTEGRATION] no test files selected' >&2; exit 1; }
# Publish all worker output in roster order. One top-level verdict names it.
# shellcheck source=/dev/null
source "$RUNNER_DIR/../gdk_runners.sh"
LOG="$(gdk_gate_log integration)"
for ((i=1; i<=count; i++)); do cat "$WORK/$i.log" >> "$LOG"; done
if [ "$fail" -ne 0 ]; then
	grep -E 'FAIL|HANG' "$LOG" | tail -5 || true
	gdk_gate_verdict INTEGRATION "FAIL ($fail/$count file(s))" "$LOG"
	exit 1
fi
gdk_gate_verdict INTEGRATION "PASS ($count file(s))" "$LOG"
