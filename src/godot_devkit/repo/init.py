"""init.py — `godot-devkit init`: a blank Godot 4 project, wired in one command.

Every piece this writes already existed as a verb. What did not exist was the
ORDER, and the two files nobody wrote: `devkit.toml` and the project's own
`Makefile`. Both consumers hand-rolled those two and then re-derived the order
by trial — the same fork this package already stopped them making, one layer up
from the files it stopped them forking.

So this composes, and re-implements nothing:

    devkit.toml       a template carrying every [section] the gates read,
                      every one commented out at its stock default
    pm init           the PM tree + the execution rule + the operations skill
    Makefile          two lines: the pin, and the include
    install-runners   Makefile.devkit + the shell library + the runners
    install-hooks     the guard corpus, then `bash tools/setup-hooks.sh` —
                      installing a hook is not ARMING it, and an unarmed hook
                      is a guard that is not there
    install-agents    the review/build contract + the base roster
    install-ci        the four workflows
    .gitignore        the four directories the runners write into
    CLAUDE.md         a skeleton naming the standard targets and the installed
                      rules, for the first agent to open the repo

TWO OWNERSHIPS, AND `--force` RESPECTS THE SPLIT. The installed files are
DEVKIT-owned: they are overwritten on `--force`, and the way to change one is
to change it here and re-install. `devkit.toml`, `Makefile`, `CLAUDE.md` and
the PM tree are PROJECT-owned from the first write: `--force` does not touch
them, ever. A template that overwrote a project's own config on a pin bump
would be this package reaching past the line it draws everywhere else.

That is also why a differing project-owned file is REPORTED rather than
refused: divergence is what those files are FOR. A differing devkit-owned file
is the install verb's own refusal, unchanged — named, with `--force` as the
remedy.

INIT IS A COMPOSITION, SO ITS ATOMICITY IS PER-VERB. Each verb it calls decides
its whole plan before writing a byte and either lands or refuses whole; init
runs them in order and reports each. It does NOT stop at the first refusal,
because a collision under `install-runners` says nothing about whether the
agents are installed — one run naming every refusal beats four re-runs that
each find the next one. The summary says which verbs refused and that `--force`
is the answer, and the exit code is 1 if any did.

TWO REFUSALS, BOTH DECIDED BEFORE THE FIRST BYTE. No `project.godot` at the
repo root: this writes a Godot project's scaffolding, and a directory that is
not one would get a Makefile whose every runner target has nothing to run. Not
a git repo: five of the gates resolve their scope through `git ls-files` (a
0-file census reddens each), and `setup-hooks.sh` has no git to point at the
hooks — so an init there would report success over a tree where nothing it
installed works.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from godot_devkit import __version__
from godot_devkit.core import apply
from godot_devkit.core.project import repo_root
from godot_devkit.repo import install

# The one substitution any seed carries: the tag the project pins. Spelled the
# same way `pm install-skills` spells its own, because it is the same fact.
VERSION_PLACEHOLDER = '{version}'

# (installable, destination) — the PROJECT-owned seeds, written once and never
# forced. Named individually because the ORDER they land in is interleaved with
# the install verbs, and collected in SEEDS so the file set stays ASKABLE.
SEED_CONFIG = ('project-devkit.toml', 'devkit.toml')
SEED_MAKEFILE = ('project-Makefile', 'Makefile')
SEED_CLAUDE = ('project-CLAUDE.md', 'CLAUDE.md')
SEEDS = (SEED_CONFIG, SEED_MAKEFILE, SEED_CLAUDE)

# What a Godot project is, and what a repo is. Both are refusals, not warnings.
PROJECT_FILE = 'project.godot'
GIT_DIR = '.git'

GITIGNORE = '.gitignore'
GITIGNORE_HEADER = '# godot-devkit run artifacts (godot-devkit init)'
# The four directories the installed runners write into, each named here as the
# runner's own default. A test pins every one of these against the `GDK_*`
# default in the runner that owns it, so the two cannot drift in silence — a
# shell default is not readable from Python, but it is greppable from a test.
IGNORED = (
    '.gate-reports/',       # GDK_GATE_REPORT_DIR      (gdk_runners.sh)
    '.headless-userdata/',  # GDK_SANDBOX_DIRNAME      (gdk_runners.sh)
    '.scenario-reports/',   # GDK_SCENARIO_REPORT_DIR  (scenario.sh)
    '.capture-reports/',    # GDK_CAPTURE_REPORT_DIR   (capture.sh)
)

SETUP_HOOKS = 'tools/setup-hooks.sh'

# The delegated install verbs, in the order a fresh project needs them. Named
# rather than derived from `install.PLANS`: the ORDER is init's contribution,
# and a dict's insertion order is not a contract.
VERBS = ('install-runners', 'install-hooks', 'install-agents', 'install-ci')

USAGE = """usage: godot-devkit init [--force] [--diff]

