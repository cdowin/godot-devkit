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
  * THE FRESH PROJECT is smoked too, and it is the one probe here that writes:
    an empty Godot 4 project in a temp dir, `godot-devkit init`, then the REAL
    `make doctor`. The suite proves the written file set and dry-runs every
    target; only a real host can run the engine-facing half, so this is where
    it happens. Never inside a consumer checkout — write verbs do not run
    against a shipping game repo.

Read-only, no network, no Godot boot. Runs the WORKING TREE build via
PYTHONPATH — never `uvx --from .`, which caches by version and will happily
serve pre-fix code from a fix's own verification run.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEVKIT = Path(__file__).resolve().parent.parent
CONSUMERS = (Path.home() / 'workspace' / 'trail',
             Path.home() / 'workspace' / 'nullbound')
SCENE_SUFFIXES = ('.tres', '.tscn')
DEFAULT_EXCLUDES = ('addons/',)

# --- the fresh-project probe --------------------------------------------------
FRESH = 'fresh project'
GODOT = 'godot'
HOOKS_PATH = 'tools/hooks'
TRACKED_HOOKS = 6
FRESH_PROJECT_GODOT = ('config_version=5\n\n[application]\n\n'
                       'config/name="Fresh"\nconfig/version="0.1.0"\n')
FRESH_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>\n'
# The doctor rows `init` is RESPONSIBLE for. Everything else doctor reports is
# a fact about the HOST (godot, gdlint, uv on PATH) or about a project that has
# not added GUT yet — real, worth printing, and not this probe's finding.
INIT_OWNED = ('core.hooksPath', 'tracked hook')
# `make check`'s verdict shape, and the one FAIL that is not this probe's
# finding. A blank Godot project holds no .tscn/.tres, so the three gates that
# read them report a 0-file census and correctly redden — the stock roster
# being wrong for a repo with no scenes yet, which the seed devkit.toml names
# and narrows in one line. ANY OTHER FAIL is a finding about a file `init`
# itself wrote, which is exactly how a `compile_sweep.gd` with no `.uid`
# sidecar shipped: the suite dry-ran `precommit`, and a dry run reaches no
# verdict to read.
CHECK_VERDICT_RE = re.compile(r'^\[check:([a-z-]+)\] (PASS|FAIL) — (.*)$',
                              re.MULTILINE)
CHECK_EMPTY_CENSUS = 'scanned 0 of 0 tracked'
CHECK_LOG = '.gate-reports/check.log'


def devkit(root: Path, *argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, '-m', 'godot_devkit.cli', *argv],
        cwd=root, capture_output=True, text=True,
        env={**_env(), 'PYTHONPATH': str(DEVKIT / 'src')})
    return proc.returncode, proc.stdout + proc.stderr


def _env() -> dict:
    import os
    return dict(os.environ)


def working_tree_devkit() -> str:
    """`make check` resolves `DEVKIT` to `uvx --from git+…@<pin>` — the
    RELEASED tag, over the network. This whole file runs the WORKING TREE, so
    the override goes on the command line; it is not a hand edit to the
    project, and without it the probe would grade the last release."""
    return (f'DEVKIT=env PYTHONPATH={DEVKIT / "src"} '
            f'{sys.executable} -m godot_devkit.cli')


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


