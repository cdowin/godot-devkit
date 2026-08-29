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
    bug_states            = [...]  # D14 only: the bug vocabulary
    bug_open_states       = [...]  # D14 only: which of those mean "still open"
    milestone_transitions = [...]  # "from->to" edges
    feature_transitions   = [...]
    story_transitions     = [...]
    checks = ["D1","D2","D3","D4","D5","D6","D7"]   # which drift rules run
    decision_grandfather = []      # D12: logs whose legacy entries predate the
                                   # schema — "<path>" or "<path>:<N entries>"
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from godot_devkit.core.markdown import fenced_flags
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
# exists so D14 can tell an OPEN bug from a closed one, and so a typo'd status
# is a finding rather than a silent "closed" (rule 4).
DEFAULT_BUG_STATES = ('open', 'fixed', 'closed')
DEFAULT_BUG_OPEN_STATES = ('open',)

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
# D11 is review RETENTION: the transient `review.md` slot must be gone once its
# grain is done. Opt-in for the same reason D8-D10 are — a project that keeps
# its review notes forever is running a different (valid) convention.
RETENTION_CHECKS = ('D11',)
# D13 is the canonical grain STRUCTURE, D14 the bug-lifetime rule. Opt-in for
# the migration reason D12 is: a tree that predates the canonical slots is
# missing most of them, and a rule that turns a consumer red on upgrade day is
# unshippable. `pm new <grain>` fills the gaps, then the rule holds the line.
STRUCTURE_CHECKS = ('D13', 'D14')
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
    + STRUCTURE_CHECKS + VALIDATE_CHECKS))

ARCHIVE_DIR_NAME = 'zz_archive'

# --- the canonical grain structure (D13) --------------------------------------
# One shape, every grain, all lowercase. The split that makes it worth having:
#
#   decisions.md  DURABLE   — appended during the grain's life, survives close,
#                             collapses to pointers when the milestone closes.
#   review.md     TRANSIENT — simplifier and reviewer both append; DELETED at
#                             close, with anything durable promoted first (D11).
#
# `handoff.md` and `bugs/` are milestone-only, ruled explicitly: a feature is
# never picked up cold on its own, and a bug lives in the milestone that will
# FIX it, which is a milestone-level decision.
#
# DIRECTORY slots are allowed but never REQUIRED, and the reason is git: an
# empty directory does not survive a clone, so requiring `design/` would mean
# 178 placeholder files or a rule that fails the moment somebody checks the
# tree out fresh. Files carry the requirement; directories carry permission.
DECISION_FILE_NAME = 'decisions.md'
REVIEW_FILE_NAME = 'review.md'

MILESTONE_FILE_SLOTS = ('milestone.md', 'handoff.md', 'decisions.md', 'review.md')
MILESTONE_DIR_SLOTS = ('features', 'bugs', 'design')
FEATURE_FILE_SLOTS = ('feature.md', 'decisions.md', 'review.md')
FEATURE_DIR_SLOTS = ('stories', 'design')

# slot -> the template that mints it. The grain file's own template is named for
# the grain, the shared docs are named for the slot.
SLOT_TEMPLATE = {
    'milestone.md': 'milestone', 'feature.md': 'feature',
    'handoff.md': 'handoff', 'decisions.md': 'decisions', 'review.md': 'review',
}

# The one-line instruction each shared doc opens with, and D13 asserts is still
# there. `.claude/rules/*` never reach a dispatched subagent — measured — so a
# file's own first line is the one delivery channel with a 100% hit rate for the
# action its reader is about to take. Each line is an INSTRUCTION for that
# action, never an explanation of what the file is, and deliberately NOT a
# second copy of a schema a gate already owns: restating D12's four fields in
# 178 files is a drift generator, so decisions.md points at the command instead.
SLOT_HEADER = {
    'decisions.md': 'Append with `godot-devkit pm decide <grain-id>` — never by '
                    'hand; the command stamps the date and the next ordinal.',
    'review.md': 'Transient. Deleted at close — promote anything durable into '
                 'decisions.md first.',
    'handoff.md': 'Cold-start only. Never restate what `pm status` computes.',
}


