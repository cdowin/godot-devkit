"""test_fuzz_inputs.py — property fuzz: mangled input vs the CLI's universal negatives.

WHY THIS EXISTS
Every release review of this package so far has returned NOT RELEASE-SAFE, and
the blocker has always been the same shape: a docstring's universal negative
("this cannot write a file it was not asked about") that no test attacked,
because builders write existential tests for intended behavior. This harness
is the standing adversarial stage: a seeded mangler composes hostile
paths/ids (traversal, empty and dot segments, backslashes, globs, absolute
paths, URL-ish schemes, whitespace, newlines, quotes, unicode confusables,
over-long strings) and drives them through the REAL CLI against a scratch
tree, asserting the property the write verbs' docstrings claim:

  VERB REFUSAL TOTALITY (scene / refs --retarget) — for every mangled node
  path / sub_resource id / res:// path: exit 0 with the edit confined to the
  file the command named, or a refusal with the tree byte-identical — never an
  exception escaping `cli.main` (the real CLI's traceback), never a write to a
  file the command did not name.

The GRAIN CONTAINMENT property this harness also carried — the pm verbs'
promise that a mangled id never writes a sibling grain, and the v0.16.0
blocker it was built to catch — left with the pm tracker (0.25.0); that
family and its fuzz are agentic-sdlc's now.

TEETH — proven against pre-fix code, not assumed
Another src tree is runnable under this same harness via a PYTHONPATH overlay:

    git archive <ref> src | tar -x -C /tmp/prefix
    DEVKIT_FUZZ_TARGET_SRC=/tmp/prefix/src \
        uv run --with pytest python -m pytest tests/test_fuzz_inputs.py -q

The overlong scene path OSError this harness caught on its first run was
pinned as a known finding, fixed in 0.17.0, and its pin replaced by the
explicit refusal test at the bottom of this file — the property now runs at
full strength with no judge carve-outs.
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

from support import FIXTURES

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
SCENE_CASES = 320
RETARGET_CASES = 100


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


# --- the property: verb refusal totality --------------------------------------
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
    where = f'{argv!r} -> code={code} delta={delta} out={out[:160]!r}'
    if escaped is not None:
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
            # The class census is over the ARGUMENTS the mangler produced —
            # every element, since any of them may be the hostile one.
            for cls in {c for arg in argv for c in _classes_of(arg)}:
                census[f'class:{cls}'] += 1
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
            for cls in _classes_of(old) | _classes_of(new):
                census[f'class:{cls}'] += 1
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
    the containment clauses rot unexercised. The class floor is asked of the
    two corpora TOGETHER: the mangler is one generator, and which corpus a
    class lands in is the seed's business, not the property's.
    """
    _, scene = _scene_results()
    _, retarget = _retarget_results()
    for cls in ('dot-segment', 'empty-segment', 'backslash', 'glob',
                'absolute', 'scheme', 'whitespace', 'newline', 'quote',
                'confusable', 'overlong', 'dash'):
        seen = scene.get(f'class:{cls}', 0) + retarget.get(f'class:{cls}', 0)
        assert seen >= 8, (cls, scene, retarget)
    assert scene['refused'] >= 100, scene
    assert scene['accepted-write'] >= 5, scene
    assert retarget['refused'] >= 30, retarget
    assert retarget['accepted-write'] >= 3, retarget


def test_overlong_path_arguments_are_refused_across_the_scene_plane():
    """Replaced the known-finding pin (0.17.0 overlong-scene-path-crash).

    At the pinned HEAD a file argument longer than NAME_MAX escaped as a raw
    OSError (ENAMETOOLONG) out of `Path.is_file` — the scene plane lacked the
    exists/OSError guard the pm plane grew for exactly this. Every verb that
    stats a caller-supplied path now refuses instead: the write verbs at
    exit 2 ("no such file"), `refs --retarget` at exit 1 (its missing-target
    refusal), and `scene add --instance` via its instance-target refusal.
    """
    overlong = 'x' * 300
    with _scratch(_build_scene) as (outer, _):
        base = _snap(outer)
        refusals = (
            (('scene', 'set', f'{overlong}.tscn', '.', 'text', '"x"'), 2),
            (('scene', 'rm', f'{overlong}.tscn', 'Inner'), 2),
            (('scene', 'canonicalize', f'{overlong}.tscn'), 2),
            (('tiles', 'paint', f'{overlong}.tscn', '--layer', 'L',
              '--region', '0,0,1,1', '--tile', '0/0,0'), 2),
            (('refs', '--retarget', 'res://scripts/old_helper.gd',
              f'res://{overlong}.gd'), 1),
            (('scene', 'add', 'scenes/panel.tscn', '.', 'Inst',
              '--instance', f'res://{overlong}.tscn'), 1),
        )
        for argv, want in refusals:
            code, out, escaped = _run(argv)
            assert escaped is None, (argv, escaped)
            assert code == want, (argv, code, out)
        assert _delta(base, _snap(outer)) == []
