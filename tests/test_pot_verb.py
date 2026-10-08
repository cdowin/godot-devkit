"""`godot-devkit pot` end to end, in a throwaway repo: write, idempotence, config.

Apart from `test_pot.py` because the throwaway repo is a git spawn, and the
`shell` mark that follows from it is per module: the parsing proofs there stay
on every interpreter of the matrix.
"""
from __future__ import annotations

import contextlib
import io

from support import temp_repo

from godot_devkit import cli
from godot_devkit.godot.write import pot

FIXTURE = 'pot_repo'
POT_REL = 'locale/fixture.pot'


def _run(argv: list[str]) -> tuple[int, str]:
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    repo_root.cache_clear()
    load_config.cache_clear()
    return code, out.getvalue() + err.getvalue()


def test_the_verb_writes_once_then_is_a_no_op_and_needs_its_output_key() -> None:
    with temp_repo(FIXTURE) as root:
        target = root / POT_REL
        expected = target.read_bytes()
        target.unlink()
        code, out = _run(['pot', '--check'])
        assert code == pot.EXIT_DRIFT, out
        assert f'MISSING  {POT_REL} does not exist' in out
        code, out = _run(['pot'])
        assert code == pot.EXIT_OK, out
        assert f'pot  {POT_REL}  2 file(s) scanned, 40 msgid(s)  written' in out
        assert target.read_bytes() == expected
        code, out = _run(['pot'])
        assert (code, out.strip().endswith('(unchanged)')) == (pot.EXIT_OK, True), out
        assert target.read_bytes() == expected
        code, out = _run(['pot', '--check'])
        assert code == pot.EXIT_OK, out

        (root / 'godot-devkit.toml').write_text('[pot]\n', encoding='utf-8')
        code, out = _run(['pot'])
        assert code == pot.EXIT_REFUSED
        assert '[pot] output is not set' in out
        (root / 'godot-devkit.toml').write_text('[pot]\noutput = "res://x.pot"\n',
                                                 encoding='utf-8')
        code, out = _run(['pot', '--check'])
        assert code == pot.EXIT_REFUSED
        assert 'carries a scheme' in out
