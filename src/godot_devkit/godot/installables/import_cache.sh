#!/usr/bin/env bash
# import_cache.sh — regenerate Godot's `.godot` import cache, sandboxed.
# Wire it as `make import-cache`.
#
# WHY A WRAPPER EXISTS FOR A ONE-LINE FUNCTION. The rebuild is a headless
# EDITOR boot (`godot --headless --editor --quit`): it runs the project's full
# autoload stack against whatever `user://` resolves to, so it must never run
# without the HOME sandbox. The rebuild itself is `gdk_rebuild_import_cache`
# (gdk_runners.sh); this file is the sanctioned ENTRY POINT that owns
# everything around it — the sandbox home, the scratch copy, the bound, the
# outcome check, and the report. Without it the only spelling is a hand-typed
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
# THE PASS RUNS IN A COPY, NEVER IN THE TREE. An editor pass re-serialises
# authored `.tres`/`.tscn` (values normalised, `ext_resource` reordered,
# sub-resources extracted to new files). Run in the working tree, a KILLED pass
# left 100+ tracked files rewritten with nothing to undo them, and an
# `rm -rf .godot` rebuild pulled imported textures out from under a game being
# played from that checkout. So the pass runs in a scratch copy of the project
# (an APFS/reflink clone where the filesystem has one) under the sandbox runs
# dir. The copy includes Git-ignored runtime inputs (an addon a plugin manager
# installed, generated scripts, override.cfg), omits `.git` metadata, prunes
# registered nested worktrees and `.gdignore` trees, and carries `.godot/`
# separately. A copy that lacks a runtime input builds a cache for a different
# project, and the swap would install it. Only two things come back:
#   1. `.godot/` as a whole, swapped in by RENAME — a running game keeps the
#      old inodes it has open, and no reader ever sees a half-written cache.
#      The old cache is renamed INTO the scratch copy and dies with it;
#   2. `.uid` / `.import` sidecars the pass created that the tree does NOT
#      have — the point of the exercise. Commit them.
# Everything else the pass rewrote is DROPPED with the copy and reported as a
# count; the tree's own files are never written. An EXISTING sidecar the pass
# rewrote is not applied either, but it gets its own line: the new cache was
# built against the pass's version of it. (That is also why this file
# no longer restores project.godot: the tree's copy is never touched. The
# library's gdk_sandbox_home still arms its restore; here it is a no-op.)
#
# Usage: tools/dev/runners/import_cache.sh   (via `make import-cache`)
#        tools/dev/runners/import_cache.sh --help | --self-test
# Exit:  0 = cache refreshed | 1 = it was not (import failed or hit the bound)
#        2 = harness error (unusable repo, the copy failed, or a usage mistake)
#        A run killed by INT/TERM before the swap exits 130/143 and leaves the
#        tree as it was; one killed after it says so.
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
# Sidecar lists are a pointer, not a report — past this many paths, print a count.
CHURN_LIST_MAX=20
# The dropped-churn line names this many paths, then counts the rest.
DROPPED_LIST_MAX=5
# cp arguments per call when building the copy — far under any ARG_MAX.
COPY_BATCH_MAX=500
# ANCHORED: a bare `.uid` substring also matches `a.uid.tres` and `x.uidmap`,
# which are re-serialization churn, not sidecars — and the two halves of the
# report do opposite things with a path (bring back vs drop).
SIDECAR_RE='\.(uid|import)$'

if [ -t 1 ]; then C_BAD=$'\033[31m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_OFF=$'\033[0m'; else C_BAD=''; C_OK=''; C_WARN=''; C_OFF=''; fi

usage() {
	cat <<'USAGE_EOF'
usage: import_cache.sh [--help] [--self-test]

Regenerates Godot's .godot import cache through a headless editor pass, inside
the gdk_runners.sh HOME sandbox, bounded and outcome-checked. The pass runs in
a scratch copy of the project; .godot/ is swapped back in by rename and only
NEW .uid/.import sidecars are copied back. The tree's files are never written.

  (no argument)  do the rebuild
  --self-test    prove the argument handling, the outcome check and the copy
                 (a stub engine, a temp project) without booting anything
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
#
# `find -newer`, NOT the shell's `[ -nt ]`: bash 3.2 (what macOS ships)
# compares whole SECONDS, so a stamp and an artifact written inside the same
# second compare "not newer" and a genuinely refreshed cache was reported
# FAIL. The filesystems underneath keep nanosecond mtimes and find reads them.
# The direction was loud rather than silent, but a false red on a small warm
# project is still a gate nobody can trust.
# mtime_ns <path> — the file's modification time as an integer count of
# nanoseconds, on GNU (`stat -c`) and BSD/macOS (`stat -f`) alike. Empty when
# neither stat answers, so the caller can fall back rather than misread.
mtime_ns() {
	local raw ns
	raw="$(stat -c '%.9Y' "$1" 2>/dev/null)" || raw="$(stat -f '%Fm' "$1" 2>/dev/null)" || raw=''
	case "$raw" in
		*.*) ns="${raw%%.*}$(printf '%-9s' "${raw#*.}" | tr ' ' 0)" ;;
		*)   ns="${raw}000000000" ;;
	esac
	# A stat that echoed its format string, or anything else non-numeric,
	# answers nothing rather than a number the caller would compare.
	case "$ns" in *[!0-9]*|"") ns='' ;; esac
	printf '%s\n' "$ns"
}

