"""check shell — shellcheck over the repo's tooling shell scripts.

Lints every tracked *.sh under the configured roots, plus tracked
extension-less files there whose shebang is a shell, with `shellcheck -x`.
Soft-skips (exit 0, loud note) when shellcheck isn't installed — it's a
SHOULD-have dev dependency, not a hard one.

devkit.toml: [shell] roots = ["tools"]
"""
from __future__ import annotations

import shutil
import subprocess

from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.core.config import config_section, str_tuple

DEFAULT_ROOTS = ('tools',)
SHEBANGS = ('#!/usr/bin/env bash', '#!/bin/bash', '#!/usr/bin/env sh', '#!/bin/sh')


def run() -> int:
    if shutil.which('shellcheck') is None:
        print('[check:shell] SKIP — shellcheck not on PATH (install it to enable this gate)')
        return 0
    root = repo_root()
    roots = str_tuple(config_section('shell'), 'shell', 'roots', DEFAULT_ROOTS)
    targets = []
    for rel in git_lines('ls-files', *roots):
        path = root / rel
        if rel.endswith('.sh'):
            targets.append(rel)
            continue
        if '.' not in path.name:
            try:
                first = path.open(encoding='utf-8', errors='replace').readline().strip()
            except OSError:
                continue
            if first in SHEBANGS:
                targets.append(rel)
    if not targets:
        # Rule 4 — a gate that scanned nothing must say so. A misconfigured
        # exclude or a wrong root is indistinguishable from a clean tree,
        # and that PASS is the most dangerous output this package emits.
        print(f'[check:shell] FAIL — no shell scripts found under '
              f'{", ".join(roots)}/; check [shell] roots')
        return 1
    result = subprocess.run(['shellcheck', '-x', *targets], cwd=root)
    if result.returncode != 0:
        print(f'[check:shell] FAIL — findings across {len(targets)} script(s)')
        return 1
    print(f'[check:shell] PASS — {len(targets)} script(s) clean')
    return 0
