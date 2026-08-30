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
    bug_states            = [...]  # D4: the bug vocabulary
    milestone_transitions = [...]  # "from->to" edges
    feature_transitions   = [...]
    story_transitions     = [...]
    checks = ["D1","D2","D3","D4","D5","D6",        # which rules run — this
              "V1","V2","V3","V4","V5","V6"]        #   IS the stock default
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from godot_devkit.core import apply, walk
from godot_devkit.core.walk import Kind, SkipReason, Walk
from godot_devkit.core.project import repo_root
from godot_devkit.core.config import ConfigError, config_section, flag, number, str_tuple, text

# --- stock policy -------------------------------------------------------------
# The story terminal is `review`: there is deliberately NO story `*->done` edge,
# because `done` is reached ONLY by the feature-review cascade. A per-story done
# flip is the latent review-skip hole this graph closes.
DEFAULT_MILESTONE_STATES = ('planning', 'ready', 'building', 'done')
DEFAULT_FEATURE_STATES = ('planning', 'ready', 'building', 'review', 'done')
DEFAULT_STORY_STATES = ('todo', 'wip', 'review', 'done', 'blocked')
# Bugs have no transition graph — they are filed and they close. The vocabulary
# exists so D4 covers a bug's status the way it covers every other grain's: a
# typo'd status is a finding rather than a silent "closed" (rule 4).
DEFAULT_BUG_STATES = ('open', 'fixed', 'closed')

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
DEFAULT_CHECKS = ('D1', 'D2', 'D3', 'D4', 'D5', 'D6',
                  'V1', 'V2', 'V3', 'V4', 'V5', 'V6')
FLOW_CHECKS = ('D8', 'D9', 'D10')
# D13 is the canonical grain STRUCTURE. Opt-in because a tree that predates the
# canonical slots is missing most of them, and a rule that turns a consumer red
# on upgrade day is unshippable. `pm new <grain>` fills the gaps, then the rule
# holds the line.
STRUCTURE_CHECKS = ('D13',)
# Structural/referential integrity. ON by default: a tree that does not satisfy
# these is malformed, not merely running a different flow.
VALIDATE_CHECKS = ('V1', 'V2', 'V3', 'V4', 'V5', 'V6')
KNOWN_CHECKS = tuple(dict.fromkeys(
    DEFAULT_CHECKS + FLOW_CHECKS + STRUCTURE_CHECKS + VALIDATE_CHECKS))

ARCHIVE_DIR_NAME = 'zz_archive'

# --- the canonical grain structure (D13) --------------------------------------
# One shape, every grain, all lowercase. The split that makes it worth having:
#
#   decisions.md  DURABLE   — appended during the grain's life, survives close.
#
# `handoff.md` and `bugs/` are milestone-only, ruled explicitly: a feature is
# never picked up cold on its own, and a bug lives in the milestone that will
# FIX it.
#
# Every shared doc is OPTIONAL and minted on first write — see
# OPTIONAL_FILE_SLOTS. Only the grain's own frontmatter file is required.
#
# DIRECTORY slots are allowed but never REQUIRED, and the reason is git: an
# empty directory does not survive a clone, so requiring `design/` would mean
# 178 placeholder files or a rule that fails the moment somebody checks the
# tree out fresh. Files carry the requirement; directories carry permission.
DECISION_FILE_NAME = 'decisions.md'
REVIEW_FILE_NAME = 'review.md'
HANDOFF_FILE_NAME = 'handoff.md'