def dir_entries(path: Path) -> dict[str, str]:
    """{exact name: 'file'|'dir'} for one directory — EXACT names, always.

    Never `Path.is_file()` for an existence question here: macOS resolves
    `decisions.md` to an existing `DECISIONS.md` and Linux does not, so the same
    tree would be clean on one platform and drifting on the other. A listing
    compares the bytes git stores.
    """
    try:
        return {p.name: ('dir' if p.is_dir() else 'file')
                for p in path.iterdir()}
    except OSError:
        return {}


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
    missing and D12 scans nothing. `git mv --force` is the one spelling that
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
    bug_open_states: tuple[str, ...] = DEFAULT_BUG_OPEN_STATES
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

    # A bug is "open" by a POSITIVE list, so a project adding `triage` says so
    # once. The two keys have to agree, or D14 would read a legal status as
    # closed and stay silent about exactly the bug it exists to find.
    bug_states = tup('bug_states', DEFAULT_BUG_STATES)
    bug_open = tup('bug_open_states', DEFAULT_BUG_OPEN_STATES)
    stray = [s for s in bug_open if s not in bug_states]
    if stray:
        raise ConfigError(
            f'[pm] bug_open_states names {", ".join(stray)}, which is not in '
            f'bug_states ({" ".join(bug_states)}) — a bug cannot be open in a '
            f'state the vocabulary does not have')

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
        bug_states=bug_states,
        bug_open_states=bug_open,
        milestone_transitions=tup('milestone_transitions', DEFAULT_MILESTONE_TRANSITIONS),
        feature_transitions=tup('feature_transitions', DEFAULT_FEATURE_TRANSITIONS),
        story_transitions=tup('story_transitions', DEFAULT_STORY_TRANSITIONS),
        checks=checks,
        # The one `[pm]` list whose default is EMPTY: it is a ledger of
        # exemptions, so `[]` means "none exempt" — the same thing the absent
        # key means — and refusing it made the documented default the one value
        # a repo could not write down.
        decision_grandfather=parse_decision_grandfather(
            str_tuple(sect, 'pm', 'decision_grandfather', (), allow_empty=True)),
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
def read_raw(path: Path) -> str:
    with path.open('r', encoding='utf-8', newline='') as fh:
        return fh.read()


def write_raw(path: Path, text: str) -> None:
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
        body = read_raw(path)
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

# --- the grain walk (D11, D13, D14) -------------------------------------------
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


# --- retention (D11) ----------------------------------------------------------
# `review.md` is CO-LOCATED, so retention has one question and no guess: is the
# transient slot still there on a grain that closed? The rule this replaces
# resolved a filename in a shared directory back to the grain it "named", and a
# real corpus got that exactly backwards — 6 of 123 docs resolved, and those 6
# were the durable ones `reviewed:` already pointed at. Anchoring the match
# could only ever remove matches. A known path removes the question.
def stale_review_files(cfg: PmConfig) -> list[tuple[GrainDir, Path]]:
    """(grain, review.md) for every `done` grain that still has one."""
    out = []
    for grain in grain_dirs(cfg):
        if grain.status != 'done':
            continue
        if dir_entries(grain.path).get(REVIEW_FILE_NAME) == 'file':
            out.append((grain, grain.path / REVIEW_FILE_NAME))
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

    `review.md` is required exactly while the grain is open and forbidden once
    it is done — the two halves of one fact, with D11 owning the `done` half so
    a closed grain is never told both to have it and to delete it.
    """
    out: list[tuple[Path, str]] = []
    for grain in grain_dirs(cfg):
        entries = dir_entries(grain.path)
        allowed = set(grain.file_slots) | set(grain.dir_slots)
        for slot in grain.file_slots:
            if slot == REVIEW_FILE_NAME and grain.status == 'done':
                continue  # D11 owns the closed half
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
            if slot not in grain.file_slots or entries.get(slot) != 'file':
                continue
            got = header_of(grain.path / slot)
            if got != want:
                out.append((grain.path / slot,
                            f'{slot} no longer opens with its instruction line '
                            f'— restore "{want}"'))
    return out


# --- bug lifetime (D14) -------------------------------------------------------
# A bug lives in the milestone that will FIX it, not the one that caught it:
# `caught_in:` keeps the provenance, `fix_milestone:` names the decision, and
# the DIRECTORY is that decision made real. An open bug under a `done` milestone
# is therefore drift twice over — the fix is not scheduled anywhere a reader
# would look, and `prune`'s lag-by-one deletes the file the moment the next
# milestone closes. This rule is what makes prune safe by construction.
def open_bugs_under_done(cfg: PmConfig) -> tuple[list[tuple[Path, str]], int]:
    """(findings, bugs scanned) — open bugs under a done milestone, plus any
    bug whose status is outside the vocabulary (which D4 does not cover, and
    which would otherwise read as "closed" and be passed in silence)."""
    out: list[tuple[Path, str]] = []
    scanned = 0
    for mdir in milestone_dirs(cfg):
        mstat = field_of(mdir / 'milestone.md', 'status')
        mid = unquote(field_of(mdir / 'milestone.md', 'id')) or mdir.name
        bdir = mdir / 'bugs'
        if not bdir.is_dir():
            continue
        # RECURSIVE, and the extension compared case-insensitively. A
        # `glob('*.md')` saw neither `bugs/<topic>/<bug>.md` nor `<BUG>.MD`, and
        # `bugs/` is a permitted slot that D13 never descends into, so both were
        # invisible to every rule at once — and the census printed the smaller
        # number without saying it had looked less far. D14 is what stops
        # `prune` deleting an open bug with its done milestone; a D14 that
        # undercounts is not a weaker safety net, it is a false one.
        for bfile in sorted(p for p in bdir.rglob('*')
                            if p.is_file() and p.suffix.lower() == '.md'):
            scanned += 1
            bstat = field_of(bfile, 'status')
            if bstat not in cfg.bug_states:
                out.append((bfile, f'bug status {bstat!r} is not in '
                                   f'({" ".join(cfg.bug_states)})'))
                continue
            if mstat != 'done' or bstat not in cfg.bug_open_states:
                continue
            fix = unquote(field_of(bfile, 'fix_milestone'))
            where = (f'move it to {fix}/bugs/' if fix and fix != mid
                     else 'set fix_milestone: and move it there')
            out.append((bfile, f'is {bstat!r} under the done milestone {mid} — '
                               f'{where} (a prune deletes it where it sits)'))
    return out, scanned


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

    NOT the detector. '' means only that the heading names itself neither way;
    whether the block IS an entry is decided by its BODY (see
    `decision_entries_in`), because a heuristic guessing which text is a record
    from the record's title is the defect this rule exists to catch.
    """
    ident = _DECISION_ID.search(heading_text)
    if ident:
        return ident.group(1)
    when = _ISO_DATE.search(heading_text)
    return when.group(0) if when else ''


