#!/usr/bin/env bash
# agent-worktree.sh — the SINGLE sanctioned way to create/teardown per-agent
# git worktrees for parallel agent dispatch. Replaces harness-level worktree
# isolation flags, which have silently no-op'd in the field (two agents in one
# working dir/index/build cache → cross-contaminated commits, a reset that
# wiped work, a corrupted import cache).
#
# Each worktree is a real, separate checkout: own working dir, own git index,
# own build cache — sharing only the append-only object store. That is how
# humans parallelize on one repo, made real for agents.
#
# Commands:
#   agent-worktree.sh new [--no-warm] <slug> [base-branch]
#       Create branch <BRANCH_PREFIX><slug> + worktree at <WORKTREE_PARENT>/<slug>
#       off base-branch (default: the active milestone's integration branch per
#       the PM tree, else FALLBACK_BASE). Pre-warms the build caches by copying
#       them from the main tree so the first boot is warm. Writes a gitignored
#       scope marker (abs path + branch + base) at the worktree root — the
#       marker the installed hooks read for agent-context detection. Prints the
#       absolute worktree path (paste it into the dispatch prompt as the
#       agent's working directory).
#
#   agent-worktree.sh done <slug>
#       The ONLY sanctioned teardown: refuse if uncommitted work remains, warn
#       (and keep the branch) if unmerged, then `git worktree remove` + branch
#       delete. Nothing else removes a worktree — this is what prevents the
#       "deleted the worktree out from under a running agent" incident.
#
#   agent-worktree.sh list
#       Show active agent worktrees + their branches + scope markers,
#       cross-checked against git's authoritative worktree registry.
#
# Run from anywhere inside the repo.
#
# set -uo pipefail (no -e): this tool inspects command exit codes (merged-check,
# porcelain-diff, ref existence) to make decisions rather than aborting on the
# first non-zero — so `-e` would be wrong. Unset vars stay fatal; pipefail keeps
# a failing upstream stage from being masked.
set -uo pipefail

MAIN_ROOT="$(git rev-parse --show-toplevel)"

# --- project config (yours to edit after install — the file is your repo's) --
WORKTREE_PARENT=".claude/worktrees"   # repo-relative; gitignore it
BRANCH_PREFIX="feat/"
SCOPE_MARKER=".agent-scope"           # the marker the installed hooks read
WARM_DIRS=(".godot" ".import")        # central caches copied to pre-warm a fresh tree
# Gitignored per-asset sidecars to mirror into the worktree (e.g. "*.import"
# for a repo that gitignores Godot's scattered import sidecars — without them
# the fresh checkout's first boot is cold and resource loads fail). Empty = off.
WARM_SIDECAR_GLOB=""
# Where an agent branches from when no milestone declares an integration
# branch (see integration_branch below).
FALLBACK_BASE="staging"
# -----------------------------------------------------------------------------