Stand a blank Godot 4 project up on this toolkit. Writes, in order:

  devkit.toml        every [section] the gates read, commented at its default
  pm/roadmap/        the PM tree, plus the execution rule and the operations
                     skill (`pm init`)
  Makefile           two lines — the DEVKIT_VERSION pin, and the include
  Makefile.devkit    the standard target set, plus tools/dev/gdk_runners.sh
  + tools/dev/       and the runners that source it   (`install-runners`)
  tools/hooks/       the guard corpus, then `bash tools/setup-hooks.sh` to arm
                     it                               (`install-hooks`)
  .claude/agents/    the review/build contract + the base roster
                                                      (`install-agents`)
  .github/workflows/ verify, uid-guard, semver-gate, auto-tag  (`install-ci`)
  .gitignore         the run-artifact directories, appended if absent
  CLAUDE.md          a skeleton naming the standard targets + installed rules

Run it again any time: it fills what is missing and reports the rest.
--diff  prints what a run would change, per file, and writes nothing.
--force overwrites the DEVKIT-owned files (the installables). devkit.toml,
        Makefile, CLAUDE.md and the PM tree are the project's from the first
        write, and --force does not touch them.

Refuses, before writing anything: a root with no project.godot (not a Godot
project), and a root that is not a git repository."""


def seed_body(name: str) -> str:
    """One seed's text, with the pin substituted. The only template in here."""
    return install.body_of(name).replace(VERSION_PLACEHOLDER, f'v{__version__}')


def _say(message: str) -> None:
    print(f'[init] {message}')


def _preflight(root: Path) -> str:
    """'' when this root can be initialized, else why it cannot."""
    if not (root / PROJECT_FILE).is_file():
        return (f'{root}/{PROJECT_FILE} does not exist — this writes a Godot '
                f'project\'s scaffolding (runners that boot the engine, gates '
                f'that read .tscn/.tres), and a directory that is not one gets '
                f'a Makefile with nothing behind it. Create the project in '
                f'Godot first, then re-run here.')
    if not (root / GIT_DIR).exists():
        return (f'{root} is not a git repository — every gate resolves its '
                f'scope through `git ls-files` (a 0-file census reddens each '
                f'of them), and {SETUP_HOOKS} has no git to point at the '
                f'installed hooks. Run `git init` first, then re-run here.')
    return ''


def _write_seed(root: Path, name: str, rel: str) -> int:
    """Write one project-owned seed, or say why it was left alone.

    A seed that exists and DIFFERS is not a collision: the project owns it and
    divergence is the point. It is reported, and `--diff` is what shows the
    drift. The only failure here is a destination that cannot be written at
    all, which is a defect naming the path.
    """
    target = root / rel
    body = seed_body(name)
    defect = install.destination_defect(target)
    if defect:
        print(f'godot-devkit init: {rel} {defect} — nothing was written to it',
              file=sys.stderr)
        return 1
    if target.is_file():
        existing, unreadable = install.read_destination(target)
        if unreadable:
            print(f'godot-devkit init: {rel} {unreadable}', file=sys.stderr)
            return 1
        if existing == body:
            _say(f'{rel} already current')
        else:
            _say(f'{rel} is yours — left alone (it differs from the template; '
                 f'`godot-devkit init --diff` shows how)')
        return 0
    result = apply.Plan().overwrite(target, body, newline=None,
                                    label=rel).apply(decide=False)
    if result.failed is not None:
        print(f'godot-devkit init: {rel} could not be written '
              f'({result.error})', file=sys.stderr)
        return 1
    _say(f'wrote {rel}')
    return 0


