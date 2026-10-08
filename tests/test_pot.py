"""`godot-devkit pot` — the editor's POT, generated without the editor.

The proof is byte identity: `tests/fixtures/pot_repo/locale/fixture.pot` was
written by hand from `template_generator.cpp` and the GDScript parser plugin
(Godot 4.7), one script line per extraction rule, and the generator must
reproduce it exactly. Then the two sins: a stale POT the check passes (drift
must name each missing and extra msgid), and a script this cannot read that
the verb skips (each is a refusal, exit 2, never a smaller POT). The verb
itself, in a throwaway repo, is `test_pot_verb.py`.
"""
from __future__ import annotations

import contextlib
import io
import shutil
from pathlib import Path

import pytest

from support import FIXTURES

from godot_devkit.godot.write import pot

FIXTURE = 'pot_repo'
POT_REL = 'locale/fixture.pot'
MENU = 'ui/menu.gd'
FIXTURE_FILES = 2
FIXTURE_MSGIDS = 40


def test_the_fixture_project_generates_its_pot_byte_for_byte() -> None:
    root = FIXTURES / FIXTURE
    fresh = pot.generate(root)
    assert fresh.text == (root / POT_REL).read_bytes().decode('utf-8')
    assert (fresh.files, fresh.msgids) == (FIXTURE_FILES, FIXTURE_MSGIDS)


def test_check_names_each_missing_and_extra_msgid_and_reorders_as_drift() -> None:
    root = FIXTURES / FIXTURE
    fresh = pot.generate(root)
    committed = fresh.text
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert pot._check(POT_REL, committed, fresh) == pot.EXIT_OK
    assert f'PASS — {POT_REL} matches the manifest: 2 file(s) scanned, 40 msgid(s)' in out.getvalue()

    stale = committed.replace('msgid "Tooltip"', 'msgid "Old tooltip"')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert pot._check(POT_REL, stale, fresh) == pot.EXIT_DRIFT
    assert '  MISSING  "Tooltip"' in out.getvalue()
    assert '  EXTRA  "Old tooltip"' in out.getvalue()
    assert '1 missing, 1 extra' in out.getvalue()

    # Same msgids, one reference line gone: still drift, and it says where.
    moved = committed.replace('#: ui/menu.gd:26\n', '')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert pot._check(POT_REL, moved, fresh) == pot.EXIT_DRIFT
    assert f'  DRIFT  {POT_REL}:' in out.getvalue()


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / 'project'
    shutil.copytree(FIXTURES / FIXTURE, root)
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding='utf-8')
    assert old in text
    path.write_text(text.replace(old, new), encoding='utf-8')


MANIFEST = 'PackedStringArray("res://ui/menu.gd", "res://ui/dialog.gd")'
REFUSALS = {
    'a scene in the manifest': (
        'project.godot', MANIFEST, 'PackedStringArray("res://ui/menu.gd", "res://ui/hud.tscn")',
        'cannot parse (only .gd): res://ui/hud.tscn'),
    'an empty manifest': (
        'project.godot', MANIFEST, 'PackedStringArray()', 'an empty manifest scans nothing'),
    'a missing script': (
        'project.godot', MANIFEST, 'PackedStringArray("res://ui/gone.gd")',
        'names res://ui/gone.gd, which cannot be read'),
    'the editor built-ins': (
        'project.godot', '[internationalization]\n',
        '[internationalization]\n\nlocale/translation_add_builtin_strings_to_pot=true\n',
        'translation_add_builtin_strings_to_pot is true'),
    'a script that does not parse': (
        MENU, 'func pick(', 'func pick((', f'{MENU}:69: cannot parse it'),
    'a fold this cannot compute': (
        MENU, 'tr(&"Name")', 'tr("%.1f" % 1.5)', f'{MENU}:32: cannot fold the format'),
    'a property of a preloaded resource': (
        MENU, 'tr(&"Name")', 'tr(preload("res://data/item.tres").title)',
        f'{MENU}:32: preload("res://data/item.tres").title may reduce to a string'),
}


@pytest.mark.parametrize('case', sorted(REFUSALS))
def test_what_it_cannot_read_it_refuses_rather_than_writing_a_smaller_pot(
        tmp_path: Path, case: str) -> None:
    file, old, new, reason = REFUSALS[case]
    root = _tree(tmp_path)
    _edit(root / file, old, new)
    with pytest.raises(pot.Refusal) as caught:
        pot.generate(root)
    assert reason in str(caught.value)
