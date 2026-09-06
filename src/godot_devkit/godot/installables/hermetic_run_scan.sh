#!/usr/bin/env bash
# hermetic_run_scan.sh — hermeticity gate: a headless run leaves NOTHING behind.
# Wire it as `make hermetic-scan`, in your static gate set.
#
# WHY THIS EXISTS. The `user://` sandbox used to be ONE durable directory shared
# by every run. It accumulated ~10,000 save dirs / 205 MB over two and a half
# months, and then a test FAILED because it counted them. A run's outcome must
# never depend on the history of every run before it — that is a false red
# today and a false green tomorrow, since accumulated state can equally MASK a
# defect.
#
# The fix lives in gdk_runners.sh: `gdk_sandbox_home` mints a per-run,
# self-destroying HOME with nothing persisted beside it. THIS file is what
# stops that silently regressing. Three checks, each a distinct failure mode:
#
#   C1 STATIC   a wrapper that sandboxes must not arm a bare `trap … EXIT`.
#               Bash has ONE EXIT slot: a bare trap CLOBBERS the sandbox's own
#               self-destruct hook, and the run then stops cleaning up in
#               silence. `gdk_on_exit` is the sanctioned registration. The
#               library's own dispatcher must still be armed — delete it and
#               every hook stops running, with C2 as the only signal.
#   C2 RUNTIME  a real child shell takes a sandbox home, writes state into it
#               and exits. Afterwards: the home is gone, the durable root
#               gained no state, and the REAL Godot user-data tree was never
#               touched.
#   C3 RESIDUE  the sandbox root holds the runs/ spool and NOTHING else. There
#               is no cache tier and no declared exception: anything else
#               sitting there outlived the run that made it.
#
# NOT A CHECK HERE: the gate-report directory. A per-scenario report spool DOES
# rot — one project's grew to 548 logs dating back two months, 396 of them for
# scenarios that no longer existed — but `gdk_gate_log` names its slot by GATE
# and clears it on every run, so that directory is bounded by construction and
# there is no reaper anyone can forget to call. A check for it would be a check
# over a shape this library cannot produce.
#
# Boots NOTHING — safe in CI and safe in parallel. The child probe is a shell,
# not an engine.
#
# Usage: tools/dev/runners/hermetic_run_scan.sh   (via `make hermetic-scan`)
#        tools/dev/runners/hermetic_run_scan.sh --help | --self-test
# Exit:  0 = hermetic | 1 = a violation | 2 = harness/usage error
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
# LIB is where `godot-devkit install-runners` put gdk_runners.sh, relative to
# THIS file. The stock layout is tools/dev/runners/ beside tools/dev/.
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
# Depth from this file to the repo root, for the stock layout above.
REPO_ROOT_FROM_HERE="../../.."
# Where wrappers live. C1 reads every shell script under here that calls the
# sandbox; a repo keeping its runners elsewhere points this at them.
GDK_SANDBOXING_SCAN_ROOT="${GDK_SANDBOXING_SCAN_ROOT:-tools/dev}"
# Env: GDK_REAL_USER_DATA_DIR  the real Godot user-data root C2 proves was not
#                              touched (default: the platform's, off the real
#                              HOME — this gate never sandboxes its OWN shell)
# -----------------------------------------------------------------------------

TAG="[hermetic]"
# The function a wrapper calls to sandbox, and the one it must register cleanup
# with. Named here because C1's whole job is telling those two apart.
SANDBOX_FN="gdk_sandbox_home"
EXIT_DISPATCHER="_gdk_run_exit_hooks"
# `trap <anything> EXIT` — the clobbering form. `gdk_on_exit …` matches nothing
# here, which is the point: the sanctioned spelling is invisible to the gate.
BARE_EXIT_TRAP_RE='^[[:space:]]*trap[[:space:]].*[[:space:]]EXIT([[:space:]]|$)'

# What the probe writes under its HOME. The basename is unique so C2 can search
# the durable root for it without knowing where a wrapper chose to put it.
PROBE_SLOT_DIRNAME="gdk-hermetic-probe-slot"
PROBE_SLOT_REL="app_userdata/probe/saves/$PROBE_SLOT_DIRNAME"
PROBE_SETTINGS_REL="app_userdata/probe/settings.json"
# What --self-test plants: a durable un-cleaned HOME (the pre-fix behaviour) and
# a persistent cache tier beside runs/ (the tier this design has none of).
SELF_TEST_DIRTY_DIRNAME="self-test-dirty-home"
SELF_TEST_DIRTY_CACHE="self-test-persistent-cache"

