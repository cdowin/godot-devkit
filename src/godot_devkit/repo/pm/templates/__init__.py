"""templates/ — the grain and doc templates, and where a project overrides them.

The package holds BOTH the loader and the `.md` files it serves, so
`importlib.resources` addresses them by package name with no separate data path
to keep in sync. (A sibling `templates.py` module plus a `templates/` directory
does not work: the module shadows the package and every lookup misses — which is
exactly how this was first written.)

Templates are FILES, not a dict in the code: a project can read them, diff them,
and replace one without restating the schema of the others. Placeholders are
`{name}` and are filled by `render`; anything a template does not name is simply
absent, so adding a field to a project's copy needs no code change here.

Override by pointing `[pm] template_dir` at a directory in the consuming repo.
A file present there wins; anything missing falls back to the packaged default,
so a project overriding one grain does not inherit responsibility for the rest.
"""
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

from godot_devkit.repo.pm import model

# The halfway name a case-only rename passes through on a case-INSENSITIVE
# filesystem. Named once because two places need it: the mover, and the pre-pass
# that refuses a leftover one before anything moves.
TEMP_RENAME_SUFFIX = '{name}.pm-case-rename'

# grain -> template filename. The shared docs are addressed by their SLOT name
# minus the extension, so `decisions.md` is minted by `decisions.md` and there
# is no mapping table to keep in sync.
GRAINS = ('milestone', 'feature', 'story', 'bug')
DOCS = ('handoff', 'decisions', 'changelog', 'review')


class MissingTemplate(Exception):
    """No packaged or project template by that name."""


def _packaged(name: str) -> str | None:
    try:
        return (resources.files('godot_devkit.repo.pm.templates')
                .joinpath(f'{name}.md').read_text(encoding='utf-8'))
    except (FileNotFoundError, ModuleNotFoundError):
        return None


def load(cfg: model.PmConfig, name: str) -> str:
    """The template text for `name`, project override winning."""
    if cfg.template_dir:
        tdir = cfg.root / cfg.template_dir
        # EXACT name, from a listing. `Path.is_file()` on macOS resolves
        # `decisions.md` to a leftover `DECISIONS.md` and on Linux does not, so
        # the same repo would render from a different template per platform.
        if model.dir_entries(tdir).get(f'{name}.md') == 'file':
            return model.read_raw(tdir / f'{name}.md')
    text = _packaged(name)
    if text is None:
        raise MissingTemplate(
            f'no template {name!r} — packaged templates are '
            f'{", ".join((*GRAINS, *DOCS))}'
            + (f', and none was found in {cfg.template_dir}/'
               if cfg.template_dir else ''))
    return text


def render(text: str, values: dict[str, str]) -> str:
    """Fill `{placeholder}`s. Unknown placeholders are left ALONE, not blanked.

    A template is prose as much as schema, and prose contains braces. Silently
    emptying something that merely looked like a placeholder would corrupt the
    file the author wrote; leaving it visible makes the mistake obvious.
    """
    out = text
    for key, val in values.items():
        out = out.replace('{' + key + '}', val)
    return out


