"""test_replay_migration.py — the scaffolders, replayed. Twice is once.

WHY THIS IS A COMMITTED TEST AND NOT A PROCEDURE
Every write verb in this package claims to be idempotent, and `pm new` claims
more than that: re-running it on an existing grain FILLS GAPS rather than
rewriting what is there. Those claims are how a consumer is told it is safe to
run the scaffolders over a live tree — which people do, at exactly the moment a
mistake is most expensive. The claim was checked by hand, once, by replaying a
migration over a copied tree and eyeballing the diff.

Here it is as a gate: run the whole scaffolding sequence over a throwaway tree,
snapshot every byte, run it again, and require the second pass to change
nothing at all. Byte-identical, not "no errors" — a verb that rewrites a file to
the same shape with a fresh timestamp passes the second bar and fails this one.

The FIRST pass is asserted too. A replay that perturbs nothing is
indistinguishable from a replay that works, so the empty tree, the tree after
pass one, and the tree after pass two are all three compared: the first
comparison must DIFFER and the second must not.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit import cli  # noqa: E402
from godot_devkit.core.project import load_config, repo_root  # noqa: E402

pytestmark = pytest.mark.fuzz

DEVKIT_TOML = """\
[pm]
template_dir = "pm/templates"
"""

# The scaffolding sequence, in the order a repo actually adopts the toolkit,
# each step paired with the exit code its REPLAY must produce.
#
# Two idempotence contracts, and the difference is deliberate rather than an
# oversight — so it is written down here instead of being tidied away by
# dropping the second kind from the sequence:
#
#   0  FILL-GAPS. A container grain (a milestone dir, a feature dir) re-scaffolds
#      into whatever slot is missing and leaves the rest alone, so a re-run is a
#      no-op that exits clean. This is what makes it safe to run over a live tree
#      after an upgrade adds a slot.
#   1  REFUSE. A story and a bug are ONE authored file each. There is no gap to
#      fill, so "re-scaffold" could only mean overwrite, and a write verb that
#      silently replaces authored content is the cardinal sin from the write
#      side. It refuses, loudly, and touches nothing.
#
# Either way the tree is unchanged, which is what the byte comparison asserts.
# What this table adds is that neither verb may quietly swap contracts.
SEQUENCE: tuple[tuple[tuple[str, ...], int], ...] = (
    (('pm', 'init'), 0),
    (('pm', 'new', 'milestone', '0.1', 'First', 'Milestone'), 0),
    (('pm', 'new', 'feature', '0.1', 'thing', 'A', 'Thing'), 0),
    (('pm', 'new', 'story', '0.1/thing', '01-slug', 'Do', 'It'), 1),
    (('pm', 'new', 'bug', '0.1', 'a-bug'), 1),
    (('pm', 'templates'), 0),
    (('pm', 'sync'), 0),
    (('pm', 'install-skills'), 0),
    (('install-ci',), 0),
    (('install-agents',), 0),
    (('install-hooks',), 0),
)


def _snapshot(root: Path) -> dict[str, str]:
    """Every tracked-able byte in the tree, hashed. `.git/` is not the product."""
    out = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or '.git' in path.parts:
            continue
        out[str(path.relative_to(root))] = hashlib.sha256(
            path.read_bytes()).hexdigest()
    return out


def _pass(root: Path) -> list[tuple[tuple[str, ...], int]]:
    """Run the whole sequence in `root`; return (argv, exit code) per step."""
    results = []
    previous = Path.cwd()
    os.chdir(root)
    try:
        for argv, _ in SEQUENCE:
            repo_root.cache_clear()
            load_config.cache_clear()
            with contextlib.redirect_stdout(io.StringIO()):
                results.append((argv, cli.main(list(argv))))
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()
    return results


@contextlib.contextmanager
def _tree():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        (root / 'devkit.toml').write_text(DEVKIT_TOML, encoding='utf-8')
        (root / 'Makefile').write_text(
            '.PHONY: precommit milestone\nprecommit:\n\t@true\n'
            'milestone:\n\t@true\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        yield root


def test_the_second_scaffolding_pass_is_a_byte_identical_no_op():
    with _tree() as root:
        before = _snapshot(root)
        first = _pass(root)
        after_one = _snapshot(root)
        second = _pass(root)
        after_two = _snapshot(root)

    unexpected = [(argv, code) for argv, code in first if code != 0]
    assert not unexpected, f'a scaffolding step failed on a FRESH tree: {unexpected}'

    # The probe perturbed. Without this the equality below is satisfied by two
    # passes that both did nothing.
    assert after_one != before
    assert len(after_one) > len(before) + 8, sorted(after_one)

    added = sorted(set(after_two) - set(after_one))
    removed = sorted(set(after_one) - set(after_two))
    changed = sorted(k for k in after_one
                     if k in after_two and after_one[k] != after_two[k])
    assert not (added or removed or changed), (
        f'the replay was not a no-op — added {added}, removed {removed}, '
        f'rewrote {changed}')


def test_each_verb_keeps_the_replay_contract_it_declares():
    """Idempotence is an EXIT CODE too, not just an unchanged tree.

    A fill-gaps verb that starts refusing breaks every migration script that
    chains it; a refusing verb that starts exiting 0 has probably started
    overwriting authored content. Both directions are failures, so the expected
    code is recorded per step rather than assumed uniform.
    """
    with _tree() as root:
        _pass(root)
        second = _pass(root)
    assert [code for _, code in second] == [want for _, want in SEQUENCE], second


def test_a_third_pass_still_changes_nothing():
    """Two passes can agree by coincidence — a verb that alternates between two
    states looks stable to any check that only ever runs it twice."""
    with _tree() as root:
        _pass(root)
        _pass(root)
        after_two = _snapshot(root)
        _pass(root)
        assert _snapshot(root) == after_two
