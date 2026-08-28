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

from godot_devkit.core.project import (ConfigError, config_section, flag, number,
                                  repo_root, str_tuple, text)

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

# D8-D10 encode the branch-per-milestone / bump-at-start flow. They are OFF by
# default: a project that ships from the trunk and bumps at close is not
# drifting, it is running a different (valid) flow, and a gate that fails it
# would be lying. Opt in with `[pm] checks`.
DEFAULT_CHECKS = ('D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7',
                  'V1', 'V2', 'V3', 'V4', 'V5', 'V6')
FLOW_CHECKS = ('D8', 'D9', 'D10')
# Structural/referential integrity. ON by default: a tree that does not satisfy
# these is malformed, not merely running a different flow.
VALIDATE_CHECKS = ('V1', 'V2', 'V3', 'V4', 'V5', 'V6')
KNOWN_CHECKS = tuple(dict.fromkeys(DEFAULT_CHECKS + FLOW_CHECKS + VALIDATE_CHECKS))

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
    # D8 only: where the shipped version lives, and the line that carries it.
    template_dir: str = ''
    version_file: str = 'project.godot'
    version_pattern: str = r'^config/version="(.*)"$'
    trunk_branches: tuple[str, ...] = ('staging', 'main')

    @property
    def roadmap(self) -> Path:
        return self.root / self.roadmap_dir

    def rel(self, path: Path) -> str:
        """Repo-relative display path (findings name a path a human can open)."""
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


