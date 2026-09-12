"""install.py — `install-runners`: the Godot kit's one installer.

    install-runners  the sandboxed headless-run shell library, the runners
                     that source it, the compile sweep they boot (with the
                     `.uid` sidecar the engine would otherwise mint), the
                     engine-boot guard for Claude Code, and the uid-drift
                     workflow. Every function is `gdk_*` — the per-project
                     `<project>_*` forks this replaces are what drifted, so a
                     consumer keeping its own prefix is a second name for the
                     same fact and is not supported.

The gate FRAMEWORK — `check`, `precommit`, `milestone`, the capture helper,
`[gates] extra` — is agentic-sdlc's, and a consumer gets it from that pin
(`agentic-sdlc install-gates`). This verb writes what a Godot project adds on
top of that framework, and nothing that framework already owns.

The verb writes the file. Once. If the destination is already there and is not
byte-for-byte what would be written, the command REFUSES, names the path, and
names both remedies — move it aside, or `--force`. `--diff` shows what a run
would change and writes nothing. There is no manifest, no content hash, no
drift tracking, no merge and no ongoing sync: after the file is written it
belongs to the repo that asked for it, and the next install has to be told, by
an operator, that clobbering it is the intent.

Every refusal is decided for EVERY entry in the plan before the first byte is
written. A refusal raised mid-loop leaves a half-installed repo behind and
still says nothing was written; `nothing was written` has to be a claim about
the whole command, not about the entry the refusal happened to land on.

A COLLISION withholds ITS file, not the roster. An entry with no destination in
the way is written, every collision is named, and the run still exits 1,
because a replacement was withheld and a caller that reads only the exit code
must not be told everything landed. A DEFECT still refuses the whole command
(see `main`): it is not a decision the operator made about that file.

A difference confined to the `project config` block is REPORTED as one — the
rest of that file is byte-current, so there is nothing in it to take and the
run needs no `--force` at all. The installer does not MERGE the block: `--force`
replaces the whole file, header included. Preserving a consumer's header under
a new body would write a file whose header is one version and whose body is
another — `cc-godot-sandbox.sh`'s header gained `SANDBOX_FUNCTION` in 0.16.0
and `GDK_BOOT_FUNCTIONS` in 0.19.0, and grafting the 0.16.0 header onto the
current body was measured: four keys the body reads go unset, `set -u` kills
the hook before it decides anything, and it exits 1 — where only exit 2 is a
BLOCK. The raw engine boot goes through a guard that is on disk, looks
installed, and stops nothing.
"""
from __future__ import annotations

import difflib
import re
import sys
from importlib import resources
from pathlib import Path

from godot_devkit.core import apply
from godot_devkit.core.project import repo_root

PACKAGE = 'godot_devkit.godot.installables'
COMMAND = 'install-runners'

