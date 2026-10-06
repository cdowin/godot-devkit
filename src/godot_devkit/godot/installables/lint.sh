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
# ONE gdlint PER SCAN DIR, IN PARALLEL. gdlint is single-threaded, and one
# process over every dir linted a consumer's 419 scripts in 7.7 s on one core.
# Each dir is its own gdlint (`xargs -P`, GDK_LINT_JOBS at once); each writes
# its own file, and the transcript joins them in scan-dir order, so the log
# reads the same at any job count (#50).
#
# A SERIAL WARM-UP RUNS FIRST. gdtoolkit creates its cache dir on first use and
# races with itself when several gdlints start together on a fresh machine, so
# one gdlint over one script runs before the fan-out (#73).
#
# THE RECEIPT KEYS ON WHAT gdlint READS: every *.gd and the config
# (`gdlintrc` / `.gdlintrc` at the root), plus the settings below. A .tres or
# .tscn edit reuses the receipt; it once re-linted every script (#50).
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
# How many gdlint processes run at once. Default: the core count.
GDK_LINT_JOBS="${GDK_LINT_JOBS:-}"
# -----------------------------------------------------------------------------

GATE_TAG="LINT"
GATE_SLOT="lint"
SCRIPT_GLOB='*.gd'
# What a reader came for on a failure: gdlint's per-finding lines and its
# closing count.
FINDING_PATTERN='Error:|^Failure:'
# The files gdlint reads, as an ERE for the receipt key (GDK_RECEIPT_MATCH in
# gdk_runners.sh): every script, and gdlint's config at the repo root.
LINT_INPUT_RE='[.]gd$|^[.]?gdlintrc$'

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
     GDK_LINT_JOBS         gdlint processes at once (default: core count, capped
                           by a container CPU quota)
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

# --- one gdlint per dir, in parallel ------------------------------------------
# lint_dirs <dir>... — run "$GDK_LINT_CMD" once per dir, GDK_LINT_JOBS (set
# and checked by the main flow) at a time. Prints each dir's output in argument order and returns the first
# non-zero gdlint exit in that order (0 when every dir is clean). xargs is
# POSIX; -0 and -P are in both the BSD (macOS) and GNU builds.
# shellcheck disable=SC2329  # invoked through gdk_gate_capture
lint_dirs() {
	local out i rc=0 one
	out="$(mktemp -d "${TMPDIR:-/tmp}/gdk-lint.XXXXXX")" || return 2
	# One dir: $0 the linter, $1 its index, $2 the dir. The inner sh expands.
	# shellcheck disable=SC2016
	local per_dir='"$0" "$2" > "$GDK_LINT_OUT/$1.log" 2>&1; echo "$?" > "$GDK_LINT_OUT/$1.rc"'
	i=0
	for one in "$@"; do
		printf '%s\0%s\0' "$i" "$one"
		i=$((i + 1))
	done | GDK_LINT_OUT="$out" xargs -0 -n 2 -P "$GDK_LINT_JOBS" sh -c "$per_dir" "$GDK_LINT_CMD"
	i=0
	for one in "$@"; do
		cat "$out/$i.log" 2>/dev/null
		one="$(cat "$out/$i.rc" 2>/dev/null || echo 2)"
		[ "$rc" -ne 0 ] || rc="$one"
		i=$((i + 1))
	done
	rm -rf "$out"
	return "$rc"
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

if [ -z "$GDK_LINT_JOBS" ]; then
	GDK_LINT_JOBS="$(gdk_cpu_count)"
fi
case "$GDK_LINT_JOBS" in
	''|*[!0-9]*|0)
		echo "[$GATE_TAG] GDK_LINT_JOBS must be a whole number above 0, got '$GDK_LINT_JOBS'" >&2
		exit 2 ;;
esac

# A receipt over these exact inputs is the proof already bought (gdk_runners.sh,
# proof receipts).
# The key reads only what gdlint reads (LINT_INPUT_RE), plus the settings
# that choose what it lints.
# shellcheck disable=SC2034  # read by gdk_receipt_key, in the sourced library
GDK_RECEIPT_MATCH="$LINT_INPUT_RE"
RECEIPT_ARGS=("$GDK_LINT_CMD" "$GDK_LINT_EXCLUDE_RE" "$GDK_LINT_NESTED_ROOT")
RECEIPT_KEY="$(gdk_receipt_key lint "${RECEIPT_ARGS[@]}")" || RECEIPT_KEY=""
if gdk_receipt_hit lint "$RECEIPT_KEY"; then
	exit 0
fi

# WARM gdtoolkit's CACHE BEFORE THE FAN-OUT (#73). gdlint checks for its
# grammar-cache dir and then makedirs it; on a fresh machine (every CI runner)
# the parallel runs below race, and the loser fails with "Cannot open file
# '<first .gd>': File exists". One serial run over one tracked script creates
# the cache first. Its result is ignored: a finding in that script is reported
# by the real run.
WARM_FILE="$(git ls-files "$SCRIPT_GLOB" 2>/dev/null | grep -Ev "$GDK_LINT_EXCLUDE_RE" | head -n 1)"
if [ -n "$WARM_FILE" ]; then
	"$GDK_LINT_CMD" "$WARM_FILE" >/dev/null 2>&1 || true
fi

LOG="$(gdk_gate_log "$GATE_SLOT")"
# The outcome the cost row files (gdk_runners.sh, THE COST ROW). FAIL until the
# one PASS below says otherwise.
export GDK_GATE_VERDICT=FAIL
gdk_gate_capture "$LOG" -- lint_dirs "${SCAN_DIRS[@]}"
LINT_EXIT="$GDK_GATE_EXIT"

if [ "$LINT_EXIT" -ne 0 ]; then
	grep -E "$FINDING_PATTERN" "$LOG" | sed 's/^/    /' || tail -n 20 "$LOG" | sed 's/^/    /'
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL (exit $LINT_EXIT) — ${#SCAN_DIRS[@]} source dir(s): ${SCAN_DIRS[*]}" "$LOG"
	exit 1
fi

GDK_GATE_VERDICT=PASS
gdk_gate_verdict "$GATE_TAG" \
	"PASS (${#SCAN_DIRS[@]} source dir(s): ${SCAN_DIRS[*]})" "$LOG"
gdk_receipt_write lint "$RECEIPT_KEY" "[$GATE_TAG] PASS (${#SCAN_DIRS[@]} source dir(s): ${SCAN_DIRS[*]})" "${RECEIPT_ARGS[@]}"
exit 0
