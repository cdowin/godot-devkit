"""install.py — write a file into a repo, once, from one source.

Three verbs, one relationship, and it is deliberately the whole relationship:

    install-ci      .github/workflows/verify.yml — ONE opinionated workflow.
                    Checkout, uv, `make milestone`. It carries no gate of its
                    own and no way to parameterize one: a project that wants
                    something else edits the file, which is now its file.
    install-agents  the review and build contract PLUS the base agent roster
                    (architect, po, developer, reviewers, simplifier, the
                    writers, pm-operator), as AGENT DEFINITIONS under
                    .claude/agents/. Deliberately not `.claude/rules/*`: it is
                    measured that a rules file never reaches a subagent's spawn
                    context while its definition does, so a contract written as
                    a rule is a contract that arrives nowhere. The roster is
                    generalized from the two consumers; per-file variation is a
                    marked `Project config` section the repo edits after
                    install, the same relationship the hook corpus has.
    install-hooks   the agent-workflow guard corpus: the Claude Code hooks
                    (commit-pathspec, engine-boot sandbox, stop gate, write
                    confinement), the git hooks (pre-push, prepare-commit-msg),
                    the worktree tool that writes the scope marker the guards
                    read, the toolchain doctor, and the script that arms them.
                    Forked between two repos (~1,000 lines duplicated per repo,
                    drifting on a project-name prefix and on which fixes each
                    fork got); canonical here. Every installed file is
                    STANDALONE — no sourcing of a library the repo may lack —
                    and per-project variation is a small config header the
                    repo edits after install, when the file is its own.

The verb writes the file. Once. If the destination is already there and is not
byte-for-byte what would be written, the command REFUSES, names the path, and
names both remedies — move it aside, or `--force`. `--diff` shows what a run
would change and writes nothing. There is no manifest, no content hash, no
drift tracking, no merge and no ongoing sync: after the file is written it
belongs to the repo that asked for it, and the next install has to be told, by
an operator, that clobbering it is the intent.

Every refusal is decided for EVERY entry in the plan before the first byte is
written — the same rule the PM scaffolder states as "every refusal the grain
can raise is decided before the first rename runs". A refusal raised mid-loop
leaves a half-installed repo behind and still says nothing was written;
`nothing was written` has to be a claim about the whole command, not about the
entry the refusal happened to land on.

The three refusal helpers below are shared with `pm install-skills`, the fourth
install verb this package ships. They live here rather than in a verb because
the wording is the contract: the collision sentence was written twice once, one
copy got the plural wrong, and the two refusals disagreed about the same
situation for a release.
"""
from __future__ import annotations

import difflib
import sys
from importlib import resources
from pathlib import Path

from godot_devkit.core import apply
from godot_devkit.core.project import repo_root

PACKAGE = 'godot_devkit.repo.installables'

# (source name under installables/, destination relative to the repo root).
PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    'install-ci': (
        ('ci-verify.yml', '.github/workflows/verify.yml'),
    ),
    'install-agents': (
        # The verification pair first — the contract predates the roster and
        # is the pair devkit itself self-hosts. Then the base roster: the
        # generalized consumer agents, each with model/effort frontmatter
        # (the tiering table in SDLC.md) and a project-config
        # section the consumer edits after install, hook-corpus style.
        ('verification-reviewer.md', '.claude/agents/verification-reviewer.md'),
        ('verification-builder.md', '.claude/agents/verification-builder.md'),
        ('architect.md', '.claude/agents/architect.md'),
        ('po.md', '.claude/agents/po.md'),
        ('developer.md', '.claude/agents/developer.md'),
        ('reviewer.md', '.claude/agents/reviewer.md'),
        ('milestone-reviewer.md', '.claude/agents/milestone-reviewer.md'),
        ('simplifier.md', '.claude/agents/simplifier.md'),
        ('test-writer.md', '.claude/agents/test-writer.md'),
        ('tech-writer.md', '.claude/agents/tech-writer.md'),
        ('changelog-writer.md', '.claude/agents/changelog-writer.md'),
        ('doc-hygiene.md', '.claude/agents/doc-hygiene.md'),
        ('pm-operator.md', '.claude/agents/pm-operator.md'),
    ),
    'install-hooks': (
        ('cc-commit-pathspec.sh', 'tools/hooks/cc-commit-pathspec.sh'),
        ('cc-godot-sandbox.sh', 'tools/hooks/cc-godot-sandbox.sh'),
        ('cc-stop-gate.sh', 'tools/hooks/cc-stop-gate.sh'),
        ('cc-write-confine.sh', 'tools/hooks/cc-write-confine.sh'),
        ('pre-push', 'tools/hooks/pre-push'),
        ('prepare-commit-msg', 'tools/hooks/prepare-commit-msg'),
        ('agent-worktree.sh', 'tools/dev/agent-worktree.sh'),
        ('doctor.sh', 'tools/dev/checks/doctor.sh'),
        ('setup-hooks.sh', 'tools/setup-hooks.sh'),
    ),
    'install-runners': (
        # The library first, then the one runner that sources it. The layout
        # is what import_cache.sh's own defaults assume: the runner reaches
        # the library at ../gdk_runners.sh and the repo root at ../../..
        # A repo that wants them elsewhere moves both and sets
        # GDK_RUNNERS_LIB — after the write the files are its own.
        ('gdk_runners.sh', 'tools/dev/gdk_runners.sh'),
        ('import_cache.sh', 'tools/dev/runners/import_cache.sh'),
    ),
}

