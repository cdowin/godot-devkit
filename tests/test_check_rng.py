"""Tier 2 — `check rng`, ported from a consumer's shell scan.

The cases are the ones the shell scan planted in its own `--self-test`, plus
the ones its allowlist file encoded as prose and this gate encodes as config.
Two properties carry the gate: an owned, seeded generator is NEVER a finding
(the false positive that would get the gate switched off), and an allowlist
entry that no longer matches IS one (an allowlist that outlives its violations
is a place to hide things).
"""
import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import rng

CLEAN = ['project.godot', 'systems/clean.gd']
DIRTY = [*CLEAN, 'systems/loot.gd']
WHOLE_TREE = [*DIRTY, 'ui/menu.gd']
SYSTEMS_ONLY = '[rng]\nroots = ["systems"]\n'


def _gate(only, config=None):
    """One run of the gate in a throwaway repo holding `only`, under `config`."""
    with temp_repo('rng_repo', only=only) as root:
        if config:
            (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
        return run_check(rng)


class Detects(unittest.TestCase):
    def test_a_bare_draw_is_reported_with_its_enclosing_func(self) -> None:
        code, out = _gate(DIRTY, SYSTEMS_ONLY)
        self.assertEqual(code, 1, out)
        self.assertIn('BARE-RNG  systems/loot.gd:4:_shimmer:', out)
        # `randomize()` on an instance: the spelling that LOOKS derived is the
        # one worth catching.
        self.assertIn('BARE-RNG  systems/loot.gd:8:_mint:', out)

    def test_every_finding_lands_in_one_run_and_roots_narrow_the_scan(self) -> None:
        # Three violations, one run: a gate that reveals the second class only
        # after you fixed the first costs a round trip per class. A file-scope
        # draw reports the file-scope marker; `roots` then drops the file.
        code, out = _gate(WHOLE_TREE)
        self.assertEqual(code, 1)
        self.assertEqual(out.count('BARE-RNG'), 3, out)
        self.assertIn(f'ui/menu.gd:3:{rng.FILE_SCOPE}:', out)
        code, out = _gate(WHOLE_TREE, SYSTEMS_ONLY)
        self.assertEqual(code, 1)
        self.assertNotIn('ui/menu.gd', out)


class Spares(unittest.TestCase):
    def test_an_owned_seeded_rng_a_string_and_a_doc_comment_pass(self) -> None:
        code, out = _gate(CLEAN, SYSTEMS_ONLY)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:rng] PASS — 1 script(s)', out)

    def test_a_draw_api_declared_under_the_engines_names_is_not_a_draw(self) -> None:
        # #30: the seeded-stream owner exposes `func randf()` & co. The
        # declaration line is no call, and a bare `randf()` in the script that
        # declares it is its OWN method; the same bare call in a script that
        # declares nothing is still the global generator.
        owner = ('var _rng := RandomNumberGenerator.new()\n'
                 'func randf() -> float:\n'
                 '\treturn _rng.randf()\n'
                 'static func randi_range(lo: int, hi: int) -> int:\n'
                 '\treturn _rng.randi_range(lo, hi)\n'
                 'func coin() -> bool:\n'
                 '\treturn randf() < 0.5\n')
        self.assertEqual([str(h) for h in rng.scan_text(owner, 'owner.gd')], [])
        caller = 'func coin() -> bool:\n\treturn randf() < 0.5\n'
        self.assertEqual([str(h) for h in rng.scan_text(caller, 'caller.gd')],
                         ['caller.gd:2:coin:return randf() < 0.5'])
        # Shadowing is scoped per class body, both directions: an inner
        # class's `func randi()` shadows nothing outside it, and the script's
        # own `func randf()` shadows nothing inside `class Inner:` — while each
        # body's own call to its own method stays spared.
        inner = ('func randf() -> float:\n'
                 '\treturn 0.5\n'
                 'class Inner:\n'
                 '\tfunc randi() -> int:\n'
                 '\t\treturn 4\n'
                 '\tfunc mine() -> int:\n'
                 '\t\treturn randi()\n'
                 '\tfunc theirs() -> float:\n'
                 '\t\treturn randf()\n'
                 '\n'
                 'func roll() -> int:\n'
                 '\treturn randi() if randf() else 0\n')
        self.assertEqual([str(h) for h in rng.scan_text(inner, 'inner.gd')],
                         ['inner.gd:9:theirs:return randf()',
                          'inner.gd:12:roll:return randi() if randf() else 0'])
        # A continuation line at column 0 — inside an open bracket, a `"""`
        # string or after a trailing `\` — is still the class body, so the
        # inner draw stays the GLOBAL one; and a bracket inside that string
        # opens nothing, so the column-0 `func own` does close the body.
        continued = ('func randf() -> float:\n'
                     '\treturn 0.5\n'
                     'class Inner:\n'
                     '\tvar table = [\n'
                     '1, 2,\n'
                     ']\n'
                     '\tconst DOC = """\n'
                     'note (unclosed\n'
                     '"""\n'
                     '\tvar total = 1 + \\\n'
                     '2\n'
                     '\tfunc draw() -> float:\n'
                     '\t\treturn randf()\n'
                     'func own() -> float:\n'
                     '\treturn randf()\n')
        self.assertEqual([str(h) for h in rng.scan_text(continued, 'c.gd')],
                         ['c.gd:13:draw:return randf()'])