# An artifact is fresh when it was written AT OR AFTER the stamp, compared at
# nanosecond resolution. Not `find -newer`: that is strictly-newer, and a Linux
# kernel stamps two files written in the same clock tick (~ms) with IDENTICAL
# nanoseconds — so a cache refreshed right behind the stamp read as stale, and
# the runner's self-test went red on every Linux container while macOS's fine
# clock hid it. Not `[ -nt ]` either: bash 3.2 compares whole seconds. When
# stat cannot answer at all, strictly-newer is the honest fallback.
stale_cache_artifacts() {
	local stamp="${1:?usage: stale_cache_artifacts <stamp> <artifact...>}"; shift
	local artifact stamp_ns artifact_ns
	stamp_ns="$(mtime_ns "$stamp")"
	for artifact in "$@"; do
		if [ -e "$artifact" ]; then
			artifact_ns="$(mtime_ns "$artifact")"
			if [ -n "$stamp_ns" ] && [ -n "$artifact_ns" ]; then
				[ "$artifact_ns" -lt "$stamp_ns" ] || continue
			elif [ -n "$(find "$artifact" -prune -newer "$stamp" 2>/dev/null)" ]; then
				continue
			fi
		fi
		printf '%s\n' "$artifact"
	done
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

# dropped_line <newline-separated paths> — the one line naming the churn the
# copy absorbed: a count, then the first few paths. Silent on empty input.
dropped_line() {
	local paths="$1" count first
	[ -n "$paths" ] || return 0
	count="$(printf '%s\n' "$paths" | grep -c . || true)"
	first="$(printf '%s\n' "$paths" | head -n "$DROPPED_LIST_MAX" | awk 'NR > 1 { printf ", " } { printf "%s", $0 }')"
	[ "$count" -gt "$DROPPED_LIST_MAX" ] && first="$first, … (+$((count - DROPPED_LIST_MAX)) more)"
	echo "$TAG dropped $count re-serialised files (import churn): $first"
}

# rewritten_sidecars_line <newline-separated paths> — the one line naming the
# EXISTING sidecars the pass rewrote (a duplicate uid re-minted, say). Not
# churn: the swapped-in cache was built against the pass's versions, so the
# tree and the cache now disagree, and the reader has to know which files.
# Silent on empty input.
rewritten_sidecars_line() {
	local paths="$1" count first
	[ -n "$paths" ] || return 0
	count="$(printf '%s\n' "$paths" | grep -c . || true)"
	first="$(printf '%s\n' "$paths" | head -n "$DROPPED_LIST_MAX" | awk 'NR > 1 { printf ", " } { printf "%s", $0 }')"
	[ "$count" -gt "$DROPPED_LIST_MAX" ] && first="$first, … (+$((count - DROPPED_LIST_MAX)) more)"
	echo "$TAG $count existing sidecars rewritten by the pass, NOT applied; the new cache expects them: $first"
}

# is_sidecar <path> — a `.uid`/`.import` sidecar, anchored (see SIDECAR_RE).
is_sidecar() {
	[[ "$1" =~ $SIDECAR_RE ]]
}

# --- the scratch copy --------------------------------------------------------
# pick_clone_flag <file> <dir> — the cp flag that CLONES rather than copies on
# this filesystem, proven on a real file: `--reflink=auto` (GNU, btrfs/xfs),
# `-c` (macOS, APFS clonefile). Empty means a plain copy. GNU is probed first
# because a GNU cp may read `-c` as something else.
pick_clone_flag() {
	local flag probe="$2/.gdk-clone-probe"
	for flag in --reflink=auto -c; do
		if cp "$flag" -p -- "$1" "$probe" 2>/dev/null; then
			rm -f "$probe"
			printf '%s\n' "$flag"
			return 0
		fi
		rm -f "$probe"
	done
	return 0
}

# copy_label <clone flag> — what a cp with that flag ran, said honestly. The
# probe above proves the flag is ACCEPTED, not that it cloned: GNU
# `--reflink=auto` falls back to a full copy, silently, on a filesystem that
# cannot clone (ext4). So a flag reads "clone or copy", never "clone".
copy_label() {
	if [ -n "${1-}" ]; then printf 'cp %s (clone or copy)\n' "$1"; else printf 'cp\n'; fi
}

# copy_size <dir> — how much the scratch copy holds, from `du -sk` (POSIX).
# du counts a clone's shared blocks as its own, so this is what the copy
# would have cost uncloned: the number a multi-GB project needs to see.
copy_size() {
	local kib
	kib="$(du -sk "$1" 2>/dev/null | awk '{ print $1 }')"
	case "$kib" in ''|*[!0-9]*) printf 'size unknown\n'; return 0 ;; esac
	awk -v k="$kib" 'BEGIN {
		if (k >= 1048576) printf "%.1f GiB\n", k / 1048576
		else if (k >= 1024) printf "%.1f MiB\n", k / 1024
		else printf "%d KiB\n", k
	}'
}

# project_file_list — every file under the project root, NUL-separated and
# relative to it, but `.git/`, `.godot/` (carried separately), the sandbox dir,
# registered nested Git worktrees and directories marked `.gdignore`. NOT
# git's tracked + untracked-not-ignored set: Godot reads ignored files too (a
# plugin manager's addons, generated scripts, override.cfg), and a pass that
# cannot see them writes a class registry for a different project. Ordinary
# nested clones and submodules can contain real addons, so preserve their files
# while omitting only `.git` metadata. Traverse sorted paths in Bash so these
# boundaries are checked before descending, without spawning a per-directory
# process over a large tree. copy_listed drops `.godot/` and the sandbox dir
# again whatever the list says.
project_file_list() {
	(
		shopt -s dotglob nullglob
		LC_ALL=C
		export LC_ALL
		local sandbox="${GDK_SANDBOX_DIRNAME:-.headless-userdata}"
		local project_root worktree record current entry name candidate registered
		local -a dirs=(.) entries=() worktrees=()
		local next=0
		project_root="$(pwd -P)" || return 1
		if command -v git >/dev/null 2>&1 && git -C "$project_root" rev-parse --git-common-dir >/dev/null 2>&1; then
			while IFS= read -r -d '' record; do
				case "$record" in
					'worktree '*)
						worktree="${record#worktree }"
						[ "$worktree" = "$project_root" ] && continue
						case "$worktree/" in
							"$project_root/"*) worktrees+=("$worktree") ;;
						esac
						;;
				esac
			done < <(git -C "$project_root" worktree list --porcelain -z 2>/dev/null)
		fi
		while [ "$next" -lt "${#dirs[@]}" ]; do
			current="${dirs[$next]}"
			next=$((next + 1))
			entries=("$current"/*)
			for entry in ${entries[@]+"${entries[@]}"}; do
				name="${entry##*/}"
				[ "$name" = .git ] && continue
				if [ -d "$entry" ] && [ ! -L "$entry" ]; then
					case "$entry" in
						./.git|"./$IMPORT_DIR"|"./$sandbox") continue ;;
					esac
					if [ -e "$entry/.gdignore" ] || [ -L "$entry/.gdignore" ]; then
						continue
					fi
					if [ -f "$entry/.git" ] || [ -L "$entry/.git" ]; then
						candidate="$(cd "$entry" 2>/dev/null && pwd -P)" || candidate=''
						for registered in ${worktrees[@]+"${worktrees[@]}"}; do
							if [ "$candidate" = "$registered" ]; then
								continue 2
							fi
						done
					fi
					dirs+=("$entry")
				elif [ -f "$entry" ] || [ -L "$entry" ]; then
					printf '%s\0' "$entry"
				fi
			done
		done
	)
}

# _copy_batch <dest> <dir> <path...> — one cp for paths that share a dir.
_copy_batch() {
	local dest="$1" dir="$2"; shift 2
	[ "$#" -gt 0 ] || return 0
	# `--`: a tracked root-level `-x.gd` is a path, not a flag.
	mkdir -p "$dest/$dir" && cp -R -p ${CP_CLONE:+"$CP_CLONE"} -- "$@" "$dest/$dir/"
}

