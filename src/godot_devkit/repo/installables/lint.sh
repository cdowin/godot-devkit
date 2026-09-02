#!/usr/bin/env bash
# lint.sh — the static-analysis gate: gdlint over every directory that holds
# shipping .gd source. It complements parse.sh (which compiles every script and
# boots the project) by catching what the ENGINE happily ignores:
# no-else-return, unused-argument, mixed tabs and spaces, duplicated-load,
# function-arguments-number, every *-name regex rule.
#
# Config is gdlint's own: a `gdlintrc` at the repo root. Update it in the same
# commit as the violations it cleans up, so the baseline stays green.
#
# THE SCAN SET IS DERIVED, NOT LISTED. This gate used to end in a
# hand-maintained directory list carrying a "keep in sync with the project
# layout" comment. It drifted, and a consumer's 240-script `systems/` tree —
# the declared home of every module — went unlinted for months because the list
# predated the convention. A gate that depends on somebody remembering to
# update a list is a gate that will drift, so the set is computed from git's
# own index on every run and a new top-level source dir is covered the day it
# lands. A gate that derives an EMPTY set says so and fails (it cannot tell a
# clean tree from a broken exclude).
#
# OUTPUT: one verdict line naming .gate-reports/lint.log; on a failure the
# findings are printed verbatim as well. VERBOSE=1 streams the whole run.
#
# Usage: tools/dev/runners/lint.sh   (via `make lint`)
#        tools/dev/runners/lint.sh --help | --self-test
# Exit:  0 = clean | 1 = findings | 2 = harness error (no linter, empty census,
#        or a usage mistake)
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
# The linter. `gdlint` ships with gdtoolkit.
GDK_LINT_CMD="${GDK_LINT_CMD:-gdlint}"
# Third-party code you do not own and do not style-govern, as an ERE over
# git-tracked paths. Excluded BY NAME WITH A REASON rather than by absence from
# a list — that distinction is this file's whole history. The stock value is
# the test framework this package's unit runner assumes; add your other
# vendored addons here, and note that YOUR OWN addon should stay linted.
GDK_LINT_EXCLUDE_RE="${GDK_LINT_EXCLUDE_RE:-^addons/(gut)/}"
# Top-level dirs whose CHILDREN are scanned individually rather than as one
# root, so a vendored sibling can be excluded while your own is linted.
GDK_LINT_NESTED_ROOT="${GDK_LINT_NESTED_ROOT:-addons}"
# -----------------------------------------------------------------------------

GATE_TAG="LINT"
GATE_SLOT="lint"
SCRIPT_GLOB='*.gd'
# What a reader came for on a failure: gdlint's per-finding lines and its
# closing count.
FINDING_PATTERN='Error:|^Failure:'

usage() {
	cat <<'USAGE_EOF'
usage: lint.sh [--help] [--self-test]

Runs gdlint over every top-level directory that holds tracked .gd source,
derived from git's index rather than from a list somebody maintains.

  (no argument)  lint the derived scan set
  --self-test    prove the argument handling and the scan-set derivation
                 without running a linter
  --help         this message

Env: GDK_LINT_CMD          the linter to run (default `gdlint`)
     GDK_LINT_EXCLUDE_RE   ERE of tracked paths to leave alone
     GDK_LINT_NESTED_ROOT  top-level dir whose children scan individually
     GDK_RUNNERS_LIB       path to gdk_runners.sh, relative to this file
     VERBOSE=1             stream the transcript to the console too
Exit: 0 clean | 1 findings | 2 harness/usage error
USAGE_EOF
}

# --- the scan-set derivation -------------------------------------------------
# Reads tracked .gd paths on STDIN and prints the directories to lint, one per
# line. Pure text over a path list, deliberately: it takes its input on a pipe
# rather than calling git itself, so the self-test can fire it at a fixture
# census in a checkout that has none of these directories.
lint_scan_dirs() {
	grep -Ev "$GDK_LINT_EXCLUDE_RE" \
		| awk -F/ -v nested="$GDK_LINT_NESTED_ROOT" '
			$1 == nested && NF > 2 { print $1 "/" $2; next }
			NF > 1 { print $1; next }
			{ print $1 }
		' \
		| sort -u
}

