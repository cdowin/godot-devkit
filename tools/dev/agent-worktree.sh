#!/usr/bin/env bash
# agent-worktree.sh — the single sanctioned way to create and tear down
# per-agent git worktrees: a real checkout each (own dir, index, build cache),
# sharing only the object store.
#   new [--no-warm] <slug> [base]  branch <BRANCH_PREFIX><slug> + worktree at
#                                  <WORKTREE_PARENT>/<slug>, caches pre-warmed,
#                                  scope marker written; prints the absolute path
#   done <slug>                    carry appended CARRY_ROWS rows to the main
#                                  checkout, refuse on any other uncommitted
#                                  work, keep a branch merged into neither its
#                                  base nor the mainline, then remove worktree
#                                  and branch
#   list                           active worktrees, cross-checked with git
# Run from anywhere in the repo. `set -uo pipefail`, no -e: exit codes are read.
set -uo pipefail

MAIN_ROOT="$(git rev-parse --show-toplevel)"

# --- project config (yours to edit after install — the file is your repo's) --
WORKTREE_PARENT=".claude/worktrees"   # repo-relative; gitignore it
BRANCH_PREFIX="feat/"
SCOPE_MARKER=".agent-scope"           # the marker the installed hooks read
# Gitignored cache dirs copied from the main tree to pre-warm a worktree.
WARM_DIRS=()
# Gitignored per-asset sidecars to mirror (e.g. "*.import"); empty = off.
WARM_SIDECAR_GLOB=""
# Where an agent branches from when no milestone declares one; empty = origin/HEAD.
FALLBACK_BASE=""
# The PM CLI as `make pm`; a project calling the CLI directly replaces the array.
PM_CMD=(make -s pm)
# Append-only row files (a glob; `*` spans directories) whose uncommitted rows
# `done` appends to the same path in the main checkout rather than refusing on.
# Keep in step with `[pm] roadmap_dir`.
CARRY_ROWS="pm/roadmap/*.jsonl"
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p WORKTREE_PARENT >/dev/null 2>&1 || WORKTREE_PARENT=".claude/worktrees"
declare -p BRANCH_PREFIX >/dev/null 2>&1 || BRANCH_PREFIX="feat/"
declare -p SCOPE_MARKER >/dev/null 2>&1 || SCOPE_MARKER=".agent-scope"
declare -p WARM_DIRS >/dev/null 2>&1 || WARM_DIRS=()
declare -p WARM_SIDECAR_GLOB >/dev/null 2>&1 || WARM_SIDECAR_GLOB=""
declare -p FALLBACK_BASE >/dev/null 2>&1 || FALLBACK_BASE=""
declare -p PM_CMD >/dev/null 2>&1 || PM_CMD=(make -s pm)
declare -p CARRY_ROWS >/dev/null 2>&1 || CARRY_ROWS="pm/roadmap/*.jsonl"

# An empty FALLBACK_BASE is READ from the remote's HEAD, never guessed. A remote
# with no HEAD (a `git remote add`, not a clone) leaves the name `origin/HEAD`,
# which `new` then refuses by name.
if [ -z "$FALLBACK_BASE" ]; then
	FALLBACK_BASE="$(git symbolic-ref --short -q refs/remotes/origin/HEAD 2>/dev/null)"
	[ -n "$FALLBACK_BASE" ] || FALLBACK_BASE="origin/HEAD"
fi

