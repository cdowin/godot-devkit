#!/usr/bin/env bash
# spot.sh — the builder's spot check: gdlint and a compile of ONLY the .gd
# files the change touched. `make spot SYS=<slice>` runs this, then the unit
# slice; the two together are a builder's whole proof, under 30 s on a quiet
# machine. The wide tiers (parse, warnings, integration) are the integrator's,
# run once per batch.
#
# THE CHANGE is every .gd that differs from the merge base of HEAD and
# GDK_SPOT_BASE (`make spot BASE=<ref>`, default `main`): committed, staged
# and unstaged edits, plus untracked files. A deleted file is not in it.
# GDK_LINT_EXCLUDE_RE (lint.sh's) drops vendored code.
#
# NO CHANGED .gd IS A PASS, and the verdict says so: `census 0`, naming the
# base. A change to scenes or data only has no script for this check to read,
# and the unit slice after it still runs.
#
# The compile is compile_sweep.gd with the list as user arguments, so it loads
# those scripts and walks nothing else. A PASS files a receipt (gdk_runners.sh,
# proof receipts): the same change checked again boots nothing.
#
# OUTPUT: one verdict line naming .gate-reports/spot.log; on a failure the
# findings are printed verbatim as well. VERBOSE=1 streams the whole run.
#
# Usage: tools/dev/runners/spot.sh   (via `make spot`)
#        tools/dev/runners/spot.sh --help | --self-test
# Exit:  0 = clean, or no .gd changed | 1 = findings | 2 = harness error (no
#        linter, no merge base, or a usage mistake)
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
# The branch this change is cut from. `make spot BASE=<ref>` sets it.
GDK_SPOT_BASE="${GDK_SPOT_BASE:-main}"
# The linter and the vendored-code exclusion, as lint.sh reads them.
GDK_LINT_CMD="${GDK_LINT_CMD:-gdlint}"
GDK_LINT_EXCLUDE_RE="${GDK_LINT_EXCLUDE_RE:-^addons/(gut)/}"
# The sweep script parse.sh runs, addressed the same way.
GDK_PARSE_SWEEP_SCRIPT="${GDK_PARSE_SWEEP_SCRIPT:-res://tools/dev/runners/compile_sweep.gd}"
# Env: GDK_SPOT_TIMEOUT  seconds bounding the compile (default 120)
#      GDK_GODOT         the engine binary (default `godot`)
# -----------------------------------------------------------------------------

GATE_TAG="SPOT"
GATE_SLOT="spot"
TIMEOUT_SECONDS="${GDK_SPOT_TIMEOUT:-120}"
# What a reader came for on a failure: gdlint's findings, and the engine lines
# that say why a script did not compile.
LINT_FINDING_PATTERN='Error:|^Failure:'
SWEEP_DIAGNOSTIC_PATTERN='SCRIPT ERROR: Parse Error|Failed to load script|Compile Error|at: GDScript::reload'

usage() {
	cat <<'USAGE_EOF'
usage: spot.sh [--help] [--self-test]

The builder's spot check: gdlint, then a compile, over only the .gd files
that differ from the merge base of HEAD and GDK_SPOT_BASE (untracked files
count). No changed .gd is a PASS with census 0.

  (no argument)  check the change
  --self-test    prove the argument handling and the change-set derivation
                 without running a linter or an engine
  --help         this message

Env: GDK_SPOT_BASE           the branch the change is cut from (default main)
     GDK_LINT_CMD            the linter to run (default `gdlint`)
     GDK_LINT_EXCLUDE_RE     ERE of paths to leave alone
     GDK_PARSE_SWEEP_SCRIPT  res:// path to compile_sweep.gd
     GDK_SPOT_TIMEOUT        seconds bounding the compile (default 120)
     GDK_RUNNERS_LIB         path to gdk_runners.sh, relative to this file
     GDK_GODOT               the engine binary (default `godot`)
     VERBOSE=1               stream the transcript to the console too
Exit: 0 clean or nothing changed | 1 findings | 2 harness/usage error
USAGE_EOF
}

