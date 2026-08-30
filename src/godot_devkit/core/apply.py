"""apply.py — the ONE place this package mutates a filesystem.

The same review that found six silent censuses found six half-writes: three
scaffolder refusal paths that raised with an earlier rename already on disk (and
already in the git INDEX, via `git mv --force`), a symlinked slot written
THROUGH to a file outside the grain it was asked to fill, `install-agents`
half-installing twice, and `pm collapse` deleting uncommitted prose. Every one
of them printed "nothing was written" while something had been.

The shape is that a writer DECIDES AS IT GOES. `target.write_text(...)` inside a
loop is a decision and an action in one expression, so the loop's third
iteration discovers a problem the first two have already made irreversible.

This module separates the two, and gives the separation a type. A `Plan` is an
EXPLICIT list of `Step`s — each naming its act and its destination, nothing
derived at apply time. `Plan.decide()` inspects the whole plan against the
filesystem and returns every `Blocked` step with a reason from a CLOSED enum.
`Plan.apply()` runs decide first, refuses whole when anything is blocked, and
otherwise executes — and if the filesystem changes under it anyway, the
`Applied` it returns names EXACTLY which steps landed. There is no way to get a
partial result that does not say so.

`tests/test_boundaries.py` asserts that `write_text`, write-mode `open`,
`rename`, `unlink`, `rmtree`, `mkdir` and the `os.`/`shutil.` mutators appear
NOWHERE ELSE in `src/`. A new verb cannot write directly. The builder methods
here are spelled `make_dir` / `move` rather than `mkdir` / `rename` for that
test's sake: an AST cannot tell `plan.mkdir()` from `Path.mkdir()`, and it must
not have to.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Act(Enum):
    """What one step DOES. Closed: a plan holds nothing else."""

    MKDIR = 'create directory'
    OVERWRITE = 'overwrite'
    RENAME = 'rename'
    DELETE_TREE = 'delete directory tree'
    DELETE_FILE = 'delete file'


class Obstruction(Enum):
    """Why a step cannot run. CLOSED — the whole vocabulary of a refusal.

    Every one of these is answerable by LOOKING, before anything is written.
    What is left over (a disk that fills, a mode changed under the plan) is
    reported by `Applied`, which names what landed.
    """

    EXISTS = 'already exists'
    IS_A_DIRECTORY = 'is a directory'
    IS_A_SYMLINK = 'is a symlink'
    NOT_WRITABLE = 'is not writable'
    PARENT_NOT_WRITABLE = 'its directory is not writable'
    PARENT_IS_A_FILE = 'its parent is a file, not a directory'
    MISSING_SOURCE = 'does not exist'
    NOT_A_DIRECTORY = 'is not a directory'
    NOT_A_REGULAR_FILE = 'is not a regular file'


class Symlink(Enum):
    """What a step does when its destination is a SYMLINK. Declared by the
    caller, never inferred, because the two callers in this package genuinely
    differ and the difference is a decision rather than a detail.

    REFUSE is the scaffolder's: a symlinked slot is a slot whose bytes live
    somewhere else, and following it lets a verb asked to fill ONE grain rewrite
    a file outside it. FOLLOW is `install-agents`/`install-skills`': their
    destinations are ordinary repo files, and a project that symlinks
    `.claude/agents/` somewhere deliberate is exercising a choice this tool has
    no business overriding.
    """

    REFUSE = 'refuse'
    FOLLOW = 'follow'


@dataclass(frozen=True)
class Step:
    """One intended operation, fully named.

    `dest` is where it lands; `body` is what CREATE/OVERWRITE write; `src` is
    what RENAME moves. Nothing here is computed at apply time — that is the
    whole point of the type. A caller that would decide the destination inside
    the apply loop puts the decision in the plan instead.

    `newline` is the write policy, and it is explicit because the two spellings
    are not interchangeable: `''` writes the bytes given (what every grain
    document needs, so a CRLF template stays CRLF), `None` is `write_text`'s
    universal translation.
    """

    act: Act
    dest: Path
    body: str | None = None
    src: Path | None = None
    newline: str | None = ''
    label: str = ''
    symlink: Symlink = Symlink.REFUSE

    def describe(self) -> str:
        if self.act is Act.RENAME:
            return f'{self.act.value} {self.src} -> {self.dest}'
        return f'{self.act.value} {self.dest}'


@dataclass(frozen=True)
class Blocked:
    step: Step
    path: Path
    reason: Obstruction

    def describe(self) -> str:
        return f'{self.path} {self.reason.value}'


@dataclass(frozen=True)
class Applied:
    """What a run of `Plan.apply` actually did.

    `landed` is the steps that completed, in order. `blocked` is non-empty when
    the plan was refused BEFORE anything ran, in which case `landed` is empty
    and means it. `error` is set when a step failed mid-apply — the case no
    listing could have predicted — and `landed` then says precisely how far it
    got.
    """

    landed: tuple[Step, ...] = ()
    blocked: tuple[Blocked, ...] = ()
    failed: Step | None = None
    error: str = ''



@dataclass
class Plan:
    """An explicit list of intended operations. Decide, then apply."""

    steps: list[Step] = field(default_factory=list)

    def add(self, step: Step) -> 'Plan':
        self.steps.append(step)
        return self

    def overwrite(self, dest: Path, body: str, *, newline: str | None = '',
                  label: str = '', symlink: Symlink = Symlink.REFUSE) -> 'Plan':
        return self.add(Step(Act.OVERWRITE, dest, body=body, newline=newline,
                             label=label, symlink=symlink))

    # Named `make_dir` / `move`, not `mkdir` / `rename`, and deliberately: an
    # AST cannot tell `plan.mkdir(...)` from `Path.mkdir(...)`, and the boundary
    # test that keeps every other module out of the filesystem must not have to.
    # A distinct vocabulary for INTENT also reads correctly — a plan step is
    # something to be done, not something done.
    def make_dir(self, dest: Path, *, label: str = '') -> 'Plan':
        return self.add(Step(Act.MKDIR, dest, label=label))

    def move(self, src: Path, dest: Path, *, label: str = '') -> 'Plan':
        return self.add(Step(Act.RENAME, dest, src=src, label=label))

    def delete_tree(self, dest: Path, *, label: str = '') -> 'Plan':
        return self.add(Step(Act.DELETE_TREE, dest, label=label))

    def delete_file(self, dest: Path, *, label: str = '') -> 'Plan':
        return self.add(Step(Act.DELETE_FILE, dest, label=label))

    # --- phase one ------------------------------------------------------------
    def decide(self) -> list[Blocked]:
        """Every step that cannot run, with the reason it cannot.

        Inspects the WHOLE plan before reporting, so a caller sees all of it
        rather than the first thing to go wrong — a refusal a human fixes twice
        is a refusal that has narrowed to one instance.

        The plan is read against the filesystem AS IT IS, plus the plan's own
        MKDIR steps: a two-step "make the directory, then fill it" plan is not
        refused for a parent the plan itself creates.
        """
        out: list[Blocked] = []
        planned_dirs = {s.dest for s in self.steps if s.act is Act.MKDIR}
        for step in self.steps:
            out.extend(self._obstructions(step, planned_dirs))
        return out

    def _obstructions(self, step: Step, planned_dirs: set[Path]) -> list[Blocked]:
        out: list[Blocked] = []
        dest = step.dest
        if step.act in (Act.OVERWRITE, Act.MKDIR, Act.RENAME):
            out.extend(self._parent_obstructions(step, dest, planned_dirs))
        if step.act is Act.OVERWRITE:
            # A SYMLINK is refused rather than followed unless the caller says
            # otherwise: writing through one lets a verb asked to fill one place
            # rewrite a file somewhere else, which is exactly how the scaffolder
            # wrote outside the grain it was given.
            if step.symlink is Symlink.REFUSE and dest.is_symlink():
                out.append(Blocked(step, dest, Obstruction.IS_A_SYMLINK))
            elif dest.exists() and not dest.is_file():
                out.append(Blocked(step, dest, Obstruction.IS_A_DIRECTORY
                                   if dest.is_dir()
                                   else Obstruction.NOT_A_REGULAR_FILE))
            elif dest.is_file() and not os.access(dest, os.W_OK):
                out.append(Blocked(step, dest, Obstruction.NOT_WRITABLE))
        elif step.act is Act.MKDIR:
            if dest.exists() and not dest.is_dir():
                out.append(Blocked(step, dest, Obstruction.NOT_A_DIRECTORY))
        elif step.act is Act.RENAME:
            src = step.src
            if src is None or not (src.exists() or src.is_symlink()):
                out.append(Blocked(step, src or dest, Obstruction.MISSING_SOURCE))
            elif src != dest and dest.exists() and not _case_respelling(src, dest):
                out.append(Blocked(step, dest, Obstruction.EXISTS))
            elif src is not None and not os.access(src.parent, os.W_OK):
                # A rename writes the DIRECTORY, not the file, and the two
                # permissions are independent: a 0555 directory holding a 0644
                # file passes every per-file check and then fails in `rename`.
                out.append(Blocked(step, src.parent, Obstruction.PARENT_NOT_WRITABLE))
        elif step.act is Act.DELETE_TREE:
            if dest.exists() and not dest.is_dir():
                out.append(Blocked(step, dest, Obstruction.NOT_A_DIRECTORY))
        elif step.act is Act.DELETE_FILE:
            if dest.exists() and not dest.is_file():
                out.append(Blocked(step, dest, Obstruction.NOT_A_REGULAR_FILE))
            elif dest.is_file() and not os.access(dest.parent, os.W_OK):
                # An unlink writes the DIRECTORY, like a rename does.
                out.append(Blocked(step, dest.parent,
                                   Obstruction.PARENT_NOT_WRITABLE))
        return out

    def _parent_obstructions(self, step: Step, dest: Path,
                             planned_dirs: set[Path]) -> list[Blocked]:
        """Whether the destination's directory can be CREATED.

        Walks up to the first ancestor that exists, because `mkdir(parents=True)`
        does: a missing `a/b/c/` is fine if `a/` is a writable directory, and is
        not if `a` is a file. Checking only `dest.parent` would wave through
        every nested destination and then traceback inside the write.
        """
        parent = dest.parent
        if parent in planned_dirs or parent == dest:
            return []
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir():
            return [Blocked(step, parent, Obstruction.PARENT_IS_A_FILE)]
        if not os.access(parent, os.W_OK):
            return [Blocked(step, parent, Obstruction.PARENT_NOT_WRITABLE)]
        return []

    # --- phase two ------------------------------------------------------------
    def apply(self, *, decide: bool = True) -> Applied:
        """Run the plan. Refuses whole when `decide` finds anything.

        `decide=False` is for the caller that has already decided in its own
        vocabulary — the scaffolder's refusals name slots and templates, not
        paths, and re-deciding here would either duplicate that or contradict
        it. It does NOT skip the reporting: whatever happens, `Applied` names
        what landed.
        """
        if decide:
            blocked = self.decide()
            if blocked:
                return Applied(blocked=tuple(blocked))
        landed: list[Step] = []
        for step in self.steps:
            try:
                _run(step)
            except OSError as err:
                return Applied(tuple(landed), failed=step,
                               error=str(err.strerror or err))
            landed.append(step)
        return Applied(tuple(landed))


def _case_respelling(src: Path, dest: Path) -> bool:
    """True when `dest` is the SAME file as `src` under a case-variant name —
    a rename-in-place on a case-insensitive filesystem, where `dest.exists()`
    is true because it IS the source. That is the one collision that is not
    one. Both halves matter: name-only waved through overwriting a DIFFERENT
    file that happened to match `src.name.upper()`, and the old
    lower()/upper() spelling falsely blocked any mixed-case rename."""
    if src.name.lower() != dest.name.lower():
        return False
    try:
        return os.path.samefile(src, dest)
    except OSError:
        return False


def _run(step: Step) -> None:
    """The only place a byte moves. Every branch is one `Act`."""
    if step.act is Act.MKDIR:
        step.dest.mkdir(parents=True, exist_ok=True)
    elif step.act is Act.OVERWRITE:
        step.dest.parent.mkdir(parents=True, exist_ok=True)
        with step.dest.open('w', encoding='utf-8', newline=step.newline) as fh:
            fh.write(step.body or '')
    elif step.act is Act.RENAME:
        assert step.src is not None
        step.src.rename(step.dest)
    elif step.act is Act.DELETE_TREE:
        # A tree that is already gone is the desired end state (idempotent);
        # anything else that stops the delete must surface as `Applied.failed`
        # — `ignore_errors=True` here was the one step in this module that
        # reported `landed` over a delete that did not happen.
        if step.dest.exists() or step.dest.is_symlink():
            shutil.rmtree(step.dest)
    elif step.act is Act.DELETE_FILE:
        # Already-gone is the desired end state (idempotent), same as
        # DELETE_TREE; a directory here raises and surfaces as `failed`.
        step.dest.unlink(missing_ok=True)


# --- the one-step conveniences ------------------------------------------------
# A single write is still a plan; these exist so a caller with exactly one step
# does not have to say so twice. They go through `Plan` — there is no shortcut
# past the type, because the shortcut is what the primitive exists to remove.

def write(path: Path, text: str, *, newline: str | None = '') -> Applied:
    """Write one file, creating its directory. Raw newlines by default, so a
    template's own line endings survive the round trip."""
    return Plan().overwrite(path, text, newline=newline).apply(decide=False)


def write_translated(path: Path, text: str) -> Applied:
    """`Path.write_text` semantics — `\\n` translated on write."""
    return write(path, text, newline=None)


def make_dir(path: Path) -> Applied:
    return Plan().make_dir(path).apply(decide=False)


def remove_file(path: Path) -> Applied:
    return Plan().delete_file(path).apply(decide=False)


def raise_on_error(applied: Applied) -> None:
    """Re-raise a mid-apply failure as the `OSError` the caller's own handler
    expects. For the callers whose refusal wording predates this module: they
    catch `OSError` and say something domain-specific about it, and taking that
    away would change a message a consumer's hook prints."""
    if applied.failed is not None:
        raise OSError(applied.error)
