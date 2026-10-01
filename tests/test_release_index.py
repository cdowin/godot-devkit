"""tools/release/build_index.py — the PEP 503 index the release workflow
publishes to GitHub Pages (#38).

What a consumer's `uv lock` trusts is two HTML files, so they are held to a
golden text: sorted and byte-stable whatever order the GitHub API lists the
assets in, the project directory PEP 503-normalised, every href carrying its
sha256 and the project's requires-python. And an asset list the index cannot
honestly publish — empty, a link with no verifiable hash, another project's
file — is refused with nothing written, never published
(rule 4: an installer recovers from a missing index, not from a lying one).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    'build_index', REPO_ROOT / 'tools' / 'release' / 'build_index.py')
build_index = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_index)

URL = 'https://github.com/cdowin/godot-devkit/releases/download'
A, B, C = 'a' * 64, 'b' * 64, '0123456789abcdef' * 4
# Deliberately NOT in filename order, the way the API hands them over.
ASSETS = [
    {'name': 'godot_devkit-1.4.0.tar.gz', 'url': f'{URL}/v1.4.0/godot_devkit-1.4.0.tar.gz', 'sha256': C},
    {'name': 'godot_devkit-1.4.0-py3-none-any.whl',
     'url': f'{URL}/v1.4.0/godot_devkit-1.4.0-py3-none-any.whl', 'sha256': B},
    {'name': 'godot_devkit-1.3.1-py3-none-any.whl',
     'url': f'{URL}/v1.3.1/godot_devkit-1.3.1-py3-none-any.whl', 'sha256': A},
]
HEAD = ('<!DOCTYPE html>\n<html>\n  <head>\n'
        '    <meta name="pypi:repository-version" content="1.0">\n'
        '    <title>{}</title>\n  </head>\n  <body>\n')
TAIL = '  </body>\n</html>\n'
ROOT_PAGE = HEAD.format('Simple index') + '    <a href="godot-devkit/">godot-devkit</a><br/>\n' + TAIL
# This checkout's pyproject.toml `requires-python`, HTML-escaped.
FLOOR = ' data-requires-python="&gt;=3.11"'


def project_page(old: str = '', new: str = '') -> str:
    """The project page, `old` on the 1.3.1 link and `new` on the 1.4.0 ones."""
    return (
        HEAD.format('Links for godot-devkit')
        + f'    <a href="{URL}/v1.3.1/godot_devkit-1.3.1-py3-none-any.whl#sha256={A}"{old}>'
          'godot_devkit-1.3.1-py3-none-any.whl</a><br/>\n'
        + f'    <a href="{URL}/v1.4.0/godot_devkit-1.4.0-py3-none-any.whl#sha256={B}"{new}>'
          'godot_devkit-1.4.0-py3-none-any.whl</a><br/>\n'
        + f'    <a href="{URL}/v1.4.0/godot_devkit-1.4.0.tar.gz#sha256={C}"{new}>'
          'godot_devkit-1.4.0.tar.gz</a><br/>\n'
        + TAIL)


# Run from this checkout, none of the listed releases is the tag being
# released, so no link carries this checkout's floor.
PROJECT_PAGE = project_page()


def _main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = build_index.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_the_index_is_byte_stable_normalised_and_every_link_is_hashed(tmp_path):
    listing = tmp_path / 'assets.json'
    listing.write_text(json.dumps(ASSETS), encoding='utf-8')
    code, out, err = _main(str(listing), str(tmp_path / 'site'))
    assert (code, err) == (0, ''), err
    assert '[index] 3 file(s) for godot-devkit' in out, out
    written = {p.relative_to(tmp_path / 'site').as_posix(): p.read_bytes()
               for p in (tmp_path / 'site').rglob('*') if p.is_file()}
    assert written == {'simple/index.html': ROOT_PAGE.encode(),
                       'simple/godot-devkit/index.html': PROJECT_PAGE.encode()}
    # Any listing order renders the same bytes, and a non-normalised project
    # name lands in the PEP 503 directory.
    assert build_index.render(list(reversed(ASSETS))) == build_index.render(ASSETS)
    assert set(build_index.render(ASSETS, project='Godot_Devkit')) == {
        'simple/index.html', 'simple/godot-devkit/index.html'}
    # The floor rides only the released tag's files; with no tag named, every link.
    by_tag = build_index.render(ASSETS, python='>=3.11', version='1.4.0')
    assert by_tag['simple/godot-devkit/index.html'] == project_page(new=FLOOR)
    untagged = build_index.render(ASSETS, python='>=3.11')
    assert untagged['simple/godot-devkit/index.html'] == project_page(FLOOR, FLOOR)


@pytest.mark.parametrize('assets, says', [
    ([], 'empty'),
    ([{**ASSETS[1], 'sha256': ''}], 'not 64 lowercase hex'),
    ([{**ASSETS[1], 'sha256': A.upper()}], 'not 64 lowercase hex'),
    ([{**ASSETS[1], 'name': 'notes.txt'}], 'neither a wheel nor an sdist'),
    ([ASSETS[1], ASSETS[1]], 'listed twice'),
    ([{**ASSETS[1], 'name': 'other_kit-1.4.0-py3-none-any.whl'}], 'not a godot-devkit file'),
    ([{**ASSETS[0], 'name': 'godot_devkit_extra-1.4.0.tar.gz'}], 'not a godot-devkit file'),
])
def test_a_list_it_cannot_publish_honestly_is_refused_and_writes_nothing(tmp_path, assets, says):
    listing = tmp_path / 'assets.json'
    listing.write_text(json.dumps(assets), encoding='utf-8')
    code, _, err = _main(str(listing), str(tmp_path / 'site'))
    assert code == 2 and says in err and 'nothing was written' in err, err
    assert not (tmp_path / 'site').exists()