# copy_listed <dest> — copy the NUL-separated paths on stdin into <dest>,
# keeping mtimes (-p: the importer compares them, and a copy with fresh mtimes
# would reimport everything). Batched per directory so a clone costs one cp
# per directory, not one per file. Prints the census; non-zero when any cp
# failed.
copy_listed() {
	local dest="${1:?usage: copy_listed <dest>}" path dir cur='' count=0 rc=0
	local -a batch=()
	if command -v rsync >/dev/null 2>&1; then
		local manifest
		manifest="$(mktemp "$dest/.gdk-import-cache-files.XXXXXX")" || return 1
		while IFS= read -r -d '' path; do
			path="${path#./}"
			path="${path%/}"
			case "$path" in
				''|"$IMPORT_DIR"|"$IMPORT_DIR"/*|"$GDK_SANDBOX_DIRNAME"|"$GDK_SANDBOX_DIRNAME"/*) continue ;;
			esac
			# A file deleted between listing and staging has nothing to copy.
			[ -e "$path" ] || [ -L "$path" ] || continue
			printf '%s\0' "$path" >> "$manifest" || rc=1
			count=$((count + 1))
		done
		if [ "$rc" -eq 0 ]; then
			rsync -rltp --from0 --files-from="$manifest" "$PWD/" "$dest/" || rc=1
		fi
		rm -f "$manifest" || rc=1
		printf '%s\n' "$count"
		return "$rc"
	fi
	while IFS= read -r -d '' path; do
		path="${path#./}"
		path="${path%/}"
		case "$path" in
			''|"$IMPORT_DIR"|"$IMPORT_DIR"/*|"$GDK_SANDBOX_DIRNAME"|"$GDK_SANDBOX_DIRNAME"/*) continue ;;
		esac
		# A file deleted between the listing and the copy has nothing to copy.
		[ -e "$path" ] || [ -L "$path" ] || continue
		case "$path" in */*) dir="${path%/*}" ;; *) dir=. ;; esac
		if [ "${#batch[@]}" -gt 0 ] && { [ "$dir" != "$cur" ] || [ "${#batch[@]}" -ge "$COPY_BATCH_MAX" ]; }; then
			_copy_batch "$dest" "$cur" "${batch[@]}" || rc=1
			batch=()
		fi
		cur="$dir"
		batch+=("$path")
		count=$((count + 1))
	done
	if [ "${#batch[@]}" -gt 0 ]; then
		_copy_batch "$dest" "$cur" "${batch[@]}" || rc=1
	fi
	printf '%s\n' "$count"
	return "$rc"
}

# fs_dev <path> — the device number of the filesystem holding <path>, GNU
# (`stat -c`) or BSD/macOS (`stat -f`). Empty when neither answers.
fs_dev() {
	local dev
	dev="$(stat -c '%d' "$1" 2>/dev/null)" || dev="$(stat -f '%d' "$1" 2>/dev/null)" || dev=''
	case "$dev" in *[!0-9]*|"") dev='' ;; esac
	printf '%s\n' "$dev"
}

# kill_tree <pid> — TERM <pid> and every descendant, children first, found by
# ppid (`ps -A -o pid= -o ppid=`, POSIX). The pass is a subshell → timeout →
# engine chain; signalling the subshell alone would orphan the engine, still
# writing into a copy that is being removed.
# shellcheck disable=SC2317,SC2329  # invoked from the exit hook and the signal trap
kill_tree() {
	local pid="$1" child
	for child in $(ps -A -o pid= -o ppid= 2>/dev/null | awk -v p="$pid" '$2 == p { print $1 }'); do
		kill_tree "$child"
	done
	kill -TERM "$pid" 2>/dev/null || true
}

