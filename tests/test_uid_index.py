"""index/uid_index — evidence gathering must survive an imperfect tree.

`from_repo_references` walks every tracked `.tscn`/`.tres` for the uid the
rest of the repo already uses. `git ls-files` lists what the INDEX knows, not
what is on disk — a tracked-but-locally-deleted file used to crash the walk
(FileNotFoundError) mid `scene canonicalize` / `scene add`.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import temp_repo

from godot_devkit.godot.index.uid_index import UidIndex

DRIFTED = ['project.godot', 'systems/rule.gd', 'systems/rule.gd.uid',
           'scenes/clean.tscn', 'scenes/drifted.tscn', 'data/drifted.tres']


class CrossReference(unittest.TestCase):
    def test_existing_resource_uid_comes_only_from_its_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix, header in (('.tres', 'gd_resource'), ('.tscn', 'gd_scene')):
                path = root / ('target' + suffix)
                for own_uid in (None, 'uid://dtarget'):
                    identity = f' uid="{own_uid}"' if own_uid else ''
                    path.write_text(
                        f'[{header} format=3{identity}]\n\n'
                        '[ext_resource type="Script" uid="uid://dscript" '
                        'path="res://script.gd" id="1"]\n', encoding='utf-8')
                    index = UidIndex(root)
                    index._cross_reference = {'res://' + path.name: 'uid://dscript'}
                    self.assertEqual(index.of('res://' + path.name), own_uid)

    def test_skips_a_tracked_but_locally_deleted_file(self) -> None:
        from godot_devkit.core.project import load_config, repo_root
        with temp_repo('uid_repo', only=DRIFTED) as root:
            repo_root.cache_clear()
            load_config.cache_clear()
            (root / 'scenes/clean.tscn').unlink()   # still in the git index
            found = UidIndex(root).from_repo_references('res://systems/rule.gd')
            repo_root.cache_clear()
            load_config.cache_clear()
        # The surviving files still supply evidence; the deleted one is skipped.
        self.assertIsNotNone(found)
        self.assertTrue(found.startswith('uid://'), found)


if __name__ == '__main__':
    unittest.main()