USAGE = """usage: godot-devkit install-ci      [--force] [--diff]
       godot-devkit install-agents  [--force] [--diff]
       godot-devkit install-hooks   [--force] [--diff]

install-ci      .github/workflows/verify.yml — checkout, uv, `make milestone`.
                It ASSUMES that target is your full gate; a project without one
                edits the workflow, which after the write is its own file.
install-agents  the review/build contract plus the base agent roster, as
                AGENT DEFINITIONS under .claude/agents/ — the one place a
                subagent actually reads. Each roster file carries a
                `Project config` section — yours to edit after install.
install-hooks   the agent-workflow guard corpus, under tools/: the Claude Code
                hooks (cc-commit-pathspec, cc-godot-sandbox, cc-stop-gate,
                cc-write-confine), the git hooks (pre-push, prepare-commit-msg),
                tools/dev/agent-worktree.sh, tools/dev/checks/doctor.sh, and
                tools/setup-hooks.sh, which arms them. Each carries a small
                `project config` header — yours to edit after install.

A destination that already exists and differs is refused, whole.
--force overwrites it. --diff prints what would change and writes nothing."""

# Installing tools/hooks/* is not arming them: core.hooksPath silently skips a
# non-executable hook, and this package cannot chmod (core.apply owns every
# mutation and has no such act). The script that does it is in the same install.
_NEXT_STEP = {
    'install-hooks': 'run `bash tools/setup-hooks.sh` to point git at them and '
                     'set the exec bit — an unexecutable hook is skipped in '
                     'silence. Then review each file\'s `project config` '
                     'header (gate commands, protected branches, trailer): '
                     'the files are yours now, and the stock values assume '
                     'the standard consumer Makefile.',
    'install-agents': 'the verification pair carries the review and build '
                      'contract; the rest are the base roster. Each roster '
                      'file opens with a `Project config` section — edit its '
                      'stock values (gate commands, pm tree, doc layout) to '
                      'your spellings: the files are yours now. `model:` in '
                      'the frontmatter is doing proven work; `effort:` is '
                      'carried unverified. The SDLC these agents run is '
                      'SDLC.md at the godot-devkit repo root.',
    'install-ci': 'the job runs `make milestone` and nothing else. Confirm that '
                  'target exists and is your full gate.',
    'install-runners': 'nothing sources the library yet — point your '
                       'Godot-booting `make` targets at it '
                       '(`source tools/dev/gdk_runners.sh`), wire '
                       '`make import-cache` to tools/dev/runners/import_cache.sh, '
                       'and gitignore .gate-reports/ and .headless-userdata/. '
                       'Then edit each file\'s `project config` header: the '
                       'files are yours now.',
}


