"""check ui-layout — action buttons live in the action bar, not in a modal's scroll.

OPT-IN: not in `check all`. With no `[ui_layout]` section it prints PASS and does
nothing; name `ui-layout` in `[roster] checks` to run it in the aggregate.

CHECK (HARD), three finding kinds, each on a `  <kind>  <file> : <node path> — <why>` line:
  action-outside-bar     a node whose `role_property` value is one of `action_roles`
                         and none of whose ancestors is an `action_bar_types` node
  button-in-modal-scroll a Button (or any class deriving Button, by the engine class
                         snapshot) with a ScrollContainer ancestor that sits under, or
                         is, a `modal_types` node
  label-no-overflow      a Label under a `panel_types` or `modal_types` node that sets
                         neither `autowrap_mode` nor `text_overrun_behavior`. Those are
                         Label properties, not theme items, so no theme (and no
                         `theme_type_variation`) can supply them and none exempts a Label.

TYPE MATCHING. A node matches a configured type when its `type=` equals the entry,
or its `script = ExtResource(..)` points at a .gd whose `class_name` does (Godot
writes the native base type into `type=` and never the script class). For an
instanced node (`instance=ExtResource(..)`), the instanced scene's ROOT type or
script class does, following the root's own `instance=` chain (an inherited scene's
root has `instance=` and no `type=`). Only the script's own `class_name` is read,
not its `extends` chain. Nodes inside an instanced scene are judged with the
instance node as their parent, so an action node inside an instanced bar is covered
by that bar, and one inside an instanced non-bar scene outside any bar is reported at
the HOST file, with the path through the instance. The ROOT node of an instanced scene is not judged on its own
properties inside the host (the host's instance node stands for it).

INHERITANCE. In an inherited scene a node written with no `type=` and no `instance=`
overrides the base scene's node of that path: it keeps the base node's type and
state, and its properties are merged over the base's before it is judged. A base
node's finding is reported in the base file only; the inheriting file reports an
overridden node only when the override changes the outcome.

SCOPE. Static parse of tracked `.tscn` files; nothing is booted. A PASS means the
three rules hold for the nodes the parse could type. An instanced scene that is
missing or cyclic, an instance whose type cannot be resolved, and an unknown class
that sits where a Button would be a finding are censused on the `NOT A FINDING:`
line as UNVERIFIED, never reported and never silently skipped. Zero scanned files,
or zero nodes matching any configured bar/modal/panel type, FAILS.

godot-devkit.toml:
  [ui_layout]
  action_bar_types = ["ActionBar"]       # required
  modal_types = ["Modal"]                # required
  panel_types = ["Panel"]                # optional
  role_property = "ui_role"              # required
  action_roles = ["primary", "destructive", "cancel"]   # required
  include_prefixes = ["ui/"]             # default: the whole repo
  exclude_prefixes = ["addons/"]         # default: vendored trees
  baseline = { "ui/old.tscn" = 2 }       # per-file debt that only shrinks
"""
from __future__ import annotations

import re
from collections import Counter
from typing import NamedTuple

from godot_devkit.core.baseline import read_baseline
from godot_devkit.core.config import ConfigError, config_section, str_tuple, text
from godot_devkit.core.project import git_lines, load_config, repo_root
from godot_devkit.godot import VENDORED_DEFAULT
from godot_devkit.godot.format import classdb
from godot_devkit.godot.format.tscn import (
    Section, ext_index, node_own_path, parse, ref_path, strip_quotes)

CONFIG_SECTION = 'ui_layout'
TAG = '[check:ui-layout]'
EXIT_OK = 0
EXIT_FINDINGS = 1
MAX_LISTED = 40
REQUIRED = ('action_bar_types', 'modal_types', 'role_property', 'action_roles')
RES_PREFIX = 'res://'
CLASS_NAME = re.compile(r'^\s*class_name\s+([A-Za-z_]\w*)', re.MULTILINE)
MAX_DEPTH = 32

OUTSIDE_BAR = 'action-outside-bar'
BUTTON_IN_SCROLL = 'button-in-modal-scroll'
NO_OVERFLOW = 'label-no-overflow'


