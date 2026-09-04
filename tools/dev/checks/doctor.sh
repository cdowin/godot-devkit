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
# The Godot project file, and the engine's import cache beside it. A repo with
# no PROJECT_FILE is not a Godot project and the uid check below stays silent.
PROJECT_FILE="project.godot"
IMPORT_DIR=".godot"
# How many missing sidecars the uid verdict names before it stops listing.
UID_REPORT_LIMIT=5
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

# --- GUT addon (make unit) — CRITICAL once the project has a unit tier -------
# Three states, not two. A project with NO addons/gut at all has no unit tier
# yet: that is a fresh project, not a broken toolchain, and failing it would
# make `make doctor` un-greenable on day one — the one day it is most likely to
# be run. A project that HAS the addon directory and is missing the entry point
# is genuinely broken, and that still fails.
GUT_DIR="$(dirname "$GUT_ENTRY")"
if [ -f "$GUT_ENTRY" ]; then
	pass "GUT addon ($GUT_ENTRY)"
elif [ -d "$GUT_DIR" ]; then
	fail "GUT addon incomplete" \
	     "$GUT_DIR/ is present but $GUT_ENTRY is absent — 'make unit' cannot run the unit tier. Restore the addon."
else
	warn "GUT addon not installed ($GUT_DIR/ absent)" \
	     "'make unit' has no unit tier to run until you add GUT. Install it into $GUT_DIR/ when you want one."
fi

