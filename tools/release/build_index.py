#!/usr/bin/env python3
"""build_index.py — the static PEP 503 index this repo's GitHub Pages serves.

    python3 tools/release/build_index.py <assets.json> <out-dir>

`<assets.json>` is a JSON list, one object per release asset:

    [{"name": "godot_devkit-1.4.0-py3-none-any.whl",
      "url":  "https://github.com/…/releases/download/v1.4.0/godot_devkit-1.4.0-py3-none-any.whl",
      "sha256": "<64 hex>"}, …]

and the two files written are `<out-dir>/simple/index.html` and
`<out-dir>/simple/<normalised project>/index.html`, every link carrying
`#sha256=<hex>` and `data-requires-python` from this checkout's
pyproject.toml — the tag being released, so an older release is listed under
the CURRENT floor (installers re-read each wheel's own metadata anyway). The
whole index is regenerated from ALL releases on every run
(.github/workflows/release.yml), so the output is a pure function of the list:
sorted, byte-stable, and a run that lost a release is repaired by the next.

Refuses (exit 2, nothing written) rather than publish a link an installer
cannot verify: an empty list, an asset with no 64-hex sha256, a file that is
neither a wheel nor an sdist, a file that is not this project's, a duplicate
name. Not part of the package and
never installed; stdlib only.
"""
from __future__ import annotations

import html
import json
import re
import sys
import tomllib
from pathlib import Path

PROJECT = 'godot-devkit'
SUFFIXES = ('.whl', '.tar.gz')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
USAGE = 'usage: build_index.py <assets.json> <out-dir>'
PYPROJECT = Path(__file__).resolve().parents[2] / 'pyproject.toml'


class Refused(ValueError):
    """An asset list this refuses to publish."""


def normalise(name: str) -> str:
    """PEP 503: runs of `-`, `_`, `.` collapse to one `-`, lowercased."""
    return re.sub(r'[-_.]+', '-', name).lower()


def distribution(filename: str) -> str:
    """The distribution a wheel or sdist filename names, PEP 503-normalised.

    A wheel's and a modern sdist's name field escapes `-` to `_`, so the name
    is everything before the first `-` of a wheel, before the last of an sdist.
    """
    if filename.endswith('.whl'):
        return normalise(filename.split('-', 1)[0])
    return normalise(filename[:-len('.tar.gz')].rsplit('-', 1)[0])


def requires_python(pyproject: Path = PYPROJECT) -> str | None:
    """`[project] requires-python` from `pyproject`, or None when undeclared."""
    with pyproject.open('rb') as handle:
        value = tomllib.load(handle).get('project', {}).get('requires-python')
    return value if isinstance(value, str) and value.strip() else None


def _page(title: str, links: list[str]) -> str:
    body = ''.join(f'    {link}<br/>\n' for link in links)
    return ('<!DOCTYPE html>\n'
            '<html>\n'
            '  <head>\n'
            '    <meta name="pypi:repository-version" content="1.0">\n'
            f'    <title>{html.escape(title)}</title>\n'
            '  </head>\n'
            '  <body>\n'
            f'{body}'
            '  </body>\n'
            '</html>\n')


def render(assets: list[dict], project: str = PROJECT,
           python: str | None = None) -> dict[str, str]:
    """{relative path: text} for the two index files. Raises Refused.

    `python` is the `requires-python` specifier every link carries as
    `data-requires-python`; None omits the attribute.
    """
    if not isinstance(assets, list) or not assets:
        raise Refused('the asset list is empty — an index of nothing is '
                          'refused, not published')
    seen: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            raise Refused(f'an asset is not an object: {asset!r}')
        name, url, sha = (asset.get('name'), asset.get('url'),
                          asset.get('sha256'))
        if not isinstance(name, str) or not name.endswith(SUFFIXES):
            raise Refused(f'{name!r} is neither a wheel nor an sdist')
        if distribution(name) != normalise(project):
            raise Refused(f'{name} is not a {normalise(project)} file — an '
                          f'index lists only its own project')
        if not isinstance(url, str) or not url.startswith('https://'):
            raise Refused(f'{name}: url {url!r} is not https')
        if not isinstance(sha, str) or not SHA256.match(sha):
            raise Refused(f'{name}: sha256 {sha!r} is not 64 lowercase '
                              f'hex — a link an installer cannot verify is '
                              f'refused')
        if name in seen:
            raise Refused(f'{name} is listed twice')
        seen.add(name)
        rows.append((name, url, sha))
    rows.sort()
    norm = normalise(project)
    root = _page('Simple index',
                 [f'<a href="{norm}/">{html.escape(norm)}</a>'])
    floor = ('' if python is None else
             f' data-requires-python="{html.escape(python, quote=True)}"')
    links = [f'<a href="{html.escape(url, quote=True)}#sha256={sha}"{floor}>'
             f'{html.escape(name)}</a>' for name, url, sha in rows]
    return {'simple/index.html': root,
            f'simple/{norm}/index.html': _page(f'Links for {norm}', links)}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    source, out = Path(argv[0]), Path(argv[1])
    try:
        assets = json.loads(source.read_text(encoding='utf-8'))
        files = render(assets, PROJECT, requires_python())
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError,
            Refused) as err:
        print(f'build_index: {err} — nothing was written', file=sys.stderr)
        return 2
    for rel, text in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
    print(f'[index] {len(assets)} file(s) for {normalise(PROJECT)} -> '
          + ', '.join(str(out / rel) for rel in files))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
