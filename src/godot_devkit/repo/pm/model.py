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
    place_branch_on_building = false  # `pm milestone building` also checks the
                                   # milestone's branch out in the trunk worktree
    milestone_states      = [...]  # vocabulary overrides
    feature_states        = [...]
    story_states          = [...]
    milestone_transitions = [...]  # "from->to" edges
    feature_transitions   = [...]
    story_transitions     = [...]
    checks = ["D1","D2","D3","D4","D5","D6","D7"]   # which drift rules run
    decision_grandfather = []      # D12: logs whose legacy entries predate the
                                   # schema — "<path>" or "<path>:<N entries>"
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from godot_devkit.core.project import repo_root
from godot_devkit.core.config import ConfigError, config_section, flag, number, str_tuple, text

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
#
# The `blocked->*` edges are the way OUT. `blocked` is reachable from any state,
# and for a while had no exit at all — so the only way to unblock a story was to
# hand-edit the `status:` line, which is the exact drift this tracker exists to
# prevent. An entry from anywhere needs a return to anywhere.
DEFAULT_STORY_TRANSITIONS = ('todo->wip', 'wip->review', 'todo->review',
                             'blocked->todo', 'blocked->wip', 'blocked->review')

# D8-D10 encode the branch-per-milestone / bump-at-start flow. They are OFF by
# default: a project that ships from the trunk and bumps at close is not
# drifting, it is running a different (valid) flow, and a gate that fails it
# would be lying. Opt in with `[pm] checks`.
DEFAULT_CHECKS = ('D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7',
                  'V1', 'V2', 'V3', 'V4', 'V5', 'V6')
FLOW_CHECKS = ('D8', 'D9', 'D10')
# D11 is review-dir RETENTION. Opt-in for the same reason D8-D10 are: a project
# whose durable review records live IN review_dir satisfies it trivially, while
# a project that keeps transient findings docs there on purpose is not drifting
# by its own lights. Opt in with `[pm] checks`.
RETENTION_CHECKS = ('D11',)
# D12 is the decision-record SCHEMA. Opt-in like the rest, and for one more
# reason: every log written before it existed conforms to none of it, so a
# consumer switching it on migrates through `decision_grandfather` rather than
# through a red gate on upgrade day.
SCHEMA_CHECKS = ('D12',)
# Structural/referential integrity. ON by default: a tree that does not satisfy
# these is malformed, not merely running a different flow.
VALIDATE_CHECKS = ('V1', 'V2', 'V3', 'V4', 'V5', 'V6')
KNOWN_CHECKS = tuple(dict.fromkeys(
    DEFAULT_CHECKS + FLOW_CHECKS + RETENTION_CHECKS + SCHEMA_CHECKS
    + VALIDATE_CHECKS))

ARCHIVE_DIR_NAME = 'zz_archive'


@dataclass(frozen=True)
class PmConfig:
    root: Path
    roadmap_dir: str = 'pm/roadmap'
    review_dir: str = 'docs/reviews'
    review_min_content_bytes: int = 20
    review_slug_fallback: bool = False
    story_ordinal_prefix: bool = False
    place_branch_on_building: bool = False
    milestone_states: tuple[str, ...] = DEFAULT_MILESTONE_STATES
    feature_states: tuple[str, ...] = DEFAULT_FEATURE_STATES
    story_states: tuple[str, ...] = DEFAULT_STORY_STATES
    milestone_transitions: tuple[str, ...] = DEFAULT_MILESTONE_TRANSITIONS
    feature_transitions: tuple[str, ...] = DEFAULT_FEATURE_TRANSITIONS
    story_transitions: tuple[str, ...] = DEFAULT_STORY_TRANSITIONS
    checks: tuple[str, ...] = DEFAULT_CHECKS
    # D12 only: the grandfather ledger, parsed at load so a malformed spec is
    # exit 2. (repo-relative log path, entries exempted or None for all).
    decision_grandfather: tuple[tuple[str, int | None], ...] = ()
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
        place_branch_on_building=flag(sect, 'pm', 'place_branch_on_building', False),
        milestone_states=tup('milestone_states', DEFAULT_MILESTONE_STATES),
        feature_states=tup('feature_states', DEFAULT_FEATURE_STATES),
        story_states=tup('story_states', DEFAULT_STORY_STATES),
        milestone_transitions=tup('milestone_transitions', DEFAULT_MILESTONE_TRANSITIONS),
        feature_transitions=tup('feature_transitions', DEFAULT_FEATURE_TRANSITIONS),
        story_transitions=tup('story_transitions', DEFAULT_STORY_TRANSITIONS),
        checks=checks,
        decision_grandfather=parse_decision_grandfather(
            str_tuple(sect, 'pm', 'decision_grandfather', ())),
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


