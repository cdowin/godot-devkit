"""check props — assert every assigned scene property actually EXISTS.

The incident this gate exists for: a `@export var floor_layer` was renamed to
`background_layer`, but a shared test fixture kept assigning `floor_layer`. Godot
silently drops an assignment to a property that no longer exists, so the node
came up half-configured. 26 integration scenarios died, every gate stayed green,
the cause was misdiagnosed as a design problem, and 47 tests were deleted over
it. A one-line static check would have named the file the moment it landed.

CHECK (HARD): for every section carrying a `script =` (scene nodes, sub_resources
              and .tres resources alike), every assigned property is either an
              `@export` on that script's inheritance chain, or a built-in of the
              node/resource type.

Precision matters more than reach here: a gate that cries wolf gets switched
off. So a property is only ever reported DEAD when the whole picture is known —
the script parsed, its `extends` chain terminated in a known engine class, and
the script declares no dynamic properties. Everything else is counted as
UNVERIFIED and printed as a census line, never as a finding:

  * nodes with no script          — pure engine types, nothing to drift against
  * `_`-prefixed and `a/b`-form   — engine-synthesized (`theme_override_*/x`,
    property keys                   `metadata/y`, `popup/item_0/text`)
  * instance-child overrides       — `[node name=.. parent=..]` with no `type=`
                                     and no `instance=`; the target lives in
                                     another scene, resolved when reachable and
                                     reported unverified when not
  * scripts with `_get_property_list` / `_set`, or an unresolvable `extends`

devkit.toml: [props] exclude_prefixes = ["addons/"]
             [props] extra_properties = { MyClass = ["virtual_prop"] }
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from godot_devkit import classdb
from godot_devkit.gdscript import RES_PREFIX, Resolution, ScriptIndex
from godot_devkit.project import git_lines, load_config, repo_root, config_section, str_tuple
from godot_devkit.tscn import (
    Section,
    node_own_path,
    parse,
    split_path,
)
from godot_devkit.tscn import (
    ext_index as _ext_index,
)
from godot_devkit.tscn import (
    ref_path as _ref_path,
)
from godot_devkit.tscn import (
    script_path as _script_path,
)

DEFAULT_EXCLUDE = ('addons/',)
SCRIPT_PROP = 'script'
NODE_PATHS_ATTR = re.compile(r'PackedStringArray\(([^)]*)\)')
QUOTED = re.compile(r'"([^"]*)"')
CHECKED_KINDS = ('node', 'sub_resource', 'resource')
RESOURCE_KIND = 'resource'
GD_RESOURCE_KIND = 'gd_resource'
# Godot synthesizes these at load time; they are never declared anywhere.
PATH_FORM_KEY = '/'
INTERNAL_PREFIX = '_'


class SceneCache:
    """Answers `(engine type, script)` for a node inside ANOTHER scene file.

    Instance overrides are the toolkit's blind spot if left unresolved: a
    `[node name="Child" parent="Root" index="0"]` names a node that lives in the
    instanced base scene, so the property universe is over there. This walks the
    instance chain to find it, and returns `(None, None)` — reported UNVERIFIED,
    never DEAD — the moment any hop cannot be resolved.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._roots: dict[str, tuple[str | None, str | None]] = {}
        self._files: dict[str, list[Section] | None] = {}

    def _sections(self, res_path: str) -> list[Section] | None:
        if res_path not in self._files:
            file = self.root / res_path[len(RES_PREFIX):]
            self._files[res_path] = (parse(str(file))
                                     if res_path.startswith(RES_PREFIX) and file.is_file()
                                     else None)
        return self._files[res_path]

    def root_of(self, res_path: str) -> tuple[str | None, str | None]:
        """-> (node type, script res:// path) of the scene's root node."""
        if res_path in self._roots:
            return self._roots[res_path]
        self._roots[res_path] = (None, None)         # cycle guard
        sections = self._sections(res_path)
        if sections is None:
            return self._roots[res_path]
        node = next((s for s in sections if s.kind == 'node' and 'parent' not in s.attrs), None)
        if node is not None:
            self._roots[res_path] = self._describe(res_path, sections, node)
        return self._roots[res_path]

    def node_at(self, res_path: str, path: list[str],
                skip_self: bool = False) -> tuple[str | None, str | None]:
        """-> (node type, script) for `path` inside `res_path`, following the
        instance chain when the path descends into an instanced sub-scene.

        `skip_self` is how an override stub asks about ITSELF: the node exists in
        this file, but as a bare `[node name=.. parent=..]` carrying only the
        overridden values — the definition it overrides is in the base scene.
        """
        if not path:
            return self.root_of(res_path)
        sections = self._sections(res_path)
        if sections is None:
            return (None, None)
        nodes = {tuple(split_path(node_own_path(s))): s for s in sections if s.kind == 'node'}
        target = None if skip_self else nodes.get(tuple(path))
        if target is not None:
            return self._describe(res_path, sections, target)
        for cut in range(len(path) - 1, 0, -1):       # descend into an instance
            host = nodes.get(tuple(path[:cut]))
            if host is None or 'instance' not in host.attrs:
                continue
            ext = _ext_index(sections)
            base = _ref_path(host.attrs['instance'], ext)
            return self.node_at(base, path[cut:]) if base else (None, None)
        return (None, None)

    def _describe(self, res_path: str, sections: list[Section],
                  node: Section) -> tuple[str | None, str | None]:
        ext = _ext_index(sections)
        script = _script_path(node, ext)
        kind = node.attrs.get('type')
        if 'instance' in node.attrs:
            base = _ref_path(node.attrs['instance'], ext)
            if base:
                inherited_kind, inherited_script = self.root_of(base)
                kind = kind or inherited_kind
                script = script or inherited_script
        return kind, script