# integration_branch [toplevel] — the ACTIVE milestone's integration branch, or
# nothing. Asked of the CLI by CATEGORY, never grepped from milestone.md, so a
# renamed status word still matches. Exactly one milestone declaring a non-trunk
# branch is the answer; two or more is ambiguous and yields nothing. "Answered"
# is the CLI's census line, not the exit code: `make pm` with no Makefile exits
# 0 saying nothing.
integration_branch() {
	local root="${1:-$MAIN_ROOT}"
	local ask="list --kind milestone --category in_progress"
	local out line _id _status _cat branch _rest found="" count=0 answered=0
	out="$(cd "$root" && "${PM_CMD[@]}" ARGS="$ask" 2>&1)" || out=""
	while IFS= read -r line; do
		case "$line" in
			"[pm] "*" of "*" milestone(s)") answered=1; continue ;;
			*"	"*) ;;
			*) continue ;;
		esac
		# `_rest` and not a bare `branch`: the LAST variable of a `read`
		# absorbs every remaining field, so a fifth column would silently
		# become part of the branch name. 0.4.0 added `name` and this is
		# what broke — a trailing catch-all is a consumer that only works
		# while the payload never grows.
		IFS=$'\t' read -r _id _status _cat branch _rest <<-EOF
		$line
		EOF
		# The trunk is `main` or the fallback itself, never a name the flow
		# may not have: a declared `staging` in a tree with none is refused
		# by name in `new`, not silently swapped for the fallback.
		case "$branch" in
			"" | - | main | "$FALLBACK_BASE") continue ;;
		esac
		found="$branch"
		count=$((count + 1))
	done <<-EOF
	$out
	EOF
	if [ "$answered" -ne 1 ]; then
		echo "agent-worktree: '${PM_CMD[*]} ARGS=\"$ask\"' could not answer (no census line) — basing off ${FALLBACK_BASE}" >&2
		return 0
	fi
	[ "$count" -eq 1 ] && printf '%s' "$found"
	return 0
}

# An agent branches off the active milestone's integration branch, not the trunk.
DEFAULT_BASE="$(integration_branch "$MAIN_ROOT")"
[ -n "$DEFAULT_BASE" ] || DEFAULT_BASE="$FALLBACK_BASE"

cd "$MAIN_ROOT" || { echo "agent-worktree: cannot cd to repo root '$MAIN_ROOT'" >&2; exit 1; }

die() { echo "agent-worktree: $*" >&2; exit 1; }

usage() {
	cat >&2 <<-EOF
	usage:
	  agent-worktree.sh new [--no-warm] <slug> [base-branch]   create ${BRANCH_PREFIX}<slug> worktree (cache pre-warmed)
	  agent-worktree.sh done <slug>                            teardown (merged-check + remove + branch delete)
	  agent-worktree.sh list                                   list active agent worktrees
	EOF
	exit 2
}

# A slug is a branch suffix and a directory name: only characters safe in both.
validate_slug() {
	local slug="$1"
	[ -n "$slug" ] || die "slug is required"
	case "$slug" in
		*[!a-zA-Z0-9._-]*) die "slug '$slug' has invalid chars (use a-z A-Z 0-9 . _ -)" ;;
	esac
}

