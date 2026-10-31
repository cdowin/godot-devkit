"""editor_layout.py — the FILE-level layout Godot 4.7's text saver writes.

`scene canonicalize --order` runs these after the property-level passes; `check
canonical` runs them on a scratch copy and reports what they would change, so
the gate flags exactly what the fixer fixes. Each was measured on an editor save
and is pinned by a pair under `tests/fixtures/editor_parity/`:

* **header** — `load_steps=` is never written (`.tscn` and `.tres`); a
  `.tres` whose `[resource]` script has a `class_name` carries
  `script_class="<name>"` right after `type=`, and one whose script has none
  carries no `script_class`.
* **ext_resources** — one contiguous block, no blank line inside, sorted by
  id in natural order, letters compared upper-cased, whatever order they
  were written in (`1` < `6_hpjp2` < `charms` < `charm_roller`).
* **sub_resources** — in the order the saver first REACHES each one: walk the
  `[resource]` (or every `[node]`, in file order) property by property — a
  resource section's properties sorted by NAME, not as written — and a
  sub_resource's own references come before it. The walk reads each value as
  written, so a dictionary is walked in its written key order — the order the
  NEXT save walks a file whose keys are already sorted. SpriteFrames
  `animations` is walked by name, the order the engine rebuilds it in.

What is not proven is refused by name and left alone: a comment among the
lines that would move, an ext_resource with a body, a sub_resource nothing
references (the saver would DROP it — a deletion is not a reorder).
"""
from __future__ import annotations

import re
from pathlib import Path

from godot_devkit.godot.format.tscn import (
    COMMENT_CHAR,
    EXT_RESOURCE_KIND,
    HEADER_ATTR,
    NODE_KIND,
    RESOURCE_REF,
    Section,
    ext_index,
    join_path,
    ref_path,
    script_path,
)
from godot_devkit.godot.format.tscn_document import TscnDocument, mint_unique_id
from godot_devkit.godot.format.value_order import OrderRefusal, animations_in_engine_order
from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.godot.index.shader_uniforms import UniformRefusal, material_parameters

SUB_RESOURCE_KIND = 'sub_resource'
RESOURCE_KIND = 'resource'
HEADER_KINDS = ('gd_scene', 'gd_resource')
RESOURCE_HEADER = 'gd_resource'
SCENE_HEADER = 'gd_scene'
ID_PRECEDES = ('name', 'type', 'parent', 'index')
SHADER_MATERIAL = 'ShaderMaterial'
SHADER_PROP = 'shader'
PARAM_PREFIX = 'shader_parameter/'
RES_PREFIX = 'res://'
TOOL_ANNOTATION = re.compile(r'^@tool\b', re.M)
RESOURCE_DEFAULT = re.compile(r'^(?:pre)?load\("([^"]+)"\)$')
LOAD_STEPS = re.compile(r' load_steps=\d+')
TYPE_ATTR = re.compile(r'\btype="[^"]*"')
SCRIPT_CLASS_ATTR = re.compile(r' script_class="[^"]*"')
DIGITS = re.compile(r'\d+|\D')
SPRITE_FRAMES = 'SpriteFrames'
ANIMATIONS = 'animations'
SUB = 'Sub'


def _header(doc: TscnDocument) -> Section | None:
    return next((s for s in doc.sections if s.kind in HEADER_KINDS), None)


def drop_load_steps(doc: TscnDocument) -> list[str]:
    header = _header(doc)
    if header is None or 'load_steps' not in header.attrs:
        return []
    line = doc.lines[header.header_line]
    doc.replace_lines(header.header_line, header.header_line + 1, [LOAD_STEPS.sub('', line)])
    return ['  HEADER  load_steps= dropped (Godot 4.7 never writes it)']