def _is_unverifiable_key(key: str) -> bool:
    return key == SCRIPT_PROP or PATH_FORM_KEY in key or key.startswith(INTERNAL_PREFIX)


def _exported_node_paths(section: Section) -> list[str]:
    """`node_paths=PackedStringArray("a","b")` lists exported PROPERTY names —
    a rename leaves them stale exactly like a body assignment does."""
    raw = section.attrs.get('node_paths')
    if not raw:
        return []
    inner = NODE_PATHS_ATTR.search(raw)
    return QUOTED.findall(inner.group(1)) if inner else []


class Report:
    """Every property in a checked section lands in exactly ONE bucket.

    The buckets are printed and they must add up: a gate that silently drops a
    property from its own census is one refactor away from a false PASS.
    """

    def __init__(self) -> None:
        self.dead: list[str] = []
        self.unverified = Counter()
        self.skipped = Counter()
        self.verified = 0
        self.sections = 0
        self.files = 0
        self.seen = 0                # every property offered to the checker

    @property
    def accounted(self) -> int:
        return (self.verified + len(self.dead) + sum(self.unverified.values())
                + sum(self.skipped.values()))


def _check_section(section: Section, rel: str, ext: dict[str, dict], scripts: ScriptIndex,
                   scenes: SceneCache, extra: dict[str, list[str]], report: Report,
                   file_type: str | None = None) -> None:
    """Decide, for one scripted section, which property names are legal.

    Three sources contribute, and all three must be KNOWN before anything is
    called dead: the script's own `@export`s (with inheritance folded in), the
    engine class the node declares, and — for an instanced node — the engine
    class of the base scene's root. That last one is why an `instance=` node
    that also overrides `script=` is not a false positive: the node is still a
    Button even if the override script only `extends Control`.
    """
    script_rel = _script_path(section, ext)
    # A .tres body section is `[resource]` with no type of its own — the type
    # lives on the file's `[gd_resource type="..."]` header.
    types: list[str | None] = [section.attrs.get('type')]
    if section.kind == RESOURCE_KIND:
        types.append(file_type)

    if section.kind == 'node' and 'instance' in section.attrs:
        base = _ref_path(section.attrs['instance'], ext)
        base_type, base_script = scenes.root_of(base) if base else (None, None)
        types.append(base_type)
        script_rel = script_rel or base_script
        if script_rel is None and base_type is None:
            report.unverified['instance root (base scene unreadable)'] += len(section.entries)
            return
    elif section.kind == 'node' and script_rel is None and section.attrs.get('type') is None:
        # An override on a child that lives inside an instanced scene: resolve
        # the node through the instance chain, or report it unverified.
        child_type, child_script = scenes.node_at(
            RES_PREFIX + rel, split_path(node_own_path(section)), skip_self=True)
        types.append(child_type)
        script_rel = child_script
        if script_rel is None and child_type is None:
            report.unverified['instance-child override (unresolvable)'] += len(section.entries)
            return

    # A scriptless node still has a drift surface — a mistyped built-in
    # (`positon = ...`) is dropped by Godot just as silently as a stale export.
    resolved = Resolution(frozenset(), None, opaque=False)
    if script_rel is not None:
        report.sections += 1
        if not scripts.has(script_rel):
            report.unverified['script not readable'] += len(section.entries)
            return
        resolved = scripts.resolve(script_rel)
        if resolved.opaque:
            report.unverified['script declares dynamic properties'] += len(section.entries)
            return
        types.append(resolved.engine_base)
    known = [t for t in types if t is not None and classdb.is_known(t)]
    if not known:
        unknown = next((t for t in types if t is not None), None)
        report.unverified[f'unknown base class {unknown or "?"}'] += len(section.entries)
        return

    allowed = set(resolved.exports) | classdb.SYNTHESIZED_PROPERTIES
    for kind in known:
        allowed |= classdb.properties_of(kind)
    for names in extra.values():
        allowed.update(names)

    where = section.attrs.get('name') or section.attrs.get('id') or section.kind
    bases = '/'.join(dict.fromkeys(known))
    origin = f'an @export of {script_rel} nor ' if script_rel else ''
    for key in _exported_node_paths(section):
        report.seen += 1                             # censused like any assignment
        if key in resolved.exports:
            report.verified += 1
            continue
        report.dead.append(f'  DEAD  {rel} : {where}.node_paths lists {key!r} — '
                           f'not an @export of {script_rel}')
    for entry in section.entries:
        if _is_unverifiable_key(entry.key):
            report.skipped['engine-synthesized key (script / _x / a/b form)'] += 1
            continue
        if entry.key in allowed:
            report.verified += 1
            continue
        report.dead.append(f'  DEAD  {rel} : {where}.{entry.key} — not {origin}'
                           f'a property of {bases}')