# --- the uid index vs the .uid sidecars this repo tracks — CRITICAL ----------
# Godot's uid index ($IMPORT_DIR/uid_cache.bin) can lose entries for files it
# already knew about, and an import pass against the EXISTING directory does
# not put them back — measured three times in a consumer, including once after
# deleting uid_cache.bin alone: 1780 entries and the same 56 missing every
# time. `rm -rf .godot` then a rebuild gave 1822. In that state every scenario
# boots, passes its own assertions, and is FAILED by the runner's
# `invalid UID … using text path instead` sweep: 147 of 147, green inside.
# That is a broken toolchain by this file's own definition — the gates cannot
# run here — so it is a FAIL, and it is one line before the sweep rather than
# 147 reports after it.
#
# HOW MEMBERSHIP IS DECIDED, and why it is not `grep -F -f` over the binary.
# Every path in the cache is preceded by the high byte of its u32 length, which
# is always NUL, so translating non-printables to newlines lands every path at
# the START of a token. Membership is then "some token begins with this path",
# in awk. The obvious `grep -a -o -F -f <paths> uid_cache.bin` was measured and
# rejected: BSD grep and ugrep 7.8.4 disagreed by 75 paths on the same 110 KB
# cache, so the verdict would have depended on which grep the host installed —
# a check that answers differently per machine is not a check.
#
# Two things it must not lie about, both of them tested:
#   - a directory carrying `.gdignore` is invisible to the editor filesystem,
#     so nothing under it is ever indexed and its sidecars are not a shortfall.
#     The exclusion is by PREFIX, never a substring: `res://a/` must not drop
#     `res://x/a/b.gd`.
#   - a token beginning with `res://a/x.gd` may be the entry for
#     `res://a/x.gdshader`, so a path that is a proper PREFIX of another
#     expected path cannot be decided this way at all. Those are reported as
#     unverifiable and left OUT of the census rather than counted present — a
#     check that is only usually exact is not a check. Sorted order puts every
#     extension of a path immediately after it, so the adjacent comparison
#     below finds all of them.
if [ -f "$PROJECT_FILE" ]; then
	if ! command -v git >/dev/null 2>&1 \
		|| ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		warn "uid index unchecked — this is not a git work tree" \
		     "The check reads the tracked .uid sidecars; without git there is no roster to compare against."
	elif [ ! -f "$IMPORT_DIR/uid_cache.bin" ]; then
		warn "no $IMPORT_DIR/uid_cache.bin — the import cache has never been built here" \
		     "run: make import-cache  — a cold checkout has no $IMPORT_DIR/, and every gate that boots will be noisy until it does."
	else
		uid_tmp="$(mktemp -d "${TMPDIR:-/tmp}/gdk-doctor-uid.XXXXXX")"
		# res:// prefixes the editor never scans. An EMPTY prefix would exclude
		# everything and empty the census in silence, so a repo-root .gdignore
		# (which would mean "index nothing") is dropped rather than honored.
		find . -name .gdignore -not -path './.git/*' 2>/dev/null \
			| sed 's|^\./||; s|\.gdignore$||; s|^|res://|' \
			| grep -v '^res://$' | sort -u > "$uid_tmp/ignored"
		git ls-files -- '*.uid' | sed 's|\.uid$||; s|^|res://|' | sort -u \
			> "$uid_tmp/tracked"
		# FILENAME==first, never NR==FNR: an EMPTY first file makes the second
		# one satisfy NR==FNR and the whole roster loads as patterns.
		awk -v first="$uid_tmp/ignored" '
			FILENAME == first { ignored[++n] = $0; next }
			{ for (i = 1; i <= n; i++) if (index($0, ignored[i]) == 1) next
			  print }' \
			"$uid_tmp/ignored" "$uid_tmp/tracked" > "$uid_tmp/scanned"
		awk 'NR>1 && index($0, prev)==1 {print prev} {prev=$0}' "$uid_tmp/scanned" \
			| sort -u > "$uid_tmp/unverifiable"
		if [ -s "$uid_tmp/unverifiable" ]; then
			comm -23 "$uid_tmp/scanned" "$uid_tmp/unverifiable" > "$uid_tmp/census"
		else
			cp "$uid_tmp/scanned" "$uid_tmp/census"
		fi
		uid_total="$(wc -l < "$uid_tmp/census" | tr -d ' ')"
		if [ "$uid_total" -eq 0 ]; then
			: > "$uid_tmp/missing"
		else
			LC_ALL=C tr -c '[:print:]' '\n' < "$IMPORT_DIR/uid_cache.bin" \
				| grep '^res://' | sort -u > "$uid_tmp/tokens"
			awk -v first="$uid_tmp/tokens" '
				FILENAME == first { token[++n] = $0; next }
				{ for (i = 1; i <= n; i++) if (index(token[i], $0) == 1) next
				  print }' \
				"$uid_tmp/tokens" "$uid_tmp/census" > "$uid_tmp/missing"
		fi
		uid_missing="$(wc -l < "$uid_tmp/missing" | tr -d ' ')"
		uid_unverifiable="$(wc -l < "$uid_tmp/unverifiable" | tr -d ' ')"
		if [ "$uid_missing" -eq 0 ]; then
			pass "uid index covers $uid_total tracked .uid sidecar(s)"
		else
			fail "uid index is STALE — $uid_missing of $uid_total tracked .uid sidecar(s) are missing from $IMPORT_DIR/uid_cache.bin" \
			     "run: rm -rf $IMPORT_DIR && make import-cache  — an import pass against the EXISTING $IMPORT_DIR does NOT restore entries it already lost, so 'make import-cache' alone will not fix this."
			head -"$UID_REPORT_LIMIT" "$uid_tmp/missing" | sed 's|^|          |'
			[ "$uid_missing" -le "$UID_REPORT_LIMIT" ] \
				|| printf '          … and %s more\n' "$((uid_missing - UID_REPORT_LIMIT))"
		fi
		if [ "$uid_unverifiable" -ne 0 ]; then
			warn "$uid_unverifiable sidecar path(s) unverifiable — each is a proper prefix of another, which a substring search cannot tell apart" \
			     "They are excluded from the $uid_total above. Rename one of each pair, or check them by hand:"
			sed 's|^|          |' "$uid_tmp/unverifiable"
		fi
		rm -rf "$uid_tmp"
	fi
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
# Check EVERY hook entry point — core.hooksPath silently skips a hook it cannot
# run, so a lost +x (a checkout onto a filesystem that drops it), a symlink
# whose target went away, or a directory that took a hook's name each disarms a
# guard with no other signal. Asked of the directory, not of a roster: a roster
# silently skips the hook added after it was written, and git's hook universe
# is every entry in the directory. Skipping a non-regular entry on `-f` made
# this census read SMALLER than the directory with no line saying so, which is
# the one thing a census must never do. The `_*` sourced-library and `*.local`
# config shapes are the only exclusions.
if [ -d "$HOOKS_PATH" ]; then
	hooks_seen=0
	for hook in "$HOOKS_PATH"/*; do
		# The ONLY skip: an unmatched glob, which is the literal pattern and
		# is neither present nor a symlink. `-e` alone is false for a broken
		# symlink, which is precisely an entry that must be reported.
		[ -e "$hook" ] || [ -L "$hook" ] || continue
		h="$(basename "$hook")"
		case "$h" in _*|*.local) continue ;; esac
		hooks_seen=1
		if [ ! -f "$hook" ]; then
			fail "tracked hook $h is not a regular file git can exec" \
			     "It is on disk under $HOOKS_PATH/ and git cannot start it, so whatever guard that name stands for runs nothing. Restore what it points at, remove it, or rename it _$h if it is not a hook."
		elif [ -x "$hook" ]; then
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