class State(NamedTuple):
    """What a node's ancestors (and itself, for its children) add up to."""
    in_bar: bool = False
    in_modal: bool = False
    in_panel: bool = False      # under a panel OR a modal
    scroll_in_modal: bool = False


class Settings(NamedTuple):
    bars: tuple[str, ...]
    modals: tuple[str, ...]
    panels: tuple[str, ...]
    role_property: str
    roles: tuple[str, ...]


class Ident(NamedTuple):
    """What a node is: its native `kind` (for the engine class snapshot) and every
    name it can match a configured type by (kind, script class_name, instance root)."""
    kind: str | None = None
    names: frozenset = frozenset()


class Merged:
    """A base node with an inheriting scene's override properties laid over it."""

    def __init__(self, base, over) -> None:
        self.base, self.over = base, over

    def prop(self, key: str):
        found = self.over.prop(key)
        return found if found is not None else self.base.prop(key)


class Scan:
    """One run: the settings, the findings so far, and the census."""

    def __init__(self, root, settings: Settings) -> None:
        self.root = root
        self.cfg = settings
        self.found: list[tuple[str, str]] = []
        self.unverified: Counter = Counter()
        self.matched = 0
        self.classes: dict[str, str | None] = {}

    def load(self, rel: str) -> list[Section] | None:
        try:
            return parse(str(self.root / rel))
        except (OSError, UnicodeDecodeError):
            return None

    def script_class(self, node: Section, ext: dict) -> str | None:
        """The `class_name` declared by the node's script, if it has one."""
        prop = node.prop('script')
        path = ref_path(prop.value, ext) if prop is not None else None
        if path is None or not path.startswith(RES_PREFIX):
            return None
        rel = path[len(RES_PREFIX):]
        if rel not in self.classes:
            try:
                text_ = (self.root / rel).read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                text_ = ''
            match = CLASS_NAME.search(text_)
            self.classes[rel] = match.group(1) if match else None
        return self.classes[rel]

    def instance_target(self, node: Section, ext: dict) -> str | None:
        value = node.attrs.get('instance')
        path = ref_path(value, ext) if value else None
        if path is None or not path.startswith(RES_PREFIX):
            return None
        return path[len(RES_PREFIX):]

    def identify(self, node: Section, ext: dict, seen: frozenset,
                 depth: int = 0) -> Ident:
        """The node's `type=` and script class, plus what its instance chain
        bottoms out at when it has no `type=` of its own."""
        own = self.script_class(node, ext)
        names = {own} if own else set()
        if node.attrs.get('type'):
            return Ident(node.attrs['type'], frozenset(names | {node.attrs['type']}))
        rel = self.instance_target(node, ext)
        if rel is None or rel in seen or depth > MAX_DEPTH:
            return Ident(None, frozenset(names))
        sections = self.load(rel)
        nodes = [s for s in sections or [] if s.kind == 'node']
        if not nodes:
            return Ident(None, frozenset(names))
        inner = self.identify(nodes[0], ext_index(sections), seen | {rel},
                              depth + 1)
        return Ident(inner.kind, inner.names | names)

    def advance(self, state: State, ident: Ident) -> State:
        if ident.kind is None and not ident.names:
            return state
        names = ident.names
        bar = bool(names & set(self.cfg.bars))
        modal = bool(names & set(self.cfg.modals))
        panel = bool(names & set(self.cfg.panels))
        if bar or modal or panel:
            self.matched += 1
        in_modal = state.in_modal or modal
        scroll = classdb.derives_from(ident.kind, 'ScrollContainer') is True
        return State(state.in_bar or bar, in_modal,
                     state.in_panel or modal or panel,
                     state.scroll_in_modal or (in_modal and scroll))

    def verdicts(self, node, kind: str | None, state: State,
                 count: bool = True) -> list[tuple[str, str]]:
        """The three rules applied to one node, given its PARENT's state, as
        (kind, why) pairs. `count=False` leaves the census alone."""
        out: list[tuple[str, str]] = []

        def unverified(reason: str) -> None:
            if count:
                self.unverified[reason] += 1
        role = node.prop(self.cfg.role_property)
        if (role is not None and strip_quotes(role.value) in self.cfg.roles
                and not state.in_bar):
            out.append((OUTSIDE_BAR, f'{self.cfg.role_property} = {role.value} '
                        f'sits in no {"/".join(self.cfg.bars)} ancestor'))
        if state.scroll_in_modal:
            if kind is None:
                unverified('node(s) whose type could not be resolved')
            elif classdb.derives_from(kind, 'Button'):
                out.append((BUTTON_IN_SCROLL, f'{kind} inside a ScrollContainer of a '
                            f'{"/".join(self.cfg.modals)}; pin it in the action bar'))
            elif classdb.derives_from(kind, 'Button') is None:
                unverified('unknown class(es) under a modal scroll')
        if kind == 'Label' and state.in_panel and not _covered(node):
            out.append((NO_OVERFLOW,
                        'sets neither autowrap_mode nor text_overrun_behavior'))
        return out

    def line(self, host: str, where: str, verdict: tuple[str, str]) -> tuple[str, str]:
        return host, f'  {verdict[0]}  {host} : {where} — {verdict[1]}'

    def judge(self, host: str, where: str, node, kind: str | None,
              state: State) -> None:
        for verdict in self.verdicts(node, kind, state):
            self.found.append(self.line(host, where, verdict))

    def rejudge(self, host: str, where: str, base, merged, kind: str | None,
                state: State, base_muted: bool) -> None:
        """An override node: judge the merged properties. A base finding the
        override leaves unchanged belongs to the base file, so only a changed
        outcome is reported here; when the base was not muted (inside a host),
        its stale line is replaced."""
        before = self.verdicts(base, kind, state, count=False)
        after = self.verdicts(merged, kind, state, count=True)
        if base_muted:
            after = [v for v in after if v not in before]
        else:
            for verdict in before:
                try:
                    self.found.remove(self.line(host, where, verdict))
                except ValueError:
                    pass
        for verdict in after:
            self.found.append(self.line(host, where, verdict))

    def place(self, host: str, rel: str, prefix: str, entry: State,
              seen: frozenset, muted: bool = False,
              reg: dict | None = None) -> dict[str, State] | None:
        """Judge scene `rel` placed at `prefix` in `host`. Returns, per node path,
        the state its children inherit (the root `.` included). `muted` places a
        base scene whose own findings belong to its own file; `reg` carries
        {path: (node, ident)} from a base scene to the scene inheriting it."""
        sections = self.load(rel)
        if sections is None:
            self.unverified['instanced scene(s) missing or unreadable'] += 1
            return None
        ext = ext_index(sections)
        states: dict[str, State] = {}
        reg = {} if reg is None else reg
        for node in (s for s in sections if s.kind == 'node'):
            path, parent = node_own_path(node), node.attrs.get('parent')
            is_root = parent is None
            above = entry if is_root else states.get(parent)
            if above is None:
                self.unverified['node(s) whose parent could not be placed'] += 1
                above = entry
            where = prefix if is_root and prefix else (
                '.' if is_root else (f'{prefix}/{path}' if prefix else path))
            nested = node.attrs.get('instance')
            if (not is_root and not node.attrs.get('type') and not nested
                    and path in states):
                # An override of an inherited node: keep its type and state.
                if path in reg:
                    base, ident = reg[path]
                    merged = Merged(base, node)
                    if not muted:
                        self.rejudge(host, where, base, merged, ident.kind,
                                     above, base_muted=not prefix)
                    reg[path] = (merged, ident)
                else:
                    self.unverified['override(s) of a node inside an instanced '
                                    'scene'] += 1
                continue
            ident = self.identify(node, ext, seen)
            if ident.kind is None and (nested or is_root):
                self.unverified['instance(s) whose type could not be resolved'] += 1
            if is_root and nested and not node.attrs.get('type'):
                # An inherited scene: lay the base scene's nodes down first.
                base = self.instance_target(node, ext)
                inner = self._instance(host, base, prefix, entry, seen,
                                       muted or not prefix, reg)
                states.update(inner or {})
            if not (is_root and prefix) and not muted:
                self.judge(host, where, node, ident.kind, above)
            reg[path] = (node, ident)
            after = self.advance(above, ident)
            states[path] = after
            if nested and not is_root:
                target = self.instance_target(node, ext)
                inner = self._instance(host, target, where, after, seen, muted)
                for sub, sub_state in (inner or {}).items():
                    if sub != '.':
                        states[f'{path}/{sub}'] = sub_state
        return states

    def _instance(self, host: str, rel: str | None, where: str, entry: State,
                  seen: frozenset, muted: bool = False,
                  reg: dict | None = None) -> dict[str, State] | None:
        if rel is None or rel in seen or len(seen) > MAX_DEPTH:
            self.unverified['instanced scene(s) missing or cyclic'] += 1
            return None
        return self.place(host, rel, where, entry, seen | {rel}, muted, reg)


