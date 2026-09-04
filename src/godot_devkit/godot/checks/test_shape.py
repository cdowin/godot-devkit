"""test_shape.py — check test-shape: the expensive test tier stays the SMALL one.

A two-tier suite says unit is the bulk and integration is the few. Nothing
holds it there: measured on one consumer, integration had grown to 60% of the
suite with six scenarios over 800 lines each — the rule was written, agreed,
and simply not binding. A big scenario is expensive in a way a big unit file is
not, because it boots a process: a 1000-line scenario is a unit suite wearing a
scenario's clothes, paying full boot cost to assert what needs no boot.

A RATCHET, not a big bang. Failing every over-cap file the day the gate lands
just means the gate gets switched off. Every file already over the cap is
recorded in `[test_shape] ledger` at its CURRENT size, and the gate fails only
when a file GROWS past its recorded ceiling or a NEW file crosses the cap. The
ledger is a DEBT LEDGER: its length is the metric, and it should only shrink.

  CHECK 1  no scenario off the ledger exceeds `[test_shape] cap` lines.
  CHECK 2  no scenario on the ledger exceeds its recorded ceiling.

A SCENARIO SAYS WHY IT BOOTS AND WHAT IT COVERS (opt-in, `header = true`).
The line cap catches a unit suite wearing a scenario's clothes after the fact;
nothing asked, at authoring time, whether the scenario needed to exist — a
fifth scenario for a shape four already cover. So a scenario's header (the
leading run of comment lines) carries two `##` lines:

    ## Boots because: tests/unit/<path> cannot <what only a boot can assert>
    ## covers: systems/<x>, resources/<y>.gd

`Boots because:` names the unit test that could NOT assert the claim without
a boot — or the existing scenario of the same shape it extends. `covers:` is
the repo-relative path prefixes the scenario exercises, which is what the
integration runner's `--diff <ref>` slices by. The same ratchet: every scenario
already written enters `[test_shape] header_ledger`, and leaves it when it is
touched and headed. A ledgered scenario that has GROWN a header is a finding
naming the ledger line to drop, so the ledger cannot go stale upward either.

  CHECK 3  every scenario off the header ledger carries both lines, well
           formed: a `Boots because:` naming a `tests/` path, and `covers:`
           entries that are repo-relative prefixes (no absolute, no `..`, no
           scheme, no glob, no whitespace, no empty segment) each of which
           EXISTS in the tree. The grammar is the runner's, entry for entry.
  CHECK 4  every scenario on the header ledger still exists, and carries no
           header — one that does has ratcheted out and the ledger line goes.

CHECK 3 and 4 are asked of THE RUNNER'S ROSTER — what `integration.sh --list`
prints, which is what `--all` boots and the only set `--diff` can slice to.
The runner owns discovery: its rule (support/ is fixtures, `_capture` is a
tool, the keep-list, the infra basenames) is configured in the runner file and
in GDK_* env, which a consumer edits and no TOML reader can see, so a roster
re-derived here was a second answer — measured on one consumer, 160 against
137, and the header rule was being asked of 22 capture tools and a support
stub. That GDK_* env is the consumer MAKEFILE's (`GDK_CAPTURE_GATE_RE := …`
plus `export`), so `bash <runner> --list` spawned from the gate's own process
answered with whatever the gate happened to inherit — 147 under `make check`,
137 from the `tools/dev/devkit` shim or a bare `uvx` — a census that was a
function of the CALLER, not of the tree. The gate therefore asks THROUGH the
consumer's `make integration-list` (a `Makefile.devkit` target) with the
GDK_* and MAKE* variables of its own environment stripped: the roster is what
a clean-shell `make integration` would boot, whoever runs the gate. No such
target is exit 2 naming it. `[test_shape] runner` names the file (stock:
where install-runners writes it) and reaches the target as
`GDK_RUNNERS_DIR`, so the gate and the target cannot name different files.
`header = true` with no runner there is exit 2; a runner that boots nothing
is a FAIL, never a PASS over nothing. CHECK 1 and 2 keep the
tracked census minus infra: the cap prices what lives in the tier, and a
capture tool that grew to 900 lines is tier weight whether or not the sweep
boots it.

HONEST SCOPE: this counts lines and reads two header lines. It cannot tell a
900-line scenario that genuinely needs a boot from one that should have been
ten unit tests, nor a true `Boots because:` from a hollow one — that judgement
stays with the reviewer. What it does is stop the tier drifting further out of
shape while nobody is looking, and make the author answer the question in the
file. The tier-balance line it prints is the number it exists to move, and is
informational: a share is not a finding, because there is no honest threshold
to fail it at.

Read-only, like every gate but `check uid --fix`: a file over the cap prints
the ledger line to paste, rather than the gate editing the config that governs
it.

devkit.toml:

    [test_shape]
    scenario_root = "tests/integration"
    unit_root = "tests/unit"
    cap = 300
    infra = ["scenario_base.gd", "scenario_runner.gd"]
    ledger = { "tests/integration/approach/approach_contracts.gd" = 956 }
    header = true
    header_ledger = ["tests/integration/approach/approach_contracts.gd"]
    runner = "tools/dev/runners/integration.sh"
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from godot_devkit.core.config import (ConfigError, config_section, flag,
                                      number, number_table, str_tuple, text)
from godot_devkit.core.project import git_lines, repo_root

SECTION = 'test_shape'
TAG = '[check:test-shape]'
SUFFIX = '.gd'
DEFAULT_SCENARIO_ROOT = 'tests/integration'
DEFAULT_UNIT_ROOT = 'tests/unit'
DEFAULT_CAP = 300
# Nothing by default. The tier's shared harness — a scenario base class, a
# lifecycle runner — boots once per scenario whatever its size and is where
# duplication is supposed to MOVE TO; measuring it as a scenario prices a
# shared helper above the hundred copies of it that it replaced. Which files
# those are is the project's fact, so the project names them.
DEFAULT_INFRA: tuple[str, ...] = ()
# Off by stock: a repo adopting the rule declares it, with the ledger of what
# it already has — a gate that reddened every existing scenario on the day of
# a pin bump would be switched off, not adopted.
DEFAULT_HEADER = False
# Where install-runners writes the integration runner. The header rule is
# asked of the roster it prints, so a header = true repo carries one.
DEFAULT_RUNNER = 'tools/dev/runners/integration.sh'
ROSTER_FLAG = '--list'
# The roster is asked THROUGH the consumer's make, so every export its
# Makefile hands `make integration` reaches `--list` the same way. The
# target is Makefile.devkit's; a Makefile that lacks it is exit 2 naming it.
MAKE = 'make'
ROSTER_TARGET = 'integration-list'
# What the gate's own environment must NOT contribute to that answer: the
# runner knobs (the consumer's Makefile sets them, or the runner defaults
# them) and the invoking make's flags (a `-n` or a jobserver would reach the
# nested run). Stripped, so the roster is a function of the tree alone.
ROSTER_ENV_PREFIX = 'GDK_'
ROSTER_ENV_DROPPED = ('MAKEFLAGS', 'MFLAGS', 'MAKELEVEL')
# make turns any recipe failure into its own exit 2 and names the recipe's
# real code on stderr — `make: *** [integration-list] Error 1` — which is
# the only way to tell the runner's "boots nothing" (1) from its "no such
# flag" (2) through the target.
MAKE_ERROR_RE = re.compile(r'\] Error (\d+)\s*$')
# make's own words for "there is no such target here", GNU make 3.81 and 4.x.
NO_TARGET_MARKERS = ('No rule to make target', 'no makefile found',
                     'No targets specified')
# How much of the runner's stderr a refusal quotes.
ROSTER_STDERR_LINES = 3
PERCENT = 100

BOOTS_KEY = 'Boots because:'
COVERS_KEY = 'covers:'
# A header line: `##`, the key, the value. Anchored on the line so prose that
# merely mentions the key is not a declaration.
HEADER_LINE = re.compile(r'^##[ \t]*(Boots because|covers):[ \t]*(.*?)[ \t]*$')
# What may appear in the header block: blank, any comment, the class prelude.
# The first line that is none of these ends the header.
HEADER_MEMBER = re.compile(r'^([ \t]*$|#|extends\b|class_name\b|@)')
# A `Boots because:` has to point at a test tier — a unit test that could not,
# or a scenario it extends. The reason around it is prose the gate cannot judge.
TESTS_PATH = re.compile(r'\btests/[A-Za-z0-9_./-]+')
COVERS_ENTRY_MAX = 200


class RosterUnavailable(Exception):
    """The runner could not say what it boots. `code` is the gate's exit —
    1 when it answered "nothing" (a finding), 2 when it could not answer."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def runner_path_defect(rel: str) -> str | None:
    """Why `rel` is not a repo-relative file path, or None when it is."""
    if not rel:
        return 'is empty'
    if rel.startswith('/'):
        return 'is absolute — the runner is a repo-relative path'
    if '\\' in rel:
        return 'carries a backslash'
    if any(seg in ('', '.', '..') for seg in rel.split('/')):
        return 'carries a dot or empty segment'
    return None


