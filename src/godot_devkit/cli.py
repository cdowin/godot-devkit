"""godot-devkit CLI — one entry point, subcommand per tool.

Introspection (pure parse, never boots Godot):
    godot-devkit scene <file.tscn|.tres> [--props] [--paths]
    godot-devkit scene-diff <file> [--git <ref>]  |  scene-diff <old> <new>
    godot-devkit refs <symbol> [--tests]
    godot-devkit orphans [--tests]
    godot-devkit autoloads
    godot-devkit stats [<dir>...] [--by dir] [--json] [--ratchet FILE]
                                    # files, lines and code lines per role
                                    # bucket (game/tests/tools/vendored .gd,
                                    # .gdshader, .tscn, .tres)
    godot-devkit tiles <file.tscn> [--layer NAME]
                       [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]
                                    # a TileMapLayer's grid: cell count, bounds,
                                    # tile-kind histogram, per-column/row counts
    godot-devkit ui-fit-plan        # the scenes and windows `make ui-fit`
                                    # boots, from [ui_fit]; 0 scenes FAILS
    godot-devkit fit-sweep-plan     # the sizes and scenes `make fit-sweep`
                                    # boots, from [fit_sweep] and its table

Scene writer (pure parse; edits only its own lines, or refuses). Godot writes
scenes; these two are for inherited scenes with overrides or local materials,
which a headless load-and-save damages:
    godot-devkit scene set      <file> <node-path> <prop> <value>
    godot-devkit scene set      <file> --resource <prop> <value>
    godot-devkit scene set      <file> --sub-resource <id> <prop> <value>
                                    # the [resource] body of a .tres, or a
                                    # [sub_resource] by the id `scene --props`
                                    # prints — read output is write input
    godot-devkit scene set      <file> <node-path> <prop> --new-sub-resource
                                <res://x.gd|Type> [key=value ...]
                                    # make a [sub_resource] and point the
                                    # property at it
    godot-devkit scene add      <file> <parent-path> <name> <type> [--script ...]
                                [--tile-set res://x.tres] [--z N] [--group G]
    godot-devkit scene add      <file> <parent-path> <name> --instance res://x.tscn
                                    # an instance node (no type=); its ref is
                                    # minted from the scene's own uid, or refused
                                    # (both take --dry-run and are idempotent)

    godot-devkit pot [--dry-run | --check]
                                    # the localization POT the editor writes,
                                    # from project.godot's translations_pot_files
                                    # (.gd only) to `[pot] output`; --check
                                    # exits 1 on drift and names each missing
                                    # and extra msgid

The installer (writes each file once; after that it is the repo's):
    godot-devkit install-runners [--force] [--diff]
                                    # the sandboxed headless-run shell library
                                    # and the runners that source it, the
                                    # compile sweep they boot, the Claude Code
                                    # engine-boot guard, the uid-drift workflow.
                                    # --force overwrites a differing
                                    # destination; --diff prints what would
                                    # change and writes nothing
    godot-devkit install-gates [--force] [--diff]
                                    # the gate framework: Makefile.gates (help,
                                    # check, precommit, verify) and the capture
                                    # library tools/dev/gdk_gate.sh. A game sets
                                    # GDK_CHECKS and includes Makefile.gates;
                                    # it needs nothing from agentic-sdlc
    godot-devkit install-skills [--runtime codex|claude] [--dest ROOT]
                                [--skill NAME] [--check] [--force] [--diff]
                                    # install every bundled skill (or NAME)
                                    # into a skills root; --check reports drift

Static gates (exit 1 on findings; run from anywhere inside the repo):
    godot-devkit check props | tres-comment | unit-disk
                      | uid [--fix] | patterns | addon [--fix]
                                    # the last three are opt-in: not in the stock `check all`
                                    # `addon --fix` mints the uids an add-on
                                    # must ship: .gd.uid sidecars and header uids
    godot-devkit check <gate> --help  # that gate's contract, config and scope
                                    # `uid --fix` applies the repairs the gate
                                    # already computes: stale Script ref uids
                                    # rewritten to the sidecar's, non-canonical
                                    # spellings canonicalized (same id), and
                                    # orphan .gd.uid sidecars deleted
    godot-devkit check all          # the stock Godot gates. `[roster]
                                    # checks` in godot-devkit.toml narrows the
                                    # roster for THIS repo; an unknown name is
                                    # refused, never skipped.

Per-project config: godot-devkit.toml at the consuming repo root (see each tool's
module docstring for its section).

What is NOT here: agent guardrails, PM trees and ledgers. godot-devkit has
Godot tooling; agentic-sdlc has agent guardrails; neither imports the other.
"""
from __future__ import annotations