def _covered(label) -> bool:
    return any(label.prop(key) is not None
               for key in ('autowrap_mode', 'text_overrun_behavior'))


def _settings(config: dict) -> Settings:
    for key in REQUIRED:
        if key not in config:
            raise ConfigError(f'[{CONFIG_SECTION}] {key} is required — it has '
                              f'no stock default')
    panels = (str_tuple(config, CONFIG_SECTION, 'panel_types', ())
              if 'panel_types' in config else ())
    role = text(config, CONFIG_SECTION, 'role_property', '')
    if not role:
        raise ConfigError(f'[{CONFIG_SECTION}] role_property is empty')
    return Settings(
        str_tuple(config, CONFIG_SECTION, 'action_bar_types', ()),
        str_tuple(config, CONFIG_SECTION, 'modal_types', ()), panels, role,
        str_tuple(config, CONFIG_SECTION, 'action_roles', ()))


def run() -> int:
    if CONFIG_SECTION not in load_config():
        print(f'{TAG} PASS — no [{CONFIG_SECTION}] declared')
        return EXIT_OK
    root = repo_root()
    config = config_section(CONFIG_SECTION)
    settings = _settings(config)
    include = str_tuple(config, CONFIG_SECTION, 'include_prefixes', ())
    exclude = str_tuple(config, CONFIG_SECTION, 'exclude_prefixes',
                        VENDORED_DEFAULT)
    baseline = read_baseline(config, CONFIG_SECTION)

    scan = Scan(root, settings)
    files = 0
    print(f'{TAG} CHECK — action buttons in the action bar, none in a modal '
          f'scroll, labels with an overflow policy')
    for rel in git_lines('ls-files', '*.tscn'):
        if rel.startswith(exclude) or (include and not rel.startswith(include)):
            continue
        files += 1
        scan.place(rel, rel, '', State(), frozenset({rel}))
    judged = baseline.judge(scan.found)
    findings = judged.open
    dirty = len({rel for rel, _ in scan.found if rel not in judged.frozen})

    for line in findings[:MAX_LISTED]:
        print(line)
    if len(findings) > MAX_LISTED:
        print(f'  … and {len(findings) - MAX_LISTED} more')
    judged.report()
    census = ', '.join(f'{count} {reason}'
                       for reason, count in scan.unverified.most_common())
    note = f'  NOT A FINDING: {census or "none"} (UNVERIFIED)'
    if files == 0:
        print(f'{TAG} FAIL — scanned 0 files; check [{CONFIG_SECTION}] '
              f'include_prefixes / exclude_prefixes')
        return EXIT_FINDINGS
    if scan.matched == 0:
        print(f'{TAG} FAIL — {files} file(s) scanned but no node matched '
              f'action_bar_types, modal_types or panel_types; check their spelling')
        print(note)
        return EXIT_FINDINGS
    if findings:
        print(f'{TAG} FAIL — {len(findings)} finding(s) in {dirty} of {files} '
              f'.tscn file(s)')
        print(note)
        return EXIT_FINDINGS
    if judged.failed:
        print(judged.verdict(TAG, f'{files} .tscn file(s)'))
        print(note)
        return EXIT_FINDINGS
    print(f'{TAG} PASS — no ui-layout finding in {files} .tscn file(s)')
    print(note)
    return EXIT_OK
