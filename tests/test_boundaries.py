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

`core/walk.py` and `core/apply.py` make each shape impossible to express. THIS
FILE makes them impossible to route around. Both tests are exact module
ALLOWLISTS, not patterns: a new gate that enumerates directly, or a new verb
that writes directly, breaks the build and is named by `file:line`.

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
# Both allowlists assert an EMPTY offender list, so both pass perfectly on a
# census of zero files — which is what a moved/renamed SRC produces. Rule 4 says
# a gate scanning nothing must say so, and these are gates. The floor is well
# under the real count (48 at the time of writing) and well over zero: it is
# there to catch a broken root, not to track the module count.
MIN_SOURCES = 20

# --- primitive 1: one walk ----------------------------------------------------
# The exact module that owns filesystem ENUMERATION. Not a package, not a
# prefix — one file.
WALK_MODULE = 'core/walk.py'
# Attribute calls that ENUMERATE. `Path.walk` is 3.12+, banned here so the two
# spellings of `os.walk` cannot split the ownership between interpreters.
ENUMERATORS = ('glob', 'rglob', 'iterdir', 'walk', 'scandir', 'listdir')
# --- primitive 2: one apply ---------------------------------------------------
APPLY_MODULE = 'core/apply.py'
# Path methods that mutate and CANNOT be anything else at the syntax level.
# `.replace()` is absent on purpose: `str.replace` is the same syntax, and no
# amount of staring at an AST distinguishes them by name. It is caught by ARITY
# instead — see `_replace_is_a_path_replace`.
PATH_MUTATORS = ('write_text', 'write_bytes', 'unlink', 'rmdir', 'mkdir',
                 'rename', 'touch', 'symlink_to', 'hardlink_to', 'chmod')
# Module-qualified mutators. The receiver is right there in the syntax, so
# these need no disambiguation at all.
MODULE_MUTATORS = {
    'os': ('rename', 'replace', 'remove', 'unlink', 'rmdir', 'mkdir',
           'makedirs', 'removedirs', 'symlink', 'link', 'truncate', 'chmod'),
    'shutil': ('rmtree', 'copy', 'copy2', 'copyfile', 'copytree', 'move'),
}
# Modes that make `open()` a mutation. A read-mode `open()` is not a write and
# stays anybody's to call.
WRITE_MODES = ('w', 'a', 'x', '+')
# Where the mode SITS, per spelling. The builtin carries the path first, so its
# mode is the second argument; the bound method already has the path in the
# receiver, so its mode is the FIRST. Reading `args[1]` for both was this gate's
# blind spot: every `p.open('w')` in `src/` classified as a read and passed.
BUILTIN_OPEN_MODE_ARG = 1
METHOD_OPEN_MODE_ARG = 0
# `mode=` outranks the positional slot in either spelling, because that is what
# Python itself does; an absent mode is a read, because that is the default.
OPEN_MODE_KEYWORD = 'mode'
DEFAULT_OPEN_MODE = 'r'
# The ONE sanctioned writer outside APPLY_MODULE, pinned by PATH **and** MODE
# rather than by a blanket allowlist. `ledger.append_row` opens its file in
# append mode deliberately (0.22.0/ledger decision D1): a read-modify-write
# drops rows when two appenders collide and rewrites the bytes `merge=union`
# depends on nobody rewriting. Append is a different primitive, not a variant of
# overwrite — so a `'w'` in THIS file is still a finding, and an `'a'` in any
# other module is too.
APPEND_ONLY_MODULE = 'repo/pm/ledger.py'
APPEND_MODES = ('a', 'ab')


def _sources() -> list[tuple[str, Path]]:
    """(module-relative posix path, file) for every shipped module.

    Enumerated through `core.walk`, because a test that hand-rolled its own
    `rglob` to police `rglob` would be the joke that writes itself.
    """
    from godot_devkit.core import walk as walkmod
    from godot_devkit.core.walk import Kind
    found = walkmod.descendants(SRC, Kind.FILE, suffix='.py')
    out = [(p.relative_to(SRC).as_posix(), p) for p in found.kept]
    # The census floor, at the one place every caller goes through, so no
    # allowlist can be satisfied by having scanned nothing.
    assert len(out) >= MIN_SOURCES, (
        f'{len(out)} shipped module(s) under {SRC} — expected at least '
        f'{MIN_SOURCES}. The allowlists below assert an EMPTY offender list, '
        f'so a census this small passes them while checking nothing.')
    return out


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def _is_an_open_call(node: ast.Call) -> bool:
    """True for both spellings of `open` — the builtin and the bound method."""
    func = node.func
    return ((isinstance(func, ast.Attribute) and func.attr == 'open')
            or (isinstance(func, ast.Name) and func.id == 'open'))


