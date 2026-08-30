#!/usr/bin/env bash
# cc-godot-sandbox.sh — Claude Code PreToolUse Bash hook: never a raw engine boot.
#
# A headless Godot boot runs the project's full autoload stack (save flush,
# run-log appends) against whatever `user://` resolves to — the developer's
# LIVE game data. A week of scenario runs once littered ~40 synthetic save
# dirs into the real user://saves/ before anyone noticed; the fix, and the
# only thing that prevents a recurrence, is the HOME override in the project's
# sandbox wrapper (SANDBOX_OWNER, project config below). Every scripted target
# routes through that. A hand-typed `godot --headless` does not. So: hard
# BLOCK, with the wrapper that owns the job named in the message.
#
# HOW THIS DOES NOT BRICK THE DEV LOOP. The wrappers themselves exec godot
# constantly and MUST keep working. They do: a PreToolUse hook observes the
# command the agent TYPED into the Bash tool, never the subprocesses that
# command goes on to spawn. `make unit` reaches this hook as the four
# characters `make unit`. The guard therefore matches only an invocation of
# godot in COMMAND POSITION within the typed line — which is precisely "an
# agent typed it" and never "a wrapper did its job".
#
# KNOWN, ACCEPTED GAP. The guard sees the typed line, never the shell's
# expansion of it. A godot-NAMED variable in command position (`$GODOT`,
# `"${GODOT}"`, `"$godot_bin"`) is resolved below by stripping quotes, `$`
# and `{}` from the command word. An engine behind an ARBITRARY name
# (`ENGINE=…; $ENGINE`), or an assignment made in an earlier Bash call, is
# out of reach for a static hook without expansion — that residue is the
# fail-open design working as declared, not an unstated hole.
#
# Protocol: Claude Code feeds the PreToolUse event as JSON on stdin (tool_name,
# tool_input.command). Exit 0 = allow, exit 2 = BLOCK with stderr returned to
# the agent. Any internal failure exits 0 (fail open) — a broken hook must never
# wedge the session.
set -eu
trap 'exit 0' ERR

# --- project config (yours to edit after install — the file is your repo's) --
# The file that owns the user:// HOME sandbox — named in the BLOCK message so
# the agent is pointed at the door, not just turned away at the wall.
SANDBOX_OWNER='tools/dev/_common.sh (its "--- user:// HOME sandbox ---" block)'
# The wrapper roster the BLOCK message offers — your project's spellings.
WRAPPER_ROSTER='    make parse | make lint | make check      # static gates
    make unit SYS=<system>                   # unit tier (sliced)
    make scenario NAME=<name>                # one integration scenario, cold
    make integration ARGS="--system <x>"     # a scenario slice
    make smoke                               # the boot smoke test
    make help                                # every target, authoritative'
# -----------------------------------------------------------------------------

# hook_json_field <payload> <dotted.key>
# Echo a STRING field out of a Claude Code hook event, or nothing.
#
# INLINE, not sourced. An installed hook is a standalone file; `source` of a
# library the project does not have fails open, and a guard that fails open is
# a guard that is not there.
#
# A `grep -oE '"key"…"[^"]*"' extractor is fine for absolute paths and
# booleans. It is NOT fine for `tool_input.command`: a Bash command routinely
# embeds escaped quotes (`git commit -m \"fix\"`), and `"[^"]*"` truncates at
# the first one, handing the guard HALF a command line — which is exactly how a
# guard starts firing on commands that were fine. So the payload is decoded
# with a real JSON parser, and this yields nothing (the caller then exits 0)
# when no parser is available.
hook_json_field() {
	local payload="$1" key="$2"
	if command -v python3 >/dev/null 2>&1; then
		printf '%s' "$payload" | python3 -c '
import json, sys
try:
	node = json.load(sys.stdin)
except Exception:
	sys.exit(0)
for part in sys.argv[1].split("."):
	if not isinstance(node, dict) or part not in node:
		sys.exit(0)
	node = node[part]
if isinstance(node, str):
	sys.stdout.write(node)
' "$key" 2>/dev/null || true
	elif command -v jq >/dev/null 2>&1; then
		printf '%s' "$payload" \
			| jq -r --arg k "$key" 'getpath($k | split(".")) | select(type == "string")' 2>/dev/null || true
	fi
}

INPUT="$(cat)"

# Fast path: the overwhelming majority of Bash calls never mention the engine.
# Pure shell, no fork, no JSON decode. `*GODOT*` is for the named-variable
# spelling (`$GODOT --headless`) with no lowercase mention beside it.
case "$INPUT" in
	*godot*|*Godot*|*GODOT*) ;;
	*) exit 0 ;;
esac

[ "$(hook_json_field "$INPUT" tool_name)" = "Bash" ] || exit 0

CMD="$(hook_json_field "$INPUT" tool_input.command)"
[ -n "$CMD" ] || exit 0   # unparseable payload → fail open

