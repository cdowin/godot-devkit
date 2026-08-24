"""support.py — shared test scaffolding.

The checks resolve their scope through `git ls-files` from the git toplevel of
the cwd, so exercising one means standing up a throwaway git repo. `temp_repo`
does exactly that, and `run_check` runs a gate inside it with the module-level
caches cleared (they are `lru_cache`d on purpose in production, where the cwd
never moves mid-run).
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / 'fixtures'
REPO_ROOT = TESTS.parent
CONSUMER_REPOS = (Path.home() / 'workspace' / 'nullbound', Path.home() / 'workspace' / 'trail')

sys.path.insert(0, str(REPO_ROOT / 'src'))


@contextlib.contextmanager
def temp_repo(fixture: str, only: list[str] | None = None):
    """A git repo populated from `tests/fixtures/<fixture>`, cwd'd into.

    `only` restricts which fixture files are copied, which is how one fixture
    tree yields both a clean census and a drifted one.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        source = FIXTURES / fixture
        if only is None:
            shutil.copytree(source, root)
        else:
            root.mkdir(parents=True)
            for rel in only:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / rel, target)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(previous)


def run_check(module) -> tuple[int, str]:
    """Run a check's `run()` in the current repo; returns (exit code, stdout)."""
    from godot_devkit.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = module.run()
    repo_root.cache_clear()
    load_config.cache_clear()
    return code, buffer.getvalue()


def available_consumers() -> list[Path]:
    return [p for p in CONSUMER_REPOS if p.is_dir()]
