"""unit_disk.py — check unit-disk: a unit test never borrows real persistent state.

The no-boot test tier is "isolated by construction" — but no-boot is not
no-global-state. A test that opens `user://`, or calls a save/settings API whose
root argument DEFAULTS to the real one, reaches the player's data from a tier
whose whole claim is that it cannot. That has cost real player data: an
unsandboxed run reset a live settings file to defaults and minted a stray save
slot into the real save directory.

A unit test constructs what it needs and destroys it. The redirect is a
settable property or an explicit parameter on the owner — never a boolean "am I
being tested" branch. This gate is what makes that a build failure rather than
a convention.

Three shapes, three config keys, because the three cannot share a matcher:

  forbidden_literals  a REAL path, matched on the line as written. The string
                      IS the violation, so quoted spans must survive the
                      sanitizer. Stock: any `user://` path.
  forbidden_calls     a call that touches live state. Matched on the line with
                      quoted spans and the trailing comment stripped — a call
                      NAMED in an assert message is not a call.
  min_args            a call whose root/scope parameter DEFAULTS to the real
                      one, and the number of arguments that proves it was
                      overridden. `Save.load(uuid)` is a finding where
                      `Save.load(uuid, throwaway_root)` is not.

HONEST SCOPE: matching is per line. A call split across a line break slips
through, and `min_args` counts only a call whose parentheses close on the same
line — an unbalanced line is skipped rather than guessed at.

devkit.toml:

    [unit_disk]
    roots = ["tests/unit"]
    forbidden_calls = { "the live settings autoload" = [
        "SettingsManager\\\\.(save_settings|load_settings|reset_to_defaults)\\\\(" ] }
    min_args = { "SaveService.save" = 2, "SaveSlotIndex.scan" = 1 }
"""
from __future__ import annotations

import re

from godot_devkit.core.config import (ConfigError, config_section, number_table,
                                      str_tuple, str_tuple_table)
from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.godot.index.gdscript import code_only

SECTION = 'unit_disk'
TAG = '[check:unit-disk]'
SUFFIX = '.gd'
DEFAULT_ROOTS = ('tests/unit',)
# The one persistent path every Godot project has, whatever else it calls its
# own state. A project's own owners go in `forbidden_calls` / `min_args`.
DEFAULT_FORBIDDEN_LITERALS = {'a real user:// path': ('user://',)}
DOC_COMMENT_RE = re.compile(r'^\s*##')
OPEN, CLOSE = '([{', ')]}'


def _compiled(sect: dict, key: str,
              fallback: dict[str, tuple[str, ...]]) -> list[tuple[str, re.Pattern]]:
    """`[(label, compiled)]` for one pattern table.

    Compiled HERE so a bad regex is exit 2 at load, not a traceback mid-scan —
    the same reason `core.config.pattern` compiles a single one.
    """
    out: list[tuple[str, re.Pattern]] = []
    for label, patterns in str_tuple_table(sect, SECTION, key, fallback).items():
        for source in patterns:
            try:
                out.append((label, re.compile(source)))
            except re.error as err:
                raise ConfigError(f'[{SECTION}] {key}.{label} is not a valid '
                                  f'regex: {err}') from err
    return out


def _min_args(sect: dict) -> dict[str, tuple[re.Pattern, int]]:
    """`{call: (matcher, floor)}` from `[unit_disk] min_args`."""
    out: dict[str, tuple[re.Pattern, int]] = {}
    for call, floor in number_table(sect, SECTION, 'min_args', {}).items():
        if floor < 1:
            raise ConfigError(
                f'[{SECTION}] min_args.{call} must be at least 1 — a floor of '
                f'{floor} is satisfied by every call, including the one whose '
                f'default root this key exists to forbid')
        out[call] = (re.compile(re.escape(call) + r'\s*\('), floor)
    return out


def count_args(code: str, open_at: int) -> int | None:
    """How many arguments the call whose `(` is at `open_at` was given.

    `None` when the call does not close on this line — an unbalanced line is
    something this gate declines to judge, never something it guesses at.
    `code` is a `code_only` line, so its strings are already masked and a comma
    inside one cannot read as an argument separator; nesting is tracked here.
    """
    depth, commas = 0, 0
    for index in range(open_at, len(code)):
        char = code[index]
        if char in OPEN:
            depth += 1
        elif char in CLOSE:
            depth -= 1
            if depth == 0:
                inner = code[open_at + 1:index]
                return commas + 1 if inner.strip() else 0
        elif char == ',' and depth == 1:
            commas += 1
    return None


def scan_text(text: str, path: str, literals, calls, min_args) -> list[str]:
    """`path:line  <label>: <code>` for every violation in one source."""
    findings: list[str] = []
    for lineno, raw in enumerate(text.split('\n'), start=1):
        if DOC_COMMENT_RE.match(raw):
            continue
        code = code_only(raw)
        # `code_only` masks in place, so its length is where the comment began:
        # the same line, comment gone, STRINGS INTACT — which is the only form
        # a path literal can be found in.
        uncommented = raw[:len(code)]
        for label, matcher in literals:
            if matcher.search(uncommented):
                findings.append(f'{path}:{lineno}  {label}: {raw.strip()}')
        for label, matcher in calls:
            if matcher.search(code):
                findings.append(f'{path}:{lineno}  {label}: {raw.strip()}')
        for call, (matcher, floor) in min_args.items():
            match = matcher.search(code)
            if not match:
                continue
            given = count_args(code, match.end() - 1)
            if given is not None and given < floor:
                findings.append(
                    f'{path}:{lineno}  {call} given {given} argument(s), needs '
                    f'{floor} — the omitted one defaults to the REAL root: '
                    f'{raw.strip()}')
    return findings


def run() -> int:
    sect = config_section(SECTION)
    roots = str_tuple(sect, SECTION, 'roots', DEFAULT_ROOTS)
    literals = _compiled(sect, 'forbidden_literals', DEFAULT_FORBIDDEN_LITERALS)
    calls = _compiled(sect, 'forbidden_calls', {})
    floors = _min_args(sect)
    root = repo_root()
    scanned = [rel for rel in git_lines('ls-files', '--', *roots)
               if rel.endswith(SUFFIX)]
    if not scanned:
        # Rule 4 — a gate that scanned nothing must say so.
        print(f'{TAG} FAIL — no tracked *{SUFFIX} under {", ".join(roots)}; '
              f'check [{SECTION}] roots')
        return 1

    findings: list[str] = []
    for rel in scanned:
        try:
            text = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        findings.extend(scan_text(text, rel, literals, calls, floors))

    if findings:
        for finding in findings:
            print(f'  DISK-WRITE  {finding}')
        print(f'\n{TAG} FAIL — {len(findings)} violation(s) across '
              f'{len(scanned)} test file(s) under {", ".join(roots)}')
        print('  A unit test constructs what it needs and destroys it — it '
              'never borrows a live path.')
        print('  Redirect through the owner\'s settable property or explicit '
              'root parameter, never a "am I being tested" branch.')
        return 1

    print(f'{TAG} PASS — {len(scanned)} test file(s) under '
          f'{", ".join(roots)} touch no real persistent state '
          f'({len(literals)} literal(s), {len(calls)} call(s), '
          f'{len(floors)} default-root call(s) checked)')
    return 0
