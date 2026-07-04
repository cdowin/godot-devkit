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

from godot_devkit.project import git_lines, load_config, repo_root

DEFAULT_ROOTS = ('tools',)
SHEBANGS = ('#!/usr/bin/env bash', '#!/bin/bash', '#!/usr/bin/env sh', '#!/bin/sh')


def run() -> int:
    if shutil.which('shellcheck') is None:
        print('[check:shell] SKIP — shellcheck not on PATH (install it to enable this gate)')
        return 0
    root = repo_root()
    roots = tuple(load_config().get('shell', {}).get('roots', DEFAULT_ROOTS))
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
        print(f'[check:shell] PASS — no shell scripts found under {", ".join(roots)}/')
        return 0
    result = subprocess.run(['shellcheck', '-x', *targets], cwd=root)
    if result.returncode != 0:
        print(f'[check:shell] FAIL — findings across {len(targets)} script(s)')
        return 1
    print(f'[check:shell] PASS — {len(targets)} script(s) clean')
    return 0
