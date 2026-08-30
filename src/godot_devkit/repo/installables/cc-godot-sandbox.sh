#!/usr/bin/env bash
# cc-godot-sandbox.sh — Claude Code PreToolUse Bash hook: never a raw engine boot.
#
# A headless Godot boot runs the full autoload stack (GameManager save flush,
# run-log appends) against whatever `user://` resolves to — and on this machine
# that is Chris's LIVE game data. A week of scenario runs once littered ~40
# synthetic save dirs into the real user://saves/ before anyone noticed; the
# fix, and the only thing that prevents a recurrence, is the HOME override in
# tools/dev/_common.sh (see its "--- user:// HOME sandbox ---" block). Every
# `make` target routes through that. A hand-typed `godot --headless` does not.
# So: hard BLOCK, with the wrapper that owns the job named in the message.
#
# HOW THIS DOES NOT BRICK THE DEV LOOP. The wrappers themselves exec godot
# constantly (parse.sh, unit.sh, scenario.sh, warnings.sh, cc-session-start.sh)
# and MUST keep working. They do: a PreToolUse hook observes the command the
# agent TYPED into the Bash tool, never the subprocesses that command goes on to
# spawn. `make unit` reaches this hook as the four characters `make unit`. The
# guard therefore matches only an invocation of godot in COMMAND POSITION within
# the typed line — which is precisely "an agent typed it" and never "a wrapper
# did its job".
#
# Protocol: Claude Code feeds the PreToolUse event as JSON on stdin (tool_name,
# tool_input.command). Exit 0 = allow, exit 2 = BLOCK with stderr returned to
# the agent. Any internal failure exits 0 (fail open) — a broken hook must never
# wedge the session.
set -eu
trap 'exit 0' ERR

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
# Pure shell, no fork, no JSON decode.
case "$INPUT" in
	*godot*|*Godot*) ;;
	*) exit 0 ;;
esac

[ "$(hook_json_field "$INPUT" tool_name)" = "Bash" ] || exit 0

CMD="$(hook_json_field "$INPUT" tool_input.command)"
[ -n "$CMD" ] || exit 0   # unparseable payload → fail open

# A heredoc BODY is data, not commands — an agent writing a doc or a script that
# quotes `godot --headless` is not booting anything. Everything from the first
# `<<` on is body (and a heredoc is not how anyone runs the engine).
ANALYZE="${CMD%%<<*}"

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
	while [ "$idx" -lt "${#toks[@]}" ]; do
		tok="${toks[$idx]}"
		if is_wrapper "$tok"; then
			idx=$((idx + 1)); shifted=1; continue
		fi
		# Only AFTER a wrapper do flags / durations belong to it (`timeout 60`,
		# `command -v`); in first position they mean this is not a command word.
		if [ "$shifted" -eq 1 ]; then
			case "$tok" in
				-*|[0-9]*) idx=$((idx + 1)); continue ;;
			esac
		fi
		break
	done
	[ "$idx" -lt "${#toks[@]}" ] || continue

	# The command word itself: `godot`, `godot4`, `./godot`, or a full
	# /Applications/Godot.app/Contents/MacOS/Godot path.
	command_word="${toks[$idx]##*/}"
	case "$(printf '%s' "$command_word" | tr '[:upper:]' '[:lower:]')" in
		godot|godot4|godot_v*) ;;
		*) continue ;;
	esac

	# `godot --version` / `--help` boot nothing and touch no user data.
	case " $segment " in
		*" --version"*|*" --help"*) continue ;;
	esac

	# Flags that open the PROJECT — the ones that reach user://.
	case " $segment " in
		*" --headless"*|*" --editor"*|*" --import"*|*" --script"*|*" -s "*|*" --path"*|*" --main-pack"*)
			offender="$segment"
			break
			;;
	esac
done <<<"$(printf '%s' "$ANALYZE" | tr ';|&()`{}' '\n\n\n\n\n\n\n\n')"

[ -n "$offender" ] || exit 0

{
	echo "BLOCKED (user:// sandbox): never invoke \`godot\` directly."
	echo "  offending segment: ${offender# }"
	echo ""
	echo "  A raw boot runs the full autoload stack against the REAL user:// —"
	echo "  Chris's live saves. Only the make / tools/dev wrappers redirect it, by"
	echo "  overriding HOME (tools/dev/_common.sh, the user:// HOME sandbox block:"
	echo "  a week of scenario runs once littered ~40 synthetic save dirs into the"
	echo "  live user://saves/). There is no exception to this."
	echo ""
	echo "  Use the wrapper that owns the job:"
	echo "    make parse | make lint | make check      # static gates"
	echo "    make unit SYS=<system>                   # unit tier (sliced)"
	echo "    make scenario NAME=<name>                # one integration scenario, cold"
	echo "    make integration ARGS=\"--system <x>\"     # a scenario slice"
	echo "    make smoke                               # the boot smoke test"
	echo "    make help                                # every target, authoritative"
	echo ""
	echo "  (The wrappers call godot themselves and are unaffected — this guard"
	echo "   only ever sees the command YOU type into the Bash tool.)"
} >&2
exit 2
