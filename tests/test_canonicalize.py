"""Tier 3 — restoring what `PackedScene.pack()` + `ResourceSaver.save()` drop.

Each case degrades a fixture the way `save()` does and checks that canonicalize
puts back exactly what was lost — anything the tool invents rather than derives
shows up as a diff. The same proof over a REAL consumer scene is `make smoke`'s
`canonicalize round trip` row, which picks the scene the degradation costs most.
"""
from __future__ import annotations

import contextlib
import io
import re
import unittest
from pathlib import Path

from support import FIXTURES, temp_repo

from godot_devkit.godot.write import scene_canonicalize
from godot_devkit.godot.format.tscn_document import read_scene_text
from godot_devkit.godot.index.uid_index import UidIndex
from godot_devkit.core.project import repo_root


def canonicalize_in_repo(*argv: str) -> tuple[int, str]:
    repo_root.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = scene_canonicalize.main([*argv])
    repo_root.cache_clear()
    return code, buffer.getvalue()


class RestoresWhatPackDrops(unittest.TestCase):
    def test_restores_all_three_losses(self) -> None:
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
        # There is no fourth: `[editable]` is authored state, not a pack() loss
        # — see EditableMarkersAreAuthoredNotDerived below.

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
# can produce.
CORPUS = FIXTURES / 'corpus'
# Floors, so a corpus that rots into vacuity fails here instead of proving
# less. 7 scenes reproduce the invention; quarantine.tscn carries the 21
# markers that prove the opposite failure would be caught.
OVERRIDDEN_SCENE_FLOOR = 7
DECLARED_MARKER_FLOOR = 21
EDITABLE_SECTION = re.compile(r'^\[editable path="([^"]*)"\]', re.M)


def editable_paths(text: str) -> list[str]:
    return EDITABLE_SECTION.findall(text)


class EditableMarkersAreAuthoredNotDerived(unittest.TestCase):
    """The committed corpus is real consumer structure that runs on CI too, so
    this is the bug's own 21-file corpus made portable."""

    def test_no_corpus_scene_gains_or_loses_a_marker(self) -> None:
        scenes = overridden = declared = 0
        for slice_name in ('nb', 'tr'):
            root = CORPUS / slice_name
            uids = UidIndex(root)
            bases = scene_canonicalize.BaseScenes(root)
            for path in sorted(root.rglob('*.tscn')):
                before = read_scene_text(path)
                after, _report = scene_canonicalize.canonicalize(
                    path, root, uids, bases)
                self.assertEqual(
                    editable_paths(after), editable_paths(before),
                    f'{path.relative_to(CORPUS)}: canonicalize changed the '
                    f'[editable] sections')
                scenes += 1
                doc = scene_canonicalize.TscnDocument(before, path)
                if any('type' not in n.attrs and 'instance' not in n.attrs
                       for n in doc.nodes):
                    overridden += 1
                declared += len(editable_paths(before))
        self.assertGreaterEqual(overridden, OVERRIDDEN_SCENE_FLOOR,
                                f'{scenes} scenes scanned but only {overridden} '
                                'carry an instance-child override — the corpus '
                                'no longer reproduces the bug')
        self.assertGreaterEqual(declared, DECLARED_MARKER_FLOOR,
                                'the corpus no longer carries a scene whose '
                                'markers a removal would destroy')

    def test_a_declared_marker_survives_a_restoration(self) -> None:
        """The OPPOSITE failure, and it would be worse: a scene that DOES
        declare Editable Children, carrying the two degradations `pack()`
        applies — a ref that lost its uid, an override that lost its `index=`
        — must come back with both restored and its marker untouched, neither
        duplicated nor dropped. It keeps its own header uid so the run has
        nothing unresolved to report; that third loss is the case above."""
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
        self.assertEqual(editable_paths(text), ['Panel'], text)


