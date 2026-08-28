"""model.py — the PM-tree invariants, single-sourced.

Everything the transition CLI and the drift gate must agree on byte-for-byte:
the status vocabularies + legal transition graphs, the id <-> filesystem-path
convention, frontmatter read/write, THE definition of "a feature has a review
record", and the drift predicates. Two readers, one definition — the gate and
the tool cannot describe "reviewed" or "drift" differently.

Config: `[pm]` in the consuming repo's devkit.toml. Every key has a stock
default, so a repo with no devkit.toml behaves identically to one declaring the
defaults. The defaults are the STRICT graph: the story terminal is `review`
(`done` comes only from the feature cascade, closing the review-skip hole) and
the milestone machine has no `review` state (nothing transitions into one).

    [pm]
    roadmap_dir  = "pm/roadmap"    # the tree, relative to the repo root
    review_dir   = "docs/reviews"  # where review records live
    review_min_content_bytes = 20  # anti-rubber-stamp floor (non-whitespace)
    review_slug_fallback = false   # also accept <review_dir>/<feature-slug>*.md
    story_ordinal_prefix = false   # also resolve stories/NN-<slug>.md
    milestone_states      = [...]  # vocabulary overrides
    feature_states        = [...]
    story_states          = [...]
    milestone_transitions = [...]  # "from->to" edges
    feature_transitions   = [...]
    story_transitions     = [...]
    checks = ["D1","D2","D3","D4","D5","D6","D7"]   # which drift rules run
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.project import load_config, repo_root

# --- stock policy -------------------------------------------------------------
# The story terminal is `review`: there is deliberately NO story `*->done` edge,
# because `done` is reached ONLY by the feature-review cascade. A per-story done
# flip is the latent review-skip hole this graph closes.
DEFAULT_MILESTONE_STATES = ('planning', 'ready', 'building', 'done')
DEFAULT_FEATURE_STATES = ('planning', 'ready', 'building', 'review', 'done')
DEFAULT_STORY_STATES = ('todo', 'wip', 'review', 'done', 'blocked')

DEFAULT_MILESTONE_TRANSITIONS = ('planning->ready', 'ready->building', 'building->done')
DEFAULT_FEATURE_TRANSITIONS = (
    'planning->ready', 'ready->building', 'building->review', 'review->done')
# todo->review is the sanctioned no-build edge: a doc/decision story with
# nothing to build reaches review without passing through wip.
DEFAULT_STORY_TRANSITIONS = ('todo->wip', 'wip->review', 'todo->review')

DEFAULT_CHECKS = ('D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7')

ARCHIVE_DIR_NAME = 'zz_archive'


@dataclass(frozen=True)
class PmConfig:
    root: Path
    roadmap_dir: str = 'pm/roadmap'
    review_dir: str = 'docs/reviews'
    review_min_content_bytes: int = 20
    review_slug_fallback: bool = False
    story_ordinal_prefix: bool = False
    milestone_states: tuple[str, ...] = DEFAULT_MILESTONE_STATES
    feature_states: tuple[str, ...] = DEFAULT_FEATURE_STATES
    story_states: tuple[str, ...] = DEFAULT_STORY_STATES
    milestone_transitions: tuple[str, ...] = DEFAULT_MILESTONE_TRANSITIONS
    feature_transitions: tuple[str, ...] = DEFAULT_FEATURE_TRANSITIONS
    story_transitions: tuple[str, ...] = DEFAULT_STORY_TRANSITIONS
    checks: tuple[str, ...] = DEFAULT_CHECKS

    @property
    def roadmap(self) -> Path:
        return self.root / self.roadmap_dir

    def rel(self, path: Path) -> str:
        """Repo-relative display path (findings name a path a human can open)."""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def load(root: Path | None = None) -> PmConfig:
    """Build the config from `[pm]` in devkit.toml, defaults where unset."""
    base = root if root is not None else repo_root()
    section = load_config().get('pm', {}) if root is None else {}

    def tup(key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
        val = section.get(key)
        return tuple(str(v) for v in val) if val else fallback

    return PmConfig(
        root=base,
        roadmap_dir=str(section.get('roadmap_dir', 'pm/roadmap')),
        review_dir=str(section.get('review_dir', 'docs/reviews')),
        review_min_content_bytes=int(section.get('review_min_content_bytes', 20)),
        review_slug_fallback=bool(section.get('review_slug_fallback', False)),
        story_ordinal_prefix=bool(section.get('story_ordinal_prefix', False)),
        milestone_states=tup('milestone_states', DEFAULT_MILESTONE_STATES),
        feature_states=tup('feature_states', DEFAULT_FEATURE_STATES),
        story_states=tup('story_states', DEFAULT_STORY_STATES),
        milestone_transitions=tup('milestone_transitions', DEFAULT_MILESTONE_TRANSITIONS),
        feature_transitions=tup('feature_transitions', DEFAULT_FEATURE_TRANSITIONS),
        story_transitions=tup('story_transitions', DEFAULT_STORY_TRANSITIONS),
        checks=tup('checks', DEFAULT_CHECKS),
    )


def transition_legal(graph: tuple[str, ...], src: str, dst: str) -> bool:
    """True if src->dst is permitted, or src == dst (idempotent no-op)."""
    return src == dst or f'{src}->{dst}' in graph


# --- frontmatter --------------------------------------------------------------
_FENCE = re.compile(r'^---[ \t]*$')


def _fence_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Index of the opening and closing `---` of the leading block, or None."""
    if not lines or not _FENCE.match(lines[0]):
        return None
    for i in range(1, len(lines)):
        if _FENCE.match(lines[i]):
            return 0, i
    return None


