"""pot.py — `godot-devkit pot`: the localization template, without the editor.

Godot 4.7 writes a POT only from the editor (Project Settings → Localization →
POT Generation); no CLI flag and no script API reaches `TranslationTemplateGenerator`.
So a string change waits on a human, and a stale POT passes every gate. This
verb writes the same file from text:

    godot-devkit pot              # write the POT that [pot] output names
    godot-devkit pot --dry-run    # print the unified diff, write nothing
    godot-devkit pot --check      # exit 1 when the committed POT is stale

The manifest is `project.godot`'s `internationalization/locale/translations_pot_files`,
in its order. Every entry must be a `.gd` script; a `.tscn`, `.csv` or any other
entry this verb cannot parse is REFUSED (exit 2), never skipped — a POT
missing one file's strings is drift that prints PASS.

Extraction is Godot's GDScript parser plugin (`godot/index/gd_translations.py`).
The file is `editor/translations/template_generator.cpp` (4.7): the header
lists the manifest; entries are keyed by (msgctxt, msgid) in first-seen order;
each keeps its `#. TRANSLATORS:` comments and `#: path:line` references in
first-seen order; the project name is the last msgid unless
`application/config/name_localized` is set; strings are JSON-escaped and a
multi-line msgid is split after each `\\n`. A project that asks for the
editor's built-in strings (`translation_add_builtin_strings_to_pot`) is refused:
that list lives in the editor binary.

godot-devkit.toml:
    [pot]
    output = "locale/messages.pot"   # repo-relative; required — Godot stores
                                     # no POT path in project.godot

Census (rule 4): every run prints how many files it scanned and how many
msgids it wrote. An empty manifest, a manifest with no strings, a missing
`[pot] output`, a script this cannot parse and a constant the editor folds
and this cannot (a preloaded resource's property, a float formatted into a
string) are each exit 2 — a refusal, never a smaller POT.

Known gap: a constant read through a variable whose type is INFERRED
(`var labels := Labels.new()` then `tr(labels.SAVE)`) folds in the editor and
not here; a declared type (`var labels: Labels`) folds in both.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.core import apply
from godot_devkit.core.config import (
    ConfigError,
    config_section,
    repo_path_defect,
    text as config_text,
)
from godot_devkit.core.project import repo_root
from godot_devkit.core.walk import Kind, SkipReason, descendants
from godot_devkit.godot.format.gdscript_syntax import GDSyntaxError, parse
from godot_devkit.godot.format.tscn import parse_text, strip_quotes
from godot_devkit.godot.index.gd_constants import (
    RES_PREFIX,
    Project,
    Unsupported,
    read_res,
    res_to_rel,
)
from godot_devkit.godot.index.gd_translations import Extracted, extract
from godot_devkit.godot.write import render_diff

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_REFUSED = 2

TAG = 'pot'
CONFIG_SECTION = 'pot'
OUTPUT_KEY = 'output'
POT_SUFFIX = '.pot'
SCRIPT_SUFFIX = '.gd'
SCRIPT_GLOB = '*.gd'
PROJECT_GODOT = 'project.godot'

APPLICATION = 'application'
NAME_KEY = 'config/name'
NAME_LOCALIZED_KEY = 'config/name_localized'
I18N = 'internationalization'
POT_FILES_KEY = 'locale/translations_pot_files'
ADD_BUILTIN_KEY = 'locale/translation_add_builtin_strings_to_pot'
AUTOLOAD = 'autoload'
AUTOLOAD_SINGLETON_MARK = '*'
TRUE_VALUE = 'true'
EMPTY_DICTIONARY = '{}'

# project.godot string literals (VariantParser).
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"', re.DOTALL)
VARIANT_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f',
                   '"': '"', '\\': '\\', "'": "'"}
UNICODE_ESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{6})|\\(.)', re.DOTALL)
HEX_BASE = 16

# template_generator.cpp, _write_to_pot.
LF = '\n'
ESCAPED_LF = '\\n'
HEADER_TEMPLATE = (
    '# LANGUAGE translation for {name} for the following files:\n'
    '{files}'
    '#\n'
    '# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.\n'
    '#\n'
    '#, fuzzy\n'
    'msgid ""\n'
    'msgstr ""\n'
    '"Project-Id-Version: {name}\\n"\n'
    '"MIME-Version: 1.0\\n"\n'
    '"Content-Type: text/plain; charset=UTF-8\\n"\n'
    '"Content-Transfer-Encoding: 8-bit\\n"\n')
HEADER_FILE = '# {file}\n'
FIRST_COMMENT = '#. TRANSLATORS: '
NEXT_COMMENT = '#. '
REFERENCE = '#: '
# String::json_escape, in its replacement order.
JSON_ESCAPES = (('\\', '\\\\'), ('\b', '\\b'), ('\f', '\\f'), ('\n', '\\n'),
                ('\r', '\\r'), ('\t', '\\t'), ('\v', '\\v'), ('"', '\\"'))


class Refusal(Exception):
    """This run cannot produce the editor's POT. Exit 2, and say why."""


