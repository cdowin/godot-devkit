"""Tier 3 — restoring what `PackedScene.pack()` + `ResourceSaver.save()` drop.

Each case degrades a fixture the way `save()` does and checks that canonicalize
puts back exactly what was lost — anything the tool invents rather than derives
shows up as a diff. The same proof at SCALE, over scrubbed real-world scenes, is
`tests/fixtures/corpus/` in test_tscn_roundtrip.py.
"""
from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from support import run_check, temp_repo

from godot_devkit.godot.write import scene_canonicalize

EDITABLE_SECTION = re.compile(r'^\[editable path="([^"]*)"\]', re.M)


def canonicalize_in_repo(*argv: str) -> tuple[int, str]:
    return run_check(SimpleNamespace(run=scene_canonicalize.main), argv=list(argv))


class RestoresWhatPackDrops(unittest.TestCase):
    def test_restores_all_three_losses_idempotently_keeping_crlf_endings(self) -> None:
        # On a CRLF copy of the fixture: canonicalize restores what pack()
        # dropped — it does not get to normalize every line ending in the
        # file on the way through.
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            scene.write_bytes(scene.read_text(encoding='utf-8').replace('\n', '\r\n').encode())
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            raw = scene.read_bytes()
            again_code, again_out = canonicalize_in_repo('scenes/packed.tscn')
            twice = scene.read_bytes()
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        text = raw.decode('utf-8')
        # 1. uid-in-refs, from the .gd sidecar and from the .tscn's own header
        self.assertIn('uid="uid://dcanonlogic" path="res://systems/logic.gd"', text)
        self.assertIn('uid="uid://dcanonpanel" path="res://scenes/panel.tscn"', text)
        # 2. the file's own header uid, recovered from what already references it
        self.assertIn('[gd_scene load_steps=3 format=3 uid="uid://dcanonpacked"]', text)
        # 3. index= — without it this override reloads as a NEW SIBLING. Footer
        #    is the SECOND child of panel.tscn's root: counted, never guessed.
        self.assertIn('[node name="Footer" parent="Panel" index="1"]', text)
        self.assertNotIn('index="0"', text)
        # There is no fourth: `[editable]` is authored state, not a pack() loss
        # — packed.tscn overrides panel.tscn's Footer, which is an override and
        # not an editable instance, and Godot writes exactly this file without
        # a marker (see EditableMarkersAreAuthoredNotDerived).
        self.assertEqual(EDITABLE_SECTION.findall(text), [], text)
        self.assertNotIn('EDITABLE', out, out)
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''),
                         'restoration minted lone-LF lines in a CRLF file')
        self.assertEqual(twice, raw)
        self.assertIn('already canonical', again_out)
        self.assertEqual(again_code, scene_canonicalize.EXIT_OK)

    def test_refuses_a_uid_it_cannot_resolve_and_a_file_that_is_not_utf8(self) -> None:
        # A uid that cannot be derived is left alone and named — inventing one
        # would be worse than the missing ref. Bytes that do not decode are
        # refused, never a traceback.
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            scene.write_text(scene.read_text(encoding='utf-8').replace(
                'res://systems/logic.gd', 'res://systems/ghost.gd'), encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = scene.read_text(encoding='utf-8')
            scene.write_bytes(b'[gd_scene format=3]\n\xff\xfe not utf-8\n')
            bad_code, bad_out = canonicalize_in_repo('scenes/packed.tscn')
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS)
        self.assertIn('UNRESOLVED', out)
        self.assertIn('ghost.gd', out)
        self.assertIn('path="res://systems/ghost.gd"', text)
        self.assertEqual(bad_code, scene_canonicalize.EXIT_FINDINGS)
        self.assertIn('REFUSED', bad_out)


# --- [editable] is authored, never derived ------------------------------------
# 0.24.0/bugs/scene-canonicalize-invents-an-editable-marker. `[editable path=]`
# records ONE thing: the editor's per-instance "Editable Children" toggle. In
# the engine (scene/resources/packed_scene.cpp) it is written on pack only from
# `p_owner->is_editable_instance(p_node)` — the live flag — and on load it is
# applied LAST, after every node and property already exists, by calling
# `set_editable_instance(ei, true)`. No override anywhere consults it. So an
# instance whose children carry overrides is not thereby an editable instance,
# and deriving the marker from the node tree invents authored state: the next
# load hands a human a sub-tree the scene never said was editable, and the next
# editor save writes the marker out for good.
#
# The corpus says the same thing without the engine: it holds 21 markers on
# hosts and 7 scenes whose instance children are overridden with NO marker —
# the two facts are independent in BOTH directions, which no derivation rule
# can produce. The invent direction is pinned on packed.tscn above; the
# opposite direction — and it would be worse — is here: a scene that DOES
# declare Editable Children, carrying the two degradations `pack()` applies (a
# ref that lost its uid, an override that lost its `index=`), must come back
# with both restored and its marker untouched, neither duplicated nor dropped.
# It keeps its own header uid so the run has nothing unresolved to report.

