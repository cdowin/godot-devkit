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
"""
from __future__ import annotations

import re
from pathlib import Path

from godot_devkit.core.config import (config_section, flag, number,
                                      number_table, str_tuple, text)
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
    if header:
        for rel in sorted(sizes):
            body = (root / rel).read_text(encoding='utf-8', errors='replace')
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
        for rel in sorted(header_ledger - set(sizes)):
            header_findings.append(
                f'  STALE  {rel} — on [{SECTION}] header_ledger but not a '
                f'scanned scenario; drop the line')

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

    if findings or header_findings:
        for finding in findings + header_findings:
            print(finding)
        print(f'\n{TAG} FAIL — {len(findings) + len(header_findings)} '
              f'finding(s) across {len(scanned)} scenario(s)')
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

    headed = (f', every one off the header ledger says why it boots'
              if header else '')
    print(f'{TAG} PASS — {len(scanned)} scenario(s) under {scenario_root}/, '
          f'none over the {cap}-line cap or its ledger ceiling{headed}')
    return 0