# --- project.godot ------------------------------------------------------------------

def _unescape(raw: str) -> str:
    def one(match: re.Match) -> str:
        if match.group(1) or match.group(2):
            return chr(int(match.group(1) or match.group(2), HEX_BASE))
        char = match.group(3)
        return VARIANT_ESCAPES.get(char, char)
    return UNICODE_ESCAPE_RE.sub(one, raw)


def _strings(value: str) -> list[str]:
    return [_unescape(m.group(1)) for m in QUOTED_RE.finditer(value)]


@dataclass
class Settings:
    manifest: list[str]
    project_name: str
    name_localized: bool
    add_builtin: bool
    autoloads: dict[str, str] = field(default_factory=dict)


def read_settings(project_text: str) -> Settings:
    """The project.godot facts the editor's generator reads."""
    values: dict[tuple[str, str], str] = {}
    autoloads: dict[str, str] = {}
    for section in parse_text(project_text):
        for key, value in section.props:
            values[(section.kind, key)] = value
            if section.kind == AUTOLOAD:
                path = strip_quotes(value).lstrip(AUTOLOAD_SINGLETON_MARK)
                autoloads[key] = path
    name_raw = values.get((APPLICATION, NAME_KEY), '')
    names = _strings(name_raw)
    localized = values.get((APPLICATION, NAME_LOCALIZED_KEY), EMPTY_DICTIONARY)
    return Settings(
        manifest=_strings(values.get((I18N, POT_FILES_KEY), '')),
        project_name=names[0] if names else '',
        name_localized=localized.replace(' ', '') != EMPTY_DICTIONARY,
        add_builtin=values.get((I18N, ADD_BUILTIN_KEY), '').strip() == TRUE_VALUE,
        autoloads=autoloads)


# --- the generator -------------------------------------------------------------------

@dataclass
class Message:
    plural: str = ''
    locations: dict[str, None] = field(default_factory=dict)  # ordered set
    comments: dict[str, None] = field(default_factory=dict)


def build_messages(extracted: list[tuple[str, list[Extracted]]], settings: Settings
                   ) -> dict[tuple[str, str], Message]:
    """`TranslationTemplateGenerator::parse`: one ordered map, first seen wins."""
    raw: list[tuple[str, str, str, str, str]] = []
    for res_path, entries in extracted:
        for entry in entries:
            if not entry.msgid:
                continue
            location = f'{res_path}:{entry.line}' if entry.line > 0 else res_path
            raw.append((entry.msgid, entry.msgctxt, entry.plural, entry.comment, location))
    if not settings.name_localized and settings.project_name:
        raw.append((settings.project_name, '', '', '', ''))
    messages: dict[tuple[str, str], Message] = {}
    for msgid, msgctxt, plural, comment, location in raw:
        data = messages.setdefault((msgctxt, msgid), Message())
        if data.plural and plural and data.plural != plural:
            continue  # "Skipping different plural definitions"
        data.plural = plural
        if location:
            data.locations[location] = None
        if comment:
            data.comments[comment] = None
    return messages


def json_quote(text: str) -> str:
    for old, new in JSON_ESCAPES:
        text = text.replace(old, new)
    return f'"{text}"'


def _field(name: str, value: str) -> str:
    """`_write_pot_field`: one line, or `""` and one line per `\\n` segment."""
    if not value:
        return f'{name} ""\n'
    lines = value.split(LF)
    last = lines[-1]
    count = len(lines) - 1 if not last else len(lines)
    out = [f'{name} ']
    if count > 1:
        out.append('""\n')
    out.extend(json_quote(line + LF) + LF for line in lines[:-1])
    if last:
        out.append(json_quote(last) + LF)
    return ''.join(out)