def load() -> PmConfig:
    """Build the config from `[pm]` in devkit.toml, defaults where unset."""
    sect = config_section('pm')

    def tup(key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
        out = str_tuple(sect, 'pm', key, fallback)
        if not out:
            raise ConfigError(
                f'[pm] {key} is empty — remove the key to take the default '
                f'({" ".join(fallback)}) rather than declaring nothing')
        return out

    checks = tup('checks', DEFAULT_CHECKS)
    unknown = [c for c in checks if c not in KNOWN_CHECKS]
    if unknown:
        # An unknown name is indistinguishable from a disabled rule at runtime,
        # so a typo would quietly narrow the gate. Name it instead.
        raise ConfigError(
            f'[pm] checks names unknown rule(s) {", ".join(unknown)} — '
            f'known rules are {" ".join(KNOWN_CHECKS)}')

    # Compile here, not at use: an invalid regex or a missing capture group is
    # a CONFIG error (exit 2), never a finding (exit 1). Deferring it meant CI
    # read a devkit.toml typo as "PM drift found".
    version_pattern = text(sect, 'pm', 'version_pattern',
                           r'^config/version="(.*)"$')
    try:
        compiled = re.compile(version_pattern)
    except re.error as err:
        raise ConfigError(f'[pm] version_pattern is not a valid regex: {err}') from err
    if compiled.groups < 1:
        raise ConfigError('[pm] version_pattern needs one capture group around '
                          'the version itself')

    # `[pm.scaffold.*]` was retired by template files. Refuse it rather than
    # ignoring it: a config key that silently does nothing is worse than one
    # that errors, because the author believes it took effect.
    if 'scaffold' in sect:
        raise ConfigError(
            '[pm.scaffold.*] was replaced by template FILES — set [pm] '
            'template_dir and run `pm templates` to copy them out, then edit '
            'the markdown (a template can change a grain\'s whole shape, not '
            'just its frontmatter defaults)')

    return PmConfig(
        root=repo_root(),
        roadmap_dir=text(sect, 'pm', 'roadmap_dir', 'pm/roadmap'),
        review_dir=text(sect, 'pm', 'review_dir', 'docs/reviews'),
        review_min_content_bytes=number(sect, 'pm', 'review_min_content_bytes', 20),
        review_slug_fallback=flag(sect, 'pm', 'review_slug_fallback', False),
        story_ordinal_prefix=flag(sect, 'pm', 'story_ordinal_prefix', False),
        milestone_states=tup('milestone_states', DEFAULT_MILESTONE_STATES),
        feature_states=tup('feature_states', DEFAULT_FEATURE_STATES),
        story_states=tup('story_states', DEFAULT_STORY_STATES),
        milestone_transitions=tup('milestone_transitions', DEFAULT_MILESTONE_TRANSITIONS),
        feature_transitions=tup('feature_transitions', DEFAULT_FEATURE_TRANSITIONS),
        story_transitions=tup('story_transitions', DEFAULT_STORY_TRANSITIONS),
        checks=checks,
        template_dir=text(sect, 'pm', 'template_dir', ''),
        version_file=text(sect, 'pm', 'version_file', 'project.godot'),
        version_pattern=version_pattern,
        trunk_branches=tup('trunk_branches', ('staging', 'main')),
    )


def transition_legal(graph: tuple[str, ...], src: str, dst: str) -> bool:
    """True if src->dst is permitted, or src == dst (idempotent no-op)."""
    return src == dst or f'{src}->{dst}' in graph


# --- frontmatter --------------------------------------------------------------
# NOTE the split rule below. `str.splitlines()` breaks on U+2028, U+2029, form
# feed and a lone CR as well as on newlines — so splitlines()+'\n'.join() silently
# rewrites every one of those into LF, and turns a CRLF file into an LF file.
# That is a write verb touching bytes it was not asked to touch (rule 3). Split
# on '\n' ONLY: a trailing '\r' then rides along as part of the line's content
# and is preserved verbatim, and split/join round-trips byte-for-byte.
_FENCE = re.compile(r'^---[ \t]*\r?$')


def _split(text: str) -> list[str]:
    return text.split('\n')


# Path.read_text/write_text apply UNIVERSAL NEWLINE translation: read turns
# every \r\n and lone \r into \n, write turns \n back into os.linesep. So the
# terminators are destroyed before any split logic runs, and a CRLF file
# silently becomes LF on a one-field write. `newline=''` disables both halves
# and hands us the bytes as they are. (Path.read_text only gained a `newline`
# parameter in 3.13; the floor here is 3.11, so open() it is.)
def _read(path: Path) -> str:
    with path.open('r', encoding='utf-8', newline='') as fh:
        return fh.read()


def _write(path: Path, text: str) -> None:
    with path.open('w', encoding='utf-8', newline='') as fh:
        fh.write(text)


def _eol(line: str) -> str:
    """The CR half of a CRLF terminator, so a rewritten line keeps the file's
    convention instead of quietly converting it."""
    return '\r' if line.endswith('\r') else ''


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
        lines = _split(_read(path))
    except (OSError, UnicodeDecodeError):
        return ''
    bounds = _fence_bounds(lines)
    if bounds is None:
        return ''
    for line in lines[bounds[0] + 1:bounds[1]]:
        if line.startswith(f'{key}:'):
            # .strip() also removes the CRLF carriage return.
            return unquote(line[len(key) + 1:].strip())
    return ''


def unquote(value: str) -> str:
    """Strip the quotes a milestone id carries (`id: "0.28"` -> `0.28`)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def set_field(path: Path, key: str, value: str) -> bool:
    """Set-or-insert a frontmatter scalar, preserving every other byte.

    Rewrites the key in place if present, else inserts it just before the
    closing fence. Every other byte in the file — including its line-ending
    convention and any U+2028/form-feed/lone-CR in the body — is preserved.

    Returns False WITHOUT writing when the file has no leading frontmatter
    block (nowhere to put the key) or when the write itself fails. Silently
    dropping the key is the failure mode this refuses to have; the caller turns
    a False into a loud refusal.
    """
    try:
        text = _read(path)
    except (OSError, UnicodeDecodeError):
        return False
    lines = _split(text)
    bounds = _fence_bounds(lines)
    if bounds is None:
        return False
    open_i, close_i = bounds
    for i in range(open_i + 1, close_i):
        if lines[i].startswith(f'{key}:'):
            lines[i] = f'{key}: {value}{_eol(lines[i])}'
            break
    else:
        lines.insert(close_i, f'{key}: {value}{_eol(lines[close_i])}')
    try:
        _write(path, '\n'.join(lines))
    except OSError:
        return False
    return True


# --- id <-> path --------------------------------------------------------------
# Milestone dirs carry a human suffix after the version (`0.28-chronicle`); the
# id is just the version. Resolution globs the version prefix, active tree
# first, then the archive.
# Ids reach glob() as patterns, so `pm milestone ready '*'` would resolve to
# whatever sorted first and transition it. An id is a literal, never a pattern.
_GLOB_CHARS = set('*?[]!')


def id_is_literal(value: str) -> bool:
    return bool(value) and not (_GLOB_CHARS & set(value))


def milestone_dir(cfg: PmConfig, mid: str) -> Path | None:
    if not id_is_literal(mid):
        return None
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
    if not slug or not id_is_literal(slug):
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
    if not fslug or not sslug or not id_is_literal(sslug):
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
def orphan_dirs(cfg: PmConfig) -> list[tuple[Path, str]]:
    """Directories that LOOK like a grain but carry no grain file.

    `milestone_dirs`/`feature_files` filter these out so the rest of the walk
    can assume a grain file exists — but silently dropping a directory takes
    every descendant with it, and the census then reads as thorough while a
    half-scaffolded milestone's drift goes unseen. Reporting them is rule 4:
    say what was skipped rather than quietly narrowing the scan.
    """
    out: list[tuple[Path, str]] = []
    if not cfg.roadmap.is_dir():
        return out
    for d in sorted(cfg.roadmap.iterdir()):
        if not d.is_dir() or d.name == ARCHIVE_DIR_NAME:
            continue
        if not (d / 'milestone.md').is_file():
            out.append((d, 'milestone dir with no milestone.md'))
            continue
        fdir = d / 'features'
        if not fdir.is_dir():
            continue
        for f in sorted(fdir.iterdir()):
            if f.is_dir() and not (f / 'feature.md').is_file():
                out.append((f, 'feature dir with no feature.md'))
    return out


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


def version_key(name: str) -> tuple:
    """Sort key that orders 0.9 BEFORE 0.10 — numeric components compare as
    numbers. Lexical order gets this backwards the moment a project has both a
    one-digit and a two-digit component, and `prune`'s lag-by-one uses it to
    decide which milestone survives."""
    head = name.split('-', 1)[0]
    parts = []
    for chunk in re.split(r'[.]', head):
        m = re.match(r'^(\d*)(.*)$', chunk)
        parts.append((int(m.group(1)) if m.group(1) else -1, m.group(2)))
    return tuple(parts)


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
        body = _read(path)
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


# --- flow helpers (D8-D10) ----------------------------------------------------
def building_milestones(cfg: PmConfig) -> list[tuple[str, str, Path]]:
    """(id, branch, milestone.md) for every ACTIVE milestone at `building`."""
    out = []
    for mdir in milestone_dirs(cfg):
        mfile = mdir / 'milestone.md'
        if field_of(mfile, 'status') != 'building':
            continue
        out.append((field_of(mfile, 'id'), field_of(mfile, 'branch'), mfile))
    return out


def shipped_version(cfg: PmConfig) -> str | None:
    """The version string from the project's own manifest, or None."""
    path = cfg.root / cfg.version_file
    if not path.is_file():
        return None
    pattern = re.compile(cfg.version_pattern)
    try:
        for line in _read(path).split('\n'):
            m = pattern.match(line.strip())
            if m:
                return m.group(1)
    except (OSError, UnicodeDecodeError):
        return None
    return None


def trunk_checkout_branch(cfg: PmConfig) -> tuple[str | None, str]:
    """(branch, reason) for git's MAIN worktree — the trunk.

    Deliberately NOT the tree this happens to run from: D10 asks whether the
    integration branch is where a human following along would find it.

    A None branch comes with a REASON, because the common case is a detached
    HEAD — which is what CI checks out. Silently skipping there turned D10 off
    in the one environment it exists to guard, and said nothing.
    """
    import subprocess
    try:
        listing = subprocess.run(['git', 'worktree', 'list', '--porcelain'],
                                 cwd=cfg.root, capture_output=True, text=True,
                                 check=True).stdout
        first = next((ln[len('worktree '):] for ln in listing.split('\n')
                      if ln.startswith('worktree ')), None)
        if first is None:
            return None, 'git reported no worktree'
        branch = subprocess.run(['git', 'branch', '--show-current'], cwd=first,
                                capture_output=True, text=True,
                                check=True).stdout.strip()
        if not branch:
            return None, 'the trunk is on a DETACHED HEAD (a CI checkout looks '\
                         'like this — D10 cannot verify placement here)'
        return branch, ''
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        return None, f'git is unavailable ({type(err).__name__})'


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
