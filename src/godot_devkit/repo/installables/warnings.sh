#!/usr/bin/env bash
# warnings.sh — the GDScript-analyzer gate: the editor-only warnings parse.sh
# and lint.sh both miss.
#
# Godot does NOT print analyzer warnings (SHADOWED_VARIABLE / UNUSED_SIGNAL /
# INTEGER_DIVISION / STANDALONE_EXPRESSION) to stdout during any normal
# headless invocation — they live in the editor's analyzer panel. The only
# headless mechanism that surfaces them is to PROMOTE THEM TO ERRORS (`…=2` in
# the project settings) and run a full editor import pass, which then prints
# each as:
#
#   SCRIPT ERROR: Parse Error: <message>. (Warning treated as error.)
#       at: GDScript::reload (res://path/to/file.gd:NN)
#
# This runner builds a THROWAWAY project root (symlinks back to the repo plus a
# patched copy of project.godot and a seeded .godot cache), runs the import pass
# against THAT, and reads the output for the promotion marker. The working tree
# is never written to, so concurrent runs cannot collide — the earlier design
# appended the promotion block to the REAL project.godot and restored it from a
# snapshot, and with two agents in one tree the [debug] blocks stacked and the
# blind restore reverted a legitimate concurrent edit.
#
# THE CATEGORY LIST IS DELIBERATELY NARROW. The broad analyzer set
# (untyped_declaration, unsafe_*, …) trips thousands of pre-existing lines in
# any real project. Grow GDK_WARNING_CATEGORIES only alongside the commit that
# clears the surface it adds.
#
# OUTPUT: one verdict line naming .gate-reports/warnings.log; on a failure
# every promoted-warning line verbatim. A clean editor import runs to ~1,500
# lines, which is exactly why it lives in the file. VERBOSE=1 streams it.
#
# Usage: tools/dev/runners/warnings.sh   (via `make warnings`)
#        tools/dev/runners/warnings.sh --help | --self-test
# Exit:  0 = clean | 1 = a promoted warning fired | 2 = harness/usage error
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
# The warning classes promoted to errors, space separated. The stock six are
# the four that a playtest proved escape parse + lint, plus each one's
# same-bug-class sibling.
GDK_WARNING_CATEGORIES="${GDK_WARNING_CATEGORIES:-shadowed_variable shadowed_variable_base_class unused_signal integer_division standalone_expression standalone_ternary}"
# Env: GDK_WARNINGS_TIMEOUT  seconds bounding the editor import pass (default 300)
#      GDK_GODOT             the engine binary (default `godot`)
# -----------------------------------------------------------------------------

GATE_TAG="WARNINGS"
GATE_SLOT="warnings"
# Value 2 = "treat as error" in Godot's warning levels (0 ignore, 1 warn).
WARNING_AS_ERROR=2
WARNING_SETTING_PREFIX="gdscript/warnings/"
PROMOTION_SECTION="[debug]"
PROMOTION_MARKER="Warning treated as error"
IMPORT_DIR=".godot"
# Seeded from the repo's cache so the pass does not re-import the whole art
# tree — and, critically, does not write fresh *.import files back through the
# symlinks into the real source tree. The two caches deliberately NOT seeded
# (editor/ and global_script_class_cache.cfg) are what force every script to be
# re-analyzed with the promotion active.
SEEDED_CACHES=(imported uid_cache.bin scene_groups_cache.cfg shader_cache)
RUN_DIR_PREFIX="gdk-warnings"
TIMEOUT_SECONDS="${GDK_WARNINGS_TIMEOUT:-300}"

usage() {
	cat <<'USAGE_EOF'
usage: warnings.sh [--help] [--self-test]

Promotes a narrow set of GDScript analyzer warnings to errors in a throwaway
mirror of the project and runs one headless editor import pass against it.
The working tree is never written to.

  (no argument)  run the pass
  --self-test    prove the argument handling and the promotion block without
                 booting anything
  --help         this message

Env: GDK_WARNING_CATEGORIES  space-separated warning classes to promote
     GDK_WARNINGS_TIMEOUT    seconds bounding the import pass (default 300)
     GDK_RUNNERS_LIB         path to gdk_runners.sh, relative to this file
     GDK_GODOT               the engine binary (default `godot`)
     VERBOSE=1               stream the transcript to the console too
Exit: 0 clean | 1 promoted warnings fired | 2 harness/usage error
USAGE_EOF
}

# --- the promotion block -----------------------------------------------------
# project.godot is ConfigFile format, so a fresh [debug] section appended to a
# COPY is merged on load. Pure text, so the self-test can read it without an
# engine: this is the one thing the runner writes that decides what the gate
# actually looks for, and a silently-empty block is a permanently-green gate.
promotion_block() {
	local category
	printf '\n%s\n\n' "$PROMOTION_SECTION"
	# shellcheck disable=SC2086  # deliberate word split: the list is space separated
	for category in $GDK_WARNING_CATEGORIES; do
		printf '%s%s=%s\n' "$WARNING_SETTING_PREFIX" "$category" "$WARNING_AS_ERROR"
	done
}