def runner_roster(root: Path, runner: str) -> list[str]:
    """The roster the runner would boot, repo-relative, sorted, deduplicated.

    Asked through `make integration-list` — the consumer's own Makefile, the
    one place its runner exports live — with `GDK_RUNNERS_DIR` set to the
    configured runner's directory, so the file this gate names is the file
    the target runs. The gate's own GDK_* / MAKE* environment is dropped
    first: the answer must be the tree's, never the caller's. Raises
    RosterUnavailable rather than returning an empty roster: a header rule
    asked of nothing must say so (rule 4).
    """
    path = root / runner
    if not path.is_file():
        raise RosterUnavailable(
            2, f'[{SECTION}] header = true asks the header rule of the roster '
               f'{runner} boots, and there is no such file — `install-runners` '
               f'writes it; a runner elsewhere is `[{SECTION}] runner`')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(ROSTER_ENV_PREFIX)
           and key not in ROSTER_ENV_DROPPED}
    runners_dir = Path(runner).parent.as_posix()
    argv = [MAKE, '-s', '--no-print-directory', '-C', str(root),
            ROSTER_TARGET, f'GDK_RUNNERS_DIR={runners_dir}']
    try:
        done = subprocess.run(argv, cwd=root, env=env, capture_output=True,
                              text=True, encoding='utf-8', errors='replace')
    except OSError as err:
        raise RosterUnavailable(2, f'could not run {MAKE}: {err}') from err
    if done.returncode == 0:
        return sorted({str(Path(line.strip())) for line in done.stdout.splitlines()
                       if line.strip()})
    stderr_lines = done.stderr.strip().splitlines()
    if any(marker in done.stderr for marker in NO_TARGET_MARKERS):
        raise RosterUnavailable(
            2, f'`{MAKE} {ROSTER_TARGET}` is not a target here — the roster is '
               f'asked through your Makefile so the exports `make integration` '
               f'boots with reach {ROSTER_FLAG} too; `include Makefile.devkit` '
               f'defines it, and `install-runners --force` writes the current '
               f'one')
    runner_exit = next((int(m.group(1)) for line in reversed(stderr_lines)
                        if (m := MAKE_ERROR_RE.search(line))), 2)
    said = ' / '.join(line for line in stderr_lines[-ROSTER_STDERR_LINES:]
                      if not line.startswith(f'{MAKE}:'))
    if runner_exit == 1:
        raise RosterUnavailable(1, f'{runner} boots NOTHING — {said}')
    raise RosterUnavailable(
        2, f'{runner} {ROSTER_FLAG} exited {runner_exit} ({said}) — a runner '
           f'installed before {ROSTER_FLAG} existed answers this; re-install '
           f'the runners with `install-runners --force`')


