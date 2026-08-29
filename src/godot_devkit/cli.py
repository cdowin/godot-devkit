"""godot-devkit CLI — one entry point, subcommand per tool.

Introspection (pure parse, never boots Godot):
    godot-devkit scene <file.tscn|.tres> [--props] [--paths]
    godot-devkit scene-diff <file> [--git <ref>]  |  scene-diff <old> <new>
    godot-devkit refs <symbol> [--tests]
    godot-devkit orphans [--tests]
    godot-devkit autoloads
    godot-devkit tiles <file.tscn> [--layer NAME]
                       [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]
                                    # a TileMapLayer's grid: cell count, bounds,
                                    # tile-kind histogram, per-column/row counts

Scene surgery (pure parse; edits only the lines it was asked to, or refuses):
    godot-devkit scene set      <file> <node-path> <prop> <value>
    godot-devkit scene rename   <file> <node-path> <new-name>
    godot-devkit scene add      <file> <parent-path> <name> <type> [--script ...]
    godot-devkit scene rm       <file> <node-path>
    godot-devkit scene reparent <file> <node-path> <new-parent>
    godot-devkit scene canonicalize <file>... [--elide-defaults]
                                    # restore what PackedScene.pack() drops:
                                    # uid-in-refs, the header uid, index= on
                                    # instance children; --elide-defaults also
                                    # removes assignments equal to the script's
                                    # @export default (what the editor omits)
    godot-devkit tiles paint <file> --layer NAME --region X0,Y0,X1,Y1
                                    --tile SRC/AX,AY[/ALT]
    godot-devkit tiles erase <file> --layer NAME --region X0,Y0,X1,Y1
                                    # fill / clear a rectangle of one
                                    # TileMapLayer; only that one property's
                                    # base64 is regenerated
    (every verb takes --dry-run, prints a unified diff, and is idempotent)

Project management (engine-agnostic; the PM tree is markdown + frontmatter):
    godot-devkit pm story <wip|review|blocked> <story-id>
    godot-devkit pm feature <ready|building|review> <feature-id>
    godot-devkit pm feature done <feature-id> [--review-record <path>]
    godot-devkit pm milestone <ready|building|done> <milestone-id>
    godot-devkit pm status [<milestone>]
    godot-devkit pm vocabulary --json   # the transition graph, for checkers
    godot-devkit pm validate            # ids/parentage/refs/graph integrity
    godot-devkit pm install-skills      # the shared rule + operations skill
    godot-devkit pm init                # stand up a tree in a repo with none
    godot-devkit pm new <milestone|feature|story|bug> ...
    godot-devkit pm prune
    (the ONLY sanctioned way to move a `status:`; `check pm` gates the drift a
     hand-edit would leave, off the SAME predicates)

Verification, in the project's own vocabulary (devkit.toml `[tasks]`):
    godot-devkit task <role>        # runs what THIS repo declared for the role
    godot-devkit task --list        # the declared roles and their commands
                                    # required roles: quick (the per-change
                                    # gate) and verify (the full gate, and
                                    # what CI runs). One word per role means a
                                    # dispatch never has to paste a regression
                                    # bar again.
    godot-devkit install-ci         # the workflow that runs `task verify`
    godot-devkit install-agents     # the review + build contract, as agent
                                    # definitions (a rules file never reaches
                                    # a subagent's spawn context; a definition
                                    # does)

Static gates (exit 1 on findings; run from anywhere inside the repo):
    godot-devkit check uid [--fix] | tres | props | defaults | doc | shell
                      | repo-hygiene | pm | agents | tasks
                                    # `uid --fix` applies the repair the gate
                                    # already computes: a stale Script ref uid
                                    # rewritten to the target's .uid sidecar
    godot-devkit check all          # the offline fast set (uid+tres+props+doc+shell).
                                    # `defaults` and `repo-hygiene` stay explicit:
                                    # the first is red until a tree is canonicalized
                                    # once, the second is close-time and hits the
                                    # network. `[checks] all` in devkit.toml names
                                    # the roster for THIS repo — a repo with no
                                    # Godot tree runs the repo-family gates instead
                                    # of failing five Godot ones over a 0-file
                                    # census.

Per-project config: devkit.toml at the consuming repo root (see each tool's
module docstring for its section).
"""
from __future__ import annotations

import sys

from godot_devkit import __version__
from godot_devkit.core.config import ConfigError, config_section, str_tuple

OFFLINE_CHECKS = ('uid', 'tres', 'props', 'doc', 'shell')
FIX_FLAG = '--fix'
# Deliberately OUT of `check all`: `defaults` reports thousands of findings on a
# tree that has never been canonicalized, so folding it into the aggregate would
# turn every existing consumer's gate red on a version bump. Wire it explicitly,
# after the one-time cleanup pass. `repo-hygiene` is excluded for its own reason
# (it is close-time and hits the network). `pm` is excluded because a repo with
# no PM tree has no drift to find and must not be failed for its absence.
# `tasks` joins them for the same reason `pm` did: a repo that has not declared
# `[tasks]` yet has no roles to find stale, and failing it for the absence would
# redden every existing consumer on the version bump that introduced the table.
# A repo that HAS declared them names `tasks` in its own `[checks] all`, as this
# one does.
EXPLICIT_CHECKS = ('defaults', 'repo-hygiene', 'pm', 'agents', 'tasks')
KNOWN_CHECKS = (*OFFLINE_CHECKS, *EXPLICIT_CHECKS)