def _open_mode(node: ast.Call) -> str | None:
    """The literal mode of this `open(...)`, or None when it is not a literal.

    The positional slot depends on the SPELLING: `open(path, 'w')` puts the mode
    where `p.open('w')` puts nothing at all. `mode=` wins over the positional in
    either form, and an absent mode is `DEFAULT_OPEN_MODE` — `open(p)` reads.
    """
    index = (METHOD_OPEN_MODE_ARG if isinstance(node.func, ast.Attribute)
             else BUILTIN_OPEN_MODE_ARG)
    mode: ast.expr | None = node.args[index] if len(node.args) > index else None
    for kw in node.keywords:
        if kw.arg == OPEN_MODE_KEYWORD:
            mode = kw.value
    if mode is None:
        return DEFAULT_OPEN_MODE
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return mode.value
    return None


def _is_write_open(node: ast.Call) -> bool:
    """True when this `open(...)` call names a WRITE mode.

    The mode is a literal in every call in this package. A non-literal mode is
    treated as a write: an unreadable mode is exactly the case a guard must not
    wave through.
    """
    mode = _open_mode(node)
    if mode is None:
        return True
    return any(ch in mode for ch in WRITE_MODES)


def _is_sanctioned_append(rel: str, node: ast.Call) -> bool:
    """True for the one append `APPEND_ONLY_MODULE` is allowed to make.

    By path AND by mode: a `'w'` in that same file is not sanctioned, and an
    `'a'` anywhere else is not either. A non-literal mode (None) matches no
    entry in `APPEND_MODES`, so an unreadable mode cannot buy the exception.
    """
    return rel == APPEND_ONLY_MODULE and _open_mode(node) in APPEND_MODES


def _is_unsanctioned_write_open(rel: str, node: ast.Call) -> bool:
    """A write-mode `open(...)` that is not the ledger's sanctioned append."""
    return _is_write_open(node) and not _is_sanctioned_append(rel, node)


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


def _replace_is_a_path_replace(node: ast.Call) -> bool:
    """True when this `.replace(...)` is `Path.replace`, decided by ARITY.

    `str.replace` needs at least TWO arguments — `s.replace(old)` is a
    TypeError, so it cannot appear in code that runs. `Path.replace(target)`
    takes exactly one. That is a syntactic fact, not a guess about types, and it
    is the only honest way to tell the two apart from an AST.
    """
    return len(node.args) == 1 and not node.keywords


def _mutation_sites(rel: str, tree: ast.Module) -> list[str]:
    out = []
    for node in _calls(tree):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == 'open' and _is_unsanctioned_write_open(rel, node):
                out.append(f'{rel}:{node.lineno}: open(..., write mode)')
            continue
        if not isinstance(func, ast.Attribute):
            continue
        receiver = func.value.id if isinstance(func.value, ast.Name) else None
        if receiver in MODULE_MUTATORS and func.attr in MODULE_MUTATORS[receiver]:
            out.append(f'{rel}:{node.lineno}: {receiver}.{func.attr}()')
        elif func.attr in PATH_MUTATORS:
            out.append(f'{rel}:{node.lineno}: {func.attr}()')
        elif func.attr == 'replace' and _replace_is_a_path_replace(node):
            out.append(f'{rel}:{node.lineno}: replace() (one arg — Path.replace)')
        elif func.attr == 'open' and _is_unsanctioned_write_open(rel, node):
            out.append(f'{rel}:{node.lineno}: .open(..., write mode)')
    return out


class TheCensusIsTheRealTree(unittest.TestCase):
    """Before either allowlist means anything, it has to have scanned the tree."""

    def test_the_source_census_clears_the_floor(self):
        self.assertGreater(len(_sources()), MIN_SOURCES)

    def test_a_moved_SRC_breaks_the_build_instead_of_passing(self):
        import tempfile
        import unittest.mock
        with tempfile.TemporaryDirectory() as empty:
            with unittest.mock.patch(f'{__name__}.SRC', Path(empty)):
                with self.assertRaises(AssertionError):
                    _sources()


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