# (source name under installables/, destination relative to the repo root).
# The library first, then the runners that source it. The layout is what every
# runner's own defaults assume: a runner reaches the library at
# ../gdk_runners.sh and the repo root at ../../.. A repo that wants them
# elsewhere moves them all and sets GDK_RUNNERS_LIB — after the write the files
# are its own.
PLAN: tuple[tuple[str, str], ...] = (
    ('gdk_runners.sh', 'tools/dev/gdk_runners.sh'),
    ('import_cache.sh', 'tools/dev/runners/import_cache.sh'),
    ('parse.sh', 'tools/dev/runners/parse.sh'),
    # compile_sweep.gd travels WITH parse.sh, beside it: it is stage 2 of that
    # runner and has no other caller, and parse.sh addresses it as
    # res://tools/dev/runners/compile_sweep.gd (GDK_PARSE_SWEEP_SCRIPT). One
    # directory, so moving the runners moves the pair together and only one
    # variable has to follow.
    ('compile_sweep.gd', 'tools/dev/runners/compile_sweep.gd'),
    # …and its `.uid` SIDECAR, the only file in this package carrying a value
    # the ENGINE would otherwise mint. Without it, `check uid` CHECK 3
    # correctly reports a NEW `.gd` with no sidecar on every fresh project — a
    # red gate on a file the project did not write — and softening the check
    # to exempt "an installed .gd under tools/dev/" would put a hole in the one
    # gate that sees a missing sidecar. A uid is RANDOM, not derived, so this
    # one was minted once and is a constant like any other: an installable
    # declaring the identity of its own shipped script is stating a fact, not
    # the invention `check uid --fix` refuses. It is canonical under the ported
    # codec, so Godot will not rewrite it, and it is the same on every consumer
    # — which is what keeps the install idempotent and the gate quiet.
    ('compile_sweep.gd.uid', 'tools/dev/runners/compile_sweep.gd.uid'),
    ('lint.sh', 'tools/dev/runners/lint.sh'),
    ('warnings.sh', 'tools/dev/runners/warnings.sh'),
    ('unit.sh', 'tools/dev/runners/unit.sh'),
    # scenario.sh is the single-scenario entry point; integration.sh fans it
    # out and capture.sh is its headed twin. All three sit in one directory
    # because integration.sh reaches scenario.sh by GDK_SCENARIO_RUNNER,
    # relative to itself.
    ('scenario.sh', 'tools/dev/runners/scenario.sh'),
    ('integration.sh', 'tools/dev/runners/integration.sh'),
    ('capture.sh', 'tools/dev/runners/capture.sh'),
    # The gate ON the library rather than a gate that uses it: it proves a
    # run's HOME self-destructs and nothing persists beside the spool.
    ('hermetic_run_scan.sh', 'tools/dev/runners/hermetic_run_scan.sh'),
    # The Claude Code guard against a raw engine boot. It ships with the
    # runners because its STOCK roster is the library's own boot function:
    # the guard and the door it points at are one install.
    ('cc-godot-sandbox.sh', 'tools/hooks/cc-godot-sandbox.sh'),
    # `check uid` on a PR and a push to a milestone branch — the one workflow
    # that is Godot's. The rest of CI (the full gate, the semver gate, the tag)
    # is the agentic kit's `install-ci`.
    ('ci-uid-guard.yml', '.github/workflows/uid-guard.yml'),
    # The CALLERS, at the repo root: the Godot target roster, on the seam
    # agentic-sdlc's Makefile.devkit `-include`s, declaring which tiers
    # `precommit` and `milestone` run. It ships with the runners rather than
    # under a verb of its own because neither half is usable alone — the
    # runners are unreachable without targets pointing at them, and every
    # target here is dead without its runner. One verb, one working `make`.
    ('Makefile.tiers', 'Makefile.tiers'),
)

USAGE = """usage: godot-devkit install-runners [--force] [--diff]

Writes, under tools/dev/: gdk_runners.sh — the shell library your
Godot-booting make targets source (one verdict line per gate naming
.gate-reports/<gate>.log, VERBOSE=1 streams, a per-run self-destroying HOME
sandbox, a bounded-run contract, a project.godot restore) — and under
tools/dev/runners/ the runners that source it: import_cache.sh, parse.sh (+
its compile_sweep.gd and the .uid sidecar the engine would otherwise mint),
lint.sh, warnings.sh, unit.sh (GUT, sliced, with the coverage gate that fails
a test script GUT refused to load), scenario.sh, integration.sh (the same
scenarios, one process each, N in parallel), capture.sh (headed, because
headless is blind to render), and hermetic_run_scan.sh — the gate proving a
run's HOME self-destructs. Every one carries --help and --self-test. Plus
tools/hooks/cc-godot-sandbox.sh — the Claude Code guard against a raw engine
boot, whose stock roster is the library's own boot function (the run prints
the .claude/settings.json entry that fires it) — and
.github/workflows/uid-guard.yml (`check uid` on a PR and a push to milestone/**).
Plus Makefile.tiers at the repo root: the Godot targets that call the
runners (parse lint warnings unit integration scenario capture import-cache
hermetic-scan …), `godot-check` (`check all`, for `[gates] extra`), and the
GDK_PRECOMMIT_TIERS / GDK_MILESTONE_TIERS lists the include's compositions
run. It reads GODOT_DEVKIT_VERSION from your Makefile.

The gate framework (`check`, `precommit`, `milestone`, Makefile.devkit) is
agentic-sdlc's: pin that package and run its `install-gates`; its include
`-include`s Makefile.tiers.

A destination that already exists and differs is REFUSED — that file, not the
roster: the entries with nothing in their way are written, every collision is
named, and the run exits 1 because a replacement was withheld. A difference
confined to the `project config` header is reported as one, and the rest of
that file is byte-current, so it needs no --force. --force overwrites the whole
file, header included. --diff prints what would change and writes nothing."""