class EditableMarkersAreAuthoredNotDerived(unittest.TestCase):
    def test_a_declared_marker_survives_a_restoration(self) -> None:
        marked = ('[gd_scene load_steps=2 format=3 uid="uid://dcanonmarked"]\n\n'
                  '[ext_resource type="PackedScene"'
                  ' path="res://scenes/panel.tscn" id="1_panel"]\n\n'
                  '[node name="Marked" type="Node2D"]\n\n'
                  '[node name="Panel" parent="."'
                  ' instance=ExtResource("1_panel")]\n\n'
                  '[node name="Footer" parent="Panel"]\nvisible = false\n\n'
                  '[editable path="Panel"]\n')
        with temp_repo('canon_repo') as root:
            (root / 'scenes/marked.tscn').write_text(marked, encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/marked.tscn')
            text = (root / 'scenes/marked.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('uid="uid://dcanonpanel"', text)   # it DID restore
        self.assertIn('index="1"', text)
        self.assertEqual(EDITABLE_SECTION.findall(text), ['Panel'], text)


# --- an INHERITED scene's root IS an instancing ancestor ----------------------
# 0.24.0/bugs/canonicalize-drops-index-on-a-typed-node. An inherited scene's
# root is written `[node name="X" instance=ExtResource(base)]`, so its children
# ARE the base's children and an override there is an instance-child override
# like any other. `_instance_host` walked ancestors down to depth 1 and stopped,
# so it never reached the root: every override directly under an inherited root
# lost its `index=` and got a "no instancing ancestor was found" refusal instead
# of the ordinal the base plainly gives it. Measured on a real hand-authored
# tree before the fix: 3 such overrides across 2 scenes.
#
# The other direction is the trap, and it is the sibling bug's: a node the scene
# CREATES (`type=` / `instance=`) is not placed by any base, so no ordinal
# exists to count and writing one invents authored position. Both directions are
# asserted below.
SHELL_BASE = ('[gd_scene format=3 uid="uid://dcanonshell"]\n\n'
              '[node name="Shell" type="Control"]\n\n'
              '[node name="Frame" type="Panel" parent="."]\n\n'
              '[node name="Inner" type="Control" parent="."]\n\n'
              '[node name="Paper" type="ColorRect" parent="Inner"]\n\n'
              '[node name="Border" type="Panel" parent="Inner"]\n\n'
              '[node name="Content" type="Control" parent="Inner"]\n')
# The inherited scene, canonical. Two overrides — one of a base child of the
# root (Inner is the shell's SECOND child, so 1), one of a base GRANDchild whose
# only instancing ancestor is the root (Content is the THIRD child of Inner, so
# 2) — and two nodes this scene creates, which carry no index and must not gain
# one.
INHERITED = ('[gd_scene load_steps=2 format=3 uid="uid://dcanoninherit"]\n\n'
             '[ext_resource type="PackedScene" uid="uid://dcanonshell"'
             ' path="res://scenes/shell.tscn" id="1_shell"]\n\n'
             '[node name="Shell" instance=ExtResource("1_shell")]\n\n'
             '[node name="Inner" parent="." index="1"]\nvisible = false\n\n'
             '[node name="Content" parent="Inner" index="2"]\n'
             'mouse_filter = 2\n\n'
             '[node name="Body" type="VBoxContainer" parent="Inner/Content"]\n\n'
             '[node name="Nested" parent="." instance=ExtResource("1_shell")]\n')
INDEX_ATTR = re.compile(r' index="\d+"')


def strip_indexes(text: str) -> str:
    """The `index=` half of the `save()` degradation, on the node lines."""
    return '\n'.join(INDEX_ATTR.sub('', line) if line.startswith('[node ') else line
                     for line in text.split('\n'))


def over_shell(scene_text: str, mid: str | None = None) -> tuple[int, str, str]:
    """Canonicalize `scene_text` in a repo whose `res://scenes/shell.tscn` is
    SHELL_BASE — and, given `mid`, whose `res://scenes/mid.tscn` is that text
    -> (exit code, report, the file as it was left)."""
    with temp_repo('canon_repo') as root:
        (root / 'scenes/shell.tscn').write_text(SHELL_BASE, encoding='utf-8')
        if mid is not None:
            (root / 'scenes/mid.tscn').write_text(mid, encoding='utf-8')
        (root / 'scenes/subject.tscn').write_text(scene_text, encoding='utf-8')
        code, out = canonicalize_in_repo('scenes/subject.tscn')
        text = (root / 'scenes/subject.tscn').read_text(encoding='utf-8')
    return code, out, text


class AnInheritedRootIsAnInstanceHost(unittest.TestCase):
    def test_the_whole_inherited_scene_round_trips_byte_for_byte(self) -> None:
        # The whole property at unit scale: strip what `save()` drops,
        # restore, and get the committed bytes back — no more and no less.
        # Both overrides get their ordinal counted through the root, and
        # neither created node gains one.
        self.assertNotEqual(strip_indexes(INHERITED), INHERITED)
        code, out, text = over_shell(strip_indexes(INHERITED))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertEqual(text, INHERITED)

    def test_an_override_the_base_does_not_place_is_refused_not_guessed(self) -> None:
        # A type-less node under an inherited root IS an override — but if the
        # base has no such child there is no ordinal, and the run says so
        # instead of picking one.
        orphan = INHERITED.replace('[node name="Inner" parent="." index="1"]',
                                   '[node name="Ghost" parent="."]')
        code, out, text = over_shell(strip_indexes(orphan))
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS, out)
        self.assertIn('UNRESOLVED', out)
        self.assertIn('Ghost', out)
        self.assertIn('[node name="Ghost" parent="."]\n', text)


# --- a base whose OWN root is instanced cannot be counted ----------------------
# `_instance_host` reaching the root (above) made a whole class of override
# resolvable — and made a second class RESOLVE WRONG. A `.tscn` holds only the
# sections that file writes, so when the base's own root carries `instance=`,
# its base's children are not in it: `child_index` counts the overrides the mid
# scene declares and returns an ordinal that is too small. Godot reads `index=`
# as the child's POSITION, so the verb wrote a value that REORDERS the node on
# every load, printed `1 change(s), 0 unresolved` and exited 0. v0.23.0 refused
# the same input (its walk stopped short of the root) — a fix that turned a
# refusal into a wrong answer.
#
# `MID` overrides only `Inner`, so counting MID's own sections puts `Inner` at
# ordinal 0 where the shell plainly places it at 1.
MID = ('[gd_scene load_steps=2 format=3 uid="uid://dcanonmid"]\n\n'
       '[ext_resource type="PackedScene" uid="uid://dcanonshell"'
       ' path="res://scenes/shell.tscn" id="1_shell"]\n\n'
       '[node name="Shell" instance=ExtResource("1_shell")]\n\n'
       '[node name="Inner" parent="." index="1"]\nvisible = false\n')
# Inherited from the INHERITED scene. `Inner` is still the shell's second child,
# so the only correct answer is 1 — and the only correct answer available from
# mid.tscn alone is "I cannot tell".
CHAINED = ('[gd_scene load_steps=2 format=3 uid="uid://dcanonchain"]\n\n'
           '[ext_resource type="PackedScene" uid="uid://dcanonmid"'
           ' path="res://scenes/mid.tscn" id="1_mid"]\n\n'
           '[node name="Shell" instance=ExtResource("1_mid")]\n\n'
           '[node name="Inner" parent="." index="1"]\nmodulate = Color(1, 0, 0, 1)\n')


class AChainedBaseIsRefusedNotCounted(unittest.TestCase):
    def test_an_override_under_a_chained_base_is_refused_naming_the_chain(self) -> None:
        # The verb's hard rule: it cannot guarantee a correct result, so it
        # refuses, says why, writes nothing and exits non-zero. And the why is
        # the reason that is actually true: `Inner` IS in mid.tscn, so a
        # refusal saying "cannot count Inner in mid.tscn" sends a reader to
        # look for it, find it, and conclude the tool is broken.
        code, out, text = over_shell(strip_indexes(CHAINED), mid=MID)
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS, out)
        self.assertIn('UNRESOLVED', out)
        self.assertIn('itself an inherited scene', out)
        self.assertIn('res://scenes/mid.tscn', out)
        self.assertEqual(text, strip_indexes(CHAINED),
                         'a refusal wrote to the file')


