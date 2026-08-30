"""Tier 3 — restoring what `PackedScene.pack()` + `ResourceSaver.save()` drop.

The strongest case here is the last one: take a REAL scene, degrade it exactly
the way `save()` does, and check that canonicalize puts it back byte-for-byte.
Anything the tool invents rather than derives would show up as a diff.
"""
from __future__ import annotations

import contextlib
import io
import re
import unittest

from support import available_consumers, temp_repo

from godot_devkit.godot.write import scene_canonicalize
from godot_devkit.core.project import repo_root

QUARANTINE = 'scenes/world/maps/quarantine.tscn'
UID_ATTR = re.compile(r' uid="uid://[0-9a-z]+"')
INDEX_ATTR = re.compile(r' index="\d+"')


def degrade(text: str) -> str:
    """What `ResourceSaver.save()` writes: no header uid, path-only refs, and no
    `index=` on instance-child overrides."""
    lines = []
    for line in text.split('\n'):
        if line.startswith(('[ext_resource ', '[gd_scene ', '[gd_resource ')):
            line = UID_ATTR.sub('', line)
        elif line.startswith('[node '):
            line = INDEX_ATTR.sub('', line)
        lines.append(line)
    return '\n'.join(lines)


def canonicalize_in_repo(*argv: str) -> tuple[int, str]:
    repo_root.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = scene_canonicalize.main([*argv])
    repo_root.cache_clear()
    return code, buffer.getvalue()


class RestoresWhatPackDrops(unittest.TestCase):
    def test_restores_all_four_losses(self) -> None:
        with temp_repo('canon_repo') as root:
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        # 1. uid-in-refs, from the .gd sidecar and from the .tscn's own header
        self.assertIn('uid="uid://dcanonlogic" path="res://systems/logic.gd"', text)
        self.assertIn('uid="uid://dcanonpanel" path="res://scenes/panel.tscn"', text)
        # 2. the file's own header uid, recovered from what already references it
        self.assertIn('[gd_scene load_steps=3 format=3 uid="uid://dcanonpacked"]', text)
        # 3. index= — without it this override reloads as a NEW SIBLING
        self.assertIn('[node name="Footer" parent="Panel" index="1"]', text)
        # 4. the editable-children marker
        self.assertIn('[editable path="Panel"]', text)

    def test_index_is_counted_off_the_base_scene_not_guessed(self) -> None:
        """Footer is the SECOND child of panel.tscn's root, so index must be 1."""
        with temp_repo('canon_repo') as root:
            canonicalize_in_repo('scenes/packed.tscn')
            text = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertIn('index="1"', text)
        self.assertNotIn('index="0"', text)

    def test_is_idempotent(self) -> None:
        with temp_repo('canon_repo') as root:
            canonicalize_in_repo('scenes/packed.tscn')
            once = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            twice = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertEqual(twice, once)
        self.assertIn('already canonical', out)
        self.assertEqual(code, scene_canonicalize.EXIT_OK)

    def test_a_crlf_file_keeps_its_endings_through_a_restoration(self) -> None:
        """Canonicalize restores what pack() dropped — it does not get to
        normalize every line ending in the file on the way through."""
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            crlf = scene.read_text(encoding='utf-8').replace('\n', '\r\n').encode()
            scene.write_bytes(crlf)
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            raw = scene.read_bytes()
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn(b'uid="uid://dcanonlogic"', raw)          # it DID restore
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''),
                         'restoration minted lone-LF lines in a CRLF file')

    def test_a_non_utf8_file_is_refused_not_a_traceback(self) -> None:
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            scene.write_bytes(b'[gd_scene format=3]\n\xff\xfe not utf-8\n')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS)
        self.assertIn('REFUSED', out)

    def test_reports_and_refuses_a_uid_it_cannot_resolve(self) -> None:
        """A uid that cannot be derived is left alone and named — inventing one
        would be worse than the missing ref."""
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            scene.write_text(scene.read_text(encoding='utf-8').replace(
                'res://systems/logic.gd', 'res://systems/ghost.gd'), encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = scene.read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS)
        self.assertIn('UNRESOLVED', out)
        self.assertIn('ghost.gd', out)
        self.assertIn('path="res://systems/ghost.gd"', text)


class RealSceneRoundTrip(unittest.TestCase):
    @unittest.skipUnless(any((repo / QUARANTINE).is_file() for repo in available_consumers()),
                         'quarantine.tscn not available')
    def test_degraded_real_scene_is_restored_byte_for_byte(self) -> None:
        import os
        import tempfile
        from pathlib import Path

        repo = next(r for r in available_consumers() if (r / QUARANTINE).is_file())
        original = (repo / QUARANTINE).read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            packed = Path(tmp) / 'packed.tscn'
            packed.write_text(degrade(original), encoding='utf-8')
            self.assertNotEqual(degrade(original), original, 'degradation was a no-op')
            previous = os.getcwd()
            os.chdir(repo)
            try:
                canonicalize_in_repo(str(packed))
                restored = packed.read_text(encoding='utf-8')
            finally:
                os.chdir(previous)
        # The header uid is the one loss that cannot be recovered for a file
        # outside its own repo path — everything else must match exactly.
        self.assertEqual(UID_ATTR.sub('', restored.split('\n')[0]), restored.split('\n')[0])
        self.assertEqual('\n'.join(restored.split('\n')[1:]),
                         '\n'.join(original.split('\n')[1:]))


if __name__ == '__main__':
    unittest.main()