# --- an INHERITED scene's root IS an instancing ancestor ----------------------
# 0.24.0/bugs/canonicalize-drops-index-on-a-typed-node. An inherited scene's
# root is written `[node name="X" instance=ExtResource(base)]`, so its children
# ARE the base's children and an override there is an instance-child override
# like any other. `_instance_host` walked ancestors down to depth 1 and stopped,
# so it never reached the root: every override directly under an inherited root
# lost its `index=` and got a "no instancing ancestor was found" refusal instead
# of the ordinal the base plainly gives it. Measured on trail before the fix:
# 3 such overrides across 2 scenes (scenes/moments/force_resolution.tscn,
# scenes/moments/game_over.tscn).
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
# root, one of a base GRANDchild whose only instancing ancestor is the root —
# and two nodes this scene creates, which carry no index and must not gain one.
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
    """The `index=` half of `make smoke`'s degradation, on the node lines."""
    return '\n'.join(INDEX_ATTR.sub('', line) if line.startswith('[node ') else line
                     for line in text.split('\n'))


def over_shell(scene_text: str) -> tuple[int, str, str]:
    """Canonicalize `scene_text` in a repo whose `res://scenes/shell.tscn` is
    SHELL_BASE -> (exit code, report, the file as it was left)."""
    with temp_repo('canon_repo') as root:
        (root / 'scenes/shell.tscn').write_text(SHELL_BASE, encoding='utf-8')
        (root / 'scenes/subject.tscn').write_text(scene_text, encoding='utf-8')
        code, out = canonicalize_in_repo('scenes/subject.tscn')
        text = (root / 'scenes/subject.tscn').read_text(encoding='utf-8')
    return code, out, text


class AnInheritedRootIsAnInstanceHost(unittest.TestCase):
    def test_an_override_under_an_inherited_root_gets_its_index_back(self) -> None:
        """`Inner` is the SECOND child of shell.tscn's root, so index must be 1
        — and the walk has to reach the root to say so."""
        code, out, text = over_shell(strip_indexes(INHERITED))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Inner" parent="." index="1"]', text)
        self.assertNotIn('UNRESOLVED', out)

    def test_an_override_of_a_base_grandchild_counts_through_the_root(self) -> None:
        """`Content` is the THIRD child of the base's `Inner` (Paper, Border,
        Content), so index must be 2. Nothing between it and the root instances
        anything, so this resolves only if the root is a candidate host."""
        code, out, text = over_shell(strip_indexes(INHERITED))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Content" parent="Inner" index="2"]', text)

    def test_the_whole_inherited_scene_round_trips_byte_for_byte(self) -> None:
        """The smoke row's property at unit scale: strip what `save()` drops,
        restore, and get the committed bytes back — no more and no less."""
        code, out, text = over_shell(strip_indexes(INHERITED))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertEqual(text, INHERITED)

    def test_a_node_the_scene_creates_gains_no_index(self) -> None:
        """The invent direction, and the one the sibling bug was. `Body` is
        built by this scene (`type=`) and `Nested` is instanced by it; no base
        places either, so neither has an ordinal to count and neither may gain
        one — not even the plausible 'next free slot'.

        A CONTROL: green before the inherited-root fix and after it, red only
        if the restoration over-corrects into inventing."""
        _code, _out, text = over_shell(strip_indexes(INHERITED))
        self.assertIn('[node name="Body" type="VBoxContainer" '
                      'parent="Inner/Content"]\n', text)
        self.assertIn('[node name="Nested" parent="." '
                      'instance=ExtResource("1_shell")]\n', text)

    def test_an_override_the_base_does_not_place_is_refused_not_guessed(self) -> None:
        """A type-less node under an inherited root IS an override — but if the
        base has no such child there is no ordinal, and the run says so instead
        of picking one."""
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


def over_chain(scene_text: str) -> tuple[int, str, str]:
    """Canonicalize `scene_text` against a TWO-level chain: shell.tscn is a
    plain scene, mid.tscn inherits it, and the subject inherits mid."""
    with temp_repo('canon_repo') as root:
        (root / 'scenes/shell.tscn').write_text(SHELL_BASE, encoding='utf-8')
        (root / 'scenes/mid.tscn').write_text(MID, encoding='utf-8')
        (root / 'scenes/subject.tscn').write_text(scene_text, encoding='utf-8')
        code, out = canonicalize_in_repo('scenes/subject.tscn')
        text = (root / 'scenes/subject.tscn').read_text(encoding='utf-8')
    return code, out, text