def render(messages: dict[tuple[str, str], Message], settings: Settings) -> str:
    """`_write_to_pot`, byte for byte."""
    name = settings.project_name.replace(LF, ESCAPED_LF)
    files = ''.join(HEADER_FILE.format(file=f.replace(LF, ESCAPED_LF))
                    for f in settings.manifest)
    out = [HEADER_TEMPLATE.format(name=name, files=files)]
    for (msgctxt, msgid), data in messages.items():
        out.append(LF)
        for index, comment in enumerate(data.comments):
            lead = FIRST_COMMENT if index == 0 else NEXT_COMMENT
            out.append(lead + comment.replace(LF, LF + NEXT_COMMENT) + LF)
        for location in data.locations:
            out.append(REFERENCE + res_to_rel(location).replace(LF, ESCAPED_LF) + LF)
        if msgctxt:
            out.append(f'msgctxt {json_quote(msgctxt)}\n')
        out.append(_field('msgid', msgid))
        if not data.plural:
            out.append('msgstr ""\n')
        else:
            out.append(_field('msgid_plural', data.plural))
            out.append('msgstr[0] ""\nmsgstr[1] ""\n')
    return ''.join(out)


def _script_paths(root: Path) -> list[str]:
    """Every `res://…gd` outside a dot-directory: the `class_name` universe."""
    walk = descendants(root, Kind.FILE, SCRIPT_SUFFIX, pattern=SCRIPT_GLOB).filter(
        lambda p: not any(part.startswith('.') for part in p.relative_to(root).parts),
        SkipReason.DOTTED_NAME)
    return [RES_PREFIX + p.relative_to(root).as_posix() for p in walk]


@dataclass
class Generated:
    text: str
    files: int
    msgids: int
    keys: list[tuple[str, str]]


def generate(root: Path) -> Generated:
    """The POT the editor would write for the project at `root`, or Refusal."""
    try:
        project_text = (root / PROJECT_GODOT).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as err:
        raise Refusal(f'cannot read {PROJECT_GODOT} at {root} ({err})') from err
    settings = read_settings(project_text)
    if not settings.manifest:
        raise Refusal(f'{PROJECT_GODOT} lists no files under [{I18N}] {POT_FILES_KEY} '
                      f'— an empty manifest scans nothing')
    if settings.add_builtin:
        raise Refusal(f'[{I18N}] {ADD_BUILTIN_KEY} is true — the editor\'s built-in '
                      f'strings live in the editor binary, which this tool never boots')
    unsupported = [p for p in settings.manifest if not p.endswith(SCRIPT_SUFFIX)]
    if unsupported:
        raise Refusal(f'the manifest names {len(unsupported)} file(s) this verb cannot '
                      f'parse (only .gd): {", ".join(unsupported)}')
    read = read_res(root)
    project = Project(read, lambda: _script_paths(root), settings.autoloads)
    extracted: list[tuple[str, list[Extracted]]] = []
    for res_path in settings.manifest:
        text = read(res_path)
        if text is None:
            raise Refusal(f'the manifest names {res_path}, which cannot be read')
        try:
            script = parse(text)
            extracted.append((res_path, extract(project, res_path, script)))
        except GDSyntaxError as err:
            raise Refusal(f'{res_to_rel(res_path)}:{err.line}: cannot parse it '
                          f'({err.message})') from err
        except Unsupported as err:
            raise Refusal(f'{res_to_rel(err.where)}: {err.reason} — the editor folds '
                          f'this constant and godot-devkit cannot') from err
    messages = build_messages(extracted, settings)
    if not messages:
        raise Refusal('no translatable strings found (the editor writes no file)')
    return Generated(render(messages, settings), len(settings.manifest),
                     len(messages), list(messages))


# --- the verb --------------------------------------------------------------------------

def output_path() -> str:
    sect = config_section(CONFIG_SECTION)
    rel = config_text(sect, CONFIG_SECTION, OUTPUT_KEY, '')
    if not rel:
        raise ConfigError(f'[{CONFIG_SECTION}] {OUTPUT_KEY} is not set — name the '
                          f'repo-relative POT path; Godot stores none in {PROJECT_GODOT}')
    why = repo_path_defect(rel)
    if why:
        raise ConfigError(f'[{CONFIG_SECTION}] {OUTPUT_KEY} {rel!r} {why}')
    if not rel.endswith(POT_SUFFIX):
        raise ConfigError(f'[{CONFIG_SECTION}] {OUTPUT_KEY} {rel!r} must end in {POT_SUFFIX}')
    return rel


