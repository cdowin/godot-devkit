"""test_boundaries.py — the package's layering, enforced by AST rather than by memory.

A day of review found ~25 defects in this package that were three bugs in
eighteen places: something silently leaves a census (~6x), and a write is not
all-or-nothing (~6x). `core/walk.py` and `core/apply.py` make each shape
impossible to express; THIS FILE makes them impossible to route around, as
exact module ALLOWLISTS — a new gate that enumerates directly, or a new verb
that writes directly, breaks the build and is named by `file:line`. The same
walk holds the import layering (`core/` knows nothing of `godot/`; inside
`godot/` a layer imports downward, never up) and the one door every config
VALUE comes through: a raw config read is importable only by an allowlisted
module, each of which routes every value through `core/config.py`'s guards —
`tuple(cfg.get(...))` over a bare string is ('a','d','d','o','n','s','/'), the
shape that shipped seven silently empty censuses in v0.9.0.

Deliberately AST, not grep: a string `'rglob'` in a docstring is not a call,
and `str.replace` is the same syntax as `Path.replace` — told apart by ARITY,
the only honest way from an AST. Every scan goes through `_sources()`, whose
floor is what keeps an empty allowlist from passing over an empty tree (rule 4).
"""
from __future__ import annotations

import ast
import unittest

from support import REPO_ROOT

SRC = REPO_ROOT / 'src' / 'godot_devkit'
# --- primitive 1: one walk. The exact module that owns filesystem ENUMERATION.
WALK_MODULE = 'core/walk.py'
# --- primitive 2: one apply. Path methods that mutate and cannot be anything
# else at the syntax level; `.replace()` is absent on purpose (see `_mutation_sites`).
APPLY_MODULE = 'core/apply.py'
PATH_MUTATORS = ('write_text', 'write_bytes', 'unlink', 'rmdir', 'mkdir',
                 'rename', 'touch', 'symlink_to', 'hardlink_to', 'chmod')
MODULE_MUTATORS = {
    'os': ('rename', 'replace', 'remove', 'unlink', 'rmdir', 'mkdir',
           'makedirs', 'removedirs', 'symlink', 'link', 'truncate', 'chmod'),
    'shutil': ('rmtree', 'copy', 'copy2', 'copyfile', 'copytree', 'move'),
}
# --- primitive 3: import layering, `godot/` bottom-up. A module may import a
# layer at or below its own; `core/` may import nothing from `godot/` at all.
LAYERS = ('format', 'index', 'read', 'write', 'checks')
# --- primitive 4: the modules that may import `config_section`/`load_config`.
# A file joins this list when the reviewer has checked every value it reads
# crosses a `core/config.py` guard (`str_tuple` & co).
CONFIG_IMPORT_ALLOWLIST = frozenset((
    'core/config.py', 'cli.py',
    'godot/checks/defaults.py', 'godot/checks/props.py', 'godot/checks/rng.py',
    'godot/checks/test_shape.py', 'godot/checks/tres.py', 'godot/checks/tres_comment.py',
    'godot/checks/uid.py', 'godot/checks/unit_disk.py',
    'godot/read/autoloads.py', 'godot/read/orphans.py', 'godot/read/refs.py',
))


# (module-relative posix path, tree) for every shipped module — enumerated
# through `core.walk`, because a test that hand-rolled its own `rglob` to police
# `rglob` would be the joke that writes itself. The census floor sits here, where
# every scan goes through: well under the real count (~48), well over the zero a
# moved SRC produces.
def _sources() -> list[tuple[str, ast.Module]]:
    from godot_devkit.core import walk
    found = walk.descendants(SRC, walk.Kind.FILE, suffix='.py')
    out = [(p.relative_to(SRC).as_posix(), ast.parse(p.read_text(encoding='utf-8')))
           for p in found.kept]
    assert len(out) >= 20, f'{len(out)} shipped module(s) under {SRC}: the allowlists ' \
                           'below assert an EMPTY offender list, so this passes while checking nothing'
    return out


