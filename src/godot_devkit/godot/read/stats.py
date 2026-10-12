#!/usr/bin/env python3
"""stats.py — how much code is in this project, and where.

One row per bucket — `.gd` split by role (game, tests, tools, vendored), then
`.gdshader`, `.tscn` and `.tres` — each with its file, line and code-line
count, and a final census line naming the files scanned and the dirs. Only
git-known files are counted (tracked + untracked-but-not-ignored, the set
`orphans` scans), so `.godot/` and every other ignored artifact stays out.
Pure parse — never writes, never boots Godot.

    godot-devkit stats [<dir>...] [--by dir] [--json] [--ratchet FILE]

Comment metrics use the shared GDScript lexer. `comments` counts own-line # comments
and standalone docstrings; `docs` counts the ## subset. Inline comment and docstring
counts are separately frozen to prevent moving prose to evade a budget.

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

godot-devkit.toml: [stats] tests    = ["tests/"]
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
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.godot.format.gdscript_syntax import tokenize, STRING, NAME, EOF, GDSyntaxError
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
HEADER = ('bucket', 'files', 'lines', 'code', 'comments', 'docs', 'inline', 'docstrings', 'tests')
COMMENT_METRICS = ('comments', 'docs', 'inline', 'docstrings')
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
    comments: int | None = 0
    docs: int | None = 0
    inline: int | None = 0
    docstrings: int | None = 0
    children: dict[str, 'Row'] = field(default_factory=dict)

    def add(self, lines: int, code: int | None, tests: int | None,
            comments: int | None = None, docs: int | None = None,
            inline: int | None = None, docstrings: int | None = None) -> None:
        for metric, value in zip(COMMENT_METRICS, (comments, docs, inline, docstrings)):
            if getattr(self, metric) is not None and value is not None:
                setattr(self, metric, getattr(self, metric) + value)
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
        out.update({key: getattr(self, key) for key in COMMENT_METRICS})
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


def gd_line_counts(text: str) -> tuple[int, int, int, int, int, int, int]:
    """Physical/code/test/comment/doc/inline/docstring counts from the shared lexer."""
    lines = text.splitlines()
    tokens, comments = tokenize(text)
    own = {n for n, comment in comments.items() if comment.own_line}
    docs = {n for n in own if comments[n].text.startswith('##')}
    inline = len(comments) - len(own)
    code_lines, docstrings = set(), set()
    tests = 0
    for index, token in enumerate(tokens):
        if token.kind == EOF:
            continue
        extent = range(token.line, (token.end_line or token.line) + 1)
        source = lines[token.line - 1].lstrip()
        if token.kind == STRING and token.bol and any(source.startswith(prefix + quote * 3) for prefix in ('', 'r', '&', '^') for quote in ('"', chr(39))):
            docstrings.update(extent)
        else:
            code_lines.update(n for n in extent if n <= len(lines) and lines[n - 1].strip())
        if token.kind == NAME and token.text == 'func' and index + 1 < len(tokens):
            following = tokens[index + 1]
            if following.kind == NAME and following.text.startswith('test_'):
                tests += 1
    own.update(docstrings)
    return len(lines), len(code_lines - own), tests, len(own), len(docs), inline, len(docstrings)


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
                      tests=0 if name == TESTS else None,
                      **{key: 0 if name in (GAME, TESTS, TOOLS, VENDORED) else None
                         for key in COMMENT_METRICS})
            for name in BUCKETS}
    for path in files:
        rel = path.as_posix()
        text = (root / path).read_text(encoding='utf-8', errors='replace')
        suffix = path.suffix.lower()
        if suffix == GD:
            lines, code, tests, comments, docs, inline, docstrings = gd_line_counts(text)
            name = gd_bucket(rel, settings)
            rows[name].add(lines, code, tests, comments, docs, inline, docstrings)
            if name == TESTS:
                prefix = _under(rel, settings.tests)
                rows[TESTS].child(_subdir_label(rel, prefix)).add(lines, code, tests, comments, docs, inline, docstrings)
            elif name == GAME and by_dir:
                label = rel.split('/', 1)[0] + '/' if '/' in rel else ROOT_LABEL
                rows[GAME].child(label).add(lines, code, None, comments, docs, inline, docstrings)
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
                        _cell(item.code), *(_cell(getattr(item, key)) for key in COMMENT_METRICS),
                        _cell(item.tests)))
    return out


def render(rows: dict[str, Row]) -> list[str]:
    """Aligned columns: the label left, every count right."""
    table = _table(rows)
    widths = [max(len(r[i]) for r in table) for i in range(len(HEADER))]
    return ['  '.join([r[0].ljust(widths[0])]
                      + [cell.rjust(widths[i]) for i, cell in enumerate(r) if i])
            for r in table]


def _baseline(document: dict) -> tuple[dict, list[str], dict[str, dict]]:
    if not isinstance(document, dict) or not isinstance(document.get('settings'), dict):
        raise ValueError('baseline must be stats --json output with settings')
    dirs = document.get('dirs')
    if not isinstance(dirs, list) or not dirs or not all(isinstance(d, str) for d in dirs):
        raise ValueError('baseline dirs must be a nonempty list of strings')
    buckets = document.get('buckets')
    if not isinstance(buckets, list) or len(buckets) != len(BUCKETS):
        raise ValueError('baseline must contain every stats bucket')
    entries = {}
    for bucket in buckets:
        if not isinstance(bucket, dict) or bucket.get('bucket') not in BUCKETS:
            raise ValueError('unknown baseline bucket')
        for entry in [bucket, *bucket.get('tiers', []), *bucket.get('dirs', [])]:
            key = entry.get('bucket')
            if not isinstance(key, str) or key in entries:
                raise ValueError('duplicate or malformed baseline bucket')
            for metric in (*COMMENT_METRICS, 'code', 'tests'):
                value = entry.get(metric)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f'{key} {metric} must be a nonnegative integer or null')
            if bucket['bucket'] in (GAME, TESTS, TOOLS, VENDORED):
                if any(type(entry.get(metric)) is not int for metric in COMMENT_METRICS):
                    raise ValueError(f'{key} is missing comment metrics')
            entries[key] = entry
    if not all(name in entries for name in BUCKETS):
        raise ValueError('baseline repeats or omits a stats bucket')
    return document['settings'], dirs, entries


def _limits(entry: dict, test_keys: set[str]) -> tuple[str, ...]:
    return COMMENT_METRICS + (('code', 'tests') if entry['bucket'] in test_keys else ())


def ratchet(root: Path, path: Path, rows: dict[str, Row], settings: Settings,
            dirs: list[str]) -> list[str]:
    path = path.resolve()
    rel = path.relative_to(root.resolve()).as_posix()
    config, baseline_dirs, caps = _baseline(json.loads(path.read_text()))
    current_config = {key: list(value) for key, value in settings.__dict__.items()}
    findings = []
    if config != current_config or baseline_dirs != dirs:
        findings.append('scope/settings changed; restore the frozen roots before comparing budgets')
    test_keys = {TESTS, *rows[TESTS].children}
    # A scope change cannot silently move a tier out of its specific cap.
    current = {row.label: row.as_json() for parent in rows.values()
               for row in (parent, *parent.children.values())}
    if not set(current).issubset(caps):
        findings.append('new bucket/tier lacks a frozen budget')
    for key, entry in current.items():
        if key not in caps:
            continue
        for metric in _limits(entry, test_keys):
            value, cap = entry.get(metric), caps[key].get(metric)
            if value is not None and (cap is None or value > cap):
                findings.append(f'{key} {metric}: {value} exceeds {cap}')
    # New baselines may be introduced once. Existing scope and limits only shrink.
    base = 'origin/main'
    exists = subprocess.run(['git', 'cat-file', '-e', base + '^{commit}'], cwd=root,
                            capture_output=True).returncode == 0
    if not exists:
        base = 'HEAD'
    previous = subprocess.run(['git', 'show', f'{base}:{rel}'], cwd=root,
                              capture_output=True, text=True)
    if previous.returncode == 0:
        old_config, old_dirs, old_caps = _baseline(json.loads(previous.stdout))
        if config != old_config or baseline_dirs != old_dirs or set(caps) != set(old_caps):
            findings.append('baseline scope/buckets changed from the Git base')
        for key, entry in caps.items():
            if key not in old_caps:
                continue
            # All tier code counts are test-code caps; production code is context only.
            keys = {TESTS, *[k for k in caps if _under(k, settings.tests) is not None]}
            for metric in _limits(entry, keys):
                cap, old = entry.get(metric), old_caps[key].get(metric)
                if old is not None and (cap is None or cap > old):
                    findings.append(f'{key} {metric}: baseline cap increased from {old} to {cap}')
    return findings


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
    parser.add_argument('--ratchet', type=Path, metavar='FILE',
                        help='fail on comment/doc/test-code growth against a stats JSON baseline')
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        root = repo_root()
        prefixes = scope_prefixes(root, args.dirs)
        files = scan(root, prefixes)
    except (ConfigError, Refusal, Usage, GDSyntaxError) as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2
    try:
        rows = tally(root, files, settings, by_dir=args.by == 'dir')
    except GDSyntaxError as err:
        print(f'godot-devkit: stats: {err}', file=sys.stderr)
        return 2
    scanned = sum(rows[name].files for name in BUCKETS)
    dirs = list(prefixes) or [ROOT_LABEL]
    census = f'{files.census(CENSUS_LABEL)} — dirs: {" ".join(dirs)}'

    buckets = []
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
                          'census': census, 'settings': settings.__dict__}, indent=2))
    else:
        for line in render(rows):
            print(line)
        print(f'# {census}')
    if not scanned:
        return 1
    if args.ratchet:
        try:
            findings = ratchet(root, args.ratchet, rows, settings, dirs)
        except (ValueError, OSError, json.JSONDecodeError) as err:
            print(f'godot-devkit: stats: invalid ratchet: {err}', file=sys.stderr)
            return 2
        for finding in findings:
            print(f'[stats:ratchet] {finding}', file=sys.stderr)
        return 1 if findings else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