class TheAllowlist(unittest.TestCase):
    def test_an_entry_silences_only_its_func_and_a_full_list_counts_the_carve_outs(self) -> None:
        # Function granularity is the whole design: a new bare call in a
        # DIFFERENT function of an already-listed file still trips the gate.
        code, out = _gate(DIRTY, SYSTEMS_ONLY + 'allowlist = { "systems/loot.gd:_shimmer" '
                                                '= "cosmetic pulse phase" }\n')
        self.assertEqual(code, 1, out)
        self.assertNotIn('_shimmer', out)
        self.assertIn('_mint', out)
        code, out = _gate(DIRTY, SYSTEMS_ONLY + 'allowlist = { '
                          '"systems/loot.gd:_shimmer" = "cosmetic pulse phase", '
                          '"systems/loot.gd:_mint" = "blocked on the run-seed bug" }\n')
        self.assertEqual(code, 0, out)
        self.assertIn('2 allowlisted site(s), each with a reason', out)

    def test_an_entry_that_matches_nothing_is_a_finding(self) -> None:
        code, out = _gate(CLEAN, SYSTEMS_ONLY
                          + 'allowlist = { "systems/clean.gd:eject" = "gone" }\n')
        self.assertEqual(code, 1, out)
        self.assertIn('STALE  systems/clean.gd:eject', out)


class RefusesRatherThanGuesses(unittest.TestCase):
    """Exit 2 is a config mistake; exit 1 is drift. A typo must never read as
    a finding, and must never quietly narrow the run either."""

    BAD_CONFIG = (
        (SYSTEMS_ONLY + 'allowlist = { "systems/loot.gd:_shimmer" = "  " }\n',
         'has no reason'),
        (SYSTEMS_ONLY + 'allowlist = { "systems/loot.gd" = "x" }\n', 'enclosing func'),
        ('[rng]\nroots = "systems"\n', 'must be a list of strings'),
    )

    def test_a_bad_config_value_is_refused_not_read_as_a_finding(self) -> None:
        for body, reason in self.BAD_CONFIG:
            with self.subTest(config=body), self.assertRaises(ConfigError) as caught:
                _gate(DIRTY, body)
            self.assertIn(reason, str(caught.exception))

    def test_a_root_holding_no_scripts_fails_loudly(self) -> None:
        code, out = _gate(DIRTY, '[rng]\nroots = ["scenes"]\n')
        self.assertEqual(code, 1, out)
        self.assertIn('no tracked *.gd', out)
        self.assertIn('[rng] roots', out)
