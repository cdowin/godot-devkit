#!/usr/bin/env bash
# doctor.sh — verify the dev toolchain. Wire it as `make doctor`.
#
# Reports every dependency the dev-loop gates rely on, with an actionable fix
# for anything missing. Designed to be the FIRST thing a cold agent or new
# contributor runs: it answers "can this environment run the gates at all?"
# before a cryptic mid-run failure has to.
#
# The dependency roster below is the stock godot-devkit consumer dev loop
# (godot + gdlint + uv + shellcheck + GUT + the tracked hooks + make). After
# install the file is your repo's — edit the roster to match your gates.
#
# Exit: 0 = all critical deps present (the gates can run), 1 = a critical dep
# is missing (the fix is printed).
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

# --- project config (yours to edit after install — the file is your repo's) --
GODOT_EXPECT="4.6"
# The tracked-hooks directory git points at via core.hooksPath.
HOOKS_PATH="tools/hooks"
# The GUT test-runner entry point `make unit` needs.
GUT_ENTRY="addons/gut/gut_cmdln.gd"
# -----------------------------------------------------------------------------

crit_fail=0

# Colorize only on a TTY (keeps captured/CI output clean).
if [ -t 1 ]; then C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""; fi

pass(){ printf "  %sok%s    %s\n" "$C_OK" "$C_OFF" "$1"; }
warn(){ printf "  %swarn%s  %s\n" "$C_WARN" "$C_OFF" "$1"; [ -n "${2:-}" ] && printf "        \xe2\x86\xb3 %s\n" "$2"; }
fail(){ printf "  %sFAIL%s  %s\n" "$C_ERR" "$C_OFF" "$1"; [ -n "${2:-}" ] && printf "        \xe2\x86\xb3 %s\n" "$2"; crit_fail=1; }

echo "Toolchain doctor"
echo

# --- godot (parse / unit / integration / scenario gates) — CRITICAL ----------
# `godot --version` prints and exits; it boots nothing.
if command -v godot >/dev/null 2>&1; then
	ver="$(godot --version 2>/dev/null | head -1)"
	if printf '%s' "$ver" | grep -q "$GODOT_EXPECT"; then
		pass "godot $ver"
	else
		warn "godot present but version '$ver' (gates target $GODOT_EXPECT.x)" \
		     "Install Godot $GODOT_EXPECT — behavior on other versions is unverified."
	fi
else
	fail "godot not on PATH" \
	     "Install Godot $GODOT_EXPECT and put 'godot' on PATH — the engine-backed gates cannot run without it."
fi

# --- gdlint (make lint) — CRITICAL -------------------------------------------
if command -v gdlint >/dev/null 2>&1; then
	pass "gdlint $(gdlint --version 2>/dev/null | head -1)"
else
	fail "gdlint not on PATH" \
	     "pip install gdtoolkit (or pipx install gdtoolkit) — provides gdlint for 'make lint'."
fi

# --- uv (the godot-devkit gates) — CRITICAL ----------------------------------
# The devkit gates (check uid/tres/doc/… + the introspect targets) run the
# pinned godot-devkit package via uvx, so a missing uv kills those rungs.
if command -v uv >/dev/null 2>&1; then
	pass "uv $(uv --version 2>/dev/null | awk '{print $2}')"
else
	fail "uv not on PATH" \
	     "brew install uv — the devkit gates invoke the pinned godot-devkit via uvx."
fi

# --- shellcheck — WARN (SHOULD-have dev dep) ---------------------------------
# The shell static gate skips cleanly without it (so `make check` won't
# hard-fail on a host that lacks it), but then the shell scripts go unlinted —
# so its absence is a WARN, not gate-blocking.
if command -v shellcheck >/dev/null 2>&1; then
	pass "shellcheck $(shellcheck --version 2>/dev/null | awk '/version:/{print $2}')"
else
	warn "shellcheck not on PATH" \
	     "brew install shellcheck — the shell static gate is skipped without it."
fi

# --- GUT addon (make unit) — CRITICAL ----------------------------------------
if [ -f "$GUT_ENTRY" ]; then
	pass "GUT addon ($GUT_ENTRY)"
else
	fail "GUT addon missing" \
	     "$GUT_ENTRY absent — 'make unit' cannot run the unit tier. Restore the addon."
fi

# --- git hooks via core.hooksPath (guards + auto-gate + push safety) ---------
# The tracked hooks under $HOOKS_PATH enforce the agent-isolation guards and
# the auto-gate. They are activated by pointing git at the tracked dir (so they
# apply across every worktree and are version-controlled, not stranded in
# .git/hooks). doctor SETS it if unset/wrong, then verifies — a cold checkout
# is one doctor run away from a guarded tree.
hookspath="$(git config --get core.hooksPath 2>/dev/null || true)"
if [ "$hookspath" != "$HOOKS_PATH" ]; then
	if git config core.hooksPath "$HOOKS_PATH" 2>/dev/null; then
		pass "git core.hooksPath set to $HOOKS_PATH (was '${hookspath:-unset}')"
	else
		fail "could not set git core.hooksPath" \
		     "run: git config core.hooksPath $HOOKS_PATH  — activates the tracked guard/gate hooks."
	fi
else
	pass "git core.hooksPath = $HOOKS_PATH"
fi
# Check the exec bit on EVERY hook entry point — core.hooksPath silently skips
# a non-executable hook, so a lost +x (a checkout onto a filesystem that drops
# it) disarms a guard with no other signal. Asked of the directory, not of a
# roster: a roster silently skips the hook added after it was written. The
# `_*` sourced-library and `*.local` config shapes are the only exclusions.
if [ -d "$HOOKS_PATH" ]; then
	hooks_seen=0
	for hook in "$HOOKS_PATH"/*; do
		[ -f "$hook" ] || continue
		h="$(basename "$hook")"
		case "$h" in _*|*.local) continue ;; esac
		hooks_seen=1
		if [ -x "$hook" ]; then
			pass "tracked hook $h present + executable"
		else
			fail "tracked hook $h not executable" \
			     "chmod +x $hook  (or run: bash tools/setup-hooks.sh) — core.hooksPath skips it in silence."
		fi
	done
	[ "$hooks_seen" -eq 1 ] || warn "no tracked hooks under $HOOKS_PATH/" \
	     "godot-devkit install-hooks ships the guard corpus; bash tools/setup-hooks.sh arms it."
else
	warn "no $HOOKS_PATH/ directory" \
	     "godot-devkit install-hooks ships the guard corpus; bash tools/setup-hooks.sh arms it."
fi

# --- make itself -------------------------------------------------------------
make_ver="$(make --version 2>/dev/null | head -1)"
pass "$make_ver"
case "$make_ver" in
	*3.8[01]*)
		warn "make $make_ver predates 3.82" \
		     "macOS make 3.81 silently ignores .SHELLFLAGS strict-mode — recipes must be robust without it; informational only." ;;
esac

echo
if [ "$crit_fail" -eq 0 ]; then
	echo "[DOCTOR] PASS — toolchain ready (run 'make help' for the target list)"
else
	echo "[DOCTOR] FAIL — fix the items above before running the gates"
fi
exit "$crit_fail"
