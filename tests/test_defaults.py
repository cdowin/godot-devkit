"""Tier 3 — the `.tres` default-elision flavour of editor churn.

Two writers, two formats: hand-authored `.tres` spell every property out, Godot's
writer omits any equal to the script's `@export` default. The repo holds one
form, the editor emits the other, and the file diffs forever.

The bar for the FIXER is higher than "produces the same bytes Godot would". A
load-and-re-save also reorders properties, respells typed arrays and floats,
mints `ext_resource` ids and deletes every `;` comment in the file — which is
why it cannot be run in bulk. This pass is a pure DELETION of lines proven
redundant, so everything else survives; the tests below are what pins that down.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from support import run_check, temp_repo

from godot_devkit.godot.write import scene_canonicalize
from godot_devkit.godot.checks import defaults as defaults_check
from godot_devkit.godot.index.gd_declarations import parse_declaration, parse_enum
from godot_devkit.godot.index.resource_defaults import literal
from godot_devkit.godot.format.tscn import parse

REDUNDANT = 'data/redundant.tres'
# Every assignment in the fixture that IS the declared default.
EXPECTED_ELISIONS = {
    ('Nested', 'trigger'), ('Nested', 'priority'),
    ('', 'trigger'), ('', 'kind'), ('', 'owner_id'), ('', 'tag'), ('', 'speed'),
    ('', 'label'), ('', 'offset'), ('', 'extent'), ('', 'untouched'),
    ('', 'members'), ('', 'lookup'), ('', 'payload'), ('', 'enabled'),
}
# Assignments that must SURVIVE, each for a different reason.
MUST_SURVIVE = (
    'guarded = 0',          # the export has a setter
    'computed = 3',         # the default is a call, outside the value language
    'priority = 99',        # simply not the default
    'label = "nested"',     # not the default, in a sub_resource
    'point_count = 0',      # an engine sub_resource — no default table for it
    'trigger_note = 1',     # not declared at all; `check props` owns that call
)


def canonicalize_in_repo(*argv: str) -> tuple[int, str]:
    return run_check(SimpleNamespace(run=scene_canonicalize.main), argv=list(argv))


def _assignments(path) -> set[tuple[str, str]]:
    # `{(section id, property)}` — the file's assignments, section-aware.
    return {(section.attrs.get('id', ''), entry.key)
            for section in parse(str(path))
            if section.kind in ('resource', 'sub_resource')
            for entry in section.entries if entry.key != 'script'}


class DeclarationScanner(unittest.TestCase):
    # The .gd half — the shapes the fixture below cannot reach; every other
    # declaration form is pinned by the fixer's exact elision set.

    def test_an_inferred_declaration_and_a_dictionary_default(self) -> None:
        decl = parse_declaration('@export var speed := 300.0')
        self.assertEqual((decl.declared_type, decl.default), (None, '300.0'))
        self.assertEqual(parse_declaration('@export var d: Dictionary = {"a": 1, "b": 2}').default,
                         '{"a": 1, "b": 2}')

    def test_unevaluable_enum_member_voids_the_whole_table(self) -> None:
        # A partially-known enum mis-resolves every member after the gap.
        self.assertIsNone(parse_enum('enum E { A = SOME_CONST, B }'))


class ValueLanguage(unittest.TestCase):
    # Both spellings normalise into it, or neither is compared — and a
    # collision deletes a value as 'redundant' that was not.

    def test_equivalent_spellings_agree_distinct_values_differ_and_the_rest_is_refused(
            self) -> None:
        # `5` equals `5.0` (Python `==` is exact) — but past 2**53 two
        # different ints must not normalize to the same float.
        for same in (('0', '0.0'), ('&"a"', '"a"'), ('[]', 'Array[Resource]([])'),
                     ('Vector2(0, 0)', 'Vector2.ZERO'), ('0.30', '0.3'), ('5', '5.0')):
            self.assertEqual(literal(same[0]), literal(same[1]), same)
        for a, b in (('0', '1'), ('""', 'null'), ('[]', '{}'), ('false', '0'),
                     ('9007199254740993', '9007199254740992')):
            self.assertNotEqual(literal(a), literal(b), (a, b))
        for spelling in ('SubResource("x")', 'ExtResource("1")', 'preload("res://a.gd")',
                         '[SubResource("x")]', 'int(SPEED / 100.0)', 'Transform2D(1, 2)'):
            self.assertIsNone(literal(spelling), spelling)


class Detector(unittest.TestCase):
    def test_gate_fails_on_the_redundant_fixture(self) -> None:
        with temp_repo('defaults_repo'):
            code, out = run_check(defaults_check)
        self.assertEqual(code, defaults_check.EXIT_FINDINGS, out)
        self.assertIn('REDUNDANT', out)
        self.assertIn('trigger = 0', out)

    def test_gate_passes_when_nothing_is_redundant(self) -> None:
        with temp_repo('defaults_repo', only=['data/clean.tres', 'systems/rule.gd',
                                              'systems/base_rule.gd', 'systems/ids.gd',
                                              'project.godot']):
            code, out = run_check(defaults_check)
        self.assertEqual(code, defaults_check.EXIT_OK, out)
        self.assertIn('PASS', out)

    def test_gate_refuses_to_pass_on_an_empty_census(self) -> None:
        # A gate that scanned nothing must say so, not print PASS (rule 4).
        with temp_repo('defaults_repo', only=['project.godot']):
            code, out = run_check(defaults_check)
        self.assertEqual(code, defaults_check.EXIT_FINDINGS, out)
        self.assertIn('scanned 0 files', out)


class Fixer(unittest.TestCase):
    def test_elides_exactly_the_redundant_lines_and_nothing_else_and_converges(
            self) -> None:
        # Deletions only — no added line, no rewritten header, no lost
        # comment — and the second run is a no-op that says so.
        with temp_repo('defaults_repo') as root:
            before_set = _assignments(root / REDUNDANT)
            before = (root / REDUNDANT).read_text(encoding='utf-8').split('\n')
            code, out = canonicalize_in_repo('--elide-defaults', REDUNDANT)
            text = (root / REDUNDANT).read_text(encoding='utf-8')
            after_set = _assignments(root / REDUNDANT)
            again_code, again_out = canonicalize_in_repo('--elide-defaults', REDUNDANT)
            twice = (root / REDUNDANT).read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertEqual(before_set - after_set, EXPECTED_ELISIONS)
        for survivor in MUST_SURVIVE:
            self.assertIn(survivor, text, survivor)
        after = text.split('\n')
        self.assertEqual(after, [line for line in before if line in after])
        self.assertEqual(len(before) - len(after), len(EXPECTED_ELISIONS))
        for line in before:
            if line.startswith((';', '[', 'script = ')):
                self.assertIn(line, after, line)
        self.assertEqual(twice, text)
        self.assertEqual(again_code, scene_canonicalize.EXIT_OK)
        self.assertIn('already canonical', again_out)

    def test_without_the_flag_nothing_is_deleted(self) -> None:
        # The pass is opt-in: it removes lines, so a consumer adopts it by choice.
        with temp_repo('defaults_repo') as root:
            before = (root / REDUNDANT).read_text(encoding='utf-8')
            canonicalize_in_repo(REDUNDANT)
            self.assertEqual((root / REDUNDANT).read_text(encoding='utf-8'), before)


# At corpus scale the transform must stay a pure, stable deletion — the write
# verb runs over a COPY in a throwaway repo, never over a fixture in place.
# What that proof lost when the live-consumer sweep went is recorded in
# 0.24.0/bugs/the-smoke-took-fixture-scale-with-it.