# --- --self-test -------------------------------------------------------------
# gdlint is a third-party binary and this corpus must run without it. What it
# covers is the runner's OWN logic: the argument surface, and the derivation —
# including the exclusion, the nested-root split, and the empty census that
# must never read as a clean tree.
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

	# A census that spans a nested root, a vendored exclusion, several
	# top-level trees, and a script at the repo root.
	cases=$((cases + 1))
	out="$(printf '%s\n' \
		'addons/gut/gut.gd' \
		'addons/mine/plugin.gd' \
		'autoloads/core/game.gd' \
		'systems/run/runner.gd' \
		'systems/run/policy.gd' \
		'root_script.gd' \
		| lint_scan_dirs | tr '\n' ' ')"
	[ "$out" = "addons/mine autoloads root_script.gd systems " ] \
		|| { echo "  MISS — scan-set derivation, got '$out'" >&2; failures=$((failures + 1)); }

	# The exclusion is what keeps a vendored tree out. Without it the scan set
	# grows a directory whose findings nobody can act on, and the gate reddens
	# on code the repo does not own.
	cases=$((cases + 1))
	out="$(printf '%s\n' 'addons/gut/gut.gd' | lint_scan_dirs | tr '\n' ' ')"
	[ -z "${out// /}" ] \
		|| { echo "  MISS — the vendored exclusion let '$out' through" >&2; failures=$((failures + 1)); }

	# The nested root splits per-addon; every other tree collapses to its top
	# level, so a 400-script tree is ONE gdlint argument.
	cases=$((cases + 1))
	out="$(printf '%s\n' 'systems/a/b/c/deep.gd' 'systems/x.gd' | lint_scan_dirs | tr '\n' ' ')"
	[ "$out" = "systems " ] \
		|| { echo "  MISS — a deep path must collapse to its top level, got '$out'" >&2; failures=$((failures + 1)); }

	# The cardinal case: an empty census. The gate must NOT lint the current
	# directory, and must NOT print a clean verdict — a wrong exclude and a
	# clean tree are indistinguishable, and that PASS is the dangerous one.
	cases=$((cases + 1))
	out="$(printf '' | lint_scan_dirs)"
	[ -z "$out" ] \
		|| { echo "  MISS — an empty census derived '$out'" >&2; failures=$((failures + 1)); }

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

# Sourced for the gate-output contract only — this gate boots nothing, so it
# needs no sandbox.
# shellcheck source=/dev/null
source "$LIB"

if ! command -v "$GDK_LINT_CMD" >/dev/null 2>&1; then
	echo "[$GATE_TAG] '$GDK_LINT_CMD' is not on PATH — install gdtoolkit, or set GDK_LINT_CMD." >&2
	exit 2
fi

# `while read` rather than `mapfile`: macOS ships bash 3.2.
SCAN_DIRS=()
while IFS= read -r dir; do
	[ -n "$dir" ] && SCAN_DIRS+=("$dir")
done < <(git ls-files "$SCRIPT_GLOB" 2>/dev/null | lint_scan_dirs)

if [ "${#SCAN_DIRS[@]}" -eq 0 ]; then
	echo "[$GATE_TAG] FAIL — derived an EMPTY scan set: git tracks no $SCRIPT_GLOB here," >&2
	echo "    or GDK_LINT_EXCLUDE_RE ('$GDK_LINT_EXCLUDE_RE') excluded all of them." >&2
	echo "    A gate that scanned nothing cannot tell a clean tree from a broken filter." >&2
	exit 2
fi

LOG="$(gdk_gate_log "$GATE_SLOT")"
gdk_gate_capture "$LOG" -- "$GDK_LINT_CMD" "${SCAN_DIRS[@]}"
LINT_EXIT="$GDK_GATE_EXIT"

if [ "$LINT_EXIT" -ne 0 ]; then
	grep -E "$FINDING_PATTERN" "$LOG" | sed 's/^/    /' || tail -n 20 "$LOG" | sed 's/^/    /'
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL (exit $LINT_EXIT) — ${#SCAN_DIRS[@]} source dir(s): ${SCAN_DIRS[*]}" "$LOG"
	exit 1
fi

gdk_gate_verdict "$GATE_TAG" \
	"PASS (${#SCAN_DIRS[@]} source dir(s): ${SCAN_DIRS[*]})" "$LOG"
exit 0
