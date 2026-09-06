"""Tier 2 — `check uid`, and the repair it can now apply.

The gate has always known the should-be value; `--fix` writes it. The cases
that matter are the ones where a repair could lie: it must rewrite ONLY the
stale uid attribute (every other byte of the file identical), it must leave a
drift it cannot resolve from evidence alone — a target with no `.uid` at all —
reported and untouched, and a re-run after a fix must come back clean, because
a repair that does not converge is worse than no repair.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from support import REPO_ROOT, run_check, temp_repo

from godot_devkit import cli
from godot_devkit.godot.checks import tres, uid

CLEAN = ['project.godot', 'systems/rule.gd', 'systems/rule.gd.uid', 'scenes/clean.tscn']
DRIFTED = [*CLEAN, 'scenes/drifted.tscn', 'data/drifted.tres']
GHOST = [*CLEAN, 'systems/ghost.gd', 'scenes/ghost_ref.tscn']
ORPHANED = [*CLEAN, 'systems/orphan.gd.uid']
# noncanon.tres carries a non-canonical header and non-Script ref; legacy_ref's
# Script ref and legacy.gd.uid both carry the SAME non-canonical text.
NONCANON = [*CLEAN, 'data/noncanon.tres', 'systems/legacy.gd',
            'systems/legacy.gd.uid', 'scenes/legacy_ref.tscn']
STALE_SCENE_UID = 'uid://dstaleuid000'
STALE_RES_UID = 'uid://dstaleuid001'
ACTUAL_UID = 'uid://drulescript'
# Real-world non-canonical spellings and their engine-canonical twins.
NONCANON_HEADER = 'uid://wkcycles00001'
CANON_HEADER = 'uid://c8bmebsj60m77'
NONCANON_REF = 'uid://zopk21mtzaqz'
CANON_REF = 'uid://0opk21mt0aq0'


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.parts}


def run_cli(*argv: str) -> tuple[int, str]:
    # `cli.main` through the same cache-clearing scaffolding as a gate, with
    # stderr (where usage errors go) appended to stdout.
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code, out = run_check(SimpleNamespace(run=cli.main), argv=list(argv))
    return code, out + err.getvalue()


class Reports(unittest.TestCase):
    def test_a_target_without_a_sidecar_is_reported_not_offered_for_repair(self) -> None:
        # The unfixable half stays a finding under `--fix` too: minting a uid
        # for a script with no sidecar is invention, and exit 0 there would be
        # a lie. ghost.gd is also staged-new with no sidecar — CHECK 3's shape.
        with temp_repo('uid_repo', only=GHOST) as root:
            code, out = run_check(uid)
            before = _snapshot(root)
            fix_code, fix_out = run_check(uid, fix=True)
            after = _snapshot(root)
        self.assertEqual(code, 1)
        self.assertIn('has NO .uid file', out)
        self.assertNotIn('re-run with --fix', out)
        self.assertIn('MISSING  systems/ghost.gd', out)
        self.assertEqual(fix_code, 1)
        self.assertEqual(after, before)
        self.assertIn('nothing to repair', fix_out)
        self.assertIn('has NO .uid file', fix_out)

    def test_the_configured_exclude_scopes_every_check_and_an_eaten_census_fails(
            self) -> None:
        # One documented key, one scope: `run()` reads `[uid] exclude_prefixes`
        # once through `str_tuple` and hands that tuple to every check. Read
        # only in CHECK 1, an excluded tree still had every sidecar-less `.gd`
        # in it reported — the key a consumer set to scope this gate did not.
        # And an exclude that eats the whole census FAILS saying how many it
        # ate (rule 4).
        with temp_repo('uid_repo', only=GHOST) as root:
            (root / 'devkit.toml').write_text(
                '[uid]\nexclude_prefixes = ["addons/", "systems/ghost"]\n',
                encoding='utf-8')
            code, out = run_check(uid)
            (root / 'devkit.toml').write_text(
                '[uid]\nexclude_prefixes = ["scenes/", "systems/"]\n',
                encoding='utf-8')
            eaten_code, eaten = run_check(uid)
        self.assertNotIn('systems/ghost.gd has no tracked', out)
        # The .tscn referencing it is still in scope, so CHECK 1 still reports.
        self.assertEqual(code, 1, out)
        self.assertIn('ghost_ref.tscn', out)
        self.assertEqual(eaten_code, 1, eaten)
        self.assertIn('scanned 0 of 2 tracked', eaten)

    def test_drift_is_named_then_rewritten_byte_surgically_and_converges(self) -> None:
        # The gate bite first: the finding names the should-be value. Then the
        # repair, byte-surgical across LF and CRLF alike — every repaired file
        # equals its old bytes with exactly the stale uid text swapped, so the
        # other ext_resource, the trailing comment and every line terminator
        # survive (the repair used to read universal-newline and write
        # translated, so fixing ONE uid on a CRLF .tres rewrote EVERY line
        # ending) — and the re-run is a clean PASS with its census, because a
        # repair that leaves the gate red has described a change rather than
        # made one.
        with temp_repo('uid_repo', only=DRIFTED) as root:
            (root / 'data/crlf.tres').write_bytes(
                b'[gd_resource type="Resource" load_steps=2 format=3 '
                b'uid="uid://ddriftedres0"]\r\n\r\n'
                b'[ext_resource type="Script" uid="' + STALE_RES_UID.encode()
                + b'" path="res://systems/rule.gd" id="1_rule"]\r\n\r\n'
                b'[resource]\r\nscript = ExtResource("1_rule")\r\n')
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            code, out = run_check(uid)
            before = _snapshot(root)
            fix_code, fix_out = run_check(uid, fix=True)
            after = _snapshot(root)
            rerun_code, rerun_out = run_check(uid)
        self.assertEqual(code, 1)
        self.assertIn(f'DRIFT  scenes/drifted.tscn : {STALE_SCENE_UID} -> should be '
                      f'{ACTUAL_UID}', out)
        self.assertIn('re-run with --fix', out)
        self.assertEqual(fix_code, 0, fix_out)
        self.assertIn('[check:uid] FIX — repaired 3 stale uid ref(s)', fix_out)
        self.assertIn(f'FIXED  scenes/drifted.tscn : {STALE_SCENE_UID} -> {ACTUAL_UID}',
                      fix_out)
        for rel, old in {'scenes/drifted.tscn': STALE_SCENE_UID,
                         'data/drifted.tres': STALE_RES_UID,
                         'data/crlf.tres': STALE_RES_UID}.items():
            self.assertEqual(before[rel].count(old.encode()), 1, rel)
            before[rel] = before[rel].replace(old.encode(), ACTUAL_UID.encode())
        self.assertEqual(after, before)
        self.assertEqual(rerun_code, 0, rerun_out)
        self.assertIn('[check:uid] PASS — 4 Script ref(s) across 4 file(s)', rerun_out)

    def test_fix_refuses_a_file_that_is_not_valid_utf8(self) -> None:
        # `_scan` reads with errors='replace'; the write path must neither
        # crash on bytes that do not decode (the pre-fix UnicodeDecodeError mid
        # `--fix`) nor lossily rewrite them — it refuses that file, repairs the
        # rest, and the drift stays reported.
        with temp_repo('uid_repo', only=DRIFTED) as root:
            scene = root / 'scenes/drifted.tscn'
            with scene.open('ab') as fh:
                fh.write(b'; \xff not utf-8\n')
            before = scene.read_bytes()
            code, out = run_check(uid, fix=True)
            after = scene.read_bytes()
            resource = (root / 'data/drifted.tres').read_text(encoding='utf-8')
        self.assertEqual(code, 1, out)
        self.assertIn('REFUSED  scenes/drifted.tscn — not valid UTF-8', out)
        self.assertEqual(after, before)
        self.assertIn(f'DRIFT  scenes/drifted.tscn : {STALE_SCENE_UID}', out)
        # The decodable file's repair still lands.
        self.assertIn(f'uid="{ACTUAL_UID}" path="res://systems/rule.gd"', resource)


class Sidecars(unittest.TestCase):
    """CHECK 3 — the tracked census misses the moment of risk: a NEW .gd
    (untracked, or staged in a tree with no commit yet) with no sidecar on
    disk sails through a tracked-only gate and fails the next cold import.
    CHECK 4 — a tracked .gd.uid whose script is gone is cruft, and the ONE
    repair that is a deletion rather than a rewrite."""

    def test_an_untracked_gd_without_a_sidecar_is_a_finding_naming_the_remedy(
            self) -> None:
        # Inside a NEW directory: plain porcelain collapses it to one
        # `?? dir/` line, and without -uall the riskiest file shape is
        # invisible. The census line discloses the buckets the check counted.
        with temp_repo('uid_repo', only=CLEAN) as root:
            (root / 'systems/newborn').mkdir()
            (root / 'systems/newborn/fresh.gd').write_text(
                'extends Node\n', encoding='utf-8')
            code, out = run_check(uid)
        self.assertEqual(code, 1, out)
        for needle in (
                'MISSING  systems/newborn/fresh.gd is new and has no '
                'systems/newborn/fresh.gd.uid',
                # The remedy is named IN the finding — minting is an
                # editor-import concern this package never performs itself.
                'godot --headless --import',
                'open the project in the editor once',
                # rule.gd is staged-new (no commit in a fixture repo) +
                # fresh.gd untracked = 2; one tracked sidecar; clean.tscn's
                # header is the one canonicality-checked uid (its Script ref
                # is CHECK 1's domain).
                '[check:uid] census — 2 new (untracked/staged) .gd, '
                '1 tracked .uid sidecar(s), '
                '1 header/non-Script uid(s) canonicality-checked'):
            self.assertIn(needle, out)

    def test_a_gone_script_is_a_finding_and_fix_deletes_only_its_sidecar(self) -> None:
        # First with the script present but UNTRACKED: a script being born,
        # not one that died — deleting its sidecar would break the commit in
        # progress. Then gone for real.
        with temp_repo('uid_repo', only=ORPHANED) as root:
            (root / 'systems/orphan.gd').write_text('extends Node\n', encoding='utf-8')
            born_code, born = run_check(uid)
            (root / 'systems/orphan.gd').unlink()
            code, out = run_check(uid)
            before = _snapshot(root)
            fix_code, fix_out = run_check(uid, fix=True)
            after = _snapshot(root)
            rerun_code, rerun_out = run_check(uid)
        self.assertEqual(born_code, 0, born)
        self.assertNotIn('ORPHAN', born)
        self.assertEqual(code, 1, out)
        self.assertIn('ORPHAN  systems/orphan.gd.uid is tracked but '
                      'systems/orphan.gd is gone', out)
        self.assertIn('--fix deletes it', out)
        self.assertEqual(fix_code, 0, fix_out)
        self.assertIn('FIXED  deleted systems/orphan.gd.uid', fix_out)
        self.assertIn('[check:uid] FIX — deleted 1 orphan .uid sidecar(s)', fix_out)
        del before['systems/orphan.gd.uid']
        self.assertEqual(after, before)
        self.assertEqual(rerun_code, 0, rerun_out)


class Canonicality(unittest.TestCase):
    """CHECK 5 — a header / non-Script uid whose TEXT is not the engine's
    spelling is churn: Godot rewrites it on the next editor save. The verdict
    comes from the ported codec, never from the engine (rule 2)."""

    def test_non_canonical_spellings_are_named_then_fixed_byte_surgically(self) -> None:
        # Exactly TWO findings: legacy_ref's Script ref and its .gd.uid carry
        # the same non-canonical text, and CHECK 1 pins ref to sidecar and
        # owns that plane, so CHECK 5 stays out — flagging one side would set
        # the two gates at war, and `--fix` would never converge.
        with temp_repo('uid_repo', only=NONCANON) as root:
            code, out = run_check(uid)
            before = _snapshot(root)
            fix_code, fix_out = run_check(uid, fix=True)
            after = _snapshot(root)
            rerun_code, rerun_out = run_check(uid)
        self.assertEqual(code, 1, out)
        self.assertIn(f'NON-CANONICAL  data/noncanon.tres : {NONCANON_HEADER} '
                      f'-> should be {CANON_HEADER}', out)
        self.assertIn(f'NON-CANONICAL  data/noncanon.tres : {NONCANON_REF} '
                      f'-> should be {CANON_REF}', out)
        self.assertEqual(out.count('NON-CANONICAL  '), 2, out)
        self.assertIn('re-run with --fix', out)
        # Rule 4 both ways: a consumer greps `across N file(s)` on PASS and
        # FAIL alike — a failing verdict with no census is a gate that stopped
        # disclosing what it scanned the moment it mattered.
        self.assertRegex(out, r'FAIL — \d+ \.uid drift / tracking '
                              r'violation\(s\) across \d+ file\(s\)')
        self.assertEqual(fix_code, 0, fix_out)
        self.assertIn('[check:uid] FIX — canonicalized 2 uid spelling(s)', fix_out)
        for spelt, canon in ((NONCANON_HEADER, CANON_HEADER), (NONCANON_REF, CANON_REF)):
            self.assertEqual(before['data/noncanon.tres'].count(spelt.encode()), 1)
            before['data/noncanon.tres'] = before['data/noncanon.tres'].replace(
                spelt.encode(), canon.encode())
        self.assertEqual(after, before)
        self.assertEqual(rerun_code, 0, rerun_out)

    def test_an_undecodable_uid_is_reported_and_never_repaired(self) -> None:
        # Two branches, one run: a header/non-Script uid that does not decode
        # (CHECK 5's INVALID), and a Script uid outside [0-9a-z] — which used
        # to fall off CHECK 1's strict regex and read as a path-only ref,
        # while CHECK 5 exempts Script refs and `check tres` only asks whether
        # uid= is present: a hand-corrupted Script uid was invisible to all
        # three gates at once. Neither is repairable — no should-be value
        # exists — and the fix hint must not advertise a repair the gate
        # refuses to make.
        with temp_repo('uid_repo', only=[*CLEAN, 'data/invalid_uid.tres',
                                         'data/script_invalid_uid.tres']) as root:
            code, out = run_check(uid)
            before = _snapshot(root)
            fix_code, fix_out = run_check(uid, fix=True)
            after = _snapshot(root)
        self.assertEqual(code, 1, out)
        self.assertIn('INVALID  data/invalid_uid.tres : uid://not_valid! '
                      'does not decode', out)
        self.assertIn('INVALID  data/script_invalid_uid.tres : '
                      'uid://INVALIDUPPER does not decode as a resource uid', out)
        self.assertNotIn('re-run with --fix', out)
        self.assertEqual(fix_code, 1, fix_out)
        self.assertEqual(after, before)
        self.assertIn('nothing to repair', fix_out)


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

    def test_check_tres_reports_a_path_only_ref_and_censuses_the_gap(self) -> None:
        """Two claims on one run. The gap is censused instead of crashing, as
        for `check uid`. And the gate's one finding — an `[ext_resource]`
        with a path and no uid — is reported: amended in 0.25.0's probe pass,
        where a `check tres` whose path-only detector had gone blind reddened
        NOTHING in the suite (every tres case asked only for a PASS or a
        census). This is the cheapest tres run, so it carries the finding —
        and, since 0.25.0's review, the ZERO-CENSUS half too: `tres` was the
        one gate of eight whose rule-4 guard was asserted by nothing, so
        disarming `if not checked:` left the whole suite green."""
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
        # Rule 4's half: a tree holding no .tres/.tscn at all FAILS rather
        # than PASSing over nothing, and says which "0" it means.
        with temp_repo('uid_repo', only=[]):
            empty_code, empty_out = run_check(tres)
        self.assertEqual(empty_code, 1, empty_out)
        self.assertIn('[check:tres] FAIL — scanned 0 of 0 tracked', empty_out)


class CliRouting(unittest.TestCase):
    """`--fix` is a contract on ONE gate; anywhere else it must be a loud usage
    error, because a consumer that thinks it asked for a repair and silently got
    a read-only run has been lied to. `[checks] godot` — which gates apply to
    THIS repo. Most of the roster reads `.tscn`/`.tres`/`.gd`, so a repo
    holding none of them gets a handful of 0-file censuses and rule 4 correctly
    reddens every one; that is the roster being wrong for the repo, not a
    reason to weaken a gate. The key is `godot`, not `all`: `all` is
    agentic-sdlc's roster in the same devkit.toml, and each kit refuses a name
    it does not know."""

    THE_EIGHT = ('uid', 'tres', 'props', 'defaults', 'rng', 'tres-comment',
                 'unit-disk', 'test-shape')

    def _check_all(self, root: Path) -> tuple[int, str]:
        # A fresh process, so two runs compare bytes and not cache state.
        proc = subprocess.run(
            [sys.executable, '-m', 'godot_devkit.cli', 'check', 'all'],
            cwd=root, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
        return proc.returncode, proc.stdout + proc.stderr

    def test_fix_routes_to_uid_and_is_a_usage_error_anywhere_else(self) -> None:
        with temp_repo('uid_repo', only=DRIFTED) as root:
            code, out = run_cli('check', 'uid', '--fix')
            scene = (root / 'scenes/drifted.tscn').read_text(encoding='utf-8')
            tres_code, tres_out = run_cli('check', 'tres', '--fix')
            all_code, _ = run_cli('check', 'all', '--fix')
        self.assertEqual(code, 0, out)
        self.assertIn(ACTUAL_UID, scene)
        self.assertEqual(tres_code, 2)
        self.assertIn('unexpected argument', tres_out)
        self.assertEqual(all_code, 2)

    def test_the_stock_roster_is_the_eight_and_a_declared_one_runs_what_it_names(
            self) -> None:
        # ONE roster: the eight, in the order they run, and a repo with NO
        # devkit.toml gets byte-identical output to one declaring exactly
        # that (rule 5). Asked of the committed clean Godot project, where
        # all eight PASS — the tree `make godot-check` stages for this repo's
        # own `make check`, so what is proven here is what that gate runs;
        # every known gate dispatching is the same run. Then a roster naming
        # one gate runs that gate only — and `[checks] all`, agentic-sdlc's
        # key naming gates this package has never heard of, is not read.
        self.assertEqual(cli.KNOWN_GATES, self.THE_EIGHT)
        with temp_repo('godot_project') as root:
            stock_code, stock = self._check_all(root)
            (root / 'devkit.toml').write_text(
                '[checks]\ngodot = [' + ', '.join(f'"{g}"' for g in self.THE_EIGHT)
                + ']\n', encoding='utf-8')
            declared_code, declared = self._check_all(root)
            (root / 'devkit.toml').write_text(
                '[checks]\nall = ["doc", "pm"]\ngodot = ["uid"]\n',
                encoding='utf-8')
            one_code, one = run_cli('check', 'all')
        self.assertEqual((stock_code, declared_code), (0, 0), stock + declared)
        self.assertEqual(stock, declared)
        for gate in self.THE_EIGHT:
            self.assertIn(f'[check:{gate}] PASS', stock)
        self.assertEqual(one_code, 0, one)
        self.assertIn('[check:uid]', one)
        self.assertNotIn('[check:tres]', one)

    def test_a_bad_roster_is_exit_2_not_a_narrowed_run(self) -> None:
        # Two grammars the roster reader must refuse: a name it does not know,
        # and a bare string (which `tuple(...)` would iterate into letters).
        with temp_repo('uid_repo', only=CLEAN) as root:
            for toml, needle in (('["uid", "tres!"]', 'unknown gate(s) tres!'),
                                 ('"uid"', 'must be a list of strings')):
                with self.subTest(toml):
                    (root / 'devkit.toml').write_text(f'[checks]\ngodot = {toml}\n',
                                                      encoding='utf-8')
                    code, out = run_cli('check', 'all')
                    self.assertEqual(code, 2, out)
                    self.assertIn(needle, out)
