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
                         neither `autowrap_mode` nor `text_overrun_behavior`. Theme
                         coverage is deliberately simple: a Label is covered when its
                         own `theme_type_variation` is non-empty or it sets `theme`.
                         Theme files are NOT parsed.

TYPE MATCHING. A node matches a configured type when its `type=` equals the entry,
or, for an instanced node (`instance=ExtResource(..)`), the instanced scene's ROOT
type does, following the root's own `instance=` chain (an inherited scene's root has
`instance=` and no `type=`). Nodes inside an instanced scene are judged with the
instance node as their parent, so an action node inside an instanced bar is covered
by that bar, and one inside an instanced non-bar scene outside any bar is reported at
the HOST file, with the path through the instance. Matching by script `class_name`
is NOT implemented. The ROOT node of an instanced scene is not judged on its own
properties inside the host (the host's instance node stands for it).

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


class Scan:
    """One run: the settings, the findings so far, and the census."""

    def __init__(self, root, settings: Settings) -> None:
        self.root = root
        self.cfg = settings
        self.found: list[tuple[str, str]] = []
        self.unverified: Counter = Counter()
        self.matched = 0

    def load(self, rel: str) -> list[Section] | None:
        try:
            return parse(str(self.root / rel))
        except (OSError, UnicodeDecodeError):
            return None

    def instance_target(self, node: Section, ext: dict) -> str | None:
        value = node.attrs.get('instance')
        path = ref_path(value, ext) if value else None
        if path is None or not path.startswith(RES_PREFIX):
            return None
        return path[len(RES_PREFIX):]

    def effective_type(self, node: Section, ext: dict, seen: frozenset,
                       depth: int = 0) -> str | None:
        """The node's `type=`, or the type its instance chain bottoms out at."""
        if node.attrs.get('type'):
            return node.attrs['type']
        rel = self.instance_target(node, ext)
        if rel is None or rel in seen or depth > MAX_DEPTH:
            return None
        sections = self.load(rel)
        nodes = [s for s in sections or [] if s.kind == 'node']
        if not nodes:
            return None
        return self.effective_type(nodes[0], ext_index(sections), seen | {rel},
                                   depth + 1)

    def advance(self, state: State, kind: str | None) -> State:
        if kind is None:
            return state
        bar, modal = kind in self.cfg.bars, kind in self.cfg.modals
        panel = kind in self.cfg.panels
        if bar or modal or panel:
            self.matched += 1
        in_modal = state.in_modal or modal
        scroll = classdb.derives_from(kind, 'ScrollContainer') is True
        return State(state.in_bar or bar, in_modal,
                     state.in_panel or modal or panel,
                     state.scroll_in_modal or (in_modal and scroll))

    def judge(self, host: str, where: str, node: Section, kind: str | None,
              state: State) -> None:
        """Apply the three rules to one node, given its PARENT's state."""
        def add(label: str, why: str) -> None:
            self.found.append((host, f'  {label}  {host} : {where} — {why}'))
        role = node.prop(self.cfg.role_property)
        if (role is not None and strip_quotes(role.value) in self.cfg.roles
                and not state.in_bar):
            add(OUTSIDE_BAR, f'{self.cfg.role_property} = {role.value} '
                f'sits in no {"/".join(self.cfg.bars)} ancestor')
        if state.scroll_in_modal:
            if kind is None:
                self.unverified['node(s) whose type could not be resolved'] += 1
            elif classdb.derives_from(kind, 'Button'):
                add(BUTTON_IN_SCROLL, f'{kind} inside a ScrollContainer of a '
                    f'{"/".join(self.cfg.modals)}; pin it in the action bar')
            elif classdb.derives_from(kind, 'Button') is None:
                self.unverified[f'unknown class(es) under a modal scroll'] += 1
        if kind == 'Label' and state.in_panel and not _covered(node):
            add(NO_OVERFLOW, 'sets neither autowrap_mode nor text_overrun_behavior')

    def place(self, host: str, rel: str, prefix: str, entry: State,
             seen: frozenset) -> dict[str, State] | None:
        """Judge scene `rel` placed at `prefix` in `host`. Returns, per node path,
        the state its children inherit (the root `.` included)."""
        sections = self.load(rel)
        if sections is None:
            self.unverified['instanced scene(s) missing or unreadable'] += 1
            return None
        ext = ext_index(sections)
        states: dict[str, State] = {}
        for node in (s for s in sections if s.kind == 'node'):
            path, parent = node_own_path(node), node.attrs.get('parent')
            is_root = parent is None
            above = entry if is_root else states.get(parent)
            if above is None:
                self.unverified['node(s) whose parent could not be placed'] += 1
                above = entry
            kind = self.effective_type(node, ext, seen)
            if kind is None and (node.attrs.get('instance') or is_root):
                self.unverified['instance(s) whose type could not be resolved'] += 1
            where = prefix if is_root and prefix else (
                '.' if is_root else (f'{prefix}/{path}' if prefix else path))
            nested = node.attrs.get('instance')
            if is_root and 'instance' in node.attrs and not node.attrs.get('type'):
                # An inherited scene: lay the base scene's nodes down first.
                base = self.instance_target(node, ext)
                inner = self._instance(host, base, prefix, entry, seen)
                states.update(inner or {})
            if not (is_root and prefix):
                self.judge(host, where, node, kind, above)
            after = self.advance(above, kind)
            states[path] = after
            if nested and not is_root:
                target = self.instance_target(node, ext)
                inner = self._instance(host, target, where, after, seen)
                for sub, sub_state in (inner or {}).items():
                    if sub != '.':
                        states[f'{path}/{sub}'] = sub_state
        return states

    def _instance(self, host: str, rel: str | None, where: str, entry: State,
                  seen: frozenset) -> dict[str, State] | None:
        if rel is None or rel in seen or len(seen) > MAX_DEPTH:
            self.unverified['instanced scene(s) missing or cyclic'] += 1
            return None
        return self.place(host, rel, where, entry, seen | {rel})


def _covered(label: Section) -> bool:
    for key in ('autowrap_mode', 'text_overrun_behavior', 'theme'):
        if label.prop(key) is not None:
            return True
    variation = label.prop('theme_type_variation')
    return variation is not None and strip_quotes(variation.value) != ''


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
