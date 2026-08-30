"""test_fuzz_inputs.py — property fuzz: mangled input vs the CLI's universal negatives.

WHY THIS EXISTS
Every release review of this package so far has returned NOT RELEASE-SAFE, and
the blocker has always been the same shape: a docstring's universal negative
("this cannot write a sibling grain") that no test attacked, because builders
write existential tests for intended behavior. The v0.16.0 blocker —
`pm bug fixed '0.1/bugs/../features/alpha/feature'` traversed and wrote a
bug-vocabulary status into the sibling FEATURE file — sat behind exactly such a
docstring. This harness is the standing adversarial stage: a seeded mangler
composes hostile ids/paths (traversal, empty and dot segments, backslashes,
globs, absolute paths, URL-ish schemes, whitespace, newlines, quotes, unicode
confusables, over-long strings) and drives them through the REAL CLI against a
scratch tree, asserting two properties the docstrings claim:

  GRAIN CONTAINMENT (pm) — for every id fed to status verbs / set / get /
  move / decide: either the command refuses (exit 1/2, whole scratch tree
  byte-identical, proven by snapshot), or every file it touched realpaths
  INSIDE pm/roadmap/<milestone>/ in the slot the verb's grain kind owns.

  VERB REFUSAL TOTALITY (scene / refs --retarget) — for every mangled node
  path / sub_resource id / res:// path: exit 0 with the edit confined to the
  file the command named, or a refusal with the tree byte-identical — never an
  exception escaping `cli.main` (the real CLI's traceback), never a write to a
  file the command did not name.

TEETH — proven against the pre-fix code, not assumed
The pre-fix package (commit 76e28fb~1, the code the v0.16.0 release review
caught) is runnable under this same harness via a PYTHONPATH overlay:

    git archive 76e28fb~1 src | tar -x -C /tmp/prefix
    DEVKIT_FUZZ_TARGET_SRC=/tmp/prefix/src \
        uv run --with pytest python -m pytest tests/test_fuzz_inputs.py -q

Run 2026-08-30 against that snapshot: test_grain_containment... FAILED with 4
violations — ('pm', 'bug', 'fixed', '0.1/bugs/../features/alpha/feature') and
its nested-slug twin exited 0 and wrote
pm/roadmap/0.1-demo/features/alpha/feature.md (a bug-kind write landing on a
feature grain), and `pm set` rode the same traversal twice. Same file, same
seed, green on HEAD. The
committed floor beneath that one-time run is
`test_the_corpus_separates_the_pre_fix_resolver`, which keeps a transcription
of the rejected resolver in-tree and proves the corpus still reaches it.

KNOWN FINDINGS (reported, deliberately not fixed here)
Three live findings on HEAD, each held by a PIN test — a carve-out in a judge
may not outlive its pin. When a pin FAILS, that bug is fixed: delete the pin
and its flag together, so the property's full clause snaps back on.

  1. `pm decide '0.1/..'` / `pm decide '0.1/.'` write a decisions.md through
     traversal at exit 0 (the milestone's log, and a features/decisions.md in
     a slot the schema does not have). Flag: `_DECIDE_CARVED_OUT`.
  2. `pm milestone ready /etc/hosts` — any absolute milestone id — escapes as
     `NotImplementedError` from `Path.glob` ("Non-relative patterns are
     unsupported") instead of exit 2. Flag: `_MILESTONE_GLOB_CRASH_PINNED`.
  3. `scene <verb> <over-long path> …` escapes as a raw `OSError`
     (ENAMETOOLONG) instead of a refusal — the scene plane lacks the `_exists`
     guard the pm plane grew for exactly this. Flag:
     `_OVERLONG_SCENE_PATH_PINNED`.
"""
from __future__ import annotations

import contextlib
import functools
import io
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES  # noqa: E402

# Teeth-proof overlay: point the harness at another src tree (see docstring).
# Purging godot_devkit from sys.modules makes the overlay win even when another
# collected test file imported the package first — run this file alone when
# the variable is set.
_TARGET_SRC = os.environ.get('DEVKIT_FUZZ_TARGET_SRC')
if _TARGET_SRC:
    sys.path.insert(0, str(Path(_TARGET_SRC).resolve()))
    for _name in [m for m in list(sys.modules)
                  if m.split('.')[0] == 'godot_devkit']:
        del sys.modules[_name]

