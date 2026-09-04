"""install.py — write a file into a repo, once, from one source.

Three verbs, one relationship, and it is deliberately the whole relationship:

    install-ci      the four workflows a Godot project runs on a push:
                    verify.yml (checkout, uv, the Godot toolchain a tree with
                    a project.godot asks for, `make milestone`),
                    uid-guard.yml, semver-gate.yml and auto-tag.yml. Each was forked in both
                    consumers, drifting on a project name and on which fix each
                    fork got. They carry no gate of their own and no way to
                    parameterize one: a project that wants something else edits
                    the file, which is now its file. Release / website / social
                    workflows are the project's and are not written.
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
    install-runners the sandboxed headless-run shell library, the runners
                    that source it, and `Makefile.devkit` — the standard target
                    set that calls them. Not folded into install-hooks: a
                    hooks-only consumer would carry runners it never calls, and
                    the library is sourced by make targets rather than fired by
                    Claude Code. Every function is `gdk_*` — the two consumers'
                    `nullbound_*` / `trail_*` forks are what this replaces, so
                    a consumer keeping its prefix is a second name for the same
                    fact and is not supported.

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
        # The set both consumers actually run on a push, in the order they
        # fire: the full gate on every PR and mainline push, then the three
        # that guard the merge and the tag. Release, website and social
        # workflows are the PROJECT's — this verb does not write them and does
        # not know they exist.
        ('ci-verify.yml', '.github/workflows/verify.yml'),
        ('ci-uid-guard.yml', '.github/workflows/uid-guard.yml'),
        ('ci-semver-gate.yml', '.github/workflows/semver-gate.yml'),
        ('ci-auto-tag.yml', '.github/workflows/auto-tag.yml'),
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
        # The two ledger couriers. They GUARD nothing — they copy the stop
        # event's transcript path and ids into `pm ledger record` and exit 0 —
        # but they are hooks, they are standalone, and they carry the same
        # editable header, so they ship on the verb that already writes
        # tools/hooks/ and the script that already arms it by glob.
        ('cc-ledger-subagent.sh', 'tools/hooks/cc-ledger-subagent.sh'),
        ('cc-ledger-session.sh', 'tools/hooks/cc-ledger-session.sh'),
        ('pre-push', 'tools/hooks/pre-push'),
        ('prepare-commit-msg', 'tools/hooks/prepare-commit-msg'),
        ('agent-worktree.sh', 'tools/dev/agent-worktree.sh'),
        ('doctor.sh', 'tools/dev/checks/doctor.sh'),
        ('setup-hooks.sh', 'tools/setup-hooks.sh'),
    ),
    'install-runners': (
        # The library first, then the runners that source it. The layout is
        # what every runner's own defaults assume: a runner reaches the library
        # at ../gdk_runners.sh and the repo root at ../../.. A repo that wants
        # them elsewhere moves them all and sets GDK_RUNNERS_LIB — after the
        # write the files are its own.
        ('gdk_runners.sh', 'tools/dev/gdk_runners.sh'),
        ('import_cache.sh', 'tools/dev/runners/import_cache.sh'),
        ('parse.sh', 'tools/dev/runners/parse.sh'),
        # compile_sweep.gd travels WITH parse.sh, beside it rather than in a
        # checks/ of its own: it is stage 2 of that runner and has no other
        # caller, and parse.sh addresses it as res://tools/dev/runners/
        # compile_sweep.gd (GDK_PARSE_SWEEP_SCRIPT). One directory, so moving
        # the runners moves the pair together and only one variable has to
        # follow.
        ('compile_sweep.gd', 'tools/dev/runners/compile_sweep.gd'),
        # …and its `.uid` SIDECAR, the only file in this package carrying a
        # value the ENGINE would otherwise mint. It ships because the
        # alternative is worse in both directions: without it, `check uid`
        # CHECK 3 correctly reports a NEW `.gd` with no sidecar on every
        # freshly-`init`'d project — a red gate on a file the project did not
        # write and cannot be asked to explain — and softening the check to
        # exempt "a devkit-installed .gd under tools/dev/" would put a hole in
        # the one gate that sees a missing sidecar, keyed on a path prefix any
        # file can move into.
        #
        # A uid is RANDOM, not derived (`ResourceUID.create_id()`), so this one
        # was minted once, here, and is a constant like any other. That is not
        # the invention `check uid --fix` refuses: a gate fabricating a uid for
        # a file it is JUDGING would be guessing at a fact it cannot know,
        # while an installable declaring the identity of its own shipped script
        # is stating one. It is canonical under the ported codec
        # (`id_to_text(text_to_id(x)) == x`), so Godot will not rewrite it, and
        # it is the same on every consumer — which is what keeps the install
        # idempotent and the gate quiet on day one.
        ('compile_sweep.gd.uid', 'tools/dev/runners/compile_sweep.gd.uid'),
        ('lint.sh', 'tools/dev/runners/lint.sh'),
        ('warnings.sh', 'tools/dev/runners/warnings.sh'),
        ('unit.sh', 'tools/dev/runners/unit.sh'),
        # scenario.sh is the single-scenario entry point; integration.sh fans
        # it out and capture.sh is its headed twin. All three sit in one
        # directory because integration.sh reaches scenario.sh by
        # GDK_SCENARIO_RUNNER, relative to itself.
        ('scenario.sh', 'tools/dev/runners/scenario.sh'),
        ('integration.sh', 'tools/dev/runners/integration.sh'),
        ('capture.sh', 'tools/dev/runners/capture.sh'),
        # The gate ON the library rather than a gate that uses it: it proves a
        # run's HOME self-destructs and nothing persists beside the spool. It
        # ships here because it can only be true of an installed PAIR — the
        # library and the wrappers that call it.
        ('hermetic_run_scan.sh', 'tools/dev/runners/hermetic_run_scan.sh'),
        # The CALLERS, at the repo root. It ships with the runners rather than
        # under a verb of its own because neither half is usable alone: the
        # runners are unreachable without targets pointing at them (this verb's
        # next step used to be a paragraph asking the operator to write those
        # targets by hand), and every runner-backed target in the include is
        # dead without the runners. One verb, one working `make`.
        ('Makefile.devkit', 'Makefile.devkit'),
    ),
}

USAGE = """usage: godot-devkit install-ci      [--force] [--diff]
       godot-devkit install-agents  [--force] [--diff]
       godot-devkit install-hooks   [--force] [--diff]
       godot-devkit install-runners [--force] [--diff]