def field_of(path: Path, key: str) -> str:
    """Scalar value of `key` inside the LEADING frontmatter block, or ''.

    Scoped to the fence on purpose: a `status:` mention in the prose body must
    never leak out and be mistaken for the grain's status.
    """
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return ''
    bounds = _fence_bounds(lines)
    if bounds is None:
        return ''
    for line in lines[bounds[0] + 1:bounds[1]]:
        if line.startswith(f'{key}:'):
            return line[len(key) + 1:].strip()
    return ''


def unquote(value: str) -> str:
    """Strip the quotes a milestone id carries (`id: "0.28"` -> `0.28`)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def set_field(path: Path, key: str, value: str) -> bool:
    """Set-or-insert a frontmatter scalar, preserving every other byte.

    Rewrites the key in place if present, else inserts it just before the
    closing fence. Returns False WITHOUT writing when the file has no leading
    frontmatter block — a malformed file has nowhere to put the key, and
    silently dropping it is the failure mode this refuses to have.
    """
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return False
    lines = text.splitlines()
    bounds = _fence_bounds(lines)
    if bounds is None:
        return False
    open_i, close_i = bounds
    for i in range(open_i + 1, close_i):
        if lines[i].startswith(f'{key}:'):
            lines[i] = f'{key}: {value}'
            break
    else:
        lines.insert(close_i, f'{key}: {value}')
    out = '\n'.join(lines)
    if text.endswith('\n'):
        out += '\n'
    path.write_text(out, encoding='utf-8')
    return True


# --- id <-> path --------------------------------------------------------------
# Milestone dirs carry a human suffix after the version (`0.28-chronicle`); the
# id is just the version. Resolution globs the version prefix, active tree
# first, then the archive.
def milestone_dir(cfg: PmConfig, mid: str) -> Path | None:
    for base in (cfg.roadmap, cfg.roadmap / ARCHIVE_DIR_NAME):
        if not base.is_dir():
            continue
        for d in sorted(base.glob(f'{mid}-*')):
            if d.is_dir():
                return d
    return None


def milestone_file(cfg: PmConfig, mid: str) -> Path | None:
    d = milestone_dir(cfg, mid)
    if d is None:
        return None
    f = d / 'milestone.md'
    return f if f.is_file() else None


def feature_dir(cfg: PmConfig, fid: str) -> Path | None:
    mid, _, slug = fid.partition('/')
    if not slug:
        return None
    d = milestone_dir(cfg, mid)
    if d is None:
        return None
    fdir = d / 'features' / slug
    return fdir if fdir.is_dir() else None


def feature_file(cfg: PmConfig, fid: str) -> Path | None:
    d = feature_dir(cfg, fid)
    if d is None:
        return None
    f = d / 'feature.md'
    return f if f.is_file() else None


def story_file(cfg: PmConfig, sid: str) -> Path | None:
    """Resolve <milestone>/<feature-slug>/<story-slug> to its .md.

    With `story_ordinal_prefix`, a story FILE may carry an ordering prefix
    (`01-the-state.md`) that its ID does not — the number sequences the build,
    it is not identity. Exact stem first, then the prefixed form. Two files
    claiming one id is an authoring error, so that REFUSES rather than silently
    taking the first.
    """
    mid, _, rest = sid.partition('/')
    fslug, _, sslug = rest.partition('/')
    if not fslug or not sslug:
        return None
    fdir = feature_dir(cfg, f'{mid}/{fslug}')
    if fdir is None:
        return None
    exact = fdir / 'stories' / f'{sslug}.md'
    if exact.is_file():
        return exact
    if cfg.story_ordinal_prefix:
        matches = sorted(p for p in (fdir / 'stories').glob(f'[0-9][0-9]-{sslug}.md')
                         if p.is_file())
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousStory(sid, [cfg.rel(p) for p in matches])
    return None


class AmbiguousStory(Exception):
    """Two files claim one story id — an authoring error, never auto-resolved."""

    def __init__(self, sid: str, paths: list[str]) -> None:
        super().__init__(f'story id {sid!r} matches {len(paths)} files: {", ".join(paths)}')
        self.sid = sid
        self.paths = paths


# --- children -----------------------------------------------------------------
def milestone_dirs(cfg: PmConfig, include_archive: bool = False) -> list[Path]:
    """Milestone dirs in the ACTIVE tree (archived ones predate the schema)."""
    if not cfg.roadmap.is_dir():
        return []
    out = [d for d in sorted(cfg.roadmap.iterdir())
           if d.is_dir() and d.name != ARCHIVE_DIR_NAME and (d / 'milestone.md').is_file()]
    if include_archive:
        arch = cfg.roadmap / ARCHIVE_DIR_NAME
        if arch.is_dir():
            out += [d for d in sorted(arch.iterdir())
                    if d.is_dir() and (d / 'milestone.md').is_file()]
    return out


def feature_files(mdir: Path) -> list[Path]:
    fdir = mdir / 'features'
    if not fdir.is_dir():
        return []
    return [d / 'feature.md' for d in sorted(fdir.iterdir()) if (d / 'feature.md').is_file()]


def story_files(ffile: Path) -> list[Path]:
    sdir = ffile.parent / 'stories'
    if not sdir.is_dir():
        return []
    return [p for p in sorted(sdir.glob('*.md')) if p.is_file()]


# --- THE review-record definition --------------------------------------------
def record_is_substantive(cfg: PmConfig, path: Path) -> bool:
    """True if the file exists and carries enough NON-WHITESPACE content.

    The anti-rubber-stamp. The bar is deliberately LOW — a one-line close is a
    valid review — so this rejects emptiness, not brevity: a pointer resolving
    to a missing file, a 0-byte file, or a whitespace/stub doc is not a review.
    """
    if not path.is_file():
        return False
    try:
        body = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return False
    return len(''.join(body.split())) >= cfg.review_min_content_bytes


def review_record_for(cfg: PmConfig, fid: str) -> str | None:
    """The feature's resolved review record, or None if it has none.

    The `reviewed:` frontmatter pointer is the mechanism. `review_slug_fallback`
    additionally accepts `<review_dir>/<feature-slug>*.md` for projects that
    name records after the slug; projects with ordinal-named records leave it
    off, because there the glob resolves nothing and would be a silent no-op
    masquerading as a fallback.
    """
    ffile = feature_file(cfg, fid)
    if ffile is None:
        return None
    pointer = unquote(field_of(ffile, 'reviewed'))
    if pointer and pointer != 'null':
        target = Path(pointer) if pointer.startswith('/') else cfg.root / pointer
        if record_is_substantive(cfg, target):
            return pointer
    if cfg.review_slug_fallback:
        slug = fid.partition('/')[2]
        rdir = cfg.root / cfg.review_dir
        if slug and rdir.is_dir():
            for cand in sorted(rdir.glob(f'{slug}*.md')):
                if record_is_substantive(cfg, cand):
                    return cfg.rel(cand)
    return None


# --- shared drift predicates --------------------------------------------------
# THE definitions of the feature-grain drift rules. Both `pm status` and the
# `check pm` gate call these, so the report and the gate cannot diverge. Each
# returns a one-line reason, or None when clean.
def drift_done_no_record(cfg: PmConfig, fid: str, fstat: str) -> str | None:
    """D1 — a `done` feature with no substantive review record."""
    if fstat != 'done' or review_record_for(cfg, fid) is not None:
        return None
    return 'done w/o review record'


def drift_stalled(fstat: str, done_n: int, total: int) -> str | None:
    """D2 — every story done, but the feature never advanced (a forgotten flip).

    A feature at `review`/`done` with all-done stories is the valid closed
    state, not drift.
    """
    if total == 0 or done_n != total:
        return None
    if fstat in ('planning', 'ready', 'building'):
        return f'all stories done, feature still {fstat}'
    return None


@dataclass
class FeatureView:
    """One feature plus the tallies every reader needs. Read once, reuse."""
    fid: str
    status: str
    phase: str
    path: Path
    stories: list[Path] = field(default_factory=list)
    done_n: int = 0

    @property
    def total(self) -> int:
        return len(self.stories)


def read_feature(ffile: Path) -> FeatureView:
    view = FeatureView(
        fid=unquote(field_of(ffile, 'id')),
        status=field_of(ffile, 'status'),
        phase=unquote(field_of(ffile, 'phase')),
        path=ffile,
        stories=story_files(ffile),
    )
    view.done_n = sum(1 for s in view.stories if field_of(s, 'status') == 'done')
    return view