class OneApply(unittest.TestCase):
    """PRIMITIVE 2 — filesystem mutation lives in exactly one module."""

    def test_only_the_apply_module_writes(self):
        offenders: list[str] = []
        for rel, path in _sources():
            if rel == APPLY_MODULE:
                continue
            offenders.extend(_mutation_sites(rel, _tree(path)))
        self.assertEqual(
            [], offenders,
            'filesystem mutation outside ' + APPLY_MODULE + '. A writer that '
            'decides as it goes lands half a plan when step three refuses, '
            'which is how the scaffolder, install-agents and `pm collapse` each '
            'left a tree neither before nor after. Route it through '
            '`core.apply`, which decides the whole plan and then applies it:\n  '
            + '\n  '.join(offenders))

    def test_the_apply_module_does_write(self):
        sites = _mutation_sites(APPLY_MODULE, _tree(SRC / APPLY_MODULE))
        self.assertGreaterEqual(len(sites), 4, sites)


# Every spelling of `open` the classifier has to get right, as
# (source, is a write). The mode MOVES between argument slots with the
# spelling — `p.open('w')` puts it where `open(p, 'w')` puts the path — and
# that is the whole of the defect this table exists to hold shut. A scratch
# module, not a real one: the gate is being MUTATED here, not observed.
OPEN_SPELLINGS = (
    # bound method — the mode is the FIRST argument.
    ("p.open('w')", True),
    ("p.open(mode='w')", True),
    ("Path(x).open('a')", True),
    ("p.open('x')", True),
    ("p.open('w+')", True),
    ("p.open('r+')", True),
    ("p.open('wb')", True),
    ("p.open('ab')", True),
    ("p.open('a', encoding='utf-8', newline='\\n')", True),
    ("p.open()", False),
    ("p.open('r')", False),
    ("p.open('rb')", False),
    ("p.open(encoding='utf-8')", False),
    # builtin — the mode is the SECOND argument, after the path.
    ("open(p, 'w')", True),
    ("open(p, mode='w')", True),
    ("open(p, 'a')", True),
    ("open(p, 'x')", True),
    ("open(p, 'w+')", True),
    ("open(p, 'r+')", True),
    ("open(p, 'wb')", True),
    ("open(p, 'ab')", True),
    ("open(p)", False),
    ("open(p, 'r')", False),
    ("open(p, 'rb')", False),
    ("open(p, encoding='utf-8')", False),
    # An unreadable mode is a write in both spellings: a guard that cannot read
    # the mode must refuse rather than wave the call through (rule 4).
    ("open(p, mode)", True),
    ("p.open(mode)", True),
)
# A module path that is emphatically NOT the ledger, for proving the exception
# is pinned to one file rather than granted to append mode generally.
SCRATCH_MODULE = 'repo/pm/scratch_not_the_ledger.py'
# The floor under the `open` census, in the same spirit as MIN_SOURCES: well
# under the real count (7 at the time of writing) and well over zero, so the
# classifier cannot be declared correct over a tree it never read.
MIN_OPEN_CALLS = 4


def _sites_for(source: str, rel: str = SCRATCH_MODULE) -> list[str]:
    """The real classifier, run over a source snippet as if it were `rel`."""
    return _mutation_sites(rel, ast.parse(source))


class TheOpenModeIsReadFromTheRightArgument(unittest.TestCase):
    """`Path.open('w')` is a write, and this gate used to say otherwise.

    `_is_write_open` read the mode from `args[1]` — correct for the builtin
    `open(path, 'w')`, and wrong for `p.open('w')`, whose `args[1]` is not the
    mode and is usually nothing at all. Every `p.open('w')` and `p.open('a')`
    under `src/` therefore classified as a READ and passed the one-writer
    boundary: a gate that missed real drift and printed PASS, which CLAUDE.md
    rule 4 calls the cardinal sin.
    """

    def test_every_spelling_of_open_is_classified_by_its_real_mode(self):
        for source, is_write in OPEN_SPELLINGS:
            with self.subTest(source=source):
                sites = _sites_for(source)
                self.assertEqual(
                    is_write, bool(sites),
                    f'{source!r} classified as a '
                    f'{"read" if is_write else "write"}. The mode is the first '
                    'argument for the bound method and the second for the '
                    f'builtin; sites={sites}')

    def test_a_scratch_module_writing_by_Path_open_is_caught(self):
        """End to end, through the same path the gate walks: a real file on
        disk, parsed by `_tree`, classified by `_mutation_sites`."""
        import tempfile
        with tempfile.TemporaryDirectory() as scratch:
            module = Path(scratch) / 'scratch.py'
            module.write_text(
                'from pathlib import Path\n'
                '\n'
                '\n'
                'def sneak(target: Path, payload: str) -> None:\n'
                "    with target.open('w', encoding='utf-8') as handle:\n"
                '        handle.write(payload)\n',
                encoding='utf-8')
            sites = _mutation_sites(SCRATCH_MODULE, _tree(module))
        self.assertEqual([f'{SCRATCH_MODULE}:5: .open(..., write mode)'], sites)

    def test_the_open_census_is_not_empty(self):
        """The classifier above is only worth anything over a tree it read."""
        census = sum(1 for _, path in _sources()
                     for node in _calls(_tree(path)) if _is_an_open_call(node))
        self.assertGreaterEqual(
            census, MIN_OPEN_CALLS,
            f'{census} open() call(s) under {SRC} — expected at least '
            f'{MIN_OPEN_CALLS}. A correct mode classifier over nothing is '
            'still a gate that checks nothing.')