def run() -> int:
    root = repo_root()
    config = config_section('props')
    exclude = str_tuple(config, 'props', 'exclude_prefixes', DEFAULT_EXCLUDE)
    extra = config.get('extra_properties', {})

    scripts = ScriptIndex(root, [p for p in git_lines('ls-files', '*.gd')
                                 if not p.startswith(exclude)])
    scenes = SceneCache(root)
    report = Report()

    print('[check:props] CHECK — every assigned property exists as an @export '
          'or an engine built-in')
    for rel in git_lines('ls-files', '*.tscn', '*.tres'):
        if rel.startswith(exclude):
            continue
        report.files += 1
        sections = parse(str(root / rel))
        ext = _ext_index(sections)
        file_type = next((s.attrs.get('type') for s in sections
                          if s.kind == GD_RESOURCE_KIND), None)
        for section in sections:
            if section.kind in CHECKED_KINDS:
                report.seen += len(section.entries)
                _check_section(section, rel, ext, scripts, scenes, extra, report, file_type)

    for line in report.dead:
        print(line)
    census = ', '.join(f'{count} {reason}' for reason, count in report.unverified.most_common())
    skipped = ', '.join(f'{count} {reason}' for reason, count in report.skipped.most_common())
    if report.accounted != report.seen:
        print(f'  BUG  census does not balance: saw {report.seen} properties, '
              f'accounted for {report.accounted}')
        return 2
    if report.files == 0:
        print('[check:props] FAIL — scanned 0 files; check [props] exclude_prefixes')
        return 1
    if report.dead:
        print(f'[check:props] FAIL — {len(report.dead)} assignment(s) point at a property '
              f'that does not exist')
        print('  Fix: rename the assignment to the current @export, or re-add the export.')
        print(f'  verified {report.verified} across {report.sections} scripted section(s) '
              f'in {report.files} file(s) (ClassDB {classdb.godot_version()})')
        print(f'  UNVERIFIED (not a finding): {census or "none"}')
        print(f'  NOT APPLICABLE: {skipped or "none"} '
              f'[{report.seen} properties seen, all accounted for]')
        return 1
    print(f'[check:props] PASS — {report.verified} assignment(s) verified across '
          f'{report.sections} scripted section(s) in {report.files} file(s) '
          f'(ClassDB {classdb.godot_version()})')
    print(f'  UNVERIFIED (not a finding): {census or "none"}')
    print(f'  NOT APPLICABLE: {skipped or "none"} '
          f'[{report.seen} properties seen, all accounted for]')
    return 0