def git_worktrees(cfg: PmConfig) -> tuple[list[tuple[Path, str]], str]:
    """([(path, branch), ...] MAIN worktree first, reason) — every worktree.

    One `git worktree list --porcelain` parse, because two readers need
    different halves of the same answer: D10 wants the trunk's branch, and
    branch placement additionally has to know whether some OTHER worktree
    already holds the branch (git allows exactly one).

    `branch` is `''` for a detached or bare entry — the entry still exists,
    which is the distinction that matters. An EMPTY list is the only "git could
    not answer" signal, and it always carries a reason.
    """
    try:
        listing = subprocess.run(['git', 'worktree', 'list', '--porcelain'],
                                 cwd=cfg.root, capture_output=True, text=True,
                                 check=True).stdout
    except (subprocess.CalledProcessError, OSError) as err:
        return [], f'git is unavailable ({type(err).__name__})'
    entries: list[tuple[Path, str]] = []
    path: Path | None = None
    branch = ''
    for line in listing.split('\n'):
        # A blank line ends a record; `worktree ` opens the next one. Flushing
        # on the OPENER rather than the blank keeps a truncated final record.
        if line.startswith('worktree '):
            if path is not None:
                entries.append((path, branch))
            path, branch = Path(line[len('worktree '):]), ''
        elif line.startswith('branch ') and path is not None:
            ref = line[len('branch '):].strip()
            branch = ref[len('refs/heads/'):] if ref.startswith('refs/heads/') else ref
    if path is not None:
        entries.append((path, branch))
    if not entries:
        return [], 'git reported no worktree'
    return entries, ''


def trunk_checkout_branch(cfg: PmConfig) -> tuple[str | None, str]:
    """(branch, reason) for git's MAIN worktree — the trunk.

    Deliberately NOT the tree this happens to run from: D10 asks whether the
    integration branch is where a human following along would find it.

    A None branch comes with a REASON, because the common case is a detached
    HEAD — which is what CI checks out. Silently skipping there turned D10 off
    in the one environment it exists to guard, and said nothing.
    """
    entries, reason = git_worktrees(cfg)
    if not entries:
        return None, reason
    branch = entries[0][1]
    if not branch:
        return None, 'the trunk is on a DETACHED HEAD (a CI checkout looks '\
                     'like this — D10 cannot verify placement here)'
    return branch, ''


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

# --- retention helper (D11) ---------------------------------------------------
def review_dir_files(cfg: PmConfig) -> list[Path]:
    """Every `*.md` directly under review_dir, minus README and the archive."""
    rdir = cfg.root / cfg.review_dir
    if not rdir.is_dir():
        return []
    return sorted(f for f in rdir.glob('*.md') if f.name.lower() != 'readme.md')