def restore_script_class(doc: TscnDocument, scripts: ScriptIndex) -> list[str]:
    """`script_class=` on a `.tres` header, from the `[resource]` script's `class_name`."""
    header = _header(doc)
    body = next((s for s in doc.sections if s.kind == RESOURCE_KIND), None)
    if header is None or header.kind != RESOURCE_HEADER or body is None:
        return []
    script = script_path(body, ext_index(doc.sections))
    have = header.attrs.get('script_class')
    have = have.strip('"') if have is not None else None
    if script is None:
        want = None
    elif not scripts.has(script):
        if have is None:
            return []
        return [f'  UNRESOLVED  header script_class: {script} is not readable — left as written']
    else:
        want = scripts.by_path[script].class_name
    if want == have:
        return []
    line = doc.lines[header.header_line]
    line = SCRIPT_CLASS_ATTR.sub('', line)
    if want is not None:
        match = TYPE_ATTR.search(line)
        if match is None:
            return ['  UNRESOLVED  header has no type= to place script_class after — left as written']
        line = f'{line[:match.end()]} script_class="{want}"{line[match.end():]}'
    doc.replace_lines(header.header_line, header.header_line + 1, [line])
    return [f'  HEADER  script_class: {have or "(none)"} -> {want or "(none)"}']


def natural_key(text: str) -> tuple:
    """Godot's `naturalnocasecmp_to`: digit runs compare as numbers, letters UPPER-cased.

    Upper-casing puts `_` after every letter: `charms` < `charm_roller`.
    """
    return tuple((ord('0'), int(part)) if part.isdigit() else (ord(part.upper()), 0)
                 for part in DIGITS.findall(text))


def sort_ext_resources(doc: TscnDocument) -> list[str]:
    exts = [s for s in doc.sections if s.kind == EXT_RESOURCE_KIND]
    if not exts:
        return []
    first, last = exts[0].header_line, exts[-1].header_line
    region = doc.lines[first:last + 1]
    heads = {s.header_line for s in exts}
    others = [i for i in range(first, last + 1) if i not in heads and doc.lines[i].strip()]
    if any(s.entries for s in exts) or others:
        return ['  UNRESOLVED  ext_resource block holds a comment, a body or another section '
                '— order left as written']
    ids = [s.attrs.get('id', '') for s in exts]
    if len({natural_key(i) for i in ids}) != len(ids):
        return ['  UNRESOLVED  two ext_resource ids tie in natural order — order left as written']
    ordered = sorted(exts, key=lambda s: natural_key(s.attrs.get('id', '')))
    lines = [doc.lines[s.header_line] for s in ordered]
    if lines == region:
        return []
    doc.replace_lines(first, last + 1, lines)
    report = []
    if [s.attrs.get('id') for s in ordered] != ids:
        report.append(f'  EXT ORDER  {len(ids)} ext_resource(s) sorted by id')
    if len(region) != len(lines):
        report.append(f'  EXT ORDER  {len(region) - len(lines)} blank line(s) inside the '
                      f'ext_resource block dropped')
    return report


def _refs(section: Section, kind: str | None) -> list[str]:
    """SubResource ids a section references, in the order the saver walks them."""
    ids = []
    entries = section.entries
    if section.kind in (RESOURCE_KIND, SUB_RESOURCE_KIND):
        entries = sorted(entries, key=lambda entry: entry.key)
    for entry in entries:
        value = entry.value
        if kind == SPRITE_FRAMES and entry.key == ANIMATIONS:
            value = animations_in_engine_order(value, 0)
        ids += [m.group(2) for m in RESOURCE_REF.finditer(value) if m.group(1) == SUB]
    return ids


def first_use_order(doc: TscnDocument) -> list[str]:
    """Sub_resource ids in the order the saver reaches them. Raises OrderRefusal."""
    header = _header(doc)
    subs = {s.attrs.get('id'): s for s in doc.sections if s.kind == SUB_RESOURCE_KIND}
    order: list[str] = []
    seen: set[str] = set()

    def visit(sub_id: str) -> None:
        if sub_id in seen:
            return
        if sub_id not in subs:
            raise OrderRefusal(f'SubResource("{sub_id}") names no sub_resource')
        seen.add(sub_id)
        for ref in _refs(subs[sub_id], subs[sub_id].attrs.get('type')):
            visit(ref)
        order.append(sub_id)

    for section in doc.sections:
        if section.kind in (EXT_RESOURCE_KIND, SUB_RESOURCE_KIND) or section.kind in HEADER_KINDS:
            continue
        kind = header.attrs.get('type') if section.kind == RESOURCE_KIND and header else None
        for ref in _refs(section, kind):
            visit(ref)
    unused = [i for i in subs if i not in seen]
    if unused:
        raise OrderRefusal(f'sub_resource {", ".join(unused)} is referenced by nothing '
                           f'(the saver would drop it)')
    return order


