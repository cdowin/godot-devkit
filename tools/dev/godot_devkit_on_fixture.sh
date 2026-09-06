#!/usr/bin/env bash
# godot_devkit_on_fixture.sh — this package, from src/, run inside a scratch
# copy of the committed clean Godot project (tests/fixtures/godot_project/).
#
# This tree is not a Godot project. Pointed at the repo itself, six of the
# eight Godot gates report a 0-file census and rule 4 reddens every one —
# which is the gate working, not a roster to soften. The self-hosting proof
# (CLAUDE.md) is that every check runs against something COMMITTED here, so
# `make check`'s `godot-check` member (Makefile.tiers, `$(GODOT_DEVKIT) check
# all`) reaches the package through THIS command: the fixture project staged
# into a throwaway git repo — the way the test suite stages every fixture —
# with no devkit.toml, so the roster it runs is the STOCK one, and the tree
# under test is never this checkout edited in place.
#
# Any argv goes through: `bash tools/dev/godot_devkit_on_fixture.sh check uid`
# is that one gate on the fixture. The scratch repo is removed on exit,
# whatever the exit was.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture="$here/tests/fixtures/godot_project"
[ -d "$fixture" ] || { echo "godot_devkit_on_fixture.sh: $fixture is not a directory" >&2; exit 2; }

scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-fixture.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT

cp -R "$fixture/." "$scratch/"
git -C "$scratch" init -q
git -C "$scratch" add -A
git -C "$scratch" -c user.name=godot-devkit -c user.email=godot-devkit@fixture.invalid \
	commit -q -m 'the committed clean Godot project, staged'

cd "$scratch"
status=0
env PYTHONPATH="$here/src" python3 -m godot_devkit.cli "$@" || status=$?
exit "$status"