from godot_devkit import cli  # noqa: E402

pytestmark = pytest.mark.fuzz

# The seed is part of the gate. Changing it changes which hostile inputs are
# covered, so it moves only with a recorded reason.
SEED = 20260830
PM_CASES = 320
SCENE_CASES = 320
RETARGET_CASES = 100

# Each flag dies with its known-finding pin — see the module docstring.
_DECIDE_CARVED_OUT = True
_MILESTONE_GLOB_CRASH_PINNED = True
_OVERLONG_SCENE_PATH_PINNED = True


# --- the mangler --------------------------------------------------------------
# Composed, not enumerated: hostile SEGMENTS spliced into valid ids, joined by
# hostile SEPARATORS, wrapped in hostile PREFIXES. Every input class the module
# docstring names has members here, and `_classes_of` is the census that proves
# the generator still emits all of them.
_HOSTILE_SEGMENTS = (
    '..', '..', '.', '', '...', '.md', '.git',
    'a\\b', '..\\..', 'C:\\roadmap',
    '*', '?', 's[0-9]', 'st*ries', '!bang',
    ' ', ' alpha', 'crash ', '\ttab', 'two words',
    'аlpha', 'ѕ0', '０.１', 'x\u200by', 'bugs\u2024crash',
    'x' * 300,
    "it's", 'say "hi"', '`tick`', '$HOME', '-', '--force',
)
_WRAP_SCHEMES = ('res://', 'file://', 'user://', 'http://evil/', 'uid://')
_SEPS = ('/', '/', '/', '/', '//', '/./', '\\', '\u2044')


def _mangle(rng: random.Random, bases: tuple[str, ...]) -> str:
    roll = rng.random()
    if roll < 0.15:
        return rng.choice(bases)  # exactly valid — keeps the accept path live
    if roll < 0.60:  # splice hostility into a valid id
        segs = rng.choice(bases).split('/')
        for _ in range(rng.randrange(1, 3)):
            pick = rng.choice(_HOSTILE_SEGMENTS)
            if rng.random() < 0.5:
                segs[rng.randrange(len(segs))] = pick
            else:
                segs.insert(rng.randrange(len(segs) + 1), pick)
    else:  # built from whole cloth
        pool = tuple(s for b in bases for s in b.split('/')) + _HOSTILE_SEGMENTS
        segs = [rng.choice(pool) for _ in range(rng.randrange(1, 6))]
    out = ''
    for i, seg in enumerate(segs):
        out += (rng.choice(_SEPS) if i else '') + seg
    wrap = rng.random()
    if wrap < 0.08:
        out = '/' + out
    elif wrap < 0.16:
        out = rng.choice(_WRAP_SCHEMES) + out
    elif wrap < 0.20:
        out = ' ' + out + ' '
    elif wrap < 0.24:
        out += '\n' + rng.choice(('x', '---', 'status: pwned'))
    elif wrap < 0.27:
        out += 'x' * 400
    return out


def _classes_of(text: str) -> set[str]:
    """Which hostile input classes a generated string exercises."""
    segs = re.split(r'[/\\]', text)
    hit = set()
    if any(s in ('.', '..', '...') for s in segs):
        hit.add('dot-segment')
    if '' in segs[1:]:
        hit.add('empty-segment')
    if '\\' in text:
        hit.add('backslash')
    if set('*?[]!') & set(text):
        hit.add('glob')
    if text.startswith('/'):
        hit.add('absolute')
    if '://' in text:
        hit.add('scheme')
    if ' ' in text or '\t' in text:
        hit.add('whitespace')
    if '\n' in text or '\r' in text:
        hit.add('newline')
    if any(q in text for q in ('"', "'", '`')):
        hit.add('quote')
    if any(ord(c) > 127 for c in text):
        hit.add('confusable')
    if len(text) > 255:
        hit.add('overlong')
    if text.startswith('-'):
        hit.add('dash')
    return hit


# --- running the real CLI -----------------------------------------------------
def _run(argv: tuple[str, ...]) -> tuple[int | None, str, BaseException | None]:
    """cli.main in-process. An exception escaping it IS the real CLI's
    traceback — returned, never asserted here, so the property owns the claim."""
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    buf = io.StringIO()
    code, escaped = None, None
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main(list(argv))
    except SystemExit as bail:  # argparse's spelling of a usage error
        code = bail.code if isinstance(bail.code, int) else 2
    except Exception as err:  # noqa: BLE001 — the property judges it
        escaped = err
    finally:
        repo_root.cache_clear()
        load_config.cache_clear()
    return code, buf.getvalue(), escaped


