#!/usr/bin/env bash
# agent-worktree.sh — the single sanctioned way to create and tear down
# per-agent git worktrees: a real checkout each (own dir, index, build cache),
# sharing only the object store.
#   new [--no-warm] <slug> [base]  branch <BRANCH_PREFIX><slug> + worktree at
#                                  external sibling/<slug> by default; caches pre-warmed,
#                                  scope marker written; prints the absolute path
#   adopt [<path>]                 write the scope marker into a worktree the
#                                  harness made (e.g. .claude/worktrees/agent-<id>)
#                                  once it is on a <BRANCH_PREFIX>* branch;
#                                  <path> defaults to the current checkout
#   done <slug>|<path>             carry appended CARRY_ROWS rows to the main
#                                  checkout, refuse on any other uncommitted
#                                  work, keep a branch merged into neither its
#                                  base nor the mainline, then remove worktree
#                                  and branch; a <path> (it has a `/`) is a
#                                  harness worktree, and its worktree-<dir>
#                                  branch goes too
#   list                           active worktrees, cross-checked with git
# Run from anywhere in the repo. `set -uo pipefail`, no -e: exit codes are read.
set -uo pipefail

if [ "$(git rev-parse --is-bare-repository 2>/dev/null)" = true ]; then
	echo "agent-worktree: bare repositories have no primary checkout and are unsupported" >&2
	exit 1
fi
PRIMARY_WORKTREE_ROOT=""
while IFS= read -r worktree_line; do
	case "$worktree_line" in
		"worktree "*) PRIMARY_WORKTREE_ROOT="${worktree_line#worktree }"; break ;;
	esac
done < <(git worktree list --porcelain 2>/dev/null)
[ -n "$PRIMARY_WORKTREE_ROOT" ] && [ -d "$PRIMARY_WORKTREE_ROOT" ] \
	|| { echo "agent-worktree: cannot identify the primary worktree; bare or missing-primary layouts are unsupported" >&2; exit 1; }
# The first registered worktree is Git's primary checkout. It remains the same
# for calls from every linked checkout, including repositories with a separate git dir.
MAIN_ROOT="$(cd "$PRIMARY_WORKTREE_ROOT" && pwd -P)" \
	|| { echo "agent-worktree: cannot resolve the primary worktree path" >&2; exit 1; }

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
declare -p WORKTREE_PARENT >/dev/null 2>&1 || WORKTREE_PARENT=""
declare -p BRANCH_PREFIX >/dev/null 2>&1 || BRANCH_PREFIX="feat/"
declare -p SCOPE_MARKER >/dev/null 2>&1 || SCOPE_MARKER=".agent-scope"
declare -p WARM_DIRS >/dev/null 2>&1 || WARM_DIRS=()
declare -p WARM_SIDECAR_GLOB >/dev/null 2>&1 || WARM_SIDECAR_GLOB=""
declare -p FALLBACK_BASE >/dev/null 2>&1 || FALLBACK_BASE=""
declare -p PM_CMD >/dev/null 2>&1 || PM_CMD=(make -s pm)
declare -p CARRY_ROWS >/dev/null 2>&1 || CARRY_ROWS="pm/roadmap/*.jsonl"

# The default is a sibling of the canonical checkout. A configured relative
# path keeps its historical meaning under that checkout.
if [ -z "$WORKTREE_PARENT" ]; then
	WORKTREE_PARENT_ABS="${MAIN_ROOT}.worktrees"
	WORKTREE_PARENT_LABEL="${MAIN_ROOT}.worktrees"
