"""godot-devkit CLI — one entry point, subcommand per tool.

Introspection (pure parse, never boots Godot):
    godot-devkit scene <file.tscn|.tres> [--props]
    godot-devkit scene-diff <file> [--git <ref>]  |  scene-diff <old> <new>
    godot-devkit refs <symbol> [--tests]
    godot-devkit orphans [--tests]
    godot-devkit autoloads

Static gates (exit 1 on findings; run from anywhere inside the repo):
    godot-devkit check uid | tres | doc | shell | repo-hygiene
    godot-devkit check all          # the offline fast set (uid+tres+doc+shell);
                                    # repo-hygiene is close-time (network) and
                                    # always explicit.

Per-project config: devkit.toml at the consuming repo root (see each tool's
module docstring for its section).
"""
from __future__ import annotations

import sys

from godot_devkit import __version__

OFFLINE_CHECKS = ('uid', 'tres', 'doc', 'shell')


def _usage() -> int:
    print(__doc__.strip())
    return 2


def _run_check(name: str) -> int:
    if name == 'uid':
        from godot_devkit.checks import uid
        return uid.run()
    if name == 'tres':
        from godot_devkit.checks import tres
        return tres.run()
    if name == 'doc':
        from godot_devkit.checks import doc
        return doc.main([])
    if name == 'shell':
        from godot_devkit.checks import shell
        return shell.run()
    if name == 'repo-hygiene':
        from godot_devkit.checks import repo_hygiene
        return repo_hygiene.run()
    if name == 'all':
        worst = 0
        for check in OFFLINE_CHECKS:
            worst = max(worst, _run_check(check))
            print()
        return worst
    print(f'godot-devkit: unknown check {name!r} '
          f'(expected: {", ".join((*OFFLINE_CHECKS, "repo-hygiene", "all"))})', file=sys.stderr)
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
        from godot_devkit import scene_summary
        return scene_summary.main(rest)
    if cmd == 'scene-diff':
        from godot_devkit import scene_diff
        return scene_diff.main(rest)
    if cmd == 'refs':
        from godot_devkit import refs
        return refs.main(rest)
    if cmd == 'orphans':
        from godot_devkit import orphans
        return orphans.main(rest)
    if cmd == 'autoloads':
        from godot_devkit import autoloads
        return autoloads.main(rest)
    if cmd == 'check':
        if not rest:
            return _usage()
        return _run_check(rest[0])
    print(f'godot-devkit: unknown command {cmd!r}', file=sys.stderr)
    return _usage()


if __name__ == '__main__':
    raise SystemExit(main())