if [ -t 1 ]; then C_BAD=$'\033[31m'; C_OK=$'\033[32m'; C_OFF=$'\033[0m'; else C_BAD=''; C_OK=''; C_OFF=''; fi

usage() {
	cat <<'USAGE_EOF'
usage: hermetic_run_scan.sh [--help] [--self-test]

Proves a headless run leaves nothing behind: no bare EXIT trap clobbering the
sandbox self-destruct (C1), a real child run whose HOME and state are gone
afterwards with the real user:// untouched (C2), and nothing persisted beside
the runs/ spool (C3). Boots no engine.

  (no argument)  run the gate
  --self-test    plant each violation in a scratch tree and prove the checks
                 REDDEN on it — and stay green on the hermetic shape
  --help         this message

Env: GDK_RUNNERS_LIB           path to gdk_runners.sh, relative to this file
     GDK_SANDBOXING_SCAN_ROOT  where C1 looks for wrappers (default tools/dev)
     GDK_REAL_USER_DATA_DIR    the real Godot user-data root C2 guards
Exit: 0 hermetic | 1 violation | 2 harness/usage error
USAGE_EOF
}

# --- argument surface (before anything is sourced or resolved) ---------------
# Nothing, --help, or --self-test. An extra argument is refused rather than
# ignored — a caller passing one believes this takes options it does not.
if [ "$#" -gt 1 ]; then
	echo "$TAG one argument at most — got $#" >&2
	usage >&2
	exit 2
fi
SELF_TEST=0
if [ "$#" -eq 1 ]; then
	case "$1" in
		--help|-h) usage; exit 0 ;;
		--self-test) SELF_TEST=1 ;;
		*) echo "$TAG unknown argument '$1'" >&2; usage >&2; exit 2 ;;
	esac
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
# The ABSOLUTE path to this file. `$0` is relative, and the corpus below runs
# from a scratch directory — a re-invocation through `$0` would be a 127 the
# corpus would read as "the argument surface is broken".
SELF="$HERE/$(basename "${BASH_SOURCE[0]}")"
# The two files C1 does NOT read, by NAME so a rename cannot strand the rule:
# the library, where the one sanctioned `trap … EXIT` lives (gdk_on_exit arms
# the dispatcher), and THIS file, whose corpus plants the forbidden shape on
# purpose. Both are held to it by other means — shellcheck, and the corpus
# itself — so neither is unguarded; what they are is not wrappers.
C1_EXEMPT_NAMES=("$(basename "$GDK_RUNNERS_LIB")" "$(basename "${BASH_SOURCE[0]}")")
# The installed layout first. The fallback is the library sitting BESIDE this
# file, which is the package's own source tree — this toolkit is its own first
# consumer, and its corpus has to run before anything is installed anywhere.
LIB="$HERE/$GDK_RUNNERS_LIB"
[ -f "$LIB" ] || LIB="$HERE/gdk_runners.sh"
if [ ! -f "$LIB" ]; then
	echo "$TAG gdk_runners.sh not found at '$HERE/$GDK_RUNNERS_LIB' — set GDK_RUNNERS_LIB" >&2
	exit 2
fi

if [ "$SELF_TEST" = "1" ]; then
	# The corpus never touches the caller's tree: it plants its residue in a
	# scratch repo of its own. A gate whose self-test mints a sandbox spool in
	# whatever directory you ran it from is a gate that fails C3 by running.
	SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/gdk-hermetic-selftest.XXXXXX")" || exit 2
	cd "$SCRATCH" || exit 2
else
	REPO_ROOT="$(cd "$HERE/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
	cd "$REPO_ROOT" || exit 2
fi

# Sourced for its sandbox constants and its exit-hook contract. This shell NEVER
# calls gdk_sandbox_home: the real HOME is what C2 has to prove was left alone,
# so the gate must still be able to see it.
# shellcheck source=/dev/null
source "$LIB"

SANDBOX_ROOT="$PWD/$GDK_SANDBOX_DIRNAME"
RUNS_ROOT="$SANDBOX_ROOT/$GDK_SANDBOX_RUNS_SUBDIR"

violations=0
fail() { echo "${C_BAD}  ${1}${C_OFF}"; violations=$((violations + 1)); }