# PERMITTED, never required, MINTED ON FIRST WRITE. A shared doc scaffolded
# empty is sprawl the tool made: across one consumer's tree `pm new`'s mandatory
# slots minted 204 empty files, ~1,900 lines, a quarter of the PM tree — so the
# verb that exists to stop sprawl was the largest single producer of it.
#
# `decisions.md` is minted by `pm decide` when the first decision is recorded;
# `handoff.md` and `review.md` are hand-written and appear when somebody writes
# one. Never required: an absent one means nothing was recorded, which is a
# fact about the grain rather than a finding. Never forbidden either — one
# consumer holds 103 review.md, and reporting them would be reporting notes.
# What a grain MUST carry: its own frontmatter file, and nothing else.
MILESTONE_FILE_SLOTS = ('milestone.md',)
MILESTONE_DIR_SLOTS = ('features', 'bugs', 'design')
MILESTONE_OPTIONAL_SLOTS = (HANDOFF_FILE_NAME, DECISION_FILE_NAME,
                            REVIEW_FILE_NAME)
FEATURE_FILE_SLOTS = ('feature.md',)
FEATURE_DIR_SLOTS = ('stories', 'design')
# No handoff.md: a feature is never picked up cold on its own.
FEATURE_OPTIONAL_SLOTS = (DECISION_FILE_NAME, REVIEW_FILE_NAME)

# slot -> the template that mints it. The grain file's own template is named for
# the grain, the shared docs are named for the slot.
SLOT_TEMPLATE = {
    'milestone.md': 'milestone', 'feature.md': 'feature',
    'handoff.md': 'handoff', 'decisions.md': 'decisions',
}

# The one-line instruction each shared doc opens with, and D13 asserts is still
# there. `.claude/rules/*` never reach a dispatched subagent — measured — so a
# file's own first line is the one delivery channel with a 100% hit rate for the
# action its reader is about to take. Each line is an INSTRUCTION for that
# action, never an explanation of what the file is, and deliberately NOT a
# second copy of a schema a gate already owns: restating a field list in 178
# files is a drift generator, so decisions.md points at the command instead.
SLOT_HEADER = {
    'decisions.md': 'Append with `godot-devkit pm decide <grain-id>` — never by '
                    'hand; the command stamps the date and the next ordinal.',
    'handoff.md': 'Cold-start only. Never restate what `pm status` computes.',
}


def dir_entries(path: Path) -> dict[str, str]:
    """{exact name: 'file'|'dir'} for one directory — EXACT names, always.

    The name the PM rules read it by; the listing itself is `core.walk.entries`,
    where every enumeration in this package lives.
    """
    return walk.entries(path)


def case_variants(entries: dict[str, str], name: str) -> list[str]:
    """Names in `entries` that differ from `name` only by case (excluding it)."""
    low = name.lower()
    return sorted(n for n in entries if n != name and n.lower() == low)


def git_rename(root: Path, old: Path, new: Path) -> tuple[bool, str]:
    """Rename THROUGH git when git tracks `old`. (did it, why it could not).

    `(False, '')` means git does not track the path — a plain rename is then the
    whole job. `(False, why)` means git tracks it and refused, which the caller
    must surface rather than paper over.

    An `os.rename` is not enough. git's default on macOS is
    `core.ignorecase = true`, and under it a case-only rename leaves the INDEX
    holding the old spelling: the worktree says `decisions.md`, `git ls-files`
    says `DECISIONS.md`, and an explicit `git add` of the new name stages
    nothing. The migration goes green on the laptop, gets committed, and CI on
    Linux checks out the OLD name — D13 then reports every renamed grain
    missing. `git mv --force` is the one spelling that
    moves the index with the file.
    """
    try:
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', '--', str(old)],
            cwd=root, capture_output=True, text=True)
        if tracked.returncode != 0:
            return False, ''
        moved = subprocess.run(['git', 'mv', '--force', '--', str(old), str(new)],
                               cwd=root, capture_output=True, text=True)
    except OSError:
        return False, ''  # no git on PATH: the plain rename is all there is
    if moved.returncode == 0:
        return True, ''
    return False, (moved.stderr.strip() or moved.stdout.strip()
                   or f'git mv exited {moved.returncode}')


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
    bug_states: tuple[str, ...] = DEFAULT_BUG_STATES
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
        bug_states=tup('bug_states', DEFAULT_BUG_STATES),
        milestone_transitions=tup('milestone_transitions', DEFAULT_MILESTONE_TRANSITIONS),
        feature_transitions=tup('feature_transitions', DEFAULT_FEATURE_TRANSITIONS),
        story_transitions=tup('story_transitions', DEFAULT_STORY_TRANSITIONS),
        checks=checks,
        template_dir=text(sect, 'pm', 'template_dir', ''),
        version_file=text(sect, 'pm', 'version_file', 'project.godot'),
        version_pattern=version_pattern,
        trunk_branches=tup('trunk_branches', ('staging', 'main')),
    )