cmd_new() {
	# --no-warm skips the dominant-cost cache copy.
	local no_warm=0
	if [ "${1:-}" = "--no-warm" ]; then
		no_warm=1; shift
	fi
	local slug="${1:-}"
	validate_slug "$slug"
	local base="${2:-$DEFAULT_BASE}"
	local branch="${BRANCH_PREFIX}${slug}"
	local rel_path="${WORKTREE_PARENT}/${slug}"
	local abs_path="${MAIN_ROOT}/${rel_path}"

	[ ! -e "$abs_path" ] || die "worktree path already exists: $abs_path (use 'done $slug' to tear it down first)"
	if git show-ref --verify --quiet "refs/heads/${branch}"; then
		die "branch ${branch} already exists — pick a fresh slug or 'done' the old worktree"
	fi
	git rev-parse --verify --quiet "${base}" >/dev/null \
		|| die "base '${base}' does not resolve — set FALLBACK_BASE in tools/dev/agent-worktree.sh, pass [base-branch], or run git remote set-head origin --auto"

	# One git op creates both the branch and the linked worktree. --no-track:
	# a base like origin/main must not become the branch's upstream.
	git worktree add --no-track -b "$branch" "$abs_path" "$base" >/dev/null \
		|| die "git worktree add failed"

	# Pre-warm the caches by copy, never symlink, so each tree owns its own;
	# a hardlink clone (cp -al) where supported.
	local warmed=()
	local sidecars=0
	local d
	if [ "$no_warm" -eq 0 ]; then
		local cp_warm=(cp -R)
		printf '' > "${abs_path}/.cp_al_src"
		if cp -al "${abs_path}/.cp_al_src" "${abs_path}/.cp_al_probe" 2>/dev/null; then
			cp_warm=(cp -al)
		fi
		rm -f "${abs_path}/.cp_al_src" "${abs_path}/.cp_al_probe"
		for d in ${WARM_DIRS[@]+"${WARM_DIRS[@]}"}; do
			if [ -e "${MAIN_ROOT}/${d}" ]; then
				"${cp_warm[@]}" "${MAIN_ROOT}/${d}" "${abs_path}/${d}"
				warmed+=("$d")
			fi
		done
		# Mirror the gitignored sidecars, hardlinked where supported; the worktree
		# parent is pruned so a re-`new` never re-warms a sibling's copies.
		if [ -n "$WARM_SIDECAR_GLOB" ]; then
			local rel dst f
			while IFS= read -r -d '' f; do
				rel="${f#"${MAIN_ROOT}/"}"
				dst="${abs_path}/${rel}"
				mkdir -p "$(dirname "$dst")"
				"${cp_warm[@]}" "$f" "$dst" 2>/dev/null || cp "$f" "$dst"
				sidecars=$((sidecars + 1))
			done < <(find "$MAIN_ROOT" \
				-path "${MAIN_ROOT}/${WORKTREE_PARENT}" -prune -o \
				-name "$WARM_SIDECAR_GLOB" -type f -print0)
		fi
	fi

	# Scope marker, key=value lines: the hooks read path/branch, `done` reads base. Gitignored.
	{
		printf 'path=%s\n' "$abs_path"
		printf 'branch=%s\n' "$branch"
		printf 'base=%s\n' "$base"
	} > "${abs_path}/${SCOPE_MARKER}"

	echo "agent-worktree: created ${branch}" >&2
	echo "  base:    ${base}" >&2
	if [ "$no_warm" -eq 1 ]; then
		echo "  warmed:  (skipped — --no-warm)" >&2
	else
		local cache_summary="(none — nothing in WARM_DIRS to copy)"
		[ "${#warmed[@]}" -gt 0 ] && cache_summary="${warmed[*]}"
		if [ -n "$WARM_SIDECAR_GLOB" ]; then
			cache_summary="${cache_summary}; ${sidecars} ${WARM_SIDECAR_GLOB} sidecars"
		fi
		echo "  warmed:  ${cache_summary}" >&2
	fi
	echo "  scope:   ${abs_path}/${SCOPE_MARKER}" >&2
	# The absolute path goes to stdout ALONE, for `$(agent-worktree.sh new x)`.
	echo "$abs_path"
}

# rows_past_head <tree> <rel> <out> — the bytes <tree>/<rel> holds past HEAD's
# copy (all of them where HEAD has none), into <out>. Returns 1 when HEAD's copy
# is not a prefix of the file: a row was changed or dropped, not appended.
rows_past_head() {
	local tree="$1" rel="$2" out="$3" size
	[ -f "${tree}/${rel}" ] || return 1
	git -C "$tree" cat-file blob "HEAD:${rel}" >"${out}.head" 2>/dev/null || : >"${out}.head"
	size="$(wc -c <"${out}.head" | tr -d ' ')"
	[ "$(wc -c <"${tree}/${rel}" | tr -d ' ')" -ge "$size" ] || return 1
	# `head -c` then a whole-file `cmp`: BSD `cmp -n` reports EOF inside its
	# limit, and BSD `head -c 0` is an error.
	[ "$size" -eq 0 ] || head -c "$size" "${tree}/${rel}" | cmp -s - "${out}.head" || return 1
	tail -c "+$((size + 1))" "${tree}/${rel}" >"$out"
}

