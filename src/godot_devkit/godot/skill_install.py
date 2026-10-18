"""Install the bundled skills into a Codex or Claude skills root.

The destination is a skills root, not a project root. Existing differing files
require --force. Every path is checked before the mutation plan runs.
"""
from __future__ import annotations

import difflib
import sys
from importlib import resources
from pathlib import Path

from godot_devkit.core import apply
from godot_devkit.core.project import repo_root
from godot_devkit.godot.install import destination_defect, read_destination

COMMAND = 'install-skills'
PACKAGE = 'godot_devkit.godot.installables'
FILES = ('SKILL.md', 'agents/openai.yaml')
USAGE = ('usage: godot-devkit install-skills [--runtime codex|claude] '
         '[--dest ROOT] [--skill NAME] [--check] [--force] [--diff]\n'
         'Install every bundled skill, or only NAME. ROOT is a skills directory; '
         'the default is .agents/skills for Codex or .claude/skills for Claude.')


SKILLS = ('godot-101', 'godot-native-first', 'godot-ui')
# Files a skill ships beyond FILES, named here so enumeration stays in core.walk.
EXTRA_FILES = {
    'godot-101': tuple(f'reference/{name}.md' for name in (
        'animation', 'audio', 'physics-and-collision', 'saving-and-data',
        'scenes-and-lifecycle', 'streaming-and-performance', 'testing-and-debugging', 'ui')),
}


def _skills() -> list[str]:
    return sorted(SKILLS)


def _source(skill: str, name: str) -> str:
    path = resources.files(PACKAGE)
    for part in ('skills', skill, *name.split('/')):
        path = path.joinpath(part)
    return path.read_text(encoding='utf-8')


def _options(argv: list[str]) -> tuple[str, Path | None, bool, bool, bool, str | None] | None:
    runtime = 'codex'
    skill: str | None = None
    dest: Path | None = None
    check = force = diff = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ('--runtime', '--dest', '--skill'):
            if index + 1 >= len(argv) or argv[index + 1].startswith('--'):
                print(f'godot-devkit {COMMAND}: {arg} needs a value', file=sys.stderr)
                return None
            value = argv[index + 1]
            if arg == '--runtime':
                runtime = value
            elif arg == '--skill':
                skill = value
            else:
                dest = Path(value).expanduser()
            index += 2
            continue
        if arg == '--check':
            check = True
        elif arg == '--force':
            force = True
        elif arg == '--diff':
            diff = True
        else:
            print(f'godot-devkit {COMMAND}: unknown argument {arg!r}',
                  file=sys.stderr)
            return None
        index += 1
    if runtime not in ('codex', 'claude'):
        print(f'godot-devkit {COMMAND}: unknown runtime {runtime!r} '
              '(expected codex or claude)', file=sys.stderr)
        return None
    if check and force:
        print(f'godot-devkit {COMMAND}: --check and --force cannot be combined',
              file=sys.stderr)
        return None
    return runtime, dest, check, force, diff, skill


def _difference(label: str, existing: str | None, desired: str) -> None:
    if existing is None:
        print(f'[install-skills] {label}: existing content is not UTF-8 text')
        return
    sys.stdout.writelines(difflib.unified_diff(
        existing.splitlines(keepends=True), desired.splitlines(keepends=True),
        fromfile=f'a/{label}', tofile=f'b/{label}'))


def _symlink_below_root(root: Path, target: Path) -> Path | None:
    """Find a symlink in the installed path, excluding the chosen skills root.

    The root can itself be a deliberate symlink (for a global skills store).
    Directories the verb creates below it, and each file slot, must stay inside
    that selected tree even under --force.
    """
    cursor = root
    for part in target.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return cursor
    return None


def main(argv: list[str]) -> int:
    if any(arg in ('-h', '--help', 'help') for arg in argv):
        print(USAGE)
        return 0
    options = _options(argv)
    if options is None:
        print(USAGE, file=sys.stderr)
        return 2
    runtime, dest, check, force, diff, skill = options
    root = dest if dest is not None else repo_root() / (
        '.agents/skills' if runtime == 'codex' else '.claude/skills')
    try:
        names = _skills()
        if skill is not None and skill not in names:
            print(f'godot-devkit {COMMAND}: unknown skill {skill!r} '
                  f'(bundled: {", ".join(names)})', file=sys.stderr)
            return 2
        entries = [(root / one / name, f'{one}/{name}', _source(one, name))
                   for one in names if skill in (None, one)
                   for name in FILES + EXTRA_FILES.get(one, ())]
    except (OSError, UnicodeError) as err:
        print(f'godot-devkit {COMMAND}: bundled skill cannot be read: {err}',
              file=sys.stderr)
        return 2

    defects: list[str] = []
    collisions: list[str] = []
    pending: list[tuple[Path, str, str]] = []
    drift = False
    for target, label, desired in entries:
        # A selected skills root can be a symlink. A symlink in the installed
        # path below it can escape that root, including when it is a directory.
        symlink = _symlink_below_root(root, target)
        defect = (f'{symlink} is a symlink below the skills root' if symlink
                  else destination_defect(target))
        if defect:
            defects.append(f'{label} {defect}')
            continue
        existing: str | None = None
        if target.exists():
            existing, unreadable = read_destination(target)
            if unreadable:
                defects.append(f'{label} {unreadable}')
                continue
        if existing == desired:
            print(f'[install-skills] {label} already current')
            continue
        drift = True
        if diff:
            if not target.exists():
                print(f'[install-skills] {label} missing — the whole file is an addition')
            _difference(label, existing if target.exists() else '', desired)
        elif check:
            print(f'[install-skills] {label} '
                  f'{"outdated" if target.exists() else "missing"}')
        if target.exists() and not force:
            collisions.append(label)
        pending.append((target, label, desired))

    if defects:
        for defect in defects:
            print(f'godot-devkit {COMMAND}: {defect}', file=sys.stderr)
        for label in collisions:
            print(f'godot-devkit {COMMAND}: {label} exists and differs; '
                  'move it aside or use --force', file=sys.stderr)
        print(f'godot-devkit {COMMAND}: nothing was written', file=sys.stderr)
        return 1
    if check:
        return 1 if drift else 0
    if diff:
        return 0
    if collisions:
        for label in collisions:
            print(f'godot-devkit {COMMAND}: {label} exists and differs; '
                  'move it aside or use --force', file=sys.stderr)
        print(f'godot-devkit {COMMAND}: nothing was written', file=sys.stderr)
        return 1

    plan = apply.Plan()
    for target, label, desired in pending:
        plan.overwrite(target, desired, label=label)
    outcome = plan.apply()
    if outcome.blocked:
        for blocked in outcome.blocked:
            print(f'godot-devkit {COMMAND}: {blocked.describe()}', file=sys.stderr)
        return 1
    for step in outcome.landed:
        print(f'[install-skills] wrote {step.label}')
    if outcome.failed is not None:
        print(f'godot-devkit {COMMAND}: {outcome.failed.label} could not be '
              f'written ({outcome.error}); {len(outcome.landed)} file(s) landed',
              file=sys.stderr)
        return 1
    return 0
