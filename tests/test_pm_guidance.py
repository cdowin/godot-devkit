"""The files the pm family installs into a consumer — `pm init` seeding,
`pm install-skills`, and the shape those skills must keep.

Split from test_pm.py by concern; the shared harness is tests/support/pm.py.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.pm import run_cli, tree, write

from godot_devkit.repo.pm import cli, skills

class Guidance(unittest.TestCase):
    """`pm install-skills` / `pm init` — the shared doctrine, and only that."""

    def test_the_install_twins_share_their_refusal_helpers(self):
        # `cmd_install_skills` and `install.main` are deliberate sibling
        # COPIES of the decide/apply/report skeleton (they diverge on
        # ownership, refusal channel and wording — skills.py's docstring says
        # why a shared driver was rejected). What must never diverge is the
        # refusal DECISIONS, so this pins that the pm side reaches every one
        # of them through `repo/install.py` rather than re-rolling a copy.
        source = Path(skills.__file__).read_text(encoding='utf-8')
        for helper in ('install.collision_refusal',
                       'install.destination_defect',
                       'install.read_destination',
                       'install.print_diff'):
            self.assertIn(helper, source,
                          f'{helper} is no longer the single home')

    def test_install_writes_a_rule_and_a_skill(self):
        with tree() as root:
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 0, out)
            rule = root / '.claude/rules/pm-execution.md'
            skill = root / '.claude/skills/pm-operations/SKILL.md'
            self.assertTrue(rule.is_file())
            self.assertTrue(skill.is_file())
            # The rule must AUTO-LOAD: without a paths: header it only applies
            # when someone thinks to ask for it, which defeats the purpose.
            self.assertIn('paths:', rule.read_text().split('---')[1])

    def test_install_is_idempotent(self):
        with tree() as root:
            run_cli(root, 'install-skills')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 0)
            self.assertIn('already current', out)

    def test_diff_shows_what_an_install_would_change_and_writes_nothing(self):
        """The fourth install verb answers --diff off the SAME helper the
        install-* verbs use, so the four cannot print four kinds of diff."""
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# our own version\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills', '--diff')
            self.assertEqual(code, 0, out)
            self.assertIn('--- a/.claude/rules/pm-execution.md', out)
            self.assertIn('-# our own version', out)
            self.assertIn('.claude/skills/pm-operations/SKILL.md does not exist',
                          out)
            self.assertEqual(rule.read_text(), '# our own version\n')
            self.assertFalse(
                (root / '.claude/skills/pm-operations/SKILL.md').exists())

    def test_install_refuses_to_clobber_a_file_it_did_not_write(self):
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# our own version\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1)
            self.assertIn('differs from what this would write', out)
            self.assertEqual(rule.read_text(), '# our own version\n')

    def test_a_collision_on_the_SECOND_entry_installs_neither(self):
        """The rule installed, the skill refused, and the operator was told
        nothing was written about a repo that now held one of the two. Every
        collision in the plan is decided before the first write."""
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            skill = root / '.claude/skills/pm-operations/SKILL.md'
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text('# our own operations manual\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1, out)
            self.assertFalse(
                rule.exists(),
                'the FIRST entry was installed before the SECOND was refused')
            self.assertEqual(skill.read_text(), '# our own operations manual\n')
            self.assertNotIn('installed', out)

    def test_both_collisions_are_named_in_one_refusal(self):
        with tree() as root:
            for rel in ('.claude/rules/pm-execution.md',
                        '.claude/skills/pm-operations/SKILL.md'):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('# ours\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1)
            self.assertIn('pm-execution.md', out)
            self.assertIn('SKILL.md', out)

    def test_the_plural_refusal_reads_as_a_sentence(self):
        """It did not. With two collisions this printed

            "    .claude/rules/pm-execution.md
                 .claude/skills/pm-operations/SKILL.md exist and were not
                 generated by this tool"

        — the list where the subject goes, so the sentence trails off. The
        install verbs in repo/install.py formatted the same refusal correctly
        and this was a second copy; both now come from one formatter."""
        with tree() as root:
            for rel in ('.claude/rules/pm-execution.md',
                        '.claude/skills/pm-operations/SKILL.md'):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('# ours\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
        self.assertEqual(code, 1)
        self.assertIn('2 destinations exist and differ from what this', out)
        # The count opens the sentence; the paths are listed under it.
        head = out.partition('2 destinations')[2].partition('\n')[0]
        self.assertNotIn('.claude', head, out)

    def test_a_destination_that_cannot_be_written_refuses_before_any_write(self):
        """The all-or-nothing property covered collisions only: a destination
        that is a DIRECTORY tracebacked out of `write_text` with the first file
        already on disk."""
        with tree() as root:
            skill = root / '.claude/skills/pm-operations/SKILL.md'
            skill.mkdir(parents=True)
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1, out)
            self.assertIn('is a directory', out)
            self.assertIn('Nothing was written', out)
            self.assertFalse((root / '.claude/rules/pm-execution.md').exists(),
                             'the FIRST entry was written before the SECOND '
                             'was found unwritable')

    def test_force_overwrites_and_updates_a_stale_generated_file(self):
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# ours\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'install-skills', '--force')[0], 0)
            # A file we DID generate, merely stale, updates without --force.
            rule.write_text(rule.read_text().replace('godot-devkit v', 'godot-devkit v0.0.1 v'),
                            encoding='utf-8')
            self.assertEqual(run_cli(root, 'install-skills')[0], 0)

    def test_init_stands_up_a_usable_tree_from_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                self.assertEqual(run_cli(root, 'init')[0], 0)
                # The flow init tells the user to run must actually work.
                self.assertEqual(
                    run_cli(root, 'new', 'milestone', '0.1', 'First')[0], 0)
                self.assertEqual(
                    run_cli(root, 'new', 'feature', '0.1', 'gw', 'GW')[0], 0)
                self.assertEqual(run_cli(root, 'validate')[0], 0)
            finally:
                os.chdir(previous)
            self.assertTrue((root / 'pm/roadmap/ROADMAP.md').is_file())
            self.assertTrue((root / '.claude/rules/pm-execution.md').is_file())

    def test_init_is_non_destructive_on_an_existing_tree(self):
        # It fills gaps (a missing ROADMAP.md) but must never disturb grains
        # that are already there.
        with tree(story_statuses=('todo',)) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_bytes()
            index = root / 'pm/roadmap/ROADMAP.md'
            index.write_text('# Ours\n', encoding='utf-8')
            code, out = run_cli(root, 'init')
            self.assertEqual(code, 0, out)
            self.assertEqual(ff.read_bytes(), before)
            self.assertEqual(index.read_text(), '# Ours\n')  # not reseeded
            self.assertEqual(run_cli(root, 'validate')[0], 0)


class SkillShape(unittest.TestCase):
    """A flat `.claude/skills/<name>.md` does not load as a skill.

    The one mechanically-decidable FACT the retired `check agents` held: where
    the file sits decides whether its description ever fires, so an otherwise
    perfect skill written flat is inert. It lives in `check doc` now, beside
    the other "does this resolve" facts, and it INFERS nothing — it lists one
    directory.

    Its three neighbours in that gate did infer, and are gone: A1/A2 failed a
    build because a markdown file DESCRIBED a workflow, guessed the subject of
    a line by "exactly one grain word appears" (6 of 8 real mentions came back
    UNVERIFIED), and suppressed an identical finding because the line happened
    to contain the word "not".
    """

    def _doc(self, root: Path) -> tuple[int, str]:
        import importlib
        from godot_devkit.repo.checks import doc
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        # `doc` binds its root and scope at IMPORT, where production resolves
        # them once per process and the cwd never moves. Tests move it.
        importlib.reload(doc)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = doc.run()
        return code, buf.getvalue()

    def _write(self, root: Path, rel: str, body: str = '# s\n') -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')

    def test_a_flat_skill_file_is_a_finding(self):
        with tree() as root:
            self._write(root, 'CLAUDE.md', '# c\n')
            self._write(root, '.claude/skills/mine.md')
            code, out = self._doc(root)
            self.assertEqual(code, 1, out)
            self.assertIn('.claude/skills/mine.md', out)
            self.assertIn('does NOT load as a skill', out)

    def test_a_correctly_shaped_skill_and_its_supporting_files_pass(self):
        with tree() as root:
            self._write(root, 'CLAUDE.md', '# c\n')
            self._write(root, '.claude/skills/mine/SKILL.md')
            self._write(root, '.claude/skills/mine/references/api.md')
            code, out = self._doc(root)
            self.assertEqual(code, 0, out)

    def test_the_census_says_what_it_listed(self):
        # Rule 4: "no flat skills" out of an empty directory and out of twelve
        # correctly-shaped ones are different reports.
        with tree() as root:
            self._write(root, 'CLAUDE.md', '# c\n')
            self._write(root, '.claude/skills/one/SKILL.md')
            self._write(root, '.claude/skills/two/SKILL.md')
            code, out = self._doc(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 .claude/skills/ entr(ies)', out)


class TheAgentsGateIsGone(unittest.TestCase):
    """`check agents` gated ENGLISH PROSE, and it inferred. Both are removed.

    A1 failed a build for a `pm <grain> <verb>` spelling inside a backtick
    span; A2 for a `<state> -> <state>` a graph refused — in a file whose job
    is to DESCRIBE the workflow. A4 was a project-supplied regex over prose.
    None of them is a fact about the tree.
    """

    def test_it_is_not_a_gate_name(self):
        with tree() as root:
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                from godot_devkit import cli as top
                code = top.main(['check', 'agents'])
            self.assertEqual(code, 2, buf.getvalue())
            self.assertIn('unknown check', buf.getvalue())

    def test_a_definition_describing_a_workflow_reddens_nothing(self):
        # The exact text A2 failed on, and the near-identical line it let pass
        # because the word "not" appeared in it.
        with tree() as root:
            d = root / '.claude' / 'rules'
            d.mkdir(parents=True)
            (d / 'r.md').write_text(
                'The milestone lifecycle is planning -> ready -> done.\n'
                'When the story is verified, flip `status: review -> done`.\n'
                'A story does not go review -> done on its own.\n',
                encoding='utf-8')
            (root / 'CLAUDE.md').write_text('# c\n', encoding='utf-8')
            import importlib
            from godot_devkit.repo.checks import doc
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            importlib.reload(doc)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(doc.run(), 0, buf.getvalue())
        # And there is no other gate left to redden it: the module that held
        # A1/A2/A4 and the two inference helpers is gone, not narrowed.
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module('godot_devkit.repo.checks.agents')
