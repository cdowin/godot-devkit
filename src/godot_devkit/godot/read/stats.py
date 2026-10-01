#!/usr/bin/env python3
"""stats.py — how much code is in this project, and where.

One row per bucket — `.gd` split by role (game, tests, tools, vendored), then
`.gdshader`, `.tscn` and `.tres` — each with its file, line and code-line
count, and a final census line naming the files scanned and the dirs. Only
git-known files are counted (tracked + untracked-but-not-ignored, the set
`orphans` scans), so `.godot/` and every other ignored artifact stays out.
Pure parse — never writes, never boots Godot.

    godot-devkit stats [<dir>...] [--by dir] [--json]

A CODE line is non-blank and not a comment. In `.gd` a comment line starts
(after indentation) with `#`, and every line of a block opened by a line that
starts with `\"\"\"` — a docstring — is a comment up to the line that closes it.
In `.gdshader` a comment line starts with `//`, and every line of a `/* … */`
block is one. `.tscn`/`.tres` have no code column (`-`). Under `tests .gd`,
one indented row per immediate subdir of each tests prefix carries a
`func test_` count; `--by dir` adds one indented row per top-level dir under
`game .gd`. `<dir>...` narrows the scan to those dirs (default: the repo root).

Exit 0 with a table; 1 when the scan counted zero files (a census of nothing
is never a clean answer); 2 on a usage or `[stats]` config error.

devkit.toml: [stats] tests    = ["tests/"]
                     tools    = ["tools/"]
                     vendored = ["addons/"]
             (repo-relative prefixes; each key replaces its default
              wholesale; a `.gd` under none of them is game. List only the
              vendored addons to count your own addon as game code.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.core import walk
from godot_devkit.core.config import ConfigError, config_section, str_tuple
from godot_devkit.core.project import repo_root
from godot_devkit.godot import VENDORED_DEFAULT
from godot_devkit.godot.read.orphans import Refusal, tracked_files

CONFIG_SECTION = 'stats'
DEFAULT_TESTS = ('tests/',)
DEFAULT_TOOLS = ('tools/',)

GD, SHADER, SCENE, RESOURCE = '.gd', '.gdshader', '.tscn', '.tres'
SUFFIXES = (GD, SHADER, SCENE, RESOURCE)
GAME, TESTS, TOOLS, VENDORED = 'game .gd', 'tests .gd', 'tools .gd', 'vendored .gd'
# Render order. A bucket with no files still prints its row: the table's shape
# is the same on every tree, so a consumer can grep a row without guarding it.
BUCKETS = (GAME, TESTS, TOOLS, VENDORED, SHADER, SCENE, RESOURCE)
NO_CODE = (SCENE, RESOURCE)
ROOT_LABEL = './'
DASH = '-'
CENSUS_LABEL = 'file(s) scanned'
HEADER = ('bucket', 'files', 'lines', 'code', 'tests')
INDENT = '  '

TEST_FUNC = re.compile(r'^\s*func\s+test_')
GD_DOCSTRING = '"""'


@dataclass(frozen=True)
class Settings:
    """The resolved `[stats]` config — loaded at CALL time, never at import."""
    tests: tuple[str, ...]
    tools: tuple[str, ...]
    vendored: tuple[str, ...]


@dataclass
class Row:
    label: str
    files: int = 0
    lines: int = 0
    code: int | None = 0
    tests: int | None = None
    children: dict[str, 'Row'] = field(default_factory=dict)

    def add(self, lines: int, code: int | None, tests: int | None) -> None:
        self.files += 1
        self.lines += lines
        if self.code is not None and code is not None:
            self.code += code
        if self.tests is not None and tests is not None:
            self.tests += tests

    def child(self, label: str) -> 'Row':
        if label not in self.children:
            self.children[label] = Row(
                label, code=None if self.code is None else 0,
                tests=None if self.tests is None else 0)
        return self.children[label]

    def as_json(self) -> dict:
        out: dict = {'bucket': self.label, 'files': self.files,
                     'lines': self.lines, 'code': self.code}
        if self.tests is not None:
            out['tests'] = self.tests
        return out


