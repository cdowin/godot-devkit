"""Tier 2 — `check uid`, and the repair it can now apply.

The gate has always known the should-be value; `--fix` writes it. The cases
that matter are the ones where a repair could lie: it must rewrite ONLY the
stale uid attribute (every other byte of the file identical), it must leave a
drift it cannot resolve from evidence alone — a target with no `.uid` at all —
reported and untouched, and a re-run after a fix must come back clean, because
a repair that does not converge is worse than no repair.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from support import REPO_ROOT, run_check, temp_repo

from godot_devkit.godot.checks import uid

BASE = ['project.godot', 'systems/rule.gd', 'systems/rule.gd.uid']
CLEAN = [*BASE, 'scenes/clean.tscn']
DRIFTED = [*CLEAN, 'scenes/drifted.tscn', 'data/drifted.tres']
GHOST = [*CLEAN, 'systems/ghost.gd', 'scenes/ghost_ref.tscn']
STALE_SCENE_UID = 'uid://dstaleuid000'
STALE_RES_UID = 'uid://dstaleuid001'
ACTUAL_UID = 'uid://drulescript'


def _fix() -> tuple[int, str]:
    return run_check(uid, fix=True)


class Reports(unittest.TestCase):
    def test_clean_tree_passes(self) -> None:
        with temp_repo('uid_repo', only=CLEAN):
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid] PASS', out)

    def test_drift_fails_and_names_the_should_be_value(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED):
            code, out = run_check(uid)
        self.assertEqual(code, 1)
        self.assertIn(f'DRIFT  scenes/drifted.tscn : {STALE_SCENE_UID} -> should be '
                      f'{ACTUAL_UID}', out)
        self.assertIn('data/drifted.tres', out)
        self.assertIn('re-run with --fix', out)

    def test_a_target_without_a_sidecar_is_reported_not_offered_for_repair(self) -> None:
        with temp_repo('uid_repo', only=GHOST):
            code, out = run_check(uid)
        self.assertEqual(code, 1)
        self.assertIn('has NO .uid file', out)
        self.assertNotIn('re-run with --fix', out)

    def test_the_configured_exclude_scopes_check_2_as_well_as_check_1(self) -> None:
        """One documented key, one scope. `exclude_prefixes` read only in CHECK
        1 meant an excluded tree still had every sidecar-less `.gd` in it
        reported — the key a consumer set to scope this gate did not."""
        with temp_repo('uid_repo', only=GHOST) as root:
            (root / 'devkit.toml').write_text(
                '[uid]\nexclude_prefixes = ["addons/", "systems/ghost"]\n',
                encoding='utf-8')
            code, out = run_check(uid)
        self.assertNotIn('systems/ghost.gd has no tracked', out)
        # The .tscn referencing it is still in scope, so CHECK 1 still reports.
        self.assertEqual(code, 1, out)
        self.assertIn('ghost_ref.tscn', out)

    def test_an_exclude_that_eats_the_census_says_how_many_it_ate(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[uid]\nexclude_prefixes = ["scenes/", "systems/"]\n',
                encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 of 1 tracked', out)


class Repairs(unittest.TestCase):
    def test_rewrites_every_stale_ref_and_exits_clean(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED) as root:
            code, out = _fix()
            scene = (root / 'scenes/drifted.tscn').read_text(encoding='utf-8')
            resource = (root / 'data/drifted.tres').read_text(encoding='utf-8')
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid] FIX — repaired 2 stale uid ref(s)', out)
        self.assertIn(f'FIXED  scenes/drifted.tscn : {STALE_SCENE_UID} -> {ACTUAL_UID}', out)
        self.assertIn(f'uid="{ACTUAL_UID}" path="res://systems/rule.gd"', scene)
        self.assertIn(f'uid="{ACTUAL_UID}" path="res://systems/rule.gd"', resource)
        self.assertNotIn(STALE_SCENE_UID, scene)
        self.assertNotIn(STALE_RES_UID, resource)

    def test_a_rerun_after_the_fix_reports_clean(self) -> None:
        """Convergence is the whole claim: a repair that leaves the gate red has
        described a change rather than made one."""
        with temp_repo('uid_repo', only=DRIFTED):
            _fix()
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid] PASS', out)

    def test_touches_only_the_uid_attribute(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED) as root:
            path = root / 'scenes/drifted.tscn'
            before = path.read_text(encoding='utf-8').splitlines()
            _fix()
            after = path.read_text(encoding='utf-8').splitlines()
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(len(before), len(after))
        self.assertEqual(changed[0][0].replace(STALE_SCENE_UID, ACTUAL_UID), changed[0][1])

    def test_leaves_the_other_ext_resource_and_trailing_comments_alone(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED) as root:
            _fix()
            scene = (root / 'scenes/drifted.tscn').read_text(encoding='utf-8')
            resource = (root / 'data/drifted.tres').read_text(encoding='utf-8')
        self.assertIn('uid="uid://dcleanscene0" path="res://scenes/clean.tscn"', scene)
        self.assertIn('speed = 4.0 ; a trailing comment the repair must not disturb',
                      resource)

    def test_fix_on_a_clean_tree_is_a_no_op_that_says_so(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            before = _snapshot(root)
            code, out = _fix()
            self.assertEqual(_snapshot(root), before)
        self.assertEqual(code, 0)
        self.assertIn('nothing to repair', out)

    def test_refuses_to_invent_a_uid_that_does_not_exist(self) -> None:
        """The unfixable half stays a finding: minting a uid for a script with no
        sidecar is invention, and exit 0 there would be a lie."""
        with temp_repo('uid_repo', only=GHOST) as root:
            before = (root / 'scenes/ghost_ref.tscn').read_text(encoding='utf-8')
            code, out = _fix()
            after = (root / 'scenes/ghost_ref.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, 1)
        self.assertEqual(after, before)
        self.assertIn('nothing to repair', out)
        self.assertIn('has NO .uid file', out)


class CliRouting(unittest.TestCase):
    """`--fix` is a contract on ONE gate; anywhere else it must be a loud usage
    error, because a consumer that thinks it asked for a repair and silently got
    a read-only run has been lied to."""

    def run_cli(self, *argv: str) -> tuple[int, str]:
        import contextlib
        import io

        from godot_devkit import cli
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = cli.main(list(argv))
        repo_root.cache_clear()
        load_config.cache_clear()
        return code, buffer.getvalue()

    def test_check_uid_fix_routes_to_the_repair(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED) as root:
            code, out = self.run_cli('check', 'uid', '--fix')
            scene = (root / 'scenes/drifted.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, 0, out)
        self.assertIn(ACTUAL_UID, scene)

    def test_fix_on_another_gate_is_a_usage_error(self) -> None:
        with temp_repo('uid_repo', only=CLEAN):
            code, out = self.run_cli('check', 'tres', '--fix')
        self.assertEqual(code, 2)
        self.assertIn('unexpected argument', out)

    def test_fix_on_the_aggregate_is_a_usage_error(self) -> None:
        with temp_repo('uid_repo', only=CLEAN):
            code, _ = self.run_cli('check', 'all', '--fix')
        self.assertEqual(code, 2)


class AggregateRoster(unittest.TestCase):
    """`[checks] all` — which gates apply to THIS repo. Five of the nine read
    `.tscn`/`.tres`/shell, so a repo holding none of them gets five 0-file
    censuses and rule 4 correctly reddens every one; that is the roster being
    wrong for the repo, not a reason to weaken a gate."""

    run_cli = CliRouting.run_cli

    def test_the_default_roster_is_every_gate_flagged_for_it(self) -> None:
        # ONE roster, with the answer to "is this in the default aggregate?"
        # on the gate itself. Two lists were two chances for a gate to be
        # dispatchable and invisible to `[checks] all`, or the reverse.
        from godot_devkit import cli
        with temp_repo('uid_repo', only=CLEAN):
            self.assertEqual(
                cli.all_roster(),
                tuple(n for n, on in cli.KNOWN_CHECKS.items() if on))

    def test_every_known_gate_is_dispatchable(self) -> None:
        # The property the split list could not state: a name `[checks] all`
        # accepts is a name `check <name>` runs. A gate in one and not the
        # other is either unreachable or a silent hole in the typo refusal.
        #
        # A SUBPROCESS per gate, for the reason `check doc` binds its scope and
        # its repo root at IMPORT: running nine gates in-process leaves that
        # module pointing at a deleted temp dir and the next test inherits it.
        # The assertion is routing only — a gate's own verdict is its own test.
        import subprocess
        from godot_devkit import cli
        with temp_repo('uid_repo', only=CLEAN) as root:
            for name in cli.KNOWN_CHECKS:
                with self.subTest(name):
                    proc = subprocess.run(
                        [sys.executable, '-m', 'godot_devkit.cli', 'check', name],
                        cwd=root, capture_output=True, text=True,
                        env={**os.environ,
                             'PYTHONPATH': str(REPO_ROOT / 'src')})
                    self.assertNotIn('unknown check',
                                     proc.stdout + proc.stderr)

    def test_a_declared_roster_runs_exactly_what_it_names(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\nall = ["uid"]\n', encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid]', out)
        self.assertNotIn('[check:tres]', out)

    def test_an_unknown_gate_name_is_exit_2_not_a_narrowed_run(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\nall = ["uid", "tres!"]\n', encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 2, out)
        self.assertIn('unknown gate(s) tres!', out)

    def test_a_bare_string_is_refused_rather_than_iterated(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\nall = "uid"\n', encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 2, out)
        self.assertIn('must be a list of strings', out)


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text(encoding='utf-8')
            for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.parts}


if __name__ == '__main__':
    unittest.main()