# --- a node the scene CREATES gains no index, wherever its PARENT came from ---
# 0.24.0/bugs/index-is-derivable-under-an-instanced-parent proposed keying the
# restoration off "is this node's PARENT an instanced subtree?" instead of off
# `type=`/`instance=` on the node itself, on the reading that a created node
# under an instanced parent is positioned among that base's children and so has
# a derivable ordinal. The ORDINAL is derivable. Whether the engine writes the
# attribute is not, and the corpus refuses the rule in both directions:
#
#   * the EDITOR-WRITTEN half — 194 scenes, all round-tripped through
#     ResourceSaver — has 1008 created nodes and NOT ONE carries an `index=`,
#     including 87 whose parent is a node the base provides. It holds no
#     inherited scene with a written child, so it cannot speak to that case.
#   * the HAND-AUTHORED half — 116 scenes, every one carrying a `;` comment and
#     so never through ResourceSaver — contradicts itself at the one position in
#     dispute: 10 created nodes directly under an inherited root carry an
#     append-correct `index=` and 10 more, same tree, same position, carry none
#     (6 appending into an empty base container, 4 after a 4-child base root).
#     Nothing structural separates the halves.
#
# Measured, degrade -> canonicalize over every tracked scene, before it was
# refused: the rule as filed invents 38 `index=` on the hand-authored tree and
# 87 on the editor-written one, and takes the latter from 0 round-trip failures
# to 26. Narrowed to inherited scenes it still invents 4. Each fixture below is
# one of those shapes, and the ordinal a parent-keyed rule would have written
# is named beside it. Both measurements are RECORDED here, not re-runnable:
# nothing in this package reaches outside its own checkout (CLAUDE.md rule 8),
# and what the fixtures below pin is the resulting BEHAVIOUR.
#
# PLAIN_HOST: `Added` hangs off the instance node itself (an append is 2);
# `Deep` off a base child with 3 children of its own (3); `Slot0/1/2` fill a
# base container the base leaves empty — the shape a next-free-slot fallback
# turns into 0, 1, 2, and the shape that made that fallback invent 505
# attributes across the two trees.
PLAIN_HOST = ('[gd_scene load_steps=2 format=3 uid="uid://dcanonplain"]\n\n'
              '[ext_resource type="PackedScene" uid="uid://dcanonshell"'
              ' path="res://scenes/shell.tscn" id="1_shell"]\n\n'
              '[node name="Host" type="Node2D"]\n\n'
              '[node name="Shell" parent="." instance=ExtResource("1_shell")]\n\n'
              '[node name="Inner" parent="Shell" index="1"]\nvisible = false\n\n'
              '[node name="Added" type="Label" parent="Shell"]\n\n'
              '[node name="Deep" type="Label" parent="Shell/Inner"]\n\n'
              '[node name="Slot0" type="Label" parent="Shell/Inner/Content"]\n\n'
              '[node name="Slot1" type="Label" parent="Shell/Inner/Content"]\n\n'
              '[node name="Slot2" type="Label" parent="Shell/Inner/Content"]\n')