def order_sub_resources(doc: TscnDocument) -> list[str]:
    subs = [s for s in doc.sections if s.kind == SUB_RESOURCE_KIND]
    if len(subs) < 2:
        return []
    try:
        order = first_use_order(doc)
    except OrderRefusal as refusal:
        return [f'  UNRESOLVED  sub_resource order: {refusal} — left as written']
    if order == [s.attrs.get('id') for s in subs]:
        return []
    position = doc.sections.index(subs[0])
    tail = doc.sections[position + len(subs)] if position + len(subs) < len(doc.sections) else None
    contiguous = doc.sections[position:position + len(subs)] == subs
    end = tail.header_line if tail is not None else len(doc.lines)
    starts = [s.header_line for s in subs] + [end]
    blocks = {s.attrs.get('id'): doc.lines[starts[i]:starts[i + 1]] for i, s in enumerate(subs)}
    trailers = {tuple(doc.lines[s.body_end:starts[i + 1]]) for i, s in enumerate(subs)}
    above = subs[0].header_line > 0 and doc.lines[subs[0].header_line - 1].lstrip().startswith(
        COMMENT_CHAR)
    if not contiguous or above or len(trailers) != 1 or any(
            line.strip() for trailer in trailers for line in trailer):
        return ['  UNRESOLVED  sub_resource order drifts but a comment, an irregular blank line '
                'or another section sits among them — left as written']
    doc.replace_lines(starts[0], end, [line for sub_id in order for line in blocks[sub_id]])
    return [f'  SUB ORDER  {len(order)} sub_resource(s) moved to first-use order']


def mint_unique_ids(doc: TscnDocument) -> list[str]:
    """`unique_id=` on every node this scene CREATES that lacks one.

    The editor writes one on every node of a `.tscn` and KEEPS any it reads,
    so its own value is random but any valid id survives the next save: a
    deterministic one (from the node's path, as `scene add` mints) is the
    form an editor save leaves alone. An override of an instance's child is
    different — the editor copies the BASE node's id — so it is reported,
    never minted.
    """
    header = _header(doc)
    if header is None or header.kind != SCENE_HEADER:
        return []
    held = {s.attrs['unique_id'] for s in doc.nodes if 'unique_id' in s.attrs}
    report, overrides, edits = [], 0, []
    for node in doc.nodes:
        if 'unique_id' in node.attrs:
            continue
        created = node.attrs.get('parent') is None or 'type' in node.attrs \
            or 'instance' in node.attrs
        if not created:
            overrides += 1
            continue
        line = doc.lines[node.header_line]
        attrs = list(HEADER_ATTR.finditer(line))
        names = [m.group(1) for m in attrs]
        lead = [i for i, name in enumerate(names) if name in ID_PRECEDES]
        if not lead or lead != list(range(len(lead))):
            report.append(f'  UNRESOLVED  unique_id: node {node.attrs.get("name")} has an '
                          f'attribute order the tool cannot place unique_id in — left as written')
            continue
        value = mint_unique_id(join_path(list(doc.node_path(node))) or '.', held)
        held.add(value)
        cut = attrs[lead[-1]].end()
        edits.append((node.header_line, f'{line[:cut]} unique_id={value}{line[cut:]}'))
    for index, line in edits:
        doc.replace_lines(index, index + 1, [line])
    if edits:
        report.append(f'  UNIQUE ID  {len(edits)} node(s) given a unique_id= (an editor save '
                      f'keeps it)')
    if overrides:
        report.append(f'  NOTE  {overrides} instance-child override(s) lack unique_id= — the '
                      f'editor copies the base node\'s id; left as written')
    return report


def _material_sections(doc: TscnDocument) -> list[Section]:
    header = _header(doc)
    return [s for s in doc.sections
            if (s.kind == RESOURCE_KIND and header is not None
                and header.attrs.get('type') == SHADER_MATERIAL)
            or (s.kind == SUB_RESOURCE_KIND and s.attrs.get('type') == SHADER_MATERIAL)]


