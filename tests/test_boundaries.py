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
    'godot/checks/canonical.py',
    'godot/checks/defaults.py', 'godot/checks/props.py', 'godot/checks/rng.py',
    'godot/checks/test_shape.py', 'godot/checks/tres.py', 'godot/checks/tres_comment.py',
    'godot/checks/uid.py', 'godot/checks/unit_disk.py',
    'godot/read/autoloads.py', 'godot/read/orphans.py', 'godot/read/refs.py',
))


# (module-relative posix path, tree) for every shipped module — enumerated
# through `core.walk`, because a test that hand-rolled its own `rglob` to police
# `rglob` would be the joke that writes itself. The census floor sits here, where
# every scan goes through: well under the real count (41 since the repo family
# left in 0.25.0), well over the zero a moved SRC produces.
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
                # ONE enumerator since 0.25.0's review took `entries`,
                # `children`, `matching` and `named` out — every one of them
                # dead in src/ and tests/ once the repo family left. The floor
                # is what stops the allowlist below from passing vacuously: if
                # `descendants` stopped enumerating, every offender could move
                # anywhere and this would still be green.
                self.assertGreaterEqual(len(_enumeration_sites(rel, tree)), 1)
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

    # PRIMITIVE 1, the third half — the rule `core/walk.py`'s own docstring
    # promises. Until 0.25.0's review it did not exist, and both surviving
    # callers ended `list(found.kept)`: the skipped half dropped on the floor,
    # which is how `refs` came to print "(no references found)" over a census
    # of zero. Reaching for the kept half is how a renderer gets a number
    # without what the number left out — iterate the Walk, or ask `census()`.
    # AST, not grep: the two callers still SAY `found.kept` in their docstrings.
    def test_no_module_reaches_for_a_walks_kept_half(self):
        offenders = [f'{rel}:{node.lineno}'
                     for rel, tree in _sources() if rel != WALK_MODULE
                     for node in ast.walk(tree)
                     if isinstance(node, ast.Attribute) and node.attr == 'kept']
        self.assertEqual([], offenders, (
            "a Walk's kept half, reached outside core/walk.py. Iterate the Walk "
            '(`list(found)`) for the paths, or `found.census(label)` for a number '
            'that carries what it left out:\n  ' + '\n  '.join(offenders)))

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


class ConfigValuesCrossTheGuards(unittest.TestCase):
    # PRIMITIVE 4, the other half. `Imports` proves a raw config read is only
    # IMPORTED by an allowlisted module; this proves the guards those modules
    # call actually refuse. 0.25.0's review found two of them — `str_tuple`'s
    # empty-list refusal and `text()`'s non-string refusal — asserted by
    # nothing: their only cases lived in `test_pm_gate.py` / `test_gates_extra.py`,
    # repo-family modules deleted in 621970e, and `core/config.py` did not
    # leave with the family. Disarming either left the whole suite green while
    # `[unit_disk] roots = []` silently scanned the entire repo and PASSed.
    #
    # Each gate reaches only the readers its own one config case happens to
    # use, so the door is asked here instead, at the altitude it lives at: a
    # dict and a call, no temp tree and no process.
    def test_every_guard_refuses_the_value_that_would_mean_its_reverse(self):
        from godot_devkit.core import config
        # (label, callable, section dict, fragment the refusal must name)
        rows = (
            ('str_tuple bare string', lambda c: c.str_tuple({'k': 'addons/'}, 's', 'k', ('d',)),
             'must be a list of strings'),
            ('str_tuple empty list', lambda c: c.str_tuple({'k': []}, 's', 'k', ('d',)),
             'is empty — remove the key'),
            ('str_tuple non-string member', lambda c: c.str_tuple({'k': ['a', 3]}, 's', 'k', ('d',)),
             'must be a list of strings'),
            ('text non-string', lambda c: c.text({'k': 17}, 's', 'k', 'd'),
             'must be a string'),
            ('flag non-bool', lambda c: c.flag({'k': 'yes'}, 's', 'k', False),
             'must be true/false'),
            ('table non-table', lambda c: c.table({'k': ['a']}, 's', 'k', {}),
             'must be a table'),
            ('str_tuple_table non-table', lambda c: c.str_tuple_table({'k': 'a'}, 's', 'k', {}),
             'must be a table'),
            ('number_table non-table', lambda c: c.number_table({'k': 'a'}, 's', 'k', {}),
             'must be a table'),
            ('pattern bad regex', lambda c: c.pattern({'k': '('}, 's', 'k', 'd'),
             'is not a valid regex'),
            ('number non-integer', lambda c: c.number({'k': 'a'}, 's', 'k', 1),
             'must be an integer'),
        )
        for label, call, fragment in rows:
            with self.subTest(guard=label):
                with self.assertRaises(config.ConfigError) as refusal:
                    call(config)
                self.assertIn(fragment, str(refusal.exception))

    def test_an_absent_key_takes_the_fallback_rather_than_refusing(self):
        # The other direction, and the reason the guards cannot simply refuse
        # everything: rule 5 — a repo with no devkit.toml behaves identically
        # to one declaring the defaults.
        from godot_devkit.core import config
        self.assertEqual(('d',), config.str_tuple({}, 's', 'k', ('d',)))
        self.assertEqual('d', config.text({}, 's', 'k', 'd'))
        self.assertIs(False, config.flag({}, 's', 'k', False))
        self.assertEqual(1, config.number({}, 's', 'k', 1))


