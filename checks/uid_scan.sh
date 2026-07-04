#!/usr/bin/env bash
# uid_scan.sh — Tier-1 guard against Godot .uid drift.
#
# Godot 4 references script dependencies in .tres/.tscn by BOTH uid and path:
#   [ext_resource type="Script" uid="uid://X" path="res://Y.gd" id="..."]
# Each .gd has a canonical sidecar Y.gd.uid. When a .gd's .uid is regenerated /
# late-committed / moved without resaving the .tres that reference it, the cached
# `uid://X` goes stale — Godot falls back to the text path and warns on every COLD
# import (a fresh checkout / CI). The warm .godot cache masks it locally, so it
# only bites where it hurts most. This scanner makes that drift a FAILING GATE at
# commit time instead.
#
# This static check and scenario.sh's cold-cache RECOVERY guard the SAME class —
# the runtime symptom is the cold-cache class ('invalid UID … using
# text path instead'), single-sourced so the scanner and the recovery describe
# it identically.
#
# Pure shell (grep/sed/git — NO Godot boot); sibling of lint.sh / parse.sh.
#
# CHECK 1 (HARD): every Script ext_resource uid in a .tres/.tscn (under the
#                 shipping dirs) matches the referenced .gd's .uid (or the .uid
#                 is absent).
# CHECK 2 (HARD): every git-tracked .gd (except addons/) has a git-tracked
#                 .gd.uid — the "commit all .uid" policy (.gitignore), applied;
#                 tests included. No untracked-vs-tracked split that lets uids
#                 diverge across machines/CI.
#
# Usage:
#   tools/dev/uid_scan.sh        (run from repo root; exits 1 on any drift)
#
# Prefer the `make` front door: `make uid-scan`.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT" || exit 2

# The runtime symptom this scanner prevents (the cold-cache / uid-drift class):
# shellcheck disable=SC2034  # documented class string; kept for operator grep parity
COLD_CACHE_PATTERN='invalid UID.*using text path instead'

# Dirs that hold shipping .gd + the .tres/.tscn that reference them. addons/ is
# third-party, tests/ aren't shipped (their .uid are still tracked — CHECK 2 —
# but no shipping .tres references them by uid), .godot/ is the import cache.
# PROJECT CONFIG SURFACE — the dirs holding shipping .gd + the .tres/.tscn
# that reference them (exclude addons/, .godot/).
SCAN_DIRS="${DEVKIT_SCAN_DIRS:-data scenes resources systems autoloads shared}"

hard=0

echo "[uid_scan] CHECK 1 — .tres/.tscn Script ext_resource uid matches the script's .uid"
# SC2086: $SCAN_DIRS is INTENTIONALLY unquoted — it must word-split into the
# multiple grep path args it lists.
# shellcheck disable=SC2086
REFS="$(grep -rnoE 'ext_resource type="Script" uid="uid://[a-z0-9]+" path="res://[^"]+\.gd"' \
	--include='*.tres' --include='*.tscn' $SCAN_DIRS 2>/dev/null || true)"
while IFS= read -r ref; do
	[ -z "$ref" ] && continue
	file="${ref%%:*}"
	uid="$(printf '%s\n' "$ref" | grep -oE 'uid://[a-z0-9]+' | head -1)"
	relpath="$(printf '%s\n' "$ref" | sed -E 's#.*path="res://([^"]+)".*#\1#')"
	uidfile="${relpath}.uid"
	if [ ! -f "$uidfile" ]; then
		echo "  DRIFT  $file → $relpath has NO .uid file (referenced uid $uid)"
		hard=$((hard + 1))
		continue
	fi
	actual="$(tr -d '[:space:]' < "$uidfile")"
	if [ "$uid" != "$actual" ]; then
		echo "  DRIFT  $file : $uid → should be $actual  ($relpath)"
		hard=$((hard + 1))
	fi
done <<< "$REFS"

echo "[uid_scan] CHECK 2 — every tracked .gd has a tracked .gd.uid (tests included; addons/ exempt)"
while IFS= read -r gd; do
	[ -z "$gd" ] && continue
	case "$gd" in addons/*) continue ;; esac  # third-party only; tests + shipping both require a tracked .uid
	if ! git ls-files --error-unmatch "${gd}.uid" >/dev/null 2>&1; then
		echo "  UNTRACKED  $gd has no tracked ${gd}.uid"
		hard=$((hard + 1))
	fi
done <<< "$(git ls-files '*.gd')"

echo
if [ "$hard" -gt 0 ]; then
	echo "[uid_scan] FAIL — $hard .uid drift / tracking violation(s)"
	exit 1
fi
echo "[uid_scan] PASS — no .uid drift; all tracked .gd have tracked .uid"