def unknown_checks(cfg: PmConfig) -> str:
    """The refusal for a `[pm] checks` naming a rule this package does not ship,
    or `''` when every name is known.

    An unknown name is indistinguishable from a disabled rule at runtime, so a
    typo would quietly narrow the gate — which is why this is strict. But it is
    NOT raised from `load()`, and that placement is the whole point: `load()` is
    on the path of every `pm` verb, so one stale id — exactly what a version
    bump retiring a rule produces — used to kill `pm status`, `pm get`, `pm new`
    and `pm vocabulary --json` at exit 2. The consumer could then neither read
    its own tree nor ask the tool what the new vocabulary is while deciding what
    to do about it. The GATES enforce it, because they are what a narrowed
    roster would lie to.
    """
    unknown = [c for c in cfg.checks if c not in KNOWN_CHECKS]
    if not unknown:
        return ''
    return (f'[pm] checks names unknown rule(s) {", ".join(unknown)} — '
            f'known rules are {" ".join(KNOWN_CHECKS)}')


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
def read_raw(path: Path) -> str:
    with path.open('r', encoding='utf-8', newline='') as fh:
        return fh.read()


def write_raw(path: Path, text: str) -> None:
    """The grain-file write, through `core.apply` — the one module that
    mutates. `newline=''` there is the same disabled translation this comment
    describes; a mid-write failure comes back as the `OSError` every caller of
    this function already handles."""
    apply.raise_on_error(apply.write(path, text))


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
        lines = _split(read_raw(path))
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
        text = read_raw(path)
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
        write_raw(path, '\n'.join(lines))
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
        for d in walk.matching(base, f'{mid}-*', Kind.DIR).kept:
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


_ORDINAL_STEM = re.compile(r'^[0-9][0-9]-(?P<slug>.*)$')


def story_file(cfg: PmConfig, sid: str) -> Path | None:
    """Resolve <milestone>/<feature-slug>/<story-slug> to its .md.

    Resolves over `story_files` — the SAME walk the gates use — so the two can
    never disagree about what a story is. They did: this resolver globbed one
    directory level while the walk went recursive, so a story at
    `stories/parked/s2.md` was SEEN by every rule in `check pm` and addressable
    by none of them. The gate reported a story `pm story wip <id>` then said did
    not exist, which is the worst possible pair of answers: each is defensible
    alone and together they leave nothing to do.

    With `story_ordinal_prefix`, a story FILE may carry an ordering prefix
    (`01-the-state.md`) that its ID does not — the number sequences the build,
    it is not identity. Exact stem first, then the prefixed form, so a tree
    holding both `s2.md` and `07-s2.md` resolves to the one whose name IS the
    id rather than refusing. Two files claiming one id at the same precedence
    is an authoring error and REFUSES rather than silently taking the first.
    """
    mid, _, rest = sid.partition('/')
    fslug, _, sslug = rest.partition('/')
    if not fslug or not sslug or not id_is_literal(sslug):
        return None
    fdir = feature_dir(cfg, f'{mid}/{fslug}')
    if fdir is None:
        return None
    exact: list[Path] = []
    prefixed: list[Path] = []
    for path in grain_docs(fdir / 'stories'):
        stem = path.name[:-len(path.suffix)]
        if stem == sslug:
            exact.append(path)
        elif cfg.story_ordinal_prefix:
            m = _ORDINAL_STEM.match(stem)
            if m is not None and m.group('slug') == sslug:
                prefixed.append(path)
    matches = exact or prefixed
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
    candidates = _milestone_candidates(cfg.roadmap, exclude_archive=True)
    _, orphan_milestones = candidates.partition(_has_milestone_file,
                                                SkipReason.NO_GRAIN_FILE)
    orphaned = set(orphan_milestones)
    for d in candidates.kept:
        if d in orphaned:
            out.append((d, 'milestone dir with no milestone.md'))
            continue
        _, orphan_features = walk.children(d / 'features', Kind.DIR).partition(
            _has_feature_file, SkipReason.NO_GRAIN_FILE)
        out += [(f, 'feature dir with no feature.md') for f in orphan_features]
    return out