elif [[ "$WORKTREE_PARENT" = /* ]]; then
	WORKTREE_PARENT_ABS="$WORKTREE_PARENT"
	WORKTREE_PARENT_LABEL="$WORKTREE_PARENT"
else
	WORKTREE_PARENT_ABS="${MAIN_ROOT}/${WORKTREE_PARENT}"
	WORKTREE_PARENT_LABEL="$WORKTREE_PARENT"
fi
LEGACY_WORKTREE_PARENT="${MAIN_ROOT}/.claude/worktrees"

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

# The caller's directory, read before the cd below: `adopt` and `done <path>` resolve against it.
CALLER_PWD="$PWD"
cd "$MAIN_ROOT" || { echo "agent-worktree: cannot cd to repo root '$MAIN_ROOT'" >&2; exit 1; }

die() { echo "agent-worktree: $*" >&2; exit 1; }

usage() {
	cat >&2 <<-EOF
	usage:
	  agent-worktree.sh new [--no-warm] <slug> [base-branch]   create ${BRANCH_PREFIX}<slug> worktree (cache pre-warmed)
	  agent-worktree.sh adopt [<path>]                         write the scope marker into a harness worktree on ${BRANCH_PREFIX}*
	  agent-worktree.sh done <slug>|<path>                     teardown (merged-check + remove + branch delete)
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

# Scope marker, key=value lines: the hooks read path/branch, `done` reads base. Gitignored.
write_marker() {
	{
		printf 'path=%s\n' "$1"
		printf 'branch=%s\n' "$2"
		printf 'base=%s\n' "$3"
		printf 'base_sha=%s\n' "$4"
	} > "${1}/${SCOPE_MARKER}" || die "cannot write ${1}/${SCOPE_MARKER}"
}

# physical <path> — the path with every symlink resolved, relative to the caller's directory.
physical() {
	case "$1" in /*) (cd "$1" 2>/dev/null && pwd -P) ;; *) (cd "${CALLER_PWD}/$1" 2>/dev/null && pwd -P) ;; esac
}

# linked_worktree <path> — the physical toplevel of a LINKED worktree of this
# repository registered with git, or a refusal naming why it is not one.
linked_worktree() {
	local abs top registered
	abs="$(physical "$1")" || die "no such directory: $1"
	top="$(git -C "$abs" rev-parse --show-toplevel 2>/dev/null)" || die "'$abs' is not inside a git checkout"
	top="$(physical "$top")"
	[ "$top" != "$MAIN_ROOT" ] || die "'$top' is the primary checkout, not an agent worktree"
	while IFS= read -r registered; do
		[ "$(physical "$registered")" = "$top" ] && { printf '%s' "$top"; return 0; }
	done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
	die "'$top' is not a registered worktree of this repository (run 'list')"
}

cmd_adopt() {
	local top branch base_sha
	top="$(linked_worktree "${1:-$CALLER_PWD}")" || exit 1
	branch="$(git -C "$top" symbolic-ref --short -q HEAD)" || branch="(detached)"
	case "$branch" in
		"$BRANCH_PREFIX"*) ;;
		*) die "'$top' is on ${branch}, not ${BRANCH_PREFIX}* — run 'git switch -c ${BRANCH_PREFIX}<slug>' in it, then adopt again" ;;
	esac
	base_sha="$(git merge-base "$branch" "$DEFAULT_BASE" 2>/dev/null)" \
		|| die "base '${DEFAULT_BASE}' shares no commit with ${branch} — set FALLBACK_BASE in tools/dev/agent-worktree.sh"
	write_marker "$top" "$branch" "$DEFAULT_BASE" "$base_sha"
	echo "agent-worktree: adopted ${branch}" >&2
	echo "  base:    ${DEFAULT_BASE}" >&2
	echo "  scope:   ${top}/${SCOPE_MARKER}" >&2
	echo "$top"
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
	local abs_path="${WORKTREE_PARENT_ABS}/${slug}"

	[ ! -e "$abs_path" ] || die "worktree path already exists: $abs_path (use 'done $slug' to tear it down first)"
	if git show-ref --verify --quiet "refs/heads/${branch}"; then
		die "branch ${branch} already exists — pick a fresh slug or 'done' the old worktree"
	fi
	local base_sha
	base_sha="$(git rev-parse --verify --quiet "${base}^{commit}")" \
		|| die "base '${base}' does not resolve — set FALLBACK_BASE in tools/dev/agent-worktree.sh, pass [base-branch], or run git remote set-head origin --auto"

	# One git op creates both the branch and the linked worktree. --no-track:
	# a base like origin/main must not become the branch's upstream.
	mkdir -p "$WORKTREE_PARENT_ABS" || die "cannot create worktree parent '$WORKTREE_PARENT_ABS'"
	git worktree add --no-track -b "$branch" "$abs_path" "$base" >/dev/null \
		|| die "git worktree add failed"

	# Pre-warm caches with copy-on-write clones where supported, never hardlinks.
	local warmed=()
	local sidecars=0
	local d
	if [ "$no_warm" -eq 0 ]; then
		local cp_clone=()
		printf '' > "${abs_path}/.clone-src"
		if [ "$(uname -s)" = "Darwin" ]; then
			cp_clone=(cp -cR)
		elif cp --reflink=auto -R "${abs_path}/.clone-src" "${abs_path}/.clone-probe" 2>/dev/null; then
			cp_clone=(cp --reflink=auto -R)
		fi
		rm -f "${abs_path}/.clone-src" "${abs_path}/.clone-probe"
		for d in ${WARM_DIRS[@]+"${WARM_DIRS[@]}"}; do
			local source="${MAIN_ROOT}/${d}" source_physical worktree_path overlaps=0
			if [ ! -e "$source" ]; then
				continue
			fi
			[ -d "$source" ] || die "WARM_DIRS entry '$d' is not a directory"
			source_physical="$(cd "$source" 2>/dev/null && pwd -P)"
			while IFS= read -r worktree_path; do
				[ -n "$worktree_path" ] && [ "$worktree_path" != "$MAIN_ROOT" ] || continue
				case "$source_physical/" in "$worktree_path/"*) overlaps=1 ;; esac
				case "$worktree_path/" in "$source_physical/"*) overlaps=1 ;; esac
			done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
			if [ "$overlaps" -eq 1 ]; then
				echo "agent-worktree: skipped cache '$d' because it overlaps a linked worktree" >&2
				continue
			fi
			local target="${abs_path}/${d}"
			mkdir -p "$(dirname "$target")"
			if [ "${#cp_clone[@]}" -gt 0 ]; then
				if ! "${cp_clone[@]}" "$source" "$target" 2>/dev/null; then
					mkdir -p "$target" || die "cannot create cache destination '$target'"
					cp -R "${source}/." "${target}/" \
						|| die "cannot copy cache directory '$source' to '$target'"
				fi
			else
				mkdir -p "$target" || die "cannot create cache destination '$target'"
				cp -R "${source}/." "${target}/" \
					|| die "cannot copy cache directory '$source' to '$target'"
			fi
			warmed+=("$d")
		done
		# Mirror gitignored sidecars. Prune every registered checkout so this pass
		# never copies artifacts from another worktree.
		if [ -n "$WARM_SIDECAR_GLOB" ]; then
			local rel dst f worktree_path
			local find_args=("$MAIN_ROOT")
			while IFS= read -r worktree_path; do
				case "$worktree_path" in "${MAIN_ROOT}/"*)
					find_args+=(-path "$worktree_path" -prune -o)
				;; esac
				done < <(git worktree list --porcelain | sed -n 's/^worktree //p')
			find_args+=(-path "$LEGACY_WORKTREE_PARENT" -prune -o -name "$WARM_SIDECAR_GLOB" -type f -print0)
			while IFS= read -r -d '' f; do
				rel="${f#"${MAIN_ROOT}/"}"
				dst="${abs_path}/${rel}"
				mkdir -p "$(dirname "$dst")"
				if [ "${#cp_clone[@]}" -gt 0 ]; then
					"${cp_clone[@]}" "$f" "$dst" 2>/dev/null \
						|| cp "$f" "$dst" || die "cannot copy sidecar '$f' to '$dst'"
				else
					cp "$f" "$dst" || die "cannot copy sidecar '$f' to '$dst'"
				fi
				sidecars=$((sidecars + 1))
			done < <(find "${find_args[@]}")
		fi
	fi

	write_marker "$abs_path" "$branch" "$base" "$base_sha"

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
	local slug="${1:-}" branches=()
	local abs_path="" candidate registered branch
	case "$slug" in
		*/*)
			# A harness worktree: its checked-out branch, and the worktree-<dir> branch the harness cut.
			abs_path="$(linked_worktree "$slug")" || exit 1
			branch="$(git -C "$abs_path" symbolic-ref --short -q HEAD)" && branches+=("$branch")
			[ "$branch" = "worktree-$(basename "$abs_path")" ] || branches+=("worktree-$(basename "$abs_path")")
			;;
		*)
			validate_slug "$slug"
			branches=("${BRANCH_PREFIX}${slug}")
			registered="$(git worktree list --porcelain | sed -n 's/^worktree //p')"
			for candidate in "${WORKTREE_PARENT_ABS}/${slug}" "${LEGACY_WORKTREE_PARENT}/${slug}"; do
				if printf '%s\n' "$registered" | grep -qxF "$candidate"; then
					abs_path="$candidate"
					break
				fi
			done
			[ -n "$abs_path" ] \
				|| die "no active worktree for ${slug} under ${WORKTREE_PARENT_ABS} or ${LEGACY_WORKTREE_PARENT} (run 'list' to see active ones)"
			;;
	esac

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
	local ref into merged=()
	for branch in "${branches[@]}"; do
		git show-ref --verify --quiet "refs/heads/${branch}" || continue
		into=""
		for ref in "$base" "$FALLBACK_BASE"; do
			if git merge-base --is-ancestor "$branch" "$ref" 2>/dev/null; then
				into="$ref"
				break
			fi
		done
		if [ -n "$into" ]; then
			merged+=("$branch")
		else
			local named="$base"
			[ "$FALLBACK_BASE" = "$base" ] || named="${base} or ${FALLBACK_BASE}"
			echo "agent-worktree: WARNING — ${branch} is NOT merged into ${named}." >&2
			echo "  Removing the worktree but KEEPING the branch so committed work is not lost." >&2
			echo "  Re-run 'done ${slug}' after merging, or delete the branch by hand if abandoning." >&2
		fi
	done

	# A harness locks its worktrees; the lock guards nothing once the work is checked.
	git worktree unlock "$abs_path" >/dev/null 2>&1
	# --force past the planted caches only; the tree carries no uncommitted work.
	git worktree remove --force "$abs_path" >/dev/null \
		|| die "git worktree remove failed for ${abs_path}"

	for branch in ${merged[@]+"${merged[@]}"}; do
		# `-D` on a merge PROVEN above against a named ref: `-d` asks HEAD, and the
		# main checkout's HEAD may sit behind the mainline the lane landed in.
		git branch -D "$branch" >/dev/null \
			|| echo "agent-worktree: note — branch ${branch} not deleted (git branch -D declined)" >&2
		echo "agent-worktree: removed worktree + deleted merged branch ${branch}" >&2
	done
	[ "${#merged[@]}" -gt 0 ] \
		|| echo "agent-worktree: removed worktree for ${slug} (branch ${branches[*]} retained)" >&2
}

cmd_list() {
	local parent_abs="$WORKTREE_PARENT_ABS"
	local parents=("$parent_abs")
	[ "$LEGACY_WORKTREE_PARENT" = "$parent_abs" ] || parents+=("$LEGACY_WORKTREE_PARENT")

	# git's registry is the authoritative view; a directory it no longer tracks is flagged.
	local registered
	registered="$(git worktree list --porcelain | sed -n 's/^worktree //p')"

	local found=0 parent dir
	for parent in "${parents[@]}"; do
		[ -d "$parent" ] || continue
		for dir in "$parent"/*/; do
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
	done
	[ "$found" -eq 1 ] || echo "agent-worktree: no agent worktree directories (${WORKTREE_PARENT_LABEL} absent)"

	# The inverse drift: registered, directory gone.
	local w
	while IFS= read -r w; do
		case "$w" in
			"${parent_abs}"/* | "${LEGACY_WORKTREE_PARENT}"/*)
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
	adopt) cmd_adopt "$@" ;;
	list) cmd_list "$@" ;;
	-h|--help|help) usage ;;
	*) die "unknown command '$sub' (new|adopt|done|list)" ;;
esac
