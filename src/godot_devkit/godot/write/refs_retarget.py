"""refs_retarget.py — re-point every reference to a moved res:// path.

    godot-devkit refs --retarget <old-res-path> <new-res-path> [--dry-run]

After a `git mv old.gd new.gd` (or .tscn/.tres), every `path="res://old"`
ext_resource ref in the tree strands: Godot falls back to the uid, warns on
every cold import, and rewrites the path on the next editor save of each
file — the whole tree diffs, one file at a time, forever. This does the
rewrite in one pass, byte-surgically: only the reference text changes, every
other byte (the uid attr, its text spelling, line endings, neighbours) is
carried through verbatim.

What it rewrites:
  * every `[ext_resource ...]` line whose `path="..."` attr IS the old path,
    in every .tscn/.tres;
  * every `preload("res://old")` / `load("res://old")` literal in a .gd whose
    quoted string IS exactly the old path.

What it reports instead of rewriting — a SKIPPED line with the reason, never
a guess (the census counts them, and any skip exits 1 so a stranded ref is
loud): an occurrence inside a comment, an exact quoted match outside a
preload/load call, an occurrence that is a substring of a longer string, and
a quoted path in a scene file outside an ext_resource path attr.

REFUSES when the NEW path does not exist on disk — retargeting refs onto
nothing is minting drift. The OLD file being gone is fine; it moved, that is
the point. `--dry-run` lists every file+line and writes nothing. tests/ are
scanned (a repair that strands the tests' refs is half a repair); the
`[refs] exclude_prefixes` scope from devkit.toml applies, same as `refs`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from godot_devkit.core import apply, walk
from godot_devkit.core.config import ConfigError
from godot_devkit.core.project import repo_root
from godot_devkit.core.walk import Kind, SkipReason
from godot_devkit.godot.format.tscn import COMMENT_CHAR, EXT_RESOURCE_KIND, scan_line
from godot_devkit.godot.format.tscn_document import LINE_ENDING, read_scene_text
from godot_devkit.godot.write import utf8_refusal_reason
from godot_devkit.godot.index.uid_index import RES_PREFIX
from godot_devkit.godot.read.refs import exclude_prefixes

EXIT_OK = 0
EXIT_FINDINGS = 1
SCENE_GLOBS = ('*.tscn', '*.tres')
GD_GLOB = '*.gd'
GD_COMMENT_CHAR = '#'
EXT_RESOURCE_OPEN = f'[{EXT_RESOURCE_KIND} '
QUOTE = '"'
CENSUS = '[refs:retarget] {files} file(s) scanned, {rewritten} rewritten, {skipped} skipped'

SKIP_COMMENT = 'inside a comment — not a reference'
SKIP_NOT_CALL = 'an exact quoted path outside a preload/load call — verify by hand'
SKIP_SUBSTRING = 'a substring of a longer string — not this resource'
SKIP_SCENE_PROP = ('a quoted path outside an ext_resource path attr — '
                   'verify by hand')


class _Line:
    """One line's rewrite: occurrences classified BEFORE any text moves, so a
    new path that contains the old one cannot confuse the census."""

    def __init__(self, content: str, comment_char: str,
                 comment_in_brackets: bool) -> None:
        self.content = content
        _, _, _, cut = scan_line(content, comment_char=comment_char,
                                 comment_in_brackets=comment_in_brackets)
        self.comment_at = cut if cut >= 0 else len(content)

    def occurrences(self, needle: str) -> list[int]:
        found, at = [], self.content.find(needle)
        while at >= 0:
            found.append(at)
            at = self.content.find(needle, at + 1)
        return found

    def is_quoted_exactly(self, at: int, needle: str) -> bool:
        end = at + len(needle)
        return (at > 0 and self.content[at - 1] == QUOTE
                and end < len(self.content) and self.content[end] == QUOTE)

    def rewrite(self, spans: list[tuple[int, int]], new: str) -> str:
        text = self.content
        for start, end in sorted(spans, reverse=True):
            text = text[:start] + new + text[end:]
        return text


def _path_attr_span(line: _Line, at: int, old: str) -> bool:
    prefix = f'path={QUOTE}'
    return (line.content.lstrip().startswith(EXT_RESOURCE_OPEN)
            and line.content[max(at - len(prefix), 0):at] == prefix
            and line.is_quoted_exactly(at, old))


def _call_spans(line: _Line, old: str) -> list[tuple[int, int]]:
    pattern = re.compile(r'\b(?:preload|load)\(\s*"' + re.escape(old) + r'"\s*\)')
    return [(m.start() + m.group(0).index(QUOTE) + 1,
             m.start() + m.group(0).index(QUOTE) + 1 + len(old))
            for m in pattern.finditer(line.content) if m.start() < line.comment_at]


def _classify(line: _Line, old: str, is_scene: bool) -> tuple[list[tuple[int, int]], list[str]]:
    """(spans to rewrite, skip reasons) for one line's occurrences of `old`."""
    spans = (
        [(at, at + len(old)) for at in line.occurrences(old)
         if at < line.comment_at and _path_attr_span(line, at, old)]
        if is_scene else _call_spans(line, old))
    starts = {span[0] for span in spans}
    skips = []
    for at in line.occurrences(old):
        if at in starts:
            continue
        if at >= line.comment_at:
            skips.append(SKIP_COMMENT)
        elif not line.is_quoted_exactly(at, old):
            skips.append(SKIP_SUBSTRING)
        else:
            skips.append(SKIP_SCENE_PROP if is_scene else SKIP_NOT_CALL)
    return spans, skips