# live_project_processes <engine> <root> [<root>] — read `pid args` lines on
# stdin and print the ones that are a Godot process holding THIS project: the
# command's basename is the engine's (or starts with `godot`, which is what an
# editor-launched game runs as whatever GDK_GODOT says), and one argument IS
# the root (or its project.godot). A path merely UNDER the root — this run's
# own scratch copy — does not count. Pure, so the self-test feeds it text.
#
# `ps` joins argv with spaces, so the arguments cannot be split back apart: a
# root holding a space never equalled any one field. The root is matched as
# TEXT instead — preceded by a blank, followed by the end, a blank, trailing
# slashes, or `/project.godot` — so `/r/my proj` matches whole and its scratch
# copy (`/r/my proj/.headless-userdata/…`) still does not.
live_project_processes() {
	local engine="${1:?usage: live_project_processes <engine> <root> [<root>]}"
	engine="$(basename "$engine" | tr '[:upper:]' '[:lower:]')"
	awk -v engine="$engine" -v r1="${2:?}" -v r2="${3:-$2}" '
		function base(p) { sub(/.*\//, "", p); return tolower(p) }
		function holds(s, r,   pos, p, before, after) {
			pos = 0
			while ((p = index(substr(s, pos + 1), r)) > 0) {
				p += pos; pos = p
				before = (p == 1) ? " " : substr(s, p - 1, 1)
				if (before != " " && before != "\t") continue
				after = substr(s, p + length(r))
				if (index(after, "/project.godot") == 1) after = substr(after, 15)
				else sub(/^\/+/, "", after)
				if (after == "" || after ~ /^[ \t]/) return 1
			}
			return 0
		}
		NF >= 2 {
			b = base($2)
			if (b != engine && index(b, "godot") != 1) next
			line = $0; sub(/^[ \t]+/, "", line)
			args = line; sub(/^[^ \t]+[ \t]+/, "", args)
			if (holds(args, r1) || holds(args, r2)) print line
		}
	'
}

# --- --self-test -------------------------------------------------------------
# This runner cannot be exercised against a real engine anywhere Godot is not
# installed — and it must never boot one in CI. So the corpus covers what is
# the runner's OWN logic rather than the engine's: its arguments, the outcome
# check, the report helpers, the live-process match, and the copy itself —
# the whole runner driven end to end against a STUB engine that does what an
# editor pass does to a tree (rewrites a tracked .tres, writes a new sidecar
# and the cache), in a temp project it removes.

# _st_install <proj> — lay this runner and its library out in <proj> at the
# depth REPO_ROOT_FROM_HERE says, and print the runner's path. Non-zero when
# the library cannot be found beside this file.
_st_install() {
	local proj="$1" here lib rest seg rel=''
	here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	if [ -f "$here/$GDK_RUNNERS_LIB" ]; then lib="$here/$GDK_RUNNERS_LIB"
	elif [ -f "$here/gdk_runners.sh" ]; then lib="$here/gdk_runners.sh"
	else return 1
	fi
	rest="$REPO_ROOT_FROM_HERE/"
	while [ -n "$rest" ]; do
		seg="${rest%%/*}"; rest="${rest#*/}"
		[ "$seg" = .. ] && rel="${rel}d/"
	done
	mkdir -p "$proj/$rel" "$(dirname "$proj/$rel$GDK_RUNNERS_LIB")" || return 1
	cp "${BASH_SOURCE[0]}" "$proj/${rel}import_cache.sh" || return 1
	cp "$lib" "$proj/$rel$GDK_RUNNERS_LIB" || return 1
	printf '%s\n' "$proj/${rel}import_cache.sh"
}

# _st_git <args...> — git on the temp project only: a caller's GIT_DIR (a
# commit hook sets one) would otherwise aim `add` at the real repo's index.
_st_git() {
	env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git "$@"
}

# _st_digest <proj> — every file but the sandbox dir and .git, checksummed.
_st_digest() {
	(cd "$1" && find . \( -path ./.headless-userdata -o -path ./.git \) -prune -o -type f -exec cksum {} + \
		| LC_ALL=C sort)
}

# _st_run <script> <stub> [VAR=value...] — the runner, as a consumer runs it.
# `exec`, so a caller that backgrounds this holds the RUNNER's pid — a TERM
# sent to a wrapping subshell would never reach the runner at all.
_st_run() {
	local script="$1" stub="$2"; shift 2
	exec env -u GDK_HEADLESS_HOME -u GDK_SANDBOX_DIRNAME -u GDK_PROJECT_FILE \
		-u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u STUB_MARKER \
		GDK_ENGINE_GATE_HOME="$scratch" GDK_RUNNERS_LIB="$GDK_RUNNERS_LIB" \
		GDK_GODOT="$stub" GDK_IMPORT_CACHE_TIMEOUT=60 \
		"$@" bash "$script"
}

self_test() {
	local scratch stamp out rc failures=0 cases=0
	local proj script stub before after i stub_pid census_before census_after fallback_dest

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

	# outcome check: an artifact refreshed in the SAME SECOND as the stamp is
	# fresh. No `sleep` here on purpose — that sleep is what hid the
	# whole-second `[ -nt ]` comparison from this corpus for a release.
	cases=$((cases + 1))
	: > "$stamp"
	: > "$scratch/same-second.bin"
	out="$(stale_cache_artifacts "$stamp" "$scratch/same-second.bin")"
	[ -z "$out" ] \
		|| { echo "  MISS — a cache refreshed within the stamp's second must read fresh, got '$out'" >&2; failures=$((failures + 1)); }

	# outcome check: an artifact whose mtime EQUALS the stamp's is fresh — the
	# same-tick case above made deterministic: `touch -r` copies the stamp's
	# timestamp to the nanosecond on GNU and BSD alike, so this fails on every
	# platform under a strictly-newer comparison and passes under at-or-after.
	cases=$((cases + 1))
	touch -r "$stamp" "$scratch/equal.bin"
	out="$(stale_cache_artifacts "$stamp" "$scratch/equal.bin")"
	[ -z "$out" ] \
		|| { echo "  MISS — an artifact stamped IDENTICALLY to the stamp must read fresh, got '$out'" >&2; failures=$((failures + 1)); }

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

	# the report helpers say nothing at all when there is nothing to say.
	cases=$((cases + 1))
	out="$(print_churn 'heading' ''; dropped_line '')"
	[ -z "$out" ] \
		|| { echo "  MISS — print_churn/dropped_line must be silent on empty input, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(print_churn 'sidecars' 'a.gd.uid
b.gd.uid' | head -1)"
	[ "$out" = "  sidecars (2):" ] \
		|| { echo "  MISS — print_churn heading/count, got '$out'" >&2; failures=$((failures + 1)); }

	# the sidecar split is ANCHORED: a path that merely CONTAINS '.uid' is
	# churn to drop, and bringing it back would write a re-serialised file
	# into the tree. An unanchored match put it under the wrong heading.
	cases=$((cases + 1))
	out=''
	for i in a.gd.uid scenes/a.uid.tres icon.png.import x.uidmap; do
		is_sidecar "$i" && out="$out $i"
	done
	[ "$out" = " a.gd.uid icon.png.import" ] \
		|| { echo "  MISS — the sidecar split matched the wrong paths, got '$out'" >&2; failures=$((failures + 1)); }

	# live-process warning (#23): a Godot holding the project root is named —
	# the editor-launched game whose binary is `Godot`, and an editor opened
	# on project.godot — while this run's own scratch copy (a path UNDER the
	# root), another project, and a non-engine process naming the root are not.
	cases=$((cases + 1))
	out="$(live_project_processes godot /r/proj /private/r/proj <<'PS_EOF' | awk '{ print $1 }' | tr '\n' ' '
  101 /Applications/Godot.app/Contents/MacOS/Godot --path /r/proj --remote-debug tcp://127.0.0.1:6007
  102 godot --path /r/proj/.headless-userdata/runs/run-1-import-x --headless --editor --quit
  103 vim /r/proj
  104 /usr/bin/godot --path /r/other
  105 godot4 -e /private/r/proj/project.godot
  106 /usr/bin/godot --path /r/proj/
PS_EOF
)"
	[ "$out" = "101 105 106 " ] \
		|| { echo "  MISS — live_project_processes named the wrong pids, got '$out'" >&2; failures=$((failures + 1)); }

	# ...and a root holding a SPACE: ps joins argv with blanks, so a match on
	# split fields never saw it. Its scratch copy and a longer sibling's name
	# still do not count.
	cases=$((cases + 1))
	out="$(live_project_processes godot '/r/my proj' <<'PS_EOF' | awk '{ print $1 }' | tr '\n' ' '
  201 godot --path /r/my proj --headless
  202 godot --path /r/my proj/.headless-userdata/runs/run-1-import-x --headless --editor --quit
  203 godot -e /r/my proj/project.godot
  204 godot --path /r/my project
  205 godot --path /r/my proj/
PS_EOF
)"
	[ "$out" = "201 203 205 " ] \
		|| { echo "  MISS — a root holding a space was not matched whole, got '$out'" >&2; failures=$((failures + 1)); }

	# the copy label says what ran: a clone flag is ACCEPTED by the probe, not
	# proven to clone (GNU --reflink=auto copies in full on ext4).
	cases=$((cases + 1))
	out="$(copy_label --reflink=auto)|$(copy_label -c)|$(copy_label '')"
	[ "$out" = "cp --reflink=auto (clone or copy)|cp -c (clone or copy)|cp" ] \
		|| { echo "  MISS — the copy label claimed more than ran, got '$out'" >&2; failures=$((failures + 1)); }

	# --- end to end, against a stub engine -------------------------------
	# The stub does to the copy what an editor pass does to a tree: rewrites
	# a tracked .tres, writes a new script sidecar, writes the cache. With
	# STUB_MARKER set it then records its pid and hangs, to be killed.
	stub="$scratch/bin/godot"
	mkdir -p "$scratch/bin"
	cat > "$stub" <<'STUB_EOF'
#!/bin/sh
printf 'normalised = true\n' >> data/thing.tres
printf 'uid://stubnew\n' > scripts/new.gd.uid
printf 'uid://dash\n' > ./-dash.gd.uid
# A duplicate uid re-minted: an EXISTING sidecar rewritten.
printf 'uid://reminted\n' > scripts/old.gd.uid
mkdir -p .godot
printf 'stub-uid-cache\n' > .godot/uid_cache.bin
printf 'stub-classes\n' > .godot/global_script_class_cache.cfg
# An engine registers every class_name it can SEE — a gitignored addon too.
[ ! -f addons/vendored/thing.gd ] || printf 'VendoredThing\n' >> .godot/global_script_class_cache.cfg
[ -L data/thing-link.tres ] || printf 'MissingSymlink\n' >> .godot/global_script_class_cache.cfg
[ ! -f addons/vendored/.git/config ] || printf 'VendoredGitMetadata\n' >> .godot/global_script_class_cache.cfg
[ ! -f vendor/nested-checkout/src/one.gd ] || printf 'NestedAddonSource\n' >> .godot/global_script_class_cache.cfg
[ ! -f vendor/nested-checkout/.git/config ] || printf 'NestedGitMetadata\n' >> .godot/global_script_class_cache.cfg
if [ -n "${STUB_MARKER:-}" ]; then
	printf '%s\n' "$$" > "$STUB_MARKER.tmp" && mv "$STUB_MARKER.tmp" "$STUB_MARKER"
	exec sleep 30
fi
STUB_EOF
	chmod +x "$stub"

	# An `rm` shim for the swap-cleanup case: the first rm whose target IS, or
	# directly holds, an old `.godot.old*` cache records its pid and stalls, so
	# an interrupt can land mid-delete; then it deletes for real.
	mkdir -p "$scratch/shim"
	cat > "$scratch/shim/rm" <<'SHIM_EOF'
#!/bin/sh
for a in "$@"; do
	case "$a" in -*) continue ;; esac
	if [ -n "${STUB_RM_MARKER:-}" ] && [ ! -f "$STUB_RM_MARKER" ] \
		&& [ -n "$(find "$a" -maxdepth 1 -name '.godot.old*' 2>/dev/null)" ]; then
		printf '%s\n' "$$" > "$STUB_RM_MARKER"
		sleep 2
	fi
done
exec /bin/rm "$@"
SHIM_EOF
	chmod +x "$scratch/shim/rm"

	proj="$scratch/proj"
	mkdir -p "$proj/data" "$proj/scripts" "$proj/.godot/imported" "$proj/addons/vendored" \
		"$proj/addons/vendored/.git" "$proj/vendor/nested-checkout/.git" \
		"$proj/vendor/nested-checkout/src" "$proj/vendor/engine-ignored"
	printf 'config_version=5\n' > "$proj/project.godot"
	printf '[gd_resource type="Resource"]\nvalue = 1.0\n' > "$proj/data/thing.tres"
	ln -s thing.tres "$proj/data/thing-link.tres"
	printf 'extends Node\nclass_name New\n' > "$proj/scripts/new.gd"
	printf 'extends Node\nclass_name Old\n' > "$proj/scripts/old.gd"
	printf 'uid://dupe\n' > "$proj/scripts/old.gd.uid"
	printf 'extends Node\n' > "$proj/-dash.gd"
	printf 'extends Node\nclass_name VendoredThing\n' > "$proj/addons/vendored/thing.gd"
	printf '.godot/\n.headless-userdata/\naddons/vendored/\nvendor/nested-checkout/\nvendor/worktree/\nvendor/engine-ignored/\n' > "$proj/.gitignore"
	: > "$proj/vendor/engine-ignored/.gdignore"
	printf 'ignored checkout file\n' > "$proj/vendor/nested-checkout/.git/config"
	printf 'vendored Git metadata\n' > "$proj/addons/vendored/.git/config"
	printf 'class_name NestedAddon\n' > "$proj/vendor/nested-checkout/src/one.gd"
	printf 'ignored Godot directory file\n' > "$proj/vendor/engine-ignored/one.gd"
	for i in {1..300}; do printf 'class_name IgnoredEngine%s\n' "$i" > "$proj/vendor/engine-ignored/source-$i.gd"; done
	printf 'old-uid-cache\n' > "$proj/.godot/uid_cache.bin"
	printf 'texture\n' > "$proj/.godot/imported/a.ctex"
	script="$(_st_install "$proj")"
	if [ -z "$script" ] \
		|| ! _st_git -C "$proj" init -q \
		|| ! _st_git -C "$proj" add project.godot data/thing.tres .gitignore \
		|| ! _st_git -C "$proj" -c user.name=GDK -c user.email=gdk@example.invalid commit -qm selftest \
		|| ! _st_git -C "$proj" worktree add --detach -q "$proj/vendor/worktree" HEAD; then
		echo "  MISS — could not build the end-to-end project (git, or no gdk_runners.sh beside this file)" >&2
		rm -rf "$scratch"
		echo "$TAG SELF-TEST FAIL — the end-to-end cases could not run" >&2
		return 1
	fi
	census_before="$(cd "$proj" && project_file_list | tr -cd '\000' | wc -c | tr -d '[:space:]')"
	for i in {1..300}; do
		printf 'class_name NestedWorktree%s\n' "$i" > "$proj/vendor/worktree/extra-$i.gd"
		printf 'class_name IgnoredEngine%s\n' "$i" > "$proj/vendor/engine-ignored/extra-$i.gd"
	done
	census_after="$(cd "$proj" && project_file_list | tr -cd '\000' | wc -c | tr -d '[:space:]')"
	cases=$((cases + 1))
	[ "$census_before" = "$census_after" ] \
		|| { echo "  MISS — registered worktree/.gdignore growth changed the copy census ($census_before → $census_after)" >&2; failures=$((failures + 1)); }
	census_after="$(cd "$proj" && project_file_list | tr -cd '\000' | wc -c | tr -d '[:space:]')"
	# Without rsync, the original batched cp fallback still preserves a listed
	# symlink as a link and reports the same one-path census.
	cases=$((cases + 1))
	fallback_dest="$scratch/fallback-copy"
	mkdir -p "$scratch/no-rsync" "$fallback_dest"
	ln -s "$(command -v cp)" "$scratch/no-rsync/cp"
	ln -s "$(command -v mkdir)" "$scratch/no-rsync/mkdir"
	rc=0
	out="$(cd "$proj" && GDK_SANDBOX_DIRNAME=.headless-userdata PATH="$scratch/no-rsync" CP_CLONE='' copy_listed "$fallback_dest" \
		< <(printf 'data/thing-link.tres\0'))" || rc=$?
	[ "$rc" -eq 0 ] && [ "$out" = 1 ] && [ -L "$fallback_dest/data/thing-link.tres" ] \
		|| { echo "  MISS — no-rsync fallback did not copy one symlink path (rc=$rc, census='$out')" >&2; failures=$((failures + 1)); }
	# ...and a root-level file whose name starts with a dash is a PATH to cp,
	# never a flag.
	cases=$((cases + 1))
	rc=0
	out="$(cd "$proj" && GDK_SANDBOX_DIRNAME=.headless-userdata PATH="$scratch/no-rsync" CP_CLONE='' copy_listed "$fallback_dest" \
		< <(printf -- '-dash.gd\0') 2>&1)" || rc=$?
	if [ "$rc" -ne 0 ] || [ "$out" != 1 ] || ! cmp -s "$proj/-dash.gd" "$fallback_dest/-dash.gd"; then
		echo "  MISS — no-rsync fallback read a root-level '-dash.gd' as a flag (rc=$rc, out='$out')" >&2
		failures=$((failures + 1))
	fi
	cp "$proj/data/thing.tres" "$scratch/thing.tres.orig"

	# killed mid-pass (#20): SIGTERM while the engine hangs leaves the tree
	# byte-identical — .godot/ included, nothing was swapped — no scratch
	# copy or run home behind, and no engine still running.
	cases=$((cases + 1))
	before="$(_st_digest "$proj")"
	_st_run "$script" "$stub" STUB_MARKER="$scratch/marker" >"$scratch/killed.out" 2>&1 &
	rc=$!
	for i in $(seq 1 100); do [ -f "$scratch/marker" ] && break; sleep 0.1; done
	kill -TERM "$rc" 2>/dev/null
	wait "$rc" 2>/dev/null
	stub_pid="$(cat "$scratch/marker" 2>/dev/null)"
	for i in $(seq 1 30); do { [ -n "$stub_pid" ] && kill -0 "$stub_pid" 2>/dev/null; } || break; sleep 0.1; done
	after="$(_st_digest "$proj")"
	out=''
	[ -n "$stub_pid" ] || out="$out the stub never started;"
	[ "$before" = "$after" ] || out="$out the tree changed;"
	[ -z "$(ls -A "$proj/.headless-userdata/runs" 2>/dev/null)" ] || out="$out a scratch copy or run home was left behind;"
	[ -n "$stub_pid" ] && kill -0 "$stub_pid" 2>/dev/null && { out="$out the engine outlived the run;"; kill "$stub_pid" 2>/dev/null; }
	[ -z "$out" ] \
		|| { echo "  MISS — a killed run:$out see $scratch/killed.out" >&2; cat "$scratch/killed.out" >&2; failures=$((failures + 1)); }

	# a full run: the tracked .tres is byte-identical and the dropped line
	# names it, the new sidecar came back, .godot/ is the pass's (and kept
	# what it held before — the pass is incremental), and nothing is left.
	cases=$((cases + 1))
	rc=0; out="$(_st_run "$script" "$stub" 2>&1)" || rc=$?
	i=''
	[ "$rc" -eq 0 ] || i="$i exit $rc;"
	cmp -s "$scratch/thing.tres.orig" "$proj/data/thing.tres" || i="$i the tracked .tres was written;"
	[ "$(cat "$proj/scripts/new.gd.uid" 2>/dev/null)" = 'uid://stubnew' ] || i="$i the new sidecar did not come back;"
	[ "$(cat "$proj/-dash.gd.uid" 2>/dev/null)" = 'uid://dash' ] || i="$i the new root-level '-dash.gd.uid' did not come back;"
	[ "$(cat "$proj/.godot/uid_cache.bin" 2>/dev/null)" = 'stub-uid-cache' ] || i="$i .godot/ is not the pass's;"
	[ -f "$proj/.godot/imported/a.ctex" ] || i="$i the existing cache was not carried into the copy;"
	printf '%s\n' "$out" | grep -qF "$TAG scratch copy: $census_after paths" \
		|| i="$i the copy census did not match the pruned traversal ($census_after);"
	printf '%s\n' "$out" | grep -q 'MissingSymlink' \
		&& i="$i rsync followed or lost a listed symlink;"
	printf '%s\n' "$out" | grep -qF "$TAG dropped 1 re-serialised files (import churn): data/thing.tres" \
		|| i="$i no dropped line naming data/thing.tres;"
	[ -z "$(ls -A "$proj/.headless-userdata/runs" 2>/dev/null)" ] || i="$i a scratch copy was left behind;"
	[ -z "$(cd "$proj" && ls -d "$IMPORT_DIR".old* 2>/dev/null)" ] || i="$i the old .godot/ was left behind;"
	[ -z "$i" ] \
		|| { echo "  MISS — a full run:$i output was:" >&2; printf '%s\n' "$out" >&2; failures=$((failures + 1)); }

	# the same run: an EXISTING sidecar the pass rewrote is named on its own
	# line, left as the tree had it, and never counted as import churn.
	cases=$((cases + 1))
	i=''
	[ "$(cat "$proj/scripts/old.gd.uid" 2>/dev/null)" = 'uid://dupe' ] || i="$i the rewritten sidecar was applied;"
	printf '%s\n' "$out" | grep -qxF "$TAG 1 existing sidecars rewritten by the pass, NOT applied; the new cache expects them: scripts/old.gd.uid" \
		|| i="$i no line of its own naming scripts/old.gd.uid;"
	printf '%s\n' "$out" | grep 'import churn' | grep -qF 'old.gd.uid' && i="$i it was counted as import churn;"
	[ -z "$i" ] \
		|| { echo "  MISS — a rewritten existing sidecar:$i output was:" >&2; printf '%s\n' "$out" >&2; failures=$((failures + 1)); }

	# the same run: the census line says what copied the tree and the cache,
	# and how much — never a bare flag that reads as "cloned".
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -qE "^\\$TAG scratch copy: $census_after paths by (rsync|cp( [^ ]+ \\(clone or copy\\))?) \\+ \\.godot/ by cp( [^ ]+ \\(clone or copy\\))?, [0-9.]+ (KiB|MiB|GiB) at " \
		|| { echo "  MISS — the copy census line does not say what ran and how much; output was:" >&2; printf '%s\n' "$out" >&2; failures=$((failures + 1)); }

	# GITIGNORED runtime inputs survive: an addon with its own .git metadata
	# remains importable, and ordinary nested checkout source remains present,
	# while those nested `.git` metadata files are omitted from the copy.
	cases=$((cases + 1))
	if ! grep -qx 'VendoredThing' "$proj/.godot/global_script_class_cache.cfg" 2>/dev/null \
		|| ! grep -qx 'NestedAddonSource' "$proj/.godot/global_script_class_cache.cfg" 2>/dev/null \
		|| grep -q 'GitMetadata' "$proj/.godot/global_script_class_cache.cfg" 2>/dev/null; then
		echo "  MISS — ignored addon/checkout source was lost or nested Git metadata was copied" >&2
		failures=$((failures + 1))
	fi

	# interrupted while the OLD cache is deleted (a group SIGINT — a Ctrl-C —
	# landing on the runner and the rm alike): no `.godot.old*` is left in the
	# tree, no scratch copy is left behind, and "the tree is as it was" is
	# printed only if .godot/ really is the old one. Job control (`set -m`)
	# gives the run its own process group, which is what a terminal signals.
	cases=$((cases + 1))
	printf 'old-uid-cache\n' > "$proj/.godot/uid_cache.bin"
	rm -f "$scratch/rm-marker"
	set -m
	_st_run "$script" "$stub" PATH="$scratch/shim:$PATH" STUB_RM_MARKER="$scratch/rm-marker" \
		</dev/null >"$scratch/swap.out" 2>&1 &
	rc=$!
	set +m
	for i in $(seq 1 100); do [ -f "$scratch/rm-marker" ] && break; sleep 0.1; done
	out=''
	if [ -f "$scratch/rm-marker" ]; then
		kill -INT -- -"$rc" 2>/dev/null
	else
		out="$out the old cache's delete was never reached;"
	fi
	wait "$rc" 2>/dev/null
	[ -z "$(cd "$proj" && ls -d "$IMPORT_DIR".old* 2>/dev/null)" ] || out="$out an old .godot/ was left in the tree;"
	[ -z "$(ls -A "$proj/.headless-userdata/runs" 2>/dev/null)" ] || out="$out a scratch copy was left behind;"
	if grep -q 'the tree is as it was' "$scratch/swap.out" \
		&& [ "$(cat "$proj/.godot/uid_cache.bin" 2>/dev/null)" != 'old-uid-cache' ]; then
		out="$out it said the tree is as it was after swapping .godot/;"
	fi
	[ -z "$out" ] \
		|| { echo "  MISS — interrupted during the swap cleanup:$out output was:" >&2; cat "$scratch/swap.out" >&2; failures=$((failures + 1)); }

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

# REPO_ROOT_FROM_HERE is a hardcoded depth. Installed at a different depth it
# resolves to some arbitrary ancestor, and the run would then mint a sandbox
# there and boot `--path .` in a directory that is not a Godot project — whose
# failure is reported as "the import pass hit the bound", a misdiagnosis of a
# harness error. This is the exit-2 path the usage text promises.
if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "$TAG $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	echo "$TAG REPO_ROOT_FROM_HERE ('$REPO_ROOT_FROM_HERE') is the depth from this" >&2
	echo "$TAG file to the project root; fix it, or move the runner back. See --help." >&2
	exit 2
fi

# user:// sandbox — this is the whole reason this file exists; it must come
# before any godot invocation.
gdk_sandbox_home

# The scratch copy lives under the sandbox runs dir with the run-<pid>- prefix,
# so a SIGKILLed run's copy is reaped by the next run like any abandoned home.
# The EXIT hook and the INT/TERM traps remove it on every other way out; there
# is nothing in the tree to revert, which is the point.
RUNS_DIR="$PWD/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR"
mkdir -p "$RUNS_DIR" || exit 2
COPY="$(mktemp -d "$RUNS_DIR/${GDK_SANDBOX_RUN_PREFIX}$$-import-XXXXXX")" || exit 2
PASS_PID=''
# Set once the new .godot/ is in the tree, so no message claims otherwise.
SWAPPED=''
# The old cache, when it had to be set aside BESIDE .godot/ rather than in the
# copy (the copy on another filesystem). Removed on exit like the copy.
OLD_BESIDE=''

# The removal runs with INT/TERM IGNORED — inherited by the rm, so a Ctrl-C
# landing mid-delete (seconds, on a large cache) cannot leave half a cache
# behind. It is already the way out; there is nothing left to interrupt.
# shellcheck disable=SC2317,SC2329  # invoked indirectly via gdk_on_exit
remove_copy() {
	trap '' INT TERM
	[ -z "$PASS_PID" ] || kill_tree "$PASS_PID"
	PASS_PID=''
	case "$OLD_BESIDE" in "$IMPORT_DIR".old.*) rm -rf "$OLD_BESIDE" ;; esac
	OLD_BESIDE=''
	case "$COPY" in
		*"/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR/$GDK_SANDBOX_RUN_PREFIX"*) rm -rf "$COPY" ;;
	esac
	COPY=''
}

