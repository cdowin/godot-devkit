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
    checks = ["D1","D2","D3","D4","D5","D6","D7",   # which rules run — this
              "V1","V2","V3","V4","V5","V6"]        #   IS the stock default
    decision_grandfather = []      # D12: logs whose legacy entries predate the
                                   # schema — "<path>" or "<path>:<N entries>"
    changelog_grandfather = []     # D15: the same ledger for changelog.md
    story_lines_max      = 120     # D17: the per-grain prose caps
    feature_lines_max    = 200
    bug_lines_max        = 125
    decisions_lines_max  = 150
    changelog_lines_max  = 150
    closed_log_lines_max = 60      # D18: a `done` milestone's decision trail
    prose_grandfather    = []      # D17/D18: "<path>:<N lines>", debt only
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from godot_devkit.core.markdown import block_scan
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
# D12 is the decision-record SCHEMA and D15 the changelog's. Opt-in like the
# rest, and for one more reason: every log written before either existed
# conforms to none of it, so a consumer switching one on migrates through the
# matching grandfather ledger rather than through a red gate on upgrade day.
#
# D16 is the RELEASE gate: a `done` milestone must have release notes. Separate
# from D15 because they answer different questions — D15 asks whether what is
# written conforms, D16 asks whether anything is written at all, and a milestone
# can ship with a perfectly conforming empty log.
SCHEMA_CHECKS = ('D12', 'D15')
RELEASE_CHECKS = ('D16',)
# D17 is the prose RATCHET and D18 the closed-milestone decision trail. Opt-in
# like the rest: the caps default to one consumer's measured p90, and another
# tree's distribution is its own — a cap that fits one repo misfires on the
# next, so a consumer sets its numbers and then turns the rules on.
PROSE_CHECKS = ('D17', 'D18')
# Structural/referential integrity. ON by default: a tree that does not satisfy
# these is malformed, not merely running a different flow.
VALIDATE_CHECKS = ('V1', 'V2', 'V3', 'V4', 'V5', 'V6')
KNOWN_CHECKS = tuple(dict.fromkeys(
    DEFAULT_CHECKS + FLOW_CHECKS + RETENTION_CHECKS + SCHEMA_CHECKS
    + STRUCTURE_CHECKS + RELEASE_CHECKS + PROSE_CHECKS + VALIDATE_CHECKS))

ARCHIVE_DIR_NAME = 'zz_archive'

# --- the canonical grain structure (D13) --------------------------------------
# One shape, every grain, all lowercase. The split that makes it worth having:
#
#   decisions.md  DURABLE   — appended during the grain's life, survives close,
#                             collapses to pointers when the milestone closes.
#   changelog.md  DURABLE   — what shipped, in the words a player would use.
#                             Milestone-only, and NEVER skipped on a `done`
#                             grain: a closed milestone is exactly when its
#                             release notes matter most.
#   review.md     TRANSIENT — simplifier and reviewer both append; DELETED at
#                             close, with anything durable promoted first (D11).
#
# `handoff.md`, `changelog.md` and `bugs/` are milestone-only, ruled explicitly:
# a feature is never picked up cold on its own, a bug lives in the milestone
# that will FIX it, and a RELEASE is a milestone — a feature contributes to its
# milestone's changelog through the entry's `Evidence:` pointer, not through a
# log of its own.
#
# DIRECTORY slots are allowed but never REQUIRED, and the reason is git: an
# empty directory does not survive a clone, so requiring `design/` would mean
# 178 placeholder files or a rule that fails the moment somebody checks the
# tree out fresh. Files carry the requirement; directories carry permission.
DECISION_FILE_NAME = 'decisions.md'
CHANGELOG_FILE_NAME = 'changelog.md'
REVIEW_FILE_NAME = 'review.md'

MILESTONE_FILE_SLOTS = ('milestone.md', 'handoff.md', 'decisions.md',
                        'changelog.md', 'review.md')
MILESTONE_DIR_SLOTS = ('features', 'bugs', 'design')
FEATURE_FILE_SLOTS = ('feature.md', 'decisions.md', 'review.md')
FEATURE_DIR_SLOTS = ('stories', 'design')

# slot -> the template that mints it. The grain file's own template is named for
# the grain, the shared docs are named for the slot.
SLOT_TEMPLATE = {
    'milestone.md': 'milestone', 'feature.md': 'feature',
    'handoff.md': 'handoff', 'decisions.md': 'decisions',
    'changelog.md': 'changelog', 'review.md': 'review',
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
    'changelog.md': 'Append with `godot-devkit pm changelog <milestone-id>` — '
                    'never by hand; the command stamps the date and the next '
                    'ordinal.',
    'review.md': 'Transient. Deleted at close — promote anything durable into '
                 'decisions.md first.',
    'handoff.md': 'Cold-start only. Never restate what `pm status` computes.',
}