def header_block(text_body: str) -> list[str]:
    """The leading run of lines a header may consist of."""
    lines: list[str] = []
    for line in text_body.split('\n'):
        if not HEADER_MEMBER.match(line):
            break
        lines.append(line)
    return lines


def read_header(text_body: str) -> tuple[str | None, list[str] | None]:
    """(boots, covers) — each None when its key is absent from the header.

    Several `## covers:` lines union; the first `## Boots because:` wins.
    Entries are comma-split and trimmed; ONE trailing `/` is dropped so a
    directory spelled either way is the same prefix — exactly one, the same
    as the runner, so a doubled slash reaches the grammar as the empty
    segment it is rather than being normalised into a directory that exists.
    """
    boots: str | None = None
    covers: list[str] | None = None
    for line in header_block(text_body):
        found = HEADER_LINE.match(line)
        if not found:
            continue
        key, value = found.group(1), found.group(2)
        if key == 'Boots because':
            if boots is None:
                boots = value
        else:
            covers = (covers or []) + [_one_trailing_slash_dropped(part.strip())
                                       for part in value.split(',')]
    return boots, covers


def _one_trailing_slash_dropped(entry: str) -> str:
    return entry[:-1] if entry.endswith('/') else entry


def covers_entry_defect(entry: str) -> str | None:
    """Why `entry` is not a repo-relative path prefix, or None when it is.

    The runner only ever COMPARES an entry as a string, so a hostile one can
    select nothing — but a malformed declaration is a declaration that lies.
    The grammar mirrors the runner's, which drops what this refuses.
    """
    if not entry:
        return 'is empty'
    if len(entry) > COVERS_ENTRY_MAX:
        return f'is longer than {COVERS_ENTRY_MAX} characters'
    if entry.startswith('/'):
        return 'is absolute — a covers entry is repo-relative'
    if '://' in entry:
        return 'carries a scheme — write the repo-relative path, not res://'
    if '\\' in entry:
        return 'carries a backslash'
    if any(ch in entry for ch in '*?['):
        return 'carries a glob — a covers entry is a literal prefix'
    if any(ch.isspace() for ch in entry):
        return 'carries whitespace'
    if any(seg in ('.', '..') for seg in entry.split('/')):
        return 'carries a dot segment'
    # After the one trailing slash the reader drops, a slash with nothing
    # after it — `a//b`, `a//`, `a/` — is an empty segment. Path() would
    # collapse it to a directory that exists; the runner compares strings and
    # would never match it. Refused, so the two cannot disagree.
    if '' in entry.split('/')[1:]:
        return 'carries an empty segment (a doubled slash)'
    return None