# (call node, callee name, receiver): `x.f()` gives ('f', 'x'), `expr.f()` gives
# ('f', ''), a bare `f()` gives ('f', None).
def _call_names(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                yield node, func.attr, func.value.id if isinstance(func.value, ast.Name) else ''
            elif isinstance(func, ast.Name):
                yield node, func.id, None


# The mode MOVES with the spelling: `p.open('w')` puts it where `open(p, 'w')`
# puts the path. Reading `args[1]` for both was this gate's blind spot — every
# `p.open('w')` in `src/` classified as a read and passed. `mode=` wins over the
# slot, an absent mode reads, and an UNREADABLE mode is a write: a guard that
# cannot read the mode refuses rather than waves through (rule 4).
def _is_write_open(node: ast.Call) -> bool:
    index = 0 if isinstance(node.func, ast.Attribute) else 1
    mode = node.args[index] if len(node.args) > index else None
    mode = next((kw.value for kw in node.keywords if kw.arg == 'mode'), mode)
    if mode is None:
        return False
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return True
    return any(ch in mode.value for ch in ('w', 'a', 'x', '+'))


def _enumeration_sites(rel: str, tree: ast.Module) -> list[str]:
    # A bare `walk()`/`glob()` is usually a local helper; a bare `scandir`/`listdir`
    # never is. `ast.walk` and this package's own `walk.walk` are not filesystem walks.
    return [f'{rel}:{node.lineno}: {name}()' for node, name, receiver in _call_names(tree)
            if name in ('glob', 'rglob', 'iterdir', 'walk', 'scandir', 'listdir')
            and (receiver is not None or name in ('scandir', 'listdir'))
            and receiver not in ('ast', 'walk')]


def _mutation_sites(rel: str, tree: ast.Module) -> list[str]:
    out = []
    for node, name, receiver in _call_names(tree):
        # `str.replace` needs at least TWO arguments, so a one-argument
        # `.replace(target)` can only be `Path.replace` — a syntactic fact.
        if (name in MODULE_MUTATORS.get(receiver, ())
                or (receiver is not None and name in PATH_MUTATORS)
                or (receiver is not None and name == 'replace'
                    and len(node.args) == 1 and not node.keywords)
                or (name == 'open' and _is_write_open(node))):
            out.append(f'{rel}:{node.lineno}: {name}()')
    return out


# (dotted import source, lineno) for every import. A relative import is resolved
# against the module's own package, so `from ..godot import x` cannot dodge the
# layering by spelling the target without its prefix.
def _imports(rel: str, tree: ast.Module) -> list[tuple[str, int]]:
    package = ['godot_devkit'] + rel.split('/')[:-1]
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else []
            module = '.'.join(base + ([node.module] if node.module else []))
            out.extend((f'{module}.{alias.name}', node.lineno) for alias in node.names)
    return out


class OneWalkOneApply(unittest.TestCase):
    # PRIMITIVES 1 and 2. The owning module must really do the thing, or every
    # offender could move somewhere else and the allowlist would still pass.
    def test_only_the_walk_module_enumerates_and_only_the_apply_module_writes(self):
        offenders: list[str] = []
        for rel, tree in _sources():
            if rel == WALK_MODULE:
                self.assertGreaterEqual(len(_enumeration_sites(rel, tree)), 4)
            else:
                offenders.extend(f'enumerates outside {WALK_MODULE}: {site}'
                                 for site in _enumeration_sites(rel, tree))
            if rel == APPLY_MODULE:
                self.assertGreaterEqual(len(_mutation_sites(rel, tree)), 4)
            else:
                offenders.extend(f'mutates outside {APPLY_MODULE}: {site}'
                                 for site in _mutation_sites(rel, tree))
        self.assertEqual([], offenders, (
            'A walk that returns one list has nowhere to put what it dropped; a '
            'writer that decides as it goes lands half a plan when step three '
            'refuses. Route it through `core.walk` / `core.apply`:\n  ' + '\n  '.join(offenders)))

    # PRIMITIVE 1, the other half. `len(walk)` would answer for the KEPT half
    # alone, with everything the walk skipped silently gone — rule 4's first sin
    # in a single call, which is why the dataclass refuses instead of answering.
    # Nothing else in this suite reddens when that refusal is deleted.
    def test_a_walk_refuses_len_and_names_the_remedy(self):
        from godot_devkit.core import walk
        found = walk.Walk(kept=(SRC / 'a.py',),
                          skipped=(walk.Skip(SRC / 'b.py', walk.SkipReason.EXCLUDED_PATH),))
        with self.assertRaises(TypeError) as refusal:
            len(found)
        self.assertIn('.census(', str(refusal.exception))
        # The halves themselves still measure — the refusal is on the whole.
        self.assertEqual((1, 1), (len(found.kept), len(found.skipped)))

    def test_every_spelling_of_open_is_classified_by_its_real_mode(self):
        # Both spellings, every mode slot, and the unreadable mode — the whole
        # of the defect `_is_write_open` exists to hold shut.
        for source, is_write in (
                ("p.open('w')", True), ("p.open(mode='w')", True), ("Path(x).open('a')", True),
                ("p.open('x')", True), ("p.open('r+')", True), ("p.open('ab')", True),
                ("p.open('a', encoding='utf-8', newline='\\n')", True),
                ("p.open()", False), ("p.open('r')", False), ("p.open('rb')", False),
                ("p.open(encoding='utf-8')", False),
                ("open(p, 'w')", True), ("open(p, mode='w')", True), ("open(p, 'x')", True),
                ("open(p, 'r+')", True), ("open(p, 'ab')", True),
                ("open(p)", False), ("open(p, 'r')", False), ("open(p, 'rb')", False),
                ("open(p, encoding='utf-8')", False),
                ("open(p, mode)", True), ("p.open(mode)", True)):
            with self.subTest(source=source):
                self.assertEqual(is_write, bool(_mutation_sites('scratch.py', ast.parse(source))))


class Imports(unittest.TestCase):
    # PRIMITIVE 3.
    def test_core_imports_no_godot_and_each_layer_imports_only_downward(self):
        offenders: list[str] = []
        internal = 0
        for rel, tree in _sources():
            own = rel.split('/')
            rank = LAYERS.index(own[1]) if own[0] == 'godot' and own[1] in LAYERS else None
            for source, lineno in _imports(rel, tree):
                parts = source.split('.')
                if parts[0] != 'godot_devkit':
                    continue
                internal += 1
                target = parts[2] if parts[1:2] == ['godot'] and parts[2:3] else None
                if own[0] == 'core' and parts[1:2] == ['godot']:
                    offenders.append(f'{rel}:{lineno}: core/ imports {source}')
                elif rank is not None and target in LAYERS and LAYERS.index(target) > rank:
                    offenders.append(f'{rel}:{lineno}: {own[1]}/ imports {target}/ (upward)')
        self.assertEqual([], offenders, 'a layer imports upward — see CLAUDE.md § Where '
                         'things live:\n  ' + '\n  '.join(offenders))
        self.assertGreaterEqual(internal, 50, 'package-internal import census collapsed')

    # PRIMITIVE 4.
    def test_raw_config_imports_are_allowlisted(self):
        reads = {rel: [(source, lineno) for source, lineno in _imports(rel, tree)
                       if source.startswith('godot_devkit.core.')
                       and source.rsplit('.', 1)[-1] in ('config_section', 'load_config')]
                 for rel, tree in _sources()}
        self.assertEqual([], sorted(CONFIG_IMPORT_ALLOWLIST - reads.keys()),
                         'allowlisted module(s) that no longer exist — an entry nothing '
                         'can match is a hole waiting for a file to move into it')
        offenders = [f'{rel}:{lineno}: imports {source}' for rel, hits in reads.items()
                     if rel not in CONFIG_IMPORT_ALLOWLIST for source, lineno in hits]
        self.assertEqual([], offenders, (
            'a raw config read imported outside the allowlist. Config comes in through '
            'the guards in core/config.py (`str_tuple` & co) — a bare `cfg.get` hands '
            'back whatever TOML holds, and a string is iterable:\n  ' + '\n  '.join(offenders)))
        # Not vacuous: most of the allowlist really does import a config read today.
        self.assertGreaterEqual(sum(bool(hits) for hits in reads.values()), 10)


if __name__ == '__main__':
    unittest.main()