# The inherited half. `FirstBody`/`SecondBody` sit exactly where the measured
# tree splits 10-for/10-against (an append is 2 and 3 — THE disputed position);
# `Slot` appends into a base container the base leaves empty (0 — no less
# invented for being the only number available; 6 real scenes, all
# `Card/Inner/Content/Body` shaped); `Row` hangs off a node this scene created,
# inside an instanced subtree (one real scene where 2 of 15 siblings carry a
# hand-typed index).
INHERITED_CREATES_BODIES = (
    '[gd_scene load_steps=2 format=3 uid="uid://dcanonbodies"]\n\n'
    '[ext_resource type="PackedScene" uid="uid://dcanonshell"'
    ' path="res://scenes/shell.tscn" id="1_shell"]\n\n'
    '[node name="Shell" instance=ExtResource("1_shell")]\n\n'
    '[node name="Inner" parent="." index="1"]\nvisible = false\n\n'
    '[node name="FirstBody" type="VBoxContainer" parent="."]\n\n'
    '[node name="SecondBody" type="VBoxContainer" parent="."]\n\n'
    '[node name="Row" type="Label" parent="FirstBody"]\n\n'
    '[node name="Slot" type="Label" parent="Inner/Content"]\n')


class ACreatedNodeGainsNoIndexWhateverItsParentIs(unittest.TestCase):
    """The refusal matrix for the created-node position, as one byte-for-byte
    round trip per fixture: every created node line comes back bare, and the
    one override in each — `Inner`, the base root's SECOND child — comes back
    as `1` under an instance node and under an inherited root alike, which is
    the control that stops the case from passing on a tool that does nothing."""

    def test_both_fixtures_round_trip_byte_for_byte(self) -> None:
        for fixture in (PLAIN_HOST, INHERITED_CREATES_BODIES):
            with self.subTest(fixture=fixture.split('\n')[0]):
                self.assertNotEqual(strip_indexes(fixture), fixture)
                code, out, text = over_shell(strip_indexes(fixture))
                self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
                self.assertEqual(text, fixture)
