#!/usr/bin/env bash
# Claude Code SessionStart hook. In a cloud container only: install the Godot that CI uses
# (MAJOR.MINOR from project.godot's config/features, the patch from the GODOT_PATCH line of a
# workflow under .github/workflows), then import the project once. A local machine has its own
# engine, and this exits at once there.
set -uo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0
log() { printf '[session-start] %s\n' "$1"; }

line=$(grep -m1 -oE 'config/features=PackedStringArray\("[0-9]+\.[0-9]+' project.godot | grep -oE '[0-9.]+$')
patch=$(grep -hoE 'GODOT_PATCH: *"?[0-9]+' .github/workflows/*.yml 2>/dev/null | head -n1 | grep -oE '[0-9]+$')
[ -n "$line" ] && [ -n "$patch" ] || { log "WARN no engine version in project.godot and .github/workflows"; exit 0; }
version="$line.$patch"

if godot --version 2>/dev/null | grep -q "^$version\.stable"; then
	log "godot $version present"
else
	log "installing Godot $version"
	tmp=$(mktemp -d)
	name="Godot_v$version-stable_linux.x86_64"
	# The cloud container's proxy signs TLS with its own CA.
	ca=(); [ -f /root/.ccr/ca-bundle.crt ] && ca=(--cacert /root/.ccr/ca-bundle.crt)
	if curl -fsSL --retry 3 "${ca[@]}" -o "$tmp/godot.zip" \
			"https://github.com/godotengine/godot/releases/download/$version-stable/$name.zip" \
			&& unzip -oq "$tmp/godot.zip" -d "$tmp" && install -m 0755 "$tmp/$name" /usr/local/bin/godot; then
		log "godot installed"
	else
		log "WARN the Godot install failed; make check needs it"
	fi
	rm -rf "$tmp"
fi

if make import >/dev/null 2>&1; then log "imported the project"; else log "WARN make import failed; run it by hand"; fi
# Work branches from origin/main; a fresh clone of one branch does not carry it.
git rev-parse --verify --quiet origin/main >/dev/null || git fetch --quiet origin main:refs/remotes/origin/main || true
log "READY: make help"
