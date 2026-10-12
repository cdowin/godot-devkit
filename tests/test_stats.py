"""stats — every bucket's numbers against a hand-counted tree, and the census.

Each case builds its own tree in a temp dir and `git init`s it (untracked but
not ignored IS git-known, so no commit is needed), then runs `stats.main()`
in-process from inside it. The table is parsed back into numbers, so every
case asserts what a consumer reads, not an internal tally.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from godot_devkit.core.project import load_config, repo_root
from godot_devkit.godot.read import stats

TREE = {
    # game: 9 lines, 4 code — the docstring block and the `#` line are comment
    'main.gd': 'extends Node\n"""Docstring line one\nline two\n"""\n\n'
               '# a comment\nvar x = 1\nfunc _ready():\n\tpass\n',
    # game: 5 lines, 4 code — a `"""` string a CODE line opens is code, not a docstring
    'scenes/player.gd': '## doc comment\nclass_name Player\nvar s = """\nmulti\n"""\n',
    'tests/unit/test_a.gd': 'extends GutTest\nfunc test_one():\n\tassert_true(true)\n\n'
                            'func test_two():\n\tpass\n',
    'tests/integration/test_b.gd': 'extends GutTest\n# func test_commented():\n'
                                   'func test_three():\n\tpass\n',
    'tests/helper.gd': 'extends Node\n',
    'tools/build.gd': 'extends SceneTree\n\n# x\n',
    # vendored, tests and all: a path lands in one bucket and nowhere else
    'addons/gut/gut.gd': 'extends Node\nfunc test_not_counted():\n',
    'addons/gut/tests/test_c.gd': 'func test_x():\n\tpass\n',
    # 7 lines, 3 code — `//` lines and both `/* … */` blocks are comment
    'shaders/glow.gdshader': 'shader_type canvas_item;\n// comment\n/* block\n'
                             '   still block */\nuniform float a; /* trailing\n'
                             '   inside */\nvoid fragment() {}\n',
    'scenes/player.tscn': '[gd_scene format=3]\n\n[node name="P" type="Node"]\n',
    'data/item.tres': '[gd_resource type="Resource" format=3]\n[resource]\n',
    # never counted: gitignored, or not a counted suffix
    'ignored.gd': 'extends Node\n',
    '.gitignore': 'ignored.gd\n',
    'notes.txt': 'not code\n',
}

# label -> (files, lines, code, tests); '-' where the column does not apply.
EXPECTED = {
    'game .gd': ('2', '14', '8', '5', '1', '0', '3', '-'),
    'tests .gd': ('3', '11', '9', '1', '0', '0', '0', '3'),
    'tests/': ('1', '1', '1', '0', '0', '0', '0', '0'),
    'tests/integration/': ('1', '4', '3', '1', '0', '0', '0', '1'),
    'tests/unit/': ('1', '6', '5', '0', '0', '0', '0', '2'),
    'tools .gd': ('1', '3', '1', '1', '0', '0', '0', '-'),
    'vendored .gd': ('2', '4', '4', '0', '0', '0', '0', '-'),
    '.gdshader': ('1', '7', '3', '-', '-', '-', '-', '-'),
    '.tscn': ('1', '3', '-', '-', '-', '-', '-', '-'),
    '.tres': ('1', '2', '-', '-', '-', '-', '-', '-'),
}
BY_DIR = {'./': ('1', '9', '4', '4', '0', '0', '3', '-'), 'scenes/': ('1', '5', '4', '1', '1', '0', '0', '-')}
CENSUS = '# 11 file(s) scanned — dirs: ./'