# --- the README's `devkit.toml` block against the keys the readers accept.
# A consumer copies that block before writing config; a key absent from it is
# guessed at, and `[unit_disk] forbidden_literals` — a TABLE beside a LIST-shaped
# `exclude_prefixes` — was guessed as a list by the first consumer to need it.
README = REPO_ROOT / 'README.md'
CONFIG_HEADING = '## Configuration'
CONFIG_FENCE = '```toml'
CONFIG_MODULE = 'core/config.py'
# A keyed guard reads `(sect, name, key, fallback)`; `config_section(name)` is
# the table read and has no key. Derived from the signature, so a new guard
# joins the census without an edit here.
READER_PARAMS = ['sect', 'name', 'key']
# Floors under the census (rule 4): 8 guards and 28 keys today.
MIN_READERS = 8
MIN_KEYS = 20
# How far a key may be passed down through helper parameters before the scan
# gives up and names the call site as unresolvable.
MAX_RESOLVE_DEPTH = 4


def _config_readers() -> frozenset[str]:
    import inspect
    from godot_devkit.core import config
    return frozenset(
        name for name, fn in vars(config).items()
        if inspect.isfunction(fn) and fn.__module__ == config.__name__
        and list(inspect.signature(fn).parameters)[:len(READER_PARAMS)] == READER_PARAMS)


def _dotted(rel: str) -> str:
    return 'godot_devkit.' + rel[:-len('.py')].replace('/', '.')


class _Module:
    """One parsed module: its string constants, its functions, and every call
    in it paired with the function it sits in."""

    def __init__(self, rel: str, tree: ast.Module):
        self.rel, self.dotted = rel, _dotted(rel)
        self.constants = {t.id: node.value.value for node in tree.body
                          if isinstance(node, ast.Assign)
                          and isinstance(node.value, ast.Constant)
                          and isinstance(node.value.value, str)
                          for t in node.targets if isinstance(t, ast.Name)}
        # local name -> dotted source, for every `from x import y [as z]`; a
        # relative import resolved against the module's own package, as `_imports` does.
        package = ['godot_devkit'] + rel.split('/')[:-1]
        self.imported: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = package[:len(package) - node.level + 1] if node.level else []
                source = '.'.join(base + ([node.module] if node.module else []))
                self.imported.update({(alias.asname or alias.name): f'{source}.{alias.name}'
                                      for alias in node.names})
        self.calls: list[tuple[ast.Call, ast.FunctionDef | None]] = []
        self._collect(tree, None)

    def _collect(self, node: ast.AST, owner: ast.FunctionDef | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child if isinstance(child, ast.FunctionDef) else owner
            if isinstance(child, ast.Call):
                self.calls.append((child, owner))
            self._collect(child, inner)

    def callee(self, call: ast.Call) -> str | None:
        """The dotted target of a bare-name or `module.name` call, else None."""
        func = call.func
        if isinstance(func, ast.Name):
            return self.imported.get(func.id, f'{self.dotted}.{func.id}')
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return f'{self.imported.get(func.value.id, func.value.id)}.{func.attr}'
        return None


def _argument(call: ast.Call, fn: ast.FunctionDef, param: str) -> ast.expr | None:
    """What `call` binds to `fn`'s `param`: by keyword, by position, or the default."""
    for kw in call.keywords:
        if kw.arg == param:
            return kw.value
    positional = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    if param in positional and positional.index(param) < len(call.args):
        return call.args[positional.index(param)]
    defaults = dict(zip(positional[len(positional) - len(fn.args.defaults):],
                        fn.args.defaults))
    defaults.update({a.arg: d for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults)
                     if d is not None})
    return defaults.get(param)


