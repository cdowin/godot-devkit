#!/usr/bin/env bash
# Tier-1 static gate (shellcheck.sh) over every shell script in tools/.
#
# Lints tools/**/*.sh + the extension-less hook entry points under tools/hooks/
# with shellcheck -x (follow `source`d files, so the shared _common.sh / _scope.sh
# libraries resolve). Sibling of lint.sh (gdlint) / uid_scan.sh — pure static, no
# Godot boot. `command -v`-guarded: shellcheck is a SHOULD-have dev dep, so a host
# without it gets a clear skip (not a hard fail) — `make doctor` flags its absence.
#
# Usage:
#   tools/dev/shellcheck.sh        (run from repo root; exits 1 on any finding)
#
# Prefer the `make` front door: `make shellcheck` (folded into `make check`).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT" || exit 2

if ! command -v shellcheck >/dev/null 2>&1; then
    echo "[shellcheck] SKIP — shellcheck not on PATH (brew install shellcheck). See 'make doctor'."
    exit 0
fi

# Targets: every *.sh under tools/, plus the extension-less entry points that are
# still real shell — the hooks in tools/hooks/ (pre-commit, pre-push,
# prepare-commit-msg) and the pm CLI at tools/pm/pm. Exclude generated .py/.uid.
# The _*.sh libraries ARE checked (real scripts).
TARGETS=()
while IFS= read -r -d '' f; do
    TARGETS+=("$f")
done < <(find tools -type f \( -name '*.sh' -o -path 'tools/hooks/*' -o -path 'tools/pm/pm' \) \
    ! -name '*.py' ! -name '*.uid' -print0)

if [ "${#TARGETS[@]}" -eq 0 ]; then
    echo "[shellcheck] no shell scripts found under tools/"
    exit 0
fi

if shellcheck -x "${TARGETS[@]}"; then
    echo "[shellcheck] PASS — ${#TARGETS[@]} script(s) clean"
    exit 0
fi
echo "[shellcheck] FAIL — findings above"
exit 1
