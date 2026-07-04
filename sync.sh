#!/usr/bin/env bash
# sync.sh — vendor the devkit tools into a consuming Godot repo, or check drift.
#
# The devkit is consumed by COPYING (vendoring), never by submodule/runtime
# dependency: consuming repos must work on a bare clone (their hooks and CI
# call these tools). A manifest records the devkit commit + a sha256 per file
# so divergence is a visible, gateable fact instead of a silent fork.
#
# Usage:
#   sync.sh <target-repo-root>            copy tools in + write tools/devkit.manifest
#   sync.sh --check <target-repo-root>    verify vendored files against the manifest
#                                         (exit 1 on drift/missing — the devkit-drift gate)
#
# Layout stamped into the target (the paths the tools' own relative
# resolution assumes):
#   introspect/*  ->  tools/dev/introspect/
#   checks/*      ->  tools/dev/checks/
#
# Local edits to the documented config surfaces (see README) will show as
# drift in --check; that is by design — drift is a prompt to either push the
# fix upstream or consciously re-stamp.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_REL="tools/devkit.manifest"

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

mode="sync"
if [[ "${1:-}" == "--check" ]]; then
	mode="check"
	shift
fi
target="${1:-}"
[[ -n "$target" && -d "$target" ]] || { echo "usage: sync.sh [--check] <target-repo-root>"; exit 2; }
target="$(cd "$target" && pwd)"

# repo-relative-source:repo-relative-dest-dir pairs
mappings=(
	"introspect:tools/dev/introspect"
	"checks:tools/dev/checks"
)

if [[ "$mode" == "sync" ]]; then
	devkit_commit="$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo "unknown")"
	manifest="$target/$MANIFEST_REL"
	mkdir -p "$(dirname "$manifest")"
	{
		echo "# godot-devkit vendored-file manifest — written by sync.sh; do not hand-edit."
		echo "# Check drift with: /path/to/godot-devkit/sync.sh --check <repo-root>"
		echo "devkit_commit=$devkit_commit"
	} > "$manifest"
	count=0
	for m in "${mappings[@]}"; do
		src_dir="${m%%:*}"; dest_dir="${m##*:}"
		mkdir -p "$target/$dest_dir"
		for f in "$HERE/$src_dir"/*; do
			[[ -f "$f" ]] || continue
			base="$(basename "$f")"
			cp "$f" "$target/$dest_dir/$base"
			[[ -x "$f" ]] && chmod +x "$target/$dest_dir/$base"
			echo "$(sha "$target/$dest_dir/$base")  $dest_dir/$base" >> "$manifest"
			count=$((count + 1))
		done
	done
	echo "[devkit-sync] stamped $count file(s) into $target (devkit @ ${devkit_commit:0:9})"
	echo "[devkit-sync] manifest: $MANIFEST_REL — review + commit in the target repo."
	exit 0
fi

# --check
manifest="$target/$MANIFEST_REL"
[[ -f "$manifest" ]] || { echo "[devkit-drift] FAIL — no $MANIFEST_REL in $target (never synced?)"; exit 1; }
drift=0
while IFS= read -r line; do
	case "$line" in \#*|devkit_commit=*|"") continue ;; esac
	want="${line%%  *}"; rel="${line#*  }"
	if [[ ! -f "$target/$rel" ]]; then
		echo "  MISSING  $rel"
		drift=$((drift + 1))
	elif [[ "$(sha "$target/$rel")" != "$want" ]]; then
		echo "  DRIFT    $rel"
		drift=$((drift + 1))
	fi
done < "$manifest"
if [[ "$drift" -gt 0 ]]; then
	echo "[devkit-drift] FAIL — $drift file(s) differ from the manifest ($(grep '^devkit_commit=' "$manifest"))"
	echo "  Push the local fix upstream to godot-devkit, or re-stamp with sync.sh and review."
	exit 1
fi
echo "[devkit-drift] PASS — all vendored files match $(grep '^devkit_commit=' "$manifest")"
