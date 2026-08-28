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

import contextlib
import io
import unittest

from support import FIXTURES, available_consumers, run_check, temp_repo

from godot_devkit import scene_canonicalize
from godot_devkit.checks import defaults as defaults_check
from godot_devkit.gd_declarations import (
    parse_declaration,
    parse_enum,
    scan_declarations,
)
from godot_devkit.gdscript import ScriptIndex
from godot_devkit.project import repo_root
from godot_devkit.resource_defaults import DefaultAnalyzer, literal
from godot_devkit.tscn import parse, parse_text

REDUNDANT = 'data/redundant.tres'
CLEAN = 'data/clean.tres'
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
    repo_root.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = scene_canonicalize.main([*argv])
    repo_root.cache_clear()
    return code, buffer.getvalue()


def _assignments(path) -> set[tuple[str, str]]:
    """`{(section id, property)}` — the file's assignments, section-aware."""
    return {(section.attrs.get('id', ''), entry.key)
            for section in parse(str(path))
            if section.kind in ('resource', 'sub_resource')
            for entry in section.entries if entry.key != 'script'}


def analyzer_in(root) -> DefaultAnalyzer:
    scripts = ScriptIndex(root, ['systems/rule.gd', 'systems/base_rule.gd',
                                 'systems/ids.gd'])
    return DefaultAnalyzer(scripts)


class DeclarationScanner(unittest.TestCase):
    """The .gd half: what a declaration says its default is."""

    def test_reads_type_and_default(self) -> None:
        decl = parse_declaration('@export var trigger: Trigger = Trigger.ALL_DOWN')
        self.assertEqual((decl.name, decl.declared_type, decl.default),
                         ('trigger', 'Trigger', 'Trigger.ALL_DOWN'))
        self.assertFalse(decl.has_accessor)

    def test_flags_an_accessor_so_the_caller_refuses(self) -> None:
        self.assertTrue(parse_declaration('@export var x: int = 0: set = _set_x').has_accessor)
        self.assertTrue(parse_declaration('@export var y: int = 0:').has_accessor)

    def test_inferred_declaration(self) -> None:
        decl = parse_declaration('@export var speed := 300.0')
        self.assertEqual((decl.declared_type, decl.default), (None, '300.0'))

    def test_dictionary_default_keeps_its_colons(self) -> None:
        decl = parse_declaration('@export var d: Dictionary = {"a": 1, "b": 2}')
        self.assertEqual(decl.default, '{"a": 1, "b": 2}')

    def test_enum_with_comments_inside_the_braces(self) -> None:
        source = 'enum Kind {\n\tFIRST,  # leading\n\tSECOND,\n\tTHIRD = 7,\n}\n'
        facts = scan_declarations(source)
        self.assertEqual(facts.enums['Kind'], {'FIRST': 0, 'SECOND': 1, 'THIRD': 7})

    def test_unevaluable_enum_member_voids_the_whole_table(self) -> None:
        """A partially-known enum mis-resolves every member after the gap."""
        self.assertIsNone(parse_enum('enum E { A = SOME_CONST, B }'))

    def test_consts_and_preload_aliases(self) -> None:
        facts = scan_declarations(
            'const Ids = preload("res://systems/ids.gd")\nconst SPEED := 300.0\n')
        self.assertEqual(facts.aliases, {'Ids': 'res://systems/ids.gd'})
        self.assertEqual(facts.consts, {'SPEED': '300.0'})


class ValueLanguage(unittest.TestCase):
    """Both spellings normalise into it, or neither is compared."""

    def test_equivalent_spellings_agree(self) -> None:
        self.assertEqual(literal('0'), literal('0.0'))
        self.assertEqual(literal('&"a"'), literal('"a"'))
        self.assertEqual(literal('[]'), literal('Array[Resource]([])'))
        self.assertEqual(literal('Vector2(0, 0)'), literal('Vector2.ZERO'))
        self.assertEqual(literal('0.30'), literal('0.3'))

    def test_refuses_what_it_cannot_evaluate(self) -> None:
        for spelling in ('SubResource("x")', 'ExtResource("1")', 'preload("res://a.gd")',
                         '[SubResource("x")]', 'int(SPEED / 100.0)', 'Transform2D(1, 2)'):
            self.assertIsNone(literal(spelling), spelling)

    def test_distinct_values_do_not_collide(self) -> None:
        self.assertNotEqual(literal('0'), literal('1'))
        self.assertNotEqual(literal('""'), literal('null'))
        self.assertNotEqual(literal('[]'), literal('{}'))
        self.assertNotEqual(literal('false'), literal('0'))


class Detector(unittest.TestCase):
    def test_finds_every_redundant_assignment_and_only_those(self) -> None:
        with temp_repo('defaults_repo') as root:
            found = {(item.section.attrs.get('id', ''), item.prop.key)
                     for item in analyzer_in(root).analyze(parse(str(root / REDUNDANT)))}
        self.assertEqual(found, EXPECTED_ELISIONS)

    def test_gate_fails_on_the_redundant_fixture(self) -> None:
        with temp_repo('defaults_repo'):
            code, out = run_check(defaults_check)
        self.assertEqual(code, defaults_check.EXIT_FINDINGS, out)
        self.assertIn('REDUNDANT', out)
        self.assertIn('trigger = 0', out)

    def test_gate_passes_when_nothing_is_redundant(self) -> None:
        with temp_repo('defaults_repo', only=[CLEAN, 'systems/rule.gd',
                                              'systems/base_rule.gd', 'systems/ids.gd',
                                              'project.godot']):
            code, out = run_check(defaults_check)
        self.assertEqual(code, defaults_check.EXIT_OK, out)
        self.assertIn('PASS', out)

    def test_gate_refuses_to_pass_on_an_empty_census(self) -> None:
        """A gate that scanned nothing must say so, not print PASS (rule 4)."""
        with temp_repo('defaults_repo', only=['project.godot']):
            code, out = run_check(defaults_check)
        self.assertEqual(code, defaults_check.EXIT_FINDINGS, out)
        self.assertIn('scanned 0 files', out)