def collision_refusal(collisions: list[str]) -> tuple[str, str]:
    """(what collided, what that means) — plural-correct, for any install verb.

    Two sentences rather than one string because the callers frame them
    differently: this module prefixes each line with `godot-devkit <command>:`,
    while the pm CLI raises them as one `Refused`.
    """
    if len(collisions) == 1:
        head = (f'{collisions[0]} exists and differs from what this would '
                f'write — move your version aside, or pass --force')
    else:
        listed = '\n'.join(f'    {rel}' for rel in collisions)
        head = (f'{len(collisions)} destinations exist and differ from what '
                f'this would write — move your versions aside, or pass '
                f'--force:\n{listed}')
    return head, ('nothing was written; the whole install is refused, not just '
                  'the first colliding file. --diff shows what would change.')

# The wording this verb's refusals have always used, mapped from the closed
# `Obstruction` vocabulary `core.apply` decides in. A dict, not a sentence
# built at the call site: the check lives in one place and the phrasing lives
# in one place, and neither has to know the other's business.
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
    WITHOUT writing a byte.

    The all-or-nothing property used to cover collisions only, so every other
    way a write can fail arrived as a traceback, and two of them arrived AFTER
    the first file had already been written: a destination that is a directory,
    a destination that is read-only, a parent path that is a file. A stack trace
    is not a refusal — it names no repair, and its "nothing was written" is a
    claim nobody made.

    This function used to BE those checks. It is now a caller: `core.apply`
    decides, in the same closed vocabulary every other writer in this package
    is decided in, and this maps the reason to the sentence four install verbs
    already print. A second copy of "can this be written" is a second chance to
    answer it differently.

    SYMLINKS ARE FOLLOWED here, said out loud rather than left to a default: an
    install destination is an ordinary repo file, and a project that symlinks
    `.claude/agents/` somewhere deliberate is exercising a choice this tool has
    no business overriding. The scaffolder declares the opposite, because a
    symlinked grain slot points OUT of the grain it was asked to fill.

    Not a substitute for handling the write's own OSError: a permission can
    change between this call and the write, and TOCTOU is exactly the case that
    must still not traceback. This is what turns the common cases into a
    sentence naming the path.
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
        existing = text
    sys.stdout.writelines(difflib.unified_diff(
        existing.splitlines(keepends=True), body.splitlines(keepends=True),
        fromfile=f'a/{rel}', tofile=f'b/{rel}'))


def _defect_refusal(command: str, defects: list[str], wrote: list[str]) -> str:
    listed = '\n'.join(f'    {d}' for d in defects)
    what = ('nothing was written' if not wrote else
            'ALREADY WRITTEN before this was reached: ' + ', '.join(wrote))
    return (f'godot-devkit {command}: {len(defects)} destination(s) cannot be '
            f'written:\n{listed}\n'
            f'godot-devkit {command}: {what}. Fix the path(s) and re-run — the '
            f'command is idempotent.')


def main(command: str, argv: list[str]) -> int:
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
            print(f'godot-devkit {command}: unknown flag {arg!r}',
                  file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2

    root = repo_root()
    entries = [(root / rel, rel, body_of(name))
               for name, rel in PLANS[command]]

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
            if existing == body:
                kind = 'current'
            elif not force:
                collisions.append(rel)
                continue
        plan.append((kind, target, rel, body))

    # Collisions first: they are the refusal a human is most likely to hit, and
    # a run that has both should name the one --force answers.
    if collisions:
        head, tail = collision_refusal(collisions)
        print(f'godot-devkit {command}: {head}\n'
              f'godot-devkit {command}: {tail}', file=sys.stderr)
        return 1
    if defects:
        print(_defect_refusal(command, defects, []), file=sys.stderr)
        return 1

    # ONE plan, decided above and applied here. `install-agents` half-installed
    # twice because the loop that wrote also decided: the third file's problem
    # arrived with the first two already on disk. `core.apply` returns what
    # LANDED, so the refusal below names it instead of guessing.
    writes = apply.Plan()
    for kind, target, rel, body in plan:
        if kind != 'current':
            writes.overwrite(target, body, newline=None, label=rel)
    # Everything answerable was answered above, so a failure here means the
    # filesystem changed under the plan. It is still a refusal that names what
    # it did — never a traceback, and never a silent "nothing was written" over
    # a directory that already has one.
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
        print(_defect_refusal(command,
                              [f'{result.failed.label} could not be written '
                               f'({result.error})'], written),
              file=sys.stderr)
        return 1
    if written:
        print(f'[install] {_NEXT_STEP[command]}')
    return 0
