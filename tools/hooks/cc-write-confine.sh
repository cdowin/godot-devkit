#!/usr/bin/env bash
# cc-write-confine.sh — Claude Code PreToolUse hook: block an Edit/Write/
# NotebookEdit/MultiEdit into a DIFFERENT repository than the session's, at the
# moment of the bad edit. Allowed: a target outside any repo, the auto-memory
# store, a worktree of the same repo, and a root listed in
# tools/hooks/extra-write-roots.local (gitignored, one toplevel per line).
# DEVKIT_AGENT_SCOPE pins the allowed toplevel. Bash is not confined; the git
# layer backstops it. Stdin: the PreToolUse JSON (tool_name, tool_input.
# {file_path|notebook_path}, cwd). Exit 0 = allow, 2 = block; failures exit 0.
set -eu
trap 'exit 0' ERR

INPUT="$(cat)"

# grep extraction suffices for a tool name and an absolute path; a COMMAND needs a real parser.
json_str() {
	printf '%s' "$INPUT" \
		| grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
		| head -1 \
		| sed -E "s/.*:[[:space:]]*\"([^\"]*)\"/\1/"
}

TOOL="$(json_str tool_name)"
case "$TOOL" in
	Edit|Write|NotebookEdit|MultiEdit) ;;
	*) exit 0 ;;  # not a structured write tool → nothing to confine
esac

TARGET="$(json_str file_path)"
[ -n "$TARGET" ] || TARGET="$(json_str notebook_path)"
# No resolvable target path → let Claude Code's own validation handle it.
[ -n "$TARGET" ] || exit 0

# The auto-memory store, by exact path shape, even when ~/.claude is itself a repo.
case "$TARGET" in
	*/.claude/projects/*/memory/*) exit 0 ;;
esac

SESSION_CWD="$(json_str cwd)"
[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"

toplevel_of() {
	# Resolve the git toplevel that owns a directory; empty if not in a repo.
	git -C "$1" rev-parse --show-toplevel 2>/dev/null || true
}

# The file may not exist yet: walk up to the nearest existing ancestor.
target_dir="$(dirname "$TARGET")"
while [ ! -d "$target_dir" ] && [ "$target_dir" != "/" ]; do
	target_dir="$(dirname "$target_dir")"
done

# Allowed toplevel: explicit scope override wins; else the session's toplevel.
if [ -n "${DEVKIT_AGENT_SCOPE:-}" ]; then
	allowed="$DEVKIT_AGENT_SCOPE"
else
	allowed="$(toplevel_of "$SESSION_CWD")"
fi

# No session toplevel: fail open; the git guard backstops.
[ -n "$allowed" ] || exit 0

target_top="$(toplevel_of "$target_dir")"

# A target in no repo is not the cross-tree collision this guards.
[ -n "$target_top" ] || exit 0

if [ "$target_top" = "$allowed" ]; then
	exit 0
fi

# Same repository, different worktree: the git common dir is shared.
allowed_common="$(git -C "$allowed" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
target_common="$(git -C "$target_top" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [ -n "$allowed_common" ] && [ "$allowed_common" = "$target_common" ]; then
	exit 0
fi

# Granted roots match exactly, so /x/repo never admits /x/repo-evil.
EXTRA_ROOTS_FILE="$(dirname "${BASH_SOURCE[0]}")/extra-write-roots.local"
if [ -f "$EXTRA_ROOTS_FILE" ]; then
	while IFS= read -r extra_root; do
		case "$extra_root" in ''|\#*) continue ;; esac
		if [ "$target_top" = "$extra_root" ]; then
			exit 0
		fi
	done < "$EXTRA_ROOTS_FILE"
fi

{
	echo "BLOCKED (write-confinement): edit targets a repository outside this session's worktree."
	echo "  session worktree: ${allowed}"
	echo "  attempted write:  ${TARGET}"
	echo "    (its toplevel:  ${target_top})"
	echo "  Writes are confined to the current repository (any of its worktrees)."
	echo "  To work in another repo, dispatch a separate agent scoped to it"
	echo "  (tools/dev/agent-worktree.sh new <slug> from that repo), or record a"
	echo "  user-granted root in tools/hooks/extra-write-roots.local."
} >&2
exit 2
