#!/usr/bin/env bash
# tres_format_scan.sh — Tier-1 guard against .tres/.tscn reference-format drift
#
# Godot 4.4+ writes ext_resource references in the canonical uid-in-refs form:
#   [ext_resource type="Script" uid="uid://X" path="res://Y" id="..."]
# A repo should be migrated to this format ONCE, deliberately. The hazard this
# guards: any editor / import / capture pass silently UPGRADES a path-only ref
# (one lacking uid=) to uid-in-refs — churn that leaks into unrelated changes.
#
# The fix is structural: keep the committed tree fully canonical, so an
# incidental upgrade has NOTHING left to rewrite. This scanner is that gate —
# it FAILS if any tracked non-archive .tres/.tscn carries a path-only
# ext_resource ref. Because a canonical tree can't be upgraded, this also
# guarantees the feature's second property: a capture/headless run leaves the
# tree clean.
#
# Pure git + grep, no Godot boot — sibling of uid_scan.sh / loc_scan.sh. This is
# the reference-FORMAT gate; uid_scan.sh is the complementary uid-DRIFT gate
# (a ref's uid matching the target's actual .uid).
#
# CHECK (HARD): every ext_resource ref in a tracked non-archive .tres/.tscn
#               carries a uid= (i.e. no path-only refs remain).
#
# Usage:  tools/dev/checks/tres_format_scan.sh   (run from repo root; exits 1 on drift)

set -uo pipefail
# Resolve the repo root robustly (git-toplevel, not a fragile ../.. count) so
# the git-ls-files listing and per-file greps below are always repo-relative.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "not in a git repo"; exit 2; }
cd "$ROOT" || exit 2

hard=0
checked=0

echo "[tres_format_scan] CHECK — every ext_resource ref carries a uid (canonical uid-in-refs)"
while IFS= read -r f; do
	[ -z "$f" ] && continue
	case "$f" in zz_archive/* | addons/*) continue ;; esac
	checked=$((checked + 1))
	# A path-only ref: an ext_resource line with a path= but no uid=.
	while IFS= read -r hit; do
		[ -z "$hit" ] && continue
		echo "  PATH-ONLY  ${f}:${hit}"
		hard=$((hard + 1))
	done <<< "$(grep -nE '^\[ext_resource ' "$f" | grep 'path="' | grep -v 'uid="uid://')"
done <<< "$(git ls-files '*.tres' '*.tscn')"

echo
if [ "$hard" -gt 0 ]; then
	echo "[tres_format_scan] FAIL — $hard path-only ext_resource ref(s) across $checked file(s)"
	echo "  Fix: rewrite each to uid-in-refs form ([ext_resource type=\"…\" uid=\"uid://…\" path=\"res://…\" id=\"…\"])."
	echo "  A path-only ref is what an editor/import/capture pass silently upgrades — the drift this gate blocks."
	exit 1
fi
echo "[tres_format_scan] PASS — all ext_resource refs canonical across $checked .tres/.tscn"