# The engine is stopped HERE, before exit, because the EXIT hooks remove the
# run home and the copy — which a still-running pass would keep writing into.
# shellcheck disable=SC2317,SC2329  # invoked indirectly via trap
on_signal() {
	trap '' INT TERM
	[ -z "$PASS_PID" ] || kill_tree "$PASS_PID"
	PASS_PID=''
	if [ -n "$SWAPPED" ]; then
		echo "$TAG interrupted after the swap — $IMPORT_DIR/ is the refreshed one, but new sidecars may not all be back; run it again." >&2
	else
		echo "$TAG interrupted — the tree is as it was; the scratch copy is removed." >&2
	fi
	exit "$1"
}
arm_signal_traps() {
	trap 'on_signal 130' INT
	trap 'on_signal 143' TERM
}
gdk_on_exit remove_copy
arm_signal_traps

echo "${C_OK}== import-cache rebuild — headless editor pass, sandboxed, in a copy ==${C_OFF}"
echo "$TAG project: $REPO_ROOT"
echo "$TAG sandbox HOME: $HOME"

CP_CLONE="$(pick_clone_flag "$GDK_PROJECT_FILE" "$COPY")"
CACHE_METHOD="$(copy_label "$CP_CLONE")"
if command -v rsync >/dev/null 2>&1; then COPY_METHOD=rsync; else COPY_METHOD="$CACHE_METHOD"; fi
copied="$(project_file_list | copy_listed "$COPY")" || {
	echo "${C_BAD}$TAG could not build the scratch copy at $COPY${C_OFF}" >&2
	exit 2
}
if [ -d "$IMPORT_DIR" ] && ! cp -R -p ${CP_CLONE:+"$CP_CLONE"} -- "$IMPORT_DIR" "$COPY/"; then
	echo "${C_BAD}$TAG could not copy $IMPORT_DIR/ into the scratch copy${C_OFF}" >&2
	exit 2