def _has_milestone_file(d: Path) -> bool:
    return (d / 'milestone.md').is_file()


def _has_feature_file(d: Path) -> bool:
    return (d / 'feature.md').is_file()


def _milestone_candidates(base: Path, exclude_archive: bool) -> Walk:
    """Directories under one roadmap base that a milestone COULD be.

    The universe `milestone_dirs` keeps from and `orphan_dirs` reports on — one
    walk, so the two can never disagree about which directories the tree holds.
    """
    found = walk.children(base, Kind.DIR)
    if exclude_archive:
        found = found.filter(lambda d: d.name != ARCHIVE_DIR_NAME,
                             SkipReason.EXCLUDED_PATH)
    return found


def milestone_walk(cfg: PmConfig, include_archive: bool = False) -> Walk:
    """Milestone dirs in the ACTIVE tree, with the scaffold-only dirs the walk
    dropped recorded beside them (archived ones predate the schema)."""
    found = _milestone_candidates(cfg.roadmap, exclude_archive=True).filter(
        _has_milestone_file, SkipReason.NO_GRAIN_FILE)
    if include_archive:
        found = found.merge(
            _milestone_candidates(cfg.roadmap / ARCHIVE_DIR_NAME, exclude_archive=False)
            .filter(_has_milestone_file, SkipReason.NO_GRAIN_FILE))
    return found


def milestone_dirs(cfg: PmConfig, include_archive: bool = False) -> list[Path]:
    """Milestone dirs in the ACTIVE tree (archived ones predate the schema)."""
    return list(milestone_walk(cfg, include_archive).kept)


BOM = '﻿'


def _opens_frontmatter(lines: list[str]) -> bool:
    """True when this text ATTEMPTS a leading `---` frontmatter block.

    LENIENT on purpose, and it is the only lenient reader in this module. It
    answers "did the author mean this to be a grain?", not "is the block
    valid?" — so it steps over a UTF-8 BOM and any run of blank lines before
    the fence, and tolerates leading spaces on the fence itself. `_fence_bounds`
    answers the second question and stays exactly as strict as it was: a BOM'd
    file is a grain whose frontmatter is DAMAGED, never a grain quietly
    accepted.

    The one thing it will not step over is PROSE. A `---` after a paragraph is
    a thematic break in a note, not a frontmatter fence, so the first non-blank
    line decides and nothing later does.
    """
    for line in lines:
        probe = line.lstrip(BOM)
        if not probe.strip():
            continue
        return _FENCE.match(probe.lstrip(' \t')) is not None
    return False