def _gitignore_missing(root: Path) -> list[str]:
    """The run-artifact entries `.gitignore` does not already carry."""
    target = root / GITIGNORE
    if not target.is_file():
        return list(IGNORED)
    text, _ = install.read_destination(target)
    if text is None:
        return list(IGNORED)
    present = {line.strip().lstrip('/').rstrip('/')
               for line in text.splitlines()}
    return [entry for entry in IGNORED if entry.rstrip('/') not in present]


def _write_gitignore(root: Path) -> int:
    """APPEND the missing run-artifact entries. Never rewrites, never removes.

    The one merge in this package, and it is a merge because both alternatives
    are worse: a `.gitignore` is a file every project already has opinions in,
    so refusing on a collision would refuse on every repo that has one, and
    overwriting would delete those opinions. Appending what is missing is the
    only act that is both idempotent and non-destructive.
    """
    missing = _gitignore_missing(root)
    if not missing:
        _say(f'{GITIGNORE} already ignores the run artifacts')
        return 0
    target = root / GITIGNORE
    defect = install.destination_defect(target)
    if defect:
        print(f'godot-devkit init: {GITIGNORE} {defect}', file=sys.stderr)
        return 1
    existing = ''
    if target.is_file():
        text, unreadable = install.read_destination(target)
        if unreadable:
            print(f'godot-devkit init: {GITIGNORE} {unreadable}',
                  file=sys.stderr)
            return 1
        existing = text or ''
        if existing and not existing.endswith('\n'):
            existing += '\n'
        existing += '\n'
    block = GITIGNORE_HEADER + '\n' + ''.join(f'{entry}\n' for entry in missing)
    result = apply.Plan().overwrite(target, existing + block, newline=None,
                                    label=GITIGNORE).apply(decide=False)
    if result.failed is not None:
        print(f'godot-devkit init: {GITIGNORE} could not be written '
              f'({result.error})', file=sys.stderr)
        return 1
    _say(f'{"appended to" if existing else "wrote"} {GITIGNORE}: '
         f'{" ".join(missing)}')
    return 0


def _arm_hooks(root: Path) -> int:
    """Run the installed `setup-hooks.sh`. Installing a hook is not arming it.

    `core.hooksPath` silently skips a non-executable hook, and this package
    makes no mode changes — the script that does both is the one the install
    just wrote, so init RUNS it rather than printing a paragraph asking the
    operator to. A failure is reported and does not stop the rest: the files
    are on disk either way, and the remedy is one named command.
    """
    script = root / SETUP_HOOKS
    if not script.is_file():
        _say(f'{SETUP_HOOKS} is not present — the hooks were NOT armed')
        return 1
    done = subprocess.run(['bash', str(script)], cwd=root,
                          capture_output=True, text=True)
    for line in done.stdout.splitlines():
        if line.strip():
            _say(line.strip())
    if done.returncode != 0:
        print(f'godot-devkit init: {SETUP_HOOKS} exited {done.returncode} — '
              f'the hooks are installed but NOT armed; run `bash '
              f'{SETUP_HOOKS}` yourself and read what it says\n'
              f'{done.stderr.strip()}', file=sys.stderr)
        return 1
    return 0


def _stand_up_pm_tree(cfg) -> int:
    """`pm init`, minus the four next-steps it prints for a bare repo.

    Two of those four are already done here — the `pm-scan` target ships in
    Makefile.devkit, and devkit.toml is written above with its `[pm]` block —
    so printing them would send an operator to wire what init just wired. The
    tree and the guidance install are the same two functions `pm init` calls.
    """
    from godot_devkit.repo.pm import skills
    for made in skills.stand_up_tree(cfg):
        _say(f'created {made}')
    return skills.cmd_install_skills(cfg, [])