def _scan_files(root: Path) -> list[Path]:
    exclude = exclude_prefixes()

    def kept(glob: str) -> list[Path]:
        found = walk.descendants(root, Kind.ANY, pattern=glob).filter(
            lambda p: not any(str(p.relative_to(root)).startswith(prefix)
                              for prefix in exclude),
            SkipReason.EXCLUDED_PATH)
        return list(found.kept)

    files: list[Path] = []
    for glob in (*SCENE_GLOBS, GD_GLOB):
        files.extend(kept(glob))
    return sorted(files)


def _retarget_file(path: Path, rel: str, old: str, new: str,
                   dry_run: bool) -> tuple[int, int, list[str]]:
    """(rewritten, skipped, report lines) for one file; writes unless dry."""
    is_scene = path.suffix != '.gd'
    comment_char = COMMENT_CHAR if is_scene else GD_COMMENT_CHAR
    try:
        text = read_scene_text(path)
    except UnicodeDecodeError as err:
        # The SKIPPED variant: a sweep steps over the file and keeps going,
        # where a single-file verb refuses — the sentence itself is shared.
        return 0, 1, [f'  SKIPPED  {rel}  {utf8_refusal_reason(err)}']
    except OSError as err:
        # Same contract for an unreadable file (permissions, vanished mid-
        # sweep): step over loudly. A traceback here would strand a partial
        # multi-file rewrite with no census.
        return 0, 1, [f'  SKIPPED  {rel}  unreadable ({err.strerror or err})']
    if old not in text:
        return 0, 0, []
    parts = LINE_ENDING.split(text)
    contents, endings = parts[::2], parts[1::2] + ['']
    rewritten, skipped, report = 0, 0, []
    for index, content in enumerate(contents):
        if old not in content:
            continue
        line = _Line(content, comment_char, comment_in_brackets=not is_scene)
        spans, skips = _classify(line, old, is_scene)
        if spans:
            contents[index] = line.rewrite(spans, new)
            rewritten += len(spans)
            report.append(f'  REWRITE  {rel}:{index + 1}  {contents[index].strip()}')
        for reason in skips:
            skipped += 1
            report.append(f'  SKIPPED  {rel}:{index + 1}  {reason}')
    if rewritten and not dry_run:
        apply.raise_on_error(apply.write(
            path, ''.join(c + e for c, e in zip(contents, endings))))
    return rewritten, skipped, report


def run(old: str, new: str, dry_run: bool) -> int:
    root = repo_root()
    if not (root / new[len(RES_PREFIX):]).is_file():
        print(f'REFUSED  {new} does not exist on disk — retargeting '
              f'references onto nothing is minting drift')
        return EXIT_FINDINGS
    print(f'retarget  {old} -> {new}'
          + ('  (dry run — nothing written)' if dry_run else ''))
    files = _scan_files(root)
    rewritten = skipped = 0
    for path in files:
        wrote, skips, report = _retarget_file(
            path, str(path.relative_to(root)), old, new, dry_run)
        rewritten += wrote
        skipped += skips
        for line in report:
            print(line)
    print(CENSUS.format(files=len(files), rewritten=rewritten, skipped=skipped))
    return EXIT_FINDINGS if skipped else EXIT_OK


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog='godot-devkit refs', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--retarget', nargs=2, metavar=('OLD', 'NEW'),
                        required=True, help='res:// paths: every reference to '
                                            'OLD is rewritten to NEW')
    parser.add_argument('--dry-run', action='store_true',
                        help='list every file+line, write nothing')
    args = parser.parse_args(argv)
    old, new = args.retarget
    for res_path in (old, new):
        if not res_path.startswith(RES_PREFIX):
            parser.error(f'{res_path!r} is not a {RES_PREFIX} path')
    if old == new:
        parser.error(f'old and new are the same path ({old}) — nothing to retarget')
    try:
        return run(old, new, args.dry_run)
    except ConfigError as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