class Fixer(unittest.TestCase):
    def test_elides_exactly_the_redundant_lines(self) -> None:
        with temp_repo('defaults_repo') as root:
            before = _assignments(root / REDUNDANT)
            code, out = canonicalize_in_repo('--elide-defaults', REDUNDANT)
            text = (root / REDUNDANT).read_text(encoding='utf-8')
            after = _assignments(root / REDUNDANT)
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertEqual(before - after, EXPECTED_ELISIONS)
        for survivor in MUST_SURVIVE:
            self.assertIn(survivor, text, survivor)

    def test_touches_nothing_but_the_redundant_lines(self) -> None:
        """Deletions only — no added line, no rewritten header, no lost comment."""
        with temp_repo('defaults_repo') as root:
            before = (root / REDUNDANT).read_text(encoding='utf-8').split('\n')
            canonicalize_in_repo('--elide-defaults', REDUNDANT)
            after = (root / REDUNDANT).read_text(encoding='utf-8').split('\n')
        self.assertEqual(after, [line for line in before if line in after])
        self.assertEqual(len(before) - len(after), len(EXPECTED_ELISIONS))
        for line in before:
            if line.startswith((';', '[', 'script = ')):
                self.assertIn(line, after, line)

    def test_is_idempotent(self) -> None:
        with temp_repo('defaults_repo') as root:
            canonicalize_in_repo('--elide-defaults', REDUNDANT)
            once = (root / REDUNDANT).read_text(encoding='utf-8')
            code, out = canonicalize_in_repo('--elide-defaults', REDUNDANT)
            twice = (root / REDUNDANT).read_text(encoding='utf-8')
        self.assertEqual(once, twice)
        self.assertEqual(code, scene_canonicalize.EXIT_OK)
        self.assertIn('already canonical', out)

    def test_leaves_a_clean_file_byte_identical(self) -> None:
        with temp_repo('defaults_repo') as root:
            before = (root / CLEAN).read_text(encoding='utf-8')
            canonicalize_in_repo('--elide-defaults', CLEAN)
            self.assertEqual((root / CLEAN).read_text(encoding='utf-8'), before)

    def test_without_the_flag_nothing_is_deleted(self) -> None:
        """The pass is opt-in: it removes lines, so a consumer adopts it by choice."""
        with temp_repo('defaults_repo') as root:
            before = (root / REDUNDANT).read_text(encoding='utf-8')
            canonicalize_in_repo(REDUNDANT)
            self.assertEqual((root / REDUNDANT).read_text(encoding='utf-8'), before)


class ConsumerCorpus(unittest.TestCase):
    """Over a real repo the transform must stay a pure, stable deletion.

    Write verbs never touch a live consumer checkout — the corpus is copied into
    the throwaway repo first.
    """

    def test_deletion_only_and_idempotent_over_a_real_tree(self) -> None:
        consumers = available_consumers()
        if not consumers:
            self.skipTest('no consumer checkout present')
        # Try each consumer and keep the first that still has something to
        # elide. A consumer that has ALREADY been canonicalized exercises
        # nothing, and asserting against that turns "the fixer did its job"
        # into a permanent red — which is what happened here.
        for source in consumers:
            outcome = self._elide_over(source)
            if outcome is not None:
                return
        self.skipTest('every consumer corpus is already canonical — nothing to '
                      'elide, so this case cannot exercise the fixer')

    def _elide_over(self, source):
        """Run the corpus case against one consumer. None if it changed nothing."""
        import shutil
        import subprocess
        tracked = subprocess.run(
            ['git', 'ls-files', '*.tres', '*.gd', '*.gd.uid'], cwd=source,
            capture_output=True, text=True, check=False).stdout.split()
        if not tracked:
            return None
        with temp_repo('defaults_repo', only=['project.godot']) as root:
            for rel in tracked:
                if rel.startswith('addons/'):
                    continue
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / rel, target)
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            files = [rel for rel in tracked
                     if rel.endswith('.tres') and not rel.startswith('addons/')]
            before = {rel: (root / rel).read_text(encoding='utf-8') for rel in files}
            code, _ = canonicalize_in_repo('--elide-defaults', *files)
            self.assertEqual(code, scene_canonicalize.EXIT_OK)
            once = {rel: (root / rel).read_text(encoding='utf-8') for rel in files}
            canonicalize_in_repo('--elide-defaults', *files)
            twice = {rel: (root / rel).read_text(encoding='utf-8') for rel in files}
        self.assertEqual(once, twice, 'not idempotent over the consumer corpus')
        changed = 0
        for rel in files:
            old, new = before[rel].split('\n'), once[rel].split('\n')
            if old != new:
                changed += 1
            # Deletion only: every surviving line is an original line, in order.
            self.assertEqual(new, [line for line in old if line in new], rel)
            self.assertLessEqual(len(new), len(old), rel)
        return changed or None


class ParserSharing(unittest.TestCase):
    def test_the_analyzer_reads_the_same_sections_the_document_edits(self) -> None:
        """Read output is write input: one parse feeds both the gate and the fix."""
        text = (FIXTURES / 'defaults_repo' / REDUNDANT).read_text(encoding='utf-8')
        self.assertEqual([s.kind for s in parse_text(text)],
                         ['gd_resource', 'ext_resource', 'sub_resource',
                          'sub_resource', 'resource'])


if __name__ == '__main__':
    unittest.main()