install-ci      four workflows under .github/workflows/: verify.yml
                (checkout, uv, then — only where a project.godot sits — the
                engine `config/features` declares plus gdlint and
                shellcheck, then `make milestone`, which it ASSUMES is your
                full gate), uid-guard.yml (`make uid-scan` on a PR and on
                a push to staging), semver-gate.yml (a merge to main must bump
                config/version) and auto-tag.yml (tag the mainline, then
                dispatch RELEASE_WORKFLOW if you have one). A project without
                one of those assumptions edits the file, which after the write
                is its own.
install-agents  the review/build contract plus the base agent roster, as
                AGENT DEFINITIONS under .claude/agents/ — the one place a
                subagent actually reads. Each roster file carries a
                `Project config` section — yours to edit after install.
install-hooks   the agent-workflow guard corpus, under tools/: the Claude Code
                hooks (cc-commit-pathspec, cc-godot-sandbox, cc-stop-gate,
                cc-write-confine) plus the two ledger couriers
                (cc-ledger-subagent on SubagentStop, cc-ledger-session on
                Stop, each handing the stop event's transcript path to
                `pm ledger record` and exiting 0 whatever it says), the git
                hooks (pre-push, prepare-commit-msg),
                tools/dev/agent-worktree.sh, tools/dev/checks/doctor.sh, and
                tools/setup-hooks.sh, which arms them. Each carries a small
                `project config` header — yours to edit after install.
                cc-godot-sandbox.sh and the two couriers ship their own
                corpora: wire `bash tools/hooks/<hook>.sh --self-test` into
                your static gate (nullbound: a `hooks-self-test` target in
                `make check`). The run prints the .claude/settings.json entries
                that fire them.
