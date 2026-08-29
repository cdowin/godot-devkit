#!/usr/bin/env python3
"""consumer_smoke.py — every verb against the live consumer checkouts.

THE CONSUMERS ARE THE FIXTURES. Two shipping game repos pin this package, and a
regression here reaches their commit gates before anyone notices it here. That
made a smoke run mandatory before a release — as a PROCEDURE, written in a skill,
performed by hand, differently each time. `make smoke` is the same thing as a
target, which is the only form of it that gets run.

WHAT IT ASSERTS, and why each is more than "it did not crash":

  * a gate that PASSES with the wrong census is a false PASS, so every printed
    count is compared against an INDEPENDENT one computed here from `git
    ls-files` and `project.godot`. Agreement is the check; the exit code alone
    is not.
  * the checkout is byte-clean before and after. Write verbs never run here —
    the consumers are shipping repos with their own dirty-tree gates — and a
    smoke run that leaves one dirty is a broken smoke run, not a thorough one.
  * a consumer that is not checked out is SKIPPED LOUDLY and named in the
    summary. Silence about what was not run is the thing this file's own
    contract forbids.

Read-only, no network, no Godot boot. Runs the WORKING TREE build via
PYTHONPATH — never `uvx --from .`, which caches by version and will happily
serve pre-fix code from a fix's own verification run.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DEVKIT = Path(__file__).resolve().parent.parent
CONSUMERS = (Path.home() / 'workspace' / 'trail',
             Path.home() / 'workspace' / 'nullbound')
SCENE_SUFFIXES = ('.tres', '.tscn')
DEFAULT_EXCLUDES = ('addons/',)


def devkit(root: Path, *argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, '-m', 'godot_devkit.cli', *argv],
        cwd=root, capture_output=True, text=True,
        env={**_env(), 'PYTHONPATH': str(DEVKIT / 'src')})
    return proc.returncode, proc.stdout + proc.stderr


def _env() -> dict:
    import os
    return dict(os.environ)


def git(root: Path, *argv: str) -> list[str]:
    proc = subprocess.run(['git', *argv], cwd=root,
                          capture_output=True, text=True)
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


class Report:
    """Rows and a verdict. Every row says what was compared against what."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.failed = 0
        self.skipped: list[str] = []

    def ok(self, consumer: str, what: str, detail: str) -> None:
        self.rows.append((consumer, f'ok    {what}', detail))

    def bad(self, consumer: str, what: str, detail: str) -> None:
        self.rows.append((consumer, f'FAIL  {what}', detail))
        self.failed += 1

    def check(self, consumer: str, what: str, cond: bool, detail: str) -> bool:
        (self.ok if cond else self.bad)(consumer, what, detail)
        return cond


def _scene_population(root: Path) -> int:
    """An INDEPENDENT count of the files the .tscn/.tres gates scan.

    Computed here from git rather than asked of the tool: a census compared
    against the tool's own idea of its scope would agree with any scoping bug
    the tool has.
    """
    excludes = _excludes(root)
    files = git(root, 'ls-files', '*.tres', '*.tscn')
    return sum(1 for f in files
               if f.endswith(SCENE_SUFFIXES)
               and not any(f.startswith(p) for p in excludes))


def _excludes(root: Path) -> tuple[str, ...]:
    cfg = root / 'devkit.toml'
    if not cfg.is_file():
        return DEFAULT_EXCLUDES
    import tomllib
    with cfg.open('rb') as fh:
        data = tomllib.load(fh)
    found = data.get('tres', {}).get('exclude_prefixes')
    return tuple(found) if isinstance(found, list) else DEFAULT_EXCLUDES


def _autoload_count(root: Path) -> int:
    body = (root / 'project.godot').read_text(encoding='utf-8', errors='replace')
    section = body.partition('[autoload]')[2].partition('\n[')[0]
    return sum(1 for line in section.splitlines() if '=' in line)


def _first(root: Path, pattern: str) -> str | None:
    """The first tracked match OUTSIDE addons/.

    Vendored plugin scenes are the same handful of files in every consumer, so
    smoking those tells you the tool still parses `addons/gut/GutScene.tscn` and
    nothing about the repo that pins this package.
    """
    found = [f for f in git(root, 'ls-files', pattern)
             if not f.startswith(DEFAULT_EXCLUDES)]
    return found[0] if found else None


