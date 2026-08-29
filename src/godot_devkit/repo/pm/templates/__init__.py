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

from importlib import resources
from pathlib import Path

from godot_devkit.repo.pm import model

# grain -> template filename. The shared docs are addressed by their SLOT name
# minus the extension, so `decisions.md` is minted by `decisions.md` and there
# is no mapping table to keep in sync.
GRAINS = ('milestone', 'feature', 'story', 'bug')
DOCS = ('handoff', 'decisions', 'review')


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


def _rename_case(cfg: model.PmConfig, old: Path, new: Path) -> None:
    """`DECISIONS.md` -> `decisions.md`, recorded by GIT when git tracks it.

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
    """
    done, why = model.git_rename(cfg.root, old, new)
    if done:
        return
    if why:
        raise ScaffoldRefused(
            f'git tracks {cfg.rel(old)} and would not rename it to {new.name} '
            f'({why}) — nothing was written; run `git mv --force '
            f'{cfg.rel(old)} {cfg.rel(new)}` yourself, then re-run')
    tmp = old.with_name(f'{old.name}.pm-case-rename')
    if tmp.exists():
        raise ScaffoldRefused(f'{cfg.rel(tmp)} is in the way of the {old.name} '
                              f'-> {new.name} rename — move it aside')
    old.rename(tmp)
    tmp.rename(new)


def _fill_header(path: Path, slot: str, actions: list[tuple[str, Path]]) -> None:
    """Prepend the slot's instruction line to a doc that predates it.

    The renamed legacy logs are the reason: 60 of them in one consumer, and a
    migration that leaves 60 hand-edits behind is the hand-migration this
    scaffolder exists to avoid. The prepend is additive and reported — no
    existing byte moves except by one line.

    A file already opening with SOME known instruction line is left alone, so a
    future wording change can never stack two headers; D13 reports the mismatch
    and a human decides.
    """
    want = model.SLOT_HEADER.get(slot)
    if want is None:
        return
    got = model.header_of(path)
    if got == want or got in set(model.SLOT_HEADER.values()):
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
    gdir.mkdir(parents=True, exist_ok=True)

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
        if entries.get(slot) == 'file':
            continue
        if entries.get(slot) == 'dir':
            # Refused, not crashed: exit 1 is reserved for findings, so a
            # traceback out of here reads to a consumer's hook as "drift found".
            raise ScaffoldRefused(
                f'{cfg.rel(gdir / slot)} is a DIRECTORY and {slot} is a file '
                f'slot — nothing was written; move it aside')
        variants = model.case_variants(entries, slot)
        if len(variants) > 1:
            raise ScaffoldRefused(
                f'{cfg.rel(gdir)}/ holds {len(variants)} spellings of {slot} '
                f'({", ".join(variants)}) — nothing was written; keep one')
        if variants:
            renames.append((variants[0], slot))

    for i, (variant, slot) in enumerate(renames):
        try:
            _rename_case(cfg, gdir / variant, gdir / slot)
        except ScaffoldRefused as err:
            # git refusing one `mv --force` cannot be inspected for in advance.
            # What CAN be guaranteed is that the message stops claiming nothing
            # happened once something has: an operator who is not told about a
            # staged rename cannot undo it.
            if not i:
                raise
            moved = ', '.join(f'{v} -> {s}' for v, s in renames[:i])
            raise ScaffoldRefused(
                f'{err} — NOTE: {i} earlier rename(s) in '
                f'{cfg.rel(gdir)}/ already landed and are staged ({moved}); '
                f'unstage or finish them before re-running') from err
        actions.append((f'renamed {variant} ->', gdir / slot))
    entries = model.dir_entries(gdir)

    grain_slot = f'{kind}.md'
    status = (model.field_of(gdir / grain_slot, 'status')
              if entries.get(grain_slot) == 'file' else '')
    for slot in file_slots:
        if entries.get(slot) == 'file':
            _fill_header(gdir / slot, slot, actions)
            continue
        if slot == model.REVIEW_FILE_NAME and status == 'done':
            continue
        body = render(load(cfg, model.SLOT_TEMPLATE[slot]), values)
        write(gdir / slot, body)
        actions.append(('created', gdir / slot))
    for slot in dir_slots:
        if slot in entries:
            continue
        (gdir / slot).mkdir(exist_ok=True)
        actions.append(('created', gdir / slot))
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