cmd_done() {
	local slug="${1:-}"
	validate_slug "$slug"
	local branch="${BRANCH_PREFIX}${slug}"
	local abs_path="${MAIN_ROOT}/${WORKTREE_PARENT}/${slug}"

	git worktree list --porcelain | grep -qx "worktree ${abs_path}" \
		|| die "no active worktree at ${abs_path} (run 'list' to see active ones)"

	# Compare against the branch this worktree was created FROM, read before
	# `git worktree remove` deletes the marker.
	local base="$DEFAULT_BASE"
	if [ -f "${abs_path}/${SCOPE_MARKER}" ]; then
		local recorded_base
		recorded_base="$(grep -E '^base=' "${abs_path}/${SCOPE_MARKER}" | head -1 | cut -d= -f2-)"
		[ -n "$recorded_base" ] && base="$recorded_base"
	fi

	# Refuse on uncommitted work, ignoring exactly the artifacts this tool planted.
	local planted_dirs planted_roots
	planted_dirs="$(printf '%s/|' ${WARM_DIRS[@]+"${WARM_DIRS[@]}"})"
	planted_dirs="${planted_dirs%|}"
	planted_roots="$(printf '%s|' ${WARM_DIRS[@]+"${WARM_DIRS[@]}"})"
	planted_roots="${planted_roots%|}"
	local status ignored=""
	status="$(git -C "$abs_path" status --porcelain --untracked-files=all 2>/dev/null \
		| grep -vE "^.. (${SCOPE_MARKER}|${planted_dirs})\$" \
		| grep -vE "^.. (${planted_roots})\$" || true)"
	# A gitignored row file is never in `status`, and `worktree remove --force`
	# would delete it with its rows: it is listed, as `!!`, to be carried.
	if [ -n "$CARRY_ROWS" ]; then
		local within="${CARRY_ROWS%%\**}"
		ignored="$(git -C "$abs_path" ls-files --others --ignored --exclude-standard \
			-- "${within:-.}" 2>/dev/null | sed 's/^/!! /')"
	fi

	# Rows APPENDED to a CARRY_ROWS file are the lane's telemetry, not its work:
	# they go to the main checkout. A row changed or dropped is work, and refuses.
	CARRY_TMP="$(mktemp -d "${TMPDIR:-/tmp}/agent-worktree.XXXXXX")" \
		|| die "cannot make a scratch directory to carry rows through"
	trap 'rm -rf "$CARRY_TMP"' EXIT
	local line rel dirty="" carried=()
	while IFS= read -r line; do
		[ -n "$line" ] || continue
		rel="${line:3}"
		case "${line:0:2}" in
			" M" | "M " | "MM" | "A " | "AM" | "??" | "!!")
				# shellcheck disable=SC2254  # CARRY_ROWS is a glob, matched as one
				case "$rel" in
					$CARRY_ROWS)
						if rows_past_head "$abs_path" "$rel" "${CARRY_TMP}/${#carried[@]}"; then
							carried+=("$rel")
						else
							# Never silently removed with the tree, gitignored or not.
							dirty="${dirty}${line}"$'\n'
						fi
						continue
						;;
				esac
				;;
		esac
		[ "${line:0:2}" = "!!" ] || dirty="${dirty}${line}"$'\n'
	done <<< "${status}
