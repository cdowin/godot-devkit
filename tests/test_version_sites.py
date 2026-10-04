"""test_version_sites.py — the three places the version lives must agree.

release.yml checks the same thing, but only after the tag exists. v3.0.1 was
tagged with `__version__` still at 3.0.0 and never released. This test fails on
the PR instead.
"""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_lock_and_dunder_version_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = next(p["version"] for p in lock["package"] if p["name"] == "godot-devkit")
    init = (ROOT / "src" / "godot_devkit" / "__init__.py").read_text()
    dunder = re.search(r"""^__version__\s*=\s*['"]([^'"]+)['"]""", init, re.M).group(1)
    assert project == locked == dunder, (
        f"pyproject.toml {project}, uv.lock {locked}, __version__ {dunder}"
    )