def decision_files(cfg: PmConfig) -> tuple[list[Path], list[Path]]:
    """(the logs, the case-variant files) in the ACTIVE tree.

    EXACT names, from a directory listing — never `rglob(DECISION_FILE_NAME)`.
    A pattern whose final segment holds no wildcard resolves through
    `Path.exists()`, so on macOS `rglob('decisions.md')` answers an on-disk
    `DECISIONS.md` with the path `x/decisions.md`: a path that does not exist,
    a `decision_grandfather` key authorable on exactly one platform, and — the
    moment ONE log of a tree is migrated — a NON-EMPTY list, which is what
    silences the scanned-nothing guard while every other log goes unopened.

    A `.md` whose lowercased name is `decisions.md` but whose bytes differ is
    returned separately to be REPORTED: never folded in (the two platforms
    would emit opposite findings about the same file) and never dropped (a log
    the rule cannot see is a log the rule has not checked).

    Archived logs predate the schema and are skipped.
    """
    if not cfg.roadmap.is_dir():
        return [], []
    logs: list[Path] = []
    variants: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(cfg.roadmap):
        dirnames[:] = [d for d in dirnames if d != ARCHIVE_DIR_NAME]
        for name in filenames:
            if name == DECISION_FILE_NAME:
                logs.append(Path(dirpath) / name)
            elif name.lower() == DECISION_FILE_NAME:
                variants.append(Path(dirpath) / name)
    return sorted(logs), sorted(variants)


def _mask_code_spans(raw: str) -> str:
    """The line with every inline `code span` blanked to spaces.

    Offsets are preserved, so the caller can go on searching the masked line
    and still report positions from the real one. A marker inside backticks is
    a marker being NAMED, not a comment being opened — which is exactly how a
    log documenting comment handling swallowed its own next three fields.
    """
    out = list(raw)
    i, n = 0, len(raw)
    while i < n:
        if raw[i] != '`':
            i += 1
            continue
        j = i
        while j < n and raw[j] == '`':
            j += 1
        close = raw.find(raw[i:j], j)
        if close < 0:  # an unpaired run opens no span
            i = j
            continue
        end = close + (j - i)
        for k in range(i, end):
            out[k] = ' '
        i = end
    return ''.join(out)