${ignored}"
	if [ -n "$dirty" ]; then
		echo "agent-worktree: REFUSING to remove ${slug} — uncommitted work in the worktree:" >&2
		printf '%s' "$dirty" | sed 's/^/    /' >&2
		die "commit or discard it in ${abs_path}, then re-run 'done ${slug}'"
	fi

	# Appended to the same path in the main checkout, then the lane's copy is
	# reset from HEAD — so a re-run after any later refusal carries nothing twice.
	local i=0 dest suffix rows
	while [ "$i" -lt "${#carried[@]}" ]; do
		rel="${carried[$i]}"
		dest="${MAIN_ROOT}/${rel}"
		suffix="${CARRY_TMP}/${i}"
		rows="$(wc -l <"$suffix" | tr -d ' ')"
		if [ -s "$suffix" ]; then
			mkdir -p "$(dirname "$dest")" \
				|| die "cannot create $(dirname "$dest") to carry ${rel} — nothing removed"
			if [ -s "$dest" ] && [ -n "$(tail -c1 "$dest")" ] && [ -n "$(head -c1 "$suffix")" ]; then
				printf '\n' >>"$dest"
			fi
			cat "$suffix" >>"$dest" \
				|| die "cannot append ${rel} to the main checkout — nothing removed"
		fi
		if git -C "$abs_path" cat-file -e "HEAD:${rel}" 2>/dev/null; then
			git -C "$abs_path" checkout -q HEAD -- "$rel" \
				|| die "cannot reset ${rel} in ${abs_path} from HEAD — its rows are already in the main checkout"
		else
			git -C "$abs_path" rm -q --cached --ignore-unmatch -- "$rel" >/dev/null 2>&1
			rm -f "${abs_path}/${rel}"
		fi
		echo "agent-worktree: carried ${rows} row(s) of ${rel} into the main checkout" >&2
		i=$((i + 1))
	done

	# Merged into the base it was cut from, or into the mainline: after a release
	# no milestone is in progress, and a lane that landed through main is merged.
	# One merged into neither is kept, loudly; committed work is never dropped.
	local unmerged=0 ref into=""
	if git show-ref --verify --quiet "refs/heads/${branch}"; then
		for ref in "$base" "$FALLBACK_BASE"; do
			if git merge-base --is-ancestor "$branch" "$ref" 2>/dev/null; then
				into="$ref"
				break
			fi
		done
		if [ -z "$into" ]; then
			unmerged=1
			local named="$base"
			[ "$FALLBACK_BASE" = "$base" ] || named="${base} or ${FALLBACK_BASE}"
			echo "agent-worktree: WARNING — ${branch} is NOT merged into ${named}." >&2
			echo "  Removing the worktree but KEEPING the branch so committed work is not lost." >&2
			echo "  Re-run 'done ${slug}' after merging, or delete the branch by hand if abandoning." >&2
		fi
	fi

	# --force past the planted caches only; the tree carries no uncommitted work.
	git worktree remove --force "$abs_path" >/dev/null \
		|| die "git worktree remove failed for ${abs_path}"

	if [ "$unmerged" -eq 0 ] && git show-ref --verify --quiet "refs/heads/${branch}"; then
		# `-D` on a merge PROVEN above against a named ref: `-d` asks HEAD, and the
		# main checkout's HEAD may sit behind the mainline the lane landed in.
		git branch -D "$branch" >/dev/null \
			|| echo "agent-worktree: note — branch ${branch} not deleted (git branch -D declined)" >&2
		echo "agent-worktree: removed worktree + deleted merged branch ${branch}" >&2
	else
		echo "agent-worktree: removed worktree for ${slug} (branch ${branch} retained)" >&2
	fi
}

cmd_list() {
	local parent_abs="${MAIN_ROOT}/${WORKTREE_PARENT}"

	# git's registry is the authoritative view; a directory it no longer tracks is flagged.
	local registered
	registered="$(git worktree list --porcelain | sed -n 's/^worktree //p')"

	if [ ! -d "$parent_abs" ]; then
		echo "agent-worktree: no agent worktree directories (${WORKTREE_PARENT}/ absent)"
	else
		local found=0
		local dir
		for dir in "$parent_abs"/*/; do
			[ -d "$dir" ] || continue
			found=1
			dir="${dir%/}"
			local slug; slug="$(basename "$dir")"
			local scope="${dir}/${SCOPE_MARKER}"
			local branch="?"
			if [ -f "$scope" ]; then
				branch="$(grep -E '^branch=' "$scope" | head -1 | cut -d= -f2-)"
			fi
			local flag=""
			printf '%s\n' "$registered" | grep -qxF "$dir" \
				|| flag="  [STALE DIR — not a registered git worktree; use 'done' to clean]"
			printf '  %-24s branch=%-28s %s%s\n' "$slug" "$branch" "$dir" "$flag"
		done
		[ "$found" -eq 1 ] || echo "agent-worktree: no agent worktrees under ${WORKTREE_PARENT}/"
	fi

	# The inverse drift: registered, directory gone.
	local w
	while IFS= read -r w; do
		case "$w" in
			"${parent_abs}"/*)
				[ -d "$w" ] || printf '  %-24s %s  [REGISTERED but dir missing — run: git worktree prune]\n' "$(basename "$w")" "$w"
				;;
		esac
	done <<< "$registered"
}

# --- dispatch ----------------------------------------------------------------
[ "$#" -ge 1 ] || usage
sub="$1"; shift
case "$sub" in
	new)  cmd_new "$@" ;;
	done) cmd_done "$@" ;;
	list) cmd_list "$@" ;;
	-h|--help|help) usage ;;
	*) die "unknown command '$sub' (new|done|list)" ;;
esac