# The same lines as a SET, for the one reader that does not know which slot it
# is holding: D17 excludes the mandated header from every prose budget, and it
# has to do that for EVERY slot header rather than the one it was written
# against. Derived from SLOT_HEADER, never retyped — a second copy of these
# strings is a second thing to keep in step with D13.
SLOT_HEADERS = frozenset(SLOT_HEADER.values())


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
    # D12/D15 only: the grandfather ledgers, parsed at load so a malformed spec
    # is exit 2. (repo-relative log path, entries exempted or None for all).
    decision_grandfather: tuple[tuple[str, int | None], ...] = ()
    changelog_grandfather: tuple[tuple[str, int | None], ...] = ()
    # D17/D18 only: the prose caps, and the debt ledger that lets a tree over
    # them ship. Every cap is CONFIG rather than a constant — the defaults are
    # one consumer's measured p90, not a law (see PROSE_CAPS).
    story_lines_max: int = 120
    feature_lines_max: int = 200
    bug_lines_max: int = 125
    decisions_lines_max: int = 150
    changelog_lines_max: int = 150
    closed_log_lines_max: int = 60
    # (repo-relative doc path, its recorded line CEILING). Never None: a
    # whole-file exemption would be a permanent uncapped pass, which is the one
    # thing a ratchet cannot have.
    prose_grandfather: tuple[tuple[str, int], ...] = ()
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

    def cap(key: str, fallback: int) -> int:
        got = number(sect, 'pm', key, fallback)
        if got < 1:
            # A cap of 0 fails every document including an empty one, so the
            # gate would be unsatisfiable rather than strict. Refuse the value
            # instead of shipping a rule nothing can pass.
            raise ConfigError(
                f'[pm] {key} is {got} — a line cap under 1 fails every '
                f'document, including an empty one')
        return got

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
        # The `[pm]` lists whose default is EMPTY: each is a ledger of
        # exemptions, so `[]` means "none exempt" — the same thing the absent
        # key means — and refusing it made the documented default the one value
        # a repo could not write down.
        decision_grandfather=parse_grandfather(
            str_tuple(sect, 'pm', 'decision_grandfather', (), allow_empty=True),
            DECISION_SCHEMA.ledger_key, DECISION_SCHEMA.file_name),
        changelog_grandfather=parse_grandfather(
            str_tuple(sect, 'pm', 'changelog_grandfather', (), allow_empty=True),
            CHANGELOG_SCHEMA.ledger_key, CHANGELOG_SCHEMA.file_name),
        story_lines_max=cap('story_lines_max', 120),
        feature_lines_max=cap('feature_lines_max', 200),
        bug_lines_max=cap('bug_lines_max', 125),
        decisions_lines_max=cap('decisions_lines_max', 150),
        changelog_lines_max=cap('changelog_lines_max', 150),
        closed_log_lines_max=cap('closed_log_lines_max', 60),
        prose_grandfather=parse_grandfather(
            str_tuple(sect, 'pm', 'prose_grandfather', (), allow_empty=True),
            'prose_grandfather', '.md', cap_required=True),
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
    explaining how bugs are filed came out of D14 as a bug with an illegal
    status.

    THE TWO QUESTIONS ARE NOT THE SAME QUESTION. "This has no frontmatter" is a
    note and is out of scope; "this frontmatter is broken" is a grain and is a
    FINDING. Deciding scope with the strict parser answered the second with the
    first: a BOM before the `---`, a blank line before it, or a missing closing
    fence dropped the document out of the census entirely — D4, D5, V1, D14 and
    D17 all went blind at once, and D14's silence is a `prune` deleting an open
    bug with the milestone it sits in. So detection is lenient
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

    The single definition every reader shares (D2/D4's story walk, D14's bug
    lifetime, D17's prose cap, every census): a second walk would be a second
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
        every rule, but COUNTED: `0 bug(s)` must not quietly mean "one open bug
        parked under `bugs/.hold/`", which prune would then delete where it
        sits.
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


def is_transient_review_slot(cfg: PmConfig, path: Path) -> bool:
    """True when `path` is a grain's TRANSIENT `review.md`, not a durable record.

    THE close protocol used to contradict itself here. `pm feature done
    --review-record <path>` stamps `reviewed:` at whatever it is handed; D11
    then requires a `done` grain to have NO `review.md`. Point the pointer at
    the transient slot and both rules cannot hold: delete the file exactly as
    D11 says and D1 reports the feature `done w/o review record`.

    The resolution is that a review.md is scratch — reviewer and simplifier
    append to it while the grain is open — and the DURABLE record of a review is
    the decision log it fed. So the pointer must name the durable half, and this
    predicate is how the close verb refuses the transient one instead of leaving
    a human to know the rule.

    Decidable without a guess: D13 permits `review.md` only as a grain slot, so
    a file with that name anywhere inside the roadmap IS the transient slot. A
    project storing durable records as `docs/reviews/<something>.md` is
    untouched — that path is outside the tree and is not this slot.

    Judged on the path AS WRITTEN and on what it RESOLVES to, and both halves
    are load-bearing. A `durable.md -> review.md` symlink is the transient slot
    under another name, and reading only the name lets it through. A `review.md`
    symlink pointing at a durable record elsewhere is still the file D11 deletes
    at close — deleting the link strands the pointer exactly the same way — so
    the name in the tree is not forgiven by where it points either.
    """
    candidates = [path]
    try:
        candidates.append(path.resolve())
    except OSError:
        pass
    for candidate in candidates:
        if candidate.name.lower() != REVIEW_FILE_NAME:
            continue
        try:
            candidate.resolve().relative_to(cfg.roadmap.resolve())
        except (ValueError, OSError):
            continue
        return True
    return False


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
def bug_files(mdir: Path) -> list[Path]:
    """Every bug document under one milestone, in reading order."""
    return grain_docs(mdir / 'bugs')


def open_bugs_under_done(cfg: PmConfig) -> tuple[list[tuple[Path, str]], int]:
    """(findings, bugs scanned) — open bugs under a done milestone, plus any
    bug whose status is outside the vocabulary (which D4 does not cover, and
    which would otherwise read as "closed" and be passed in silence)."""
    out: list[tuple[Path, str]] = []
    scanned = 0
    for mdir in milestone_dirs(cfg):
        mstat = field_of(mdir / 'milestone.md', 'status')
        mid = unquote(field_of(mdir / 'milestone.md', 'id')) or mdir.name
        # D14 is what stops `prune` deleting an open bug with its done
        # milestone; a D14 that undercounts is not a weaker safety net, it is a
        # false one — which is why the walk it shares with D17 is recursive.
        for bfile in bug_files(mdir):
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


# --- append-only log schemas (D12, D15) ---------------------------------------
# TWO logs, ONE schema machine. A decision log rots into description and a
# changelog rots into a commit log, and the cure is the same shape both times:
# an `## <ID> — <ISO date> — <title>` heading over `**Field:**` lines, one per
# line, each capped. Padding is impossible when every part has to be a field.
#
#     ## D3 — 2026-08-28 — the sweep verb belongs to the combat layer
#     **Chose:** move `sweep_tracked_contributions` to `combat_behavior.gd`
#     **Over:** leaving it on `entity_behavior.gd`, the lean root
#     **Because:** all three consumers extend the combat layer
#     **Evidence:** `64e89ad5b`
#
#     ## C1 — 2026-08-29 — the hub remembers where you parked
#     **What:** Your loadout is where you left it when you come back to the hub.
#     **Evidence:** `64e89ad5b`
#
# What differs between them is DATA — the field list, the ordinal prefix, the
# file name, the config key its grandfather ledger lives under — so it is data,
# not a second parser, a second validator and a second writer.
#
# The two caps are module-level rather than per-schema because they are one
# fact: how much text fits on a line a human scans. `log_entries_in` needs the
# title cap without knowing which schema it is reading (it names an unnamed
# entry by its own title), so a per-schema-only home would have forced a second
# copy of the number right there.
TITLE_MAX = 80
VALUE_MAX = 200


@dataclass(frozen=True)
class LogSchema:
    """One append-only log's entry schema. D12 and D15 are two instances.

    `notes` is the WHY appended to a missing-field finding, for the field whose
    absence is the whole reason the log has a schema at all.
    """
    rule: str            # the drift rule that holds this log to the schema
    plural: str          # how a census names it ('1 decision log(s)')
    file_name: str       # the canonical slot it lives in
    fields: tuple[str, ...]
    prefix: str          # the ordinal prefix an EMPTY log starts numbering at
    ledger_key: str      # the `[pm]` key holding its grandfather ledger
    notes: tuple[tuple[str, str], ...] = ()
    title_max: int = TITLE_MAX
    value_max: int = VALUE_MAX


DECISION_SCHEMA = LogSchema(
    rule='D12', plural='decision log', file_name=DECISION_FILE_NAME,
    fields=('Chose', 'Over', 'Because', 'Evidence'), prefix='D',
    ledger_key='decision_grandfather',
    # `Over:` is the load-bearing field: a decision with no rejected alternative
    # is not a decision, it is a description, and an entry that cannot name what
    # it ruled out should not exist.
    notes=(('Over', ' — a decision with no rejected alternative is a '
                    'description'),))

# The changelog is deliberately the SMALLER schema — what was built that a
# player cares about, and the reference proving it shipped. Dev detail lives in
# decisions.md; a changelog that carries it is a commit log with a nicer name.
CHANGELOG_SCHEMA = LogSchema(
    rule='D15', plural='changelog', file_name=CHANGELOG_FILE_NAME,
    fields=('What', 'Evidence'), prefix='C',
    ledger_key='changelog_grandfather',
    notes=(('Evidence', ' — a changelog entry with nothing behind it is a '
                        'rumour'),))

# An ENTRY is an `##` heading carrying an ID or a DATE **anywhere** in it — not
# one that opens with an id. Detection has to be looser than the schema or the
# gate is blind to exactly the logs it exists for: real logs number `M27`, `D1`,
# and also write `## 2026-08-24 — D1: ...` with the id AFTER the date, which an
# opens-with-an-id test reads as prose and passes in silence (rule 4's cardinal
# sin). A heading with neither ("## The through-line") IS prose and is never
# schema-checked: a log may have a preamble.
_ENTRY_HEADING = re.compile(r'^##[ \t]+(\S.*?)[ \t]*$')
# A VERSION is not an id. `v0.9` opens with a token shaped exactly like one, so
# a changelog preamble reading `## v0.9 release notes` was read as entry `v0`
# and `next_entry_id` then allocated `v1` into a log numbering `C`. D15 makes
# version-shaped headings MORE likely, not less, so the trailing `.` is
# admitted only when no digit follows it: `D1.` ends a sentence, `v0.9` names a
# release.
_ENTRY_ID = re.compile(
    r'(?:^|[\s([{`"\'/—-])([A-Za-z]{1,4}\d+)(?=\.(?!\d)|[\s,:;)\]}`"\'—-]|$)')
_ISO_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
# The full header. The separator is an em dash BOTH times, exactly as the schema
# reads. A hyphen renders near-identically to a human and differently to a
# parser, and a separator that is "either" is not a schema.
_ENTRY_HEADER = re.compile(
    r'^##[ \t]+[A-Za-z]+\d+[ \t]+—[ \t]+(\d{4}-\d{2}-\d{2})[ \t]+—[ \t]+(\S.*?)[ \t]*$')
_ENTRY_FIELD = re.compile(r'^\*\*([A-Za-z]+):\*\*[ \t]*(.*?)[ \t]*$')
# A new `##`/`#` heading ends the entry; `###` and deeper stay inside it.
_ENTRY_SECTION_END = re.compile(r'^#{1,2}[ \t]')

# `Evidence:` is a REFERENCE, not a sentence — that is what stops "we discussed
# it and agreed" from counting as evidence. Every whitespace-separated token has
# to be a commit hash, a path (optionally `:line`), or a number; prose fails on
# its first word.
_REF_HASH = re.compile(r'^[0-9a-f]{7,40}$')
# The SAME vocabulary one abbreviation short. `aaa111` is a valid hash that git
# simply printed at six characters, and calling it prose is wrong about the
# cause and silent about the fix — so it gets its own refusal, naming the
# minimum and the command that lengthens it.
REF_HASH_MIN = 7
_REF_SHORT_HASH = re.compile(r'^[0-9a-f]{1,6}$')
_REF_NUMBER = re.compile(r'^[+-]?\d[\d,._%/x×→-]*$')
_REF_PATH = re.compile(r'^[\w./~@+-]+(?::\d+(?:-\d+)?)?$')


@dataclass(frozen=True)
class LogEntry:
    eid: str
    line: int
    header: str
    fields: tuple[tuple[str, str], ...]


_EVIDENCE_PROSE = ('**Evidence:** is prose, not a reference — want a commit '
                   'hash, a path[:line], or a number')


def evidence_defect(value: str) -> str:
    """'' when every token in `value` is a hash, a path[:line] or a number,
    else the reason — NAMING the change that resolves it.

    Returns the reason rather than a bool because the two ways a reference
    fails are not the same mistake. A six-character `aaa111` is a real commit
    hash git abbreviated one character short of what this accepts, and the
    prose refusal misidentifies the cause AND leaves the author with nothing to
    do about it. The too-short refusal names the minimum and prints the
    `git rev-parse` that lengthens the hash, the way the scaffolder's refusals
    print the exact `git mv --force` to run.
    """
    tokens = [raw.strip('[]()<>,;.:"\'')
              for raw in value.replace('`', ' ').split()]
    if not tokens:
        return _EVIDENCE_PROSE
    for tok in tokens:
        if not tok:
            return _EVIDENCE_PROSE
        if _REF_HASH.match(tok) or _REF_NUMBER.match(tok):
            continue
        # A path must LOOK like one. Without this, any bare word matches.
        if _REF_PATH.match(tok) and ('/' in tok or '.' in tok):
            continue
        # Only when the WHOLE value is that one token. A sentence whose first
        # bad word happens to be hex — "added a cafe" — is prose, and telling
        # its author about commit-hash length would be the same misdiagnosis
        # in the other direction.
        if len(tokens) == 1 and _REF_SHORT_HASH.match(tok):
            return (f'**Evidence:** {tok!r} is {len(tok)} chars — a commit '
                    f'hash needs at least {REF_HASH_MIN}; lengthen it with '
                    f'`git rev-parse --short={REF_HASH_MIN} {tok}`')
        return _EVIDENCE_PROSE
    return ''


def entry_label(heading_text: str) -> str:
    """How a finding NAMES this entry — its id, else its date, else ''.

    NOT the detector. '' means only that the heading names itself neither way;
    whether the block IS an entry is decided by its BODY (see
    `log_entries_in`), because a heuristic guessing which text is a record
    from the record's title is the defect this rule exists to catch.
    """
    ident = _ENTRY_ID.search(heading_text)
    if ident:
        return ident.group(1)
    when = _ISO_DATE.search(heading_text)
    return when.group(0) if when else ''


def log_files(cfg: PmConfig, schema: LogSchema) -> tuple[list[Path], list[Path]]:
    """(the logs, the case-variant files) in the ACTIVE tree.

    EXACT names, from a directory listing — never `rglob(schema.file_name)`.
    A pattern whose final segment holds no wildcard resolves through
    `Path.exists()`, so on macOS `rglob('decisions.md')` answers an on-disk
    `DECISIONS.md` with the path `x/decisions.md`: a path that does not exist,
    a grandfather key authorable on exactly one platform, and — the moment ONE
    log of a tree is migrated — a NON-EMPTY list, which is what silences the
    scanned-nothing guard while every other log goes unopened.

    A `.md` whose lowercased name matches but whose bytes differ is returned
    separately to be REPORTED: never folded in (the two platforms would emit
    opposite findings about the same file) and never dropped (a log the rule
    cannot see is a log the rule has not checked).

    Archived logs predate the schema and are skipped.
    """
    return walk.named(cfg.roadmap, schema.file_name, prune=(ARCHIVE_DIR_NAME,))


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

    A fenced block is a code sample the reader sees verbatim: `## <short title>`
    inside one is not a heading and `<!--` inside one is a marker being quoted.
    Fenced lines are dead here for that reason — counting a template's example
    block as a real entry is the same lie in the other direction.

    WHERE the fences and the comments are is `core.markdown.block_scan`'s
    answer, not a second one: `check doc` and `check agents` read the same
    markdown under the same CommonMark rules, and two scanners would drift into
    disagreeing about which lines a document even has. It settles both markers
    in ONE ordered pass, which is the only way to get both right — a fence
    quoted inside a CLOSED comment used to be reported malformed, because the
    fences were decided before anything knew where the comments were.
    """
    scan = block_scan(lines, comments=True)
    live = [not f for f in scan.fenced]
    text = list(lines)
    for opened, closed, after in scan.comment_spans:
        if closed == opened:
            continue  # opened and closed inline: the line was never suppressed
        for k in range(opened + 1, closed):
            live[k] = False
        text[closed] = lines[closed][after:].lstrip(' \t')
    return live, text, scan.unclosed, scan.unterminated


def log_comment_defect(text: str, rule: str) -> str:
    """'' when the log's HTML comments are all closed, else what is wrong.

    Separate from the entry list on purpose: this is a defect of the LOG, not
    of any entry, so no grandfather ordinal caps it and no entry name carries
    it. `rule` names the rule reporting it, because the same defect in a
    decisions.md and in a changelog.md is found by D12 and by D15.
    """
    _, _, unclosed, _ = _comment_scan(_split(text))
    if not unclosed:
        return ''
    return (f'line {unclosed} opens an HTML comment `<!--` that is never '
            f'closed — the log is malformed and {rule} cannot say what it '
            f'holds; close it, or put the marker in backticks if you meant to '
            f'name it')


def log_fence_defect(text: str, rule: str) -> str:
    """'' when the log's code fences are all terminated, else what is wrong.

    The twin of `log_comment_defect`, and it exists for the same reason.
    Fence masking was added so a quoted `<!--` inside a sample stopped eating
    the log; an unterminated fence then ate the log by the other route, and did
    it in SILENCE — `1 entry/ies … PASS` over a two-entry file. A mask nothing
    reports is the defect, whichever marker opened it.
    """
    _, _, _, unfenced = _comment_scan(_split(text))
    if not unfenced:
        return ''
    return (f'line {unfenced} opens a code fence that is never terminated — '
            f'the log is malformed and {rule} cannot say which of it is a '
            f'sample; close the fence, or shorten the run of backticks if you '
            f'meant an inline span')


def log_entries_in(text: str) -> list[LogEntry]:
    """Every entry in a log's TEXT, so a candidate entry can be validated
    against the gate's own regexes BEFORE it is written rather than after.

    SCHEMA-FREE by design, and it is the same parse for a decisions.md and a
    changelog.md: what an entry IS does not depend on which fields it should
    carry. That is what lets a log missing every field still be SEEN and
    reported, rather than read as prose and passed in silence.

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
    out: list[LogEntry] = []
    for i, raw in enumerate(body):
        if not live[i]:
            continue
        m = _ENTRY_HEADING.match(raw.rstrip('\r'))
        if not m:
            continue
        stop = len(lines)
        for j in range(i + 1, len(lines)):
            if live[j] and _ENTRY_SECTION_END.match(body[j].rstrip('\r')):
                stop = j
                break
        fields: list[tuple[str, str]] = []
        for j in range(i + 1, stop):
            if not live[j]:
                continue
            fm = _ENTRY_FIELD.match(body[j].rstrip('\r'))
            if fm:
                fields.append((fm.group(1), fm.group(2)))
        eid = entry_label(m.group(1))
        if not eid:
            if not fields:
                continue
            # It IS an entry and still has to be named. Its own title is the
            # only handle it has; a finding naming nothing cannot be acted on.
            flat = ' '.join(m.group(1).split())
            eid = (flat if len(flat) <= TITLE_MAX
                   else flat[:TITLE_MAX - 1] + '…')
        out.append(LogEntry(eid=eid, line=i + 1,
                                 header=body[i].rstrip('\r'),
                                 fields=tuple(fields)))
    return out


def entry_title(entry: LogEntry) -> str:
    """The entry's own title from its header, or its id when it has none.

    A render needs a handle for every entry it prints, INCLUDING one whose
    header does not conform — dropping the non-conforming ones would make the
    render disagree with the gate about what the log holds.
    """
    head = _ENTRY_HEADER.match(entry.header)
    return head.group(2) if head else entry.eid


def entry_violations_in(entries: list[LogEntry],
                        schema: LogSchema) -> list[tuple[int, str, str]]:
    """[(ordinal, entry-id, what failed)], in document order, over already-parsed
    entries. The ordinal is the entry's 0-based position, which is what a
    `path:N` grandfather caps: a log is append-only, so "the first N" is stable.

    ONE implementation, for BOTH logs and for both readers: `pm decide` and
    `pm changelog` each validate their candidate through this, so a writer
    cannot disagree with its gate about what conforms."""
    out: list[tuple[int, str, str]] = []
    notes = dict(schema.notes)
    for n, entry in enumerate(entries):
        def bad(msg: str, _n: int = n, _e: str = entry.eid) -> None:
            out.append((_n, _e, msg))

        head = _ENTRY_HEADER.match(entry.header)
        if head is None:
            bad('header is not `## <ID> — <ISO date> — <title>` (em dashes)')
        else:
            try:
                date.fromisoformat(head.group(1))
            except ValueError:
                bad(f'header date {head.group(1)!r} is not a real date')
            if len(head.group(2)) > schema.title_max:
                bad(f'title is {len(head.group(2))} chars, over the '
                    f'{schema.title_max}-char cap')

        names = [n_ for n_, _ in entry.fields]
        at = -1
        for want in schema.fields:
            if want not in names:
                bad(f'missing **{want}:**{notes.get(want, "")}')
                continue
            here = names.index(want)
            if here <= at:
                bad(f'**{want}:** is out of order — the fields read '
                    f'{", ".join(schema.fields)}')
            at = max(at, here)
        for name, value in entry.fields:
            if name in schema.fields and len(value) > schema.value_max:
                bad(f'**{name}:** is {len(value)} chars, over the '
                    f'{schema.value_max}-char cap')
        if 'Evidence' not in schema.fields:
            continue
        for name, value in entry.fields:
            if name != 'Evidence':
                continue
            defect = evidence_defect(value)
            if defect:
                bad(defect)
            break
    return out


# --- writing an entry (`pm decide`, `pm changelog`) ----------------------------
_ENTRY_ORDINAL = re.compile(r'^([A-Za-z]{1,4})(\d+)$')

# The sentence `pm collapse` writes in place of the entries it retires. It lives
# HERE and not in the verb that writes it, because the allocator has to read it:
# a collapsed entry is gone from the file, and an allocator that sees only what
# is still present will hand its id out a second time.
COLLAPSE_MARKER = 'Collapsed at close'
# The pointer's machine-read slot. Everything before it is prose for a human;
# this is the one place the allocator looks, so a rule id quoted in the
# explanation ("D16's separation from D15") can never be mistaken for a
# retired entry.
SPENT_IDS_LABEL = 'Ids spent, never minted again:'


def collapse_pointers(text: str) -> list[tuple[int, str]]:
    """[(1-based line, the pointer's whole paragraph)] for each collapse pointer.

    A PARAGRAPH, not a line: the pointer is wrapped to fit a diff, so its id
    list routinely spans two of them. The paragraph ends at the first blank
    line, which is what keeps a `--note` (written after a blank line) out of the
    id list — a note quoting `D4` must not make D4 look retired.
    """
    lines = _split(text)
    live, body, _, _ = _comment_scan(lines)
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(body):
        if not live[i] or COLLAPSE_MARKER not in raw:
            continue
        block = [raw.rstrip('\r')]
        for j in range(i + 1, len(lines)):
            if not live[j] or not body[j].strip():
                break
            block.append(body[j].rstrip('\r'))
        out.append((i + 1, '\n'.join(block)))
    return out


def spent_entry_ids(text: str) -> tuple[set[str], list[str]]:
    """(the ids this log's collapse pointers record as retired, what is wrong).

    The ids are the RECORD of entries the file no longer holds. Without them an
    allocator counting only present entries re-mints `D3` three lines under a
    pointer saying D3 was collapsed — one file, two different D3s, and no gate
    can see it, because a pointer is prose.

    Read from a LABELLED slot and never from the paragraph's prose. The first
    cut of this scanned the whole pointer for id-shaped tokens and immediately
    read `D16's separation from D15` — two RULE names in a hand-written pointer
    — as two retired entries, which is a false claim in a gate. An id list a
    machine reads has to be somewhere a machine can point at.

    A pointer with no such slot is REPORTED, never read as "nothing was
    retired": that is the hand-edited case, and guessing there is exactly the
    silent re-mint this exists to stop.
    """
    ids: set[str] = set()
    defects: list[str] = []
    for line, block in collapse_pointers(text):
        # Whitespace-normalised, because the pointer is wrapped to fit a diff
        # and the label itself can land across two lines.
        flat = ' '.join(block.split())
        _, sep, tail = flat.partition(SPENT_IDS_LABEL)
        if not sep:
            defects.append(
                f'line {line} carries a `{COLLAPSE_MARKER}` pointer with no '
                f'`{SPENT_IDS_LABEL}` list, so nothing can tell which ids it '
                f'retired — an append would risk re-minting one. Add the list '
                f'the way `pm collapse` writes it: `{SPENT_IDS_LABEL} D1, D3, '
                f'D4.`')
            continue
        for token in tail.strip().rstrip('.').replace(',', ' ').split():
            if _ENTRY_ORDINAL.match(token):
                ids.add(token)
            else:
                # Loud: a token that is not an id in the one place ids are read
                # means the list has been edited into prose, and quietly
                # dropping it would shrink the spent set without saying so.
                defects.append(
                    f'line {line}: `{SPENT_IDS_LABEL}` lists {token!r}, which '
                    f'is not an entry id — that slot holds ids and nothing '
                    f'else, so the retired set cannot be trusted')
    return ids, defects


def next_entry_id(entries: list[LogEntry], schema: LogSchema,
                  spent: set[str] | tuple[str, ...] = ()) -> str:
    """The next id for this log — the two things authors get wrong, allocated.

    The PREFIX comes from the log's own last id-shaped entry, so a tree that
    numbers `M27` keeps numbering `M`. An empty log (or one whose headings are
    all dates) starts at the schema's own prefix: `D1` for decisions, `C1` for
    a changelog.

    `spent` is what a COLLAPSE retired. An id is never re-minted within one
    file, whether or not its entry is still in it — a fully collapsed log whose
    pointer records D1-D5 allocates D6, not D1. Reuse across FILES stays by
    design: 0.14.0's D7 and 0.15.0's D7 are different decisions in different
    logs, and numbering every milestone from a global counter would say they
    were related.
    """
    numbered = [m for m in (_ENTRY_ORDINAL.match(e.eid) for e in entries) if m]
    retired = [m for m in (_ENTRY_ORDINAL.match(s) for s in sorted(spent)) if m]
    if numbered:
        prefix = numbered[-1].group(1)
    elif retired:
        # Nothing is left in the file, so the pointer is the only surviving
        # record of how this log numbers itself. Falling back to the schema
        # prefix here would restart at D1 — on top of every id it just retired.
        prefix = retired[-1].group(1)
    else:
        return f'{schema.prefix}1'
    highest = max((int(m.group(2)) for m in numbered + retired
                   if m.group(1) == prefix), default=0)
    return f'{prefix}{highest + 1}'


def render_entry(eid: str, when: str, title: str, values: dict[str, str],
                 schema: LogSchema, eol: str = '\n') -> str:
    """One schema-shaped entry block. The separator is an em dash both times,
    because that is what `_ENTRY_HEADER` matches — a hyphen renders
    near-identically to a human and differently to a parser."""
    lines = [f'## {eid} — {when} — {title}']
    lines += [f'**{name}:** {values[name]}' for name in schema.fields]
    return ''.join(f'{line}{eol}' for line in lines)


def append_entry(text: str, eid: str, when: str, title: str,
                 values: dict[str, str],
                 schema: LogSchema) -> tuple[str, list[str]]:
    """(log text with the entry appended, what the NEW entry gets wrong).

    Composed then re-parsed through the GATE's own predicates, so the writer
    refuses exactly what the gate would report — no second copy of the schema,
    and no way for the two to drift apart. Pre-existing violations further up a
    legacy log are the grandfather ledger's business, never this call's.
    """
    eol = '\r\n' if '\r\n' in text else '\n'
    body = text
    if body and not body.endswith(('\n', '\r')):
        body += eol
    if body and not body.endswith(eol * 2):
        body += eol
    body += render_entry(eid, when, title, values, schema, eol)
    entries = log_entries_in(body)
    if not entries or entries[-1].eid != eid:
        return body, ['the composed entry does not parse as a log entry']
    last = len(entries) - 1
    return body, [why for n, _, why
                  in entry_violations_in(entries, schema) if n == last]


def parse_grandfather(specs: tuple[str, ...], key_name: str, suffix: str,
                      cap_required: bool = False
                      ) -> tuple[tuple[str, int | None], ...]:
    """`"<path>"` (the whole file) or `"<path>:<N>"` (its first N / its first N
    lines, depending on which ledger is reading).

    The capped form is the point: a grandfathered log keeps its legacy entries
    and every entry ADDED past the cap still has to conform, so the log stops
    growing badly without anyone rewriting old text. A malformed spec is a
    CONFIG error (exit 2), never a finding.

    ONE implementation over all three ledgers. `decision_grandfather`,
    `changelog_grandfather` and `prose_grandfather` differ in which file name a
    key must end with and in whether the number is optional — data, passed in.
    Three copies of this would be three chances to accept a spec the others
    reject, and the ledger form is the thing a consumer hand-writes.

    `cap_required` is the RATCHET's half: D17's ledger records a line ceiling,
    and an entry without one would be a permanent uncapped pass — exactly what
    a ratchet cannot have.
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
                    f'[pm] {key_name} {spec!r} caps 0 entries — drop '
                    f'the ":0" to exempt nothing at all')
        elif sep:
            raise ConfigError(
                f'[pm] {key_name} {spec!r} has a ":" but no entry '
                f'count — write "<path>" or "<path>:<N>"')
        key = raw.replace('\\', '/')
        while key.startswith('./'):
            key = key[2:]
        if not key:
            raise ConfigError(f'[pm] {key_name} {spec!r} names no path')
        if not key.endswith(suffix):
            raise ConfigError(
                f'[pm] {key_name} {spec!r} does not name a '
                f'{suffix} — the ledger names files, not directories')
        if cap is None and cap_required:
            raise ConfigError(
                f'[pm] {key_name} {spec!r} records no line ceiling — write '
                f'"<path>:<N lines>"; an entry with no ceiling never fails, '
                f'and a ratchet with a permanent pass in it is decorative')
        if key in seen:
            raise ConfigError(
                f'[pm] {key_name} names {key} twice — one entry per file')
        seen.add(key)
        out.append((key, cap))
    return tuple(out)


def relkey(cfg: PmConfig, path: Path) -> str:
    """The repo-relative, forward-slashed key a ledger spec is matched on.

    One spelling for all three ledgers, so a path a consumer writes into
    `decision_grandfather` is keyed exactly as one written into
    `prose_grandfather`.
    """
    return cfg.rel(path).replace('\\', '/')


def ledger_for(cfg: PmConfig, schema: LogSchema) -> dict[str, int | None]:
    """The grandfather ledger this schema's rule reads, keyed by log path.

    The schema names its own config key, so a caller holding a schema never has
    to know which attribute of PmConfig carries its exemptions — which is what
    keeps D12 and D15 one code path instead of two with a branch in them.
    """
    return dict(getattr(cfg, schema.ledger_key))


# --- the changelog union (`pm changelog --render`, D16) ----------------------
# A changelog is only worth having if "the notes for milestone xyz" is the SAME
# answer every time. So the union is ordered by two totally-ordered keys and
# never by a directory walk: milestones by DECLARED VERSION, entries by the
# order the log itself holds them in (append-only, so that is the order they
# were written).
def milestones_newest_first(cfg: PmConfig) -> list[tuple[str, Path]]:
    """(declared id, dir) for the ACTIVE tree, newest release first.

    By the DECLARED VERSION, compared component-wise — never a string sort of
    the directory name. `0.10` sorts BEFORE `0.9` lexically and after it
    numerically, so a string sort publishes 0.9 as the newest release: wrong in
    the one place a reader trusts a changelog most. `version_key` is the same
    comparison `prune`'s lag-by-one already makes about which milestone is
    newest, so the two cannot disagree about the order of a tree.

    The id, then the directory name, break a tie — two milestones declaring one
    version still come out in the same order on every filesystem, where the
    walk order alone would vary.
    """
    out = [(unquote(field_of(d / 'milestone.md', 'id')) or d.name, d)
           for d in milestone_dirs(cfg)]
    return sorted(out, key=lambda t: (version_key(t[0]), t[0], t[1].name),
                  reverse=True)


def changelog_entries_of(mdir: Path) -> tuple[list[LogEntry], str]:
    """(the milestone's changelog entries, why there are none).

    The reason is not decoration: "this milestone shipped nothing worth saying"
    and "this milestone's log could not be opened" are different facts, and a
    render that prints an empty section for both is lying about one of them.
    """
    if dir_entries(mdir).get(CHANGELOG_FILE_NAME) != 'file':
        return [], f'no {CHANGELOG_FILE_NAME}'
    try:
        text = read_raw(mdir / CHANGELOG_FILE_NAME)
    except (OSError, UnicodeDecodeError) as err:
        return [], f'{CHANGELOG_FILE_NAME} cannot be read ({err})'
    entries = log_entries_in(text)
    return entries, '' if entries else 'no entries yet'


def milestones_without_notes(cfg: PmConfig) -> tuple[list[tuple[Path, str]], int]:
    """D16 — (findings, `done` milestones scanned).

    A release that ships with no notes is the one this stops. The bar is a
    changelog that EXISTS, holds at least one entry, and holds at least one
    entry D15 does not report — a log of four malformed blocks is not release
    notes, it is four malformed blocks.

    The `changelog_grandfather` cap suppresses here exactly as it does in D15:
    a legacy entry D15 has been told to accept is an entry D16 must accept too,
    or turning both rules on at once would be permanently red for a consumer
    whose migration is the ledger.
    """
    ledger = ledger_for(cfg, CHANGELOG_SCHEMA)
    out: list[tuple[Path, str]] = []
    scanned = 0
    for mdir in milestone_dirs(cfg):
        mfile = mdir / 'milestone.md'
        if field_of(mfile, 'status') != 'done':
            continue
        scanned += 1
        mid = unquote(field_of(mfile, 'id')) or mdir.name
        path = mdir / CHANGELOG_FILE_NAME
        entries, why = changelog_entries_of(mdir)
        if why:
            out.append((path, f'milestone {mid} is done and has {why} — a '
                              f'release ships with notes; append them with '
                              f'`pm changelog {mid}`'))
            continue
        cap = ledger.get(relkey(cfg, path), 0)
        broken = {n for n, _, _ in entry_violations_in(entries, CHANGELOG_SCHEMA)}
        if any(n not in broken or cap is None or n < cap
               for n in range(len(entries))):
            continue
        out.append((path, f'milestone {mid} is done and every one of its '
                          f'{len(entries)} changelog entries is malformed — '
                          f'no reader can tell what shipped'))
    return out, scanned


# --- the prose ratchet (D17, D18) ---------------------------------------------
# WHY THIS EXISTS: everything written into a PM tree is grep-reachable, so every
# line of PM prose is a line some future agent may pull into its context and
# reason from. The scaffolding should not be twice the size of the thing it
# scaffolds. The close-evidence budget is already stated in prose — "≤5 lines"
# for a story close, "a line and a link" for a milestone — and nothing enforced
# any of it; one consumer measured 48,704 lines across 235 stories, 136
# feature.md, 89 bugs and 57 decisions.md, with individual files at 774 and 567.
#
# HONEST SCOPE: this counts lines. It cannot tell 200 earned lines of authored
# tables from 200 lines of restated commit messages — that judgement stays with
# the PO and the reviewer. What it can do is stop the corpus growing while
# nobody is looking, which is what happened.
#
# A RATCHET, not a big bang. Every already-over-cap document is recorded in
# `[pm] prose_grandfather` at its CURRENT size, and the gate fails only when a
# ledgered document GROWS past its recorded ceiling (GREW) or a new one crosses
# its cap (OVERCAP). The ledger is a DEBT ledger: its length is the metric, and
# `pm prose-ledger` REFUSES TO RAISE AN EXISTING CEILING. Without that refusal
# the gate is decorative — every growth would be absorbed by a regeneration.
#
# WHAT IS ENFORCED, EXACTLY: no recorded ceiling ever rises, and a document
# back inside its cap is dropped rather than re-recorded. A document that has
# newly crossed its cap DOES come out as a new ledger line — a regeneration
# that could not record new debt could not be run on a growing tree at all. It
# is not silent: `pm prose-ledger` names every newly absorbed document on
# stderr with a count, and the line itself is a `devkit.toml` diff a human has
# to paste. "The ledger may only ever shrink" would be a stronger claim than
# the code makes, and a gate whose docstring overstates it is a gate people
# stop reading.
#
# THREE THINGS THAT ARE NOT OBVIOUS AND ARE LOAD-BEARING:
#
#  1. A MILESTONE'S OWN `decisions.md` IS NOT CAPPED WHILE ITS MILESTONE IS
#     OPEN. It is the append-only autonomous-mode trail by design, and it is
#     routinely the largest file in the tree. Capping it fights the process.
#     What IS a finding is a CLOSED milestone still carrying its raw log — that
#     is D18, and its threshold is derived from the close rule ("close evidence
#     is pointers, a line and a link") rather than from any distribution: about
#     twenty pointer lines plus headers, an order of magnitude above "a line and
#     a link" and an order of magnitude below what a live trail reaches.
#
#  2. THE TOOL-MANDATED INSTRUCTION HEADER IS EXCLUDED FROM EVERY LINE COUNT.
#     D13 asserts that header is present, so it is a constant an author cannot
#     trim — counting it against a prose budget makes the budget uncompliable
#     and silently shrinks every cap. `doc_lines` drops it for EVERY slot
#     header (SLOT_HEADERS), not just the decisions one.
#
#  3. THE CAPS ARE CONFIG, NOT CONSTANTS. The defaults below are ONE consumer's
#     measured p90 — the median document is untouched and only the outliers must
#     shrink. Another tree's distribution is its own, and hardcoding one repo's
#     numbers into a shared toolkit is a gate that fits that repo and misfires
#     on the next. Every cap is a `[pm]` key.
#
# This is a SHAPE gate, not a style gate: a story that genuinely needs 200 lines
# is usually two stories.
def doc_lines(path: Path) -> int:
    """Line count for a PM document, EXCLUDING the mandated instruction header.

    D13 asserts each shared doc opens with its SLOT_HEADER line, so that line —
    and the blank line separating it from the body — is a constant an author
    cannot trim. Counting it against a prose budget makes the budget
    uncompliable and silently shrinks every cap by two.

    A file's final newline TERMINATES its last line rather than starting an
    empty one, which is `wc -l`'s reading; a final line with no newline is still
    counted, which is not. The difference shows up only on a file that does not
    end in a newline, and there the honest answer is the larger one.
    """
    try:
        lines = _split(read_raw(path))
    except (OSError, UnicodeDecodeError):
        return 0
    if lines and lines[-1] == '':
        lines.pop()
    total = len(lines)
    head = next((n for n, line in enumerate(lines) if line.strip()), None)
    if head is None or lines[head].strip() not in SLOT_HEADERS:
        return total
    total -= 1
    if head + 1 < len(lines) and not lines[head + 1].strip():
        total -= 1
    return total


@dataclass(frozen=True)
class ProseDoc:
    """One measured grain document: what it is, what it may be, what it is."""
    kind: str    # story | feature | bug | decisions | changelog | closed-log
    rule: str    # the rule that reports it over cap — D17, or D18 for a closed log
    cap: int
    path: Path
    key: str     # repo-relative, forward-slashed — the ledger's spelling
    lines: int


def prose_docs(cfg: PmConfig) -> list[ProseDoc]:
    """Every capped grain document in the ACTIVE tree, in reading order.

    IN SCOPE: a story, a feature.md, a bug, a feature's decisions.md, a
    milestone's changelog.md — and, for D18 only, a DONE milestone's
    decisions.md.

    OUT OF SCOPE, deliberately: an OPEN milestone's decisions.md (the
    append-only trail, see note 1 above), milestone.md, handoff.md, review.md
    and anything under `design/`. Those are not prose budgets — a milestone.md
    is frontmatter and a scope statement, a review.md is transient and D11
    deletes it at close, and `design/` is where a feature.md over its cap is
    told to put the design it is carrying. Capping the destination too would
    leave the author nowhere to go.

    The walk reuses the discovery every other rule uses — `milestone_dirs`,
    `feature_files`, `story_files`, `bug_files`, `dir_entries` — so D17 and D13
    can never disagree about which documents the tree holds.
    """
    out: list[ProseDoc] = []

    def add(kind: str, rule: str, cap: int, path: Path) -> None:
        out.append(ProseDoc(kind=kind, rule=rule, cap=cap, path=path,
                            key=relkey(cfg, path), lines=doc_lines(path)))

    for mdir in milestone_dirs(cfg):
        mfile = mdir / 'milestone.md'
        entries = dir_entries(mdir)
        for ffile in feature_files(mdir):
            add('feature', 'D17', cfg.feature_lines_max, ffile)
            for sfile in story_files(ffile):
                add('story', 'D17', cfg.story_lines_max, sfile)
            if dir_entries(ffile.parent).get(DECISION_FILE_NAME) == 'file':
                add('decisions', 'D17', cfg.decisions_lines_max,
                    ffile.parent / DECISION_FILE_NAME)
        for bfile in bug_files(mdir):
            add('bug', 'D17', cfg.bug_lines_max, bfile)
        # The changelog accumulates by design exactly as a decision log does,
        # and stopping it growing without bound is the whole reason it is a
        # written-by-the-tool slot rather than a free-text file.
        if entries.get(CHANGELOG_FILE_NAME) == 'file':
            add('changelog', 'D17', cfg.changelog_lines_max,
                mdir / CHANGELOG_FILE_NAME)
        # D18. The OPEN half of this file is out of scope on purpose — see
        # note 1. Only a milestone that has already closed is measured.
        if (entries.get(DECISION_FILE_NAME) == 'file'
                and field_of(mfile, 'status') == 'done'):
            add('closed-log', 'D18', cfg.closed_log_lines_max,
                mdir / DECISION_FILE_NAME)
    return out


# The ledger's own hygiene is reported under whichever prose rule is enabled:
# one `[pm]` key serves both rules, so its integrity is one fact, not two.
LEDGER_FINDING = 'LEDGER'

# What an over-cap document of THIS kind is usually carrying. A finding that
# tells a decisions.md "a story over its cap is usually two stories" is naming
# the wrong grain and the reader has to translate it; the whole value of the
# sentence is that it says where the lines went.
OVERCAP_ADVICE = {
    'story': 'a story over its cap is usually two stories',
    'feature': 'a feature.md over its cap is carrying design that belongs in '
               'a design/ note',
    'bug': 'a bug over its cap is carrying a repro transcript — link it '
           'rather than paste it',
    'decisions': 'a decisions.md over its cap is carrying narrative in its '
                 'entries — a decision is four fields',
    'changelog': 'a changelog.md over its cap is carrying a devlog — an entry '
                 'is what shipped and the reference proving it',
}


def prose_findings(cfg: PmConfig,
                   docs: list[ProseDoc]) -> list[tuple[str, str]]:
    """[(rule, message)] — the ratchet's findings and the ledger's own hygiene.

    Measurement is INDEPENDENT of which rules are enabled, and only the
    reporting is filtered. Otherwise a ledger entry for a story would "suppress
    nothing" whenever D17 happened to be off, and the shrink-only rule would
    delete the debt record of a document nobody had looked at.

    Three classes, and the shrink-only ledger rules `decision_grandfather`
    already has:
      GREW       — ledgered and larger than its recorded ceiling.
      OVERCAP    — over its grain's cap and not on the ledger.
      CLOSED-LOG — a `done` milestone still carrying its raw decision trail.
    """
    ledger = dict(cfg.prose_grandfather)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for doc in docs:
        ceiling = ledger.get(doc.key)
        if ceiling is None:
            if doc.lines <= doc.cap:
                continue
            if doc.kind == 'closed-log':
                out.append((doc.rule, (
                    f'CLOSED-LOG  {doc.key} — {doc.lines} lines of raw '
                    f'decision trail on a `done` milestone (cap '
                    f'{doc.cap}); close evidence is pointers, a line and a '
                    f'link, and the detail lives at the feature grain')))
            else:
                out.append((doc.rule, (
                    f'OVERCAP     {doc.key} — {doc.lines} lines, over the '
                    f'{doc.kind} cap of {doc.cap} and not on the ledger; '
                    + OVERCAP_ADVICE[doc.kind])))
            continue
        seen.add(doc.key)
        if doc.lines > ceiling:
            out.append((doc.rule, (
                f'GREW        {doc.key} — {doc.lines} lines, past its '
                f'prose_grandfather ceiling of {ceiling}; the ledger only '
                f'shrinks, so trim it rather than regenerate')))
            continue
        # Shrink-only, both directions, exactly as the log ledgers are: an
        # entry that suppresses nothing has done its job and must go, and a
        # ceiling reaching past the end of the file is a claim the file no
        # longer supports.
        #
        # ONE FACT, ONE FINDING. A document back inside its cap is ALSO smaller
        # than its ceiling, so reporting both told the reader to lower a
        # ceiling on a line they were being told to delete. The drop subsumes
        # the lower, so the drop is the only finding.
        if doc.lines <= doc.cap:
            out.append((LEDGER_FINDING, (
                f'{doc.key} is in prose_grandfather but {doc.lines} lines is '
                f'inside the {doc.kind} cap of {doc.cap} — drop it from the '
                f'ledger')))
        elif ceiling > doc.lines:
            out.append((LEDGER_FINDING, (
                f'{doc.key} is ledgered at {ceiling} lines but the document '
                f'has {doc.lines} — lower the ceiling')))
    for key in ledger:
        if key not in seen:
            out.append((LEDGER_FINDING, (
                f'{key} is in prose_grandfather but no such grain document '
                f'exists — drop it from the ledger')))
    return out


def regenerate_prose_ledger(
        cfg: PmConfig,
        docs: list[ProseDoc]) -> tuple[list[str], list[str], list[str]]:
    """(the `"<path>:<lines>"` entries, the growths REFUSED, the ABSORPTIONS).

    The refusal is the load-bearing half. A regeneration that raised an
    existing ceiling would make the ratchet decorative: every over-cap document
    would simply be re-recorded at its new size and the gate would never fail.
    So a document larger than its recorded ceiling is refused, and the only way
    past it is a genuine trim.

    What this does NOT refuse is a document that has newly crossed its cap and
    is on no ledger line yet — it comes out as a new entry, because a
    regeneration that could not record new debt could never be run on a growing
    tree at all. That absorption is not silent and it is not this function's to
    approve: the new keys come back NAMED, the verb prints them, and the entry
    itself is a visible diff in `devkit.toml` that a human has to paste. The
    ratchet is "no ceiling ever rises", not "the ledger never gains a line".

    What comes out is gate-clean by construction — a document back inside its
    cap is DROPPED rather than re-recorded, which is the same shrink the
    "suppresses nothing" finding asks for by hand.
    """
    ledger = dict(cfg.prose_grandfather)
    body: list[str] = []
    refused: list[str] = []
    absorbed: list[str] = []
    for doc in docs:
        ceiling = ledger.get(doc.key)
        if ceiling is not None and doc.lines > ceiling:
            refused.append(f'{doc.key} is {doc.lines} lines, past its ledger '
                           f'ceiling of {ceiling}')
            continue
        if doc.lines > doc.cap:
            body.append(f'{doc.key}:{doc.lines}')
            if ceiling is None:
                absorbed.append(f'{doc.key}:{doc.lines} ({doc.kind} cap '
                                f'{doc.cap})')
    return body, refused, absorbed
