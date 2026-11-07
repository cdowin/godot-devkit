"""`ui-fit`: the plan `[ui_fit]` resolves to, and the installed runner over the
fixture project — one passing and one failing scene per finding kind.

The plan is pure parse and proven in-process. The runner is proven the way
every runner is (installed into a scratch copy, never this repo's copy), and
its findings need a real engine: that case runs where `godot` (or GDK_GODOT)
is on PATH and is skipped elsewhere. The runner's census and usage paths exit
before any boot, so they run everywhere.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from support import REPO_ROOT, temp_repo

from godot_devkit.core.project import load_config, repo_root
from godot_devkit.godot import install
from godot_devkit.godot.read import ui_fit_plan

FIXTURE = 'ui_fit_project'
GODOT = shutil.which(os.environ.get('GDK_GODOT') or 'godot')
RUNNER = 'tools/dev/runners/ui_fit.sh'
SRC = REPO_ROOT / 'src'


def _plan(config: str | None = None) -> tuple[int, str, str]:
    root = Path.cwd()
    if config is not None:
        (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
    repo_root.cache_clear()
    load_config.cache_clear()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ui_fit_plan.main([])
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """The fixture project in a git repo with the runners installed, cwd'd into."""
    monkeypatch.setenv('GDK_ENGINE_GATE_HOME', str(tmp_path / 'lease-home'))
    with temp_repo(FIXTURE) as root:
        repo_root.cache_clear()
        load_config.cache_clear()
        with contextlib.redirect_stdout(io.StringIO()):
            install.main([])
        yield root
        repo_root.cache_clear()
        load_config.cache_clear()


def _runner(root: Path, plan: str | None = None) -> subprocess.CompletedProcess:
    """The runner as `make ui-fit` calls it (`-- <godot-devkit command>`, here
    the package from src/), or over a hand-written `plan`."""
    env = {k: v for k, v in os.environ.items() if k != 'VERBOSE'}
    env['GDK_UI_FIT_CAPTURE'] = '0'
    env['PYTHONPATH'] = str(SRC)
    args = ['--', sys.executable, '-m', 'godot_devkit.cli']
    if plan is not None:
        (root / 'plan.txt').write_text(plan, encoding='utf-8')
        args = ['plan.txt']
    return subprocess.run(['bash', RUNNER, *args], cwd=root, text=True,
                          capture_output=True, env=env)


def test_the_plan_takes_the_gallery_default_and_refuses_bad_config(project):
    code, out, _ = _plan()
    assert code == 0
    assert out.splitlines() == [
        'window 1280 720', 'window 3840 2160',
        'scene res://ui/gallery/cut_fail.tscn', 'scene res://ui/gallery/cut_pass.tscn',
        'scene res://ui/gallery/spills_fail.tscn', 'scene res://ui/gallery/spills_pass.tscn']
    (project / 'godot-devkit.toml').unlink()
    assert _plan()[1] == out                  # no config behaves as the defaults
    code, out, _ = _plan('[ui_fit]\nscenes = ["ui/gallery/cut_pass.tscn"]\n'
                         'smallest_window = [640, 360]\n'
                         'large_text_hook = "res://ui/text.gd:use_large_text"\n')
    assert code == 0 and out.splitlines() == [
        'window 640 360', 'window 3840 2160', 'large_text res://ui/text.gd use_large_text',
        'scene res://ui/gallery/cut_pass.tscn']
    code, _, err = _plan('[ui_fit]\nscenes = ["menus/"]\n')
    assert code == 1 and '[ui-fit] FAIL — 0 scenes' in err
    for bad in ('scenes = "ui/gallery/"', 'scenes = ["res://ui/"]', 'scenes = ["ui/gallery"]',
                'smallest_window = [0, 720]', 'largest_window = "4k"',
                'large_text_hook = "ui/text.gd"'):
        code, _, err = _plan(f'[ui_fit]\n{bad}\n')
        assert code == 2 and 'ui_fit' in err, bad


def test_the_runner_fails_an_empty_scope_and_refuses_a_missing_plan(project):
    done = _runner(project, 'window 1280 720\nwindow 3840 2160\n')
    assert done.returncode == 1 and '[UI-FIT] FAIL — the plan names 0 scenes' in done.stdout
    (project / 'godot-devkit.toml').write_text('[ui_fit]\nscenes = ["menus/"]\n', encoding='utf-8')
    done = _runner(project)
    assert done.returncode == 1 and '[ui-fit] FAIL — 0 scenes' in done.stderr
    done = subprocess.run(['bash', RUNNER, 'none.txt'], cwd=project, text=True,
                          capture_output=True)
    assert done.returncode == 2 and 'no plan at none.txt' in done.stderr


@pytest.mark.skipif(GODOT is None, reason='needs a Godot engine (godot or GDK_GODOT)')
def test_the_runner_reports_each_kind_on_its_failing_scene_only(project):
    done = _runner(project)
    findings = [line for line in done.stdout.splitlines() if line.startswith('  ')]
    assert done.returncode == 1, done.stdout + done.stderr
    assert [line.split(' — ')[0] for line in findings] == [
        '  cut  ui/gallery/cut_fail.tscn : Title',
        '  spills  ui/gallery/spills_fail.tscn : Bar'], done.stdout
    assert 'at 1280x720' in findings[1]       # the smallest window is what spills it
    assert '[UI-FIT] FAIL (2 finding(s) in 4 scene(s)' in done.stdout
    (project / 'godot-devkit.toml').write_text(
        '[ui_fit]\nscenes = ["ui/gallery/cut_pass.tscn", "ui/gallery/spills_pass.tscn"]\n',
        encoding='utf-8')
    done = _runner(project)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[UI-FIT] PASS (2 of 2 scene(s), 0 findings)' in done.stdout