# --- byte-snapshots of the whole scratch tree ---------------------------------
def _snap(root: Path) -> dict[str, bytes | None]:
    """Every file's bytes and every directory under `root`, .git excluded
    (nothing here runs git after setup). Keyed relative, dirs suffixed '/'."""
    out: dict[str, bytes | None] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '.git']
        rel = Path(dirpath).relative_to(root)
        for d in dirnames:
            out[f'{rel / d}/'] = None
        for f in filenames:
            out[str(rel / f)] = (Path(dirpath) / f).read_bytes()
    return out


def _delta(before: dict, after: dict) -> list[str]:
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k, ...) != after.get(k, ...))


def _restore(root: Path, before: dict) -> None:
    current = _snap(root)
    for rel in current:
        if rel in before:
            continue
        target = root / rel
        if not rel.endswith('/'):
            target.unlink()
    for rel, data in before.items():
        target = root / rel
        if rel.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
        elif current.get(rel, ...) != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    # prune created-and-now-empty directories, deepest first
    for rel in sorted((k for k in current if k.endswith('/')),
                      key=len, reverse=True):
        if rel not in before:
            with contextlib.suppress(OSError):
                (root / rel).rmdir()
    assert _snap(root) == before, 'restore failed — the scratch tree drifted'


@contextlib.contextmanager
def _scratch(build) -> tuple[Path, Path]:
    """(outer, repo): repo is `outer/repo`, snapshots cover ALL of `outer`, so
    a `repo/../…` traversal write lands inside the evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        outer = Path(tmp)
        root = outer / 'repo'
        build(outer, root)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        try:
            yield outer, root
        finally:
            os.chdir(previous)


# --- property (a): grain containment ------------------------------------------
_PM_BASES = ('0.1', '0.1/alpha', '0.1/beta', '0.1/alpha/s0', '0.1/alpha/s1',
             '0.1/beta/b0', '0.1/bugs/crash', '0.1/bugs/sub/nested')

# The fixed refusal matrix under the fuzz: canonical hostile shapes, including
# the v0.16.0 blocker id verbatim, run against every verb regardless of what
# the seeded stream generates.
_KILLERS = (
    '0.1/bugs/../features/alpha/feature',
    '0.1/bugs/sub/../../features/alpha/feature',
    '0.1/bugs/',
    '0.1/bugs/../../../outside',
    '0.1/../0.1/alpha/s0',
    '../repo/pm/roadmap/0.1-demo/features/alpha/feature',
    '/etc/hosts',
    '0.1/alpha/../../0.1/bugs/crash',
)

_PM_VERBS = ('story', 'bug', 'feature', 'milestone', 'set', 'get', 'move',
             'decide')


def _grain_front(path: Path, front: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['---'] + [f'{k}: {v}' for k, v in front.items()] + ['---', '', 'x', '']
    path.write_text('\n'.join(lines), encoding='utf-8')


def _build_pm(outer: Path, root: Path) -> None:
    (outer / 'outside.md').write_text('---\nstatus: decoy\n---\n', encoding='utf-8')
    m = root / 'pm' / 'roadmap' / '0.1-demo'
    _grain_front(m / 'milestone.md',
                 {'id': '"0.1"', 'name': 'Demo', 'status': 'building'})
    for slug in ('alpha', 'beta'):
        _grain_front(m / 'features' / slug / 'feature.md',
                     {'id': f'0.1/{slug}', 'milestone': '"0.1"', 'name': slug,
                      'status': 'building', 'reviewed': ''})
    for fid, sslug in (('alpha', 's0'), ('alpha', 's1'), ('beta', 'b0')):
        _grain_front(m / 'features' / fid / 'stories' / f'{sslug}.md',
                     {'id': f'0.1/{fid}/{sslug}', 'feature': f'0.1/{fid}',
                      'milestone': '"0.1"', 'name': sslug, 'status': 'todo'})
    _grain_front(m / 'bugs' / 'crash.md',
                 {'id': '0.1/bugs/crash', 'milestone': '"0.1"', 'status': 'open'})
    _grain_front(m / 'bugs' / 'sub' / 'nested.md',
                 {'id': '0.1/bugs/sub/nested', 'milestone': '"0.1"',
                  'status': 'open'})


def _pm_argv(rng: random.Random, verb: str,
             gid: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(argv, the caller-supplied grain ids inside it)."""
    if verb == 'story':
        return ('pm', 'story', 'wip', gid), (gid,)
    if verb == 'bug':
        return ('pm', 'bug', 'fixed', gid), (gid,)
    if verb == 'feature':
        return ('pm', 'feature', 'planning', gid), (gid,)
    if verb == 'milestone':
        return ('pm', 'milestone', 'ready', gid), (gid,)
    if verb == 'set':
        return ('pm', 'set', gid, 'status', 'wombat'), (gid,)
    if verb == 'get':
        return ('pm', 'get', gid, 'status'), (gid,)
    if verb == 'decide':
        return ('pm', 'decide', gid, 'fuzz', 'entry'), (gid,)
    if rng.random() < 0.5:
        return ('pm', 'move', gid, '0.1/beta'), (gid, '0.1/beta')
    return ('pm', 'move', '0.1/alpha/s0', gid), ('0.1/alpha/s0', gid)