# A `.sh` installable is WRITTEN EXECUTABLE. Every one of them is a script a
# caller runs — a make recipe, a hook dispatcher, another runner's fan-out —
# and a script that is not executable is a file that looks installed and is
# not: `integration.sh` exec'd `scenario.sh` directly and got exit 126 from
# every scenario, under a FAILURES block that printed nothing, because
# `Permission denied` matched no summary pattern. The mode is part of the
# WRITE, in `core.apply`, which owns every mutation this package makes.
EXECUTABLE_SUFFIX = '.sh'

NEXT_STEP = (
    'set `GODOT_DEVKIT_VERSION := <tag>` in your Makefile above `include '
    'Makefile.devkit` (the include is agentic-sdlc\'s `install-gates`; it '
    '`-include`s Makefile.tiers, where the Godot targets live) and join the '
    'Godot checks to `make check` with `[gates] extra = ["godot-check"]` in '
    'devkit.toml — never a fork of the include. Then gitignore .gate-reports/, '
    '.scenario-reports/, .capture-reports/ and .headless-userdata/. Every '
    '`.sh` here is written EXECUTABLE, so a target may call it either way — '
    'the stock recipes say `bash tools/dev/runners/<x>.sh`, which also works '
    'on a checkout that lost the mode bits. Then edit each file\'s `project '
    'config` header: the files are yours now. Then paste the settings block '
    'below into .claude/settings.json — installing a Claude Code hook is not '
    'registering it, and an unregistered hook is a file nothing ever runs.')

# The `.claude/settings.json` entry that FIRES the engine-boot guard. PRINTED,
# not written: `.claude/settings.json` is a hand-maintained file with
# permissions, env and MCP entries this package knows nothing about, and this
# verb writes a whole file or refuses — there is no merge here and there is
# deliberately not going to be one. Synchronous on purpose: a PreToolUse block
# that arrived after the tool ran would be narration.
HOOK_SETTINGS = '''{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "bash tools/hooks/cc-godot-sandbox.sh"}
        ]
      }
    ]
  }
}'''

# The per-entry annotation for a collision confined to the editable block.
# Short, because it hangs off a path in a list; the sentence that says what it
# MEANS is printed once, below the list.
HEADER_ONLY_NOTE = '   (project-config header only)'


def _is_executable(target: Path) -> bool:
    """Whether `target` already carries an execute bit for anyone."""
    try:
        return bool(target.stat().st_mode & 0o111)
    except OSError:
        return False