import sys

from godot_devkit import __version__
from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks.roster import (KNOWN_GATES, OPT_IN_GATES,
                                             REMOVED_GATES, all_roster)

FIX_FLAG = '--fix'
HELP_FLAGS = ('-h', '--help')

# The gates that accept `--fix`. A second fixable gate is a row here, not a
# new inline condition in `_run_check`.
FIXABLE_CHECKS = frozenset({'uid', 'addon'})

# The verbs that LEFT with the repo-discipline family (0.25.0). Routed to one
# line and exit 2 rather than falling through to `unknown command`: a consumer
# whose Makefile still says `godot-devkit pm` should be told where the verb
# went, not that it never existed. Exit 2 is the usage-error code (rule 6), and
# it is deliberately not 0 — a retired verb that exits 0 is a gate that
# silently stopped gating. Since 3.0 agentic-sdlc has no CLI, so the line says
# the verb is gone from both kits. (`install-gates` is a real verb again in
# 3.0, and `install-ci`, `install-agents`, `install-hooks` and `install-sdlc`
# are plain unknown commands.)
RETIRED_COMMANDS = frozenset({'pm', 'init', 'gates-extra'})
RETIRED_CHECKS = frozenset({'doc', 'shell', 'pm', 'hooks', 'repo-hygiene'})

# What 5.0 removed, keyed by (command, subcommand or flag), each with what does
# the job now. Godot writes its own files: the editor, or a headless GDScript
# that loads, edits and saves with ResourceSaver (the godot-devkit skill).
_ENGINE = 'use the editor, or a headless GDScript that saves with ResourceSaver'
_ROSTER = 'drop it from `[roster] checks`'
REMOVED_VERBS = {
    **{('scene', verb): _ENGINE for verb in
       ('rename', 'rm', 'reparent', 'connect', 'disconnect', 'new')},
    ('scene', 'canonicalize'): 'nothing replaces it: a file Godot saved is already in its form',
    ('tiles', 'paint'): 'use TileMapLayer.set_cell / set_cells_terrain_connect in a headless GDScript',
    ('tiles', 'erase'): 'use TileMapLayer.erase_cell in a headless GDScript',
    ('refs', '--retarget'): 'move it in the editor\'s FileSystem dock; uid-in-refs '
                            'finds a moved file and the next save writes its path',
    ('refs', '--rename'): 'rename in the editor, or edit by hand and prove no '
                          'caller is left with `refs <symbol>`',
    ('autoloads', 'add'): 'use Project Settings > Autoload, or '
                          'ProjectSettings.set_setting() + save() in a headless script',
    ('autoloads', 'rm'): 'use Project Settings > Autoload, or '
                         'ProjectSettings.clear() + save() in a headless script',
    **{('check', gate): _ROSTER for gate in REMOVED_GATES},
}


def _usage() -> int:
    print(__doc__.strip())
    return 2


def _removed(cmd: str, rest: list[str]) -> int | None:
    """Exit 2 with the replacement for a verb 5.0 removed, else None. Looks at
    the subcommand and at flags only, so a node or file named `rm` is not one."""
    for arg in rest[:1] + [a for a in rest[1:] if a.startswith('--')]:
        replacement = REMOVED_VERBS.get((cmd, arg))
        if replacement:
            print(f'godot-devkit: `{cmd} {arg}` was removed in 5.0: '
                  f'{replacement}', file=sys.stderr)
            return 2
    return None


def _retired(verb: str) -> int:
    """One line, exit 2: the verb is gone from both kits."""
    print(f'godot-devkit: {verb!r} left this package in 0.25.0 and is not in '
          f'agentic-sdlc 3.0 either: godot-devkit has Godot tooling, '
          f'agentic-sdlc has agent guardrails', file=sys.stderr)
    return 2


