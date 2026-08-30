"""tasks.py — `[tasks]` roles: devkit owns the SHAPE, the project the VOCABULARY.

An agent that has to be told how to verify a repo gets told differently every
time, and the paragraph doing the telling is pasted into every dispatch until
it IS the cost. One word replaces it: `godot-devkit task quick`.

What that word runs is entirely the project's. A rigid Makefile shipped into
three repos is a fork-by-copy that drifts — the exact failure this toolkit
exists to prevent — so a consumer declares which of ITS OWN targets fill each
role:

    [tasks]
    quick  = "make precommit"    # the per-change gate
    verify = "make milestone"    # the full gate, and what CI runs

Those two values are real, and no consumer had to rename anything to write
them. That is the evidence the role set is discovered rather than invented.

REQUIRED_ROLES is the contract; anything else in the table is the project's own
and runs the same way. `check tasks` is what makes the shape a guarantee rather
than a convention: a project that drops its `quick` target fails its own gate
the same day, instead of on the day an agent needed it.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys

from godot_devkit.core.config import ConfigError, config_section
from godot_devkit.core.project import repo_root

# The two roles every consumer must fill. `quick` is what a builder runs after
# a change; `verify` is what CI runs and what closes a milestone. A third
# would have to earn itself the way these did — by already existing, under the
# project's own name, in more than one repo.
REQUIRED_ROLES = ('quick', 'verify')

USAGE = """usage: godot-devkit task <role>
       godot-devkit task --list

Runs the command a repo declared for that role in devkit.toml:

    [tasks]
    quick  = "make precommit"
    verify = "make milestone"

Required roles: """ + ', '.join(REQUIRED_ROLES) + """. Others are the project's own.
`godot-devkit check tasks` asserts every declared role resolves to a real,
invocable target. Resolving a `make` role runs `make -n`, which PARSES your
Makefile — parse-time `$(shell …)` and `+`-prefixed recipe lines execute."""

# GNU make is the one program whose TARGETS the gate can check, rather than only
# checking that the program exists — `make -n` resolves a target name against the
# makefile and refuses an unknown one. What it does NOT promise is that nothing
# runs: see `_resolves` for exactly what `-n` still executes.
_MAKES = ('make', 'gmake', 'make.exe', 'gmake.exe')


def roles() -> dict[str, str]:
    """The `[tasks]` table, every value validated as a non-empty command.

    A non-string, or an empty one, is exit 2 rather than a finding: a role that
    resolves to nothing would run nothing and report success, which is the one
    outcome a verification shortcut may never produce.
    """
    sect = config_section('tasks')
    out: dict[str, str] = {}
    for name, value in sect.items():
        if not isinstance(value, str):
            raise ConfigError(
                f'[tasks] {name} must be a string command, got {value!r}')
        if not value.strip():
            raise ConfigError(
                f'[tasks] {name} is empty — remove the key rather than '
                f'declaring a role that runs nothing')
        out[name] = value
    return out


def _no_tasks_message() -> str:
    return ('no [tasks] table in devkit.toml. Declare which of THIS repo\'s '
            'targets fill each role:\n\n'
            '    [tasks]\n'
            '    quick  = "make precommit"\n'
            '    verify = "make milestone"\n')


def run_role(role: str) -> int:
    """Run one declared role, in the repo root, and propagate its exit code."""
    table = roles()
    if not table:
        print(f'godot-devkit task: {_no_tasks_message()}', file=sys.stderr)
        return 2
    command = table.get(role)
    if command is None:
        print(f'godot-devkit task: no role {role!r} in [tasks] '
              f'(declared: {", ".join(sorted(table)) or "none"})',
              file=sys.stderr)
        return 2
    root = repo_root()
    print(f'[task] {role}: {command}   (in {root})')
    # shell=True because the declared value is a COMMAND LINE a human wrote for
    # their own shell — `make precommit`, `npm run check && ./gradlew test`.
    # Splitting it here would silently drop the second half of any consumer who
    # wrote one, and a verification command that runs half of itself is worse
    # than one that fails.
    return subprocess.run(command, shell=True, cwd=root).returncode


def _list() -> int:
    table = roles()
    if not table:
        print(_no_tasks_message())
        return 2
    width = max(len(n) for n in table)
    for name in sorted(table, key=lambda n: (n not in REQUIRED_ROLES, n)):
        mark = '*' if name in REQUIRED_ROLES else ' '
        print(f'{mark} {name.ljust(width)}  {table[name]}')
    missing = [r for r in REQUIRED_ROLES if r not in table]
    if missing:
        print(f'\nMISSING required role(s): {", ".join(missing)}')
        return 1
    print(f'\n* = required. `godot-devkit task <role>` runs one.')
    return 0


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] in ('-h', '--help', 'help'):
            print(USAGE)
            return 0 if argv else 2
        if argv[0] == '--list':
            if argv[1:]:
                print(f'godot-devkit task: --list takes no arguments',
                      file=sys.stderr)
                return 2
            return _list()
        if len(argv) > 1:
            print(f'godot-devkit task: one role at a time '
                  f'(got {" ".join(argv)})', file=sys.stderr)
            return 2
        return run_role(argv[0])
    except ConfigError as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


# --- the gate ----------------------------------------------------------------
def _is_make(command: str) -> bool:
    """True when this role's program is a make. Shared by the gate's warning and
    by `_resolves`, so the run that says "this parses your Makefile" is exactly
    the run that does."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return bool(parts) and parts[0].rsplit('/', 1)[-1] in _MAKES


