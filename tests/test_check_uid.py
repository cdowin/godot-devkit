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
import re
import subprocess
import sys
import unittest
from pathlib import Path

from support import REPO_ROOT, run_check, temp_repo

from godot_devkit.godot.checks import tres, uid

BASE = ['project.godot', 'systems/rule.gd', 'systems/rule.gd.uid']
CLEAN = [*BASE, 'scenes/clean.tscn']
DRIFTED = [*CLEAN, 'scenes/drifted.tscn', 'data/drifted.tres']
GHOST = [*CLEAN, 'systems/ghost.gd', 'scenes/ghost_ref.tscn']
ORPHANED = [*CLEAN, 'systems/orphan.gd.uid']
NONCANON = [*CLEAN, 'data/noncanon.tres']
UNDECODABLE = [*CLEAN, 'data/invalid_uid.tres']
LEGACY = [*CLEAN, 'systems/legacy.gd', 'systems/legacy.gd.uid',
          'scenes/legacy_ref.tscn']
STALE_SCENE_UID = 'uid://dstaleuid000'
STALE_RES_UID = 'uid://dstaleuid001'
ACTUAL_UID = 'uid://drulescript'
# Real-world non-canonical spellings and their engine-canonical twins.
NONCANON_HEADER = 'uid://wkcycles00001'
CANON_HEADER = 'uid://c8bmebsj60m77'
NONCANON_REF = 'uid://zopk21mtzaqz'
CANON_REF = 'uid://0opk21mt0aq0'


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

    def test_fix_refuses_a_file_that_is_not_valid_utf8(self) -> None:
        """`_scan` reads with errors='replace'; the write path must neither
        crash on bytes that do not decode (the pre-fix UnicodeDecodeError mid
        `--fix`) nor lossily rewrite them — it refuses that file, repairs the
        rest, and the drift stays reported."""
        with temp_repo('uid_repo', only=DRIFTED) as root:
            scene = root / 'scenes/drifted.tscn'
            with scene.open('ab') as fh:
                fh.write(b'; \xff not utf-8\n')
            before = scene.read_bytes()
            code, out = _fix()
            after = scene.read_bytes()
            resource = (root / 'data/drifted.tres').read_text(encoding='utf-8')
        self.assertEqual(code, 1, out)
        self.assertIn('REFUSED  scenes/drifted.tscn', out)
        self.assertIn('not valid UTF-8', out)
        self.assertEqual(after, before)
        self.assertIn(f'DRIFT  scenes/drifted.tscn : {STALE_SCENE_UID}', out)
        # The decodable file's repair still lands.
        self.assertIn(f'uid="{ACTUAL_UID}" path="res://systems/rule.gd"', resource)

    def test_fix_preserves_crlf_line_endings_byte_for_byte(self) -> None:
        """Byte-surgical must hold for the cross-platform case too: the repair
        used to read universal-newline and write translated, so fixing ONE uid
        on a CRLF .tres rewrote EVERY line ending. The whole file is byte-
        compared: exactly the uid attribute's text differs, every CRLF
        terminator — including the repaired line's own — survives."""
        with temp_repo('uid_repo', only=CLEAN) as root:
            crlf = root / 'data' / 'crlf.tres'
            crlf.parent.mkdir(exist_ok=True)
            body = ('[gd_resource type="Resource" load_steps=2 format=3 '
                    'uid="uid://ddriftedres0"]\r\n\r\n'
                    f'[ext_resource type="Script" uid="{STALE_RES_UID}" '
                    'path="res://systems/rule.gd" id="1_rule"]\r\n\r\n'
                    '[resource]\r\nscript = ExtResource("1_rule")\r\n')
            crlf.write_bytes(body.encode())
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            before = crlf.read_bytes()
            code, out = _fix()
            after = crlf.read_bytes()
        expected = before.replace(STALE_RES_UID.encode(), ACTUAL_UID.encode())
        self.assertNotEqual(before, expected)     # the drift was really there
        self.assertEqual(code, 0, out)
        self.assertEqual(after, expected)

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