def all_roster() -> tuple[str, ...]:
    """Which gates `check all` runs HERE — `[checks] all`, default OFFLINE_CHECKS.

    Applicability is per-repo and the aggregate is where it shows. Five of the
    eight gates read `.tscn`/`.tres`/shell, so a repo holding none of those
    (this package itself; a PM-tree-only consumer) gets five 0-file censuses,
    and rule 4 correctly turns every one of them red. That is not drift and it
    is not a reason to weaken a gate — it is the roster being wrong for the
    repo, which is exactly the kind of variation rule 5 puts in devkit.toml.

    An unknown name is REFUSED rather than skipped: a typo would otherwise
    narrow the aggregate in silence, which is the cardinal sin with a config
    file in front of it.
    """
    roster = str_tuple(config_section('checks'), 'checks', 'all', OFFLINE_CHECKS)
    unknown = [c for c in roster if c not in KNOWN_CHECKS]
    if unknown:
        raise ConfigError(
            f'[checks] all names unknown gate(s) {", ".join(unknown)} — '
            f'known gates are {" ".join(KNOWN_CHECKS)}')
    # `all` naming itself would recurse forever; it is the one name that cannot
    # appear, and KNOWN_CHECKS already excludes it.
    return tuple(dict.fromkeys(roster))


def install_commands() -> tuple[str, ...]:
    """The `install-*` verbs, from the installer's own plan table.

    Asked rather than restated: a second list here would be a second name for
    the same fact, and the failure mode is a verb documented in one place and
    dispatched in neither.
    """
    from godot_devkit.repo.install import PLANS
    return tuple(PLANS)


def _usage() -> int:
    print(__doc__.strip())
    return 2


def _run_check(name: str, flags: list[str]) -> int:
    # Only `uid` takes a flag today. An unknown one is a usage error, never a
    # silently-ignored argument: a consumer that thinks it asked for a repair
    # and got a read-only run has been lied to.
    unknown = [f for f in flags if not (name == 'uid' and f == FIX_FLAG)]
    if unknown:
        print(f'godot-devkit: check {name}: unexpected argument(s) '
              f'{" ".join(unknown)}', file=sys.stderr)
        return 2
    try:
        return _dispatch_check(name, fix=FIX_FLAG in flags)
    except ConfigError as err:
        # A devkit.toml mistake is exit 2, never 1 (findings) and never 0.
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


def _dispatch_check(name: str, fix: bool = False) -> int:
    if name == 'uid':
        from godot_devkit.godot.checks import uid
        return uid.run(fix=fix)
    if name == 'tres':
        from godot_devkit.godot.checks import tres
        return tres.run()
    if name == 'props':
        from godot_devkit.godot.checks import props
        return props.run()
    if name == 'defaults':
        from godot_devkit.godot.checks import defaults
        return defaults.run()
    if name == 'doc':
        from godot_devkit.repo.checks import doc
        return doc.main([])
    if name == 'shell':
        from godot_devkit.repo.checks import shell
        return shell.run()
    if name == 'repo-hygiene':
        from godot_devkit.repo.checks import repo_hygiene
        return repo_hygiene.run()
    if name == 'pm':
        from godot_devkit.repo.checks import pm
        return pm.run()
    if name == 'agents':
        from godot_devkit.repo.checks import agents
        return agents.run()
    if name == 'tasks':
        from godot_devkit.repo import tasks
        return tasks.run()
    if name == 'all':
        worst = 0
        for check in all_roster():
            worst = max(worst, _dispatch_check(check))
            print()
        return worst
    # `all` never repairs: an aggregate that writes is the last place a
    # consumer expects one, so `--fix` is asked for on the gate itself.
    print(f'godot-devkit: unknown check {name!r} '
          f'(expected: {", ".join((*OFFLINE_CHECKS, *EXPLICIT_CHECKS, "all"))})',
          file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _usage()
    if args[0] in ('-h', '--help', 'help'):
        print(__doc__.strip())
        return 0
    cmd, rest = args[0], args[1:]
    if cmd in ('-V', '--version', 'version'):
        print(f'godot-devkit {__version__}')
        return 0
    if cmd == 'scene':
        from godot_devkit.godot.write import scene_edit
        if rest and rest[0] == 'canonicalize':
            from godot_devkit.godot.write import scene_canonicalize
            return scene_canonicalize.main(rest[1:])
        if rest and rest[0] in scene_edit.VERBS:
            return scene_edit.main(rest)
        from godot_devkit.godot.read import scene_summary
        return scene_summary.main(rest)
    if cmd == 'tiles':
        from godot_devkit.godot.write import tiles_paint
        if rest and rest[0] in tiles_paint.VERBS:
            return tiles_paint.main(rest)
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
    if cmd == 'pm':
        from godot_devkit.repo.pm import cli as pm_cli
        return pm_cli.main(rest)
    if cmd == 'task':
        from godot_devkit.repo import tasks
        return tasks.main(rest)
    if cmd in install_commands():
        from godot_devkit.repo import install
        return install.main(cmd, rest)
    if cmd == 'check':
        if not rest:
            return _usage()
        return _run_check(rest[0], rest[1:])
    print(f'godot-devkit: unknown command {cmd!r}', file=sys.stderr)
    return _usage()


if __name__ == '__main__':
    raise SystemExit(main())