def _pm_config():
    from godot_devkit.repo.pm import model
    return model.load()


def _diff(root: Path) -> int:
    """What a run WOULD change, per file, writing nothing.

    Same order as a real run, so the two reports read as one thing. The seeds
    go through the SAME diff printer the install verbs use — a second unified
    diff would be a second answer to one question.
    """
    from godot_devkit.repo.pm import skills
    install.print_diff(SEED_CONFIG[1], root / SEED_CONFIG[1],
                       seed_body(SEED_CONFIG[0]))
    skills.cmd_install_skills(_pm_config(), ['--diff'])
    install.print_diff(SEED_MAKEFILE[1], root / SEED_MAKEFILE[1],
                       seed_body(SEED_MAKEFILE[0]))
    for command in VERBS:
        install.main(command, ['--diff'], next_step=False)
    missing = _gitignore_missing(root)
    print(f'[install] {GITIGNORE} '
          + (f'is missing {" ".join(missing)}' if missing
             else 'already ignores the run artifacts'))
    install.print_diff(SEED_CLAUDE[1], root / SEED_CLAUDE[1],
                       seed_body(SEED_CLAUDE[0]))
    return 0


def main(argv: list[str]) -> int:
    force = False
    diff = False
    for arg in argv:
        if arg == '--force':
            force = True
        elif arg == '--diff':
            diff = True
        elif arg in ('-h', '--help', 'help'):
            print(USAGE)
            return 0
        else:
            print(f'godot-devkit init: unknown flag {arg!r}', file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2

    root = repo_root()
    blocked = _preflight(root)
    if blocked:
        print(f'godot-devkit init: {blocked}', file=sys.stderr)
        print('godot-devkit init: nothing was written.', file=sys.stderr)
        return 2

    # --diff reads and prints. Never combined with a write, so it is answered
    # before the first plan is decided — the same shape the install verbs use.
    if diff:
        return _diff(root)

    passthrough = ['--force'] if force else []
    refused: list[str] = []
    worst = 0

    worst = max(worst, _write_seed(root, *SEED_CONFIG))
    worst = max(worst, _stand_up_pm_tree(_pm_config()))
    worst = max(worst, _write_seed(root, *SEED_MAKEFILE))
    for command in VERBS:
        code = install.main(command, list(passthrough), next_step=False)
        if code != 0:
            refused.append(command)
        worst = max(worst, code)
        if command == 'install-hooks':
            worst = max(worst, _arm_hooks(root))
    worst = max(worst, _write_gitignore(root))
    worst = max(worst, _write_seed(root, *SEED_CLAUDE))

    print()
    if refused:
        _say(f'REFUSED by {", ".join(refused)} — each names the file(s) it '
             f'would not overwrite. Move yours aside, or re-run with --force '
             f'(which touches the installed files only, never devkit.toml, '
             f'Makefile, CLAUDE.md or the PM tree).')
        return worst
    if worst != 0:
        _say('finished with the problem(s) named above; everything else was '
             'written. The command is idempotent — fix those and re-run.')
        return worst
    _say(f'godot-devkit v{__version__} — this project is wired. Next:')
    print()
    print('  1. `make doctor` — the toolchain census; it names a fix for '
          'anything missing.')
    print('  2. `make help` — the standard target set, plus any of your own.')
    print('  3. Edit CLAUDE.md and devkit.toml. They are yours now: the '
          'skeleton says where')
    print('     your own facts go, and every gate roster and scope lives in '
          'devkit.toml.')
    print('  4. Every file under .claude/agents/ and tools/ opens with a '
          'project-config')
    print('     section carrying stock values — edit them to your spellings.')
    print('  5. .github/workflows/: uid-guard.yml names its branches '
          'literally (an `on:`')
    print('     filter takes no variable), and auto-tag.yml dispatches '
          'RELEASE_WORKFLOW —')
    print('     leave that alone if you have no release pipeline; the step is '
          'a no-op then.')
    print('  6. `godot-devkit pm new milestone 0.1 "First Milestone"`, then '
          '`make pm-scan`.')
    return 0
