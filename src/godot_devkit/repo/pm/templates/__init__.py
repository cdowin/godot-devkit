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

from godot_devkit.core import apply
from godot_devkit.repo.pm import model

# grain -> template filename. The shared docs are addressed by their SLOT name
# minus the extension, so `decisions.md` is minted by `decisions.md` and there
# is no mapping table to keep in sync.
GRAINS = ('milestone', 'feature', 'story', 'bug')
DOCS = ('handoff', 'decisions')


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
    """Create a grain file, preserving the template's own line endings.

    Through `core.apply`, which owns every mutation in this package. The
    refusals this module raises are named in slots and templates rather than
    paths, so the plan is applied with `decide=False` and the domain wording
    above stays exactly what a consumer's hook prints.
    """
    apply.raise_on_error(apply.write(path, text))


class ScaffoldRefused(Exception):
    """The scaffolder cannot guarantee a correct result, so it did nothing."""


def _header_wanted(path: Path, slot: str) -> str:
    """The instruction line this doc is MISSING, or '' when it needs none.

    A file already opening with SOME known instruction line needs none, so a
    future wording change can never stack two headers — a doc that has one is
    left exactly as its author wrote it.
    """
    want = model.SLOT_HEADER.get(slot)
    if want is None:
        return ''
    got = model.header_of(path)
    return '' if got == want or got in set(model.SLOT_HEADER.values()) else want


def _fill_header(path: Path, slot: str, actions: list[tuple[str, Path]]) -> None:
    """Prepend the slot's instruction line to a doc that predates it.

    Legacy logs are the reason: 60 of them in one consumer, and a migration
    that leaves 60 hand-edits behind is the hand-migration this scaffolder
    exists to avoid. The prepend is additive and reported — no existing byte
    moves except by one line.

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
    """Fill one grain dir's REQUIRED slots. IDEMPOTENT, and never clobbers: an
    existing slot is left byte-identical, and a slot present under another CASE
    is REFUSED rather than written past.

    Re-running over an existing grain fills only the gaps. A tree with 22
    milestones and 136 features cannot be hand-shaped, and a scaffolder that
    refuses on an existing grain would leave hand-shaping as the only path.

    WHAT IT DOES NOT MINT: a shared doc, or a directory. `handoff.md`,
    `decisions.md` and `review.md` appear on first write — a decisions.md the
    moment `pm decide` records one, the other two when a human writes one;
    scaffolding them empty put 204 files and ~1,900 lines into one consumer's
    tree, a quarter of it, minted by the verb that exists to stop sprawl. The
    directory slots went the same way and worse: git stores no empty directory,
    so 158 minted `design/` dirs left 11 with anything in them. `apply` creates
    a parent on the way to a write, so `stories/` appears when the first story
    is written into it.

    They stay MANAGED, which is the other half: an existing doc that lost its
    instruction header still gets it back. Creation-from-nothing is what it
    stops doing.
    """
    file_slots = (model.MILESTONE_FILE_SLOTS if kind == 'milestone'
                  else model.FEATURE_FILE_SLOTS)
    # Renamed and header-repaired when PRESENT, never created when absent.
    managed = file_slots + (model.MILESTONE_OPTIONAL_SLOTS if kind == 'milestone'
                            else model.FEATURE_OPTIONAL_SLOTS)
    actions: list[tuple[str, Path]] = []
    # The grain DIRECTORY is the first byte this verb writes, and it was the
    # last unguarded one: a name the filesystem will not take (`OSError: File
    # name too long`) and an unwritable `<roadmap>/` both came out as a
    # traceback under exit 1 — the code a consumer's pre-push hook reads as
    # "drift found", so the stack trace lied in both directions. Nothing has
    # been written when this fails, so the refusal can say so and mean it.
    try:
        apply.raise_on_error(apply.make_dir(gdir))
    except OSError as err:
        raise ScaffoldRefused(
            f'{cfg.rel(gdir)}/ could not be created ({err}) — nothing was '
            f'written; shorten the id or name, or make {cfg.rel(gdir.parent)}/ '
            f'writable, and re-run') from err

    # Every refusal for the WHOLE grain is raised before the first slot write.
    # Rule 3: a write verb refuses whole or not at all.
    #
    # A slot present under another CASE is refused, never written past and
    # never renamed — the uppercase->lowercase migration is complete in every
    # consumer, so a variant here is a leftover to name, not work to finish.
    # Writing the canonical name anyway would mint a twin beside it on a
    # case-sensitive filesystem and TRUNCATE the legacy bytes on an
    # insensitive one; both are worse than stopping.
    entries = model.dir_entries(gdir)
    for slot in managed:
        variants = model.case_variants(entries, slot)
        if variants:
            raise ScaffoldRefused(
                f'{cfg.rel(gdir)}/ holds {", ".join(variants)} where this '
                f'package expects {slot} — nothing was written; rename it '
                f'yourself (`git mv --force {cfg.rel(gdir / variants[0])} '
                f'{cfg.rel(gdir / slot)}`), then re-run')
        if slot not in entries:
            continue
        # The LINK before the kind. `dir_entries` classifies with `is_dir()`,
        # which follows the link, so a symlink pointing at a directory read as
        # 'dir' and got the DIRECTORY refusal: correctly refused, but told to
        # "move the directory aside" when the thing in the grain is a link and
        # the directory is somewhere else entirely. A symlinked slot is a slot
        # whose bytes live somewhere else — following it would let a verb
        # asked to fill THIS grain rewrite a file outside it.
        if (gdir / slot).is_symlink():
            raise ScaffoldRefused(
                f'{cfg.rel(gdir / slot)} is a SYMLINK to '
                f'{os.readlink(gdir / slot)} — the scaffolder writes inside '
                f'the grain it was asked to fill and does not follow a link '
                f'out of it; nothing was written; replace it with the real '
                f'file')
        if entries[slot] == 'dir':
            # Refused, not crashed: exit 1 is reserved for findings, so a
            # traceback out of here reads to a consumer's hook as "drift
            # found".
            raise ScaffoldRefused(
                f'{cfg.rel(gdir / slot)} is a DIRECTORY and {slot} is a '
                f'file slot — nothing was written; move it aside')

    # What the fill phase will DO, decided here too, because a refusal raised
    # after the first `write` is a refusal that already changed the tree. Both
    # halves are inspectable now: every template the grain will need is loaded
    # and DECODED (a latin-1 byte in a project's `template_dir` used to escape
    # as `UnicodeDecodeError` two slots in), and every existing doc due a header
    # prepend is proved writable (a read-only legacy `handoff.md` used to escape
    # as `PermissionError` with the remaining slots never created).
    bodies: dict[str, str] = {}
    for slot in file_slots:
        if entries.get(slot) == 'file':
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
    for slot in managed:
        now = gdir / slot
        if slot in bodies or entries.get(slot) != 'file':
            continue
        want = _header_wanted(now, slot)
        if want and not os.access(now, os.W_OK):
            raise ScaffoldRefused(
                f'{cfg.rel(now)} is missing its header line and is not '
                f'writable — nothing was written; make it writable, or prepend '
                f'the line yourself: {want!r}')

    # Whatever is left is a real write, and a real write can still fail on
    # something no listing could show (a disk that fills, a mode changed under
    # us). It becomes a REFUSAL naming what already landed, so exit 1 always
    # reads as a finding a consumer's hook can print, never as a stack trace.
    try:
        for slot in managed:
            if slot in bodies:
                write(gdir / slot, bodies[slot])
                actions.append(('created', gdir / slot))
            elif entries.get(slot) == 'file':
                _fill_header(gdir / slot, slot, actions)
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