def fresh_project(report: Report) -> None:
    """init an empty Godot 4 project in scratch, then run the REAL make doctor
    and the REAL make check.

    The ship criterion of the bootstrap milestone, on a real host: `init`, then
    `make doctor` green and no `make check` finding about anything the install
    wrote, with zero hand edits. What this can assert everywhere is the half
    `init` OWNS — the hooks armed, git pointed at them, and every gate quiet
    about the files the verb just wrote. Whether doctor is GREEN also depends
    on the host having godot, gdlint and uv, so the verdict distinguishes the
    two: an init-owned FAIL is this probe's finding, a missing host tool is
    named and is not.
    """
    if shutil.which('make') is None or shutil.which('git') is None:
        report.skipped.append(f'{FRESH}: needs make and git')
        return
    if shutil.which(GODOT) is None:
        report.skipped.append(
            f'{FRESH}: `{GODOT}` is not on PATH — the real `make doctor` was '
            f'NOT run (the suite still proves the file set and `make -n`)')
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'game'
        root.mkdir()
        (root / 'project.godot').write_text(FRESH_PROJECT_GODOT, encoding='utf-8')
        (root / 'icon.svg').write_text(FRESH_ICON, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)

        code, out = devkit(root, 'init')
        if not report.check(FRESH, 'godot-devkit init', code == 0,
                            f'exit {code}' + ('' if code == 0 else f'\n{out[-2000:]}')):
            return

        doctor = subprocess.run(['make', 'doctor'], cwd=root, text=True,
                                capture_output=True, env=dict(os.environ),
                                timeout=300)
        rows = doctor.stdout.splitlines()
        failed = [r.strip() for r in rows if r.strip().startswith('FAIL')]
        mine = [r for r in failed if any(k in r for k in INIT_OWNED)]
        report.check(FRESH, 'make doctor: hooks armed', not mine,
                     'git points at the installed hooks and every one is '
                     'executable' if not mine else '; '.join(mine))
        armed = sum(1 for r in rows
                    if 'tracked hook' in r and 'present + executable' in r)
        report.check(FRESH, 'make doctor: hook census', armed == TRACKED_HOOKS,
                     f'{armed} tracked hook(s) armed, {TRACKED_HOOKS} installed')
        host_gaps = [r for r in failed if r not in mine]
        report.check(FRESH, 'make doctor verdict',
                     doctor.returncode == 0 or bool(host_gaps),
                     f'exit {doctor.returncode}'
                     + (f'; host gaps, not this install: {"; ".join(host_gaps)}'
                        if host_gaps else ' — green on a fresh project'))
        if host_gaps:
            report.skipped.append(
                f'{FRESH}: `make doctor` is not green on this host — '
                f'{"; ".join(host_gaps)}')

        # …and the REAL `make check`. It boots nothing — the roster is pure
        # parse — so unlike doctor there is no host to blame and no reason
        # this was ever a dry run. Committed first: every gate resolves its
        # scope through `git ls-files`, and an uncommitted tree is a 0-file
        # census for all of them.
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(['git', '-c', 'user.email=smoke@example.com',
                        '-c', 'user.name=smoke', 'commit', '-qm',
                        'godot-devkit init', '--', '.'],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['make', 'check', working_tree_devkit()], cwd=root,
                       text=True, capture_output=True, env=_env(), timeout=300)
        transcript = (root / CHECK_LOG)
        verdicts = CHECK_VERDICT_RE.findall(
            transcript.read_text(encoding='utf-8') if transcript.is_file()
            else '')
        report.check(FRESH, 'make check: gates ran',
                     bool(verdicts), f'{len(verdicts)} gate verdict(s)')
        ours = [f'[check:{gate}] {detail}' for gate, outcome, detail in verdicts
                if outcome == 'FAIL' and CHECK_EMPTY_CENSUS not in detail]
        report.check(FRESH, 'make check: nothing init wrote is a finding',
                     not ours,
                     'no gate has a finding about an installed file'
                     if not ours else '; '.join(ours))
        empty = [gate for gate, outcome, detail in verdicts
                 if outcome == 'FAIL' and CHECK_EMPTY_CENSUS in detail]
        if empty:
            report.skipped.append(
                f'{FRESH}: {", ".join(empty)} report a 0-file census — a blank '
                f'project holds no .tscn/.tres; the roster is narrowed in '
                f'devkit.toml, not softened here')


def main() -> int:
    report = Report()
    fresh_project(report)
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
    if report.failed:
        print(f'[smoke] FAIL — {report.failed} check(s) across '
              f'{len(present)} consumer(s) + the fresh project')
        return 1
    if not present:
        # Loud, and exit 0: a machine without the consumers checked out has not
        # found a defect, and failing here would make the full gate unrunnable
        # anywhere but one laptop. What it must never do is imply it ran.
        print('[smoke] SKIPPED — no consumer checkout available; NOTHING was '
              'smoked against a live consumer. This is not a pass.')
        return 0
    print(f'[smoke] PASS — {len(report.rows)} check(s) across '
          f'{len(present)} consumer(s) + the fresh project, every census '
          f'matched an independent count, both checkouts unchanged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