# --- the per-run mirror ------------------------------------------------------
# Named with THIS run's pid, and every run first reaps the ones whose owner is
# gone — the pid is what keeps the reap off a CONCURRENT run's live mirror, the
# same device the library's sandbox homes use.
reap_dead_run_mirrors() {
	local dir="${1:?usage: reap_dead_run_mirrors <tmp root>}" entry base pid
	for entry in "$dir/$RUN_DIR_PREFIX".*; do
		[ -e "$entry" ] || continue
		base="${entry##*/}"
		pid="${base#"$RUN_DIR_PREFIX".}"; pid="${pid%%.*}"
		# A stray carrying no numeric field is by definition abandoned.
		case "$pid" in ''|*[!0-9]*) rm -rf "$entry"; continue ;; esac
		gdk_pid_is_live "$pid" && continue
		rm -rf "$entry"
	done
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

	# The block opens a [debug] section and promotes EVERY configured category
	# — one line each, at level 2. A block missing a category is a gate that
	# silently stopped looking for it.
	cases=$((cases + 1))
	out="$(promotion_block | grep -c "^${WARNING_SETTING_PREFIX}.*=${WARNING_AS_ERROR}$")"
	[ "$out" = "$(printf '%s' "$GDK_WARNING_CATEGORIES" | wc -w | tr -d ' ')" ] \
		|| { echo "  MISS — the promotion block covers $out of the configured categories" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	promotion_block | grep -qxF "$PROMOTION_SECTION" \
		|| { echo "  MISS — the promotion block opens no $PROMOTION_SECTION section" >&2; failures=$((failures + 1)); }

	# Level 2 is the whole mechanism: at level 1 the analyzer warns and the
	# import pass exits clean, so the gate would pass over every warning there
	# is. Nothing else in the file would notice.
	cases=$((cases + 1))
	out="$(promotion_block | grep -c "=1$")"
	[ "$out" = "0" ] \
		|| { echo "  MISS — $out categories were promoted below error level" >&2; failures=$((failures + 1)); }

	# An empty category list produces a block that promotes nothing — a gate
	# that can only ever pass. Refused up front rather than run.
	cases=$((cases + 1))
	out="$(GDK_WARNING_CATEGORIES='' promotion_block | grep -c "^${WARNING_SETTING_PREFIX}")"
	[ "$out" = "0" ] \
		|| { echo "  MISS — an empty category list still promoted $out setting(s)" >&2; failures=$((failures + 1)); }

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

# Shared sandbox / bounded-run / gate-output contract.
# shellcheck source=/dev/null
source "$LIB"

if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "[$GATE_TAG] $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	echo "[$GATE_TAG] REPO_ROOT_FROM_HERE ('$REPO_ROOT_FROM_HERE') is the depth from" >&2
	echo "[$GATE_TAG] this file to the project root; fix it, or move the runner back." >&2
	exit 2
fi

# Rule 4, at the top: a gate configured to look for nothing must refuse, not
# report a clean tree.
if [ -z "${GDK_WARNING_CATEGORIES// /}" ]; then
	echo "[$GATE_TAG] GDK_WARNING_CATEGORIES is empty — this gate would promote nothing" >&2
	echo "    and could only ever pass. Name the classes you want promoted." >&2
	exit 2
fi

# user:// sandbox — the editor import boot must never touch real player data.
gdk_sandbox_home

LOG="$(gdk_gate_log "$GATE_SLOT")"

TMP_ROOT="${TMPDIR:-/tmp}"
reap_dead_run_mirrors "$TMP_ROOT"
RUN_DIR="$(mktemp -d "$TMP_ROOT/$RUN_DIR_PREFIX.$$.XXXXXX")" || exit 2

# NEVER a bare `trap … EXIT` here — it would clobber the sandbox home's own
# self-destruct hook. See gdk_runners.sh's gdk_on_exit.
gdk_on_exit "rm -rf '$RUN_DIR'"

# Mirror every top-level repo entry except the two this run owns: the project
# file (a patched copy) and .godot (a seeded cache). .git is skipped — the
# import pass has no business walking it.
for entry in "$REPO_ROOT"/* "$REPO_ROOT"/.[!.]*; do
	[ -e "$entry" ] || continue
	name="$(basename "$entry")"
	case "$name" in
		"$GDK_PROJECT_FILE"|"$IMPORT_DIR"|.git) continue ;;
	esac
	ln -s "$entry" "$RUN_DIR/$name"
done

mkdir -p "$RUN_DIR/$IMPORT_DIR"
for cache in "${SEEDED_CACHES[@]}"; do
	[ -e "$IMPORT_DIR/$cache" ] || continue
	# clonefile (APFS) when available — a 50 MB copy per run otherwise.
	cp -Rc "$IMPORT_DIR/$cache" "$RUN_DIR/$IMPORT_DIR/$cache" 2>/dev/null \
		|| cp -R "$IMPORT_DIR/$cache" "$RUN_DIR/$IMPORT_DIR/$cache"
done

{
	cat "$GDK_PROJECT_FILE"
	promotion_block
} > "$RUN_DIR/$GDK_PROJECT_FILE"

# A full editor import pass is the only headless path that runs the analyzer
# over every script. --quit exits once the import completes.
gdk_gate_capture "$LOG" -- gdk_run_bounded "$TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path "$RUN_DIR" --headless --editor --quit
IMPORT_EXIT="$GDK_GATE_EXIT"

if gdk_timeout_is_hang "$IMPORT_EXIT"; then
	gdk_gate_verdict "$GATE_TAG" \
		"FAIL — the import pass exceeded ${TIMEOUT_SECONDS}s, killed" "$LOG"
	exit 1
fi

if grep -qF "$PROMOTION_MARKER" "$LOG"; then
	echo "[$GATE_TAG] FAIL — GDScript analyzer warnings detected:"
	grep -A1 -F "$PROMOTION_MARKER" "$LOG" \
		| grep -E "$PROMOTION_MARKER|res://.*\.gd:" | sed 's/^/    /' || true
	gdk_gate_verdict "$GATE_TAG" "FAIL" "$LOG"
	exit 1
fi

gdk_gate_verdict "$GATE_TAG" \
	"PASS (promoted: ${GDK_WARNING_CATEGORIES})" "$LOG"
exit 0
