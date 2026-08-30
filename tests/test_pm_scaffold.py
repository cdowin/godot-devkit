"""`pm new` / `pm templates` — scaffolding, slug hygiene, template minting,
and the no-deleter contract over the caller\'s own tree.

Split from test_pm.py by concern; the shared harness is tests/support/pm.py.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from support.pm import run_cli, run_gate, tree, write

from godot_devkit.repo.pm import cli, model, templates

LEGACY_LOG = '# legacy log\n\nM1 said something.\n'


class Scaffolding(unittest.TestCase):
    def test_new_grains_round_trip_into_a_clean_gate(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')[0], 0)
            self.assertEqual(
                run_cli(root, 'new', 'story', '0.1/beta', 'first', 'First')[0], 0)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 feature(s), 2 story/ies', out)

    def test_new_is_idempotent_over_an_existing_grain(self):
        # This is how a consumer MIGRATES. A tree of 22 milestones and 136
        # features cannot be hand-shaped, so re-running the scaffolder has to
        # fill gaps and leave every existing byte alone.
        with tree(story_statuses=('todo',)) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_text(encoding='utf-8')
            code, out = run_cli(root, 'new', 'feature', '0.1', 'alpha')
            self.assertEqual(code, 0, out)
            self.assertEqual(ff.read_text(encoding='utf-8'), before)
            for slot in model.FEATURE_FILE_SLOTS:
                self.assertTrue((ff.parent / slot).is_file(), slot)

            # Second run: nothing left to do, and it says so.
            code, out = run_cli(root, 'new', 'feature', '0.1', 'alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('already has every canonical slot', out)
            self.assertEqual(ff.read_text(encoding='utf-8'), before)

    def test_new_fills_a_milestones_slots_without_touching_milestone_md(self):
        with tree(story_statuses=('todo',)) as root:
            mf = root / 'pm/roadmap/0.1-demo/milestone.md'
            before = mf.read_text(encoding='utf-8')
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(mf.read_text(encoding='utf-8'), before)
            for slot in model.MILESTONE_FILE_SLOTS:
                self.assertTrue((mf.parent / slot).is_file(), slot)

    def test_a_legacy_uppercase_slot_is_refused_never_renamed_or_twinned(self):
        # The uppercase->lowercase migration is COMPLETE in every consumer and
        # the rename machinery is retired. The CHOSEN successor behavior: a
        # leftover case variant is a refusal that names it and the canonical
        # name — never a rename, and never a `decisions.md` minted beside
        # `DECISIONS.md` (a twin on a case-sensitive filesystem, a truncation
        # of the legacy bytes on an insensitive one).
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            legacy = mdir / 'DECISIONS.md'
            model.write_raw(legacy, LEGACY_LOG)
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('REFUSED', out)
            self.assertIn('DECISIONS.md', out)
            self.assertIn('decisions.md', out)
            self.assertIn('nothing was written', out)
            entries = model.dir_entries(mdir)
            # EXACT names: on macOS `exists('decisions.md')` answers True off
            # the DECISIONS.md sitting there, so only a listing can prove no
            # twin was minted and no rename ran.
            self.assertEqual(entries.get('DECISIONS.md'), 'file')
            self.assertNotIn('decisions.md', entries)
            self.assertNotIn('handoff.md', entries)
            self.assertEqual(model.read_raw(legacy), LEGACY_LOG)

    def test_new_refuses_a_file_slot_that_exists_as_a_directory(self):
        # Rule 6 reserves exit 1 for FINDINGS, so an uncaught IsADirectoryError
        # reads to a consumer's hook as "drift found" with a traceback attached.
        # ScaffoldRefused is the shape, and it refuses before anything moves.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            (mdir / model.DECISION_FILE_NAME).mkdir()
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('REFUSED', out)
            self.assertIn('is a DIRECTORY', out)
            self.assertIn('nothing was written', out)
            self.assertFalse((mdir / 'handoff.md').exists())

    def test_new_refuses_a_slot_it_cannot_prepend_a_header_to(self):
        # `_fill_header` guarded the READ and not the write, so a read-only
        # legacy doc raised `PermissionError` — a traceback, exit 1, and the
        # remaining slots never created. Writability is inspectable up front.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            model.write_raw(mdir / 'handoff.md', 'legacy prose\n')
            model.write_raw(mdir / 'decisions.md', LEGACY_LOG)
            (mdir / 'handoff.md').chmod(0o444)
            try:
                code, out = run_cli(root, 'new', 'milestone', '0.1')
                self.assertEqual(code, 1, out)
                self.assertIn('is not writable', out)
                self.assertIn('nothing was written', out)
                self.assertNotIn('Traceback', out)
                self.assertEqual(model.read_raw(mdir / 'decisions.md'), LEGACY_LOG)
            finally:
                (mdir / 'handoff.md').chmod(0o644)
            # And it goes through once the mode allows it.
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            self.assertTrue((mdir / 'handoff.md').is_file())

    def test_new_refuses_an_undecodable_template_before_the_first_write(self):
        # A latin-1 byte in a project's `template_dir` raised
        # `UnicodeDecodeError` from inside the slot loop, two files in. Every
        # template the grain needs is loaded and decoded before anything lands.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'templates')[0], 0)
            (root / 'pm/templates/milestone.md').write_bytes(b'caf\xe9\n')
            (root / 'pm/roadmap/0.1-demo/milestone.md').unlink()
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('template cannot be read', out)
            self.assertIn('nothing was written', out)
            self.assertNotIn('Traceback', out)
            self.assertFalse((root / 'pm/roadmap/0.1-demo/milestone.md').exists())

    def test_decide_refuses_an_undecodable_decisions_template(self):
        # `pm decide` mints the log on first write, so the decode that used to
        # happen inside `pm new` now happens here — and it refuses the same
        # way, with the grain byte-identical.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'templates')[0], 0)
            (root / 'pm/templates/decisions.md').write_bytes(b'caf\xe9\n')
            code, out = run_cli(root, 'decide', '0.1', 'a choice')
            self.assertEqual(code, 2, out)
            self.assertIn('template cannot be read', out)
            self.assertNotIn('Traceback', out)
            self.assertFalse(
                (root / 'pm/roadmap/0.1-demo/decisions.md').exists())

    def test_new_reports_a_write_that_no_listing_could_have_predicted(self):
        # Not everything is pre-inspectable — a mode changed under us, a disk
        # that fills. Rule 6 still holds: exit 1 is a finding a consumer's hook
        # can print, so the escaping exception becomes a refusal that names
        # exactly which slots did land rather than a stack trace over them.
        with tree(story_statuses=('todo',)) as root:
            gdir = root / 'pm/roadmap/0.2-second'
            real = templates.write

            def flaky(path: Path, text: str) -> None:
                if path.name == 'milestone.md':
                    raise OSError(28, 'No space left on device')
                real(path, text)

            with unittest.mock.patch.object(templates, 'write', flaky):
                code, out = run_cli(root, 'new', 'milestone', '0.2', 'Second')
            self.assertEqual(code, 1, out)
            self.assertNotIn('Traceback', out)
            self.assertIn('No space left on device', out)
            self.assertIn('PART-FILLED', out)
            # The grain file is the FIRST write, so the honest report is that
            # nothing had landed — the claim has to track the truth in both
            # directions, not only when something did.
            self.assertIn('nothing had been written yet', out)
            self.assertFalse((gdir / 'features').exists())

    def test_new_refuses_a_slot_that_is_a_symlink_out_of_the_grain(self):
        # `_fill_header` followed it and rewrote a file the verb was never
        # pointed at. A write verb stays inside the grain it was asked to fill.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            outside = root / 'outside.md'
            model.write_raw(outside, 'OUTSIDE\n')
            (mdir / 'decisions.md').symlink_to(outside)
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('is a SYMLINK', out)
            self.assertIn('nothing was written', out)
            self.assertEqual(model.read_raw(outside), 'OUTSIDE\n')
            self.assertFalse((mdir / 'handoff.md').exists())

    def test_a_symlinked_slot_is_named_a_LINK_even_when_it_points_at_a_dir(self):
        # `dir_entries` classifies with `is_dir()`, which FOLLOWS the link, so a
        # link to a directory got the DIRECTORY refusal: refused correctly, and
        # then told to move aside a directory that is not in the grain at all.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            outside = root / 'outside'
            outside.mkdir()
            (mdir / 'decisions.md').symlink_to(outside)
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('is a SYMLINK', out)
            self.assertNotIn('is a DIRECTORY', out)

    def test_new_never_stacks_a_second_header_on_a_doc_that_has_one(self):
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            model.write_raw(mdir / 'decisions.md',
                            f'{model.SLOT_HEADER["decisions.md"]}\n\n# log\n')
            before = (mdir / 'decisions.md').read_text(encoding='utf-8')
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            self.assertEqual((mdir / 'decisions.md').read_text(encoding='utf-8'),
                             before)

    def test_new_needs_a_name_only_when_the_grain_does_not_exist(self):
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'new', 'milestone', '0.2')
            self.assertEqual(code, 2, out)
            self.assertIn('needs a name', out)

    def test_new_mints_no_shared_doc_and_repairs_the_header_of_one_present(self):
        # BOTH halves. `pm new` stopped CREATING a shared doc — that scaffolded
        # 204 empty files into one consumer's tree — and still MANAGES one that
        # exists, which is what a migration needs.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            for slot in model.MILESTONE_OPTIONAL_SLOTS:
                self.assertFalse((mdir / slot).exists(), slot)
            for slot, want in model.SLOT_HEADER.items():
                (mdir / slot).write_text('# headerless\n', encoding='utf-8')
                self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
                self.assertEqual(model.header_of(mdir / slot), want, slot)
                self.assertIn('# headerless',
                              (mdir / slot).read_text(encoding='utf-8'))

    def test_a_name_the_filesystem_refuses_is_a_refusal_not_a_traceback(self):
        # The grain DIRECTORY was the last unguarded write: `gdir.mkdir` on a
        # name too long for the filesystem came out as an OSError traceback
        # under exit 1, and exit 1 is what a consumer's pre-push hook reads as
        # "drift found".
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'new', 'milestone', '0.2-' + 'a' * 300,
                                'Too Long')
            self.assertEqual(code, 1, out)
            self.assertNotIn('Traceback', out)
            self.assertIn('REFUSED', out)
            self.assertIn('could not be created', out)
            self.assertIn('nothing was written', out)

    def test_new_story_and_new_bug_refuse_a_name_the_filesystem_rejects(self):
        # Those two write straight rather than through the scaffolder, so
        # neither guard `new` grew ever covered them.
        with tree(story_statuses=('todo',)) as root:
            for argv in (('new', 'story', '0.1/alpha', 'a' * 300, 'S'),
                         ('new', 'bug', '0.1', 'a' * 300)):
                code, out = run_cli(root, *argv)
                self.assertEqual(code, 1, out)
                self.assertNotIn('Traceback', out)
                self.assertIn('nothing was written', out)

    def test_the_same_pm_new_refuses_on_every_supported_python(self):
        # `Path.exists()` raises OSError on an over-long name up to 3.13 and
        # answers False from 3.14 on, so the verb came out as a traceback or as
        # a refusal depending on which interpreter `uvx` picked.
        from godot_devkit.repo.pm import cli as pm_cli
        with tree(story_statuses=('todo',)) as root:
            self.assertFalse(pm_cli._exists(root / ('a' * 300)))

    def test_an_unwritable_roadmap_dir_is_a_refusal_not_a_traceback(self):
        # The same unguarded call from the other side, and the claim is
        # honest here: nothing has been written when the mkdir fails.
        with tree(story_statuses=('todo',)) as root:
            rdir = root / 'pm/roadmap'
            rdir.chmod(0o555)
            try:
                code, out = run_cli(root, 'new', 'milestone', '0.2', 'Next')
                self.assertEqual(code, 1, out)
                self.assertNotIn('Traceback', out)
                self.assertIn('nothing was written', out)
                self.assertFalse((rdir / '0.2-next').exists())
            finally:
                rdir.chmod(0o755)
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.2', 'Next')[0], 0)


class NoDeleter(unittest.TestCase):
    """The tracker mostly REPORTS; the one verb that deletes NAMES its target.

    Reproduced on the default roster before `prune` was removed: an OPEN bug
    filed under a `done` milestone, `check pm` PASS, `pm prune`, and the bug
    file was gone. The rule that was supposed to make that impossible (an open
    bug under a done milestone) was opt-in and neither consumer enabled it, so
    nothing at all stood between the two commands. `prune` stays gone, and
    every one of these tests still holds for it.

    If archive sprawl needs an answer it is a READ verb — that is still true.
    `pm retire <milestone-id>` is the OPPOSITE shape from `prune`: one
    milestone, spelled out on the command line by the caller every time,
    never a sweep the tool decides the scope of on its own.
    `test_the_pm_cli_carries_no_recursive_delete` below is narrowed to
    let exactly that one command through — see it for why the shape still
    holds everywhere else.
    """

    def _commit(self, root: Path) -> None:
        for args in (['add', '-A'], ['-c', 'user.email=t@t', '-c', 'user.name=t',
                                     'commit', '-qm', 'x']):
            subprocess.run(['git', *args], cwd=root, check=True,
                           capture_output=True)

    def _two_closed_milestones_and_an_open_bug(self, root: Path) -> Path:
        write(root / 'pm/roadmap/0.2-later/milestone.md',
              {'id': '"0.2"', 'name': 'Later', 'status': 'done'})
        bug = root / 'pm/roadmap/0.1-demo/bugs/seed-is-zero.md'
        write(bug, {'id': '0.1/bugs/seed-is-zero', 'milestone': '"0.1"',
                    'status': 'open'})
        return bug

    def test_the_open_bug_under_the_cooled_milestone_survives(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            bug = self._two_closed_milestones_and_an_open_bug(root)
            self._commit(root)
            code, out = run_cli(root, 'prune')
            self.assertEqual(code, 2, out)
            self.assertIn('unknown command', out)
            self.assertTrue(bug.is_file(), 'the bug file was deleted')
            self.assertTrue((root / 'pm/roadmap/0.1-demo/milestone.md').is_file())

    def test_two_closed_milestones_are_a_fact_not_a_gate_failure(self):
        # The other half: the gate used to REDDEN until the destructive verb
        # was run, so a green build depended on a deletion whose scope the
        # person running it did not choose.
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            self._two_closed_milestones_and_an_open_bug(root)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_an_archive_directory_is_not_a_gate_failure_either(self):
        with tree(milestone_status='building') as root:
            (root / 'pm/roadmap/zz_archive').mkdir(parents=True)
            (root / 'pm/roadmap/zz_archive/note.md').write_text('x\n',
                                                               encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_the_pm_cli_carries_no_recursive_delete_OUTSIDE_cmd_retire(self):
        # The shape, not the instance: any function OTHER than the one that
        # is `pm retire`'s own implementation reaching for one of these is
        # `prune` wearing a different name. Narrowed to `cmd_retire`'s own
        # body — not dropped — so the guard still catches a delete that
        # turns up in `cmd_bug`, `cmd_move`, or anywhere else future work
        # adds a verb.
        source = Path(cli.__file__).read_text(encoding='utf-8')
        lines = source.split('\n')
        start = next(i for i, line in enumerate(lines)
                     if line.startswith('def cmd_retire('))
        end = next(i for i in range(start + 1, len(lines))
                   if lines[i].startswith('def '))
        retire_body = '\n'.join(lines[start:end])
        rest = '\n'.join(lines[:start] + lines[end:])
        for spelling in ('remove_tree', 'rmtree', "'rm'", 'unlink', 'delete_tree'):
            self.assertNotIn(spelling, rest,
                             f'{spelling} is back in the pm CLI outside '
                             f'cmd_retire')
        self.assertIn('delete_tree', retire_body,
                      "cmd_retire no longer deletes anything — this test's "
                      'own fixture has gone stale')

    def test_the_retired_rules_are_not_silently_accepted_names(self):
        # A retired id must not linger in KNOWN_CHECKS: a name that parses but
        # runs nothing is a gate a consumer believes is on.
        for retired in ('D7', 'D14'):
            self.assertNotIn(retired, model.KNOWN_CHECKS)


class NewRefusesUnsafeSlugs(unittest.TestCase):
    def test_a_slug_is_one_path_component_never_a_path(self):
        with tree() as root:
            before = sorted(p.name for p in root.iterdir())
            for bad in ('../../../pwned', 'a/b', '..', '-dash', 'glob*'):
                with self.subTest(bad=bad):
                    code, _ = run_cli(root, 'new', 'bug', '0.1', bad)
                    self.assertEqual(code, 1)
            self.assertEqual(sorted(p.name for p in root.iterdir()), before)

    def test_a_milestone_version_is_validated_too(self):
        with tree() as root:
            self.assertEqual(
                run_cli(root, 'new', 'milestone', '../../oops', 'Name')[0], 1)


class Templates(unittest.TestCase):
    def test_new_grains_come_from_templates_and_validate(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'b', 'B')[0], 0)
            ff = root / 'pm/roadmap/0.1-demo/features/b/feature.md'
            self.assertEqual(model.field_of(ff, 'id'), '0.1/b')
            self.assertEqual(model.field_of(ff, 'milestone'), '0.1')
            self.assertEqual(run_cli(root, 'validate')[0], 0)

    def test_a_new_milestone_gets_its_grain_file_under_the_exact_name(self):
        # EXACT names, from a listing: `is_file()` here passed on macOS against
        # the OLD uppercase spellings long after the rename landed, and would
        # have failed in CI on Linux. The slot names are the assertion.
        with tree() as root:
            run_cli(root, 'new', 'milestone', '0.2', 'Second')
            mdir = root / 'pm/roadmap/0.2-second'
            entries = model.dir_entries(mdir)
            for f in model.MILESTONE_FILE_SLOTS:
                self.assertEqual(entries.get(f), 'file', f)
            self.assertIn('# 0.2 — Second', (mdir / 'milestone.md').read_text())

    def test_templates_command_refuses_to_write_past_a_case_variant(self):
        # `is_file()` on macOS answers `decisions.md` with a leftover
        # `DECISIONS.md`, so the install skipped the very name `load` reads —
        # the project's customised template silently ignored, and no message
        # naming the spelling to port it to. Writing it anyway is worse still:
        # `open('decisions.md', 'w')` TRUNCATES the variant sitting there.
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            tdir = root / 'pm/templates'
            tdir.mkdir(parents=True)
            mine = 'MINE — a customised decisions template\n'
            model.write_raw(tdir / 'DECISIONS.md', mine)
            code, out = run_cli(root, 'templates')
            self.assertEqual(code, 0, out)
            self.assertIn('is a case variant of decisions.md', out)
            self.assertIn('git mv --force', out)
            self.assertEqual(model.read_raw(tdir / 'DECISIONS.md'), mine)
            self.assertNotIn('decisions.md', model.dir_entries(tdir))

            # Renamed, it is the template the log is MINTED from — the whole
            # point. Through a temp name: a direct rename is a no-op on macOS.
            (tdir / 'DECISIONS.md').rename(tdir / 'x.tmp')
            (tdir / 'x.tmp').rename(tdir / 'decisions.md')
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.3', 'Third')[0], 0)
            self.assertEqual(run_cli(root, 'decide', '0.3', 'a choice')[0], 0)
            self.assertIn('MINE', model.read_raw(
                root / 'pm/roadmap/0.3-third/decisions.md'))

    def test_a_project_template_overrides_the_packaged_one(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            tdir = root / 'pm/templates'
            tdir.mkdir(parents=True)
            (tdir / 'story.md').write_text(
                '---\nid: {id}\nfeature: {feature}\nmilestone: "{milestone}"\n'
                'name: {name}\nstatus: todo\nhouse_field: yes\n---\n\n# {name}\n',
                encoding='utf-8')
            run_cli(root, 'new', 'story', '0.1/alpha', 's', 'S')
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s.md'
            self.assertEqual(model.field_of(sf, 'house_field'), 'yes')

    def test_missing_grains_fall_back_to_the_packaged_template(self):
        # Overriding one grain must not make a project own all of them.
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            (root / 'pm/templates').mkdir(parents=True)
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'z', 'Z')[0], 0)

    def test_templates_command_copies_them_out_without_clobbering(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'templates')[0], 0)
            self.assertTrue((root / 'pm/templates/feature.md').is_file())
            (root / 'pm/templates/feature.md').write_text('mine\n', encoding='utf-8')
            run_cli(root, 'templates')
            self.assertEqual((root / 'pm/templates/feature.md').read_text(), 'mine\n')


class ATemplateMintsWhateverItSays(unittest.TestCase):
    def test_a_project_template_may_open_a_grain_at_any_state(self):
        # The guard here forbade a project's OWN template from minting a grain
        # past `planning` — the tool overruling a project about its own
        # scaffold. What the state has to be is in the vocabulary, and D4 reads
        # that off the tree.
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            run_cli(root, 'templates')
            t = root / 'pm/templates/feature.md'
            t.write_text(t.read_text().replace('status: planning', 'status: done'),
                         encoding='utf-8')
            code, out = run_cli(root, 'new', 'feature', '0.1', 'sneaky', 'S')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/sneaky/feature.md',
                               'status'), 'done')


class YourMilestoneDirectoryIsYours(unittest.TestCase):
    """D13 is gone, both halves, and `pm new` mints no directory.

    D13b — "extra slot" — FAILED your gate for keeping a file in your own
    milestone directory. `plans/`, `findings/`, `AUDIT-REPORT.md`: those are a
    project's own notes in a project's own tree, and a tracker with an opinion
    about them is a tracker deciding what you may write down.

    D13a — a grain dir with no grain file — was already reported twice over:
    `orphan_dirs` says it (always on, never gated by `[pm] checks`) because a
    dropped directory takes every descendant out of the scan, and V1 says a
    grain file with no `id:`/`status:` is malformed. This pins BOTH so the
    coverage cannot quietly leave with the rule.

    And `pm new` no longer mints `features/ bugs/ design/ stories/`. Git does
    not store an empty directory: across one consumer's tree that produced 158
    `design/` dirs, 11 of which hold anything.
    """

    def test_your_own_files_in_your_own_milestone_dir_are_not_findings(self):
        for name in ('plans', 'findings', 'AUDIT-REPORT.md',
                     'DELETED-SCENARIO-LEDGER.md', 'design'):
            with self.subTest(name=name), tree(story_statuses=('todo',)) as root:
                target = root / 'pm/roadmap/0.1-demo' / name
                if name.endswith('.md'):
                    target.write_text('# notes\n', encoding='utf-8')
                else:
                    target.mkdir()
                code, out = run_gate(root)
                self.assertEqual(code, 0, out)

    def test_a_shared_doc_that_lost_its_header_is_not_a_finding(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/decisions.md').write_text(
                '# log\n\n## D1 — 2026-01-01 — a thing\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_a_missing_grain_file_is_STILL_reported_by_two_other_rules(self):
        # The fold-in, proven. If this ever goes quiet, the D13a coverage left
        # with the rule and the census is lying about what it scanned.
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.2-scaffolded-by-hand').mkdir()
            (root / 'pm/roadmap/0.1-demo/features/beta').mkdir()
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('milestone dir with no milestone.md', out)
            self.assertIn('feature dir with no feature.md', out)
            self.assertIn('SKIPPED', out)

    def test_a_grain_file_with_no_id_or_status_is_STILL_V1(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/features/beta').mkdir()
            (root / 'pm/roadmap/0.1-demo/features/beta/feature.md').write_text(
                '---\nname: Beta\n---\n\nprose\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('missing id: or status:', out)

    def test_the_rule_and_its_config_name_are_both_gone(self):
        self.assertNotIn('D13', model.KNOWN_CHECKS)
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D13"]\n', encoding='utf-8')
            self.assertEqual(run_gate(root)[0], 2)

    def test_new_mints_no_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                self.assertEqual(run_cli(root, 'new', 'milestone', '0.1', 'M')[0], 0)
                mdir = root / 'pm/roadmap/0.1-m'
                self.assertEqual(sorted(p.name for p in mdir.iterdir()),
                                 ['milestone.md'])
                self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'f', 'F')[0], 0)
                fdir = mdir / 'features' / 'f'
                self.assertEqual(sorted(p.name for p in fdir.iterdir()),
                                 ['feature.md'])
                # ...and `stories/` appears when the first story goes into it.
                self.assertEqual(
                    run_cli(root, 'new', 'story', '0.1/f', 's0', 'S0')[0], 0)
                self.assertTrue((fdir / 'stories' / 's0.md').is_file())
            finally:
                os.chdir(previous)

    def test_the_help_line_matches_what_new_milestone_actually_mints(self):
        # The help said "No directory is minted" while the verb minted three and
        # printed one of them. A claim in shipped output is a claim under test.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, out = run_cli(root, '--help')
                self.assertEqual(code, 0, out)
                self.assertIn('in its own dir', out)
                self.assertIn('no sub-slot dirs', out)
                self.assertNotIn('No directory\n', out)
                self.assertEqual(run_cli(root, 'new', 'milestone', '0.9', 'N')[0], 0)
                mdir = root / 'pm/roadmap/0.9-n'
                # its OWN dir exists, and holds no sub-slot dir
                self.assertTrue(mdir.is_dir())
                self.assertEqual([p.name for p in mdir.iterdir() if p.is_dir()], [])
            finally:
                os.chdir(previous)