class TheLedgerAppendIsTheOneException(unittest.TestCase):
    """PRIMITIVE 2, continued — the single sanctioned writer outside apply.

    Decision D1 of `0.22.0/ledger`: `ledger.append_row` owns append as a
    PRIMITIVE, because a read-modify-write drops rows when two appenders
    collide. The exception it earns is one file in one mode — not an allowlist
    entry that would also excuse an overwrite, a `mkdir`, or a `write_text`.
    """

    def test_append_is_admitted_in_the_ledger(self):
        for source in ("p.open('a')", "p.open('ab')",
                       "p.open(mode='a')",
                       "p.open('a', encoding='utf-8', newline='\\n')"):
            with self.subTest(source=source):
                self.assertEqual([], _sites_for(source, APPEND_ONLY_MODULE))

    def test_an_overwrite_in_the_ledger_is_still_a_finding(self):
        for source in ("p.open('w')", "open(p, 'w')", "p.open('w+')",
                       "p.open(mode='w')", "p.open('x')"):
            with self.subTest(source=source):
                self.assertNotEqual(
                    [], _sites_for(source, APPEND_ONLY_MODULE),
                    'the ledger exception is append-only — an overwrite there '
                    'rewrites the bytes `merge=union` relies on nobody '
                    'rewriting, which is the defect D1 exists to prevent')

    def test_the_exception_does_not_excuse_other_mutations(self):
        for source in ('p.write_text(x)', 'p.mkdir()', 'p.unlink()',
                       'os.remove(p)'):
            with self.subTest(source=source):
                self.assertNotEqual([], _sites_for(source, APPEND_ONLY_MODULE),
                                    'the exception is by MODE, not a blanket '
                                    'allowlist for the file')

    def test_append_anywhere_else_is_a_finding(self):
        for rel in (SCRATCH_MODULE, 'cli.py', 'repo/pm/model.py'):
            for source in ("p.open('a')", "open(p, 'a')", "p.open('ab')"):
                with self.subTest(rel=rel, source=source):
                    self.assertNotEqual([], _sites_for(source, rel))

    def test_an_unreadable_mode_does_not_buy_the_exception(self):
        self.assertNotEqual([], _sites_for('p.open(mode)', APPEND_ONLY_MODULE))

    def test_the_ledger_really_does_append(self):
        """The exception must not outlive the append it was granted for.

        An allowlist entry nothing matches is a hole waiting for a file to move
        into it — the same reasoning `CONFIG_IMPORT_ALLOWLIST` prunes for.
        """
        tree = _tree(SRC / APPEND_ONLY_MODULE)
        appends = [f'{APPEND_ONLY_MODULE}:{node.lineno}'
                   for node in _calls(tree)
                   if _is_an_open_call(node)
                   and _is_sanctioned_append(APPEND_ONLY_MODULE, node)]
        self.assertEqual(
            1, len(appends),
            f'{APPEND_ONLY_MODULE} should hold exactly ONE sanctioned append; '
            f'found {appends}. If the append is gone, delete the exception.')


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