def _grain_shaped(path: Path) -> bool:
    return (path.name in ('feature.md', 'milestone.md')
            or 'stories' in path.parts or 'bugs' in path.parts)


_KIND_OK = {
    'story': lambda p: 'stories' in p.parts,
    'bug': lambda p: 'bugs' in p.parts,
    'feature': lambda p: p.name == 'feature.md',
    'milestone': lambda p: p.name == 'milestone.md',
    'set': _grain_shaped,
    'move': lambda p: 'stories' in p.parts,
    'decide': lambda p: p.name == 'decisions.md',
}


def _literal_segments(gid: str) -> bool:
    return all(s not in ('', '.', '..')
               for s in gid.replace('\\', '/').split('/'))


def _judge_pm(verb: str, argv: tuple[str, ...], ids: tuple[str, ...],
              code, out: str, escaped, delta: list[str],
              outer: Path, roadmap: Path) -> str | None:
    where = f'{argv!r} -> code={code} delta={delta} out={out[:160]!r}'
    if escaped is not None:
        if (_MILESTONE_GLOB_CRASH_PINNED and verb == 'milestone'
                and isinstance(escaped, NotImplementedError) and not delta):
            return None  # known finding 2 — held by its pin test
        return f'TRACEBACK {type(escaped).__name__}: {escaped!r} on {where}'
    if code not in (0, 1, 2):
        return f'EXIT CODE outside the contract on {where}'
    if code != 0 and delta:
        return f'REFUSAL WROTE on {where}'
    if code == 0 and verb == 'get' and delta:
        return f'READ VERB WROTE on {where}'
    if code == 0:
        for rel in delta:
            resolved = (outer / rel.rstrip('/')).resolve()
            if not resolved.is_relative_to(roadmap):
                return f'ESCAPED pm/roadmap/: {rel} on {where}'
            if not _KIND_OK[verb](Path(rel)):
                return f'WRONG GRAIN KIND: {rel} on {where}'
        if delta and not (verb == 'decide' and _DECIDE_CARVED_OUT):
            for gid in ids:
                if not _literal_segments(gid):
                    return f'NON-LITERAL ID ACCEPTED: {gid!r} on {where}'
    return None


@functools.lru_cache(maxsize=1)
def _pm_results() -> tuple[tuple[str, ...], dict]:
    rng = random.Random(SEED)
    violations: list[str] = []
    census: Counter = Counter()
    cases = [(verb, gid) for gid in _KILLERS for verb in _PM_VERBS]
    cases += [(rng.choice(_PM_VERBS), _mangle(rng, _PM_BASES))
              for _ in range(PM_CASES)]
    with _scratch(_build_pm) as (outer, root):
        roadmap = (root / 'pm' / 'roadmap').resolve()
        base = _snap(outer)
        for verb, gid in cases:
            argv, ids = _pm_argv(rng, verb, gid)
            code, out, escaped = _run(argv)
            delta = _delta(base, _snap(outer))
            verdict = _judge_pm(verb, argv, ids, code, out, escaped, delta,
                                outer, roadmap)
            if verdict:
                violations.append(verdict)
            census['refused'] += 1 if code in (1, 2) else 0
            census['accepted-write'] += 1 if code == 0 and delta else 0
            census['ok-no-write'] += 1 if code == 0 and not delta else 0
            for cls in _classes_of(gid):
                census[f'class:{cls}'] += 1
            if delta:
                _restore(outer, base)
    return tuple(violations), dict(census)