def pointed_review_paths(cfg: PmConfig, fids: list[str]) -> set[Path]:
    """Every review file the TREE points at, as a resolved `Path`.

    Deliberately NOT `review_record_for()`. That applies `record_is_substantive`,
    which is D1's business: a short-but-legitimate record would be told by D1 to
    exist and by D11 to be deleted — two rules ordering opposite repairs on one
    file. Whether a record says enough is D1's question; whether the tree still
    points at the file is this one's.

    Resolved paths, never the `reviewed:` string as a human typed it: `./docs/
    reviews/x.md`, an absolute path and a Windows-separator spelling all name the
    same file, and comparing the raw text flags the tree's own durable record.

    `review_slug_fallback` accepts a GLOB, so every candidate it would accept is
    exempt — not just the first sorted one, which is all `review_record_for`
    returns.
    """
    out: set[Path] = set()
    rdir = cfg.root / cfg.review_dir
    for fid in fids:
        ffile = feature_file(cfg, fid)
        if ffile is None:
            continue
        pointer = unquote(field_of(ffile, 'reviewed'))
        if pointer and pointer != 'null':
            p = Path(pointer.replace('\\', '/'))
            out.add((p if p.is_absolute() else cfg.root / p).resolve())
        if cfg.review_slug_fallback:
            slug = fid.partition('/')[2]
            if slug and rdir.is_dir():
                out.update(c.resolve() for c in rdir.glob(f'{slug}*.md'))
    return out


def grain_named_by(cfg: PmConfig, path: Path) -> tuple[str, str] | None:
    """(feature-id, status) for the FEATURE a review file NAMES, or None.

    Filename-slug resolution, because a transient findings doc is by definition
    not pointed at by any `reviewed:` field — that is what makes it transient.
    Longest slug wins so `health-as-composition` beats a stem that merely
    contains a shorter sibling's slug.

    FEATURES ONLY. `reviewed:` exists on `feature.md` and nowhere else, so a
    milestone-scoped record has no green state to reach and the finding would
    order a repair the schema cannot accept.

    KNOWN DEFECT, do not enable D11 against a tree you have not eyeballed: the
    match is a bare substring, so a slug embedded in a longer word resolves
    (a feature `den` claims `hidden-room-audit.md`). Anchoring it is deferred
    pending the co-located-`reviews/` decision, which removes the guess
    entirely.
    """
    stem = path.stem
    best: tuple[int, str, str] | None = None
    for mdir in milestone_dirs(cfg):
        for fdir in sorted((mdir / 'features').glob('*')):
            ffile = fdir / 'feature.md'
            if not ffile.is_file() or fdir.name not in stem:
                continue
            # The dir slug is the fallback id: a feature.md with no `id:` would
            # otherwise render as "is transient and  is done".
            cand = (len(fdir.name), field_of(ffile, 'id') or fdir.name,
                    field_of(ffile, 'status'))
            if best is None or cand[0] > best[0]:
                best = cand
    return (best[1], best[2]) if best else None


# --- decision-record schema (D12) ---------------------------------------------
# A decision log rots into description. The four fields are the cure, and `Over:`
# is the load-bearing one: a decision with no rejected alternative is not a
# decision, it is a description, and an entry that cannot name what it ruled out
# should not exist. Padding is impossible when every part has to be a field.
#
#     ## D3 — 2026-08-28 — the sweep verb belongs to the combat layer
#     **Chose:** move `sweep_tracked_contributions` to `combat_behavior.gd`
#     **Over:** leaving it on `entity_behavior.gd`, the lean root
#     **Because:** all three consumers extend the combat layer
#     **Evidence:** `64e89ad5b`
DECISION_FILE_NAME = 'DECISIONS.md'
DECISION_FIELDS = ('Chose', 'Over', 'Because', 'Evidence')
DECISION_TITLE_MAX = 80
DECISION_VALUE_MAX = 200

# An ENTRY is an `##` heading carrying an ID or a DATE **anywhere** in it — not
# one that opens with an id. Detection has to be looser than the schema or the
# gate is blind to exactly the logs it exists for: real logs number `M27`, `D1`,
# and also write `## 2026-08-24 — D1: ...` with the id AFTER the date, which an
# opens-with-an-id test reads as prose and passes in silence (rule 4's cardinal
# sin). A heading with neither ("## The through-line") IS prose and is never
# schema-checked: a log may have a preamble.
_DECISION_HEADING = re.compile(r'^##[ \t]+(\S.*?)[ \t]*$')
_DECISION_ID = re.compile(
    r'(?:^|[\s([{`"\'/—-])([A-Za-z]{1,4}\d+)(?=[\s.,:;)\]}`"\'—-]|$)')