def _mask_markup(lines: list[str]) -> tuple[list[str], list[bool], int]:
    """(each line with inline code spans blanked, which lines are FENCED, the
    1-based line of a fence that is never terminated, or 0).

    A fenced block is a code sample the reader sees verbatim: `## <short title>`
    inside one is not a heading and `<!--` inside one is a marker being quoted,
    not a comment being opened. Fenced lines are blanked here and excluded from
    entry detection by the caller — counting a template's example block as a
    real entry is the same lie in the other direction.

    An UNTERMINATED fence suppresses nothing, exactly as an unterminated `<!--`
    suppresses nothing: left masked it would mark every remaining entry dead and
    the gate would print PASS over the ones it ate — the cardinal sin, arrived at
    the second way. One stray ``` typo, one ~~~ closed by ```, one line opening
    with a three-backtick inline span: each is REPORTED here instead, because a
    log whose fences D12 cannot delimit is a log D12 has not honestly scanned.

    Blanking preserves length, so a marker OUTSIDE the masked ranges still lands
    at its real offset.

    WHERE the fences are is `core.markdown.fenced_flags`' answer, not a second
    one: `check doc` and `check agents` read the same markdown under the same
    CommonMark rules, and two scanners would drift into disagreeing about which
    lines a document even has.
    """
    fenced, unfenced = fenced_flags(lines)
    out = [' ' * len(raw) if hidden else _mask_code_spans(raw)
           for raw, hidden in zip(lines, fenced)]
    return out, fenced, unfenced


def _comment_scan(lines: list[str]) -> tuple[list[bool], list[str], int, int]:
    """(per line: is it LIVE log text — outside any HTML comment at the point it
    starts, and outside any fenced code block?, the text of each line the entry
    parser should READ, the 1-based line of an `<!--` that is never closed, or 0,
    the same for an unterminated code fence).

    A `<!-- ... -->` block renders as nothing, so what it holds is not in the
    log. Load-bearing here because the RETIRED decisions template shipped its
    example block commented out, `**Decision:**` field lines and all — and the
    field line is exactly the signal entry detection keys on.

    Only a CLOSED block suppresses anything. A single-pass toggle would let one
    stray `<!--` mark the whole rest of the file dead and still print PASS over
    the entries it ate — rule 4's cardinal sin, from a log that looks fine to
    every reader. So spans are collected first and an unterminated marker
    suppresses nothing at all; it is returned to be REPORTED, because a log
    whose comments D12 cannot delimit is a log D12 has not honestly scanned.

    The two EDGE lines of a span are symmetric, and both keep their live half.
    The opening line's live half is what precedes `<!--`, and it already reads
    at line start. The closing line's live half is what FOLLOWS `-->`, so the
    commented head is dropped and that half reads at line start too — killing
    the whole closing line instead hid a conforming `**Over:**` written after a
    spanning aside, and D12 failed the entry for having no rejected alternative.
    """
    masked, fenced, unfenced = _mask_markup(lines)
    live = [not f for f in fenced]
    text = list(lines)
    spans: list[tuple[int, int, int]] = []
    inside, start = False, 0
    for idx, body in enumerate(masked):
        i = 0
        while i < len(body):
            if inside:
                j = body.find('-->', i)
                if j < 0:
                    break
                spans.append((start, idx, j + 3))
                inside, i = False, j + 3
            else:
                j = body.find('<!--', i)
                if j < 0:
                    break
                inside, start, i = True, idx, j + 4
    for opened, closed, after in spans:
        if closed == opened:
            continue  # opened and closed inline: the line was never suppressed
        for k in range(opened + 1, closed):
            live[k] = False
        text[closed] = lines[closed][after:].lstrip(' \t')
    return live, text, (start + 1 if inside else 0), unfenced


def decision_comment_defect(text: str) -> str:
    """'' when the log's HTML comments are all closed, else what is wrong.

    Separate from the entry list on purpose: this is a defect of the LOG, not
    of any entry, so no grandfather ordinal caps it and no entry name carries
    it.
    """
    _, _, unclosed, _ = _comment_scan(_split(text))
    if not unclosed:
        return ''
    return (f'line {unclosed} opens an HTML comment `<!--` that is never '
            f'closed — the log is malformed and D12 cannot say what it holds; '
            f'close it, or put the marker in backticks if you meant to name it')


def decision_fence_defect(text: str) -> str:
    """'' when the log's code fences are all terminated, else what is wrong.

    The twin of `decision_comment_defect`, and it exists for the same reason.
    Fence masking was added so a quoted `<!--` inside a sample stopped eating
    the log; an unterminated fence then ate the log by the other route, and did
    it in SILENCE — `1 entry/ies … PASS` over a two-entry file. A mask nothing
    reports is the defect, whichever marker opened it.
    """
    _, _, _, unfenced = _comment_scan(_split(text))
    if not unfenced:
        return ''
    return (f'line {unfenced} opens a code fence that is never terminated — '
            f'the log is malformed and D12 cannot say which of it is a sample; '
            f'close the fence, or shorten the run of backticks if you meant an '
            f'inline span')