def test_grain_containment_under_mangled_ids():
    violations, _ = _pm_results()
    assert not violations, (
        f'{len(violations)} containment violations (seed {SEED}):\n\n'
        + '\n\n'.join(violations[:8]))


# --- property (b): verb refusal totality --------------------------------------
_NODE_BASES = ('.', 'Inner', 'Footer', 'Panel/Inner')
_SUB_BASES = ('1_abc', 'StyleBoxFlat_1')
_SCENE = 'scenes/panel.tscn'
_FILE_BASES = ('scenes/panel.tscn', 'scenes/referrer.tscn')


def _build_scene(outer: Path, root: Path) -> None:
    shutil.copytree(FIXTURES / 'canon_repo', root)
    (outer / 'outside.tscn').write_text(
        '[gd_scene format=3]\n\n[node name="Decoy" type="Node"]\n',
        encoding='utf-8')


def _scene_argv(rng: random.Random) -> tuple[str, ...]:
    file = _SCENE if rng.random() < 0.8 else _mangle(rng, _FILE_BASES)
    np = _mangle(rng, _NODE_BASES)
    kind = rng.choice(('set', 'set', 'sub', 'rm', 'rename', 'add', 'script',
                       'connect'))
    if kind == 'set':
        value = '"fuzz"' if rng.random() < 0.7 else _mangle(rng, ('true',))
        prop = 'text' if rng.random() < 0.7 else _mangle(rng, ('text',))
        return 'scene', 'set', file, np, prop, value
    if kind == 'sub':
        return ('scene', 'set', file, '--sub-resource',
                _mangle(rng, _SUB_BASES), 'bg_color', '"red"')
    if kind == 'rm':
        return 'scene', 'rm', file, np
    if kind == 'rename':
        return 'scene', 'rename', file, np, _mangle(rng, ('Renamed',))
    if kind == 'add':
        return 'scene', 'add', file, np, _mangle(rng, ('Fresh',)), 'Node2D'
    if kind == 'script':
        return ('scene', 'add', file, '.', 'Scripted', 'Node2D', '--script',
                _mangle(rng, ('res://systems/logic.gd',)))
    return ('scene', 'connect', file, _mangle(rng, ('pressed',)), np,
            _mangle(rng, _NODE_BASES), 'on_fuzz')


def _named_file(argv: tuple[str, ...], root: Path) -> Path | None:
    try:
        return (root / argv[2]).resolve()
    except (OSError, ValueError):
        return None


def _judge_scene(argv, code, out, escaped, delta, outer, root) -> str | None:
    import errno
    where = f'{argv!r} -> code={code} delta={delta} out={out[:160]!r}'
    if escaped is not None:
        if (_OVERLONG_SCENE_PATH_PINNED and isinstance(escaped, OSError)
                and escaped.errno == errno.ENAMETOOLONG and not delta):
            return None  # known finding 3 — held by its pin test
        return f'TRACEBACK {type(escaped).__name__}: {escaped!r} on {where}'
    if code not in (0, 1, 2):
        return f'EXIT CODE outside the contract on {where}'
    if code != 0 and delta:
        return f'REFUSAL WROTE on {where}'
    if code == 0 and delta:
        named = _named_file(argv, root)
        for rel in delta:
            if (outer / rel).resolve() != named:
                return f'WROTE AN UNNAMED FILE: {rel} on {where}'
    return None


@functools.lru_cache(maxsize=1)
def _scene_results() -> tuple[tuple[str, ...], dict]:
    rng = random.Random(SEED + 1)
    violations: list[str] = []
    census: Counter = Counter()
    with _scratch(_build_scene) as (outer, root):
        base = _snap(outer)
        for _ in range(SCENE_CASES):
            argv = _scene_argv(rng)
            code, out, escaped = _run(argv)
            delta = _delta(base, _snap(outer))
            verdict = _judge_scene(argv, code, out, escaped, delta, outer, root)
            if verdict:
                violations.append(verdict)
            census['refused'] += 1 if code in (1, 2) else 0
            census['accepted-write'] += 1 if code == 0 and delta else 0
            if delta:
                _restore(outer, base)
    return tuple(violations), dict(census)