_ISO_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
# The full header. The separator is an em dash BOTH times, exactly as the schema
# reads. A hyphen renders near-identically to a human and differently to a
# parser, and a separator that is "either" is not a schema.
_DECISION_HEADER = re.compile(
    r'^##[ \t]+[A-Za-z]+\d+[ \t]+—[ \t]+(\d{4}-\d{2}-\d{2})[ \t]+—[ \t]+(\S.*?)[ \t]*$')
_DECISION_FIELD = re.compile(r'^\*\*([A-Za-z]+):\*\*[ \t]*(.*?)[ \t]*$')
# A new `##`/`#` heading ends the entry; `###` and deeper stay inside it.
_DECISION_SECTION_END = re.compile(r'^#{1,2}[ \t]')

# `Evidence:` is a REFERENCE, not a sentence — that is what stops "we discussed
# it and agreed" from counting as evidence. Every whitespace-separated token has
# to be a commit hash, a path (optionally `:line`), or a number; prose fails on
# its first word.
_REF_HASH = re.compile(r'^[0-9a-f]{7,40}$')
_REF_NUMBER = re.compile(r'^[+-]?\d[\d,._%/x×→-]*$')
_REF_PATH = re.compile(r'^[\w./~@+-]+(?::\d+(?:-\d+)?)?$')


@dataclass(frozen=True)
class DecisionEntry:
    eid: str
    line: int
    header: str
    fields: tuple[tuple[str, str], ...]


def decision_evidence_is_reference(value: str) -> bool:
    """True if every token in `value` is a hash, a path[:line], or a number."""
    tokens = value.replace('`', ' ').split()
    if not tokens:
        return False
    for raw in tokens:
        tok = raw.strip('[]()<>,;.:"\'')
        if not tok:
            return False
        if _REF_HASH.match(tok) or _REF_NUMBER.match(tok):
            continue
        # A path must LOOK like one. Without this, any bare word matches.
        if _REF_PATH.match(tok) and ('/' in tok or '.' in tok):
            continue
        return False
    return True


def decision_entry_label(heading_text: str) -> str:
    """How a finding NAMES this entry — its id, else its date, else ''.

    '' means the heading is prose, not a decision entry.
    """
    ident = _DECISION_ID.search(heading_text)
    if ident:
        return ident.group(1)
    when = _ISO_DATE.search(heading_text)
    return when.group(0) if when else ''


def decision_files(cfg: PmConfig) -> list[Path]:
    """Every DECISIONS.md in the ACTIVE tree (archived logs predate the schema)."""
    if not cfg.roadmap.is_dir():
        return []
    return sorted(p for p in cfg.roadmap.rglob(DECISION_FILE_NAME)
                  if p.is_file() and ARCHIVE_DIR_NAME not in p.parts)


def decision_entries(path: Path) -> list[DecisionEntry]:
    """The decision entries in one log, in document order."""
    try:
        lines = _split(_read(path))
    except (OSError, UnicodeDecodeError):
        return []
    starts: list[tuple[int, str]] = []
    for i, raw in enumerate(lines):
        m = _DECISION_HEADING.match(raw.rstrip('\r'))
        if m:
            label = decision_entry_label(m.group(1))
            if label:
                starts.append((i, label))
    out: list[DecisionEntry] = []
    for i, eid in starts:
        stop = len(lines)
        for j in range(i + 1, len(lines)):
            if _DECISION_SECTION_END.match(lines[j].rstrip('\r')):
                stop = j
                break
        fields: list[tuple[str, str]] = []
        for raw in lines[i + 1:stop]:
            fm = _DECISION_FIELD.match(raw.rstrip('\r'))
            if fm:
                fields.append((fm.group(1), fm.group(2)))
        out.append(DecisionEntry(eid=eid, line=i + 1,
                                 header=lines[i].rstrip('\r'),
                                 fields=tuple(fields)))
    return out