def write(path: Path, text: str) -> None:
    """Create a grain file, preserving the template's own line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as fh:
        fh.write(text)


class ScaffoldRefused(Exception):
    """The scaffolder cannot guarantee a correct result, so it did nothing."""


def _rename_case(cfg: model.PmConfig, old: Path, new: Path) -> bool:
    """`DECISIONS.md` -> `decisions.md`, recorded by GIT when git tracks it.
    True when git moved it — so the rename is also STAGED — and False when the
    temp rename did, which stages nothing at all.

    Which one ran is the whole of the advice a later refusal can give. Telling
    an operator to unstage a rename that only ever touched the worktree sends
    them to a `git status` showing nothing, and unactionable advice on a refusal
    is its own defect.

    Two problems, one on each side of the filesystem. macOS is
    case-INSENSITIVE, so the rename is a no-op there and `open(new)` would
    truncate the existing file — the migration deleting the very content it
    exists to carry forward. And git on macOS defaults to
    `core.ignorecase = true`, under which a worktree-only rename leaves the
    INDEX on the old spelling: clean on the laptop, and CI on Linux checks out
    `DECISIONS.md` with every gate red. `git mv --force` fixes both at once.

    Untracked, or no git: the two-step temp rename is a real rename on both
    kinds of filesystem. Tracked and git refused: this REFUSES, printing the
    command that finishes the job, because a half-done rename is the one
    outcome worse than none.

    Every failure out of here is a ScaffoldRefused naming WHERE THE BYTES ARE.
    The two `rename` calls sat outside any handler, so a grain directory the
    process cannot write (its FILES being writable proves nothing about it)
    came out as a `PermissionError` traceback under exit 1 — the one code this
    package reserves for findings. And the second call failing is worse than
    the first: the log is then parked under a temp name that no later run looks
    for, so a message saying only "the rename failed" leaves an operator
    hunting for content that is sitting right there.
    """
    done, why = model.git_rename(cfg.root, old, new)
    if done:
        return True
    if why:
        raise ScaffoldRefused(
            f'git tracks {cfg.rel(old)} and would not rename it to {new.name} '
            f'({why}) — its content is untouched, still at {cfg.rel(old)}; run '
            f'`git mv --force {cfg.rel(old)} {cfg.rel(new)}` yourself, then '
            f're-run')
    # The squatter this would trip over is refused in the pre-pass, where the
    # directory listing already showed it — a refusal raised here has an earlier
    # slot's rename behind it and is no longer the "nothing was written" it says.
    tmp = old.with_name(TEMP_RENAME_SUFFIX.format(name=old.name))
    try:
        old.rename(tmp)
    except OSError as err:
        raise ScaffoldRefused(
            f'{cfg.rel(old)} could not be renamed to {new.name} ({err}); its '
            f'content is untouched, still at {cfg.rel(old)}') from err
    try:
        tmp.rename(new)
    except OSError as err:
        raise ScaffoldRefused(
            f'{cfg.rel(old)} was renamed halfway to {new.name} and the second '
            f'step failed ({err}) — ITS CONTENT IS NOW AT {cfg.rel(tmp)}, '
            f'where nothing looks for it; finish the move with `mv '
            f'{cfg.rel(tmp)} {cfg.rel(new)}`, then re-run') from err
    return False


def _header_wanted(path: Path, slot: str) -> str:
    """The instruction line this doc is MISSING, or '' when it needs none.

    A file already opening with SOME known instruction line needs none, so a
    future wording change can never stack two headers; D13 reports the mismatch
    and a human decides.
    """
    want = model.SLOT_HEADER.get(slot)
    if want is None:
        return ''
    got = model.header_of(path)
    return '' if got == want or got in set(model.SLOT_HEADER.values()) else want


def _fill_header(path: Path, slot: str, actions: list[tuple[str, Path]]) -> None:
    """Prepend the slot's instruction line to a doc that predates it.

    The renamed legacy logs are the reason: 60 of them in one consumer, and a
    migration that leaves 60 hand-edits behind is the hand-migration this
    scaffolder exists to avoid. The prepend is additive and reported — no
    existing byte moves except by one line.

    Whether it CAN be written is settled in the pre-pass, not here: a
    `PermissionError` out of this call used to escape as a traceback with the
    grain half-filled behind it.
    """
    want = _header_wanted(path, slot)
    if not want:
        return
    try:
        body = model.read_raw(path)
    except (OSError, UnicodeDecodeError):
        return
    eol = '\r\n' if '\r\n' in body else '\n'
    model.write_raw(path, f'{want}{eol}{eol}{body}')
    actions.append(('restored the header line of', path))


def scaffold(cfg: model.PmConfig, kind: str, gdir: Path,
             values: dict[str, str]) -> list[tuple[str, Path]]:
    """Fill every canonical slot of one grain dir. IDEMPOTENT, and never
    clobbers: an existing slot is left byte-identical, and a slot present under
    another CASE is renamed rather than written past.

    This is how a consumer migrates. A tree with 22 milestones and 136 features
    cannot be hand-shaped, and a scaffolder that refuses on an existing grain
    would leave hand-shaping as the only path.

    `review.md` is scaffolded only while the grain is OPEN: minting the
    transient slot on a `done` grain would hand D11 a finding the scaffolder
    itself created.
    """
    file_slots = (model.MILESTONE_FILE_SLOTS if kind == 'milestone'
                  else model.FEATURE_FILE_SLOTS)
    dir_slots = (model.MILESTONE_DIR_SLOTS if kind == 'milestone'
                 else model.FEATURE_DIR_SLOTS)
    actions: list[tuple[str, Path]] = []
    # The grain DIRECTORY is the first byte this verb writes, and it was the
    # last unguarded one: a name the filesystem will not take (`OSError: File
    # name too long`) and an unwritable `<roadmap>/` both came out as a
    # traceback under exit 1 — the code a consumer's pre-push hook reads as
    # "drift found", so the stack trace lied in both directions. Nothing has
    # been written when this fails, so the refusal can say so and mean it.
    try:
        gdir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise ScaffoldRefused(
            f'{cfg.rel(gdir)}/ could not be created ({err}) — nothing was '
            f'written; shorten the id or name, or make {cfg.rel(gdir.parent)}/ '
            f'writable, and re-run') from err

    # Resolve every case-variant FIRST, so the status read below and the writes
    # after it both see the canonical names.
    #
    # Every refusal for the WHOLE grain is raised before the first rename runs.
    # Deciding slot-by-slot inside the moving loop meant an earlier slot's
    # rename was already on disk — and, through `git mv --force`, already in the
    # INDEX — while the message said "nothing was written". Rule 3: a write verb
    # refuses whole or not at all. The staged half is the worse harm of the two:
    # on a shared tree it rides out on the next `git commit` under someone
    # else's message, which is exactly what a consumer's commit hook exists to
    # stop.
    entries = model.dir_entries(gdir)
    renames: list[tuple[str, str]] = []
    for slot in file_slots:
        variants = model.case_variants(entries, slot)
        # A DIRECTORY or a SYMLINK is refused under EVERY spelling, not only the
        # canonical one. `case_variants` reads names, not kinds, so a variant
        # DIRECTORY was queued as a rename, renamed, and then opened as a file:
        # an `IsADirectoryError` traceback with the move already done. And a
        # symlinked slot is a slot whose bytes live somewhere else — following
        # it would let a verb asked to fill THIS grain rewrite a file outside it.
        for name in (slot, *variants):
            if name not in entries:
                continue
            # The LINK before the kind. `dir_entries` classifies with
            # `is_dir()`, which follows the link, so a symlink pointing at a
            # directory read as 'dir' and got the DIRECTORY refusal: correctly
            # refused, but told to "move the directory aside" when the thing in
            # the grain is a link and the directory is somewhere else entirely.
            if (gdir / name).is_symlink():
                raise ScaffoldRefused(
                    f'{cfg.rel(gdir / name)} is a SYMLINK to '
                    f'{os.readlink(gdir / name)} — the scaffolder writes inside '
                    f'the grain it was asked to fill and does not follow a link '
                    f'out of it; nothing was written; replace it with the real '
                    f'file')
            if entries[name] == 'dir':
                # Refused, not crashed: exit 1 is reserved for findings, so a
                # traceback out of here reads to a consumer's hook as "drift
                # found".
                raise ScaffoldRefused(
                    f'{cfg.rel(gdir / name)} is a DIRECTORY and {slot} is a '
                    f'file slot — nothing was written; move it aside')
        if entries.get(slot) == 'file':
            continue
        if len(variants) > 1:
            raise ScaffoldRefused(
                f'{cfg.rel(gdir)}/ holds {len(variants)} spellings of {slot} '
                f'({", ".join(variants)}) — nothing was written; keep one')
        if variants:
            squat = TEMP_RENAME_SUFFIX.format(name=variants[0])
            if squat in entries:
                raise ScaffoldRefused(
                    f'{cfg.rel(gdir / squat)} is in the way of the '
                    f'{variants[0]} -> {slot} rename — nothing was written; '
                    f'move it aside')
            renames.append((variants[0], slot))

    # A rename writes the DIRECTORY, not the file, and the two permissions are
    # independent: a 0555 grain dir holding a 0644 decisions.md passes every
    # per-file check below and then fails inside `os.rename`. Directory
    # writability is trivially inspectable, so it is inspected here, where a
    # refusal is still whole-or-nothing.
    if renames and not os.access(gdir, os.W_OK):
        under = ', '.join(f'{variant} -> {slot}' for variant, slot in renames)
        raise ScaffoldRefused(
            f'{cfg.rel(gdir)}/ needs {len(renames)} case rename(s) ({under}) '
            f'and the DIRECTORY is not writable — a writable file in it proves '
            f'nothing, the rename writes the directory; nothing was written, '
            f'make it writable and re-run')

    # What the fill phase will DO, decided here too, because a refusal raised
    # after the first `write` is a refusal that already changed the tree. Both
    # halves are inspectable now: every template the grain will need is loaded
    # and DECODED (a latin-1 byte in a project's `template_dir` used to escape
    # as `UnicodeDecodeError` two slots in), and every existing doc due a header
    # prepend is proved writable (a read-only legacy `handoff.md` used to escape
    # as `PermissionError` with the remaining slots never created).
    by_slot = {slot: variant for variant, slot in renames}
    grain_slot = f'{kind}.md'
    grain_now = by_slot.get(grain_slot, grain_slot)
    status = (model.field_of(gdir / grain_now, 'status')
              if entries.get(grain_now) == 'file' else '')
    bodies: dict[str, str] = {}
    for slot in file_slots:
        if entries.get(by_slot.get(slot, slot)) == 'file':
            continue
        if slot == model.REVIEW_FILE_NAME and status == 'done':
            continue
        name = model.SLOT_TEMPLATE[slot]
        try:
            bodies[slot] = render(load(cfg, name), values)
        except (OSError, UnicodeDecodeError) as err:
            raise ScaffoldRefused(
                f'the {name} template cannot be read ({err}) — nothing was '
                f'written' + (f'; fix it under {cfg.template_dir}/, or delete '
                              f'it there to fall back to the packaged one'
                              if cfg.template_dir else '')) from err
    for slot in file_slots:
        now = gdir / by_slot.get(slot, slot)
        if slot in bodies or entries.get(now.name) != 'file':
            continue
        want = _header_wanted(now, slot)
        if want and not os.access(now, os.W_OK):
            raise ScaffoldRefused(
                f'{cfg.rel(now)} is missing its header line and is not '
                f'writable — nothing was written; make it writable, or prepend '
                f'the line yourself: {want!r}')

    landed: list[tuple[str, str, bool]] = []
    for variant, slot in renames:
        try:
            staged = _rename_case(cfg, gdir / variant, gdir / slot)
        except ScaffoldRefused as err:
            # git refusing one `mv --force` cannot be inspected for in advance.
            # What CAN be guaranteed is that the message stops claiming nothing
            # happened once something has — and says WHICH half happened: an
            # operator told to unstage a worktree-only rename goes to a `git
            # status` that shows nothing and cannot act on the advice at all.
            #
            # `_rename_case` states what became of the file IT was moving, and
            # this adds what became of the ones before it. Neither half claims
            # anything about the other, which is how the composed sentence stops
            # saying "nothing was written" and "1 earlier rename already landed"
            # at the same time.
            if not landed:
                raise
            moved = ', '.join(
                f'{v} -> {s} ({"staged by git mv" if g else "on disk, staged nowhere"})'
                for v, s, g in landed)
            raise ScaffoldRefused(
                f'{err} — NOTE: {len(landed)} earlier rename(s) in '
                f'{cfg.rel(gdir)}/ already landed: {moved}; undo or finish '
                f'them before re-running') from err
        landed.append((variant, slot, staged))
        actions.append((f'renamed {variant} ->', gdir / slot))
    entries = model.dir_entries(gdir)

    # Whatever is left is a real write, and a real write can still fail on
    # something no listing could show (a disk that fills, a mode changed under
    # us). It becomes a REFUSAL naming what already landed, so exit 1 always
    # reads as a finding a consumer's hook can print, never as a stack trace.
    try:
        for slot in file_slots:
            if slot in bodies:
                write(gdir / slot, bodies[slot])
                actions.append(('created', gdir / slot))
            elif entries.get(slot) == 'file':
                _fill_header(gdir / slot, slot, actions)
        for slot in dir_slots:
            if slot in entries:
                continue
            (gdir / slot).mkdir(exist_ok=True)
            actions.append(('created', gdir / slot))
    except (OSError, UnicodeDecodeError) as err:
        did = '; '.join(f'{what} {cfg.rel(p)}' for what, p in actions)
        raise ScaffoldRefused(
            f'{cfg.rel(gdir)}/ could not be filled ({err}) — this one could not '
            f'be decided in advance, so the grain is PART-FILLED: '
            + (did or 'nothing had been written yet')
            + '; fix it and re-run, which fills only the gaps') from err
    return actions


def install(cfg: model.PmConfig, force: bool = False) -> tuple[list[Path],
                                                              list[tuple[str, str]]]:
    """Copy the packaged templates into `template_dir`. (written, case variants).

    EXACT names, from a listing, exactly as `load` reads them — `Path.is_file()`
    on macOS answers `decisions.md` with a leftover `DECISIONS.md`, and the
    install would then decline to write the very name `load` looks for: the
    project's customised template is silently ignored in favour of the packaged
    one, and the consumer cannot even SEE the new name to port it to. A variant
    already present is REPORTED, never skipped in silence — this package's own
    `load` rejects an unknown config key on the same grounds, that a thing which
    silently does nothing is worse than one that errors.

    Reported and NOT written past, `--force` included: on a case-insensitive
    filesystem `open('decisions.md', 'w')` truncates the `DECISIONS.md` sitting
    there, so an install that "helpfully" minted the new name would destroy the
    customisation it exists to preserve. The consumer renames it, then re-runs.
    """
    if not cfg.template_dir:
        raise MissingTemplate(
            'no [pm] template_dir configured — set one before installing '
            'templates to edit (e.g. template_dir = "pm/templates")')
    out: list[Path] = []
    variants: list[tuple[str, str]] = []
    target_dir = cfg.root / cfg.template_dir
    entries = model.dir_entries(target_dir)
    for name in (*GRAINS, *DOCS):
        text = _packaged(name)
        if text is None:
            continue
        slot = f'{name}.md'
        others = model.case_variants(entries, slot)
        if others:
            variants.extend((other, slot) for other in others)
            continue
        if entries.get(slot) == 'file' and not force:
            continue
        target = target_dir / slot
        write(target, text)
        out.append(target)
    return out, variants
