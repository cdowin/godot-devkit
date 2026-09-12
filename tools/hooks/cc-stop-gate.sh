#!/usr/bin/env bash
# cc-stop-gate.sh — Claude Code Stop hook: when an AGENT tries to finish, run
# the project's fast gate; on red, block the stop (exit 2) with the gate output
# on stderr so the agent fixes before claiming done. Agent context only — the
# scope marker or DEVKIT_AGENT_SCOPE; the orchestrator's trunk session is never
# gated, because it stops constantly — it is only TOLD when `check pm` names a
# ready close (its CLOSE lines), and CLOSE_READY decides whether that informs or
# holds the stop once. Stdin: the Stop event JSON (cwd, stop_hook_active).
# Exit 0 = allow, exit 2 = block.
set -eu

# --- project config (yours to edit after install — the file is your repo's) --
# The static slice of the gate, run first; cheap enough to pay on every agent stop.
# godot-devkit: `check` is the agentic-sdlc gates plus this package's own
# `godot-check` ([gates] extra), seconds together.
GATE_STATIC=(make check)
# The unit tier, run as "${GATE_UNIT[@]}" SYS="<slices>"; an empty SYS is the whole tier.
# godot-devkit: `pyunit` is the suite minus the spawns (-m "not shell"), seconds;
# it has no per-system slices, so SYS is accepted and ignored.
GATE_UNIT=(make pyunit)
# A changed top-level dir <d> with a <UNIT_SLICE_ROOT>/<d>/ becomes a slice.
UNIT_SLICE_ROOT="tests/unit"
# The diff base when the scope marker records none. godot-devkit works on
# `milestone/<id>` branches cut from `main` (SDLC.md §1); there is no staging.
DEFAULT_BASE="main"
# The per-agent worktree marker written by tools/dev/agent-worktree.sh.
SCOPE_MARKER=".agent-scope"
# The trunk session's ask, grepped for `check pm`'s `(CLOSE)` lines; empty = never ask.
CLOSE_ASK=(make -s sdlc ARGS="check pm")
# A ready close at the trunk session's stop: "inform" names it; "block" holds the stop once.
CLOSE_READY="inform"
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p GATE_STATIC >/dev/null 2>&1 || GATE_STATIC=(make check)
declare -p GATE_UNIT >/dev/null 2>&1 || GATE_UNIT=(make unit)
declare -p UNIT_SLICE_ROOT >/dev/null 2>&1 || UNIT_SLICE_ROOT="tests/unit"
declare -p DEFAULT_BASE >/dev/null 2>&1 || DEFAULT_BASE=""
declare -p SCOPE_MARKER >/dev/null 2>&1 || SCOPE_MARKER=".agent-scope"
declare -p CLOSE_ASK >/dev/null 2>&1 || CLOSE_ASK=(make -s sdlc ARGS="check pm")
declare -p CLOSE_READY >/dev/null 2>&1 || CLOSE_READY="inform"

# Inline, not sourced: a library the repo may lack would fail the hook.
is_agent_context() {
	local root="${1:-}"
	if [ -z "$root" ]; then
		root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
	fi
	[ -n "${DEVKIT_AGENT_SCOPE:-}" ] && return 0
	[ -n "$root" ] && [ -f "${root}/${SCOPE_MARKER}" ]
}

INPUT="$(cat)"
# Unreadable payload: exit 0 with the reason, before the agent-context test.
case "${INPUT#"${INPUT%%[![:space:]]*}"}" in
	'{'*) ;;
	*) echo "cc-stop-gate: payload is not JSON; allowing the stop" >&2; exit 0 ;;
esac

# grep extractors suffice for a path and a boolean; a COMMAND needs a real parser.
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
# Stdin as one JSON string body: backslash, quote and tab escaped, lines joined by \n.
json_escape() {
	sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/	/\\t/g' \
		| awk 'NR > 1 { printf "\\n" } { printf "%s", $0 }'
}

# Re-entrancy guard: a stop already continuing from a prior block is not blocked again.
[ "$(json_bool stop_hook_active)" = "true" ] && exit 0

SESSION_CWD="$(json_str cwd)"
[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"

REPO_ROOT="$(git -C "$SESSION_CWD" rev-parse --show-toplevel 2>/dev/null || true)"
# Not inside a repo → nothing to gate.
[ -n "$REPO_ROOT" ] || exit 0

# Tested against the SESSION's repo root, not this process's cwd. The trunk
# session is never gated; a ready close is NAMED at its stop, because a CLOSE
# line nobody reads before the session ends is read a session late.
if ! is_agent_context "$REPO_ROOT"; then
	if [ "${#CLOSE_ASK[@]}" -eq 0 ] || [ ! -f "${REPO_ROOT}/Makefile" ]; then
		exit 0
	fi
	ready="$(cd "$REPO_ROOT" || exit 0
		"${CLOSE_ASK[@]}" 2>/dev/null \
			| grep -E '\(CLOSE\)[[:space:]]*$' \
			| sed -E 's/^[[:space:]]*(WARN[[:space:]]+)?//')" || ready=''
	[ -n "$ready" ] || exit 0
	if [ "$CLOSE_READY" = "block" ]; then
		{
			echo "BLOCKED (Stop gate): a close is ready — run it, or say why it waits, then stop again:"
			printf '%s\n' "$ready" | sed 's/^/  /'
		} >&2
		exit 2
	fi
	[ "$CLOSE_READY" = "inform" ] \
		|| echo "cc-stop-gate: CLOSE_READY='${CLOSE_READY}' is neither inform nor block — informing" >&2
	message="$(printf '%s\n%s\n%s\n' 'Stop gate: a close is ready —' "$ready" \
		'(CLOSE_READY="block" in tools/hooks/cc-stop-gate.sh holds the stop instead)' \
		| json_escape)"
	printf '{"systemMessage": "%s"}\n' "$message"
	exit 0
fi

cd "$REPO_ROOT"

# No Makefile, no gate: fail open.
[ -f Makefile ] || exit 0

# Scope the unit tier to the changed-system slices; no mapping means the whole tier.
UNIT_SLICES=""
base_branch="$DEFAULT_BASE"
if [ -f "${REPO_ROOT}/${SCOPE_MARKER}" ]; then
	b="$(grep -E '^base=' "${REPO_ROOT}/${SCOPE_MARKER}" | head -1 | cut -d= -f2-)"
	[ -n "$b" ] && base_branch="$b"
fi
# An empty base is READ from the remote's HEAD, never guessed; a remote with no
# HEAD leaves the name `origin/HEAD`, which the check below names.
if [ -z "$base_branch" ]; then
	base_branch="$(git symbolic-ref --short -q refs/remotes/origin/HEAD 2>/dev/null || true)"
	[ -n "$base_branch" ] || base_branch="origin/HEAD"
fi
if ! git rev-parse --verify --quiet "$base_branch" >/dev/null 2>&1; then
	echo "cc-stop-gate: base '${base_branch}' does not resolve — running the WHOLE unit tier (set DEFAULT_BASE in tools/hooks/cc-stop-gate.sh, or the marker's base=)" >&2
else
	changed_dirs="$(git diff --name-only "$base_branch"...HEAD 2>/dev/null \
		| awk -F/ 'NF>1 {print $1}' | sort -u)"
	for d in $changed_dirs; do
		if [ -d "${UNIT_SLICE_ROOT}/$d" ]; then
			UNIT_SLICES="${UNIT_SLICES:+$UNIT_SLICES }$d"
		fi
	done
fi

# Captured so the agent gets the failure text; mktemp without -t, which BSD treats as a prefix.
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
