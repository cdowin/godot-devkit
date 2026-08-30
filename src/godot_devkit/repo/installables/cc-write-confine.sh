#!/usr/bin/env bash
# cc-write-confine.sh — Claude Code PreToolUse write-confinement hook.
#
# The early-catch layer of the shared-tree guard. Blocks a mis-targeted WRITE
# before it lands: an agent whose session lives in worktree-A must not
# Edit/Write/NotebookEdit a path inside a DIFFERENT repository. This turns the
# silent cross-tree collision into an instant, recoverable error at the moment
# of the bad edit — not at commit time.
#
# Scope: this confines ONLY the structured write tools
# (Edit|Write|NotebookEdit|MultiEdit). It deliberately does NOT confine the
# `Bash` tool — robust bash-write-target parsing (redirects, cp/mv/tee, command
# substitution) is a tar pit, and the git pre-commit layer backstops any
# resulting commit.
#
# What is ALLOWED, and why each carve-out exists:
#   - a target outside ANY git repo (a scratchpad, /tmp, the agent-memory dir,
#     a home dotfile). A non-repo location is not the cross-tree collision this
#     hook guards; blocking it just pushes the agent to Bash heredocs, which
#     this hook cannot see.
#   - the Claude Code auto-memory store (~/.claude/projects/<p>/memory/), by
#     exact path shape — it survives even when ~/.claude is itself a git repo.
#   - a worktree of the SAME repository. A dispatched subagent reports the
#     PARENT session's cwd, not the worktree it was told to work in — the Agent
#     tool exposes no per-agent cwd or env — so without this branch every edit
#     a worktree-scoped agent makes is blocked and the agent falls back to Bash
#     heredocs (observed in the field: a whole feature authored through Bash to
#     dodge this guard). Per-worktree isolation between sibling agents rests on
#     the git layer, where it is genuinely enforceable.
#   - a root granted in tools/hooks/extra-write-roots.local — one absolute git
#     toplevel per line, '#' comments allowed. LOCAL and gitignored: a per-
#     machine, temporary grant for a deliberate cross-repo task, never a
#     committed standing allowlist.
#
# Optional strict override: if DEVKIT_AGENT_SCOPE is exported by the dispatch,
# it pins the allowed toplevel directly (a path VALUE, not a boolean flag).
#
# Protocol: Claude Code feeds the PreToolUse event as JSON on stdin
# (tool_name, tool_input.{file_path|notebook_path}, cwd). Exit 0 = allow,
# exit 2 = BLOCK with stderr returned to the agent. Any internal failure exits
# 0 (fail open) — a broken hook must never wedge the session.
set -eu
trap 'exit 0' ERR

INPUT="$(cat)"

# Minimal JSON field extraction (no jq dependency — hooks must run anywhere).
# Pulls the first "key": "value" string value. Adequate here because every
# field THIS hook reads is a tool name or an absolute path — values that never
# carry an escaped quote. A hook that reads tool_input.command must use a real
# JSON parser instead (see cc-commit-pathspec.sh for why).
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

# The auto-memory store lives outside any repo by design. Scoped to that exact
# path shape — not a blanket opening — so it stays allowed even on a machine
# where ~/.claude is itself version-controlled.
case "$TARGET" in
	*/.claude/projects/*/memory/*) exit 0 ;;
esac

SESSION_CWD="$(json_str cwd)"
[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"

toplevel_of() {
	# Resolve the git toplevel that owns a directory; empty if not in a repo.
	git -C "$1" rev-parse --show-toplevel 2>/dev/null || true
}

# The directory the write would land in (the file itself may not exist yet, so
# walk up to the nearest existing ancestor before asking git).
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

# If we can't determine the session's toplevel, fail OPEN — never wedge editing
# outside a repo (the git guard still backstops any resulting commit).
[ -n "$allowed" ] || exit 0

target_top="$(toplevel_of "$target_dir")"

# Target is not inside ANY git repo → not the cross-tree collision this hook
# guards (see the header). Only a write into a DIFFERENT repository is blocked.
[ -n "$target_top" ] || exit 0

if [ "$target_top" = "$allowed" ]; then
	exit 0
fi

# Same repository, different worktree? Compare the shared git common dir —
# identical across a repo's worktrees, different across repos.
allowed_common="$(git -C "$allowed" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
target_common="$(git -C "$target_top" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [ -n "$allowed_common" ] && [ "$allowed_common" = "$target_common" ]; then
	exit 0
fi

# Explicitly-granted extra roots: a LOCAL, gitignored file of absolute git
# toplevels, one per line. The grant is the toplevel itself — matched exactly,
# so a grant of /x/repo never admits /x/repo-evil.
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