def _is_grain_doc(path: Path) -> bool:
    """True when this file is a GRAIN document rather than a note parked beside
    one — i.e. it OPENS a `---` frontmatter block, whether or not that block
    turns out to be well-formed.

    A grain IS its frontmatter: every template mints the block, and every rule
    asks its questions through `field_of`, which reads nothing else. A `.md`
    without one answers `''` to every question, which is why a `README.md`
    explaining how bugs are filed came out of the bug walk as a bug with an
    illegal status.

    THE TWO QUESTIONS ARE NOT THE SAME QUESTION. "This has no frontmatter" is a
    note and is out of scope; "this frontmatter is broken" is a grain and is a
    FINDING. Deciding scope with the strict parser answered the second with the
    first: a BOM before the `---`, a blank line before it, or a missing closing
    fence dropped the document out of the census entirely — D4, D5 and V1 all
    went blind at once, and a damaged grain nothing reports is a grain nothing
    can fix. So detection is lenient
    (`_opens_frontmatter`) and parsing stays strict (`_fence_bounds`), and the
    damage is reported by the rules rather than resolved here.

    A file that cannot be READ stays IN scope for the same reason: "this is not
    a grain" and "this cannot be opened" are different facts. In scope it
    reaches the rule, and the rule reports it.
    """
    try:
        return _opens_frontmatter(_split(read_raw(path)))
    except (OSError, UnicodeDecodeError):
        return True


def slot_walk(gdir: Path) -> Walk:
    """THE walk of one slot directory (`bugs/`, `stories/`) — both halves.

    The single definition every reader shares (D2/D4's story walk, D4's bug
    walk, every census): a second walk would be a second
    chance to disagree about which documents the tree even holds. It replaced
    six hand-rolled functions — `_slot_docs`, `_all_slot_docs`, `hidden_docs`,
    `grain_docs`, `note_docs` and their two tree-wide aggregators — which were
    the same enumeration written five times so that each narrowing could be
    remembered separately. One of them was forgotten, twice.

    RECURSIVE, and the extension compared case-insensitively: a `glob('*.md')`
    saw neither `<slot>/<topic>/<doc>.md` nor `<DOC>.MD`, and neither `bugs/`
    nor `stories/` is a directory D13 descends into, so both were invisible to
    every rule at once — and the census printed the smaller number without
    saying it had looked less far.

    Two NARROWINGS, and both disclose because `Walk.filter` gives them no other
    option:

      * DOTTED_NAME — dot-prefixed components, files and directories alike,
        exactly as `structure_findings` skips them for D13. Out of scope for
        every rule, but COUNTED: `0 bug(s)` must not quietly mean "one bug
        parked under `bugs/.hold/` that no rule ever opened".
      * NO_FRONTMATTER — a `.md` that is a note parked beside a grain rather
        than a grain. "0 bugs" and "0 bugs and a README nobody counted" are
        different facts about a directory.
    """
    return (walk.descendants(gdir, Kind.FILE, suffix='.md')
            .filter(lambda p: not _is_hidden(gdir, p), SkipReason.DOTTED_NAME)
            .filter(_is_grain_doc, SkipReason.NO_FRONTMATTER))


def _is_hidden(gdir: Path, p: Path) -> bool:
    """True if any path component under `gdir` is dot-prefixed."""
    return any(part.startswith('.') for part in p.relative_to(gdir).parts)


def grain_docs(gdir: Path) -> list[Path]:
    """Every grain document under one slot directory, in reading order."""
    return list(slot_walk(gdir).kept)


def feature_files(mdir: Path) -> list[Path]:
    return [d / 'feature.md' for d in walk.children(mdir / 'features', Kind.DIR)
            .filter(_has_feature_file, SkipReason.NO_GRAIN_FILE).kept]


def story_files(ffile: Path) -> list[Path]:
    """Every story document under one feature, in reading order."""
    return grain_docs(ffile.parent / 'stories')


def tree_walk(cfg: PmConfig) -> Walk:
    """Every slot document in the ACTIVE tree, and everything the walk skipped.

    What the census renders. A census must never assert the opposite of the
    filesystem, and the only way to a number here is `Walk.census`, which emits
    the number and its narrowings as one string.
    """
    found = Walk(())
    for mdir in milestone_dirs(cfg):
        found = found.merge(slot_walk(mdir / 'bugs'))
        for ffile in feature_files(mdir):
            found = found.merge(slot_walk(ffile.parent / 'stories'))
    return found


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
        body = read_raw(path)
    except (OSError, UnicodeDecodeError):
        return False
    return len(''.join(body.split())) >= cfg.review_min_content_bytes


