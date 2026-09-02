#!/usr/bin/env bash
# import_cache.sh — regenerate Godot's `.godot` import cache, sandboxed.
# Wire it as `make import-cache`.
#
# WHY A WRAPPER EXISTS FOR A ONE-LINE FUNCTION. The rebuild is a headless
# EDITOR boot (`godot --headless --editor --quit`): it runs the project's full
# autoload stack against whatever `user://` resolves to, so it must never run
# without the HOME sandbox. The rebuild itself is `gdk_rebuild_import_cache`
# (gdk_runners.sh); this file is the sanctioned ENTRY POINT that owns
# everything around it — the sandbox home, the bound, the outcome check, and
# the tree-churn report. Without it the only spelling is a hand-typed
# `source gdk_runners.sh && gdk_rebuild_import_cache`, whose sandbox depends on
# the typist ALSO remembering `gdk_sandbox_home` first — and a developer duly
# ran the unsandboxed half against live player data. The engine-boot guard
# (`tools/hooks/cc-godot-sandbox.sh`) blocks that spelling; this is the one it
# points at.
#
# WHEN YOU NEED IT:
#   - a NEW `class_name` script — the global class registry and the script's
#     sibling `.gd.uid` are not written until an editor import pass runs. A
#     parse gate does NOT do it, and a test runner hides the resulting error.
#   - after adding / deleting / moving `.tscn` / `.tres` / asset files.
#   - a cold checkout with no `.godot/` (otherwise the parse gate fails with a
#     cascade of "Failed to instantiate an autoload").
#   - `invalid UID … using text path instead` warnings on a cold run.
#   - after editing a `.png`/`.tres` asset, before a screenshot capture —
#     otherwise the capture renders the OLD art.
#
# THE PASS WRITES INTO THE TREE, in two very different ways, so the run ends by
# listing them apart:
#   - `.uid` sidecars for new scripts — the point of the exercise. Commit them.
#   - re-serialized `.tres`/`.tscn`/`project.godot` with no semantic change —
#     churn. Diff it, then revert it; never commit it.
#
# Usage: tools/dev/runners/import_cache.sh   (via `make import-cache`)
#        tools/dev/runners/import_cache.sh --help | --self-test
# Exit:  0 = cache refreshed | 1 = it was not (import failed or hit the bound)
#        2 = harness error (unusable repo, or a usage mistake)
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
# LIB is where `godot-devkit install-runners` put gdk_runners.sh, relative to
# THIS file. The stock layout is tools/dev/runners/import_cache.sh beside
# tools/dev/gdk_runners.sh.
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
# Depth from this file to the repo root, for the stock layout above.
REPO_ROOT_FROM_HERE="../../.."
# Env: GDK_IMPORT_CACHE_TIMEOUT  seconds to bound the editor pass (default 300)
# -----------------------------------------------------------------------------

TAG="[import-cache]"
IMPORT_DIR=".godot"
# The two artifacts everything downstream reads: the uid map (`uid://` → path)
# and the `class_name` global registry. The pass rewrites BOTH, so either one
# still older than this run means the pass did not do its job — an outcome
# check that holds even though gdk_rebuild_import_cache swallows godot's exit
# code (it is a best-effort recovery step for its other caller).
CACHE_ARTIFACTS=("$IMPORT_DIR/uid_cache.bin" "$IMPORT_DIR/global_script_class_cache.cfg")
# A cold, full import of a real project runs well past the 60s the library
# default assumes.
TIMEOUT_SECONDS="${GDK_IMPORT_CACHE_TIMEOUT:-300}"
# Churn lists are a pointer, not a report — past this many paths, print a count.
CHURN_LIST_MAX=20
UID_SIDECAR_SUFFIX=".uid"

if [ -t 1 ]; then C_BAD=$'\033[31m'; C_OK=$'\033[32m'; C_OFF=$'\033[0m'; else C_BAD=''; C_OK=''; C_OFF=''; fi

usage() {
	cat <<'USAGE_EOF'
usage: import_cache.sh [--help] [--self-test]

Regenerates Godot's .godot import cache through a headless editor pass, inside
the gdk_runners.sh HOME sandbox, bounded and outcome-checked.

  (no argument)  do the rebuild
  --self-test    prove the argument handling and the outcome check without
                 booting anything
  --help         this message

Env: GDK_IMPORT_CACHE_TIMEOUT  seconds to bound the editor pass (default 300)
     GDK_RUNNERS_LIB           path to gdk_runners.sh, relative to this file
Exit: 0 refreshed | 1 not refreshed | 2 harness/usage error
USAGE_EOF
}