# --- the probe ---------------------------------------------------------------
# A CHILD SHELL, so the EXIT trap the sandbox relies on really fires. Told to be
# dirty, it takes the PRE-FIX behaviour instead (a durable shared HOME, no
# cleanup) and every assertion below MUST redden — that is what proves C2 checks
# something.
probe_script="$(mktemp "${TMPDIR:-/tmp}/gdk-hermetic-probe.XXXXXX")" || exit 2
# Registered, not trapped — C1 forbids exactly the bare form here.
# Deferred expansion is the point.
# shellcheck disable=SC2016
gdk_on_exit 'rm -f "$probe_script"'
cat > "$probe_script" <<'PROBE'
set -eu
# shellcheck source=/dev/null
source "$GDK_PROBE_LIB"
if [ "${GDK_HERMETIC_DIRTY_PROBE:-0}" = "1" ]; then
	# The REGRESSION being guarded against: a durable, shared, never-cleaned HOME.
	HOME="$PWD/$GDK_SANDBOX_DIRNAME/$GDK_PROBE_DIRTY_DIRNAME"
	export HOME
	mkdir -p "$HOME"
else
	gdk_sandbox_home
fi
echo "$HOME"
mkdir -p "$HOME/$GDK_PROBE_SLOT_REL"
mkdir -p "$(dirname "$HOME/$GDK_PROBE_SETTINGS_REL")"
echo '{"hermetic":"probe"}' > "$HOME/$GDK_PROBE_SETTINGS_REL"
PROBE

# real_user_data_dir — where the ENGINE would really write, off the real HOME:
# the thing the whole sandbox exists to protect.
real_user_data_dir() {
	if [ -n "${GDK_REAL_USER_DATA_DIR:-}" ]; then
		printf '%s\n' "$GDK_REAL_USER_DATA_DIR"
		return 0
	fi
	case "$(uname -s)" in
		Darwin) printf '%s\n' "$HOME/Library/Application Support/Godot" ;;
		*) printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/godot" ;;
	esac
}

real_user_roster() {
	find "$(real_user_data_dir)" -mindepth 1 -maxdepth 2 2>/dev/null | sort | tr '\n' ' '
}

# --- C2: a real run leaves nothing behind ------------------------------------
# <report_fn> <dirty 0|1> — so the corpus can score the same run twice: once on
# the hermetic shape (which must stay silent) and once on the pre-fix one.
scan_run_residue() {
	local report="$1" dirty="$2" before after out status home
	before="$(real_user_roster)"
	out="$(GDK_HERMETIC_DIRTY_PROBE="$dirty" \
		GDK_PROBE_LIB="$LIB" \
		GDK_PROBE_SLOT_REL="$PROBE_SLOT_REL" \
		GDK_PROBE_SETTINGS_REL="$PROBE_SETTINGS_REL" \
		GDK_PROBE_DIRTY_DIRNAME="$SELF_TEST_DIRTY_DIRNAME" \
		bash "$probe_script" 2>&1)"
	status=$?
	home="$(printf '%s\n' "$out" | tail -n 1)"

	if [ "$status" -ne 0 ] || [ -z "$home" ]; then
		# A probe that could not run is a HARNESS failure in either mode: it is
		# the absence of evidence, never evidence of the planted defect.
		fail "C2 probe run failed — could not exercise $SANDBOX_FN: $out"
		return 0
	fi
	[ -e "$home" ] && "$report" "C2 the run's HOME survived it: $home"
	# Whatever the probe wrote must be gone from the durable root, wherever a
	# wrapper chose to put it.
	if [ -n "$(find "$SANDBOX_ROOT" -name "$PROBE_SLOT_DIRNAME" -print -quit 2>/dev/null)" ]; then
		"$report" "C2 probe state persists under $GDK_SANDBOX_DIRNAME/"
	fi
	# The real user:// must be untouched — and this one is NEVER downgraded to a
	# corpus detection: a probe that reached real player data is a failure in
	# both modes.
	after="$(real_user_roster)"
	if [ "$before" != "$after" ]; then
		fail "C2 the REAL Godot user data at $(real_user_data_dir) changed during a probe — the HOME sandbox is broken"
	fi
	return 0
}