# A heredoc BODY is data, not commands — an agent writing a doc or a script that
# quotes `godot --headless` is not booting anything. Everything from the first
# `<<` on is body (and a heredoc is not how anyone runs the engine). A `<<<`
# HERESTRING is not a heredoc: its payload is one inline word and the command
# line CONTINUES after it, so truncating at it would hide a boot typed after
# the herestring. Neutralize herestrings first; the placeholder glues onto the
# data word so that word can never be misread as a fresh command word.
ANALYZE="${CMD//<<</ __NBHSTR__}"
ANALYZE="${ANALYZE%%<<*}"

# Wrapper words that legitimately precede a real command word.
is_wrapper() {
	case "$1" in
		env|time|nohup|exec|command|nice|sudo|xargs|caffeinate|stdbuf|timeout|gtimeout) return 0 ;;
		[A-Za-z_]*=*) return 0 ;;   # leading VAR=value assignment
		*) return 1 ;;
	esac
}

offender=""
# Split at shell operators so each segment starts at a command word. `$(`, a
# backtick and a brace group all start a fresh command too.
# shellcheck disable=SC2020  # the tr below maps a char SET to newline — exactly the intent
while IFS= read -r segment; do
	[ -n "$segment" ] || continue
	# shellcheck disable=SC2206  # deliberate word-split; read -ra avoids globbing
	IFS=' 	' read -ra toks <<<"$segment"
	[ "${#toks[@]}" -gt 0 ] || continue

	idx=0
	shifted=0
	in_command=0
	resolves_only=0
	while [ "$idx" -lt "${#toks[@]}" ]; do
		tok="${toks[$idx]}"
		if is_wrapper "$tok"; then
			if [ "$tok" = "command" ]; then in_command=1; fi
			idx=$((idx + 1)); shifted=1; continue
		fi
		# Only AFTER a wrapper do flags / durations belong to it (`timeout 60`,
		# `command -v`); in first position they mean this is not a command word.
		if [ "$shifted" -eq 1 ]; then
			case "$tok" in
				-v|-V)
					# `command -v godot` RESOLVES the binary and runs nothing.
					if [ "$in_command" -eq 1 ]; then resolves_only=1; fi
					idx=$((idx + 1)); continue ;;
				-*|[0-9]*) idx=$((idx + 1)); continue ;;
			esac
		fi
		break
	done
	[ "$idx" -lt "${#toks[@]}" ] || continue
	[ "$resolves_only" -eq 0 ] || continue

	# The command word itself: `godot`, `godot4`, `./godot`, a full
	# /Applications/Godot.app/Contents/MacOS/Godot path — or the engine behind
	# a godot-NAMED variable (`$GODOT`, `"${GODOT}"`, `"$godot_bin"`): quotes,
	# `$` and `{}` are stripped first, so those resolve to a godot* token (the
	# arbitrary-name case is the accepted gap in the header). `godot-devkit`
	# is this toolkit's own CLI in command position — never a boot.
	command_word="${toks[$idx]//[\$\{\}\"\']/}"
	command_word="${command_word##*/}"
	case "$(printf '%s' "$command_word" | tr '[:upper:]' '[:lower:]')" in
		godot-devkit) continue ;;
		godot*) ;;
		*) continue ;;
	esac

	# The ONLY raw invocations that boot nothing are the pure version/help
	# queries — and only when the WHOLE invocation is one. Everything else
	# reaches real state: a boot flag (`--headless`, `-e`/`--editor`,
	# `--import`, `-s`/`--script`, `--path`, …), a bare scene or project
	# path positional (`godot main.tscn`, `godot .`), and bare `godot`
	# itself (the project manager is a real boot against the real user://).
	# Matching per-token also closes the smuggle: a `--help` buried in a
	# boot's argument list no longer waves the boot through.
	argi=$((idx + 1))
	query_only=1
	if [ "$argi" -ge "${#toks[@]}" ]; then
		query_only=0   # bare `godot` — a boot, not a query
	fi
	while [ "$argi" -lt "${#toks[@]}" ]; do
		case "${toks[$argi]}" in
			--version|--help|-h) argi=$((argi + 1)) ;;
			*) query_only=0; break ;;
		esac
	done
	if [ "$query_only" -eq 1 ]; then
		continue
	fi

	offender="$segment"
	break
done <<<"$(printf '%s' "$ANALYZE" | tr ';|&()`{}' '\n\n\n\n\n\n\n\n')"

[ -n "$offender" ] || exit 0

{
	echo "BLOCKED (user:// sandbox): never invoke \`godot\` directly."
	echo "  offending segment: ${offender# }"
	echo ""
	echo "  A raw boot runs the full autoload stack against the REAL user:// —"
	echo "  the LIVE game data. Only the scripted wrappers redirect it, by"
	echo "  overriding HOME ($SANDBOX_OWNER:"
	echo "  a week of scenario runs once littered ~40 synthetic save dirs into the"
	echo "  live user://saves/). There is no exception to this."
	echo ""
	echo "  Use the wrapper that owns the job:"
	echo "$WRAPPER_ROSTER"
	echo ""
	echo "  (The wrappers call godot themselves and are unaffected — this guard"
	echo "   only ever sees the command YOU type into the Bash tool.)"
} >&2
exit 2