def _dirs(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    """Each prefix as a directory: `tests` must not take in `testsuite/`."""
    return tuple(p if p.endswith('/') else p + '/' for p in prefixes)


def load_settings() -> Settings:
    sect = config_section(CONFIG_SECTION)
    return Settings(
        tests=_dirs(str_tuple(sect, CONFIG_SECTION, 'tests', DEFAULT_TESTS)),
        tools=_dirs(str_tuple(sect, CONFIG_SECTION, 'tools', DEFAULT_TOOLS)),
        vendored=_dirs(str_tuple(sect, CONFIG_SECTION, 'vendored', VENDORED_DEFAULT)),
    )


def gd_line_counts(text: str) -> tuple[int, int, int]:
    """(lines, code lines, `func test_` count) of one `.gd` source."""
    lines = text.splitlines()
    code = tests = 0
    in_block = False   # inside a `"""` block
    block_is_code = False  # …that a code line opened (a multi-line string value)
    for line in lines:
        stripped = line.strip()
        odd = stripped.count(GD_DOCSTRING) % 2 == 1
        if in_block:
            if block_is_code and stripped:
                code += 1
            if odd:
                in_block = False
            continue
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith(GD_DOCSTRING):
            in_block, block_is_code = odd, False
            continue
        code += 1
        if TEST_FUNC.match(line):
            tests += 1
        if odd:
            in_block, block_is_code = True, True
    return len(lines), code, tests


def _opens_block_comment(line: str) -> bool:
    """Does this shader line leave a `/*` open past its end? A `//` that comes
    before any `/*` ends the line's code, and whatever follows it with it."""
    if '//' in line.split('/*', 1)[0]:
        line = line.split('//', 1)[0]
    return line.rfind('/*') > line.rfind('*/')


def shader_line_counts(text: str) -> tuple[int, int]:
    """(lines, code lines) of one `.gdshader` source."""
    lines = text.splitlines()
    code = 0
    in_block = False
    for line in lines:
        stripped = line.strip()
        if in_block:
            if '*/' in stripped:
                in_block = False
                tail = stripped.split('*/', 1)[1].strip()
                if tail and not tail.startswith('//'):
                    code += 1
                    in_block = _opens_block_comment(tail)
            continue
        if not stripped or stripped.startswith('//'):
            continue
        if stripped.startswith('/*'):
            in_block = _opens_block_comment(stripped)
            continue
        code += 1
        in_block = _opens_block_comment(stripped)
    return len(lines), code


def _under(rel: str, prefixes: tuple[str, ...]) -> str | None:
    """The first prefix `rel` lives under, or None."""
    for prefix in prefixes:
        if rel.startswith(prefix):
            return prefix
    return None


def _subdir_label(rel: str, prefix: str) -> str:
    """`tests/unit/` for `tests/unit/a/test_x.gd`; the prefix itself for a file
    directly under it."""
    rest = rel[len(prefix):].lstrip('/')
    base = prefix if prefix.endswith('/') else prefix + '/'
    return base + rest.split('/', 1)[0] + '/' if '/' in rest else base


def gd_bucket(rel: str, settings: Settings) -> str:
    """Which `.gd` role a path plays — vendored first, so an addon's own tests
    are the addon's, never the project's."""
    if _under(rel, settings.vendored) is not None:
        return VENDORED
    if _under(rel, settings.tests) is not None:
        return TESTS
    if _under(rel, settings.tools) is not None:
        return TOOLS
    return GAME


def tally(root: Path, files: walk.Walk, settings: Settings,
          by_dir: bool) -> dict[str, Row]:
    """Every bucket's row, its tier/dir children filled in."""
    rows = {name: Row(name, code=None if name in NO_CODE else 0,
                      tests=0 if name == TESTS else None)
            for name in BUCKETS}
    for path in files:
        rel = path.as_posix()
        text = (root / path).read_text(encoding='utf-8', errors='replace')
        suffix = path.suffix.lower()
        if suffix == GD:
            lines, code, tests = gd_line_counts(text)
            name = gd_bucket(rel, settings)
            rows[name].add(lines, code, tests)
            if name == TESTS:
                prefix = _under(rel, settings.tests)
                rows[TESTS].child(_subdir_label(rel, prefix)).add(lines, code, tests)
            elif name == GAME and by_dir:
                label = rel.split('/', 1)[0] + '/' if '/' in rel else ROOT_LABEL
                rows[GAME].child(label).add(lines, code, None)
        elif suffix == SHADER:
            rows[SHADER].add(*shader_line_counts(text), None)
        else:
            rows[suffix].add(len(text.splitlines()), None, None)
    return rows


class Usage(Exception):
    """A `<dir>` argument this verb cannot scope to — exit 2."""


def scope_prefixes(root: Path, dirs: list[str]) -> tuple[str, ...]:
    """Each `<dir>` as a repo-relative `prefix/`; () for the repo root."""
    prefixes: list[str] = []
    for raw in dirs:
        target = (Path.cwd() / raw).resolve()
        try:
            rel = target.relative_to(root.resolve()).as_posix()
        except ValueError as err:
            raise Usage(f'stats: {raw!r} is outside the repo at {root}') from err
        if rel == '.':
            return ()
        prefixes.append(rel + '/')
    return tuple(dict.fromkeys(prefixes))


def scan(root: Path, prefixes: tuple[str, ...]) -> walk.Walk:
    """The git-known files with a counted suffix that are on disk — the
    universe — narrowed to `prefixes`, every path it drops disclosed."""
    universe = walk.Walk(tuple(
        Path(rel) for rel in sorted(tracked_files(root))
        if Path(rel).suffix.lower() in SUFFIXES and (root / rel).is_file()))
    if not prefixes:
        return universe
    return universe.filter(lambda p: p.as_posix().startswith(prefixes),
                           walk.SkipReason.EXCLUDED_PATH)


def _cell(value: int | None) -> str:
    return DASH if value is None else str(value)


def _table(rows: dict[str, Row]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = [HEADER]
    for name in BUCKETS:
        row = rows[name]
        for item, indent in [(row, '')] + [(row.children[k], INDENT)
                                           for k in sorted(row.children)]:
            out.append((indent + item.label, str(item.files), str(item.lines),
                        _cell(item.code), _cell(item.tests)))
    return out


def render(rows: dict[str, Row]) -> list[str]:
    """Aligned columns: the label left, every count right."""
    table = _table(rows)
    widths = [max(len(r[i]) for r in table) for i in range(len(HEADER))]
    return ['  '.join([r[0].ljust(widths[0])]
                      + [cell.rjust(widths[i]) for i, cell in enumerate(r) if i])
            for r in table]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='godot-devkit stats', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dirs', nargs='*', metavar='dir',
                        help='narrow the scan to these dirs (default: the repo root)')
    parser.add_argument('--by', choices=('dir',),
                        help='dir: one row per top-level dir under `game .gd`')
    parser.add_argument('--json', action='store_true',
                        help='the same numbers as one JSON object')
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        root = repo_root()
        prefixes = scope_prefixes(root, args.dirs)
        files = scan(root, prefixes)
    except (ConfigError, Refusal, Usage) as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2
    rows = tally(root, files, settings, by_dir=args.by == 'dir')
    scanned = sum(rows[name].files for name in BUCKETS)
    dirs = list(prefixes) or [ROOT_LABEL]
    census = f'{files.census(CENSUS_LABEL)} — dirs: {" ".join(dirs)}'

    if args.json:
        buckets = []
        for name in BUCKETS:
            entry = rows[name].as_json()
            if rows[name].children:
                key = 'tiers' if name == TESTS else 'dirs'
                entry[key] = [rows[name].children[k].as_json()
                              for k in sorted(rows[name].children)]
            buckets.append(entry)
        print(json.dumps({'buckets': buckets, 'files': scanned, 'dirs': dirs,
                          'census': census}, indent=2))
    else:
        for line in render(rows):
            print(line)
        print(f'# {census}')
    return 0 if scanned else 1


if __name__ == '__main__':
    raise SystemExit(main())