class AChainedBaseIsRefusedNotCounted(unittest.TestCase):
    def test_the_ordinal_that_would_be_written_is_the_WRONG_one(self) -> None:
        """The fixture's own claim, so no case below can pass on a chain that
        was never chained: counting mid.tscn's sections gives 0, and the truth
        the shell states is 1."""
        with temp_repo('canon_repo') as root:
            (root / 'scenes/shell.tscn').write_text(SHELL_BASE, encoding='utf-8')
            (root / 'scenes/mid.tscn').write_text(MID, encoding='utf-8')
            bases = scene_canonicalize.BaseScenes(root)
            self.assertTrue(bases.root_is_instanced('res://scenes/mid.tscn'))
            self.assertFalse(bases.root_is_instanced('res://scenes/shell.tscn'))
            self.assertEqual(
                bases.child_index('res://scenes/shell.tscn', [], 'Inner'), 1,
                'the shell places Inner second — the fixture is wrong')
            self.assertIsNone(
                bases.child_index('res://scenes/mid.tscn', [], 'Inner'),
                'mid.tscn lists only what it overrides, so nothing there is '
                'countable — this is the value the verb used to write')

    def test_an_override_under_a_chained_base_is_refused_not_guessed(self) -> None:
        """The verb's hard rule: it cannot guarantee a correct result, so it
        refuses, says why, writes nothing and exits non-zero."""
        code, out, text = over_chain(strip_indexes(CHAINED))
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS, out)
        self.assertIn('UNRESOLVED', out)
        self.assertNotIn('index=', text.split('\n')[4])
        self.assertEqual(text, strip_indexes(CHAINED),
                         'a refusal wrote to the file')

    def test_the_refusal_names_the_chain_rather_than_the_missing_name(self) -> None:
        """`Inner` IS in mid.tscn. A refusal saying "cannot count Inner in
        mid.tscn" sends a reader to look for it, find it, and conclude the tool
        is broken — so the refusal names the reason that is actually true."""
        _code, out, _text = over_chain(strip_indexes(CHAINED))
        self.assertIn('itself an inherited scene', out)
        self.assertIn('res://scenes/mid.tscn', out)

    def test_a_plain_base_one_level_down_still_resolves(self) -> None:
        """The refusal is scoped to a base whose OWN root is instanced. An
        ordinary inherited scene over a plain base is the case the same release
        fixed, and it must stay fixed."""
        code, out, text = over_shell(strip_indexes(INHERITED))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Inner" parent="." index="1"]', text)


# --- the smoke row that would notice ------------------------------------------
# `make smoke`'s `canonicalize invents no index` gated `invented == 0` only: a
# value that came back DIFFERENT from the authored one increments neither
# `restored` nor `lost`, so it was counted, printed in the detail of a green
# row, and gated by nothing. `restored + lost == authored` is the identity "no
# wrong value", and it is what would notice the day a consumer grows a scene
# whose base is itself inherited.
def smoke_harness():
    """`tools/consumer_smoke.py` — a tool, not a package module, so the import
    needs the path. Same spelling test_uid_codec.py uses."""
    import sys                                                  # noqa: PLC0415
    sys.path.insert(0, str(FIXTURES.parent.parent / 'tools'))
    import consumer_smoke                                       # noqa: PLC0415
    return consumer_smoke


def canon_row(scenes: dict[str, str]) -> tuple[bool, str]:
    """Run the smoke's canonicalize row over a repo holding EXACTLY `scenes`
    -> (the row passed, its detail).

    Its own repo rather than a fixture tree: the row scans every tracked
    `.tscn`, so a fixture's other scenes would land in the same counts and the
    assertions below would be about the fixture.
    """
    import subprocess                                           # noqa: PLC0415
    import tempfile                                             # noqa: PLC0415
    harness = smoke_harness()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'consumer'
        root.mkdir()
        (root / 'project.godot').write_text(
            'config_version=5\n\n[application]\n\nconfig/name="Scratch"\n',
            encoding='utf-8')
        for rel, body in scenes.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                       capture_output=True)
        report = harness.Report()
        harness.canonicalize_invents_no_index(root, report)
    assert len(report.rows) == 1, report.rows
    _consumer, what, detail = report.rows[0]
    return what.startswith('ok'), detail