# --- primitive 3: config through the guards -----------------------------------
# The exact modules that may IMPORT a raw config read (`config_section` /
# `load_config`). Every one of them routes each VALUE through the guards in
# `core/config.py` (`str_tuple`, `str_tuple_table`, `pattern`, `text`) — that
# is what the reviewer checks when a file joins this list. A closed list, not a
# pattern: a new module reading config either goes through a guard and gets
# named here, or it breaks the build. `tuple(cfg.get(...))` over a bare string
# is ('a','d','d','o','n','s','/') — the shape that shipped seven silently
# empty censuses in v0.9.0.
CONFIG_READERS = ('config_section', 'load_config')
CONFIG_OWNER = 'core/config.py'
CONFIG_IMPORT_ALLOWLIST = frozenset((
    CONFIG_OWNER,                 # the guard module itself
    'cli.py',
    'repo/pm/model.py',
    'repo/checks/doc.py',
    'repo/checks/repo_hygiene.py',
    'repo/checks/shell.py',
    'repo/gates_extra.py',
    'godot/checks/defaults.py',
    'godot/checks/props.py',
    'godot/checks/rng.py',
    'godot/checks/test_shape.py',
    'godot/checks/tres.py',
    'godot/checks/tres_comment.py',
    'godot/checks/uid.py',
    'godot/checks/unit_disk.py',
    'godot/read/autoloads.py',
    'godot/read/orphans.py',
    'godot/read/refs.py',
))
# Calls that build a collection straight from an unguarded value.
COLLECTORS = ('tuple', 'set', 'list', 'frozenset')
# --- primitive 4: import layering ----------------------------------------------
# (directory prefix, module prefixes it must NEVER import, census floor).
# format/ is the floor of godot/ (the one upward edge there ever was —
# `_uid_of` importing `uid_index` — is now an injected resolver); index/ sits
# on format/ only; repo/ has no Godot in it, which is what keeps CLAUDE.md
# rule 2's exit clause real; core/ knows about neither family.
LAYER_RULES = (
    ('core/', ('godot_devkit.godot', 'godot_devkit.repo'), 4),
    ('godot/format/', ('godot_devkit.godot.index', 'godot_devkit.godot.read',
                       'godot_devkit.godot.write', 'godot_devkit.godot.checks'), 4),
    ('godot/index/', ('godot_devkit.godot.read', 'godot_devkit.godot.write',
                      'godot_devkit.godot.checks'), 4),
    ('repo/', ('godot_devkit.godot',), 4),
)
PACKAGE = 'godot_devkit'