def decision_entries_in(text: str) -> list[DecisionEntry]:
    """The same parse over log TEXT, so a candidate entry can be validated
    against D12's own regexes BEFORE it is written rather than after.

    An ENTRY is a `##` heading that either NAMES itself (an id or an ISO date
    anywhere in it) or carries at least one `**Word:**` field line beneath it.
    The second half is the positive signal: a heading may be titled anything —
    the retired template told authors to write `## <short title>` — and a
    detector reading only the title passes an entire non-conforming corpus in
    silence, which is rule 4's cardinal sin. A heading with NEITHER is prose and
    is never schema-checked: a log may have a preamble.
    """
    lines = _split(text)
    live, body, _, _ = _comment_scan(lines)
    out: list[DecisionEntry] = []
    for i, raw in enumerate(body):
        if not live[i]:
            continue
        m = _DECISION_HEADING.match(raw.rstrip('\r'))
        if not m:
            continue
        stop = len(lines)
        for j in range(i + 1, len(lines)):
            if live[j] and _DECISION_SECTION_END.match(body[j].rstrip('\r')):
                stop = j
                break
        fields: list[tuple[str, str]] = []
        for j in range(i + 1, stop):
            if not live[j]:
                continue
            fm = _DECISION_FIELD.match(body[j].rstrip('\r'))
            if fm:
                fields.append((fm.group(1), fm.group(2)))
        eid = decision_entry_label(m.group(1))
        if not eid:
            if not fields:
                continue
            # It IS an entry and still has to be named. Its own title is the
            # only handle it has; a finding naming nothing cannot be acted on.
            flat = ' '.join(m.group(1).split())
            eid = (flat if len(flat) <= DECISION_TITLE_MAX
                   else flat[:DECISION_TITLE_MAX - 1] + '…')
        out.append(DecisionEntry(eid=eid, line=i + 1,
                                 header=body[i].rstrip('\r'),
                                 fields=tuple(fields)))
    return out


def decision_violations_in(entries: list[DecisionEntry]) -> list[tuple[int, str, str]]:
    """[(ordinal, entry-id, what failed)], in document order, over already-parsed
    entries. The ordinal is the entry's 0-based position, which is what a
    `path:N` grandfather caps: a log is append-only, so "the first N" is stable.

    ONE implementation: `pm decide` validates its candidate through this, so the
    writer cannot disagree with the gate about what conforms."""
    out: list[tuple[int, str, str]] = []
    for n, entry in enumerate(entries):
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


# --- writing a decision (`pm decide`) -----------------------------------------
_DECISION_ORDINAL = re.compile(r'^([A-Za-z]{1,4})(\d+)$')


def next_decision_id(entries: list[DecisionEntry]) -> str:
    """The next id for this log — the two things authors get wrong, allocated.

    The PREFIX comes from the log's own last id-shaped entry, so a tree that
    numbers `M27` keeps numbering `M`. An empty log (or one whose headings are
    all dates) starts at `D1`.
    """
    numbered = [m for m in (_DECISION_ORDINAL.match(e.eid) for e in entries) if m]
    if not numbered:
        return 'D1'
    prefix = numbered[-1].group(1)
    highest = max(int(m.group(2)) for m in numbered if m.group(1) == prefix)
    return f'{prefix}{highest + 1}'


def render_decision(eid: str, when: str, title: str,
                    values: dict[str, str], eol: str = '\n') -> str:
    """One schema-shaped entry block. The separator is an em dash both times,
    because that is what `_DECISION_HEADER` matches — a hyphen renders
    near-identically to a human and differently to a parser."""
    lines = [f'## {eid} — {when} — {title}']
    lines += [f'**{name}:** {values[name]}' for name in DECISION_FIELDS]
    return ''.join(f'{line}{eol}' for line in lines)


def append_decision(text: str, eid: str, when: str, title: str,
                    values: dict[str, str]) -> tuple[str, list[str]]:
    """(log text with the entry appended, what the NEW entry gets wrong).

    Composed then re-parsed through D12's own predicates, so the writer refuses
    exactly what the gate would report — no second copy of the schema, and no
    way for the two to drift apart. Pre-existing violations further up a legacy
    log are the grandfather ledger's business, never this call's.
    """
    eol = '\r\n' if '\r\n' in text else '\n'
    body = text
    if body and not body.endswith(('\n', '\r')):
        body += eol
    if body and not body.endswith(eol * 2):
        body += eol
    body += render_decision(eid, when, title, values, eol)
    entries = decision_entries_in(body)
    if not entries or entries[-1].eid != eid:
        return body, ['the composed entry does not parse as a decision entry']
    last = len(entries) - 1
    return body, [why for n, _, why in decision_violations_in(entries) if n == last]


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
