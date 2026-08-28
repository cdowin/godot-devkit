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

from godot_devkit.pm import model

# grain -> template filename. HANDOFF/DECISIONS are milestone-scoped docs rather
# than grains, so they are addressed by name.
GRAINS = ('milestone', 'feature', 'story', 'bug')
DOCS = ('HANDOFF', 'DECISIONS')


class MissingTemplate(Exception):
    """No packaged or project template by that name."""


def _packaged(name: str) -> str | None:
    try:
        return (resources.files('godot_devkit.pm.templates')
                .joinpath(f'{name}.md').read_text(encoding='utf-8'))
    except (FileNotFoundError, ModuleNotFoundError):
        return None


def load(cfg: model.PmConfig, name: str) -> str:
    """The template text for `name`, project override winning."""
    if cfg.template_dir:
        local = cfg.root / cfg.template_dir / f'{name}.md'
        if local.is_file():
            with local.open('r', encoding='utf-8', newline='') as fh:
                return fh.read()
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


def install(cfg: model.PmConfig, force: bool = False) -> list[Path]:
    """Copy the packaged templates into the project's `template_dir` to edit."""
    if not cfg.template_dir:
        raise MissingTemplate(
            'no [pm] template_dir configured — set one before installing '
            'templates to edit (e.g. template_dir = "pm/templates")')
    out = []
    target_dir = cfg.root / cfg.template_dir
    for name in (*GRAINS, *DOCS):
        text = _packaged(name)
        if text is None:
            continue
        target = target_dir / f'{name}.md'
        if target.is_file() and not force:
            continue
        write(target, text)
        out.append(target)
    return out