install-runners tools/dev/gdk_runners.sh — the shell library your
                Godot-booting make targets source (one verdict line per gate
                naming .gate-reports/<gate>.log, VERBOSE=1 streams, a per-run
                self-destroying HOME sandbox, a bounded-run contract, a
                project.godot restore) — plus the runners that source it under
                tools/dev/runners/: import_cache.sh, parse.sh (+ its
                compile_sweep.gd and the .uid sidecar the engine would
                otherwise mint), lint.sh, warnings.sh, unit.sh (GUT,
                sliced, with the coverage gate that fails a test script GUT
                refused to load), scenario.sh, integration.sh (the same
                scenarios, one process each, N in parallel), capture.sh
                (headed, because headless is blind to render), and
                hermetic_run_scan.sh — the gate proving a run's HOME
                self-destructs and nothing persists beside the spool. Every
                one carries --help and --self-test. Plus Makefile.devkit at
                the repo root: the standard target set that calls them, which
                your own Makefile `include`s.

A destination that already exists and differs is refused, whole.
--force overwrites it. --diff prints what would change and writes nothing."""

# A `.sh` installable is WRITTEN EXECUTABLE. Every one of them is a script a
# caller runs — a make recipe, a hook dispatcher, another runner's fan-out —
# and a script that is not executable is a file that looks installed and is
# not. `integration.sh` exec'd `scenario.sh` directly and got exit 126 from
# every scenario on every `init`'d project, under a FAILURES block that printed
# nothing, because `Permission denied` matched no summary pattern.
#
# The mode is part of the WRITE, in `core.apply`, which owns every mutation
# this package makes. It is not a post-pass: a chmod outside the plan is the
# decide-as-you-go shape that module exists to remove.
#
# The extension-less git hooks (`pre-push`, `prepare-commit-msg`) are still
# armed by `tools/setup-hooks.sh`, because arming one is also pointing
# `core.hooksPath` at the directory — one act, one owner, and it ships in the
# same install.
EXECUTABLE_SUFFIX = '.sh'


def _is_executable(target: Path) -> bool:
    """Whether `target` already carries an execute bit for anyone."""
    try:
        return bool(target.stat().st_mode & 0o111)
    except OSError:
        return False


# Installing tools/hooks/* is not arming them: core.hooksPath silently skips a
# non-executable hook, and pointing git at the directory is the other half of
# the same act. The script that does both is in the same install.
_NEXT_STEP = {
    'install-hooks': 'run `bash tools/setup-hooks.sh` to point git at them and '
                     'set the exec bit — an unexecutable hook is skipped in '
                     'silence. Then review each file\'s `project config` '
                     'header (gate commands, protected branches, trailer): '
                     'the files are yours now, and the stock values assume '
                     'the standard consumer Makefile. Then wire `bash '
                     'tools/hooks/cc-godot-sandbox.sh --self-test` into your '
                     'static gate (nullbound: a `hooks-self-test` target in '
                     '`make check`) — it replays the hook\'s own block/allow '
                     'corpus, so an edit to the guard cannot quietly change '
                     'a verdict. Then paste the settings block below into '
                     '.claude/settings.json — installing a Claude Code hook '
                     'is not registering it, and an unregistered hook is a '
                     'file nothing ever runs.',
    'install-agents': 'the verification pair carries the review and build '
                      'contract; the rest are the base roster. Each roster '
                      'file opens with a `Project config` section — edit its '
                      'stock values (gate commands, pm tree, doc layout) to '
                      'your spellings: the files are yours now. `model:` in '
                      'the frontmatter is doing proven work; `effort:` is '
                      'carried unverified. The SDLC these agents run is '
                      'SDLC.md at the godot-devkit repo root.',
    'install-ci': 'verify.yml runs `make milestone` — confirm that target '
                  'exists and is your full gate. uid-guard.yml runs `make '
                  'uid-scan` on a PR to main and a push to staging; rename the '
                  'branches if yours differ (an `on:` filter takes no '
                  'variable). semver-gate.yml and auto-tag.yml read '
                  'config/version out of project.godot; set '
                  'RELEASE_WORKFLOW in auto-tag.yml if your release pipeline '
                  'is not release.yml, and leave it alone if you have none — '
                  'the step is a documented no-op then.',
    'install-runners': 'make your Makefile two lines — `DEVKIT_VERSION := '
                       '<tag>` and then `include Makefile.devkit` — plus your '
                       'own targets; your own gates join `check` through '
                       '`[gates] extra` in devkit.toml, never a fork of the '
                       'include. Then gitignore '
                       '.gate-reports/, .scenario-reports/, .capture-reports/ '
                       'and .headless-userdata/. Every `.sh` here is written '
                       'EXECUTABLE, so a target may call it either way — the '
                       'stock recipes say `bash tools/dev/runners/<x>.sh`, '
                       'which also works on a checkout that lost the mode '
                       'bits. Then edit each file\'s `project config` header: '
                       'the files are yours now.',
}

# The `.claude/settings.json` entries that FIRE the Claude Code half of the
# corpus. `tools/setup-hooks.sh` arms the GIT hooks — `core.hooksPath` plus the
# exec bit — and there is no equivalent for a Claude Code hook: it runs because
# a settings file names it, and nothing else. So an install that wrote the
# files and said nothing else left every guard on disk and none of them armed.
#
# PRINTED, not written. `.claude/settings.json` is a hand-maintained file with
# permissions, env and MCP entries this package knows nothing about, and the
# install verbs write a whole file or refuse — there is no merge here and there
# is deliberately not going to be one. Copying a block is the operator's edit
# to their own file.
#
# The two ledger couriers are `"async": true` because they are the only entries
# here that do WORK rather than decide: the verb parses a transcript that can
# be tens of megabytes (D4), and an orchestrator that waits for that on every
# stop pays the cost the async flag exists to remove. The four guards are
# synchronous on purpose — a PreToolUse block that arrived after the tool ran
# would be narration, and cc-stop-gate's exit 2 IS the gate.
#
# `SubagentStop` takes a matcher (on `agent_type`) and `Stop` takes none;
# cc-ledger-subagent.sh is registered with NO matcher, because every dispatch
# costs something and a roster written here would silently stop measuring the
# day a repo adds an agent.
_HOOK_SETTINGS = '''{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "bash tools/hooks/cc-commit-pathspec.sh"},
          {"type": "command", "command": "bash tools/hooks/cc-godot-sandbox.sh"}
        ]
      },
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {"type": "command", "command": "bash tools/hooks/cc-write-confine.sh"}
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "bash tools/hooks/cc-stop-gate.sh"},
          {"type": "command", "command": "bash tools/hooks/cc-ledger-session.sh", "async": true}
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {"type": "command", "command": "bash tools/hooks/cc-ledger-subagent.sh", "async": true}
        ]
      }
    ]
  }
}'''

# Only `install-hooks` has a registration step; the other three verbs' files
# are found by a path (a workflow directory, an agents directory, a make
# include) rather than by a settings entry.
_SETTINGS_BLOCK = {'install-hooks': _HOOK_SETTINGS}


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


def main(command: str, argv: list[str], next_step: bool = True) -> int:
    """One install verb. `next_step=False` silences the closing paragraph.

    `init` composes all four of these and then DOES most of what those
    paragraphs ask for — writes the two-line Makefile, gitignores the run
    artifacts, runs setup-hooks.sh. Printed there, they would send an operator
    to wire what the same command just wired, and a report whose instructions
    are already stale is a report nobody finishes reading. Init prints its own,
    covering the residue that still applies.
    """
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
            writes.overwrite(target, body, newline=None, label=rel,
                             executable=rel.endswith(EXECUTABLE_SUFFIX))
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
    if written and next_step:
        print(f'[install] {_NEXT_STEP[command]}')
        settings = _SETTINGS_BLOCK.get(command)
        if settings:
            # Raw, unprefixed, so the block can be selected and pasted whole.
            # A `[install] ` on every line would make the operator strip it,
            # and a JSON file is the one place a stray prefix is not a cosmetic
            # problem.
            print(f'\n.claude/settings.json — the entries that FIRE these '
                  f'hooks (merge into yours):\n\n{settings}\n')
    return 0
