#!/usr/bin/env bash
# cc-stop-gate.sh — Claude Code Stop hook: the verification-before-done gate.
#
# When an AGENT tries to finish, run the project's fast gate. On red, block the
# stop (exit 2) and return the gate output so the agent fixes before truly
# finishing — enforcing "verify before claiming done" structurally instead of
# relying on the LLM to remember.
#
# AGENT-CONTEXT ONLY. The orchestrator's main session (the trunk tree) stops
# constantly mid-orchestration and MUST NOT pay this cost — agent context is a
# worktree scope marker (written by tools/dev/agent-worktree.sh) or the
# DEVKIT_AGENT_SCOPE env, and everything else exits 0 ungated. This is THE
# load-bearing safety property: a false trigger would wedge the orchestrator
# every turn. The full pre-merge gate stays an orchestrator step, not a
# per-stop cost.
#
# Protocol: Claude Code feeds the Stop event as JSON on stdin (cwd,
# stop_hook_active). Exit 0 = allow stop; exit 2 = block, stderr returned to
# the agent.
set -eu

# --- project config (yours to edit after install — the file is your repo's) --
# The static slice of the gate, run first. Must be cheap enough to pay on
# every agent stop.
GATE_STATIC=(make check)
# The unit tier, invoked as: "${GATE_UNIT[@]}" SYS="<derived slices>". An empty
# SYS means the whole tier — never silently narrower than "all".
GATE_UNIT=(make unit)
# Where per-system unit slices live: a changed top-level dir <d> with a
# matching <UNIT_SLICE_ROOT>/<d>/ becomes a slice.
UNIT_SLICE_ROOT="tests/unit"
# The branch agents' worktrees are diffed against when the scope marker does
# not record one.
DEFAULT_BASE="staging"
# The per-agent worktree marker written by tools/dev/agent-worktree.sh.
SCOPE_MARKER=".agent-scope"
# -----------------------------------------------------------------------------

# Agent-context predicate. INLINE, not sourced: an installed hook is a
# standalone file, and `source` of a library the repo may lack fails the hook
# instead of the check.
is_agent_context() {
	local root="${1:-}"
	if [ -z "$root" ]; then
		root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
	fi
	[ -n "${DEVKIT_AGENT_SCOPE:-}" ] && return 0
	[ -n "$root" ] && [ -f "${root}/${SCOPE_MARKER}" ]
}

INPUT="$(cat)"

# grep extractors are adequate here: the fields this hook reads are a path and
# a boolean, which never carry an escaped quote. A hook reading a COMMAND must
# use a real JSON parser instead (see cc-commit-pathspec.sh for why).
json_str() {
	printf '%s' "$INPUT" \
		| grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" \
		| head -1 \
		| sed -E "s/.*:[[:space:]]*\"([^\"]*)\"/\1/"
}
json_bool() {
	printf '%s' "$INPUT" \
		| grep -oE "\"$1\"[[:space:]]*:[[:space:]]*(true|false)" \
		| head -1 \
		| grep -oE '(true|false)' || true
}

# Re-entrancy guard: if Claude Code is already continuing because of a prior
# Stop-hook block, do not block again (avoids a gate loop).
[ "$(json_bool stop_hook_active)" = "true" ] && exit 0

SESSION_CWD="$(json_str cwd)"
[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"

REPO_ROOT="$(git -C "$SESSION_CWD" rev-parse --show-toplevel 2>/dev/null || true)"
# Not inside a repo → nothing to gate.
[ -n "$REPO_ROOT" ] || exit 0

# Agent-context only — the trunk session stops constantly and must not be
# gated. Tested against the SESSION's repo root, not this process's CWD.
is_agent_context "$REPO_ROOT" || exit 0

cd "$REPO_ROOT"

# No Makefile → no gate to run. Fail OPEN, out loud in the design: a stop gate
# installed ahead of the dev loop must not wedge every agent stop in the
# meantime.
[ -f Makefile ] || exit 0

# Scope the unit tier to the changed-system slices, not the whole tier, so a
# long agent session that stops many times pays a sub-suite cost. Derive SYS=
# from the diff vs the worktree's base branch: each changed path's leading dir
# that ALSO has a <UNIT_SLICE_ROOT>/<dir>/ slice becomes a slice. No mapping →
# whole tier (safe default; never silently narrower than "all").
UNIT_SLICES=""
base_branch="$DEFAULT_BASE"
if [ -f "${REPO_ROOT}/${SCOPE_MARKER}" ]; then
	b="$(grep -E '^base=' "${REPO_ROOT}/${SCOPE_MARKER}" | head -1 | cut -d= -f2-)"
	[ -n "$b" ] && base_branch="$b"
fi
if git rev-parse --verify --quiet "$base_branch" >/dev/null 2>&1; then
	changed_dirs="$(git diff --name-only "$base_branch"...HEAD 2>/dev/null \
		| awk -F/ 'NF>1 {print $1}' | sort -u)"
	for d in $changed_dirs; do
		if [ -d "${UNIT_SLICE_ROOT}/$d" ]; then
			UNIT_SLICES="${UNIT_SLICES:+$UNIT_SLICES }$d"
		fi
	done
fi

# Run the gate, captured so the agent gets the failure text, not a bare exit
# code. mktemp without -t (GNU/BSD-consistent — BSD treats -t's arg as a prefix
# and appends its own suffix, leaving the literal XXXXXX unsubstituted).
GATE_LOG="$(mktemp "${TMPDIR:-/tmp}/cc-stop-gate.XXXXXX")"
trap 'rm -f "$GATE_LOG"' EXIT

if "${GATE_STATIC[@]}" >"$GATE_LOG" 2>&1 \
		&& "${GATE_UNIT[@]}" SYS="$UNIT_SLICES" >>"$GATE_LOG" 2>&1; then
	exit 0
fi

unit_desc="${UNIT_SLICES:-<all>}"
{
	echo "BLOCKED (Stop gate): the fast verification gate is RED — do not finish yet."
	echo "  gate: ${GATE_STATIC[*]} && ${GATE_UNIT[*]} SYS=\"${unit_desc}\""
	echo "  ---- output (tail) ----"
	tail -n 60 "$GATE_LOG"
	echo "  -----------------------"
	echo "  Fix the failures above, then stop again. Re-run locally:"
	echo "    ${GATE_STATIC[*]} && ${GATE_UNIT[*]} SYS=\"${unit_desc}\""
} >&2
exit 2