def collision_refusal(collisions: list[str],
                      wrote: list[str] | None = None,
                      header_only: tuple[str, ...] | list[str] = (),
                      ) -> tuple[str, str]:
    """(what collided, what that means) — plural-correct.

    `wrote` is what the SAME run landed, and it changes the second sentence
    only: `nothing was written` is a claim about the disk, so it has to be
    checked rather than asserted. `header_only` names the subset whose
    difference is confined to the editable `project config` block. That is a
    different message, not a softer one: the rest of those files is
    byte-current, so the repair is to do NOTHING rather than to force and
    re-edit — and the sentence says out loud that `--force` would take the
    header too, because it would.
    """
    flagged = set(header_only)
    if len(collisions) == 1:
        rel = collisions[0]
        if rel in flagged:
            head = (f'{rel} exists and differs ONLY inside its project-config '
                    f'header — the rest of the file is byte-current, so there '
                    f'is nothing in it to take; leave it as yours, or pass '
                    f'--force to replace the whole file, header included')
        else:
            head = (f'{rel} exists and differs from what this would '
                    f'write — move your version aside, or pass --force')
    else:
        listed = '\n'.join(
            f'    {rel}' + (HEADER_ONLY_NOTE if rel in flagged else '')
            for rel in collisions)
        head = (f'{len(collisions)} destinations exist and differ from what '
                f'this would write — move your versions aside, or pass '
                f'--force:\n{listed}')
        if flagged:
            head += (f'\n{len(flagged)} of them differ only inside the '
                     f'project-config header the file invites you to edit: '
                     f'the rest of each is byte-current, so there is nothing '
                     f'in them to take, and --force would replace the header '
                     f'too')
    if wrote:
        landed = f'{len(wrote)} file(s) with nothing in the way'
        landed += ' was written' if len(wrote) == 1 else ' were written'
        held = 'it was' if len(collisions) == 1 else 'those above were'
        return head, (f'{landed}; {held} withheld and no existing file was '
                      f'overwritten. --diff shows what would change.')
    return head, ('nothing was written; every colliding destination is listed '
                  'above, not just the first. --diff shows what would change.')


# The wording this verb's refusals have always used, mapped from the closed
# `Obstruction` vocabulary `core.apply` decides in.
_DEFECT_TEXT = {
    apply.Obstruction.IS_A_DIRECTORY: 'is a directory',
    apply.Obstruction.NOT_A_REGULAR_FILE: 'is not a regular file',
    apply.Obstruction.NOT_WRITABLE: 'is not writable',
}
_PARENT_TEXT = {
    apply.Obstruction.PARENT_IS_A_FILE: 'is not a directory',
    apply.Obstruction.PARENT_NOT_WRITABLE: 'is not writable',
}


def destination_defect(target: Path) -> str:
    """'' when `target` can be written, else what stands in the way — decided
    WITHOUT writing a byte, by `core.apply`, in the same closed vocabulary
    every other writer in this package is decided in.

    SYMLINKS ARE FOLLOWED here, said out loud rather than left to a default: an
    install destination is an ordinary repo file, and a project that symlinks
    `tools/` somewhere deliberate is exercising a choice this tool has no
    business overriding.
    """
    blocked = apply.Plan().overwrite(
        target, '', symlink=apply.Symlink.FOLLOW).decide()
    if not blocked:
        return ''
    first = blocked[0]
    if first.reason in _DEFECT_TEXT:
        return _DEFECT_TEXT[first.reason]
    return f'cannot be created: {first.path} {_PARENT_TEXT[first.reason]}'


def read_destination(target: Path) -> tuple[str | None, str]:
    """(the file's text, or None when it is not ours to compare; a defect).

    A destination this cannot DECODE cannot be compared with an installable,
    which is text — so it is treated as a collision rather than as an error,
    and `--force` overwrites it the same way it overwrites any other differing
    file. An unreadable one (permissions, a race) is a defect: a collision
    check that silently skipped it would clobber whatever is there.
    """
    try:
        return target.read_text(encoding='utf-8'), ''
    except UnicodeDecodeError:
        return None, ''
    except OSError as err:
        return None, f'cannot be read ({err.strerror or err})'


