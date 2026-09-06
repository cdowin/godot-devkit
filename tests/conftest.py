"""`shell` is derived here — from the source, at collection, never by hand.

`make matrix` replays this suite on four interpreters, and ~85% of that wall
clock is `subprocess`: bash, make, git and the installed hook corpora, none of
which an interpreter changes. The matrix runs everything on the floor and
`-m "not shell"` on the other three, so the mark has to be true of every
spawning module on every run, with nobody maintaining a list. Hence derivation.

A module carries `shell` when its own source imports `subprocess`, or when it
binds a `tests/support` name that reaches `subprocess`. The helper set is
derived too — support's call graph walked to a fixpoint — so `commit()` counts
because it calls `git()`, and a new helper that shells out drags its callers
across on the next collection rather than on the next audit.

Deliberately AST, not grep. `grep -l subprocess tests/test_*.py` gets both ends
of the census wrong: it counts `test_boundaries.py`, which spells
`subprocess.run` in a docstring and spawns nothing, and it misses every module
that shells out only through `temp_repo()` or `tree()` — which is most of the
pm suite, and the bulk of the seconds this mark exists to move.

The mark is a fact, so no module gets to assert it: an item that reaches this
hook already carrying `shell` is refused by name. That holds even when the
claim is TRUE, because one mechanism is the whole point — `pytest -m shell`
should be a statement about what the source does, and a reader should never
have to work out whether a given mark was derived or opined.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

MARK = 'shell'
SPAWN_MODULE = 'subprocess'
TESTS = Path(__file__).resolve().parent
SUPPORT = TESTS / 'support'


def _rel(path: Path) -> str:
    """`tests/test_x.py` for a file in this repo; the full path for anything else."""
    try:
        return str(path.relative_to(TESTS.parent))
    except ValueError:
        return str(path)


def _touches_subprocess(node: ast.AST) -> bool:
    """Does anything under `node` reach through the `subprocess` module?

    An attribute off the name, so `subprocess.run(...)` and `subprocess.Popen`
    both count and the string `'subprocess'` in a docstring does not.
    """
    return any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
               and n.value.id == SPAWN_MODULE
               for n in ast.walk(node))


def _called_names(node: ast.AST) -> set[str]:
    """Every name called under `node`, bare (`git(...)`) or attributed (`x.git(...)`)."""
    called: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                called.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                called.add(n.func.attr)
    return called


def _assigned_names(stmt: ast.stmt) -> set[str]:
    """The module-level names a top-level assignment binds."""
    if isinstance(stmt, ast.Assign):
        return {t.id for t in stmt.targets if isinstance(t, ast.Name)}
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return {stmt.target.id}
    return set()


def _attribute_root(node: ast.Attribute) -> str | None:
    """`support` for `support.pm.tree`; None when the chain is not rooted in a name."""
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


@functools.cache
def support_spawn_names() -> frozenset[str]:
    """Every name importable from `tests/support` whose use means a spawn.

    Three passes over the package. Each function's own body first: a
    `subprocess.<anything>` under it spawns. Then a fixpoint over the call
    graph, so `commit` joins `git` and a future wrapper of either joins on the
    collection after it is written. Then import time: a support module whose
    module-level code spawns promotes its own name and everything it defines,
    because importing it IS the spawn and the caller never names a helper.

    The graph is keyed by bare function name across the whole package, which
    over-approximates if two support modules ever define the same name.
    Over-marking costs one module its skip on three interpreters; under-marking
    costs the matrix a silent hole. The over-approximation is the safe side.
    """
    graph: dict[str, set[str]] = {}
    spawns: set[str] = set()
    defines: dict[str, set[str]] = {}
    module_level: dict[str, list[ast.stmt]] = {}
    for path in sorted(SUPPORT.glob('*.py')):
        module = SUPPORT.name if path.stem == '__init__' else path.stem
        defined = defines.setdefault(module, set())
        body = module_level.setdefault(module, [])
        for stmt in ast.parse(path.read_text(encoding='utf-8')).body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(stmt.name)
                graph[stmt.name] = _called_names(stmt)
                if _touches_subprocess(stmt):
                    spawns.add(stmt.name)
            else:
                if isinstance(stmt, ast.ClassDef):
                    defined.add(stmt.name)
                defined |= _assigned_names(stmt)
                body.append(stmt)
    changed = True
    while changed:
        changed = False
        for function, called in graph.items():
            if function not in spawns and called & spawns:
                spawns.add(function)
                changed = True
    for module, body in module_level.items():
        if any(_touches_subprocess(s) or (_called_names(s) & spawns) for s in body):
            spawns |= defines[module] | {module}
    return frozenset(spawns)


@functools.cache
def module_spawns(path: Path) -> bool:
    """Does this test module's source spawn a process?

    Not a guess about runtime: the two ways a module in this suite can reach a
    spawn are importing `subprocess` and binding a `tests/support` name that
    does. Source is read once per module and cached — pytest asks per item, and
    a file does not change under a running session.
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    bound: set[str] = set()
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split('.')
                if parts[0] == SPAWN_MODULE:
                    return True
                if SUPPORT.name not in parts:
                    continue
                # `import support` binds `support`; `import support.pm as sp`
                # binds `sp`. Either way the bound name and the module's own
                # name both matter, for an import-time spawner.
                aliases.add(alias.asname or parts[0])
                bound |= {alias.asname or parts[0], parts[-1]}
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or '').split('.')
            if parts[0] == SPAWN_MODULE:
                return True
            if SUPPORT.name not in parts:
                continue
            for alias in node.names:
                bound.add(alias.name)
                if (SUPPORT / f'{alias.name}.py').exists():
                    aliases.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _attribute_root(node) in aliases:
            bound.add(node.attr)
    return bool(bound & support_spawn_names())


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    """Apply the derived mark, and refuse a hand-written one by name.

    `tryfirst`, because pytest's own `-m` filtering is a
    `pytest_collection_modifyitems` too: the mark has to be on the items before
    the expression is evaluated, or `-m shell` selects nothing.
    """
    hand_applied = sorted({_rel(item.path) for item in items
                           if item.get_closest_marker(MARK)})
    if hand_applied:
        raise pytest.UsageError(
            f'hand-applied `{MARK}` mark in: {", ".join(hand_applied)}. '
            f'`{MARK}` is DERIVED in tests/conftest.py from what the module '
            f'source does — it imports `{SPAWN_MODULE}`, or it uses a '
            'tests/support helper that spawns. Delete the mark: if the module '
            'really shells out the mark is already there, and if it does not, '
            'the mark is a claim the source does not support.')
    for item in items:
        if module_spawns(item.path):
            item.add_marker(MARK)