def test_scene_verbs_refuse_or_edit_only_the_named_file():
    violations, _ = _scene_results()
    assert not violations, (
        f'{len(violations)} totality violations (seed {SEED + 1}):\n\n'
        + '\n\n'.join(violations[:8]))


_OLD = 'res://scripts/old_helper.gd'
_NEW = 'res://scripts/new_helper.gd'
_SOURCE_SUFFIXES = ('.tscn', '.tres', '.gd')


def _build_retarget(outer: Path, root: Path) -> None:
    shutil.copytree(FIXTURES / 'retarget_repo', root)
    (outer / 'outside.tscn').write_text(
        '[gd_scene load_steps=2 format=3]\n\n'
        f'[ext_resource type="Script" path="{_OLD}" id="1_h"]\n',
        encoding='utf-8')


@functools.lru_cache(maxsize=1)
def _retarget_results() -> tuple[tuple[str, ...], dict]:
    rng = random.Random(SEED + 2)
    violations: list[str] = []
    census: Counter = Counter()
    with _scratch(_build_retarget) as (outer, root):
        base = _snap(outer)
        for _ in range(RETARGET_CASES):
            old = _OLD if rng.random() < 0.4 else _mangle(rng, (_OLD,))
            new = _NEW if rng.random() < 0.4 else _mangle(rng, (_NEW,))
            argv = ('refs', '--retarget', old, new)
            code, out, escaped = _run(argv)
            delta = _delta(base, _snap(outer))
            where = f'{argv!r} -> code={code} delta={delta} out={out[:160]!r}'
            if escaped is not None:
                violations.append(f'TRACEBACK {type(escaped).__name__}: '
                                  f'{escaped!r} on {where}')
            elif code not in (0, 1, 2):
                violations.append(f'EXIT CODE outside the contract on {where}')
            elif code == 2 and delta:
                violations.append(f'USAGE ERROR WROTE on {where}')
            else:
                # exit 1 with rewrites is contractual here: a skip is loud
                # (exit 1) while provable refs are still rewritten.
                for rel in delta:
                    inside = (outer / rel).resolve().is_relative_to(
                        root.resolve())
                    if not inside or not rel.endswith(_SOURCE_SUFFIXES):
                        violations.append(
                            f'WROTE OUTSIDE THE SWEEP: {rel} on {where}')
            census['refused'] += 1 if code in (1, 2) and not delta else 0
            census['accepted-write'] += 1 if delta else 0
            if delta:
                _restore(outer, base)
    return tuple(violations), dict(census)


def test_retarget_refuses_or_sweeps_only_source_files_in_repo():
    violations, _ = _retarget_results()
    assert not violations, (
        f'{len(violations)} retarget violations (seed {SEED + 2}):\n\n'
        + '\n\n'.join(violations[:8]))


# --- the teeth ----------------------------------------------------------------
def test_the_corpus_actually_exercises_every_hostile_class_and_both_verdicts():
    """A fuzz whose corpus is all one answer proves nothing.

    Two censuses, asserted rather than trusted: the generator must still emit
    every hostile input class it advertises, and the runs must contain both
    refusals AND accepted writes — a corpus the CLI always refuses would let
    the containment clauses rot unexercised.
    """
    _, pm = _pm_results()
    _, scene = _scene_results()
    _, retarget = _retarget_results()
    for cls in ('dot-segment', 'empty-segment', 'backslash', 'glob',
                'absolute', 'scheme', 'whitespace', 'newline', 'quote',
                'confusable', 'overlong', 'dash'):
        assert pm.get(f'class:{cls}', 0) >= 8, (cls, pm)
    assert pm['refused'] >= 150, pm
    assert pm['accepted-write'] >= 5, pm
    assert scene['refused'] >= 100, scene
    assert scene['accepted-write'] >= 5, scene
    assert retarget['refused'] >= 30, retarget
    assert retarget['accepted-write'] >= 3, retarget


def _pre_fix_bug_resolver(mdir: Path, gid: str) -> Path | None:
    """The v0.16.0 resolver, kept on purpose — transcribed from
    `git show 76e28fb~1:src/godot_devkit/repo/pm/cli.py` `_grain_file`:
    partition on '/bugs/', join the slug half, no segment guard. This is the
    code the release review rejected; the corpus must still reach it."""
    _, _, rest = gid.partition('/bugs/')
    bf = mdir / 'bugs' / f'{rest}.md'
    try:
        return bf if bf.is_file() else None
    except OSError:
        return None


