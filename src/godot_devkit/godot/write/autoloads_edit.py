"""autoloads_edit.py — declare or remove one autoload in project.godot, in place.

    godot-devkit autoloads add <Name> <res://path> [--dry-run]
    godot-devkit autoloads rm  <Name>              [--dry-run]

The write half of the `autoloads` census, under the same noun the way `scene`
and `tiles` carry theirs. `add` writes `Name="*res://path"` — the `*` is an
enabled singleton, what the editor's Autoload tab writes — as the last entry of
`[autoload]`, creating the section at the end of the file when there is none.
`rm` deletes that one entry, and the section with it only when nothing but
blank lines would be left. Every other byte of `project.godot` is carried
through verbatim, its own line endings included.

Refusals (exit 1, nothing written, the reason named): a name that is not an
identifier, or that the editor refuses because it is an engine class or a
project script's `class_name` — a script the editor sees, so not one under a
dot-prefixed directory or a directory holding `.gdignore`, and `addons/`
included; a path that is not `res://`, escapes the project,
is not in its canonical spelling (`//`, `/./`, `/../`, a trailing `/` — the
refusal names the canonical one), differs from the file's on-disk spelling only
by case (a case-insensitive filesystem finds it, a case-sensitive export does
not — the refusal names the on-disk one), or names no file on disk; a name already
declared with a DIFFERENT path (the line names it), or with the same path but
DISABLED (no `*`, so no singleton exists to be `unchanged`); a name or an
`[autoload]` section declared more than once. The same `add` twice
is a no-op that says `unchanged`, and so is `rm` of a name nobody declares —
exit 0, because models retry. A `project.godot` that is missing or is not
UTF-8 is exit 2: there is no project here to edit.
"""
from __future__ import annotations

import argparse
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath

from godot_devkit.core import apply, walk
from godot_devkit.core.project import repo_root
from godot_devkit.godot.format import classdb
from godot_devkit.godot.format.tscn import parse_lines, strip_quotes
from godot_devkit.godot.format.tscn_document import read_scene_text
from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.godot.read.autoloads import PROJECT_GODOT
from godot_devkit.godot.write import file_exists, render_diff, utf8_refusal_reason

VERBS = ('add', 'rm')
ADD, RM = VERBS
SECTION_KIND = 'autoload'
HEADER = f'[{SECTION_KIND}]'
RES_PREFIX = 'res://'
ENABLED = '*'
GD_SUFFIX = '.gd'
HIDDEN = '.'
GDIGNORE = '.gdignore'
PARENT = '..'
# ASCII on purpose: a narrower rule than the editor's never writes a name the
# editor would refuse, and the refusal says what was expected.
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
# Bytes that cannot sit unescaped inside the quoted value this verb writes.
UNQUOTABLE = ('"', '\\', '\n', '\r')
UNCHANGED = 'unchanged'
CR = '\r'
LF = '\n'
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


class Refused(Exception):
    """The edit cannot be made correctly — say why, write nothing, exit 1."""


def _entry(name: str, res_path: str) -> str:
    return f'{name}="{ENABLED}{res_path}"'


def _declared_path(value: str) -> str:
    """`"*res://x.gd"` -> `res://x.gd`; the same reading the census makes."""
    return strip_quotes(value).lstrip(ENABLED)


def _editor_sees(root: Path, path: Path) -> bool:
    """Godot's own scan rule: a directory whose name starts with `.` (`.git/`,
    `.godot/`, a `.claude/` worktree) or that holds a `.gdignore` hides
    everything below it. Nothing else does — an addon's class_name is one the
    editor knows."""
    folder = root
    for part in path.relative_to(root).parts[:-1]:
        folder = folder / part
        if part.startswith(HIDDEN) or file_exists(folder / GDIGNORE):
            return False
    return True


