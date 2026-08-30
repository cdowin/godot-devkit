"""test_boundaries.py — the two primitives, enforced by AST rather than by memory.

A day of review found ~25 defects in this package that were three bugs in
eighteen places. Two of the three are shapes, not incidents:

  * something silently leaves a census (~6x), and
  * a write is not all-or-nothing (~6x).

Every fix before this file was an INSTANCE — one filter taught to report
itself, one writer given a pre-pass — so the next feature reintroduced the
shape somewhere new. Fixing grain detection literally created a new narrowing
via dotted names, because the fix was a filter and nothing made filters
disclose.

`core/walk.py` makes the first shape impossible to express. THIS FILE makes it
impossible to route around: the test is an exact module ALLOWLIST, not a
pattern, and a new gate that enumerates directly breaks the build and is named
by `file:line`. The second primitive lands next, with its own allowlist here.

Deliberately AST, not grep: `subprocess.run(['git', 'mv', ...])` is not a
`Path.rename`, a string `'rglob'` in a docstring is not a call, and a grep
cannot tell those apart. An AST walk decides from the syntax, with no inference
and nothing to tune.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from support import REPO_ROOT

SRC = REPO_ROOT / 'src' / 'godot_devkit'

# --- primitive 1: one walk ----------------------------------------------------
# The exact module that owns filesystem ENUMERATION. Not a package, not a
# prefix — one file.
WALK_MODULE = 'core/walk.py'
# Attribute calls that ENUMERATE. `Path.walk` is 3.12+, banned here so the two
# spellings of `os.walk` cannot split the ownership between interpreters.
ENUMERATORS = ('glob', 'rglob', 'iterdir', 'walk', 'scandir', 'listdir')
def _sources() -> list[tuple[str, Path]]:
    """(module-relative posix path, file) for every shipped module.

    Enumerated through `core.walk`, because a test that hand-rolled its own
    `rglob` to police `rglob` would be the joke that writes itself.
    """
    from godot_devkit.core import walk as walkmod
    from godot_devkit.core.walk import Kind
    found = walkmod.descendants(SRC, Kind.FILE, suffix='.py')
    return [(p.relative_to(SRC).as_posix(), p) for p in found.kept]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def _calls(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _enumeration_sites(rel: str, tree: ast.Module) -> list[str]:
    out = []
    for node in _calls(tree):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ENUMERATORS:
            # `ast.walk` / `os.walk` / `path.walk` — the receiver decides
            # whether `walk` is an enumeration or this package's own module.
            if func.attr == 'walk' and isinstance(func.value, ast.Name) \
                    and func.value.id in ('ast', 'walk'):
                continue
            out.append(f'{rel}:{node.lineno}: {func.attr}()')
        elif isinstance(func, ast.Name) and func.id in ('scandir', 'listdir'):
            out.append(f'{rel}:{node.lineno}: {func.id}()')
    return out


class OneWalk(unittest.TestCase):
    """PRIMITIVE 1 — filesystem enumeration lives in exactly one module."""

    def test_only_the_walk_module_enumerates(self):
        offenders: list[str] = []
        for rel, path in _sources():
            if rel == WALK_MODULE:
                continue
            offenders.extend(_enumeration_sites(rel, _tree(path)))
        self.assertEqual(
            [], offenders,
            'filesystem enumeration outside ' + WALK_MODULE + '. A walk that '
            'returns one list has nowhere to put what it dropped, which is how '
            'six censuses came to narrow in silence. Route it through '
            '`core.walk`, whose result carries both halves:\n  '
            + '\n  '.join(offenders))

    def test_the_walk_module_does_enumerate(self):
        """The allowlist must not be vacuously satisfiable by a module that
        stopped enumerating — then every offender would move somewhere else and
        the test would still pass."""
        sites = _enumeration_sites(WALK_MODULE, _tree(SRC / WALK_MODULE))
        self.assertGreaterEqual(len(sites), 4, sites)


class WalkHasNoLength(unittest.TestCase):
    """A census must not be able to reach a number without its narrowings.

    `Walk.__len__` raises, and `len(x.kept)` is the way around it — so the way
    around it is a build break too. The counting API is `Walk.census(label)`,
    which renders the number and the disclosures as ONE string.
    """

    def test_len_of_a_walk_half_is_never_taken(self):
        offenders: list[str] = []
        for rel, path in _sources():
            if rel == WALK_MODULE:
                continue
            for node in _calls(_tree(path)):
                if not (isinstance(node.func, ast.Name) and node.func.id == 'len'):
                    continue
                for arg in node.args:
                    if isinstance(arg, ast.Attribute) and arg.attr in ('kept', 'skipped'):
                        offenders.append(f'{rel}:{node.lineno}: len(...{arg.attr})')
        self.assertEqual(
            [], offenders,
            'a count taken off half a Walk. Call `.census(label)` so the number '
            'and what it left out render together:\n  ' + '\n  '.join(offenders))

    def test_len_of_a_walk_raises(self):
        from godot_devkit.core.walk import Walk
        with self.assertRaises(TypeError):
            len(Walk((Path('a'),)))


if __name__ == '__main__':
    unittest.main()
