"""refs_rename.py — rename a class_name, method, signal or autoload, everywhere or nowhere.

    godot-devkit refs --rename <old> <new> [--dry-run]

The hit set is `refs <old>`'s — definitions, typed refs, call/emit sites,
scene `[connection] signal=`/`method=` attrs, the `project.godot [autoload]`
entry and its uses — and the rewrite is that set fed to `core/apply` as ONE
plan: in a `.gd` only the identifier token a typed arm claims, in a scene only
the connection attr's value, in `project.godot` only the autoload's key.

All or nothing, unlike `--retarget` (which writes what it can prove and SKIPs
the rest): a stranded old name is a runtime break with no parse error. Any
blocking site refuses the WHOLE plan, exit 1, every site named, nothing
written. A site blocks when it is:
  * a dynamic hit (`refs` prints these under `dynamic (untyped receiver)`);
  * in a `.gd`, a claimed token inside a string literal, a string literal
    that IS the name (`call("old")`, `&"old"`), or a code token no typed arm
    proves (a member `x.old`, a local, a callable reference);
  * in a scene, a StringName `&"old"` (a call-method track), a
    `script_class="old"`, or any other line holding <old> as a word outside
    a rewritten [connection] attr, a res:// or uid:// path and a section
    header's `name=`/`parent=`/`from=`/`to=` — a built-in script's
    `script/source`, a `NodePath("/root/old")`, a by-name value;
  * a line it would rewrite that already carries <new>.
Before any of that it refuses when <old> or <new> is an engine name — in
the snapshot's `engine_methods` (a method on any class or builtin type, a
utility function: `play`, `_ready`, `queue_free`) or `engine_signals`
(`pressed`) — even when the project defines it too: without types,
`sfx.play()` or a Button's `[connection signal="pressed"]` may be the
engine's, and a rename that rewrote it would break the game. A name in
neither set is unaffected. It also refuses when <new> is already defined (a
class_name, func, signal or autoload), and when <old> is defined nowhere in
the scanned tree — a typo or an engine name is not this project's to rename.

A res:// path or uid that `refs` matches (a preload, an ext_resource) is
neither rewritten nor a block — a rename changes identifiers, not files. Each
prints as a PATH line after the plan, and leaves the exit code alone.
A comment and a node path (`$Name`, `%Name` where an expression starts — after
an operand `%` is modulo) are not references and are left alone. The same rename twice is a no-op: zero hits of <old> with <new> defined
prints `already renamed`, exit 0. Zero hits with <new> undefined is exit 1 —
nothing to rename. <new> not an identifier, a GDScript keyword, or equal to
<old>, is exit 2.
tests/ is ALWAYS in scope — a rename that skips the tests strands their
references — so there is no `--tests` (passing one is a usage error); the
`[refs] exclude_prefixes` scope applies. `--dry-run` prints the diff and
writes nothing.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.core import apply
from godot_devkit.core.config import ConfigError
from godot_devkit.core.project import repo_root
from godot_devkit.godot.format import classdb
from godot_devkit.godot.format.tscn import parse_lines
from godot_devkit.godot.format.tscn_document import LINE_ENDING, read_scene_text
from godot_devkit.godot.read import refs
from godot_devkit.godot.read.autoloads import PROJECT_GODOT
from godot_devkit.godot.write import render_diff, utf8_refusal_reason

EXIT_OK = 0
EXIT_FINDINGS = 1
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
ALREADY = 'already renamed'
CENSUS = '[refs:rename] {census}, {rewritten} rewritten, {blocked} blocked'
CONNECTION_KIND = 'connection'
CONNECTION_ATTRS = ('signal', 'method')
AUTOLOAD_KIND = 'autoload'
GD_SUFFIX = '.gd'
QUOTES = ('"', "'")
NODE_PATH_SIGIL = '$'
UNIQUE_NODE_SIGIL = '%'
OPERAND_END = re.compile(refs.OPERAND_END)
# GDScript's reserved words (Godot 4): a <new> spelled like one is not a name.
GDSCRIPT_KEYWORDS = frozenset((
    'if', 'elif', 'else', 'for', 'while', 'match', 'when', 'break', 'continue',
    'pass', 'return', 'class', 'class_name', 'extends', 'is', 'in', 'as', 'self',
    'super', 'signal', 'func', 'static', 'const', 'enum', 'var', 'breakpoint',
    'preload', 'await', 'yield', 'assert', 'void', 'and', 'or', 'not', 'true',
    'false', 'null', 'PI', 'TAU', 'INF', 'NAN', 'namespace', 'trait',
))

BLOCK_DYNAMIC = 'a dynamic hit — a receiver the index cannot type'
PATH_LINE = ('  PATH  {location}  {path} — left as is; git mv + refs --retarget '
             'if the file should follow')
RESOURCE_PATH = re.compile(r'(?:res|uid)://[^"\s)]+')
PATH_KINDS = (refs.PRELOAD_LOAD_KIND, refs.SCENE_REF_KIND)
BLOCK_IN_STRING = 'inside a string literal — not provably a reference'
BLOCK_STRING_NAMES = ('a string that IS the name — a by-name reference '
                      '(call, has_method, Callable, StringName) the index cannot type')
BLOCK_UNPROVEN = ('an occurrence no typed arm proves — a member, a local or a '
                  'callable reference; rename it by hand or rename the other name first')
BLOCK_CARRIES_NEW = 'the line already carries {new}'
BLOCK_STRINGNAME = 'a StringName naming it — a call-method track or a by-name reference'
BLOCK_SCRIPT_CLASS = 'a script_class naming it — `refs` does not index it; rename by hand'
BLOCK_SCENE_UNPROVEN = ('an occurrence in a scene no [connection] rewrite covers — a built-in '
                        'script, a NodePath, a by-name value; rename it by hand')
# A section header's node addressing: a node's own name, its parent's path, a
# connection's ends — a node in the tree, not the symbol.
NODE_ATTRS = re.compile(r'\b(?:name|parent|from|to)="[^"]*"')
BLOCK_CONNECTION_MISMATCH = ('{found} [connection] attr(s) here, `refs` counted '
                             '{counted} — refusing to guess which')
BLOCK_CONNECTION_SPELLING = 'a [connection] whose signal=/method= is not spelled `attr="name"`'
BLOCK_AUTOLOAD = 'the [autoload] entry for {old} is not one plain `{old}=` line'
BLOCK_UNDEFINED = 'a reference to {old}, which nothing here defines'
BLOCK_NEW_DEFINED = '{new} is already defined here — renaming onto it merges two symbols'
ENGINE_LINE = ('  BLOCKED  {name}  an engine {sets} name ({names_from}) — without types a '
               'call or [connection] on it may be the engine\'s')


@dataclass
class Site:
    """One line the plan touches: a rewrite, or — with a reason — a block."""
    rel: str
    line: int          # 1-based; 0 is the file as a whole
    text: str
    reason: str = ''

    def render(self) -> str:
        location = f'{self.rel}:{self.line}' if self.line else self.rel
        if self.reason:
            return f'  BLOCKED  {location}  {self.reason}: {self.text}'
        return f'  REWRITE  {location}  {self.text}'


@dataclass
class FilePlan:
    path: Path
    rel: str
    before: str
    contents: list[str]
    endings: list[str]
    rewrites: list[Site] = field(default_factory=list)
    blocks: list[Site] = field(default_factory=list)

    def after(self) -> str:
        return ''.join(c + e for c, e in zip(self.contents, self.endings))

    def block(self, index: int, reason: str) -> None:
        self.blocks.append(Site(self.rel, index + 1, self.contents[index].strip(), reason))

    def rewrite(self, index: int, spans: list[tuple[int, int]], new: str) -> None:
        text = self.contents[index]
        for start, end in sorted(spans, reverse=True):
            text = text[:start] + new + text[end:]
        self.contents[index] = text
        self.rewrites.append(Site(self.rel, index + 1, text.strip()))


def _token(name: str) -> re.Pattern:
    return re.compile(rf'(?<!\w){re.escape(name)}(?!\w)')


def _load(root: Path, path: Path, old: str, hit: bool) -> FilePlan | Site | None:
    """The file split into lines with its own endings, a blocking Site when it
    holds <old> and cannot be read as UTF-8, or None when it has nothing to
    say: <old> is not in it and `refs` put no hit there (`hit` — a path hit
    matches case-insensitively, so it can sit in a file <old> is not in)."""
    rel = str(path.relative_to(root))
    try:
        text = read_scene_text(path)
    except UnicodeDecodeError as err:
        lossy = path.read_bytes().decode('utf-8', errors='replace')
        return (Site(rel, 0, utf8_refusal_reason(err), 'unreadable')
                if hit or old in lossy else None)
    except OSError as err:
        return Site(rel, 0, str(err.strerror or err), 'unreadable')
    if not hit and old not in text:
        return None
    parts = LINE_ENDING.split(text)
    return FilePlan(path, rel, text, parts[::2], parts[1::2] + [''])


def _gd_regions(lines: list[str]) -> list[tuple[list[tuple[int, int]], int]]:
    """Per line: the string-literal spans (quotes included) and where a
    comment starts (len(line) when none) — string-aware, which `refs`'s
    comment strip is not. A triple-quoted string carries across lines."""
    out = []
    quote = ''
    for line in lines:
        strings: list[tuple[int, int]] = []
        comment = len(line)
        start = 0
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if char == '\\':
                    index += 2
                    continue
                if line.startswith(quote, index):
                    index += len(quote)
                    strings.append((start, index))
                    quote = ''
                    continue
                index += 1
                continue
            if char == '#':
                comment = index
                break
            if char in QUOTES:
                quote = char * 3 if line.startswith(char * 3, index) else char
                start = index
                index += len(quote)
                continue
            index += 1
        if quote:
            strings.append((start, len(line)))
            if len(quote) == 1:
                quote = ''      # an unterminated one-line string ends with its line
        out.append((strings, comment))
    return out


def _is_node_path(line: str, at: int) -> bool:
    """`$Name`, `%Name`, `$Parent/Name` — a node in the tree, not the symbol.
    A `%` after an operand is modulo (`10%Name`), not a sigil."""
    index = at - 1
    while index >= 0 and (line[index].isalnum() or line[index] in '_/'):
        index -= 1
    if index < 0:
        return False
    if line[index] == UNIQUE_NODE_SIGIL:
        return not (index > 0 and OPERAND_END.match(line[index - 1]))
    return line[index] == NODE_PATH_SIGIL


def _plan_gd(plan: FilePlan, old: str, new: str, global_name: bool,
             dynamic: set[int]) -> None:
    token, new_token = _token(old), _token(new)
    regions = _gd_regions(plan.contents)
    for index, content in enumerate(plan.contents):
        lineno = index + 1
        if lineno in dynamic:
            plan.block(index, BLOCK_DYNAMIC)
            continue
        if old not in content:
            continue
        strings, comment_at = regions[index]
        claimed = refs.typed_spans(old, refs.strip_comment(content), global_name)
        spans, reasons = [], []
        for match in token.finditer(content):
            span = (match.start(), match.end())
            if span[0] >= comment_at:
                continue
            literal = next((s for s in strings if s[0] <= span[0] < s[1]), None)
            if literal is not None:
                if span in claimed:
                    reasons.append(BLOCK_IN_STRING)
                elif content[literal[0]:literal[1]].strip('"\'') == old:
                    reasons.append(BLOCK_STRING_NAMES)
                continue
            if _is_node_path(content, span[0]):
                continue
            if span in claimed:
                spans.append(span)
            else:
                reasons.append(BLOCK_UNPROVEN)
        if spans and new_token.search(content):
            reasons.append(BLOCK_CARRIES_NEW.format(new=new))
        for reason in dict.fromkeys(reasons):
            plan.block(index, reason)
        if spans and not reasons:
            plan.rewrite(index, spans, new)


def _plan_scene(plan: FilePlan, old: str, new: str, counted: int) -> None:
    attr = re.compile(rf'(\b(?:{"|".join(CONNECTION_ATTRS)})="){re.escape(old)}(")')
    stringname = re.compile(rf'&"{re.escape(old)}"')
    script_class = re.compile(rf'\bscript_class="{re.escape(old)}"')
    token, new_token = _token(old), _token(new)
    sections = parse_lines(plan.contents)
    section_headers = {section.header_line for section in sections}
    headers = {section.header_line for section in sections
               if section.kind == CONNECTION_KIND
               and old in (section.attrs.get(a) for a in CONNECTION_ATTRS)}
    for index, content in enumerate(plan.contents):
        if old not in content:
            continue
        connection = index in headers
        # What is left once the parts that are provably not the symbol go: a
        # res:// or uid:// path, a header's node addressing, the attr rewritten.
        rest = RESOURCE_PATH.sub('', content)
        if index in section_headers:
            rest = NODE_ATTRS.sub('', rest)
        if connection:
            rest = attr.sub('', rest)
        blocked = False
        if stringname.search(content):
            plan.block(index, BLOCK_STRINGNAME)
            blocked = True
        if script_class.search(content):
            plan.block(index, BLOCK_SCRIPT_CLASS)
            blocked = True
        if (not blocked and token.search(rest)
                and not (connection and not attr.search(content))):
            plan.block(index, BLOCK_SCENE_UNPROVEN)
            blocked = True
        if not connection or blocked:
            continue
        if new_token.search(content):
            plan.block(index, BLOCK_CARRIES_NEW.format(new=new))
        elif not attr.search(content):
            plan.block(index, BLOCK_CONNECTION_SPELLING)
        else:
            text = attr.sub(lambda m: m.group(1) + new + m.group(2), content)
            plan.contents[index] = text
            plan.rewrites.append(Site(plan.rel, index + 1, text.strip()))
    if len(headers) != counted:
        plan.blocks.append(Site(plan.rel, 0, f'{old} in [connection]',
                                BLOCK_CONNECTION_MISMATCH.format(found=len(headers),
                                                                 counted=counted)))


def _plan_project(plan: FilePlan, old: str, new: str) -> None:
    sections = [s for s in parse_lines(plan.contents) if s.kind == AUTOLOAD_KIND]
    entries = [e for s in sections for e in s.entries if e.key == old]
    key = re.compile(rf'^(\s*){re.escape(old)}(?=\s*=)')
    plain = (len(sections) == 1 and len(entries) == 1
             and entries[0].end - entries[0].start == 1
             and key.match(plan.contents[entries[0].start]))
    if not plain:
        reason = BLOCK_AUTOLOAD.format(old=old)
        if entries:
            plan.block(entries[0].start, reason)
        else:
            plan.blocks.append(Site(plan.rel, 0, f'[{AUTOLOAD_KIND}]', reason))
        return
    index = entries[0].start
    plan.contents[index] = key.sub(lambda m: m.group(1) + new, plan.contents[index], count=1)
    plan.rewrites.append(Site(plan.rel, index + 1, plan.contents[index].strip()))


def _lines(hits: list[refs.Hit]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for hit in hits:
        out.setdefault(hit.path, set()).add(hit.line)
    return out


def _plan(root: Path, found: refs.Scan, old: str, new: str) -> tuple[list[FilePlan], list[Site]]:
    """Every file's rewrite, and every site that blocks the whole plan."""
    hits = found.hits
    dynamic = _lines(hits[refs.DYNAMIC_KIND])
    connections: dict[str, int] = {}
    for hit in hits[refs.SCENE_CONNECTION_KIND]:
        connections[hit.path] = connections.get(hit.path, 0) + 1
    plans: list[FilePlan] = []
    blocks: list[Site] = []

    def load(path: Path, hit: bool = False) -> FilePlan | None:
        loaded = _load(root, path, old, hit)
        if isinstance(loaded, Site):
            blocks.append(loaded)
            return None
        return loaded

    for path in found.gd_files:
        rel = str(path.relative_to(root))
        plan = load(path, rel in dynamic)
        if plan is not None:
            _plan_gd(plan, old, new, found.global_name,
                     dynamic.get(rel, set()))
            plans.append(plan)
    for path in found.scene_files:
        plan = load(path, str(path.relative_to(root)) in connections)
        if plan is not None:
            _plan_scene(plan, old, new, connections.get(plan.rel, 0))
            plans.append(plan)
    if any(hit.path == PROJECT_GODOT for hit in hits[refs.DEFINITION_KIND]):
        plan = load(root / PROJECT_GODOT, True)
        if plan is not None:
            _plan_project(plan, old, new)
            plans.append(plan)
    for plan in plans:
        blocks.extend(plan.blocks)
    return [p for p in plans if p.rewrites], blocks