def decision_violations(path: Path) -> list[tuple[int, str, str]]:
    """[(ordinal, entry-id, what failed)] for one log, in document order.

    The ordinal is the entry's 0-based position, which is what a `path:N`
    grandfather caps: a log is append-only, so "the first N" is stable.
    """
    out: list[tuple[int, str, str]] = []
    for n, entry in enumerate(decision_entries(path)):
        def bad(msg: str, _n: int = n, _e: str = entry.eid) -> None:
            out.append((_n, _e, msg))

        head = _DECISION_HEADER.match(entry.header)
        if head is None:
            bad('header is not `## <ID> — <ISO date> — <title>` (em dashes)')
        else:
            try:
                date.fromisoformat(head.group(1))
            except ValueError:
                bad(f'header date {head.group(1)!r} is not a real date')
            if len(head.group(2)) > DECISION_TITLE_MAX:
                bad(f'title is {len(head.group(2))} chars, over the '
                    f'{DECISION_TITLE_MAX}-char cap')

        names = [n_ for n_, _ in entry.fields]
        at = -1
        for want in DECISION_FIELDS:
            if want not in names:
                why = (' — a decision with no rejected alternative is a '
                       'description') if want == 'Over' else ''
                bad(f'missing **{want}:**{why}')
                continue
            here = names.index(want)
            if here <= at:
                bad(f'**{want}:** is out of order — the fields read '
                    f'{", ".join(DECISION_FIELDS)}')
            at = max(at, here)
        for name, value in entry.fields:
            if name in DECISION_FIELDS and len(value) > DECISION_VALUE_MAX:
                bad(f'**{name}:** is {len(value)} chars, over the '
                    f'{DECISION_VALUE_MAX}-char cap')
        for name, value in entry.fields:
            if name != 'Evidence':
                continue
            if not decision_evidence_is_reference(value):
                bad('**Evidence:** is prose, not a reference — want a commit '
                    'hash, a path[:line], or a number')
            break
    return out


def parse_decision_grandfather(specs: tuple[str, ...]) -> tuple[tuple[str, int | None], ...]:
    """`"<path>"` (whole log) or `"<path>:<N>"` (its first N entries only).

    The capped form is the point: a grandfathered log keeps its legacy entries
    and every entry ADDED past the cap still has to conform, so the log stops
    growing badly without anyone rewriting old text. A malformed spec is a
    CONFIG error (exit 2), never a finding.
    """
    out: list[tuple[str, int | None]] = []
    seen: set[str] = set()
    for spec in specs:
        raw, cap = spec.strip(), None
        head, sep, tail = raw.rpartition(':')
        if sep and tail.isdigit():
            raw, cap = head.strip(), int(tail)
            if cap < 1:
                raise ConfigError(
                    f'[pm] decision_grandfather {spec!r} caps 0 entries — drop '
                    f'the ":0" to exempt nothing at all')
        elif sep:
            raise ConfigError(
                f'[pm] decision_grandfather {spec!r} has a ":" but no entry '
                f'count — write "<path>" or "<path>:<N>"')
        key = raw.replace('\\', '/')
        while key.startswith('./'):
            key = key[2:]
        if not key:
            raise ConfigError(f'[pm] decision_grandfather {spec!r} names no path')
        if not key.endswith(DECISION_FILE_NAME):
            raise ConfigError(
                f'[pm] decision_grandfather {spec!r} does not name a '
                f'{DECISION_FILE_NAME} — the ledger exempts logs, not directories')
        if key in seen:
            raise ConfigError(
                f'[pm] decision_grandfather names {key} twice — one entry per log')
        seen.add(key)
        out.append((key, cap))
    return tuple(out)


def decision_relkey(cfg: PmConfig, path: Path) -> str:
    """The repo-relative, forward-slashed key a grandfather spec is matched on."""
    return cfg.rel(path).replace('\\', '/')
