"""godot-devkit CLI — one entry point, subcommand per tool.

Introspection (pure parse, never boots Godot):
    godot-devkit scene <file.tscn|.tres> [--props] [--paths]
    godot-devkit scene-diff <file> [--git <ref>]  |  scene-diff <old> <new>
    godot-devkit refs <symbol> [--tests]
    godot-devkit orphans [--tests]
    godot-devkit autoloads

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
    (every verb takes --dry-run, prints a unified diff, and is idempotent)

Project management (engine-agnostic; the PM tree is markdown + frontmatter):
    godot-devkit pm story <wip|review|blocked> <story-id>
    godot-devkit pm feature <ready|building|review> <feature-id>
    godot-devkit pm feature done <feature-id> [--review-record <path>]
    godot-devkit pm milestone <ready|building|done> <milestone-id>
    godot-devkit pm status [<milestone>]
    godot-devkit pm validate            # ids/parentage/refs/graph integrity
    godot-devkit pm install-skills      # the shared rule + operations skill
    godot-devkit pm init                # stand up a tree in a repo with none
    godot-devkit pm new <milestone|feature|story|bug> ...
    godot-devkit pm prune
    (the ONLY sanctioned way to move a `status:`; `check pm` gates the drift a
     hand-edit would leave, off the SAME predicates)

Static gates (exit 1 on findings; run from anywhere inside the repo):
    godot-devkit check uid | tres | props | defaults | doc | shell | repo-hygiene | pm
    godot-devkit check all          # the offline fast set (uid+tres+props+doc+shell).
                                    # `defaults` and `repo-hygiene` stay explicit:
                                    # the first is red until a tree is canonicalized
                                    # once, the second is close-time and hits the
                                    # network.

Per-project config: devkit.toml at the consuming repo root (see each tool's
module docstring for its section).
"""
from __future__ import annotations

import sys

from godot_devkit import __version__
from godot_devkit.core.project import ConfigError

OFFLINE_CHECKS = ('uid', 'tres', 'props', 'doc', 'shell')
# Deliberately OUT of `check all`: `defaults` reports thousands of findings on a
# tree that has never been canonicalized, so folding it into the aggregate would
# turn every existing consumer's gate red on a version bump. Wire it explicitly,
# after the one-time cleanup pass. `repo-hygiene` is excluded for its own reason
# (it is close-time and hits the network). `pm` is excluded because a repo with
# no PM tree has no drift to find and must not be failed for its absence.
EXPLICIT_CHECKS = ('defaults', 'repo-hygiene', 'pm')


def _usage() -> int:
    print(__doc__.strip())
    return 2


def _run_check(name: str) -> int:
    try:
        return _dispatch_check(name)
    except ConfigError as err:
        # A devkit.toml mistake is exit 2, never 1 (findings) and never 0.
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


def _dispatch_check(name: str) -> int:
    if name == 'uid':
        from godot_devkit.godot.checks import uid
        return uid.run()
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
    if name == 'all':
        worst = 0
        for check in OFFLINE_CHECKS:
            worst = max(worst, _dispatch_check(check))
            print()
        return worst
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
    if cmd == 'check':
        if not rest:
            return _usage()
        return _run_check(rest[0])
    print(f'godot-devkit: unknown command {cmd!r}', file=sys.stderr)
    return _usage()


if __name__ == '__main__':
    raise SystemExit(main())