class NewScripts(unittest.TestCase):
    """CHECK 3 — the tracked census misses the moment of risk: a NEW .gd
    (untracked, or staged in a tree with no commit yet) with no sidecar on
    disk sails through a tracked-only gate and fails the next cold import."""

    def test_an_untracked_gd_without_a_sidecar_is_a_finding_naming_the_remedy(
            self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'systems/fresh.gd').write_text('extends Node\n',
                                                   encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn('MISSING  systems/fresh.gd is new and has no '
                      'systems/fresh.gd.uid', out)
        # The remedy is named IN the finding — minting is an editor-import
        # concern this package never performs itself.
        self.assertIn('godot --headless --import', out)
        self.assertIn('open the project in the editor once', out)

    def test_an_untracked_gd_with_an_on_disk_sidecar_passes(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'systems/fresh.gd').write_text('extends Node\n',
                                                   encoding='utf-8')
            (root / 'systems/fresh.gd.uid').write_text('uid://dfreshuid000\n',
                                                       encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)

    def test_a_gd_inside_an_untracked_directory_is_still_censused(self) -> None:
        """Plain porcelain collapses a new directory to one `?? dir/` line;
        without -uall the riskiest file shape is invisible."""
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'systems/newborn').mkdir()
            (root / 'systems/newborn/fresh.gd').write_text(
                'extends Node\n', encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn('MISSING  systems/newborn/fresh.gd', out)

    def test_a_gitignored_gd_is_not_censused(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / '.gitignore').write_text('generated/\n', encoding='utf-8')
            (root / 'generated').mkdir()
            (root / 'generated/gen.gd').write_text('extends Node\n',
                                                   encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertNotIn('gen.gd', out)

    def test_the_configured_exclude_scopes_check_3(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'addons').mkdir()
            (root / 'addons/vendored.gd').write_text('extends Node\n',
                                                     encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertNotIn('vendored.gd', out)

    def test_a_staged_new_gd_without_a_sidecar_is_censused_too(self) -> None:
        # In these fixture repos everything is staged-new (git add -A, no
        # commit): ghost.gd is exactly the staged shape, and it reports.
        with temp_repo('uid_repo', only=GHOST):
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn('MISSING  systems/ghost.gd', out)

    def test_the_census_line_discloses_the_new_buckets(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'systems/fresh.gd').write_text('extends Node\n',
                                                   encoding='utf-8')
            _, out = run_check(uid)
        # rule.gd is staged-new (no commit in a fixture repo) + fresh.gd
        # untracked = 2; one tracked sidecar; clean.tscn's header is the one
        # canonicality-checked uid (its Script ref is CHECK 1's domain).
        self.assertIn('[check:uid] census — 2 new (untracked/staged) .gd, '
                      '1 tracked .uid sidecar(s), '
                      '1 header/non-Script uid(s) canonicality-checked', out)


class OrphanSidecars(unittest.TestCase):
    """CHECK 4 — a tracked .gd.uid whose script is gone is cruft, and the ONE
    repair that is a deletion rather than a rewrite."""

    def test_a_tracked_sidecar_whose_script_is_gone_is_a_finding(self) -> None:
        with temp_repo('uid_repo', only=ORPHANED):
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn('ORPHAN  systems/orphan.gd.uid is tracked but '
                      'systems/orphan.gd is gone', out)
        self.assertIn('--fix deletes it', out)

    def test_a_sidecar_whose_script_exists_only_on_disk_is_not_cruft(self) -> None:
        """An untracked .gd next to its tracked sidecar is a script being
        born, not a script that died — deleting the sidecar would break the
        commit in progress."""
        with temp_repo('uid_repo', only=ORPHANED) as root:
            (root / 'systems/orphan.gd').write_text('extends Node\n',
                                                    encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertNotIn('ORPHAN', out)

    def test_fix_deletes_the_orphan_and_only_the_orphan(self) -> None:
        with temp_repo('uid_repo', only=ORPHANED) as root:
            before = _snapshot(root)
            code, out = _fix()
            after = _snapshot(root)
        self.assertEqual(code, 0, out)
        self.assertIn('FIXED  deleted systems/orphan.gd.uid', out)
        self.assertIn('[check:uid] FIX — deleted 1 orphan .uid sidecar(s)', out)
        del before['systems/orphan.gd.uid']
        self.assertEqual(after, before)

    def test_a_rerun_after_the_deletion_reports_clean(self) -> None:
        with temp_repo('uid_repo', only=ORPHANED):
            _fix()
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)

    def test_the_configured_exclude_scopes_check_4(self) -> None:
        with temp_repo('uid_repo', only=ORPHANED) as root:
            (root / 'devkit.toml').write_text(
                '[uid]\nexclude_prefixes = ["addons/", "systems/orphan"]\n',
                encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertNotIn('ORPHAN', out)


class Canonicality(unittest.TestCase):
    """CHECK 5 — a header / non-Script uid whose TEXT is not the engine's
    spelling is churn: Godot rewrites it on the next editor save. The verdict
    comes from the ported codec, never from the engine (rule 2)."""

    def test_the_fail_line_carries_the_census_like_the_pass_line(self) -> None:
        # Rule 4 both ways: a consumer greps `across N file(s)` on PASS and
        # FAIL alike — a failing verdict with no census is a gate that stopped
        # disclosing what it scanned the moment it mattered.
        with temp_repo('uid_repo', only=NONCANON):
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r'FAIL — \d+ \.uid drift / tracking '
                              r'violation\(s\) across \d+ file\(s\)')

    def test_non_canonical_spellings_are_findings_naming_the_canonical_form(
            self) -> None:
        with temp_repo('uid_repo', only=NONCANON):
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn(f'NON-CANONICAL  data/noncanon.tres : {NONCANON_HEADER} '
                      f'-> should be {CANON_HEADER}', out)
        self.assertIn(f'NON-CANONICAL  data/noncanon.tres : {NONCANON_REF} '
                      f'-> should be {CANON_REF}', out)
        self.assertIn('re-run with --fix', out)

    def test_an_undecodable_uid_is_reported_and_never_repaired(self) -> None:
        with temp_repo('uid_repo', only=UNDECODABLE) as root:
            code, out = run_check(uid)
            self.assertEqual(code, 1, out)
            self.assertIn('INVALID  data/invalid_uid.tres : uid://not_valid! '
                          'does not decode', out)
            self.assertNotIn('re-run with --fix', out)
            before = (root / 'data/invalid_uid.tres').read_text(encoding='utf-8')
            fix_code, fix_out = _fix()
            after = (root / 'data/invalid_uid.tres').read_text(encoding='utf-8')
        self.assertEqual(fix_code, 1, fix_out)
        self.assertEqual(after, before)
        self.assertIn('nothing to repair', fix_out)

    def test_a_script_ref_matching_its_sidecar_is_exempt(self) -> None:
        """The Script ref and its .gd.uid both carry the same non-canonical
        text: CHECK 1 pins ref to sidecar and owns that plane, so CHECK 5
        stays out — flagging one side would set the two gates at war."""
        with temp_repo('uid_repo', only=LEGACY):
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertNotIn('NON-CANONICAL', out)

    def test_fix_canonicalizes_byte_surgically_and_converges(self) -> None:
        with temp_repo('uid_repo', only=NONCANON) as root:
            path = root / 'data/noncanon.tres'
            before = path.read_text(encoding='utf-8').splitlines()
            code, out = _fix()
            after = path.read_text(encoding='utf-8').splitlines()
            rerun_code, rerun_out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid] FIX — canonicalized 2 uid spelling(s)', out)
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(changed), 2)
        self.assertEqual(len(before), len(after))
        self.assertEqual(changed[0][0].replace(NONCANON_HEADER, CANON_HEADER),
                         changed[0][1])
        self.assertEqual(changed[1][0].replace(NONCANON_REF, CANON_REF),
                         changed[1][1])
        self.assertEqual(rerun_code, 0, rerun_out)


SCRIPT_INVALID = [*CLEAN, 'data/script_invalid_uid.tres']


class ScriptUidCharset(unittest.TestCase):
    """CHECK 1's permissive census — a Script uid spelling outside [0-9a-z]
    used to fall off the strict regex and read as a path-only ref, CHECK 5
    exempts Script refs, and `check tres` only asks whether uid= is present:
    a hand-corrupted Script uid was invisible to all three gates at once."""

    def test_an_undecodable_script_uid_is_invalid_not_invisible(self) -> None:
        with temp_repo('uid_repo', only=SCRIPT_INVALID):
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn('INVALID  data/script_invalid_uid.tres : '
                      'uid://INVALIDUPPER does not decode as a resource uid',
                      out)
        # Not repairable: no should-be value exists, and the fix hint must
        # not advertise a repair the gate refuses to make.
        self.assertNotIn('re-run with --fix', out)

    def test_fix_never_touches_an_undecodable_script_uid(self) -> None:
        with temp_repo('uid_repo', only=SCRIPT_INVALID) as root:
            before = (root / 'data/script_invalid_uid.tres').read_bytes()
            code, out = _fix()
            after = (root / 'data/script_invalid_uid.tres').read_bytes()
        self.assertEqual(code, 1, out)
        self.assertEqual(after, before)
        self.assertIn('nothing to repair', out)

    def test_check_tres_cannot_see_it_which_is_why_check_1_owns_it(self) -> None:
        # Documents the sibling gate's contract: tres asks "is a uid=
        # present", not "does it decode" — without CHECK 1's permissive
        # census the spelling passes every gate.
        with temp_repo('uid_repo', only=SCRIPT_INVALID):
            code, out = run_check(tres)
        self.assertEqual(code, 0, out)


class TrackedButDeleted(unittest.TestCase):
    """A file in the git index but gone on disk (partial checkout, mid-rebase)
    is censused as an UNVERIFIED skip — never a FileNotFoundError traceback
    (exit 1 with a stack trace a hook reads as findings), never a silent
    drop. Mirrors `uid_index.from_repo_references`'s guard."""

    GAP = ('UNVERIFIED  data/drifted.tres — tracked in git but not readable '
           'on disk; not scanned')

    def test_check_uid_censuses_the_gap_and_still_reports_real_drift(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED) as root:
            (root / 'data/drifted.tres').unlink()
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)               # drifted.tscn stays red
        self.assertIn(self.GAP, out)
        self.assertIn('across 2 file(s)', out)       # the gap is not counted scanned

    def test_check_uid_passes_with_the_gap_disclosed_when_nothing_drifts(self) -> None:
        with temp_repo('uid_repo', only=[*CLEAN, 'data/drifted.tres']) as root:
            (root / 'data/drifted.tres').unlink()
            code, out = run_check(uid)
        self.assertEqual(code, 0, out)
        self.assertIn(self.GAP, out)

    def test_check_tres_reports_a_path_only_ref_and_censuses_the_gap(self) -> None:
        """Two claims on one run. The gap is censused instead of crashing, as
        for `check uid`. And the gate's one finding — an `[ext_resource]`
        with a path and no uid — is reported: amended in 0.25.0's probe pass,
        where a `check tres` whose path-only detector had gone blind reddened
        NOTHING in the suite (every tres case asked only for a PASS or a
        census). This is the cheapest tres run, so it carries the finding."""
        with temp_repo('uid_repo', only=DRIFTED) as root:
            (root / 'data/drifted.tres').unlink()
            scene = root / 'scenes/drifted.tscn'
            scene.write_text(scene.read_text(encoding='utf-8').replace(
                'uid="uid://dcleanscene0" ', '', 1), encoding='utf-8')
            code, out = run_check(tres)
        self.assertEqual(code, 1, out)
        self.assertIn(self.GAP, out)
        self.assertIn('PATH-ONLY  scenes/drifted.tscn:6:', out)
        self.assertIn('1 path-only ext_resource ref(s) across 2 file(s)', out)


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

    # The verb surface after the repo family left (0.25.0). One tuple, asked
    # of both `--help` and the router: a verb documented and not routed, or
    # routed and not documented, is the drift this pins.
    GODOT_VERBS = ('scene', 'tiles', 'scene-diff', 'refs', 'orphans',
                   'autoloads', 'install-runners', 'check')
    RETIRED = ('pm', 'init', 'gates-extra', 'install-ci', 'install-agents',
               'install-hooks', 'install-gates', 'install-sdlc')

    def test_help_lists_exactly_the_godot_verbs(self) -> None:
        from godot_devkit import cli
        code, out = self.run_cli('--help')
        self.assertEqual(code, 0)
        documented = {m.group(1) for m in re.finditer(
            r'^\s+godot-devkit ([a-z-]+)', out, re.M)}
        self.assertEqual(documented, set(self.GODOT_VERBS), documented)
        self.assertEqual(set(self.RETIRED), set(cli.RETIRED_COMMANDS))
        self.assertEqual(set(cli.KNOWN_GATES),
                         {'uid', 'tres', 'props', 'defaults', 'rng',
                          'tres-comment', 'unit-disk', 'test-shape'})

    def test_a_retired_verb_exits_2_naming_the_second_pin(self) -> None:
        # One line, exit 2, and the line says where the verb went: a consumer
        # whose Makefile still says `godot-devkit pm` is told about the second
        # pin rather than about an unknown command.
        retired = ([(verb,) for verb in self.RETIRED]
                   + [('check', gate) for gate in
                      ('doc', 'shell', 'pm', 'hooks', 'repo-hygiene')])
        for argv in retired:
            with self.subTest(argv=argv):
                with temp_repo('uid_repo', only=CLEAN):
                    code, out = self.run_cli(*argv)
                self.assertEqual(code, 2, out)
                self.assertEqual(len(out.strip().splitlines()), 1, out)
                self.assertIn('agentic-sdlc', out)
                self.assertNotIn('unknown command', out)