def durable_record_for(cfg: PmConfig, fid: str) -> Path | None:
    """Where a feature's review record BELONGS — its own `decisions.md`.

    Named so the refusal can point at a path rather than at a principle.
    """
    ffile = feature_file(cfg, fid)
    return None if ffile is None else ffile.parent / DECISION_FILE_NAME


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
            for cand in walk.matching(rdir, f'{slug}*.md', Kind.FILE).kept:
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
        for line in read_raw(path).split('\n'):
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

# --- the grain walk (D13) ------------------------------------------------
@dataclass(frozen=True)
class GrainDir:
    """One milestone or feature directory, its grain file, and its status."""
    kind: str          # 'milestone' | 'feature'
    path: Path
    grain_file: Path
    gid: str
    status: str

    @property
    def file_slots(self) -> tuple[str, ...]:
        return (MILESTONE_FILE_SLOTS if self.kind == 'milestone'
                else FEATURE_FILE_SLOTS)

    @property
    def dir_slots(self) -> tuple[str, ...]:
        return (MILESTONE_DIR_SLOTS if self.kind == 'milestone'
                else FEATURE_DIR_SLOTS)

    @property
    def optional_slots(self) -> tuple[str, ...]:
        return (MILESTONE_OPTIONAL_SLOTS if self.kind == 'milestone'
                else FEATURE_OPTIONAL_SLOTS)


def grain_dirs(cfg: PmConfig) -> list[GrainDir]:
    """Every milestone and feature dir in the ACTIVE tree, in reading order."""
    out: list[GrainDir] = []
    for mdir in milestone_dirs(cfg):
        mfile = mdir / 'milestone.md'
        out.append(GrainDir('milestone', mdir, mfile,
                            unquote(field_of(mfile, 'id')) or mdir.name,
                            field_of(mfile, 'status')))
        for ffile in feature_files(mdir):
            out.append(GrainDir('feature', ffile.parent, ffile,
                                unquote(field_of(ffile, 'id')) or ffile.parent.name,
                                field_of(ffile, 'status')))
    return out


# --- structure (D13) ----------------------------------------------------------
def header_of(path: Path) -> str:
    """The file's first non-blank line, stripped — its canonical header slot."""
    try:
        for line in _split(read_raw(path)):
            if line.strip():
                return line.strip()
    except (OSError, UnicodeDecodeError):
        return ''
    return ''


def structure_findings(cfg: PmConfig) -> list[tuple[Path, str]]:
    """(path, reason) for every deviation from the canonical grain shape.

    MISSING is drift and EXTRA is drift, and the extra half is the one that
    matters: `plans/`, `findings/`, `AUDIT-REPORT.md` and `DELETED-SCENARIO-
    LEDGER.md` all exist in a real tree because no slot was scaffolded AND
    nothing flagged the invention. A missing-only check leaves those forever.

    The shared docs are OPTIONAL and minted on first write — permitted, never
    required, see MILESTONE_OPTIONAL_SLOTS. Their instruction header is still
    asserted once one EXISTS: the breadcrumb is the reason the file has a
    convention at all, and a hand-made one that lost it is drift.
    """
    out: list[tuple[Path, str]] = []
    for grain in grain_dirs(cfg):
        entries = dir_entries(grain.path)
        allowed = (set(grain.file_slots) | set(grain.dir_slots)
                   | set(grain.optional_slots))
        for slot in grain.file_slots:
            if entries.get(slot) == 'file':
                continue
            variants = case_variants(entries, slot)
            why = (f' — {", ".join(variants)} is the same slot in another case, '
                   f'renamed by `pm new {grain.kind}`') if variants else ''
            out.append((grain.path / slot,
                        f'{grain.kind} {grain.gid} is missing {slot}{why}'))
        for name, kind in sorted(entries.items()):
            if name in allowed or name.startswith('.'):
                continue
            out.append((grain.path / name,
                        f'{grain.kind} {grain.gid} carries {name}'
                        f'{"/" if kind == "dir" else ""}, which is not a '
                        f'canonical slot ({" ".join(sorted(allowed))})'))
        for slot, want in SLOT_HEADER.items():
            if slot not in grain.optional_slots or entries.get(slot) != 'file':
                continue
            got = header_of(grain.path / slot)
            if got != want:
                out.append((grain.path / slot,
                            f'{slot} no longer opens with its instruction line '
                            f'— restore "{want}"'))
    return out