def _run_check(name: str, flags: list[str]) -> int:
    if name in RETIRED_CHECKS:
        return _retired(f'check {name}')
    if any(flag in HELP_FLAGS for flag in flags):
        # A gate's contract, its config section and its honest scope are in its
        # module docstring — the one copy, so `--help` cannot drift from it.
        module = _check_module(name)
        if module is None:
            return _unknown_check(name)
        print((module.__doc__ or '').strip())
        return 0
    # Only the FIXABLE_CHECKS take a flag today. An unknown one is a usage
    # error, never a silently-ignored argument: a consumer that thinks it asked
    # for a repair and got a read-only run has been lied to.
    unknown = [f for f in flags
               if not (name in FIXABLE_CHECKS and f == FIX_FLAG)]
    if unknown:
        print(f'godot-devkit: check {name}: unexpected argument(s) '
              f'{" ".join(unknown)}', file=sys.stderr)
        return 2
    try:
        return _dispatch_check(name, fix=FIX_FLAG in flags)
    except ConfigError as err:
        # A godot-devkit.toml mistake is exit 2, never 1 (findings) and never 0.
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


def _check_module(name: str):
    """The module implementing one gate, or None.

    Split out of the dispatch so `--help` can reach a gate's docstring without a
    second table naming the same modules — the import chain IS the roster, and
    it is lazy on purpose: a gate nobody asked for is a gate nobody imports.
    """
    if name == 'uid':
        from godot_devkit.godot.checks import uid
        return uid
    if name == 'props':
        from godot_devkit.godot.checks import props
        return props
    if name == 'tres-comment':
        from godot_devkit.godot.checks import tres_comment
        return tres_comment
    if name == 'unit-disk':
        from godot_devkit.godot.checks import unit_disk
        return unit_disk
    if name == 'patterns':
        from godot_devkit.godot.checks import patterns
        return patterns
    if name == 'addon':
        from godot_devkit.godot.checks import addon
        return addon
    return None


def _unknown_check(name: str) -> int:
    print(f'godot-devkit: unknown check {name!r} '
          f'(expected: {", ".join((*KNOWN_GATES, *OPT_IN_GATES, "all"))})',
          file=sys.stderr)
    return 2


def _dispatch_check(name: str, fix: bool = False) -> int:
    if name == 'all':
        worst = 0
        for check in all_roster():
            worst = max(worst, _dispatch_check(check))
            print()
        return worst
    module = _check_module(name)
    if module is None:
        return _unknown_check(name)
    # `all` never repairs: an aggregate that writes is the last place a
    # consumer expects one, so `--fix` is asked for on the gate itself.
    return module.run(fix=fix) if name in FIXABLE_CHECKS else module.run()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _usage()
    if args[0] in ('-h', '--help', 'help'):
        print(__doc__.strip())
        return 0
    cmd, rest = args[0], args[1:]
    removed = _removed(cmd, rest)
    if removed is not None:
        return removed
    if cmd in ('-V', '--version', 'version'):
        print(f'godot-devkit {__version__}')
        return 0
    if cmd == 'scene':
        from godot_devkit.godot.write import scene_edit
        if rest and rest[0] in scene_edit.VERBS:
            return scene_edit.main(rest)
        from godot_devkit.godot.read import scene_summary
        return scene_summary.main(rest)
    if cmd == 'tiles':
        from godot_devkit.godot.read import tiles
        return tiles.main(rest)
    if cmd == 'scene-diff':
        from godot_devkit.godot.read import scene_diff
        return scene_diff.main(rest)
    if cmd == 'refs':
        from godot_devkit.godot.read import refs
        return refs.main(rest)
    if cmd == 'orphans':
        from godot_devkit.godot.read import orphans
        return orphans.main(rest)
    if cmd == 'autoloads':
        from godot_devkit.godot.read import autoloads
        return autoloads.main(rest)
    if cmd == 'pot':
        from godot_devkit.godot.write import pot
        return pot.main(rest)
    if cmd == 'stats':
        from godot_devkit.godot.read import stats
        return stats.main(rest)
    if cmd == 'ui-fit-plan':
        from godot_devkit.godot.read import ui_fit_plan
        return ui_fit_plan.main(rest)
    if cmd == 'fit-sweep-plan':
        from godot_devkit.godot.read import fit_sweep_plan
        return fit_sweep_plan.main(rest)
    if cmd == 'install-runners':
        from godot_devkit.godot import install
        return install.main(rest)
    if cmd == 'install-gates':
        from godot_devkit.godot import install
        return install.main_gates(rest)
    if cmd == 'install-skills':
        from godot_devkit.godot import skill_install
        return skill_install.main(rest)
    if cmd in RETIRED_COMMANDS:
        return _retired(cmd)
    if cmd == 'check':
        if not rest:
            return _usage()
        return _run_check(rest[0], rest[1:])
    print(f'godot-devkit: unknown command {cmd!r}', file=sys.stderr)
    return _usage()


if __name__ == '__main__':
    raise SystemExit(main())
