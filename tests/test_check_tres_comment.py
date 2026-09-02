"""Tier 2 — `check tres-comment`, ported from a consumer's shell scan.

The gate is a hard one because its match has no judgement in it: Godot writes
multi-line strings escaped and packed data as one-line base64, so a column-0
`;` cannot occur inside a value the engine wrote. The cases below pin both
halves of that claim — the planted comment is caught, and a `;` INSIDE a value
is not a comment.
"""
from __future__ import annotations

import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import tres_comment

BASE = ['project.godot']
CLEAN = [*BASE, 'data/clean.tres']
PLANTED = [*CLEAN, 'data/planted.tres', 'scenes/planted.tscn']
VENDORED = [*CLEAN, 'addons/vendor/thing.tres']


def _config(root, body: str) -> None:
    (root / 'devkit.toml').write_text(body, encoding='utf-8')


class Detects(unittest.TestCase):
    def test_a_planted_comment_is_caught_in_both_file_kinds(self) -> None:
        with temp_repo('tres_comment_repo', only=PLANTED):
            code, out = run_check(tres_comment)
        self.assertEqual(code, 1, out)
        self.assertIn('STRIPPED  data/planted.tres:1:; why this value is 7', out)
        self.assertIn('STRIPPED  scenes/planted.tscn:3:; a scene comment', out)
        self.assertIn('2 authored comment line(s)', out)


class Spares(unittest.TestCase):
    def test_a_semicolon_inside_a_value_is_not_a_comment(self) -> None:
        with temp_repo('tres_comment_repo', only=CLEAN):
            code, out = run_check(tres_comment)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:tres-comment] PASS — 1 of 1 tracked', out)

    def test_vendored_resources_are_excluded_by_default(self) -> None:
        """`addons/` is not ours to rewrite — and the census still says how
        many files the exclude removed."""
        with temp_repo('tres_comment_repo', only=VENDORED):
            code, out = run_check(tres_comment)
        self.assertEqual(code, 0, out)
        self.assertIn('1 of 2 tracked', out)

    def test_the_exclude_is_configurable(self) -> None:
        with temp_repo('tres_comment_repo', only=PLANTED) as root:
            _config(root, '[tres_comment]\nexclude_prefixes = ["data/"]\n')
            code, out = run_check(tres_comment)
        self.assertEqual(code, 1, out)
        self.assertNotIn('data/planted.tres', out)
        self.assertIn('scenes/planted.tscn', out)


class RefusesRatherThanGuesses(unittest.TestCase):
    def test_an_exclude_that_eats_the_census_fails_and_names_the_key(self) -> None:
        with temp_repo('tres_comment_repo', only=PLANTED) as root:
            _config(root, '[tres_comment]\nexclude_prefixes = ["data/", "scenes/"]\n')
            code, out = run_check(tres_comment)
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 of 3 tracked', out)
        self.assertIn('[tres_comment] exclude_prefixes', out)

    def test_a_bare_string_exclude_is_refused_not_iterated(self) -> None:
        """`"addons/"` under a plain `tuple(...)` is seven single characters,
        and `data/planted.tres` starts with `d`."""
        with temp_repo('tres_comment_repo', only=PLANTED) as root:
            _config(root, '[tres_comment]\nexclude_prefixes = "addons/"\n')
            with self.assertRaises(ConfigError):
                run_check(tres_comment)


if __name__ == '__main__':
    unittest.main()