# --- bug status vocabulary (D4) -----------------------------------------------
# A bug is filed where it was caught and it is never moved by this tool. What IS
# checkable is the same fact D4 already owns for every other grain: a status
# outside the vocabulary. It matters more here than elsewhere, because every
# reader that asks "is this bug still open" tests for a NAME — so a typo reads
# as "closed" and passes in silence, which is rule 4's cardinal sin.
def bug_files(mdir: Path) -> list[Path]:
    """Every bug document under one milestone, in reading order."""
    return grain_docs(mdir / 'bugs')


def bug_status_findings(cfg: PmConfig) -> tuple[list[tuple[Path, str]], int]:
    """(findings, bugs scanned) — every bug whose status is outside `bug_states`.

    The walk is RECURSIVE and case-insensitive on the extension, because a bug
    parked in `bugs/<topic>/` or written as `.MD` is still a bug: an
    undercounting scan reports a smaller number without saying it looked less
    far, which is a census asserting the opposite of the filesystem.
    """
    out: list[tuple[Path, str]] = []
    scanned = 0
    for mdir in milestone_dirs(cfg):
        for bfile in bug_files(mdir):
            scanned += 1
            bstat = field_of(bfile, 'status')
            if bstat not in cfg.bug_states:
                out.append((bfile, f'bug status {bstat!r} is not in '
                                   f'({" ".join(cfg.bug_states)})'))
    return out, scanned


# --- appending a decision heading (`pm decide`) -------------------------------
# The two things authors get wrong writing one of these by hand are the DATE and
# the ORDINAL, so the verb stamps both and stops there. Everything under the
# heading is the author's prose: a schema that told them which four fields to
# write produced, across 158 real decision logs holding 320 hand-written
# headings, exactly zero conforming entries.
_ENTRY_ORDINAL = re.compile(r'^##[ \t]+([A-Za-z]{1,4})(\d+)\b')
DECISION_PREFIX = 'D'


def next_entry_id(text: str) -> str:
    """The next ordinal for this log, from the ids the log itself holds.

    The PREFIX comes from the log's own last id-shaped heading, so a tree that
    numbers `M27` keeps numbering `M`. A log with no id-shaped heading starts
    at `D1`. Reuse across FILES is by design: 0.14.0's D7 and 0.15.0's D7 are
    different decisions in different logs, and numbering every milestone from a
    global counter would say they were related.
    """
    seen = [m for m in (_ENTRY_ORDINAL.match(line) for line in _split(text)) if m]
    if not seen:
        return f'{DECISION_PREFIX}1'
    prefix = seen[-1].group(1)
    highest = max(int(m.group(2)) for m in seen if m.group(1) == prefix)
    return f'{prefix}{highest + 1}'


def append_heading(text: str, eid: str, when: str, title: str) -> str:
    """`text` with one `## <id> — <date> — <title>` heading appended.

    The separator is an em dash because that is what `next_entry_id` and every
    log already in the tree use; a hyphen renders near-identically to a human
    and differently to a reader looking for the id.
    """
    eol = '\r\n' if '\r\n' in text else '\n'
    body = text
    if body and not body.endswith(('\n', '\r')):
        body += eol
    if body and not body.endswith(eol * 2):
        body += eol
    return body + f'## {eid} — {when} — {title}{eol}'