class AggregateRoster(unittest.TestCase):
    """`[checks] godot` — which gates apply to THIS repo. Most of the roster
    reads `.tscn`/`.tres`/`.gd`, so a repo holding none of them gets a
    handful of 0-file censuses and rule 4 correctly reddens every one; that is
    the roster being wrong for the repo, not a reason to weaken a gate. The
    key is `godot`, not `all`: `all` is agentic-sdlc's roster in the same
    devkit.toml, and each kit refuses a name it does not know."""

    run_cli = CliRouting.run_cli
    THE_EIGHT = ('uid', 'tres', 'props', 'defaults', 'rng', 'tres-comment',
                 'unit-disk', 'test-shape')

    def _check_all(self, root: Path) -> tuple[int, str]:
        # A fresh process, so two runs compare bytes and not cache state.
        proc = subprocess.run(
            [sys.executable, '-m', 'godot_devkit.cli', 'check', 'all'],
            cwd=root, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
        return proc.returncode, proc.stdout + proc.stderr

    def test_the_stock_roster_is_the_eight_and_declaring_them_changes_nothing(self) -> None:
        # ONE roster: the eight, in the order they run, and a repo with NO
        # devkit.toml gets byte-identical output to one declaring exactly
        # that (rule 5). Asked of the committed clean Godot project, where
        # all eight PASS — the tree `make godot-check` stages for this repo's
        # own `make check`, so what is proven here is what that gate runs.
        from godot_devkit import cli
        self.assertEqual(cli.KNOWN_GATES, self.THE_EIGHT)
        with temp_repo('godot_project') as root:
            self.assertEqual(cli.all_roster(), self.THE_EIGHT)
            stock_code, stock = self._check_all(root)
            (root / 'devkit.toml').write_text(
                '[checks]\ngodot = [' + ', '.join(f'"{g}"' for g in self.THE_EIGHT)
                + ']\n', encoding='utf-8')
            declared_code, declared = self._check_all(root)
        self.assertEqual(stock_code, 0, stock)
        self.assertEqual(declared_code, 0, declared)
        self.assertEqual(stock, declared)
        for gate in self.THE_EIGHT:
            self.assertIn(f'[check:{gate}] PASS', stock)

    def test_every_known_gate_is_dispatchable(self) -> None:
        # The property the split list could not state: a name `[checks]
        # godot` accepts is a name `check <name>` runs. A gate in one and not
        # the other is either unreachable or a silent hole in the typo refusal.
        #
        # A SUBPROCESS per gate, so nothing a gate caches at import outlives
        # the temp repo it was pointed at. The assertion is routing only — a
        # gate's own verdict is its own test.
        from godot_devkit import cli
        with temp_repo('uid_repo', only=CLEAN) as root:
            for name in cli.KNOWN_GATES:
                with self.subTest(name):
                    proc = subprocess.run(
                        [sys.executable, '-m', 'godot_devkit.cli', 'check', name],
                        cwd=root, capture_output=True, text=True,
                        env={**os.environ,
                             'PYTHONPATH': str(REPO_ROOT / 'src')})
                    self.assertNotIn('unknown check',
                                     proc.stdout + proc.stderr)

    def test_every_known_gate_answers_help_with_its_own_contract(self) -> None:
        # `check <gate> --help` prints that gate's MODULE DOCSTRING — the one
        # copy, so the help and the contract cannot drift apart. A gate whose
        # docstring never names its config section is a gate whose scope a
        # consumer has to read the source to discover.
        from godot_devkit import cli
        with temp_repo('uid_repo', only=CLEAN) as root:
            for name in cli.KNOWN_GATES:
                with self.subTest(name):
                    proc = subprocess.run(
                        [sys.executable, '-m', 'godot_devkit.cli', 'check',
                         name, '--help'],
                        cwd=root, capture_output=True, text=True,
                        env={**os.environ,
                             'PYTHONPATH': str(REPO_ROOT / 'src')})
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertIn(name, proc.stdout)

    def test_help_on_an_unknown_gate_is_exit_2_not_an_empty_page(self) -> None:
        with temp_repo('uid_repo', only=CLEAN):
            code, out = self.run_cli('check', 'rng!', '--help')
        self.assertEqual(code, 2, out)
        self.assertIn('unknown check', out)

    def test_a_declared_roster_runs_exactly_what_it_names(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\ngodot = ["uid"]\n', encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid]', out)
        self.assertNotIn('[check:tres]', out)

    def test_the_other_kits_roster_key_is_not_read(self) -> None:
        # `[checks] all` is agentic-sdlc's, and it names gates this package
        # has never heard of. Reading it would refuse every two-pin tree.
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\nall = ["doc", "pm"]\ngodot = ["uid"]\n',
                encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 0, out)
        self.assertIn('[check:uid]', out)

    def test_an_unknown_gate_name_is_exit_2_not_a_narrowed_run(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\ngodot = ["uid", "tres!"]\n', encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 2, out)
        self.assertIn('unknown gate(s) tres!', out)

    def test_a_bare_string_is_refused_rather_than_iterated(self) -> None:
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'devkit.toml').write_text(
                '[checks]\ngodot = "uid"\n', encoding='utf-8')
            code, out = self.run_cli('check', 'all')
        self.assertEqual(code, 2, out)
        self.assertIn('must be a list of strings', out)


def _snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text(encoding='utf-8')
            for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.parts}


if __name__ == '__main__':
    unittest.main()