def _msgid_label(key: tuple[str, str]) -> str:
    msgctxt, msgid = key
    shown = json_quote(msgid)
    return f'{shown} (msgctxt {json_quote(msgctxt)})' if msgctxt else shown


def _committed_keys(text: str) -> list[tuple[str, str]]:
    """(msgctxt, msgid) of every entry in a POT, the header excluded."""
    keys: list[tuple[str, str]] = []
    context = ''
    lines = text.split(LF)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith('msgctxt '):
            context = _po_string(lines, index, 'msgctxt ')
        elif line.startswith('msgid '):
            msgid = _po_string(lines, index, 'msgid ')
            if msgid:
                keys.append((context, msgid))
            context = ''
        index += 1
    return keys


def _po_string(lines: list[str], index: int, keyword: str) -> str:
    parts = [lines[index][len(keyword):]]
    follow = index + 1
    while follow < len(lines) and lines[follow].startswith('"'):
        parts.append(lines[follow])
        follow += 1
    return ''.join(_unescape(p.strip()[1:-1]) for p in parts if p.strip())


def _check(rel: str, current: str | None, fresh: Generated) -> int:
    census = f'{fresh.files} file(s) scanned, {fresh.msgids} msgid(s)'
    if current == fresh.text:
        print(f'[{TAG}] PASS — {rel} matches the manifest: {census}')
        return EXIT_OK
    if current is None:
        print(f'  MISSING  {rel} does not exist')
        print(f'[{TAG}] FAIL — {rel} is missing ({census}); run: godot-devkit pot')
        return EXIT_DRIFT
    committed = set(_committed_keys(current))
    wanted = set(fresh.keys)
    missing = [k for k in fresh.keys if k not in committed]
    extra = [k for k in _committed_keys(current) if k not in wanted]
    for key in missing:
        print(f'  MISSING  {_msgid_label(key)}')
    for key in extra:
        print(f'  EXTRA  {_msgid_label(key)}')
    if not missing and not extra:
        old, new = current.split(LF), fresh.text.split(LF)
        line = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b),
                    min(len(old), len(new)))
        print(f'  DRIFT  {rel}:{line + 1}: same msgids, different references, '
              f'comments or order')
    print(f'[{TAG}] FAIL — {rel} is stale: {len(missing)} missing, {len(extra)} extra '
          f'msgid(s); {census}; run: godot-devkit pot')
    return EXIT_DRIFT


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='godot-devkit pot', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true',
                      help='exit 1 when the committed POT differs from a fresh one')
    mode.add_argument('--dry-run', action='store_true',
                      help='print the unified diff instead of writing')
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    root = repo_root()
    try:
        rel = output_path()
    except ConfigError as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return EXIT_REFUSED
    try:
        fresh = generate(root)
    except Refusal as err:
        print(f'REFUSED  {TAG}: {err}', file=sys.stderr)
        return EXIT_REFUSED
    target = root / rel
    try:
        current: str | None = target.read_bytes().decode('utf-8')
    except FileNotFoundError:
        current = None
    except (OSError, UnicodeDecodeError) as err:
        print(f'REFUSED  {TAG}: cannot read {rel} ({err})', file=sys.stderr)
        return EXIT_REFUSED
    if args.check:
        return _check(rel, current, fresh)
    census = f'{fresh.files} file(s) scanned, {fresh.msgids} msgid(s)'
    if current == fresh.text:
        print(f'{TAG}  {rel}  {census}  (unchanged)')
        return EXIT_OK
    if args.dry_run:
        print(render_diff(current or '', fresh.text, rel), end='')
        print(f'{TAG}  {rel}  {census}  (dry run)')
        return EXIT_OK
    applied = apply.write(target, fresh.text)
    if applied.failed is not None:
        print(f'REFUSED  {TAG}: cannot write {rel} ({applied.error})', file=sys.stderr)
        return EXIT_REFUSED
    print(f'{TAG}  {rel}  {census}  written')
    return EXIT_OK