def _engine_sets(name: str) -> str:
    """Which engine name set(s) hold `name` — `method`, `signal`, both — or ''."""
    held = [kind for kind, names in (('method', classdb.engine_methods()),
                                     ('signal', classdb.engine_signals()))
            if name in names]
    return ' and '.join(held)


def _location(hit: refs.Hit) -> str:
    return f'{hit.path}:{hit.line}' if hit.line else hit.path


def run(old: str, new: str, dry_run: bool) -> int:
    root = repo_root()
    found = refs.scan(root, old, include_tests=True)
    new_definitions = refs.scan(root, new, include_tests=True).hits[refs.DEFINITION_KIND]
    census = found.searched.census('file(s) searched')
    header = f'rename  {old} -> {new}' + ('  (dry run — nothing written)' if dry_run else '')
    total = sum(len(hits) for kind, hits in found.hits.items() if kind not in PATH_KINDS)

    def verdict(rewritten: int, blocked: int) -> None:
        for kind in PATH_KINDS:
            for hit in found.hits[kind]:
                shown = RESOURCE_PATH.search(hit.text)
                print(PATH_LINE.format(location=_location(hit),
                                       path=shown.group(0) if shown else hit.text))
        print(CENSUS.format(census=census, rewritten=rewritten, blocked=blocked))

    engine = [(name, sets) for name in (old, new) if (sets := _engine_sets(name))]
    if engine:
        print(header)
        for name, sets in engine:
            print(ENGINE_LINE.format(name=name, sets=sets,
                                     names_from=classdb.engine_names_from()))
        print(f'REFUSED  {" and ".join(name for name, _ in engine)} '
              f'{"is an engine name" if len(engine) == 1 else "are engine names"} — '
              f'a rename cannot tell the project\'s from the engine\'s; nothing written')
        verdict(0, len(engine))
        return EXIT_FINDINGS
    if total == 0:
        if new_definitions:
            print(f'{header}  {ALREADY}  ({new} is defined at '
                  f'{_location(new_definitions[0])}; no reference to {old} is left)')
            verdict(0, 0)
            return EXIT_OK
        print(header)
        print(f'REFUSED  no reference to {old} and no definition of {new} — '
              f'nothing to rename')
        verdict(0, 0)
        return EXIT_FINDINGS
    if not found.hits[refs.DEFINITION_KIND]:
        print(header)
        sites = [Site(hit.path, hit.line, hit.text, BLOCK_UNDEFINED.format(old=old))
                 for kind, hits in found.hits.items() if kind not in PATH_KINDS
                 for hit in hits]
        for site in sites:
            print(site.render())
        print(f'REFUSED  {old} is defined nowhere in the scanned tree — an engine '
              f'name or a typo is not this project\'s to rename; nothing written')
        verdict(0, len(sites))
        return EXIT_FINDINGS
    if new_definitions:
        print(header)
        for hit in new_definitions:
            print(Site(hit.path, hit.line, hit.text, BLOCK_NEW_DEFINED.format(new=new)).render())
        print(f'REFUSED  {new} is already defined — nothing written')
        verdict(0, len(new_definitions))
        return EXIT_FINDINGS

    plans, blocks = _plan(root, found, old, new)
    rewritten = sum(len(plan.rewrites) for plan in plans)
    print(header)
    if blocks:
        for site in blocks:
            print(site.render())
        print(f'REFUSED  {len(blocks)} blocking site(s) — a rename is all or nothing; '
              f'nothing written')
        verdict(0, len(blocks))
        return EXIT_FINDINGS
    if dry_run:
        for plan in plans:
            print(render_diff(plan.before, plan.after(), plan.rel), end='')
        verdict(rewritten, 0)
        return EXIT_OK
    write = apply.Plan()
    for plan in plans:
        write.overwrite(plan.path, plan.after())
    applied = write.apply()
    if applied.blocked:
        for blocked in applied.blocked:
            print(f'  BLOCKED  {blocked.describe()}')
        print('REFUSED  the plan cannot be written — nothing written')
        verdict(0, len(applied.blocked))
        return EXIT_FINDINGS
    for plan in plans:
        for site in plan.rewrites:
            print(site.render())
    if applied.failed is not None:
        landed = ', '.join(str(step.dest.relative_to(root)) for step in applied.landed)
        print(f'FAILED  {applied.failed.dest.relative_to(root)}: {applied.error} — '
              f'written before it: {landed or "nothing"}')
        verdict(len(applied.landed), 0)
        return EXIT_FINDINGS
    verdict(rewritten, 0)
    return EXIT_OK


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog='godot-devkit refs', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rename', nargs=2, metavar=('OLD', 'NEW'), required=True,
                        help='a class_name / method / signal / autoload: every '
                             'reference to OLD is rewritten to NEW, or none is')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the diff, write nothing')
    args = parser.parse_args(argv)
    old, new = args.rename
    for name in (old, new):
        if not IDENTIFIER.match(name):
            parser.error(f'{name!r} is not an identifier ([A-Za-z_][A-Za-z0-9_]*)')
    if new in GDSCRIPT_KEYWORDS:
        parser.error(f'{new!r} is a GDScript keyword — not a name a symbol can take')
    if old == new:
        parser.error(f'old and new are the same name ({old}) — nothing to rename')
    try:
        return run(old, new, args.dry_run)
    except ConfigError as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