fi
# The census: a copy without the project file is a pass over nothing.
if [ ! -f "$COPY/$GDK_PROJECT_FILE" ]; then
	echo "${C_BAD}$TAG the scratch copy holds no $GDK_PROJECT_FILE ($copied paths copied)${C_OFF}" >&2
	exit 2
fi
echo "$TAG scratch copy: $copied paths by $COPY_METHOD + ${IMPORT_DIR}/ by $CACHE_METHOD, $(copy_size "$COPY") at $COPY"
echo "$TAG regenerating $IMPORT_DIR/ (uid map + class_name registry), up to ${TIMEOUT_SECONDS}s…"

# mtime reference for the outcome check AND for what the pass wrote, taken
# after the copy (whose mtimes -p kept), inside the run home so it dies with it.
STAMP="$(gdk_sandbox_tmpfile import-cache-stamp.XXXXXX)"

# gdk_rebuild_import_cache boots `--path .`, so it runs in the copy's working
# directory. In the background and `wait`ed on, so an INT/TERM reaches
# on_signal NOW rather than after the engine exits on its own.
# A RELATIVE engine path (./bin/godot) is the tree's, and would not resolve
# from inside the copy.
case "$GDK_GODOT" in /*|'') ;; */*) GDK_GODOT="$REPO_ROOT/$GDK_GODOT" ;; esac
started_at="$(date +%s)"
( cd "$COPY" && gdk_rebuild_import_cache "$TIMEOUT_SECONDS" ) &
PASS_PID=$!
wait "$PASS_PID"
PASS_PID=''
elapsed=$(( $(date +%s) - started_at ))