def _import_bindings(rel: str, tree: ast.Module) -> list[tuple[str, str, int]]:
    """(bound name, imported dotted source, lineno) for every import.

    `import a.b.c` binds `a`; `from m import x as y` binds `y` from `m.x`. A
    relative import is resolved against the module's own package, so a
    hypothetical `from ..godot import x` cannot dodge the layering rules by
    spelling the target without its prefix.
    """
    package_parts = [PACKAGE] + rel.split('/')[:-1]
    out: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split('.')[0]
                out.append((bound, alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[:len(package_parts) - (node.level - 1)]
                module = '.'.join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ''
            if module == '__future__':
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                out.append((bound, f'{module}.{alias.name}', node.lineno))
    return out


def _names_config_is_bound_to(tree: ast.Module) -> set[str]:
    """Every name assigned from a bare `config_section(...)`/`load_config(...)`
    call anywhere in the module — `_CFG = config_section('doc')` makes `_CFG`
    an unguarded section, and `tuple(_CFG.get(...))` the same defect one
    statement later."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in CONFIG_READERS):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        bound.update(t.id for t in targets if isinstance(t, ast.Name))
    return bound


def _is_config_lookup(node: ast.expr, section_names: set[str]) -> bool:
    """True for `config_section(...)`, `load_config(...)`, and a `.get(...)`
    on either of those or on a name bound to one."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in CONFIG_READERS:
        return True
    if isinstance(func, ast.Attribute) and func.attr == 'get':
        receiver = func.value
        if isinstance(receiver, ast.Name) and receiver.id in section_names:
            return True
        return _is_config_lookup(receiver, section_names)
    return False


class ConfigGoesThroughTheGuards(unittest.TestCase):
    """PRIMITIVE 3 — every config VALUE crosses `core/config.py` on its way in."""

    def test_raw_config_imports_are_allowlisted(self):
        census = {rel for rel, _ in _sources()}
        stale = sorted(CONFIG_IMPORT_ALLOWLIST - census)
        self.assertEqual([], stale,
                         'allowlisted module(s) that no longer exist — an entry '
                         'nothing can match is a hole waiting for a file to '
                         'move into it. Prune:\n  ' + '\n  '.join(stale))
        offenders: list[str] = []
        importers = 0
        for rel, path in _sources():
            hits = [(bound, lineno)
                    for bound, source, lineno in _import_bindings(rel, _tree(path))
                    if source.rsplit('.', 1)[-1] in CONFIG_READERS
                    and source.startswith(f'{PACKAGE}.core.')]
            if hits and rel in CONFIG_IMPORT_ALLOWLIST:
                importers += 1
            elif hits:
                offenders.extend(f'{rel}:{lineno}: imports {bound}'
                                 for bound, lineno in hits)
        self.assertEqual(
            [], offenders,
            'a raw config read imported outside the allowlist. Config comes in '
            'through the guards in ' + CONFIG_OWNER + ' (`str_tuple` & co) — a '
            'bare `cfg.get` hands back whatever TOML holds, and a string is '
            'iterable:\n  ' + '\n  '.join(offenders))
        # The allowlist must not be vacuously satisfied: most of its members
        # really do import a config read today.
        self.assertGreaterEqual(importers, 10, 'config-importer census collapsed')

    def test_no_collection_is_built_from_an_unguarded_lookup(self):
        offenders: list[str] = []
        for rel, path in _sources():
            if rel == CONFIG_OWNER:
                continue  # the guards themselves collect, AFTER validating
            tree = _tree(path)
            section_names = _names_config_is_bound_to(tree)
            for node in _calls(tree):
                if not (isinstance(node.func, ast.Name)
                        and node.func.id in COLLECTORS):
                    continue
                if any(_is_config_lookup(arg, section_names) for arg in node.args):
                    offenders.append(f'{rel}:{node.lineno}: '
                                     f'{node.func.id}(<config lookup>)')
        self.assertEqual(
            [], offenders,
            'a collection built straight from a config lookup. `tuple(...)` of '
            'a bare string is a tuple of its CHARACTERS — seven gates shipped '
            'a silent PASS that way in v0.9.0. Route the value through a '
            + CONFIG_OWNER + ' guard:\n  ' + '\n  '.join(offenders))


class NoImportIsDead(unittest.TestCase):
    """PRIMITIVE 4a — an import nobody reads is a claim nobody checked.

    Eight dead `load_config` imports survived an extraction because nothing
    made them fail. A name counts as read when it appears as any `ast.Name`
    in the module (annotations included — `from __future__ import annotations`
    keeps them unquoted) or in `__all__` (the `__init__.py` re-export form).
    """

    def test_every_import_is_read(self):
        offenders: list[str] = []
        bindings_seen = 0
        for rel, path in _sources():
            tree = _tree(path)
            bindings = _import_bindings(rel, tree)
            bindings_seen += len(bindings)
            # An import binds via `alias` nodes, never `ast.Name` — so every
            # Name in the tree is a READ (or a rebind, which also keeps the
            # import from being deletable without a look).
            used = {node.id for node in ast.walk(tree)
                    if isinstance(node, ast.Name)}
            for node in ast.walk(tree):
                if (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == '__all__'
                                for t in node.targets)
                        and isinstance(node.value, (ast.List, ast.Tuple))):
                    used.update(c.value for c in node.value.elts
                                if isinstance(c, ast.Constant)
                                and isinstance(c.value, str))
            offenders.extend(
                f'{rel}:{lineno}: {bound} (from {source})'
                for bound, source, lineno in bindings if bound not in used)
        self.assertGreaterEqual(bindings_seen, 100,
                                'import census collapsed — this gate is '
                                'asserting emptiness over nothing')
        self.assertEqual(
            [], offenders,
            'imported and never read. Delete it — or read it, in this same '
            'change:\n  ' + '\n  '.join(offenders))


class LayersPointDownward(unittest.TestCase):
    """PRIMITIVE 4b — format/ -> index/ -> read/+write/ -> checks/; repo/ has
    no Godot in it; core/ knows about neither family. An upward import is the
    architecture running backwards, however locally convenient."""

    def test_no_layer_imports_upward(self):
        sources = _sources()
        offenders: list[str] = []
        for prefix, banned, floor in LAYER_RULES:
            in_layer = [(rel, path) for rel, path in sources
                        if rel.startswith(prefix)]
            self.assertGreaterEqual(
                len(in_layer), floor,
                f'{prefix} census too small ({len(in_layer)}) — a moved layer '
                'passes this rule by not being scanned')
            for rel, path in in_layer:
                for _, source, lineno in _import_bindings(rel, _tree(path)):
                    if any(source == b or source.startswith(b + '.')
                           for b in banned):
                        offenders.append(f'{rel}:{lineno}: {source}')
        self.assertEqual(
            [], offenders,
            'an import against the layering. A layer imports DOWNWARD only '
            '(format -> index -> read/write -> checks; repo/ never godot/; '
            'core/ neither family):\n  ' + '\n  '.join(offenders))


if __name__ == '__main__':
    unittest.main()