# integration_branch [toplevel]
# Echo the ACTIVE milestone's integration branch, or nothing when no milestone
# is building. Read from the devkit PM tree — the `branch:` stamp on the
# milestone whose status is `building`.
#
# There are THREE kinds of branch here, and conflating the middle one with the
# last is what has stranded an integration branch in a worktree:
#   the trunk (staging/main)           — the resting state between milestones
#   the milestone's integration branch — feat/*-named but belongs in the TRUNK,
#                                        so the human can follow along
#   per-agent feat/<slug>              — worktree-only, branched from and merged
#                                        back into the integration branch
#
# More than one milestone may be `building` — a long-running umbrella declaring
# a trunk branch alongside a sub-milestone on its own branch. So this does NOT
# take the first building milestone: it collects the ones declaring a NON-trunk
# branch. Exactly one is the answer; zero means the trunk simply stays put; two
# or more is genuinely ambiguous and yields nothing, because a tool that
# guesses wrong here either strands an agent or mis-bases one.
integration_branch() {
	local root="${1:-$MAIN_ROOT}"
	local mfile branch found="" count=0
	for mfile in "$root"/pm/roadmap/*/milestone.md; do
		[ -f "$mfile" ] || continue
		grep -qE '^status: *"?building"? *$' "$mfile" || continue
		branch="$(sed -n 's/^branch: *"\{0,1\}\(.*[^"]\)"\{0,1\} *$/\1/p' "$mfile" | head -1)"
		case "$branch" in
			"" | staging | main) continue ;;
		esac
		found="$branch"
		count=$((count + 1))
	done
	[ "$count" -eq 1 ] && printf '%s' "$found"
	return 0
}

# An agent branches off the ACTIVE milestone's integration branch and merges
# back into it — that branch, not the trunk, is where a milestone's work is
# being assembled. Basing off the trunk while a milestone is building strands
# the agent behind every commit the milestone has already landed.
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

# A slug becomes both a branch suffix and a directory name — keep it to the
# characters that are safe in both (no slashes, no whitespace).
validate_slug() {
	local slug="$1"
	[ -n "$slug" ] || die "slug is required"
	case "$slug" in
		*[!a-zA-Z0-9._-]*) die "slug '$slug' has invalid chars (use a-z A-Z 0-9 . _ -)" ;;
	esac
}

cmd_new() {
	# --no-warm skips the (dominant-cost) cache copy for callers that don't
	# need a warm first boot.
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
		|| die "base branch '${base}' does not exist"

	# One git op creates both the branch and the linked worktree.
	git worktree add -b "$branch" "$abs_path" "$base" >/dev/null \
		|| die "git worktree add failed"

	# Pre-warm the build caches so the first boot is warm. A fresh worktree has
	# no import cache, which is exactly the cold-cache state that produces
	# spurious first-boot failures. Copy (not symlink) so the agent's tree owns
	# an independent cache — concurrent import runs across agents must never
	# share one cache file. Prefer a hardlink clone (cp -al) where supported —
	# same on-disk blocks, near-instant, safe for reads (a tool rewriting a
	# cache file replaces the inode rather than mutating shared blocks). Fall
	# back to a deep copy. --no-warm skips it entirely.
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
		for d in "${WARM_DIRS[@]}"; do
			if [ -e "${MAIN_ROOT}/${d}" ]; then
				"${cp_warm[@]}" "${MAIN_ROOT}/${d}" "${abs_path}/${d}"
				warmed+=("$d")
			fi
		done
		# Mirror the gitignored per-asset sidecars (absent from the fresh
		# checkout) into the worktree at the same relative path, hardlinked
		# where supported. The worktree parent is pruned so a re-`new` never
		# recursively re-warms a sibling worktree's copies. NUL-delimited
		# find|read so paths with spaces survive.
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

	# Scope marker: abs path + branch + base. The guards read path/branch to
	# enforce "this worktree may only commit its own branch"; `done`'s
	# merged-check reads base so a worktree based off something other than the
	# trunk isn't falsely warned "unmerged". Gitignored so it never lands in a
	# commit. key=value lines (grep-friendly).
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
		local cache_summary="(none — main tree had no ${WARM_DIRS[*]} to copy)"
		[ "${#warmed[@]}" -gt 0 ] && cache_summary="${warmed[*]}"
		if [ -n "$WARM_SIDECAR_GLOB" ]; then
			cache_summary="${cache_summary}; ${sidecars} ${WARM_SIDECAR_GLOB} sidecars"
		fi
		echo "  warmed:  ${cache_summary}" >&2
	fi
	echo "  scope:   ${abs_path}/${SCOPE_MARKER}" >&2
	# The absolute path goes to stdout ALONE so a caller can
	# `$(agent-worktree.sh new x)` it straight into a dispatch prompt.
	echo "$abs_path"
}

cmd_done() {
	local slug="${1:-}"
	validate_slug "$slug"
	local branch="${BRANCH_PREFIX}${slug}"
	local abs_path="${MAIN_ROOT}/${WORKTREE_PARENT}/${slug}"

	git worktree list --porcelain | grep -qx "worktree ${abs_path}" \
		|| die "no active worktree at ${abs_path} (run 'list' to see active ones)"

	# The merged-check must compare against the branch this worktree was
	# created FROM, not always DEFAULT_BASE — a worktree based off another
	# branch that merged there would otherwise be falsely warned "NOT merged"
	# and its branch retained. Read base= from the scope marker before
	# `git worktree remove` deletes it; fall back to DEFAULT_BASE.
	local base="$DEFAULT_BASE"
	if [ -f "${abs_path}/${SCOPE_MARKER}" ]; then
		local recorded_base
		recorded_base="$(grep -E '^base=' "${abs_path}/${SCOPE_MARKER}" | head -1 | cut -d= -f2-)"
		[ -n "$recorded_base" ] && base="$recorded_base"
	fi

	# Guard against losing UNCOMMITTED work. The pre-warmed caches and the
	# scope marker are untracked-by-design, so a naive `git worktree remove`
	# always refuses (sees them as a dirty tree) and a naive `--force` would
	# discard real work alongside the caches. Inspect the porcelain status,
	# ignore exactly the artifacts we planted, and refuse only if genuine
	# tracked/untracked work remains uncommitted.
	local planted_dirs planted_roots
	planted_dirs="$(printf '%s/|' "${WARM_DIRS[@]}")"
	planted_dirs="${planted_dirs%|}"
	planted_roots="$(printf '%s|' "${WARM_DIRS[@]}")"
	planted_roots="${planted_roots%|}"
	local dirty
	dirty="$(git -C "$abs_path" status --porcelain --untracked-files=all 2>/dev/null \
		| grep -vE "^.. (${SCOPE_MARKER}|${planted_dirs})\$" \
		| grep -vE "^.. (${planted_roots})\$" || true)"
	if [ -n "$dirty" ]; then
		echo "agent-worktree: REFUSING to remove ${slug} — uncommitted work in the worktree:" >&2
		printf '%s\n' "$dirty" | sed 's/^/    /' >&2
		die "commit or discard it in ${abs_path}, then re-run 'done ${slug}'"
	fi

	# Merged-check: warn loudly but do NOT silently drop unmerged COMMITS. The
	# branch is preserved when unmerged so committed work is never lost; the
	# operator merges then re-runs 'done', or deletes the branch by hand.
	local unmerged=0
	if git show-ref --verify --quiet "refs/heads/${branch}"; then
		if ! git merge-base --is-ancestor "$branch" "$base" 2>/dev/null; then
			unmerged=1
			echo "agent-worktree: WARNING — ${branch} is NOT merged into ${base}." >&2
			echo "  Removing the worktree but KEEPING the branch so committed work is not lost." >&2
			echo "  Re-run 'done ${slug}' after merging, or delete the branch by hand if abandoning." >&2
		fi
	fi

	# --force past the planted caches only — we already proved the tree carries
	# no uncommitted work above, so this discards build artifacts exclusively.
	git worktree remove --force "$abs_path" >/dev/null \
		|| die "git worktree remove failed for ${abs_path}"

	if [ "$unmerged" -eq 0 ] && git show-ref --verify --quiet "refs/heads/${branch}"; then
		git branch -d "$branch" >/dev/null \
			|| echo "agent-worktree: note — branch ${branch} not deleted (git branch -d declined)" >&2
		echo "agent-worktree: removed worktree + deleted merged branch ${branch}" >&2
	else
		echo "agent-worktree: removed worktree for ${slug} (branch ${branch} retained)" >&2
	fi
}

cmd_list() {
	local parent_abs="${MAIN_ROOT}/${WORKTREE_PARENT}"

	# git's worktree registry is the authoritative view. Capture the set of
	# registered worktree paths so we can flag a directory that exists on disk
	# but git no longer tracks (or vice-versa) — the drift a raw `git worktree
	# remove` (the anti-pattern this tool exists to prevent) leaves behind.
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

	# Surface any git-registered agent worktree whose directory is gone (the
	# inverse drift) so it can be pruned.
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