def test_the_corpus_separates_the_pre_fix_resolver():
    """The harness proven to have teeth, not just to be green.

    Path-level: the generated stream (not just the fixed matrix) must keep
    producing bug ids whose slug half resolves OUTSIDE bugs/. Live-fire: at
    least one corpus id must make the pre-fix resolver hand back an EXISTING
    sibling grain file — the exact cross-grain write of the v0.16.0 blocker.
    """
    rng = random.Random(SEED)
    generated = [_mangle(rng, _PM_BASES) for _ in range(PM_CASES)]
    bug_ids = [g for g in generated if '/bugs/' in g]
    assert len(bug_ids) >= 20, len(bug_ids)
    escapes = 0
    for gid in bug_ids:
        rest = gid.partition('/bugs/')[2]
        resolved = os.path.normpath(os.path.join('bugs', rest + '.md'))
        if not resolved.startswith('bugs' + os.sep):
            escapes += 1
    assert escapes >= 5, (
        f'only {escapes} of {len(bug_ids)} generated bug ids escape the '
        f'bugs/ slot at the path level — the fuzz has lost its teeth')
    with _scratch(_build_pm) as (_, root):
        mdir = root / 'pm' / 'roadmap' / '0.1-demo'
        live = [gid for gid in list(_KILLERS) + bug_ids
                if (hit := _pre_fix_bug_resolver(mdir, gid)) is not None
                and not hit.resolve().is_relative_to((mdir / 'bugs').resolve())]
        assert live, ('no corpus id makes the pre-fix resolver return an '
                      'existing sibling grain — the blocker shape is gone')


def test_known_finding_decide_traverses_dot_segments_pin():
    """PIN of a live finding, not an endorsement — see the module docstring.

    On HEAD, `pm decide` resolves '0.1/..' (the milestone dir, via
    features/..) and '0.1/.' (features/ itself, a slot the schema does not
    have) and writes a decisions.md there at exit 0. Reported upstream rather
    than fixed here. While this reproduces, the containment property carves
    decide out of the literal-segment clause. WHEN THIS TEST FAILS the bug is
    fixed: delete this pin AND `_DECIDE_CARVED_OUT`, so decide rejoins the
    clause and the carve-out cannot outlive its reason.
    """
    with _scratch(_build_pm) as (_, root):
        mdir = root / 'pm' / 'roadmap' / '0.1-demo'
        code, out, escaped = _run(('pm', 'decide', '0.1/..', 'pin', 'probe'))
        assert escaped is None
        assert code == 0 and (mdir / 'decisions.md').is_file(), (code, out)
        code, out, escaped = _run(('pm', 'decide', '0.1/.', 'pin', 'probe'))
        assert escaped is None
        assert code == 0 and (mdir / 'features' / 'decisions.md').is_file(), (
            code, out)


def test_known_finding_absolute_milestone_id_crashes_pin():
    """PIN of finding 2 (module docstring): an absolute milestone id reaches
    `Path.glob` as a non-relative pattern and escapes as NotImplementedError —
    the real CLI prints a traceback where exit 2 belongs. When this fails,
    delete this pin AND `_MILESTONE_GLOB_CRASH_PINNED`."""
    with _scratch(_build_pm):
        code, _, escaped = _run(('pm', 'milestone', 'ready', '/etc/hosts'))
        assert isinstance(escaped, NotImplementedError), (code, escaped)


def test_known_finding_overlong_scene_path_crashes_pin():
    """PIN of finding 3 (module docstring): a scene file arg longer than
    NAME_MAX escapes as a raw OSError (ENAMETOOLONG) — the pm plane grew
    `_exists` for exactly this, the scene plane has not. When this fails,
    delete this pin AND `_OVERLONG_SCENE_PATH_PINNED`."""
    import errno
    with _scratch(_build_scene):
        argv = ('scene', 'set', 'x' * 300 + '.tscn', '.', 'text', '"x"')
        code, _, escaped = _run(argv)
        assert isinstance(escaped, OSError), (code, escaped)
        assert escaped.errno == errno.ENAMETOOLONG, escaped
