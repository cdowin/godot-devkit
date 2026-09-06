"""scene (read) — structural [resource]/[sub_resource] property values.

The consumer contract, as a real content-schema linter stated it at its SEAM:
`scene --props` must expose sub_resource/resource property VALUES, not names —
structurally enough to answer questions like "does this `next` StringName
resolve to a graph member?" without reading the raw file. Read output is write
input: the sub_resource id printed is the exact address the future
`scene set --sub-resource <id>` verb takes, spelled as the file spells it.

Contract guards, one per failure class:

  * values render under --props (the pre-fix failure was their ABSENCE), and
    a value that references other resources renders as the existing ref
    notation, so ids stay visible even inside typed arrays;
  * default (no --props) output stays name-preview only — the existing lines
    are a grepped contract and this feature is purely additive;
  * bulky packed/tile data ELIDES exactly as node props already do — the
    summary must stay smaller than the raw file on the heaviest corpus file.

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


def summarize(path, *flags: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert scene_summary.main([str(path), *flags]) == 0
    return out.getvalue()


class ResourceValues(unittest.TestCase):
    def test_props_renders_resource_and_sub_resource_values_with_refs_resolved(self):
        out = summarize(JOB_TRES, '--props')
        for line in ('## resource (JobDefinition)',
                     'id=&"forager"',
                     'display_name="Zephyr"',
                     'script=→job_definition.gd',
                     # `effects = Array[Resource]([SubResource("e_on_trail"), ...])`
                     # keeps its member ids visible — they are write-verb addresses.
                     'effects: [→e_on_trail, →e_wear]',
                     'demand_contributions: [→o_want_tools]',
                     # A sub_resource's own script ref resolves like a node's does,
                     # and SubResource refs inside a sub_resource render as →id.
                     'script=→location_condition.gd',
                     'fire_condition=→c_on_trail'):
            self.assertIn(line, out)

    def test_props_renders_sub_resource_values_and_elides_packed_data(self):
        out = summarize(ANIM_TRES, '--props')
        for line in ('[Animation_door_close] Animation',   # the write address, as the file spells it
                     'resource_name="door_close"',
                     'length=0.15',
                     'tracks/0/keys',                     # PackedFloat32Arrays inside a dict:
                     'elided'):                           # summarized, never dumped
            self.assertIn(line, out)
        self.assertNotIn('PackedFloat32Array(0, 0.04', out)

    def test_summary_stays_smaller_than_raw_on_heaviest_file(self):
        raw_lines = THEME_TRES.read_text(encoding='utf-8').count('\n')
        out = summarize(THEME_TRES, '--props')
        self.assertLess(out.count('\n'), raw_lines)
        self.assertNotIn('PackedVector2Array(', out)

    def test_default_output_is_a_name_preview_and_not_one_value_line_more(self):
        # The long-standing default lines are a grepped contract.
        out = summarize(JOB_TRES)
        for line in ('## resource (JobDefinition)', 'script, id, display_name'):
            self.assertIn(line, out)
        self.assertNotIn('&"forager"', out)                 # no values w/o --props
        out = summarize(ANIM_TRES)
        self.assertIn('[Animation_door_close] Animation  resource_name, length, step', out)
        for value in ('resource_name="door_close"', 'length=0.15'):
            self.assertNotIn(value, out)
