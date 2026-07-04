#!/usr/bin/env bash
# repo_hygiene.sh — milestone-CLOSE git-state guard.
#
# A milestone does not close clean if the repo carries leftover git state — WIP
# stashes, dangling worktrees, dead (merged-but-undeleted) branches, or an unclean
# tree. That cruft is invisible to the content/test gates yet accumulates across
# milestones (leftover stashes, merged-but-undeleted agent feat/* branches) until
# a close pass has to hand-sweep it. This makes the swept-clean end-state a
# FAILING GATE.
#
# CLOSE-TIME ONLY — it runs a network `git fetch --prune` for the remote-branch
# check, so it is wired into `make milestone` (the close gate), NOT `make precommit`
# / `make check`: mid-development you legitimately hold WIP stashes + feature
#
# Pure git (no Godot boot) — sibling of uid_scan.sh / tres_format_scan.sh.
#
# CHECK 1 (HARD): working tree clean — no uncommitted or untracked changes.
# CHECK 2 (HARD): no stashes.
# CHECK 3 (HARD): no dangling worktrees (a prune would remove nothing).
# CHECK 4 (HARD): no merged-but-undeleted branches — local AND remote merged into
#                 origin/main, excluding the long-lived lines + archive/* keepsakes.
# REPORT  (WARN): unmerged non-archive/* branches — a human keep/delete call the
#                 scanner can't make. Keep one by renaming it archive/* (the
#                 sanctioned keepsake convention, e.g. archive/ldtk-pipeline).
#
# Usage:  tools/dev/checks/repo_hygiene.sh     (run from repo root; exits 1 on any HARD violation)

set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && git rev-parse --show-toplevel)"
cd "$ROOT" || exit 2

# The mainline every merge lands on, and the branches this gate never flags:
# the two long-lived lines + intentional archive keepsakes.
MAINLINE="${DEVKIT_MAINLINE:-origin/main}"
PROTECTED_RE="${DEVKIT_PROTECTED_RE:-^(main|staging|archive/.*)\$}"

hard=0
warn=0

# Refresh remote state so CHECK 4's merged-remote view is current (close-time; needs network).
echo "[repo_hygiene] refreshing remote refs (git fetch --prune)…"
if ! git fetch --prune origin --quiet 2>/dev/null; then
	echo "  WARN: git fetch failed — the merged-remote-branch check may be stale"
fi

echo "[repo_hygiene] CHECK 1 — working tree clean"
dirty="$(git status --porcelain)"
if [ -n "$dirty" ]; then
	echo "  DIRTY  uncommitted/untracked changes present:"
	printf '%s\n' "$dirty" | sed 's/^/    /'
	hard=$((hard + 1))
fi

echo "[repo_hygiene] CHECK 2 — no stashes"
stashes="$(git stash list)"
if [ -n "$stashes" ]; then
	echo "  STASHES  present (a milestone close carries none):"
	printf '%s\n' "$stashes" | sed 's/^/    /'
	hard=$((hard + 1))
fi

echo "[repo_hygiene] CHECK 3 — no dangling worktrees"
dangling="$(git worktree prune -n -v 2>/dev/null)"
if [ -n "$dangling" ]; then
	echo "  WORKTREES  a prune would remove:"
	printf '%s\n' "$dangling" | sed 's/^/    /'
	hard=$((hard + 1))
fi

echo "[repo_hygiene] CHECK 4 — no merged-but-undeleted branches (merged into $MAINLINE)"
while IFS= read -r b; do
	b="${b#\* }"
	b="${b#"${b%%[![:space:]]*}"}"   # ltrim
	b="${b%"${b##*[![:space:]]}"}"   # rtrim
	[ -z "$b" ] && continue
	printf '%s\n' "$b" | grep -qE "$PROTECTED_RE" && continue
	echo "  MERGED-LOCAL   $b is merged into $MAINLINE but not deleted"
	hard=$((hard + 1))
done <<< "$(git branch --merged "$MAINLINE" 2>/dev/null)"

while IFS= read -r b; do
	b="${b#"${b%%[![:space:]]*}"}"
	b="${b%"${b##*[![:space:]]}"}"
	[ -z "$b" ] && continue
	b="${b#origin/}"
	printf '%s\n' "$b" | grep -qE "$PROTECTED_RE" && continue
	echo "  MERGED-REMOTE  origin/$b is merged into $MAINLINE but not deleted"
	hard=$((hard + 1))
done <<< "$(git branch -r --merged "$MAINLINE" 2>/dev/null | grep -vE 'origin/HEAD')"

echo "[repo_hygiene] REPORT — unmerged branches needing a keep/delete decision (warn only)"
while IFS= read -r b; do
	b="${b#\* }"
	b="${b#"${b%%[![:space:]]*}"}"
	b="${b%"${b##*[![:space:]]}"}"
	[ -z "$b" ] && continue
	printf '%s\n' "$b" | grep -qE "$PROTECTED_RE" && continue
	echo "  UNMERGED  $b (keep → rename archive/*, or delete)"
	warn=$((warn + 1))
done <<< "$(git branch --no-merged "$MAINLINE" 2>/dev/null)"

echo
if [ "$hard" -gt 0 ]; then
	echo "[repo_hygiene] FAIL — $hard repo-state violation(s); $warn unmerged branch(es) to review"
	exit 1
fi
echo "[repo_hygiene] PASS — clean tree, no stashes, no dangling worktrees, no dead branches ($warn unmerged branch(es) to review)"