# --- the outcome check -------------------------------------------------------
# gdk_rebuild_import_cache swallows the engine's exit code, so the ONLY honest
# evidence the pass did its job is that every artifact came out NEWER than a
# stamp taken before it started. A missing artifact is as stale as an old one.
#
# Pure over the filesystem and free of the boot, which is what lets the
# self-test below fire it at fake files in CI.
#
# stale_cache_artifacts <stamp> <artifact...> — print every artifact that is
# missing or not newer than <stamp>, one per line. Empty output means the pass
# refreshed everything.
stale_cache_artifacts() {
	local stamp="${1:?usage: stale_cache_artifacts <stamp> <artifact...>}"; shift
	local artifact
	for artifact in "$@"; do
		[ -e "$artifact" ] && [ "$artifact" -nt "$stamp" ] && continue
		printf '%s\n' "$artifact"
	done
}

# git_dirty_paths — the worktree's changed paths, one per line (empty when git
# is unavailable, so a non-git checkout degrades to "no churn report" rather
# than to a failure).
git_dirty_paths() {
	git status --porcelain 2>/dev/null | sed 's/^...//' || true
}

# print_churn <heading> <newline-separated paths>
print_churn() {
	local heading="$1" paths="$2" count
	[ -n "$paths" ] || return 0
	count="$(printf '%s\n' "$paths" | grep -c . || true)"
	echo "  $heading ($count):"
	printf '%s\n' "$paths" | head -n "$CHURN_LIST_MAX" | sed 's/^/      /'
	[ "$count" -gt "$CHURN_LIST_MAX" ] && echo "      … and $((count - CHURN_LIST_MAX)) more"
	return 0
}

# --- --self-test -------------------------------------------------------------
# This runner cannot be exercised end to end anywhere Godot is not installed —
# and it must never boot one in CI. So the corpus covers the two things that
# are the runner's OWN logic rather than the engine's: how it reads its
# arguments, and whether the outcome check tells a refreshed cache from a stale
# one. Both run against fake files in a scratch dir it removes.
self_test() {
	local scratch stamp out rc failures=0 cases=0

	# argument handling: --help is 0, an unknown argument is a usage error (2).
	cases=$((cases + 1))
	rc=0; usage >/dev/null || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — 'import_cache.sh --help' should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --what >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an unknown argument should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --help extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EXTRA argument should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-import-cache-selftest.XXXXXX")" || return 1

	# outcome check: a MISSING artifact is stale.
	cases=$((cases + 1))
	stamp="$scratch/stamp"; : > "$stamp"
	out="$(stale_cache_artifacts "$stamp" "$scratch/absent.bin")"
	[ "$out" = "$scratch/absent.bin" ] \
		|| { echo "  MISS — a missing artifact must be reported stale, got '$out'" >&2; failures=$((failures + 1)); }

	# outcome check: an artifact OLDER than the stamp is stale.
	cases=$((cases + 1))
	: > "$scratch/old.bin"
	sleep 1
	: > "$stamp"
	out="$(stale_cache_artifacts "$stamp" "$scratch/old.bin")"
	[ "$out" = "$scratch/old.bin" ] \
		|| { echo "  MISS — an artifact older than the stamp must be stale, got '$out'" >&2; failures=$((failures + 1)); }

	# outcome check: an artifact NEWER than the stamp is fresh — and the whole
	# roster fresh means empty output, which is what the runner reads as PASS.
	cases=$((cases + 1))
	sleep 1
	: > "$scratch/new.bin"; : > "$scratch/also-new.bin"
	out="$(stale_cache_artifacts "$stamp" "$scratch/new.bin" "$scratch/also-new.bin")"
	[ -z "$out" ] \
		|| { echo "  MISS — refreshed artifacts must report nothing stale, got '$out'" >&2; failures=$((failures + 1)); }

	# outcome check: ONE stale artifact out of two is still a failed pass —
	# the case a check that only looked at uid_cache.bin would wave through.
	cases=$((cases + 1))
	out="$(stale_cache_artifacts "$stamp" "$scratch/new.bin" "$scratch/old.bin")"
	[ "$out" = "$scratch/old.bin" ] \
		|| { echo "  MISS — a partial refresh must name the stale artifact, got '$out'" >&2; failures=$((failures + 1)); }

	# the churn report splits sidecars from re-serialized files, and says
	# nothing at all when there is no churn.
	cases=$((cases + 1))
	out="$(print_churn 'heading' '')"
	[ -z "$out" ] \
		|| { echo "  MISS — print_churn must be silent on empty input, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(print_churn 'sidecars' 'a.gd.uid
b.gd.uid' | head -1)"
	[ "$out" = "  sidecars (2):" ] \
		|| { echo "  MISS — print_churn heading/count, got '$out'" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "$TAG SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "$TAG SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

# The whole argument surface: nothing, --help, or --self-test. An extra
# argument is refused rather than ignored — a caller passing one believes this
# takes options it does not.
if [ "$#" -gt 1 ]; then
	echo "$TAG one argument at most — got $#" >&2
	usage >&2
	exit 2
fi
# `$# -eq 1` rather than a `''` case branch: an EMPTY argument is a caller
# passing an unset variable, not a caller passing nothing, and running the
# rebuild on it would hide their bug behind a boot.
if [ "$#" -eq 1 ]; then
	case "$1" in
		--help|-h) usage; exit 0 ;;
		--self-test) self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
		*) echo "$TAG unknown argument '$1'" >&2; usage >&2; exit 2 ;;
	esac
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$GDK_RUNNERS_LIB"
if [ ! -f "$LIB" ]; then
	echo "$TAG gdk_runners.sh not found at '$LIB' — set GDK_RUNNERS_LIB" >&2
	exit 2
