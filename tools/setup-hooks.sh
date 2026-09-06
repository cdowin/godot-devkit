#!/usr/bin/env bash
# setup-hooks.sh — arm the tracked git hooks under tools/hooks/ via
# core.hooksPath and set their exec bits. Run once after cloning:
# `bash tools/setup-hooks.sh`. core.hooksPath, not symlinks, so the hooks are
# version-controlled and apply across every worktree.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# The tracked-hooks directory git points at via core.hooksPath.
HOOKS_PATH="tools/hooks"

cd "$REPO_ROOT"
git config core.hooksPath "$HOOKS_PATH"

# core.hooksPath silently skips a non-executable hook; cc-*.sh by glob so the list tolerates absence.
chmod +x "$HOOKS_PATH"/pre-commit "$HOOKS_PATH"/pre-push "$HOOKS_PATH"/prepare-commit-msg 2>/dev/null || true
chmod +x "$HOOKS_PATH"/cc-*.sh 2>/dev/null || true
# The non-hook halves of the corpus, invoked by path; absence is not an error.
chmod +x tools/dev/agent-worktree.sh 2>/dev/null || true

echo "OK: git core.hooksPath → $HOOKS_PATH"
# The active entry points, by glob; `_*.sh` are sourced libraries.
active=""
for hook in "$HOOKS_PATH"/*; do
	name="$(basename "$hook")"
	case "$name" in _*) continue ;; esac
	active="${active:+$active }$name"
done
echo "    active hooks: $active"