# --- C1: no bare EXIT trap in a sandboxing wrapper ---------------------------
# <report_fn> <root> — so the corpus can score the same scan over a scratch tree
# holding a deliberately clobbering wrapper beside a sanctioned one.
scan_bare_exit_traps() {
	local report="$1" root="$2" file hit exempt skip
	[ -d "$root" ] || return 0
	while IFS= read -r file; do
		[ -n "$file" ] || continue
		skip=0
		for exempt in "${C1_EXEMPT_NAMES[@]}"; do
			[ "$(basename "$file")" = "$exempt" ] && skip=1
		done
		[ "$skip" -eq 1 ] && continue
		while IFS= read -r hit; do
			[ -n "$hit" ] || continue
			"$report" "C1 $file:$hit — a bare \`trap … EXIT\` clobbers the sandbox self-destruct; register with gdk_on_exit"
		done < <(grep -nE "$BARE_EXIT_TRAP_RE" "$file" 2>/dev/null || true)
	done < <(grep -rl -- "$SANDBOX_FN" "$root" --include='*.sh' 2>/dev/null || true)
}

# --- C3: the sandbox root persists the runs/ spool and nothing else ----------
# Nothing is exempt: there is no cache tier to declare a path in, so any sibling
# of runs/ is by definition something that outlived the run that created it.
scan_root_residue() {
	local report="$1" entry
	[ -d "$SANDBOX_ROOT" ] || return 0
	for entry in "$SANDBOX_ROOT"/* "$SANDBOX_ROOT"/.[!.]*; do
		[ -e "$entry" ] || continue
		case "$(basename "$entry")" in
			"$GDK_SANDBOX_RUNS_SUBDIR") ;;
			*) "$report" "C3 $entry — nothing persists beside $GDK_SANDBOX_RUNS_SUBDIR/; a run's HOME is its only storage" ;;
		esac
	done
}

# --- --self-test -------------------------------------------------------------
# Every check is fired at BOTH shapes: the hermetic one (must stay silent) and
# the planted one (must redden). A corpus that only ever plants defects proves
# the gate is loud, not that it is right.
self_test() {
	local failures=0 cases=0 scored=0 before rc detected
	# A detection is the EXPECTED result of a planted defect, so it is not
	# printed as it happens — it is held, and rendered only by the miss that
	# needed it. A corpus whose green run narrates every planted hit buries its
	# own verdict, and that verdict line is what a caller parses.
	detected=""
	# shellcheck disable=SC2329,SC2317  # invoked indirectly, by name (SC2317 is the same finding on shellcheck < 0.10)
	detect() { scored=$((scored + 1)); detected="$detected
      $1"; }
	# shellcheck disable=SC2329,SC2317  # invoked indirectly, by name
	miss() { echo "  MISS — $1${detected}" >&2; failures=$((failures + 1)); }
	# score — open a scored block: baseline the counter and drop the held
	# detections, so a miss renders THIS block's hits rather than the run's.
	# shellcheck disable=SC2329  # invoked indirectly, by name
	score() { before=$scored; detected=""; }

	# argument handling: --help is 0, an unknown or extra argument is 2.
	cases=$((cases + 1))
	rc=0; bash "$SELF" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || miss "'--help' should exit 0, got $rc"
	cases=$((cases + 1))
	rc=0; bash "$SELF" --what >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "an unknown argument should exit 2, got $rc"
	cases=$((cases + 1))
	rc=0; bash "$SELF" --help extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "an EXTRA argument should exit 2, got $rc"

	# C1 — a clobbering wrapper beside the sanctioned shape.
	mkdir -p "$SCRATCH/wrappers"
	cat > "$SCRATCH/wrappers/clobbering.sh" <<'CLOBBER'
#!/usr/bin/env bash
gdk_sandbox_home
trap 'rm -rf /tmp/whatever' EXIT
CLOBBER
	cat > "$SCRATCH/wrappers/sanctioned.sh" <<'CLEAN'
#!/usr/bin/env bash
gdk_sandbox_home
gdk_on_exit 'rm -rf /tmp/whatever'
CLEAN
	cases=$((cases + 1))
	score; scan_bare_exit_traps detect "$SCRATCH/wrappers"
	[ "$((scored - before))" -eq 1 ] \
		|| miss "C1 scored $((scored - before)) on one planted trap beside one sanctioned hook"

	# The exemption, proven rather than asserted: a file carrying THIS gate's
	# own name is skipped even holding the forbidden shape (its corpus plants
	# that shape), and the count stays 1 — so the exemption is not a hole wide
	# enough to swallow the real wrapper beside it.
	cases=$((cases + 1))
	cp "$SCRATCH/wrappers/clobbering.sh" "$SCRATCH/wrappers/$(basename "$SELF")"
	score; scan_bare_exit_traps detect "$SCRATCH/wrappers"
	[ "$((scored - before))" -eq 1 ] \
		|| miss "C1 scored $((scored - before)) with an exempt-NAMED copy beside the planted trap, expected 1"
	rm -f "$SCRATCH/wrappers/$(basename "$SELF")"

	# C2 — the hermetic shape stays silent…
	cases=$((cases + 1))
	score; scan_run_residue detect 0
	[ "$scored" -eq "$before" ] \
		|| miss "C2 called a HERMETIC run dirty ($((scored - before)) detection(s)) — false positive"
	# …and the pre-fix durable HOME reddens twice: the home survived, and its
	# state is still under the durable root.
	cases=$((cases + 1))
	score; scan_run_residue detect 1
	[ "$((scored - before))" -eq 2 ] \
		|| miss "C2 scored $((scored - before)) on a durable un-cleaned HOME, expected 2"

	# C3 — the spool alone is clean; a sibling of it is not.
	cases=$((cases + 1))
	rm -rf "${SANDBOX_ROOT:?}/$SELF_TEST_DIRTY_DIRNAME"
	score; scan_root_residue detect
	[ "$scored" -eq "$before" ] \
		|| miss "C3 flagged the runs/ spool itself ($((scored - before)) detection(s))"
	cases=$((cases + 1))
	mkdir -p "$SANDBOX_ROOT/$SELF_TEST_DIRTY_CACHE/Caches/Godot"
	score; scan_root_residue detect
	[ "$((scored - before))" -eq 1 ] \
		|| miss "C3 scored $((scored - before)) on one planted cache tier, expected 1"

	# Nothing above may have fired a REAL violation — the corpus runs in a
	# scratch repo, so a `fail` here means the gate reached outside it.
	cases=$((cases + 1))
	[ "$violations" -eq 0 ] || miss "$violations real violation(s) fired inside the scratch corpus"

	if [ "$failures" -eq 0 ]; then
		echo "${C_OK}$TAG SELF-TEST OK — $cases case(s)${C_OFF}"
		return 0
	fi
	echo "${C_BAD}$TAG SELF-TEST FAIL — $failures of $cases case(s), see above${C_OFF}" >&2
	return 1
}

if [ "$SELF_TEST" = "1" ]; then
	# shellcheck disable=SC2016
	gdk_on_exit 'rm -rf "$SCRATCH"'
	self_test_rc=0
	self_test || self_test_rc=$?
	exit "$self_test_rc"
fi

# --- the gate ----------------------------------------------------------------
echo "${C_OK}== hermetic-run scan (per-run sandbox home; nothing survives a run) ==${C_OFF}"

scan_bare_exit_traps fail "$GDK_SANDBOXING_SCAN_ROOT"

# The library's own dispatcher must still be armed — delete it and every hook
# silently stops running, with C2 as the only signal.
if ! grep -qE "^[[:space:]]*trap[[:space:]]+${EXIT_DISPATCHER}[[:space:]]+EXIT" "$LIB"; then
	fail "C1 $LIB — the $EXIT_DISPATCHER EXIT dispatcher is not armed"
fi

scan_run_residue fail 0
scan_root_residue fail

# A run home whose owner pid is dead is a LEAK, not a failure: the next
# gdk_sandbox_home reaps it. Reported so a SYSTEMATIC leak is visible. The
# liveness test is the library's own, deliberately — a bare `kill -0` reads
# another user's live process as dead, which is how a reaper once removed a
# peer's home in a shared checkout.
leaked=0
for dir in "$RUNS_ROOT/$GDK_SANDBOX_RUN_PREFIX"*; do
	[ -d "$dir" ] || continue
	pid="${dir##*/"$GDK_SANDBOX_RUN_PREFIX"}"; pid="${pid%%-*}"
	case "$pid" in ''|*[!0-9]*) continue ;; esac
	gdk_pid_is_live "$pid" || leaked=$((leaked + 1))
done
[ "$leaked" -gt 0 ] && echo "  note: $leaked orphaned run home(s) from killed runs — the next run reaps them"

if [ "$violations" -gt 0 ]; then
	echo "${C_BAD}$TAG FAIL — $violations hermeticity violation(s) above${C_OFF}"
	exit 1
fi

echo "${C_OK}$TAG PASS — a run's HOME self-destructs; nothing persists beside $GDK_SANDBOX_RUNS_SUBDIR/${C_OFF}"
exit 0