def _check_name(root: Path, name: str) -> None:
    """The editor's refusals, as far as this package can know them: an
    identifier, and not a name a script already resolves to something else."""
    if not IDENTIFIER.match(name):
        raise Refused(f'{name!r} is not a valid autoload name '
                      f'(expected an identifier: [A-Za-z_][A-Za-z0-9_]*)')
    if classdb.is_known(name):
        raise Refused(f'{name} is an engine class — the editor refuses an '
                      f'autoload that shadows it; pick another name')
    scripts = walk.descendants(root, walk.Kind.FILE, suffix=GD_SUFFIX,
                               pattern=f'*{GD_SUFFIX}').filter(
        lambda path: _editor_sees(root, path), walk.SkipReason.EXCLUDED_PATH)
    index = ScriptIndex(root, [path.relative_to(root).as_posix() for path in scripts])
    owner = index.by_class.get(name)
    if owner is not None:
        raise Refused(f'{name} is the class_name of {owner} — the editor refuses '
                      f'an autoload that shadows it; pick another name')


def _case_mismatch(root: Path, rel: str) -> str | None:
    """The on-disk spelling of `rel` when one differs from it only by case.

    Read off the tree's own listing, never `stat`: a case-insensitive
    filesystem answers `stat` for any spelling, so the listing is the only
    place the real one is written down. An exact match wins — a case-sensitive
    tree may hold both spellings."""
    want = rel.casefold()
    other = None
    for path in walk.descendants(root):
        found = path.relative_to(root).as_posix()
        if found == rel:
            return None
        if other is None and found.casefold() == want:
            other = found
    return other


def _check_path(root: Path, res_path: str) -> None:
    if not res_path.startswith(RES_PREFIX):
        raise Refused(f'{res_path!r} is not a {RES_PREFIX} path')
    rel = res_path[len(RES_PREFIX):]
    canonical = posixpath.normpath(rel) if rel else rel
    if (not rel or rel.startswith('/')
            or PurePosixPath(canonical).parts[:1] == (PARENT,)):
        raise Refused(f'{res_path} does not name a file inside the project')
    if canonical != rel:
        # Normalising silently would write a spelling the user did not type;
        # leaving it would make one file two autoload paths.
        raise Refused(f'{res_path} is not the canonical spelling — '
                      f'write {RES_PREFIX}{canonical}')
    if any(char in res_path for char in UNQUOTABLE):
        raise Refused(f'{res_path!r} holds a character this verb cannot '
                      f'write unescaped (one of {" ".join(map(repr, UNQUOTABLE))})')
    # Before the existence check, so a case-sensitive filesystem names the
    # on-disk spelling too, rather than calling the file missing.
    spelled = _case_mismatch(root, rel)
    if spelled is not None:
        raise Refused(f'{res_path} is spelled {RES_PREFIX}{spelled} on disk — '
                      f'a case-sensitive export would not find it; '
                      f'write {RES_PREFIX}{spelled}')
    if not file_exists(root / rel):
        raise Refused(f'{res_path} does not exist on disk ({root / rel})')


def _autoload_section(parts: list[str]):
    """The one `[autoload]` section, None when absent; two is a refusal."""
    sections = parse_lines(parts)
    found = [s for s in sections if s.kind == SECTION_KIND]
    if len(found) > 1:
        raise Refused(f'{HEADER} is declared {len(found)} times — '
                      f'refusing to pick one')
    if not found:
        return None, sections
    return found[0], sections


def _the_entry(section, name: str):
    """The one entry declaring `name`, None when undeclared; two is a refusal."""
    matches = [e for e in section.entries if e.key == name]
    if len(matches) > 1:
        raise Refused(f'{name} is declared {len(matches)} times in {HEADER} — '
                      f'refusing to pick one')
    return matches[0] if matches else None