stale="$(cd "$COPY" && stale_cache_artifacts "$STAMP" "${CACHE_ARTIFACTS[@]}")"

if [ -n "$stale" ]; then
	echo "${C_BAD}$TAG FAIL — the import pass did not refresh the cache (${elapsed}s):${C_OFF}"
	printf '%s\n' "$stale" | sed 's/^/      /'
	echo "  The pass either failed or hit the ${TIMEOUT_SECONDS}s bound; the tree's $IMPORT_DIR/ is untouched."
	echo "  Raise it with GDK_IMPORT_CACHE_TIMEOUT=<seconds> make import-cache,"
	echo "  or run your parse gate — its boot prints the underlying error."
	exit 1
fi

# --- what the pass wrote, sorted into brought-back and dropped ---------------
# Every file in the copy the pass wrote after the stamp: a NEW sidecar comes
# back; anything else that differs from the tree (a rewrite, or a new file
# such as an extracted sub-resource) is churn, dropped with the copy — except
# a rewritten EXISTING sidecar. That is not churn: the cache swapped in below
# was built against the pass's version, so it is not applied, and it is named
# on its own line rather than counted as churn.
sidecars=''
dropped=''
rewritten=''
while IFS= read -r rel; do
	[ -n "$rel" ] || continue
	if [ -e "$rel" ] || [ -L "$rel" ]; then
		cmp -s "$COPY/$rel" "$rel" && continue
		if is_sidecar "$rel"; then
			rewritten="$rewritten$rel"$'\n'
		else
			dropped="$dropped$rel"$'\n'
		fi
	elif is_sidecar "$rel"; then
		sidecars="$sidecars$rel"$'\n'
	else
		dropped="$dropped$rel"$'\n'
	fi