def write_shader_parameters(doc: TscnDocument, root: Path) -> list[str]:
    """Each ShaderMaterial's `shader_parameter/*` lines, as a windowed editor writes them."""
    report = []
    for section in _material_sections(doc):
        where = f'{section.kind} {section.attrs.get("id", "")}'.strip()
        try:
            body = _material_body(doc, section, root)
        except UniformRefusal as refusal:
            report.append(f'  UNRESOLVED  {where} shader parameters: {refusal} — left as written')
            continue
        first = section.header_line + 1
        if body is None or body == doc.lines[first:section.body_end]:
            continue
        added = len(body) - (section.body_end - first)
        doc.replace_lines(first, section.body_end, body)
        report.append(f'  SHADER  {where}: {added} shader_parameter(s) written from the '
                      f'shader\'s uniform defaults, in declaration order')
    return report


def _material_body(doc: TscnDocument, section: Section, root: Path) -> list[str] | None:
    keys = [e.key for e in section.entries]
    shader = section.prop(SHADER_PROP)
    if shader is None:
        return None
    path = ref_path(shader.value, ext_index(doc.sections))
    if path is None or not path.startswith(RES_PREFIX):
        raise UniformRefusal('the shader is not an ext_resource .gdshader in this repo')
    file = root / path[len(RES_PREFIX):]
    if not file.is_file():
        raise UniformRefusal(f'{path} is not readable')
    params = material_parameters(file.read_text(encoding='utf-8'))
    names = {name for name, _ in params}
    if keys[0] != SHADER_PROP or any(not k.startswith(PARAM_PREFIX) for k in keys[1:]):
        raise UniformRefusal('the material holds a property other than shader and '
                             'shader_parameter/* — its place is not measured')
    unknown = [k for k in keys[1:] if k[len(PARAM_PREFIX):] not in names]
    if unknown:
        raise UniformRefusal(f'{", ".join(unknown)} names no uniform of {path}')
    if sum(e.end - e.start for e in section.entries) != section.body_end - section.header_line - 1:
        raise UniformRefusal('a comment or blank line sits among the material\'s properties')
    lines = list(doc.lines[shader.start:shader.end])
    for name, value in params:
        held = section.prop(PARAM_PREFIX + name)
        lines += (doc.lines[held.start:held.end] if held is not None
                  else [f'{PARAM_PREFIX}{name} = {value}'])
    return lines


def tool_default_refs(doc: TscnDocument, scripts: ScriptIndex) -> list[str]:
    """Name what a parse cannot write: a `@tool` script's resource default.

    The editor runs a `@tool` script, so an export left at a `preload()` /
    `load()` default makes the save add an ext_resource for that resource —
    under an id the editor generates at random, with no property using it.
    Nothing a parse can derive; reported so a PASS never hides it.
    """
    ext = ext_index(doc.sections)
    held = {attrs.get('path') for attrs in ext.values()}
    report = []
    for section in doc.sections:
        if section.kind not in (RESOURCE_KIND, SUB_RESOURCE_KIND):
            continue
        script = script_path(section, ext)
        if script is None or not scripts.has(script) or not _is_tool(scripts, script):
            continue
        resolved = scripts.resolve(script)
        for name, decl in resolved.declarations.items():
            match = RESOURCE_DEFAULT.match((decl.default or '').strip())
            if match and section.prop(name) is None and match.group(1) not in held:
                report.append(f'  UNRESOLVED  {section.kind}.{name}: @tool default '
                              f'{match.group(1)} — the editor adds an ext_resource for it '
                              f'under a random id; not derivable by parse')
    return report


def _is_tool(scripts: ScriptIndex, script: str) -> bool:
    try:
        text = (scripts.root / script[len(RES_PREFIX):]).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return False
    return TOOL_ANNOTATION.search(text) is not None


def layout(doc: TscnDocument, scripts: ScriptIndex | None,
           root: Path | None = None) -> list[str]:
    """Every file-level pass, in the order `--order` runs them."""
    report = mint_unique_ids(doc)
    if root is not None:
        report += write_shader_parameters(doc, root)
    report += order_sub_resources(doc)
    report += sort_ext_resources(doc)
    report += drop_load_steps(doc)
    if scripts is not None:
        report += restore_script_class(doc, scripts)
        report += tool_default_refs(doc, scripts)
    return report