def _resolves(command: str) -> tuple[bool, str, str]:
    """(ok, how it was verified, why not).

    Two depths, and the census says which each role got. A `make` role is
    verified all the way to the TARGET — `make -n` resolves the target name
    against the makefile and refuses an unknown one. Anything else is verified
    only as far as its program being on PATH, and the census says so rather than
    implying the target was checked.

    RESOLVING A MAKE ROLE PARSES THAT REPO'S MAKEFILE, AND PARSING A MAKEFILE
    CAN RUN SHELL. This is inherent to make, not a property of how it is called
    here, and it was measured on GNU Make 3.81 (what macOS ships): under `-n`,
    a `$(shell …)` in a variable assignment runs at parse time, a `$(shell …)`
    inside an expanded recipe runs, and a recipe line prefixed with `+` runs.
    A repo whose Makefile does any of those has that much of it executed by
    `check tasks`, so the gate says so on every run rather than leaving it to
    be discovered. What each consumer's Makefile actually contains is that
    consumer's fact and is not asserted here.

    What `-n` DOES hold back is the recipe itself, including the sub-make: a
    recursive `$(MAKE)` line runs under `-n` and inherits `-n`, so it also only
    prints. The gate therefore cannot run the suite it is checking for the
    existence of — which is a narrower claim than "cannot execute anything".
    """
    try:
        parts = shlex.split(command)
    except ValueError as err:
        return False, '', f'is not a parsable command line ({err})'
    if not parts:
        return False, '', 'is empty'
    program = parts[0]
    if shutil.which(program) is None:
        return False, '', f'names program {program!r}, which is not on PATH'
    if not _is_make(command):
        return True, f'{program} is on PATH (target not verifiable)', ''
    targets = [a for a in parts[1:] if not a.startswith('-')]
    if not targets:
        return True, f'{program} is on PATH (no target named)', ''
    # `-n` prints recipes instead of running them, and exits non-zero on a
    # target the makefile does not define. It is not a sandbox: this parses the
    # consumer's makefile, and parse-time `$(shell …)` — plus `+`-prefixed
    # recipe lines — still run. The docstring above says exactly what was
    # measured and on which make.
    proc = subprocess.run([program, '-n', *targets], cwd=repo_root(),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        why = (proc.stderr or proc.stdout).strip().splitlines()
        return False, '', (f'names {program} target(s) '
                           f'{" ".join(targets)} that do not resolve: '
                           f'{why[-1] if why else "exit " + str(proc.returncode)}')
    return True, f'{program} target(s) {" ".join(targets)} resolve', ''


def run() -> int:
    """check tasks — every declared role resolves, and the required ones exist.

    The shape is only a guarantee if something asserts it. Without this, a
    project renames a target, `[tasks]` goes stale, and the failure surfaces
    the next time an agent runs `task quick` — inside a dispatch, as a
    confusing shell error, days later.
    """
    table = roles()
    findings: list[str] = []

    def report(msg: str) -> None:
        findings.append(msg)
        print(f'  UNRESOLVED  {msg}')

    print(f'[check:tasks] resolving {len(table)} declared role(s) against '
          f'devkit.toml [tasks]')
    # Said on every run that will do it, not buried in a docstring: resolving a
    # make role reads THIS repo's Makefile, and reading a Makefile is not free
    # of side effects. Printed only when a make role is declared — a gate that
    # warns about something it is not about to do is noise.
    if any(_is_make(command) for command in table.values()):
        print(f'[check:tasks] a make role resolves via `make -n`, which parses '
              f'this repo\'s Makefile — parse-time `$(shell …)` and '
              f'`+`-prefixed recipe lines run')
    if not table:
        # Rule 4: a gate that scanned nothing says so rather than printing
        # PASS. No [tasks] table is not a repo with tidy roles.
        print()
        # The message OPENS with the finding, so the phrase is not repeated
        # here — a gate that says the same sentence twice reads as two
        # findings, and the operator goes looking for the second one.
        print(f'[check:tasks] FAIL — {_no_tasks_message()}')
        return 1
    verified = []
    for name in sorted(table):
        ok, how, why = _resolves(table[name])
        if ok:
            verified.append(f'{name} ({how})')
        else:
            report(f'[tasks] {name} = {table[name]!r} {why}')
    for role in REQUIRED_ROLES:
        if role not in table:
            report(f'[tasks] has no {role!r} role — every repo declares '
                   f'{" and ".join(repr(r) for r in REQUIRED_ROLES)}, so one '
                   f'word reaches the same gate in all of them')
    print()
    for line in verified:
        print(f'  ok  {line}')
    census = (f'{len(table)} role(s), {len(verified)} resolved, '
              f'required: {", ".join(REQUIRED_ROLES)}')
    if findings:
        print(f'[check:tasks] FAIL — {len(findings)} role(s) do not resolve, '
              f'across {census}')
        return 1
    print(f'[check:tasks] PASS — every declared role is invocable; {census}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