done <<WRITTEN_EOF
$(cd "$COPY" && find . -path "./$IMPORT_DIR" -prune -o -type f -newer "$STAMP" -print | sed 's|^\./||' | LC_ALL=C sort)
WRITTEN_EOF
sidecars="${sidecars%$'\n'}"
dropped="${dropped%$'\n'}"
rewritten="${rewritten%$'\n'}"

# #23: a game or editor on this project keeps running across the swap — its
# open files are the old inodes — but it will not see the new imports.
live="$(ps -A -o pid= -o args= 2>/dev/null | live_project_processes "$GDK_GODOT" "$REPO_ROOT" "$(pwd -P)")"
if [ -n "$live" ]; then
	echo "${C_WARN}$TAG WARN — a Godot process has this project open:${C_OFF}"
	printf '%s\n' "$live" | sed 's/^/      pid /'
	echo "  Swapping $IMPORT_DIR/ in anyway: it is a rename, so what that process has open stays valid."
	echo "  A running game may need a restart to see the new imports."
fi

# The swap: two renames on one filesystem, signals held off between them so no
# INT/TERM can leave the tree with no $IMPORT_DIR/ at all. The old cache goes
# INTO the scratch copy, so the exit hook that removes the copy removes it —
# with signals ignored — and a SIGKILLed run's is reaped with its copy by the
# next run. Renamed BESIDE $IMPORT_DIR/, a Ctrl-C during its delete left an
# untracked, unignored `.godot.old.<pid>/` in the tree that no run reaped.
# `mv` across filesystems silently COPIES, so the device is compared first; a
# copy on another filesystem sets the old cache aside beside $IMPORT_DIR/.
if [ -n "$(fs_dev "$COPY")" ] && [ "$(fs_dev "$COPY")" = "$(fs_dev .)" ]; then
	old="$COPY/$IMPORT_DIR.old"
else
	old="$IMPORT_DIR.old.$$"
	rm -rf "$old"
	echo "${C_WARN}$TAG the scratch copy is on another filesystem — the old $IMPORT_DIR/ is set aside at $old and removed on exit${C_OFF}"
fi
trap '' INT TERM
swap_rc=0
restored=1
# A KNOWN RACE, recorded and not locked. Two runs whose renames interleave —
# A sets the old cache aside, B finds no $IMPORT_DIR/ to set aside, A swaps
# its new one in, B's second `mv` then lands B's INSIDE A's
# ($IMPORT_DIR/$IMPORT_DIR). The engine lease does not cover it: the library
# holds the lease for the editor pass alone (gdk_engine_gate_run wraps the
# boot and releases on its exit), so two runs whose passes queued one behind
# the other still reach these renames unleased. The window is the two renames
# — microseconds — and holding the lease across them would make the swap wait
# on every other engine gate on the machine.
if [ -e "$IMPORT_DIR" ] && ! mv "$IMPORT_DIR" "$old"; then
	swap_rc=1
elif ! mv "$COPY/$IMPORT_DIR" "$IMPORT_DIR"; then
	swap_rc=1
	if [ -e "$old" ] && ! mv "$old" "$IMPORT_DIR"; then restored=0; fi
else
	SWAPPED=1
	case "$old" in "$COPY"/*) ;; *) OLD_BESIDE="$old" ;; esac
fi
if [ "$restored" -eq 0 ]; then
	# The old cache could not go back: keep it, and the copy holding it.
	COPY=''
	echo "${C_BAD}$TAG could not swap the new $IMPORT_DIR/ in, NOR put the old one back — it is at $old; move it back to $REPO_ROOT/$IMPORT_DIR${C_OFF}" >&2
	exit 2
fi
arm_signal_traps
if [ "$swap_rc" -ne 0 ]; then
	echo "${C_BAD}$TAG could not swap the new $IMPORT_DIR/ into $REPO_ROOT — the old one is in place${C_OFF}" >&2
	exit 2
fi

while IFS= read -r rel; do
	[ -n "$rel" ] || continue
	if ! { mkdir -p -- "$(dirname -- "$rel")" && cp -p -- "$COPY/$rel" "$rel"; }; then
		echo "${C_BAD}$TAG could not bring back $rel${C_OFF}" >&2
		exit 2
	fi
done <<SIDECARS_EOF
$sidecars
SIDECARS_EOF

echo "${C_OK}$TAG PASS — $IMPORT_DIR/ refreshed in ${elapsed}s${C_OFF}"

if [ -z "$sidecars" ] && [ -z "$dropped" ] && [ -z "$rewritten" ]; then
	echo "$TAG the tree is unchanged — nothing to commit, nothing to revert."
	exit 0
fi
print_churn "new sidecars brought back into the tree — COMMIT these (they are why you ran this)" "$sidecars"
rewritten_sidecars_line "$rewritten"
dropped_line "$dropped"
[ -z "$dropped" ] || echo "  (left in the scratch copy and removed with it — the tree's files were never written)"
exit 0