fi
cd "$REPO_ROOT" || exit 2

# Shared sandbox / bounded-run contract.
# shellcheck source=/dev/null
source "$LIB"

# user:// sandbox — this is the whole reason this file exists; it must come
# before any godot invocation.
gdk_sandbox_home

before_dirty="$(git_dirty_paths)"

# mtime reference for the outcome check, inside the run home so it dies with it.
STAMP="$(gdk_sandbox_tmpfile import-cache-stamp.XXXXXX)"

echo "${C_OK}== import-cache rebuild — headless editor pass, sandboxed ==${C_OFF}"
echo "$TAG project: $REPO_ROOT"
echo "$TAG sandbox HOME: $HOME"
echo "$TAG regenerating $IMPORT_DIR/ (uid map + class_name registry), up to ${TIMEOUT_SECONDS}s…"

started_at="$(date +%s)"
gdk_rebuild_import_cache "$TIMEOUT_SECONDS"
elapsed=$(( $(date +%s) - started_at ))

stale="$(stale_cache_artifacts "$STAMP" "${CACHE_ARTIFACTS[@]}")"

if [ -n "$stale" ]; then
	echo "${C_BAD}$TAG FAIL — the import pass did not refresh the cache (${elapsed}s):${C_OFF}"
	printf '%s\n' "$stale" | sed 's/^/      /'
	echo "  The pass either failed or hit the ${TIMEOUT_SECONDS}s bound."
	echo "  Raise it with GDK_IMPORT_CACHE_TIMEOUT=<seconds> make import-cache,"
	echo "  or run your parse gate — its boot prints the underlying error."
	exit 1
fi

echo "${C_OK}$TAG PASS — $IMPORT_DIR/ refreshed in ${elapsed}s${C_OFF}"

# --- what the pass wrote into the TREE ---------------------------------------
# Only paths this run made dirty: a tree that was already dirty is the caller's
# business, and reporting it as churn would send them to revert their own work.
after_dirty="$(git_dirty_paths)"
new_dirty="$(comm -13 \
	<(printf '%s\n' "$before_dirty" | sort -u) \
	<(printf '%s\n' "$after_dirty" | sort -u) | grep . || true)"

if [ -z "$new_dirty" ]; then
	echo "$TAG the tree is unchanged — nothing to commit, nothing to revert."
	exit 0
fi

sidecars="$(printf '%s\n' "$new_dirty" | grep -F -- "$UID_SIDECAR_SUFFIX" || true)"
churn="$(printf '%s\n' "$new_dirty" | grep -vF -- "$UID_SIDECAR_SUFFIX" || true)"

echo "$TAG the pass wrote into the tree:"
print_churn "uid sidecars — COMMIT these (they are why you ran this)" "$sidecars"
print_churn "re-serialized by the importer — DIFF, then 'git checkout --' them" "$churn"
exit 0
