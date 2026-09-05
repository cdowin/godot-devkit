#!/usr/bin/env bash
# Activate the tracked git hooks under tools/hooks/ by pointing git at them via
# core.hooksPath. Run once after cloning: `bash tools/setup-hooks.sh`.
#
# We use core.hooksPath (not symlinks into .git/hooks) so the hooks are
# version-controlled, apply across every worktree, and stay in sync with the
# repo. WHICH guards run is whatever your repo puts under tools/hooks/; this
# script only points git at the directory and arms the exec bit.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# The tracked-hooks directory git points at via core.hooksPath.
HOOKS_PATH="tools/hooks"

cd "$REPO_ROOT"
git config core.hooksPath "$HOOKS_PATH"

# NTH-2: belt-and-suspenders exec bit. core.hooksPath silently skips a
# non-executable hook (a checkout onto a filesystem that drops the exec bit
# would disarm the guards). chmod the actual hook entry points — not the
# sourced _*.sh libraries, which are only ever `source`d. The cc-*.sh Claude
# Code hooks are chmodded by GLOB, so the list tolerates absence and does not
# have to be edited every time one is added.
chmod +x "$HOOKS_PATH"/pre-commit "$HOOKS_PATH"/pre-push "$HOOKS_PATH"/prepare-commit-msg 2>/dev/null || true
chmod +x "$HOOKS_PATH"/cc-*.sh 2>/dev/null || true
# The non-hook halves of the installed corpus, invoked by path rather than by
# git — same silent-skip risk if a checkout drops the exec bit.
chmod +x tools/dev/agent-worktree.sh tools/dev/checks/doctor.sh 2>/dev/null || true

echo "OK: git core.hooksPath → $HOOKS_PATH"
# List the active hook entry points (exclude the _*.sh sourced libraries) via a
# glob, not ls|grep.
active=""
for hook in "$HOOKS_PATH"/*; do
	name="$(basename "$hook")"
	case "$name" in _*) continue ;; esac
	active="${active:+$active }$name"
done
echo "    active hooks: $active"