# The editable `project config` block: a shell file opens it with a rule
# comment and closes with another. Both ends are markers the source ships and
# the consumer keeps — an edit that takes one out is an edit this cannot
# locate, and it says so by declining to classify rather than by guessing
# where the block ended.
_BLOCK_OPENING = '--- project config (yours to edit after install'
_BLOCK_CLOSING = re.compile(r'^#\s*-{5,}\s*$')


def config_block_span(text: str) -> tuple[int, int] | None:
    """The half-open LINE range of `text`'s editable project-config block, or
    None when it carries none this can locate.

    The first opening marker wins and the first closing marker after it ends
    the block; an opened block with no closing marker runs to the end of the
    file. The marker lines themselves are OUTSIDE the span — a consumer who
    edited one has changed something the installable owns, and that has to
    read as a plain difference. Locating LESS than is there is the safe
    direction: the one caller asks whether a difference is confined to the
    span, so a span that is too small can only answer "no".
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if _BLOCK_OPENING not in line:
            continue
        for end in range(start + 1, len(lines)):
            if _BLOCK_CLOSING.match(lines[end]):
                return start + 1, end
        return start + 1, len(lines)
    return None


def header_only_difference(existing: str, body: str) -> bool:
    """True when the two texts differ ONLY inside the project-config block.

    Decided by DELETING both blocks and comparing what is left, byte for byte,
    rather than by aligning the two files: an alignment is free to pair a line
    inside one block with an identical line outside the other, and a predicate
    whose True means "the rest of your file is byte-current" must not be able
    to reach that answer through a coincidence. False whenever either side
    carries no block this can locate.
    """
    mine = config_block_span(existing)
    theirs = config_block_span(body)
    if mine is None or theirs is None:
        return False
    return _outside_block(existing, mine) == _outside_block(body, theirs)


def _outside_block(text: str, span: tuple[int, int]) -> list[str]:
    # keepends, so a difference that is only a trailing newline is still a
    # difference: `splitlines()` renders 'x' and 'x\n' as the same one line.
    lines = text.splitlines(keepends=True)
    return lines[:span[0]] + lines[span[1]:]


def body_of(name: str) -> str:
    """One installable, verbatim. There is no substitution and no template."""
    return resources.files(PACKAGE).joinpath(name).read_text(encoding='utf-8')


def print_diff(rel: str, target: Path, body: str) -> None:
    """What an install WOULD change, as a unified diff. Writes nothing."""
    if not target.is_file():
        print(f'[install] {rel} does not exist — the whole file is an addition')
        existing = ''
    else:
        text, defect = read_destination(target)
        if text is None:
            print(f'[install] {rel} {defect or "is not text this can diff"} '
                  f'— --force would replace it whole')
            return
        if text == body:
            print(f'[install] {rel} already current')
            return
        if header_only_difference(text, body):
            # Said BEFORE the hunks, because it is the answer: the hunks below
            # are the operator's own header and the rest of the file is
            # byte-current, so this file has nothing in it to take.
            print(f'[install] {rel} differs ONLY inside its project-config '
                  f'header — the rest of the file is byte-current')
        existing = text
    sys.stdout.writelines(difflib.unified_diff(
        existing.splitlines(keepends=True), body.splitlines(keepends=True),
        fromfile=f'a/{rel}', tofile=f'b/{rel}'))


def _defect_refusal(defects: list[str], wrote: list[str]) -> str:
    listed = '\n'.join(f'    {d}' for d in defects)
    what = ('nothing was written' if not wrote else
            'ALREADY WRITTEN before this was reached: ' + ', '.join(wrote))
    return (f'godot-devkit {COMMAND}: {len(defects)} destination(s) cannot be '
            f'written:\n{listed}\n'
            f'godot-devkit {COMMAND}: {what}. Fix the path(s) and re-run — the '
            f'command is idempotent.')


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
            print(f'godot-devkit {COMMAND}: unknown flag {arg!r}',
                  file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2

    root = repo_root()
    entries = [(root / rel, rel, body_of(name)) for name, rel in PLAN]

    # --diff reads and prints. It is never combined with a write, so it is
    # answered before the plan is decided rather than inside it.
    if diff:
        for target, rel, body in entries:
            print_diff(rel, target, body)
        return 0

    # Decide the WHOLE plan first — resolve every destination, collect every
    # collision — and touch nothing until it holds.
    plan: list[tuple[str, Path, str, str]] = []   # (kind, target, rel, body)
    collisions: list[str] = []
    header_only: list[str] = []
    defects: list[str] = []
    for target, rel, body in entries:
        kind = 'write'
        defect = destination_defect(target)
        if defect:
            defects.append(f'{rel} {defect}')
            continue
        if target.is_file():
            existing, unreadable = read_destination(target)
            if unreadable:
                defects.append(f'{rel} {unreadable}')
                continue
            if existing == body and not (rel.endswith(EXECUTABLE_SUFFIX)
                                         and not _is_executable(target)):
                kind = 'current'
            elif existing == body:
                # Right bytes, missing execute bit. Not `current`: the file a
                # consumer installed before this package wrote the mode is
                # exactly the broken one, and reporting it current would leave
                # it broken forever. Rewritten (same bytes) so the ONE writer
                # sets the mode, and idempotent — the next run finds it right.
                pass
            elif not force:
                collisions.append(rel)
                # `existing` is None for a destination this cannot decode, and
                # a file with no text has no block to confine anything to.
                if existing is not None and header_only_difference(existing,
                                                                   body):
                    header_only.append(rel)
                continue
        plan.append((kind, target, rel, body))

    # A DEFECT refuses the whole command, the additions with it: it is a
    # destination the command cannot write at all, its repair is the same for
    # every entry (fix the path, re-run), and nothing has been written yet, so
    # `nothing was written` is still true at the moment it is printed.
    if defects:
        if collisions:
            head, tail = collision_refusal(collisions,
                                           header_only=header_only)
            print(f'godot-devkit {COMMAND}: {head}\n'
                  f'godot-devkit {COMMAND}: {tail}', file=sys.stderr)
        print(_defect_refusal(defects, []), file=sys.stderr)
        return 1

    # ONE plan, decided above and applied here. `core.apply` returns what
    # LANDED, so a refusal below names it instead of guessing.
    writes = apply.Plan()
    for kind, target, rel, body in plan:
        if kind != 'current':
            writes.overwrite(target, body, newline=None, label=rel,
                             executable=rel.endswith(EXECUTABLE_SUFFIX))
    result = writes.apply(decide=False)
    written = [step.label for step in result.landed]
    landed = set(written)
    # Reported in PLAN order, and STOPPING where the plan stopped: a line
    # printed past the failure would describe a file that was never reached.
    for kind, target, rel, body in plan:
        if kind == 'current':
            print(f'[install] {rel} already current')
        elif rel in landed:
            print(f'[install] wrote {rel}')
        else:
            break
    if result.failed is not None:
        print(_defect_refusal([f'{result.failed.label} could not be written '
                               f'({result.error})'], written),
              file=sys.stderr)
        return 1
    # After the writes, and named against what actually landed. Before the
    # next-step paragraph, so the pasteable settings block stays the last
    # thing on stdout.
    if collisions:
        head, tail = collision_refusal(collisions, wrote=written,
                                       header_only=header_only)
        print(f'godot-devkit {COMMAND}: {head}\n'
              f'godot-devkit {COMMAND}: {tail}', file=sys.stderr)
    if written:
        print(f'[install] {NEXT_STEP}')
        # Raw, unprefixed, so the block can be selected and pasted whole: a
        # JSON file is the one place a stray `[install] ` is not cosmetic.
        print(f'\n.claude/settings.json — the entry that FIRES the engine-boot '
              f'guard (merge into yours):\n\n{HOOK_SETTINGS}\n')
    # A withheld replacement is a non-zero exit even when additions landed.
    return 1 if collisions else 0
