"""scene (read) — structural [resource]/[sub_resource] property values.

The consumer contract, as a real content-schema linter stated it at its SEAM:
`scene --props` must expose sub_resource/resource property VALUES, not names —
structurally enough to answer questions like "does this `next` StringName
resolve to a graph member?" without reading the raw file. Read output is write
input: the sub_resource id printed is the exact address the future
`scene set --sub-resource <id>` verb takes, spelled as the file spells it.

Contract guards, one per failure class:

  * values render under --props (the pre-fix failure was their ABSENCE);
  * default (no --props) output stays name-preview only — the existing lines
    are a grepped contract and this feature is purely additive;
  * bulky packed/tile data ELIDES exactly as node props already do — the
    summary must stay smaller than the raw file on the heaviest corpus file;
  * a value that references other resources renders as the existing ref
    notation, so ids stay visible even inside typed arrays.

Corpus files are read-only test subjects — never mutated here.
"""
from __future__ import annotations

import contextlib
import io
import unittest

from support import FIXTURES

from godot_devkit.godot.read import scene_summary

CORPUS = FIXTURES / 'corpus'
# A scrubbed real consumer .tres: [resource] body + 10 typed sub_resources.
JOB_TRES = CORPUS / 'hand_authored' / 'data' / 'jobs' / 'forager.tres'
# AnimationLibrary: sub_resources whose track keys carry PackedFloat32Arrays.
ANIM_TRES = CORPUS / 'editor_written' / 'data' / 'animations' / 'door_base.tres'
# The heaviest corpus file (521 raw lines, 31 sub_resources).
THEME_TRES = CORPUS / 'editor_written' / 'resources' / 'themes' / 'menu_theme.tres'
# A .tscn with sub_resources, to prove the scene path renders values too.
SCENE_TSCN = CORPUS / 'hand_authored' / 'scenes' / 'modals' / 'rest_moment.tscn'


def summarize(path, *flags: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = scene_summary.main([str(path), *flags])
    assert code == 0
    return out.getvalue()


class ResourceValues(unittest.TestCase):
    """[resource] body of a .tres — previously absent from the output entirely."""

    def test_props_renders_resource_values(self):
        out = summarize(JOB_TRES, '--props')
        self.assertIn('## resource (JobDefinition)', out)
        self.assertIn('id=&"forager"', out)
        self.assertIn('display_name="Zephyr"', out)
        self.assertIn('script=→job_definition.gd', out)

    def test_ref_arrays_render_as_ref_lists(self):
        # `effects = Array[Resource]([SubResource("e_on_trail"), ...])` must
        # keep its member ids visible — they are write-verb addresses.
        out = summarize(JOB_TRES, '--props')
        self.assertIn('effects: [→e_on_trail, →e_wear]', out)
        self.assertIn('demand_contributions: [→o_want_tools]', out)

    def test_default_shows_resource_names_not_values(self):
        out = summarize(JOB_TRES)
        self.assertIn('## resource (JobDefinition)', out)
        self.assertIn('script, id, display_name', out)      # name preview
        self.assertNotIn('&"forager"', out)                 # no values w/o --props


class SubResourceValues(unittest.TestCase):
    def test_props_renders_sub_resource_values(self):
        out = summarize(ANIM_TRES, '--props')
        # The id line is the write address, spelled as the file spells it.
        self.assertIn('[Animation_door_close] Animation', out)
        self.assertIn('resource_name="door_close"', out)
        self.assertIn('length=0.15', out)

    def test_sub_resource_ref_values_resolve(self):
        out = summarize(JOB_TRES, '--props')
        # A sub_resource's own script ref resolves like a node's does.
        self.assertIn('script=→location_condition.gd', out)
        # SubResource refs inside a sub_resource render as →id.
        self.assertIn('fire_condition=→c_on_trail', out)

    def test_tscn_sub_resources_render_values_too(self):
        out = summarize(SCENE_TSCN, '--props')
        self.assertIn('[Animation_open] Animation', out)
        self.assertIn('resource_name="', out)  # a real value line, not just names

    def test_default_output_is_name_preview_only(self):
        # The long-standing default lines are a contract: id + type + key
        # names, and NOT one value line more.
        out = summarize(ANIM_TRES)
        self.assertIn('[Animation_door_close] Animation  resource_name, length, step', out)
        self.assertNotIn('resource_name="door_close"', out)
        self.assertNotIn('length=0.15', out)


class Elision(unittest.TestCase):
    def test_packed_data_elides(self):
        out = summarize(ANIM_TRES, '--props')
        # Track keys carry PackedFloat32Arrays inside a dictionary — the
        # bytes must never be dumped, only summarized.
        self.assertIn('tracks/0/keys', out)
        self.assertNotIn('PackedFloat32Array(0, 0.04', out)
        self.assertIn('elided', out)

    def test_summary_stays_smaller_than_raw_on_heaviest_file(self):
        raw_lines = THEME_TRES.read_text(encoding='utf-8').count('\n')
        out = summarize(THEME_TRES, '--props')
        self.assertLess(out.count('\n'), raw_lines)
        self.assertNotIn('PackedVector2Array(', out)


if __name__ == '__main__':
    unittest.main()