class TheSmokeRowGatesAWrongValueNotOnlyAnInventedOne(unittest.TestCase):
    def test_an_authored_index_that_comes_back_DIFFERENT_reds_the_row(self) -> None:
        """Nothing was invented — a node that HAD an index still has one — and
        it is not the one the file said. The old condition called that green
        and printed the number in the detail."""
        wrong = INHERITED.replace('[node name="Inner" parent="." index="1"]',
                                  '[node name="Inner" parent="." index="7"]')
        passed, detail = canon_row({'scenes/shell.tscn': SHELL_BASE,
                                    'scenes/subject.tscn': wrong})
        self.assertFalse(passed, detail)
        self.assertIn('WRONG', detail)
        self.assertIn('index="7"', detail)
        self.assertIn('index="1"', detail)

    def test_a_chained_scene_is_NOT_DERIVABLE_and_the_row_stays_green(self) -> None:
        """Both halves together. The verb refuses the chain, so the authored
        index comes back absent rather than wrong — `lost`, which the identity
        accounts for, and the row is green with the refusal visible in its
        own detail."""
        passed, detail = canon_row({'scenes/shell.tscn': SHELL_BASE,
                                    'scenes/mid.tscn': MID,
                                    'scenes/subject.tscn': CHAINED})
        self.assertTrue(passed, detail)
        self.assertIn('0 invented', detail)
        self.assertIn('1 not derivable', detail)

    def test_the_identity_holds_on_a_corpus_with_nothing_wrong_in_it(self) -> None:
        """A CONTROL: the new half of the condition must not red a tree the
        verb handles correctly, or every consumer's smoke goes red on a rule
        rather than on a defect."""
        passed, detail = canon_row({'scenes/shell.tscn': SHELL_BASE,
                                    'scenes/subject.tscn': INHERITED})
        self.assertTrue(passed, detail)
        self.assertIn('0 invented', detail)
        self.assertIn('2/2 authored index= restored', detail)


