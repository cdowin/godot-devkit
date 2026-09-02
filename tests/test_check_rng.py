"""Tier 2 — `check rng`, ported from a consumer's shell scan.

The cases are the ones the shell scan planted in its own `--self-test`, plus
the ones its allowlist file encoded as prose and this gate encodes as config.
Two properties carry the gate: an owned, seeded generator is NEVER a finding
(the false positive that would get the gate switched off), and an allowlist
entry that no longer matches IS one (an allowlist that outlives its violations
is a place to hide things).
"""
from __future__ import annotations

import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import rng

BASE = ['project.godot']
CLEAN = [*BASE, 'systems/clean.gd']
DIRTY = [*CLEAN, 'systems/loot.gd']
WHOLE_TREE = [*DIRTY, 'ui/menu.gd']
SYSTEMS_ONLY = '[rng]\nroots = ["systems"]\n'


def _config(root, body: str) -> None:
    (root / 'devkit.toml').write_text(body, encoding='utf-8')


class Detects(unittest.TestCase):
    def test_a_bare_draw_is_reported_with_its_enclosing_func(self) -> None:
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, SYSTEMS_ONLY)
            code, out = run_check(rng)
        self.assertEqual(code, 1, out)
        self.assertIn('BARE-RNG  systems/loot.gd:4:_shimmer:', out)

    def test_randomize_on_an_instance_is_still_a_finding(self) -> None:
        """The spelling that LOOKS derived is the one worth catching."""
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, SYSTEMS_ONLY)
            code, out = run_check(rng)
        self.assertEqual(code, 1)
        self.assertIn('BARE-RNG  systems/loot.gd:8:_mint:', out)

    def test_a_file_scope_draw_reports_the_file_scope_marker(self) -> None:
        with temp_repo('rng_repo', only=WHOLE_TREE):
            code, out = run_check(rng)
        self.assertEqual(code, 1)
        self.assertIn(f'ui/menu.gd:3:{rng.FILE_SCOPE}:', out)

    def test_every_finding_lands_in_one_run(self) -> None:
        """Three violations, one run: a gate that reveals the second class only
        after you fixed the first costs a round trip per class."""
        with temp_repo('rng_repo', only=WHOLE_TREE):
            code, out = run_check(rng)
        self.assertEqual(code, 1)
        self.assertEqual(out.count('BARE-RNG'), 3, out)


class Spares(unittest.TestCase):
    def test_an_owned_seeded_rng_a_string_and_a_doc_comment_pass(self) -> None:
        with temp_repo('rng_repo', only=CLEAN) as root:
            _config(root, SYSTEMS_ONLY)
            code, out = run_check(rng)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:rng] PASS — 1 script(s)', out)

    def test_roots_narrow_the_scan(self) -> None:
        with temp_repo('rng_repo', only=WHOLE_TREE) as root:
            _config(root, SYSTEMS_ONLY)
            code, out = run_check(rng)
        self.assertEqual(code, 1)
        self.assertNotIn('ui/menu.gd', out)


class TheAllowlist(unittest.TestCase):
    def test_an_entry_silences_its_func_and_only_its_func(self) -> None:
        """Function granularity is the whole design: a new bare call in a
        DIFFERENT function of an already-listed file still trips the gate."""
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, SYSTEMS_ONLY + 'allowlist = { "systems/loot.gd:_shimmer" '
                                         '= "cosmetic pulse phase" }\n')
            code, out = run_check(rng)
        self.assertEqual(code, 1, out)
        self.assertNotIn('_shimmer', out)
        self.assertIn('_mint', out)

    def test_a_fully_allowlisted_tree_passes_and_counts_the_carve_outs(self) -> None:
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, SYSTEMS_ONLY + 'allowlist = { '
                    '"systems/loot.gd:_shimmer" = "cosmetic pulse phase", '
                    '"systems/loot.gd:_mint" = "blocked on the run-seed bug" }\n')
            code, out = run_check(rng)
        self.assertEqual(code, 0, out)
        self.assertIn('2 allowlisted site(s), each with a reason', out)

    def test_an_entry_that_matches_nothing_is_a_finding(self) -> None:
        with temp_repo('rng_repo', only=CLEAN) as root:
            _config(root, SYSTEMS_ONLY
                    + 'allowlist = { "systems/clean.gd:eject" = "gone" }\n')
            code, out = run_check(rng)
        self.assertEqual(code, 1, out)
        self.assertIn('STALE  systems/clean.gd:eject', out)


class RefusesRatherThanGuesses(unittest.TestCase):
    """Exit 2 is a config mistake; exit 1 is drift. A typo must never read as
    a finding, and must never quietly narrow the run either."""

    def test_an_allowlist_entry_with_no_reason_is_refused(self) -> None:
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, SYSTEMS_ONLY
                    + 'allowlist = { "systems/loot.gd:_shimmer" = "  " }\n')
            with self.assertRaises(ConfigError) as caught:
                run_check(rng)
        self.assertIn('has no reason', str(caught.exception))

    def test_an_allowlist_key_without_a_func_is_refused(self) -> None:
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, SYSTEMS_ONLY + 'allowlist = { "systems/loot.gd" = "x" }\n')
            with self.assertRaises(ConfigError) as caught:
                run_check(rng)
        self.assertIn('enclosing func', str(caught.exception))

    def test_a_bare_string_root_is_refused_not_iterated(self) -> None:
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, '[rng]\nroots = "systems"\n')
            with self.assertRaises(ConfigError):
                run_check(rng)

    def test_a_root_holding_no_scripts_fails_loudly(self) -> None:
        with temp_repo('rng_repo', only=DIRTY) as root:
            _config(root, '[rng]\nroots = ["scenes"]\n')
            code, out = run_check(rng)
        self.assertEqual(code, 1, out)
        self.assertIn('no tracked *.gd', out)
        self.assertIn('[rng] roots', out)


if __name__ == '__main__':
    unittest.main()