def plan_add(text: str, name: str, res_path: str) -> tuple[str, str]:
    """(new text, note). The text is unchanged when the entry already exists."""
    crlf = CR + LF in text
    cr = CR if crlf else ''
    parts = text.split(LF)
    section, _ = _autoload_section(parts)
    entry = _entry(name, res_path)
    if section is None:
        # Godot's own layout: a blank line between sections, one after the
        # header. Always the separator, so `rm` removing exactly one restores
        # the file whatever its tail looked like.
        eol = cr + LF
        lead = eol if text and not text.endswith(LF) else ''
        block = [HEADER, '', entry]
        if text:
            block.insert(0, '')
        added = ''.join(line + eol for line in block)
        # A file with no final newline keeps having none, so `rm` restores it.
        if lead:
            added = added[:-len(eol)]
        return text + lead + added, f'new {HEADER} section'
    existing = _the_entry(section, name)
    if existing is not None:
        declared = _declared_path(existing.value)
        if declared == res_path:
            if not strip_quotes(existing.value).startswith(ENABLED):
                raise Refused(f'{name} is declared but disabled (no `{ENABLED}`) — '
                              f'`autoloads rm {name}` then add to enable it')
            return text, f'{UNCHANGED}  (already declared: {declared})'
        raise Refused(f'{name} is already declared with {declared} — '
                      f'`autoloads rm {name}` first to point it elsewhere')
    parts.insert(section.body_end, entry + cr)
    return LF.join(parts), ''


def plan_rm(text: str, name: str) -> tuple[str, str]:
    """(new text, note). The text is unchanged when nothing declares `name`."""
    parts = text.split(LF)
    section, sections = _autoload_section(parts)
    existing = _the_entry(section, name) if section is not None else None
    if existing is None:
        return text, f'{UNCHANGED}  (not declared)'
    following = [s.header_line for s in sections if s.header_line > section.header_line]
    at_eof = not following
    # The phantom '' after a final newline is not a line: keep it, so the file
    # keeps its last newline.
    end = following[0] if following else len(parts) - (1 if text.endswith(LF) else 0)
    rest = [line for index, line in enumerate(parts[section.header_line + 1:end],
                                               start=section.header_line + 1)
            if not existing.start <= index < existing.end]
    if any(line.strip() for line in rest):
        del parts[existing.start:existing.end]
        return LF.join(parts), ''
    start = section.header_line
    # A section at the end of the file takes its one separator line with it —
    # the inverse of `add` creating it; mid-file, that line separates the
    # section before from the one after and stays.
    if at_eof and start > 0 and not parts[start - 1].strip():
        start -= 1
    del parts[start:end]
    return LF.join(parts), f'{HEADER} section removed (it held only {name})'


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='godot-devkit autoloads', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest='verb', required=True)
    for verb in VERBS:
        sub = subs.add_parser(verb)
        sub.add_argument('name', help='the autoload (singleton) name')
        if verb == ADD:
            sub.add_argument('path', help='the script or scene, as res://...')
        sub.add_argument('--dry-run', action='store_true',
                         help='print the unified diff instead of writing')
    return parser


def _read(path: Path, verb: str) -> str | None:
    """The file's text, endings intact — or None with the exit-2 line printed."""
    try:
        return read_scene_text(path)
    except UnicodeDecodeError as err:
        reason = utf8_refusal_reason(err)
    except OSError as err:
        reason = (f'cannot read it — run from inside a Godot repo '
                  f'({err.strerror or err})')
    print(f'godot-devkit autoloads {verb}: {path}: {reason}', file=sys.stderr)
    return None


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    root = repo_root()
    path = root / PROJECT_GODOT
    before = _read(path, args.verb)
    if before is None:
        return EXIT_USAGE
    try:
        if args.verb == ADD:
            _check_name(root, args.name)
            _check_path(root, args.path)
            after, note = plan_add(before, args.name, args.path)
        else:
            after, note = plan_rm(before, args.name)
    except Refused as err:
        print(f'REFUSED  {PROJECT_GODOT}: {err}')
        return EXIT_REFUSED

    label = f'{args.verb}  {PROJECT_GODOT}  {args.name}'
    if after == before:
        print(f'{label}  {note}')
        return EXIT_OK
    if args.dry_run:
        print(render_diff(before, after, PROJECT_GODOT), end='')
    else:
        try:
            apply.raise_on_error(apply.write(path, after))
        except OSError as err:
            print(f'REFUSED  {PROJECT_GODOT}: cannot write it ({err})')
            return EXIT_REFUSED
    shown = _entry(args.name, args.path) if args.verb == ADD else args.name
    tail = ''.join(f'  ({part})' for part in (note, 'dry run' if args.dry_run else '')
                   if part)
    print(f'{args.verb}  {PROJECT_GODOT}  {shown}{tail}')
    return EXIT_OK