@contextlib.contextmanager
def tree(files: dict[str, str], toml: str | None = None):
    """A git repo holding `files` (and `godot-devkit.toml` when given), cwd'd into."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, body in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding='utf-8')
        if toml is not None:
            (root / 'godot-devkit.toml').write_text(toml, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(previous)


def run(files=TREE, *argv: str, toml: str | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with tree(files, toml):
        for cache in (repo_root, load_config):
            cache.cache_clear()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = stats.main(list(argv))
        finally:
            for cache in (repo_root, load_config):
                cache.cache_clear()
    return code, out.getvalue(), err.getvalue()


def table(out: str) -> dict[str, tuple[str, ...]]:
    """The rendered rows, keyed by label — columns are 2+ spaces apart."""
    rows = {}
    for line in out.splitlines()[1:]:
        if line.startswith('#'):
            continue
        label, *cells = re.split(r'\s{2,}', line.strip())
        rows[label] = tuple(cells)
    return rows


class Buckets(unittest.TestCase):
    def test_each_row_equals_the_hand_counted_tree(self) -> None:
        code, out, err = run()
        self.assertEqual(code, 0, err)
        self.assertEqual(table(out), EXPECTED)
        self.assertEqual(out.splitlines()[0].split(),
                         ['bucket', 'files', 'lines', 'code', 'comments', 'docs', 'inline', 'docstrings', 'tests'])
        self.assertEqual(out.splitlines()[-1], CENSUS)

    def test_by_dir_splits_the_game_bucket_by_top_level_dir(self) -> None:
        code, out, err = run(TREE, '--by', 'dir')
        self.assertEqual(code, 0, err)
        self.assertEqual(table(out), {**EXPECTED, **BY_DIR})

    def test_json_carries_the_same_numbers_as_the_table(self) -> None:
        _, out, _ = run(TREE, '--by', 'dir')
        _, text, _ = run(TREE, '--by', 'dir', '--json')
        doc = json.loads(text)

        def cells(entry):
            return tuple('-' if entry.get(k) is None else str(entry[k])
                         for k in ('files', 'lines', 'code', 'comments', 'docs', 'inline', 'docstrings', 'tests'))
        flat = {}
        for bucket in doc['buckets']:
            flat[bucket['bucket']] = cells(bucket)
            for child in bucket.get('tiers', []) + bucket.get('dirs', []):
                flat[child['bucket']] = cells(child)
        self.assertEqual(flat, table(out))
        self.assertEqual(doc['files'], 11)
        self.assertEqual('# ' + doc['census'], CENSUS)


class Scope(unittest.TestCase):
    def test_no_config_equals_declaring_the_defaults(self) -> None:
        declared = '[stats]\ntests = ["tests/"]\ntools = ["tools/"]\nvendored = ["addons/"]\n'
        self.assertEqual(run(TREE, toml=declared), run(TREE))
        # A prefix names a directory with or without its slash: `tests` never
        # takes in `testsuite/`.
        beside = {**TREE, 'testsuite/x.gd': 'extends Node\n'}
        slashless = '[stats]\ntests = ["tests"]\ntools = ["tools"]\nvendored = ["addons"]\n'
        self.assertEqual(run(beside, toml=slashless), run(beside))

    def test_listing_only_the_vendored_addons_makes_the_rest_game(self) -> None:
        _, out, _ = run(TREE, toml='[stats]\nvendored = ["addons/other/"]\n')
        rows = table(out)
        self.assertEqual(rows['game .gd'], ('4', '18', '12', '5', '1', '0', '3', '-'))
        self.assertEqual(rows['vendored .gd'], ('0', '0', '0', '0', '0', '0', '0', '-'))

    def test_a_dir_argument_narrows_the_scan_and_the_census_says_so(self) -> None:
        code, out, _ = run(TREE, 'scenes')
        self.assertEqual(code, 0)
        self.assertEqual(table(out)['game .gd'], ('1', '5', '4', '1', '1', '0', '0', '-'))
        self.assertEqual(out.splitlines()[-1],
                         '# 2 file(s) scanned, 9 path(s) excluded from scope — dirs: scenes/')

    def test_an_empty_scan_exits_1_and_a_bare_string_exits_2(self) -> None:
        code, out, _ = run({'notes.txt': 'not code\n'})
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], '# 0 file(s) scanned — dirs: ./')
        code, out, err = run(TREE, toml='[stats]\ntests = "tests/"\n')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('[stats] tests must be a list of strings', err)


if __name__ == '__main__':
    unittest.main()

class CommentRatchet(unittest.TestCase):
    def test_lexer_counts_real_comments_not_hashes_or_quotes_in_strings(self):
        source = ('## API\nvar text = "# not a comment, \\\"quote\\\"" # real\n'
                  'var block = """\n# string content\nfunc test_fake():\n"""\n'
                  '# invariant\nfunc test_real():\n\tpass\n')
        self.assertEqual(stats.gd_line_counts(source), (9, 7, 1, 2, 1, 1, 0))

    def test_ratchet_rejects_growth_evasion_scope_changes_and_cap_increases(self):
        with tree({'main.gd': 'extends Node\n# keep\n',
                   'tests/unit/test_a.gd': 'extends GutTest\nfunc test_contract():\n\tpass\n'}) as root:
            for cache in (repo_root, load_config):
                cache.cache_clear()
            def invoke(*args):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = stats.main(list(args))
                return code, out.getvalue(), err.getvalue()
            code, output, _ = invoke('--json')
            self.assertEqual(code, 0)
            baseline = json.loads(output)
            path = root / 'stats.json'
            path.write_text(output)
            self.assertEqual(invoke('--ratchet', str(path))[0], 0)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.email=fixture@example.invalid', '-c', 'user.name=Fixture',
                            'commit', '-qm', 'freeze'], cwd=root, check=True)
            for source, finding in [
                ('extends Node\n# keep\n# grew\n', 'comments'),
                ('extends Node # moved prose\n', 'inline'),
                ('extends Node\n"""prose"""\n', 'docstrings'),
            ]:
                (root / 'main.gd').write_text(source)
                code, _, err = invoke('--ratchet', str(path))
                self.assertEqual(code, 1, err)
                self.assertIn(finding, err)
            (root / 'main.gd').write_text('extends Node\n# keep\n')
            (root / 'tests/unit/test_a.gd').write_text('extends GutTest\nfunc test_contract():\n\tpass\n\tpass\n')
            code, _, err = invoke('--ratchet', str(path))
            self.assertEqual(code, 1)
            self.assertIn('code', err)
            grown = json.loads(output)
            grown['buckets'][0]['comments'] += 1
            path.write_text(json.dumps(grown))
            code, _, err = invoke('--ratchet', str(path))
            self.assertEqual(code, 1)
            self.assertIn('cap increased', err)
            path.write_text(output)
            (root / 'godot-devkit.toml').write_text('[stats]\nvendored = ["main/"]\n')
            load_config.cache_clear()
            self.assertEqual(invoke('--ratchet', str(path))[0], 1)
            path.write_text('{"buckets": []}')
            self.assertEqual(invoke('--ratchet', str(path))[0], 2)
            for cache in (repo_root, load_config):
                cache.cache_clear()