# --- the change set ----------------------------------------------------------
# spot_scripts — changed paths on stdin; the .gd ones to check out, sorted,
# once each, less the exclusion. Pure text, so the self-test can fire it at a
# fixture list.
spot_scripts() {
	grep -E '\.gd$' | grep -Ev "$GDK_LINT_EXCLUDE_RE" | sort -u
}

# spot_res_paths — repo-relative paths on stdin; the res:// spelling the sweep
# takes as user arguments out.
spot_res_paths() {
	sed 's|^|res://|'
}

# --- --self-test -------------------------------------------------------------
self_test() {
	local rc out failures=0 cases=0

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

	# A change that spans a scene, a vendored script, a script named twice
	# (edited and untracked never both, but a diff and a listing can overlap)
	# and two of the project's own.
	cases=$((cases + 1))
	out="$(printf '%s\n' \
		'scenes/main.tscn' \
		'addons/gut/gut.gd' \
		'systems/run/runner.gd' \
		'systems/run/runner.gd' \
		'tests/unit/test_runner.gd' \
		'systems/run/runner.gd.uid' \
		| spot_scripts | tr '\n' ' ')"
	[ "$out" = "systems/run/runner.gd tests/unit/test_runner.gd " ] \
		|| { echo "  MISS — change-set derivation, got '$out'" >&2; failures=$((failures + 1)); }

	# A scene-only change derives nothing — the census-0 PASS, never a lint of
	# the whole tree.
	cases=$((cases + 1))
	out="$(printf '%s\n' 'scenes/main.tscn' 'data/clean.tres' | spot_scripts)"
	[ -z "$out" ] || { echo "  MISS — a scene-only change derived '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(printf '%s\n' 'systems/a.gd' 'b.gd' | spot_res_paths | tr '\n' ' ')"
	[ "$out" = "res://systems/a.gd res://b.gd " ] \
		|| { echo "  MISS — the res:// spelling, got '$out'" >&2; failures=$((failures + 1)); }

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

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

# shellcheck source=/dev/null
source "$LIB"

if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "[$GATE_TAG] $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	exit 2
fi
case "$TIMEOUT_SECONDS" in
	''|*[!0-9]*|0) echo "[$GATE_TAG] GDK_SPOT_TIMEOUT='$TIMEOUT_SECONDS' — expected whole seconds above 0" >&2; exit 2 ;;
esac

if ! BASE_SHA="$(git merge-base HEAD "$GDK_SPOT_BASE" 2>/dev/null)"; then
	echo "[$GATE_TAG] no merge base between HEAD and '$GDK_SPOT_BASE' — set BASE= (GDK_SPOT_BASE) to the branch this change is cut from" >&2
	exit 2
fi
BASE_NOTE="merge-base ${BASE_SHA:0:12} with $GDK_SPOT_BASE"

# Relative to the project root (the cwd), as res:// is; the bytes, never git's
# C-quoting. `while read`, not `mapfile`: macOS ships bash 3.2.
FILES=()
while IFS= read -r f; do
	[ -f "$f" ] && FILES+=("$f")
done < <({ git -c core.quotePath=false diff --name-only --relative --diff-filter=d "$BASE_SHA" -- '*.gd' 2>/dev/null
	git -c core.quotePath=false ls-files --others --exclude-standard -- '*.gd' 2>/dev/null; } | spot_scripts)

LOG=""
if [ "${#FILES[@]}" -eq 0 ]; then
	LOG="$(gdk_gate_log "$GATE_SLOT")"
	echo "no .gd differs from $BASE_NOTE" >> "$LOG"
	export GDK_GATE_VERDICT=PASS GDK_GATE_CENSUS=0
	gdk_gate_verdict "$GATE_TAG" "PASS — census 0: no .gd changed vs $BASE_NOTE" "$LOG"
	exit 0
fi

if ! command -v "$GDK_LINT_CMD" >/dev/null 2>&1; then
	echo "[$GATE_TAG] '$GDK_LINT_CMD' is not on PATH — install gdtoolkit, or set GDK_LINT_CMD." >&2
	exit 2
fi

RECEIPT_KEY="$(gdk_receipt_key spot "$BASE_SHA" "$GDK_LINT_CMD")" || RECEIPT_KEY=""
if gdk_receipt_hit spot "$RECEIPT_KEY"; then
	exit 0
fi

LOG="$(gdk_gate_log "$GATE_SLOT")"
# The outcome the cost row files (gdk_runners.sh, THE COST ROW). FAIL until the
# one PASS below says otherwise.
export GDK_GATE_VERDICT=FAIL GDK_GATE_CENSUS="${#FILES[@]}"
printf 'the change: %s file(s) vs %s\n' "${#FILES[@]}" "$BASE_NOTE" >> "$LOG"
printf '    %s\n' "${FILES[@]}" >> "$LOG"

# --- Stage 1: gdlint over the change -----------------------------------------
gdk_gate_capture "$LOG" -- "$GDK_LINT_CMD" "${FILES[@]}"
LINT_EXIT="$GDK_GATE_EXIT"

# --- Stage 2: compile the change, and nothing else ---------------------------
# Run even when lint failed: a builder wants both findings from one pass.
gdk_sandbox_home
RES_PATHS=()
while IFS= read -r p; do RES_PATHS+=("$p"); done < <(printf '%s\n' "${FILES[@]}" | spot_res_paths)
gdk_gate_capture "$LOG" -- gdk_run_bounded "$TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path . --headless -s "$GDK_PARSE_SWEEP_SCRIPT" -- "${RES_PATHS[@]}"
SWEEP_EXIT="$GDK_GATE_EXIT"

FINDINGS=""
if [ "$LINT_EXIT" -ne 0 ]; then
	echo "[$GATE_TAG] gdlint (exit $LINT_EXIT):"
	grep -E "$LINT_FINDING_PATTERN" "$LOG" | sed 's/^/    /' || true
	FINDINGS="lint"
fi
if gdk_timeout_is_hang "$SWEEP_EXIT"; then
	GDK_GATE_VERDICT=HANG
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL — the compile exceeded ${TIMEOUT_SECONDS}s, killed${FINDINGS:+; $FINDINGS failed too}" "$LOG"
	exit 1
fi
RESULT_LINE="$(gdk_sweep_result_line "$LOG")"
if [ -z "$RESULT_LINE" ]; then
	echo "[$GATE_TAG] the compile produced no result line; it cannot prove anything compiled."
	echo "    Is $GDK_PARSE_SWEEP_SCRIPT where GDK_PARSE_SWEEP_SCRIPT says it is?"
	tail -n 20 "$LOG" | sed 's/^/    /'
	gdk_gate_verdict "$GATE_TAG" "FAIL (no compile result)${FINDINGS:+; $FINDINGS failed too}" "$LOG"
	exit 1
fi
COMPILED="$(gdk_sweep_result_field "$RESULT_LINE" 1)"
TOTAL="$(gdk_sweep_result_field "$RESULT_LINE" 2)"
FAILED_PATHS="$(gdk_sweep_failed_paths "$LOG")"
# The census: the sweep read exactly the list it was given, or it proved
# something other than the change.
if [ "$TOTAL" != "${#FILES[@]}" ]; then
	echo "[$GATE_TAG] the compile read $TOTAL script(s); the change has ${#FILES[@]}."
	FINDINGS="${FINDINGS:+$FINDINGS, }census"
fi
if [ -n "$FAILED_PATHS" ]; then
	echo "[$GATE_TAG] ${COMPILED}/${TOTAL} changed scripts compiled; these did not:"
	printf '%s\n' "$FAILED_PATHS" | sed 's/^/    /'
	grep -E "$SWEEP_DIAGNOSTIC_PATTERN" "$LOG" | sed 's/^/    /' || true
	FINDINGS="${FINDINGS:+$FINDINGS, }compile"
fi

if [ -n "$FINDINGS" ]; then
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL ($FINDINGS) — ${#FILES[@]} changed .gd vs $BASE_NOTE; ${COMPILED}/${TOTAL} compiled" "$LOG"
	exit 1
fi

GDK_GATE_VERDICT=PASS
SAID="PASS (${#FILES[@]} changed .gd vs $BASE_NOTE: lint clean, ${COMPILED}/${TOTAL} compiled)"
gdk_gate_verdict "$GATE_TAG" "$SAID" "$LOG"
gdk_receipt_write spot "$RECEIPT_KEY" "[$GATE_TAG] $SAID" "$BASE_SHA" "$GDK_LINT_CMD"
exit 0
