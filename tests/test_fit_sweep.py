"""`fit-sweep`: the plan `[fit_sweep]` and its size-class table resolve to, and
the installed runner over the fixture project — a scene that clips, one with
controls out of reach (covered, off screen at one size, under the touch
target), and one that passes.

The plan is pure parse and proven in-process. The runner is proven the way
every runner is (installed into a scratch copy, never this repo's copy), and
its findings need a real engine: that case runs where `godot` (or GDK_GODOT)
is on PATH and is skipped elsewhere; its PNGs need a display or Xvfb too. The
runner's census and usage paths exit before any boot, so they run everywhere.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from support import REPO_ROOT, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.core.project import load_config, repo_root
from godot_devkit.godot import install
from godot_devkit.godot.read import fit_sweep_plan

FIXTURE = 'fit_sweep_project'
GODOT = shutil.which(os.environ.get('GDK_GODOT') or 'godot')
DRAWS = bool(os.environ.get('DISPLAY')) or shutil.which('Xvfb') is not None
RUNNER = 'tools/dev/runners/fit_sweep.sh'
SRC = REPO_ROOT / 'src'
FIXTURE_TABLE = REPO_ROOT / 'tests' / 'fixtures' / FIXTURE / 'design' / 'layout.json'


def _plan(config: str | None = None) -> tuple[int, str, str]:
    root = Path.cwd()
    if config is not None:
        (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
    repo_root.cache_clear()
    load_config.cache_clear()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fit_sweep_plan.main([])
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


def _runner(root: Path, plan: str | None = None, **env_extra: str) -> subprocess.CompletedProcess:
    """The runner as `make fit-sweep` calls it (`-- <godot-devkit command>`,
    here the package from src/), or over a hand-written `plan`."""
    env = {k: v for k, v in os.environ.items() if k != 'VERBOSE'}
    env['PYTHONPATH'] = str(SRC)
    env.update(env_extra)
    args = ['--', sys.executable, '-m', 'godot_devkit.cli']
    if plan is not None:
        (root / 'plan.txt').write_text(plan, encoding='utf-8')
        args = ['plan.txt']
    return subprocess.run(['bash', RUNNER, *args], cwd=root, text=True,
                          capture_output=True, env=env)


def test_the_table_gives_every_size_once_and_a_touch_target_only_in_px():
    table = json.loads(FIXTURE_TABLE.read_text(encoding='utf-8'))
    assert fit_sweep_plan.table_sizes(table, 't') == ([
        'size 800 360 phone-worst', 'size 667 360 phone-floor', 'size 844 390 phone-also',
        'size 1280 720 desktop-worst'], 44)
    table['sizeClasses']['desktop']['also'] = [[800, 360]]          # already swept
    table['components']['button']['size']['min']['h'] = '{size.touch-target}'
    sizes, touch = fit_sweep_plan.table_sizes(table, 't')
    assert len(sizes) == 4 and touch is None
    for bad in ({'format': 2}, {'widthClasses': {}}, {'widthClasses': {'Wide': 0}},
                {'sizeClasses': {}}, {'sizeClasses': {'phone': {'worst': [800, 360]}}},
                {'sizeClasses': {'phone': {'worst': [800, 0], 'also': []}}},
                {'sizeClasses': {'phone': {'worst': [800, 360], 'floor': '667x360', 'also': []}}}):
        with pytest.raises(ConfigError):
            fit_sweep_plan.table_sizes({**table, **bad}, 't')


def test_the_plan_reads_the_config_and_refuses_bad_values(project):
    code, out, _ = _plan()
    assert code == 0, out
    assert out.splitlines()[-4:] == [
        'touch 44', 'scene res://ui/screens/clip_fail.tscn',
        'scene res://ui/screens/pass.tscn', 'scene res://ui/screens/reach_fail.tscn']
    code, out, _ = _plan('[fit_sweep]\ntable = "design/layout.json"\n'
                         'scenes = ["res://ui/screens/pass.tscn"]\n')
    assert code == 0 and out.splitlines()[-1] == 'scene res://ui/screens/pass.tscn'
    code, _, err = _plan('[fit_sweep]\ntable = "design/layout.json"\n'
                         'scenes = ["res://ui/screens/pass.tscn", "res://menus/**"]\n')
    assert code == 1 and "[fit-sweep] FAIL — scenes entry 'res://menus/**' matches 0" in err
    (project / 'godot-devkit.toml').unlink()
    code, _, err = _plan()
    assert code == 2 and 'table is not set' in err   # no config: nothing to sweep against
    for bad in ('table = "design/layout.json"',
                'table = "res://design/layout.json"\nscenes = ["res://ui/screens/**"]',
                'table = "design/none.json"\nscenes = ["res://ui/screens/**"]',
                'table = "project.godot"\nscenes = ["res://ui/screens/**"]',
                'table = "design/layout.json"\nscenes = "res://ui/screens/**"',
                'table = "design/layout.json"\nscenes = ["ui/screens/pass.tscn"]'):
        code, _, err = _plan(f'[fit_sweep]\n{bad}\n')
        assert code == 2 and 'fit_sweep' in err, bad


def test_the_runner_fails_an_empty_scope_and_refuses_what_it_cannot_run(project):
    done = _runner(project, 'size 800 360 phone-worst\n')
    assert done.returncode == 1 and '[FIT-SWEEP] FAIL — the plan names 0 scene(s)' in done.stdout
    done = subprocess.run(['bash', RUNNER, 'none.txt'], cwd=project, text=True,
                          capture_output=True)
    assert done.returncode == 2 and 'no plan at none.txt' in done.stderr
    plan = 'size 800 360 phone-worst\nscene res://ui/screens/pass.tscn\n'
    done = _runner(project, plan, GDK_FIT_SWEEP_PNG='0')
    assert done.returncode == 2 and 'no import cache' in done.stderr, done.stderr
    env = {k: v for k, v in os.environ.items() if k != 'DISPLAY'}
    env.update(PYTHONPATH=str(SRC), GDK_FIT_SWEEP_XVFB='no-such-xvfb')
    done = subprocess.run(['bash', RUNNER, 'plan.txt'], cwd=project, text=True,
                          capture_output=True, env=env)
    assert done.returncode == 2 and 'drawing needs a display' in done.stderr, done.stderr


@pytest.mark.skipif(GODOT is None or not DRAWS,
                    reason='needs a Godot engine (godot or GDK_GODOT) and a display or Xvfb')
def test_the_runner_names_each_planted_violation_and_passes_the_clean_scene(project):
    imported = subprocess.run(['bash', 'tools/dev/runners/import_cache.sh'], cwd=project,
                              text=True, capture_output=True)
    assert imported.returncode == 0, imported.stdout + imported.stderr
    done = _runner(project)
    assert done.returncode == 1, done.stdout + done.stderr
    found = sorted(line.strip().split(' — ')[0] for line in done.stdout.splitlines()
                   if line.startswith('  '))
    sizes = ('800x360 phone-worst', '667x360 phone-floor', '844x390 phone-also',
             '1280x720 desktop-worst')
    want = [f'{kind}  ui/screens/{scene} {size} : {node}'
            for kind, scene, node in (('clipped', 'clip_fail.tscn', 'Title'),
                                      ('clipped', 'clip_fail.tscn', 'Body'),
                                      ('unreachable', 'reach_fail.tscn', 'Covered'),
                                      ('small', 'reach_fail.tscn', 'Tiny'))
            for size in sizes]
    want.append('unreachable  ui/screens/reach_fail.tscn 667x360 phone-floor : Offscreen')
    assert found == sorted(want), done.stdout
    pngs = sorted(p.name for p in (project / '.gate-reports' / 'fit-sweep').iterdir())
    assert len(pngs) == 12 and 'ui__screens__pass__667x360.png' in pngs
    assert '[FIT-SWEEP] FAIL (17 finding(s) over 3 scene(s) x 4 size(s)' in done.stdout
    (project / 'godot-devkit.toml').write_text(
        '[fit_sweep]\ntable = "design/layout.json"\n'
        'scenes = ["res://ui/screens/pass.tscn"]\n', encoding='utf-8')
    done = _runner(project)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[FIT-SWEEP] PASS (1 of 1 scene(s) x 4 size(s), 0 findings' in done.stdout
    assert '4 PNG(s) in .gate-reports/fit-sweep/' in done.stdout