# --- a node the scene CREATES gains no index, wherever its PARENT came from ---
# 0.24.0/bugs/index-is-derivable-under-an-instanced-parent proposed keying the
# restoration off "is this node's PARENT an instanced subtree?" instead of off
# `type=`/`instance=` on the node itself, on the reading that a created node
# under an instanced parent is positioned among that base's children and so has
# a derivable ordinal. The ORDINAL is derivable. Whether the engine writes the
# attribute is not, and the corpus refuses the rule in both directions:
#
#   * the editor-written half — nullbound, 194 scenes — has 1008 created nodes
#     and NOT ONE carries an `index=`, including 87 whose parent is a node the
#     base provides. It has no inherited scene with a written child, so it
#     cannot speak to that case at all.
#   * the hand-authored half — trail, 116 scenes, every one carrying a `;`
#     comment and so never through ResourceSaver — contradicts itself at the
#     one position in dispute: 10 created nodes directly under an inherited root
#     carry an append-correct `index=` and 10 more, same repo, same position,
#     carry none (6 appending into an empty base container, 4 after a 4-child
#     base root). Nothing structural separates the halves.
#
# Measured, degrade -> canonicalize over every tracked scene, before it was
# refused: the rule as filed invents 38 `index=` on trail and 87 on nullbound
# and takes nullbound from 0 round-trip failures to 26. Narrowed to inherited
# scenes it still invents 4. Each fixture below is one of those shapes, and the
# ordinal named in each docstring is what the rule would have written.
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
# The inherited half. `FirstBody`/`SecondBody` sit exactly where trail's corpus
# splits 10-for/10-against; `Slot` appends into a base container the base leaves
# empty (trail: 6 scenes, all `Card/Inner/Content/Body`); `Row` hangs off a node
# this scene created, inside an instanced subtree (trail: dossier.tscn's
# `DossierBody/Columns/Right`, where 2 of 15 siblings carry a hand-typed index).
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
    """The refusal matrix for the created-node position. Every case names the
    ordinal a parent-keyed rule would write, and asserts the node line as the
    file spells it — bare, with no `index=` appended."""

    def test_a_created_node_under_the_instance_node_itself_gains_none(self) -> None:
        """`Added` hangs off `Shell`, which instances the base. The base root
        places 2 children, so an append is `2`. nullbound's `game.tscn` is this
        shape six times over and carries no index on any of them."""
        code, out, text = over_shell(strip_indexes(PLAIN_HOST))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Added" type="Label" parent="Shell"]\n', text)

    def test_a_created_node_under_a_base_child_gains_none(self) -> None:
        """`Deep` hangs off `Shell/Inner`, a node the base provides and gives 3
        children of its own, so an append is `3`."""
        code, out, text = over_shell(strip_indexes(PLAIN_HOST))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Deep" type="Label" parent="Shell/Inner"]\n', text)

    def test_created_siblings_gain_no_run_of_sequential_ordinals(self) -> None:
        """`Slot0/1/2` fill a base container the base leaves empty — the shape a
        next-free-slot fallback turns into `0`, `1`, `2`, and the shape that
        made that fallback invent 505 attributes across the two trees. All three
        stay bare, and none of the three numbers appears anywhere in the file."""
        code, out, text = over_shell(strip_indexes(PLAIN_HOST))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        for name in ('Slot0', 'Slot1', 'Slot2'):
            self.assertIn(f'[node name="{name}" type="Label" '
                          f'parent="Shell/Inner/Content"]\n', text)
        self.assertEqual(text.count('index="'), 1, 'only the override is indexed')

    def test_a_created_body_under_an_inherited_root_gains_none(self) -> None:
        """THE disputed position, and the one this bug was filed to restore.
        The base root places 2 children, so an append is `2` for `FirstBody` and
        `3` for `SecondBody` — the numbers trail's 10 indexed bodies carry and
        its 4 unindexed ones (force_resolution, game_over) do not."""
        code, out, text = over_shell(strip_indexes(INHERITED_CREATES_BODIES))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="FirstBody" type="VBoxContainer" parent="."]\n', text)
        self.assertIn('[node name="SecondBody" type="VBoxContainer" parent="."]\n', text)

    def test_a_created_node_appending_into_an_empty_base_container_gains_none(self) -> None:
        """`Slot` goes into `Inner/Content`, which the base leaves childless. An
        append is `0`, and `index="0"` is no less invented for being the only
        number available."""
        code, out, text = over_shell(strip_indexes(INHERITED_CREATES_BODIES))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Slot" type="Label" parent="Inner/Content"]\n', text)

    def test_a_created_node_under_a_locally_created_parent_gains_none(self) -> None:
        """`Row`'s parent is a node this scene built. It is inside an instanced
        subtree — the root instances the base — so a rule that asks only "is the
        parent within an instance?" reaches it, and no base places its siblings."""
        code, out, text = over_shell(strip_indexes(INHERITED_CREATES_BODIES))
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('[node name="Row" type="Label" parent="FirstBody"]\n', text)

    def test_both_fixtures_round_trip_byte_for_byte(self) -> None:
        """The whole property in one assertion: strip what `save()` drops, and
        get the committed bytes back — no more and no less."""
        for fixture in (PLAIN_HOST, INHERITED_CREATES_BODIES):
            with self.subTest(fixture=fixture.split('\n')[0]):
                code, out, text = over_shell(strip_indexes(fixture))
                self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
                self.assertEqual(text, fixture)

    def test_the_override_in_each_fixture_still_gets_its_index_back(self) -> None:
        """The control that stops every case above from passing on a tool that
        does nothing: `Inner` is the base root's SECOND child in both fixtures,
        and it must come back as `1` under an instance node and under an
        inherited root alike."""
        _code, _out, plain = over_shell(strip_indexes(PLAIN_HOST))
        _code, _out, inherited = over_shell(strip_indexes(INHERITED_CREATES_BODIES))
        self.assertIn('[node name="Inner" parent="Shell" index="1"]\n', plain)
        self.assertIn('[node name="Inner" parent="." index="1"]\n', inherited)


class NoMarkerIsInventedForAnOverriddenInstance(unittest.TestCase):
    def test_the_packed_fixture_gains_no_editable_section(self) -> None:
        """`canon_repo/scenes/packed.tscn` instances `panel.tscn` and overrides
        its `Footer` child. That is an override, not an editable instance, and
        Godot writes exactly this file without a marker."""
        with temp_repo('canon_repo') as root:
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('index="1"', text, 'the fixture stopped restoring at all')
        self.assertEqual(editable_paths(text), [], text)
        self.assertNotIn('EDITABLE', out, out)



if __name__ == '__main__':
    unittest.main()