def _resolve(expr: ast.expr | None, mod: _Module, owner: ast.FunctionDef | None,
             modules: list[_Module], depth: int = 0) -> set[str] | None:
    """Every string `expr` can be: a literal, a module constant, or a parameter
    followed out to each call site that binds it. None when any path is not
    one of those — the census names it rather than skipping it."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if not isinstance(expr, ast.Name) or depth > MAX_RESOLVE_DEPTH:
        return None
    params = set() if owner is None else {
        a.arg for a in (*owner.args.posonlyargs, *owner.args.args, *owner.args.kwonlyargs)}
    if expr.id not in params:
        return {mod.constants[expr.id]} if expr.id in mod.constants else None
    target = f'{mod.dotted}.{owner.name}'
    out: set[str] = set()
    sites = 0
    for caller in modules:
        for call, caller_owner in caller.calls:
            if caller.callee(call) != target:
                continue
            sites += 1
            found = _resolve(_argument(call, owner, expr.id), caller, caller_owner,
                             modules, depth + 1)
            if found is None:
                return None
            out |= found
    return out if sites else None


def _keys_the_readers_accept() -> tuple[dict[tuple[str, str], str], list[str], int]:
    """({(section, key): reader}, unresolvable call sites, readers found)."""
    readers = _config_readers()
    modules = [_Module(rel, tree) for rel, tree in _sources()]
    reader_targets = {f'{_dotted(CONFIG_MODULE)}.{name}': name for name in readers}
    keys: dict[tuple[str, str], str] = {}
    unresolved: list[str] = []
    for mod in modules:
        if mod.rel == CONFIG_MODULE:
            continue
        for call, owner in mod.calls:
            reader = reader_targets.get(mod.callee(call) or '')
            if reader is None:
                continue
            sections = _resolve(call.args[1] if len(call.args) > 1 else None,
                                mod, owner, modules)
            names = _resolve(call.args[2] if len(call.args) > 2 else None,
                             mod, owner, modules)
            if sections is None or names is None:
                unresolved.append(f'{mod.rel}:{call.lineno}: {reader}()')
                continue
            keys.update({(s, k): reader for s in sections for k in names})
    return keys, unresolved, len(readers)


def _readme_config_block() -> dict:
    import tomllib
    text = README.read_text(encoding='utf-8')
    section = text.split(f'\n{CONFIG_HEADING}', 1)[1]
    block = section.split(CONFIG_FENCE + '\n', 1)[1].split('\n```', 1)[0]
    return tomllib.loads(block)


class EveryConfigKeyShowsItsShape(unittest.TestCase):
    # The README block is the only place a consumer looks before writing
    # config. Walk the readers — every guard call in src/, its section and key
    # resolved from the code — and require one example per key, fed back
    # through the SAME guard so the example is of the shape the reader accepts.
    def test_every_key_a_reader_accepts_has_an_example_of_its_shape_in_the_readme(self):
        from godot_devkit.core import config
        keys, unresolved, readers = _keys_the_readers_accept()
        self.assertGreaterEqual(readers, MIN_READERS, 'config guard census collapsed')
        self.assertGreaterEqual(len(keys), MIN_KEYS, 'config key census collapsed')
        self.assertEqual([], unresolved, (
            'a config read whose section or key is not a literal, a module constant '
            'or a parameter bound by one — the census cannot say what it reads:\n  '
            + '\n  '.join(unresolved)))
        doc = _readme_config_block()
        missing, misshapen = [], []
        for (section, key), reader in sorted(keys.items()):
            value = doc.get(section, {})
            if key not in value:
                missing.append(f'[{section}] {key}  ({reader})')
                continue
            try:
                getattr(config, reader)(value, section, key, None)
            except config.ConfigError as err:
                misshapen.append(f'[{section}] {key}: {err}')
        self.assertEqual([], missing, (
            f'key(s) the readers accept with no example in README.md § {CONFIG_HEADING[3:]}'
            " — a consumer guesses a key's shape when there is nothing to copy:\n  "
            + '\n  '.join(missing)))
        self.assertEqual([], misshapen, 'README example(s) their own reader refuses:\n  '
                         + '\n  '.join(misshapen))


if __name__ == '__main__':
    unittest.main()