def _a_class_name(root: Path) -> str | None:
    tracked = [f for f in git(root, 'ls-files', '*.gd')
               if not f.startswith(DEFAULT_EXCLUDES)]
    for rel in tracked[:400]:
        try:
            body = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        match = re.search(r'^class_name\s+(\w+)', body, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def smoke(root: Path, report: Report) -> None:
    name = root.name
    before = git(root, 'status', '--porcelain')
    if before:
        # Reported, not fatal: somebody else's uncommitted work is not this
        # run's finding. What WOULD be this run's finding is a difference
        # between before and after, which is checked at the end regardless.
        report.ok(name, 'pre-existing dirty tree',
                  f'{len(before)} path(s) already modified — not this run')

    code, out = devkit(root, 'check', 'all')
    report.check(name, 'check all', code == 0,
                 f'exit {code}' + ('' if code == 0 else f'\n{out[-2000:]}'))

    population = _scene_population(root)
    for gate, pattern in (('check tres', r'across (\d+) \.tres/\.tscn'),
                          ('check uid', r'across (\d+) file\(s\)')):
        code, out = devkit(root, *gate.split())
        match = re.search(pattern, out)
        if not match:
            report.bad(name, f'{gate} census', f'no census line in output')
            continue
        report.check(name, f'{gate} census', int(match.group(1)) == population,
                     f'gate says {match.group(1)}, git ls-files says {population}')

    code, out = devkit(root, 'autoloads')
    declared = _autoload_count(root)
    match = re.search(r'census \((\d+)\)', out)
    if match:
        report.check(name, 'autoloads census',
                     int(match.group(1)) == declared,
                     f'tool says {match.group(1)}, project.godot declares {declared}')
    else:
        report.bad(name, 'autoloads census', 'no census line in output')

    scene = _first(root, '*.tscn')
    if scene:
        code, out = devkit(root, 'scene', scene)
        report.check(name, 'scene', code == 0 and 'node tree' in out,
                     f'{scene}: exit {code}')
    else:
        report.skipped.append(f'{name}: scene (no .tscn tracked)')

    symbol = _a_class_name(root)
    if symbol:
        code, out = devkit(root, 'refs', symbol)
        report.check(name, 'refs', code == 0 and out.strip() != '',
                     f'{symbol}: exit {code}, {len(out.splitlines())} line(s)')
    else:
        report.skipped.append(f'{name}: refs (no class_name found)')

    for argv in (('pm', 'status'), ('pm', 'validate'), ('check', 'pm')):
        code, out = devkit(root, *argv)
        report.check(name, ' '.join(argv), code == 0,
                     f'exit {code}' + ('' if code == 0 else f'\n{out[-1500:]}'))

    after = git(root, 'status', '--porcelain')
    report.check(name, 'checkout unchanged', after == before,
                 'clean' if after == before
                 else f'the smoke run DIRTIED the tree: '
                      f'{sorted(set(after) - set(before))}')


def main() -> int:
    report = Report()
    present = [c for c in CONSUMERS if c.is_dir()]
    for absent in (c for c in CONSUMERS if not c.is_dir()):
        report.skipped.append(f'{absent} is not checked out')
    for root in present:
        smoke(root, report)

    width = max((len(r[1]) for r in report.rows), default=0)
    current = ''
    for consumer, what, detail in report.rows:
        if consumer != current:
            print(f'\n=== {consumer} ===')
            current = consumer
        print(f'  {what.ljust(width)}  {detail}')
    print()
    for line in report.skipped:
        print(f'[smoke] NOT RUN — {line}')
    if not present:
        # Loud, and exit 0: a machine without the consumers checked out has not
        # found a defect, and failing here would make the full gate unrunnable
        # anywhere but one laptop. What it must never do is imply it ran.
        print('[smoke] SKIPPED — no consumer checkout available; NOTHING was '
              'smoked. This is not a pass.')
        return 0
    if report.failed:
        print(f'[smoke] FAIL — {report.failed} check(s) across '
              f'{len(present)} consumer(s)')
        return 1
    print(f'[smoke] PASS — {len(report.rows)} check(s) across '
          f'{len(present)} consumer(s), every census matched an independent '
          f'count, both checkouts unchanged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