def header_defects(root: Path, text_body: str) -> list[str]:
    """Everything wrong with a scenario's header; empty when it is whole."""
    boots, covers = read_header(text_body)
    defects: list[str] = []
    if boots is None:
        defects.append(f'no `## {BOOTS_KEY}` line')
    elif not boots:
        defects.append(f'`## {BOOTS_KEY}` says nothing')
    elif not TESTS_PATH.search(boots):
        defects.append(f'`## {BOOTS_KEY}` names no tests/ path — the unit '
                       f'test that could not, or the scenario it extends')
    if covers is None:
        defects.append(f'no `## {COVERS_KEY}` line')
    else:
        for entry in covers:
            why = covers_entry_defect(entry)
            if why:
                defects.append(f'covers `{entry}` {why}')
            elif not (root / entry).exists():
                defects.append(f'covers `{entry}`, which is not in the tree')
    return defects


def has_any_header(text_body: str) -> bool:
    boots, covers = read_header(text_body)
    return boots is not None or covers is not None


def line_count(text_body: str) -> int:
    """Lines, counted as `wc -l` counts them — newlines, not fragments.

    The ledger's numbers were measured with `wc -l`; a different definition
    here would redden every entry on adoption day.
    """
    return text_body.count('\n')


def _measure(root, rels: list[str]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for rel in rels:
        try:
            sizes[rel] = line_count((root / rel).read_text(encoding='utf-8',
                                                           errors='replace'))
        except OSError:
            continue
    return sizes


def run() -> int:
    sect = config_section(SECTION)
    scenario_root = text(sect, SECTION, 'scenario_root', DEFAULT_SCENARIO_ROOT)
    unit_root = text(sect, SECTION, 'unit_root', DEFAULT_UNIT_ROOT)
    cap = number(sect, SECTION, 'cap', DEFAULT_CAP)
    infra = str_tuple(sect, SECTION, 'infra', DEFAULT_INFRA)
    ledger = number_table(sect, SECTION, 'ledger', {})
    header = flag(sect, SECTION, 'header', DEFAULT_HEADER)
    header_ledger = set(str_tuple(sect, SECTION, 'header_ledger', ()))
    runner = text(sect, SECTION, 'runner', DEFAULT_RUNNER)
    why = runner_path_defect(runner)
    if why:
        raise ConfigError(f'[{SECTION}] runner {why}: {runner!r}')
    root = repo_root()

    tracked = [rel for rel in git_lines('ls-files', '--', scenario_root)
               if rel.endswith(SUFFIX)]
    scanned = [rel for rel in tracked if rel.rsplit('/', 1)[-1] not in infra]
    if not scanned:
        # Rule 4 — a gate that scanned nothing must say so, and name which of
        # the two reasons applies.
        print(f'{TAG} FAIL — scanned 0 of {len(tracked)} tracked *{SUFFIX} '
              f'under {scenario_root}/; check [{SECTION}] scenario_root/infra')
        return 1

    sizes = _measure(root, scanned)
    findings: list[str] = []
    for rel in sorted(sizes):
        lines = sizes[rel]
        ceiling = ledger.get(rel)
        if ceiling is not None:
            if lines > ceiling:
                findings.append(f'  GREW  {rel} — {lines} lines, ledger '
                                f'ceiling {ceiling}')
        elif lines > cap:
            findings.append(f'  OVERCAP  {rel} — {lines} lines (cap {cap}, not '
                            f'on the [{SECTION}] ledger)')

    header_findings: list[str] = []
    roster: list[str] = []
    if header:
        try:
            roster = runner_roster(root, runner)
        except RosterUnavailable as err:
            print(f'{TAG} {"FAIL" if err.code == 1 else "ERROR"} — {err}')
            return err.code
        for rel in roster:
            try:
                body = (root / rel).read_text(encoding='utf-8', errors='replace')
            except OSError:
                header_findings.append(f'  UNREADABLE  {rel} — on the roster '
                                       f'{runner} prints, not readable on disk')
                continue
            if rel in header_ledger:
                if has_any_header(body):
                    # Ratcheted out: the file answered the question. Validate
                    # what it says, and the ledger line goes.
                    header_findings.append(
                        f'  HEADED  {rel} — carries its header; drop it from '
                        f'[{SECTION}] header_ledger')
                    header_findings.extend(
                        f'  HEADER  {rel} — {why}'
                        for why in header_defects(root, body))
                continue
            defects = header_defects(root, body)
            if not has_any_header(body):
                header_findings.append(
                    f'  NO-HEADER  {rel} — says neither why it boots nor '
                    f'what it covers')
            else:
                header_findings.extend(f'  HEADER  {rel} — {why}'
                                       for why in defects)
        for rel in sorted(header_ledger - set(roster)):
            header_findings.append(
                f'  STALE  {rel} — on [{SECTION}] header_ledger but not a '
                f'scenario the runner boots (a capture tool, a support stub, '
                f'infra, or gone); drop the line')

    unit_lines = sum(_measure(root, [rel for rel
                                     in git_lines('ls-files', '--', unit_root)
                                     if rel.endswith(SUFFIX)]).values())
    # The BALANCE counts the whole tier, infra included — the shared harness
    # boots with every scenario, so it is part of what the tier costs. Only the
    # CAP excludes it, and for the opposite reason: a helper that replaced a
    # hundred copies of itself must not be priced as a scenario.
    scenario_lines = sum(_measure(root, tracked).values())
    total = unit_lines + scenario_lines
    if total:
        share = PERCENT * scenario_lines // total
        print(f'  tier balance: unit {unit_lines} / {scenario_root} '
              f'{scenario_lines} — the booting tier is {share}% of the suite')
    print(f'  debt ledger: {len(ledger)} scenario(s) over cap — this number '
          f'should only shrink')
    if header:
        print(f'  header ledger: {len(header_ledger)} scenario(s) yet to say '
              f'why they boot — this number should only shrink')
        print(f'  roster: {len(roster)} scenario(s) the runner would boot '
              f'({runner} {ROSTER_FLAG}) — the header rule is asked of exactly '
              f'those')

    if findings or header_findings:
        for finding in findings + header_findings:
            print(finding)
        # One census per line. The cap is asked of the tracked tier minus
        # infra; the header rule of the roster the runner boots. A verdict
        # that said "N findings across 160" while the roster was 147 was
        # two censuses in one sentence, and neither number was the other's.
        if header:
            print(f'\n{TAG} FAIL — {len(findings) + len(header_findings)} '
                  f'finding(s)')
            print(f'  size: {len(findings)} finding(s) across {len(scanned)} '
                  f'scenario(s) under {scenario_root}/')
            print(f'  header: {len(header_findings)} finding(s) across '
                  f'{len(roster)} the runner would boot')
        else:
            print(f'\n{TAG} FAIL — {len(findings)} finding(s) across '
                  f'{len(scanned)} scenario(s)')
        if findings:
            print(f'  A scenario over {cap} lines is usually a unit suite '
                  f"wearing a scenario's clothes:")
            print('  assert the contract in the no-boot tier and keep the '
                  'scenario to the use case.')
            print(f'  If the size is genuinely earned, record it in '
                  f'[{SECTION}] ledger and say why in the commit:')
            for rel in sorted(sizes):
                if any(rel in finding for finding in findings):
                    print(f'      "{rel}" = {sizes[rel]}')
        if header_findings:
            print('  A scenario says, in its leading comment block, why it '
                  'boots and what it covers:')
            print(f'      ## {BOOTS_KEY} tests/unit/<path> cannot <what only '
                  f'a boot can assert>')
            print(f'      ## {COVERS_KEY} systems/<x>, resources/<y>.gd')
        return 1

    headed = (f', every one off the header ledger says why it boots '
              f'({len(roster)} the runner would boot)' if header else '')
    print(f'{TAG} PASS — {len(scanned)} scenario(s) under {scenario_root}/, '
          f'none over the {cap}-line cap or its ledger ceiling{headed}')
    return 0
