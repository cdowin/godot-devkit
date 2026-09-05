"""model.py — the PM-tree invariants, single-sourced.

Everything the status CLI and the drift gate must agree on byte-for-byte: the
status vocabularies, the id <-> filesystem-path convention, frontmatter
read/write, THE definition of "a feature has a review record", and the drift
predicates. Two readers, one definition — the gate and the tool cannot describe
"reviewed" or "drift" differently.

Config: `[pm]` in the consuming repo's devkit.toml. Every key has a stock
default, so a repo with no devkit.toml behaves identically to one declaring the
defaults.

    [pm]
    roadmap_dir  = "pm/roadmap"    # the tree, relative to the repo root
    review_dir   = "docs/reviews"  # where review records live
    review_slug_fallback = false   # also accept <review_dir>/<feature-slug>*.md
    story_ordinal_prefix = false   # also resolve stories/NN-<slug>.md
    milestone_states      = [...]  # vocabulary overrides
    feature_states        = [...]
    story_states          = [...]
    bug_states            = [...]  # D4: the bug vocabulary
    checks = ["D1","D2","D3","D4","D5","D6",        # which rules run — this
              "V1","V2","V3","V4","V5"]             #   IS the stock default
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.core import apply, walk
from godot_devkit.core.walk import Kind, SkipReason, Walk
from godot_devkit.core.project import repo_root
from godot_devkit.core.config import (ConfigError, config_section,
                                       section_declared, flag, str_tuple, text)

# --- stock policy -------------------------------------------------------------
# ONE vocabulary, in order, for milestone / feature / story. There is still no
# transition graph: nothing here decides which move is allowed next, because a
# `sed` of the `status:` line reaches any state the CLI would have refused and
# no rule checks an EDGE — so the graph taxed whoever used the sanctioned tool
# and stopped nobody else. What IS checked is END STATE, by D3/D4/D5, on the
# tree as it stands. A grain uses the states it needs and SKIPS the rest:
# packaging a feature is a different act from packaging a milestone, and a
# story routinely skips packaging altogether.
#
# `done` does not mean SHIPPED and cannot: the flip is itself a commit that has
# not shipped at the moment it is written, so a tree can never observe its own
# release. It means everything inside this tree's authority is finished —
# changelog written, reviews closed, findings landed, gates green. Branch, PR,
# merge and tag are git events, outside the tree, after `done`.
#
# The ORDER is load-bearing, and it is what one shared vocabulary buys: while a
# story said `wip` and a feature said `building`, "is this story ahead of its
# feature?" was not a question that could be asked, and D5 could only test
# equality with `done`.
LIFECYCLE = ('planning', 'ready', 'building', 'reviewing', 'accepted',
             'packaging', 'done')

# --- the deprecation window (0.24.0 only) -------------------------------------
# The four words this vocabulary REPLACED, each mapped to the word it became.
# They ride in the stock default set for ONE release; 0.25.0 removes them
# (pm/roadmap/0.24.0-gate-cost/bugs/the-deprecation-window-closes.md).
#
# Why they are here at all: a state a tree already HOLDS cannot vanish under
# it. Every `status:` line is validated against these sets, so dropping four
# words turned every grain holding one into a D4 finding on upgrade day —
# measured the day before the tag on the two live consumers that pin this
# package, 43 and 25 findings, both pre-push gates red on the pin bump alone.
# And there is no ordering that avoids it: the unmigrated tree fails under the
# new package, the migrated tree fails under the pinned old one. A window costs
# one release and asks nobody to hold a red gate through a rewrite.
#
# READ, never WRITTEN. `deprecated_write` is the half that makes it a window
# rather than a second vocabulary: the CLI writes the replacement, so the set
# of files a consumer must migrate before 0.25.0 only ever shrinks.
#
# The POSITION is load-bearing and therefore DERIVED, never typed: each retired
# word is spliced in immediately after the word that replaced it, so it lands
# on the same side of `building` as its replacement and the two cannot
# disagree. `work_started` is an index comparison, so a `wip` ordered before
# `building` would report a story at work as not started and a `todo` after it
# the reverse. `blocked` maps to `building` because a blocked grain's work has
# STARTED and stopped — which also keeps it inside D2's stalled window, where a
# feature holding it with every story done is a forgotten flip rather than a
# silence. Hung off the END (past `done`) it would be both: invisible to D2 and
# a claim, in the one place consumers read the order, that a blocked grain is
# further along than a finished one.
DEPRECATED_STATES = {'todo': 'ready', 'wip': 'building',
                     'review': 'reviewing', 'blocked': 'building'}

# Of those four, the ones that were REMOVED rather than renamed. `todo`, `wip`
# and `review` each have a synonym in the new vocabulary and the map above
# names it. `blocked` does not: it was a first-class story state carrying the
# one fact this vocabulary cannot express, and its entry above is a POSITION
# (where the read side places a grain still holding it), not a replacement.
# The write side must say so, because a refusal that names `building` as the
# replacement tells the user the word was renamed and loses the distinction
# on the way out.
REMOVED_STATES = ('blocked',)
STOCK_STATES = tuple(
    word
    for canonical in LIFECYCLE
    for word in (canonical, *(retired for retired, replacement
                              in DEPRECATED_STATES.items()
                              if replacement == canonical)))
DEFAULT_MILESTONE_STATES = STOCK_STATES
DEFAULT_FEATURE_STATES = STOCK_STATES
DEFAULT_STORY_STATES = STOCK_STATES


def deprecated_write(status: str, states: tuple[str, ...]) -> str:
    """The word `status` was retired FOR, or `''` when it may be written.

    The window READS; it does not write. A tree that already holds `wip` stays
    green under 0.24.0, and the sanctioned tool asked to add another one
    refuses and names `building`. Without this half the CLI is itself the thing
    filling trees with the words the window exists to carry out, and the
    rewrite 0.25.0 needs grows for a whole release — while `pm story wip <id>`,
    which exits 2 today, would start succeeding again.

    Armed only while the set IS the window, by VALUE. That is rule 5 (a repo
    declaring the stock default behaves identically to one declaring nothing)
    and it is also the escape hatch: a project whose own vocabulary uses `todo`
    declared a different set, means it, and writes it.
    """
    if tuple(states) != STOCK_STATES:
        return ''
    return DEPRECATED_STATES.get(status, '')
# The two words read BY NAME rather than by position, so each has one spelling
# the gate, the CLI and the reports all reach for. `BUILDING` is the pivot: it
# is where the shaping half ends and the work starts, which is the split D5
# compares a story against its feature across. `REVIEWING` is the one state the
# feature verb has behaviour of its own for (it reports the stories not there
# yet, and `--cascade` closes the ones that are).
BUILDING = 'building'
REVIEWING = 'reviewing'
# D2's question — a feature holding one of these while every story is done has
# not advanced. Derived from the pivot rather than re-listed: a re-listed tuple
# is a second spelling of the vocabulary, and it goes stale silently.
STALLED_IF_ALL_STORIES_DONE = STOCK_STATES[:STOCK_STATES.index(REVIEWING)]
# Bugs have no transition graph — they are filed and they close. A DIFFERENT
# machine, untouched by the lifecycle above. The vocabulary exists so D4 covers
# a bug's status the way it covers every other grain's: a typo'd status is a
# finding rather than a silent "closed" (rule 4).
DEFAULT_BUG_STATES = ('open', 'fixed', 'closed')

# D8/D9/D10 encode the branch-per-milestone / bump-at-start flow. They are OFF
# by default: a project that ships from the trunk and bumps at close is not
# drifting, it is running a different (valid) flow, and a gate that fails it
# would be lying. Opt in with `[pm] checks`. D10 is stricter than D9 — a repo
# may run D9 alone (branch declared, wherever it points) or add D10 to also
# refuse the trunk itself.
DEFAULT_CHECKS = ('D1', 'D2', 'D3', 'D4', 'D5', 'D6',
                  'V1', 'V2', 'V3', 'V4', 'V5')
FLOW_CHECKS = ('D8', 'D9', 'D10')
# Structural/referential integrity — the validate family. V1-V5 are ON by
# default: a tree that does not satisfy them is malformed, not merely running a
# different flow. V6 is the exception and is OPT-IN: an execution list is a
# GENERATED VIEW a project chooses to keep, and a view going stale while
# ordinary work moves the tree is not a defect in the tree. `pm sync --check`
# answers the same question on demand for anyone who wants it, and naming V6 in
# `[pm] checks` puts it back on the gate.
VALIDATE_CHECKS = ('V1', 'V2', 'V3', 'V4', 'V5', 'V6')
KNOWN_CHECKS = tuple(dict.fromkeys(
    DEFAULT_CHECKS + FLOW_CHECKS + VALIDATE_CHECKS))

ARCHIVE_DIR_NAME = 'zz_archive'

# --- the canonical grain slots ------------------------------------------------
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
# There are no DIRECTORY slots. `pm new` used to mint `features/`, `bugs/` and
# `design/` on every milestone and `stories/`+`design/` on every feature — and
# git does not store an empty directory, so across one consumer's tree that
# produced 158 `design/` dirs of which 11 hold anything. `apply` creates a
# parent on the way to a write, so `stories/` appears when the first story is
# written into it, which is the moment it means something.
DECISION_FILE_NAME = 'decisions.md'
REVIEW_FILE_NAME = 'review.md'
HANDOFF_FILE_NAME = 'handoff.md'
# The grain files themselves + the roadmap index — the id↔path convention is
# this module's, so the names are spelled here once and composed everywhere.
MILESTONE_DOC = 'milestone.md'
FEATURE_DOC = 'feature.md'
ROADMAP_DOC = 'ROADMAP.md'

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
MILESTONE_FILE_SLOTS = (MILESTONE_DOC,)
MILESTONE_OPTIONAL_SLOTS = (HANDOFF_FILE_NAME, DECISION_FILE_NAME,
                            REVIEW_FILE_NAME)
FEATURE_FILE_SLOTS = (FEATURE_DOC,)
# No handoff.md: a feature is never picked up cold on its own.
FEATURE_OPTIONAL_SLOTS = (DECISION_FILE_NAME, REVIEW_FILE_NAME)

# slot -> the template that mints it. The grain file's own template is named for
# the grain, the shared docs are named for the slot.
SLOT_TEMPLATE = {
    MILESTONE_DOC: 'milestone', FEATURE_DOC: 'feature',
    'handoff.md': 'handoff', 'decisions.md': 'decisions',
}

# The one-line instruction each shared doc opens with, restored by `pm new` on a
# doc that lost it. `.claude/rules/*` never reach a dispatched subagent — so a
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


@dataclass(frozen=True)
class PmConfig:
    root: Path
    roadmap_dir: str = 'pm/roadmap'
    review_dir: str = 'docs/reviews'
    review_slug_fallback: bool = False
    story_ordinal_prefix: bool = False
    milestone_states: tuple[str, ...] = DEFAULT_MILESTONE_STATES
    feature_states: tuple[str, ...] = DEFAULT_FEATURE_STATES
    story_states: tuple[str, ...] = DEFAULT_STORY_STATES
    bug_states: tuple[str, ...] = DEFAULT_BUG_STATES
    checks: tuple[str, ...] = DEFAULT_CHECKS
    # D8 only: where the shipped version lives, and the line that carries it.
    template_dir: str = ''
    version_file: str = 'project.godot'
    version_pattern: str = r'^config/version="(.*)"$'

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
        review_slug_fallback=flag(sect, 'pm', 'review_slug_fallback', False),
        story_ordinal_prefix=flag(sect, 'pm', 'story_ordinal_prefix', False),
        milestone_states=tup('milestone_states', DEFAULT_MILESTONE_STATES),
        feature_states=tup('feature_states', DEFAULT_FEATURE_STATES),
        story_states=tup('story_states', DEFAULT_STORY_STATES),
        bug_states=tup('bug_states', DEFAULT_BUG_STATES),
        checks=checks,
        template_dir=text(sect, 'pm', 'template_dir', ''),
        version_file=text(sect, 'pm', 'version_file', 'project.godot'),
        version_pattern=version_pattern,
    )


# `[pm]` keys this package USED to honour. Named, because a key that silently
# does nothing is worse than one that errors: the author believes it took
# effect. Same reasoning as the `[pm.scaffold.*]` refusal below it.
RETIRED_KEYS = {
    'place_branch_on_building':
        '`pm milestone building` no longer runs `git checkout` in your trunk '
        'worktree — a PM tracker does not move your VCS checkout',
    'trunk_branches': 'read only by the retired branch-placement flow — the '
                      'id D10 was later reused for a different rule (branch '
                      'discipline: a building milestone off the mainline)',
    'bug_open_states': 'read only by the retired D14; `bug_states` still gates '
                       'a bug\'s status through D4',
    'milestone_transitions': 'there is no transition graph — `milestone_states` '
                             'is the closed set, and nothing constrains order',
    'feature_transitions': 'there is no transition graph — `feature_states` is '
                           'the closed set, and nothing constrains order',
    'story_transitions': 'there is no transition graph — `story_states` is the '
                         'closed set, and nothing constrains order',
    # The close ceremony stopped judging content. All ten were read from `[pm]`
    # at v0.14.0 and are read by nothing at HEAD; without an entry here each was
    # a silent PASS, and the first one cost a project its review-prose floor
    # with no word said.
    'review_min_content_bytes':
        'a review record is a pointer that RESOLVES — the byte floor refused an '
        'honest 15-byte "LGTM. Ship it.", which is the tool judging whether your '
        'prose was long enough. D1 checks the pointer',
    'prose_grandfather': 'read only by the retired prose ratchet (D17/D18)',
    'changelog_grandfather': 'read only by the retired prose ratchet (D17/D18)',
    'decision_grandfather': 'read only by the retired prose ratchet (D17/D18)',
    'story_lines_max': 'the six line caps went with the prose ratchet — this '
                       'package does not manage the length of your markdown',
    'feature_lines_max': 'the six line caps went with the prose ratchet — this '
                         'package does not manage the length of your markdown',
    'bug_lines_max': 'the six line caps went with the prose ratchet — this '
                     'package does not manage the length of your markdown',
    'decisions_lines_max': 'the six line caps went with the prose ratchet — this '
                           'package does not manage the length of your markdown',
    'changelog_lines_max': 'the six line caps went with the prose ratchet — this '
                           'package does not manage the length of your markdown',
    'closed_log_lines_max': 'the six line caps went with the prose ratchet — this '
                            'package does not manage the length of your markdown',
}

# Whole `devkit.toml` SECTIONS a release retired. Same reasoning as the keys
# above, one level up: `check agents` is gone, so every key under `[agents]` is
# read by nothing, and a section is exactly as silent as a key.
RETIRED_SECTIONS = {
    'agents': '`check agents` is removed — A1/A2/A4 failed a build because a '
              'markdown file DESCRIBED a workflow, inferring a line\'s subject '
              'from "one grain word appears". The flat-skill rule it also held '
              'survives in `check doc`',
}


def config_complaints(cfg: PmConfig, sect: dict | None = None) -> list[str]:
    """Everything `[pm]` names that this package does not ship. Empty when clean.

    A rule id, or a key retired by a release. Both are what a PIN BUMP produces,
    and both would otherwise narrow silently — an unknown rule name is
    indistinguishable from a disabled rule at runtime, and a dead key reads as
    honoured.

    An unknown name is indistinguishable from a disabled rule at runtime, so a
    typo would quietly narrow the gate — which is why this is strict. But it is
    NOT raised from `load()`, and that placement is the whole point: `load()` is
    on the path of every `pm` verb, so one stale id — exactly what a version
    bump retiring a rule produces — used to kill `pm status`, `pm get`, `pm new`
    and `pm vocabulary --json` at exit 2. The consumer could then neither read
    its own tree nor ask the tool what the new vocabulary is while deciding what
    to do about it. The GATES enforce it, because they are what a narrowed
    roster or a dead key would lie to.
    """
    out: list[str] = []
    unknown = [c for c in cfg.checks if c not in KNOWN_CHECKS]
    if unknown:
        out.append(f'[pm] checks names unknown rule(s) {", ".join(unknown)} — '
                   f'known rules are {" ".join(KNOWN_CHECKS)}')
    section = config_section('pm') if sect is None else sect
    for key, why in RETIRED_KEYS.items():
        if key in section:
            out.append(f'[pm] {key} was retired and does nothing — {why}. '
                       f'Remove the key.')
    # `sect` is the `[pm]` table a caller may inject; a retired SECTION is a
    # fact about the whole file, so it is read from the file either way.
    for name, why in RETIRED_SECTIONS.items():
        if section_declared(name):
            out.append(f'[{name}] was retired and does nothing — {why}. '
                       f'Remove the section.')
    return out


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

    One key, through `set_fields` — see it for the N-key shape.
    """
    return set_fields(path, {key: value})


def set_fields(path: Path, updates: dict[str, str]) -> bool:
    """Set-or-insert SEVERAL frontmatter scalars in one read + one write.

    `set_field` is this with a one-entry dict. The reason the N-key shape
    exists: `pm move` rewrites a story's `id`/`feature`/`milestone` together,
    and three separate `set_field` calls would be three separate writes — the
    first two landed and the third refused is a story half re-parented, which
    is exactly the partial write rule 3 forbids. One read, every key applied
    to the SAME in-memory copy, one write — the multi-field rewrite is atomic
    the same way the single-field one always was.

    Same contract as `set_field` per key: rewritten in place if present,
    inserted just before the closing fence otherwise; every other byte
    preserved; False WITHOUT writing when there is no frontmatter block to
    write into or the write itself fails.
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
    for key, value in updates.items():
        for i in range(open_i + 1, close_i):
            if lines[i].startswith(f'{key}:'):
                lines[i] = f'{key}: {value}{_eol(lines[i])}'
                break
        else:
            lines.insert(close_i, f'{key}: {value}{_eol(lines[close_i])}')
            close_i += 1
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


def segment_is_literal(value: str) -> bool:
    """One id SEGMENT the resolvers below may join onto a directory.

    The resolution twin of the CLI's creation guard (`_check_slug`), the same
    doctrine as `_grain_file`'s bugs branch: resolution must refuse every
    spelling creation refuses. `id_is_literal` covers only the glob half — a
    `.`/`..`/empty segment joins OUTSIDE the slot it addresses (`0.1/..`
    resolved the MILESTONE dir via `features/..`, and `0.1/.` minted files in
    `features/` itself, a slot the schema does not have), a separator smuggles
    extra components into a one-component slot, and an absolute id reaches
    `Path.glob` as a non-relative pattern and raises instead of exiting 2.
    """
    return (id_is_literal(value) and value not in ('.', '..')
            and not any(c in value for c in '/\\'))


def milestone_dir(cfg: PmConfig, mid: str) -> Path | None:
    if not segment_is_literal(mid):
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
    f = d / MILESTONE_DOC
    return f if f.is_file() else None


def feature_dir(cfg: PmConfig, fid: str) -> Path | None:
    mid, _, slug = fid.partition('/')
    if not segment_is_literal(slug):
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
    f = d / FEATURE_DOC
    return f if f.is_file() else None


_ORDINAL_STEM = re.compile(r'^[0-9][0-9]-(?P<slug>.*)$')


def story_slug_of(cfg: PmConfig, stem: str) -> str:
    """The id segment a story FILE named `stem` must carry.

    One rule, three callers: `story_file` resolves with it, V2 validates with
    it, and `pm new story` SCAFFOLDS with it. The scaffolder did not, so with
    `story_ordinal_prefix` on it stamped `id: <feature>/01-<slug>` into a file
    named `01-<slug>.md` — an id V2 then rejected against the same file's own
    path. Every story scaffolded in one consumer's tree failed `pm validate`
    until it was hand-fixed, which is the tool creating the drift its gate
    reports.

    The prefix SEQUENCES the build; it is not identity. Off, the stem is the
    slug verbatim — a file really named `01-boots.md` owns that id.
    """
    if not cfg.story_ordinal_prefix:
        return stem
    match = _ORDINAL_STEM.match(stem)
    return match.group('slug') if match is not None else stem


def story_file(cfg: PmConfig, sid: str) -> Path | None:
    """Resolve <milestone>/<feature-slug>/<story-slug> to its .md.

    Resolves over `story_files` — the SAME walk the gates use — so the two can
    never disagree about what a story is. They did: this resolver globbed one
    directory level while the walk went recursive, so a story at
    `stories/parked/s2.md` was SEEN by every rule in `check pm` and addressable
    by none of them. The gate reported a story that `pm story building <id>`
    then said did not exist, which is the worst possible pair of answers: each
    is defensible alone and together they leave nothing to do.

    With `story_ordinal_prefix`, a story FILE may carry an ordering prefix
    (`01-the-state.md`) that its ID does not — the number sequences the build,
    it is not identity. Exact stem first, then the prefixed form, so a tree
    holding both `s2.md` and `07-s2.md` resolves to the one whose name IS the
    id rather than refusing. Two files claiming one id at the same precedence
    is an authoring error and REFUSES rather than silently taking the first.
    """
    mid, _, rest = sid.partition('/')
    fslug, _, sslug = rest.partition('/')
    if not fslug or not segment_is_literal(sslug):
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
        elif story_slug_of(cfg, stem) == sslug:
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
    return (d / MILESTONE_DOC).is_file()


def _has_feature_file(d: Path) -> bool:
    return (d / FEATURE_DOC).is_file()


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


def milestone_walk(cfg: PmConfig) -> Walk:
    """Milestone dirs in the ACTIVE tree, with the scaffold-only dirs the walk
    dropped recorded beside them (archived ones predate the schema)."""
    return _milestone_candidates(cfg.roadmap, exclude_archive=True).filter(
        _has_milestone_file, SkipReason.NO_GRAIN_FILE)


def milestone_dirs(cfg: PmConfig) -> list[Path]:
    """Milestone dirs in the ACTIVE tree (archived ones predate the schema)."""
    return list(milestone_walk(cfg).kept)


def milestone_dir_of(cfg: PmConfig, path: Path) -> Path | None:
    """The milestone directory that CONTAINS this grain document, or None.

    The twin of `milestone_dir`, asked from the other end: that one resolves an
    ID to a directory, this one asks which milestone a RESOLVED PATH belongs
    to. Every per-milestone shared file — `decisions.md`, `ledger.jsonl` —
    needs the second question, and re-deriving it by re-parsing the id string
    would be a second resolver with its own opinion about which milestone
    `0.1/alpha/s0` lives in. The path already went through `story_file` /
    `feature_file` / `_grain_file`; where it landed is the answer.

    Structural, not documentary: the milestone directory is the first component
    under `roadmap/` (or under `roadmap/zz_archive/`), whether or not it still
    holds a `milestone.md`. A path outside the roadmap gets None rather than a
    guess, and a path directly IN the roadmap (`ROADMAP.md`) is not inside a
    milestone at all.
    """
    base = cfg.roadmap
    try:
        here = path.resolve()
        base = base.resolve()
    except OSError:
        return None
    if not here.is_relative_to(base):
        return None
    parts = here.relative_to(base).parts
    if parts[:1] == (ARCHIVE_DIR_NAME,):
        base, parts = base / ARCHIVE_DIR_NAME, parts[1:]
    if len(parts) < 2:
        return None
    return base / parts[0]


def known_milestones(cfg: PmConfig) -> list[tuple[Path, str]]:
    """Every milestone dir with its declared id (unquoted; '' when absent).

    The one enumeration `pm status`, `pm list` and retire's id-refusal all
    read — spelled once, so a scope refusal and a filter can never disagree
    about which milestones exist.
    """
    return [(mdir, unquote(field_of(mdir / MILESTONE_DOC, 'id')))
            for mdir in milestone_dirs(cfg)]


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
    nor `stories/` was descended into, so both were invisible to every rule at
    once — and the census printed the smaller number without saying it had
    looked less far.

    Two NARROWINGS, and both disclose because `Walk.filter` gives them no other
    option:

      * DOTTED_NAME — dot-prefixed components, files and directories alike,
        a dot prefix is a deliberate hide. Out of scope for
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
    return [d / FEATURE_DOC for d in walk.children(mdir / 'features', Kind.DIR)
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
def record_resolves(path: Path) -> bool:
    """True if the pointer names a file that is actually there.

    The WHOLE definition. There used to be a `review_min_content_bytes` floor
    under it, and it refused an honest 15-byte "LGTM. Ship it." — the tool
    judging whether a human's prose was long enough. Whether a pointer resolves
    is a fact about the tree, the same shape V4 checks for `depends_on`; how
    much a reviewer needed to write is not a fact about anything.
    """
    return path.is_file()


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
        if record_resolves(target):
            return pointer
    if cfg.review_slug_fallback:
        slug = fid.partition('/')[2]
        rdir = cfg.root / cfg.review_dir
        if slug and rdir.is_dir():
            for cand in walk.matching(rdir, f'{slug}*.md', Kind.FILE).kept:
                if record_resolves(cand):
                    return cfg.rel(cand)
    return None


# --- flow helpers (D8/D9/D10) --------------------------------------------------
def building_milestones(cfg: PmConfig) -> list[tuple[str, str, Path]]:
    """(id, branch, milestone.md) for every ACTIVE milestone at `building`."""
    out = []
    for mdir in milestone_dirs(cfg):
        mfile = mdir / MILESTONE_DOC
        if field_of(mfile, 'status') != 'building':
            continue
        out.append((field_of(mfile, 'id'), field_of(mfile, 'branch'), mfile))
    return out


def mainline_branch() -> str:
    """D10's trunk name — `[repo_hygiene] mainline`, `origin/`-stripped.

    Read from `[repo_hygiene]`, not `[pm]`: the mainline name is a repo-hygiene
    fact one section already owns (`check repo-hygiene` CHECK 4 reads the same
    key), and D10 is the one PM rule that needs it — duplicating the key under
    `[pm]` would be a second name for the same fact. `check repo-hygiene`
    compares against real `git` refs so it keeps the `origin/` remote prefix;
    D10 compares against a milestone's authored `branch:` string, which is
    never remote-qualified, so the stock `origin/main` reads as the local
    branch name `main`.
    """
    sect = config_section('repo_hygiene')
    value = text(sect, 'repo_hygiene', 'mainline', 'origin/main')
    if value.startswith('origin/'):
        value = value[len('origin/'):]
    return value


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


def drift_dangling_record(cfg: PmConfig, fid: str) -> str | None:
    """D1 — a `reviewed:` pointer naming a file that is not there.

    The dangling-POINTER half only. "This feature carries no `reviewed:` at
    all" used to fail here too, and that is not a fact about the tree — it is
    the tool holding an opinion about whether a human had written a document
    yet. A pointer that resolves to nothing IS a fact, and the same one V4
    reports for `depends_on`.
    """
    ffile = feature_file(cfg, fid)
    if ffile is None:
        return None
    pointer = unquote(field_of(ffile, 'reviewed'))
    if not pointer or pointer == 'null':
        return None
    target = Path(pointer) if pointer.startswith('/') else cfg.root / pointer
    if record_resolves(target):
        return None
    return f'reviewed: {pointer!r} resolves to nothing'


def drift_stalled(fstat: str, done_n: int, total: int) -> str | None:
    """D2 — every story done, but the feature never advanced (a forgotten flip).

    A feature at `reviewing` or later with all-done stories is the valid state
    of a feature that HAS advanced — its remaining work is review, acceptance
    and packaging, none of which a story tracks.
    """
    if total == 0 or done_n != total:
        return None
    if fstat in STALLED_IF_ALL_STORIES_DONE:
        return f'all stories done, feature still {fstat}'
    return None


def work_started(status: str, states: tuple[str, ...]) -> bool | None:
    """Is `status` at or past `BUILDING` within `states`? `None` = unreadable.

    The one question D5 is built out of, asked inside ONE vocabulary so it is
    always an index comparison in a single ordered list rather than a guess
    across two. `None` when this set cannot place the pivot at all (a project
    renamed its vocabulary and dropped `building`) or does not contain the
    status (which is D4's finding, already reported) — never `False`, because a
    "no" here reads as "this grain has not started" and saying that about a
    grain whose position is unknown is the invented measurement rule 4 bans.
    """
    if BUILDING not in states or status not in states:
        return None
    return states.index(status) >= states.index(BUILDING)


def drift_ahead_of_parent(child: str, child_states: tuple[str, ...],
                          parent: str, parent_states: tuple[str, ...]) -> bool:
    """D5 — the child is at work while its parent says it has not started.

    NOT "the child is further along than its parent". A story reaching `done`
    while its feature is still `reviewing`, `accepted` or `packaging` is the
    NORMAL path — the feature's remaining work is not story work — and a rule
    that reported it would fire on every feature in every tree. What is a
    genuine disagreement is a story at work under a feature that says it is
    still being shaped: the work has started in one place and not the other.

    So the comparison is across the ONE split each vocabulary carries, not
    across every state. Both halves are read inside their own grain's set, so
    a project that renamed one set and not the other still gets a true answer
    for the set it kept — and `False` when either side is unreadable, which
    `split_blind_vocabularies` reports so the silence is never mistaken for a
    clean tree.

    Two grains holding the SAME WORD are never a disagreement, whatever the
    two sets say about where that word sits. This is a real config, not a
    hypothetical: the split is an index comparison, so a custom set authored
    in a different order (alphabetically, or as a hand-written union during a
    vocabulary migration) moves the pivot for one grain and not the other, and
    the finding that fell out said "the story is at work and the feature says
    it has not started" about `planning` and `planning`. A finding whose two
    halves are the same word cannot be acted on, and D5's whole claim is that
    two places in this tree disagree.
    """
    if child == parent:
        return False
    return (work_started(child, child_states) is True
            and work_started(parent, parent_states) is False)


def split_blind_vocabularies(cfg: PmConfig) -> list[str]:
    """The `[pm]` state sets D5 cannot place `BUILDING` in — what it CANNOT see.

    A rule that reports nothing must say why, or its silence reads as a clean
    tree (rule 4). Named as config keys because that is what the reader edits.
    """
    return [name for name, states in (('story_states', cfg.story_states),
                                      ('feature_states', cfg.feature_states))
            if BUILDING not in states]


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

# --- shared-doc headers -------------------------------------------------------
def header_of(path: Path) -> str:
    """The file's first non-blank line, stripped — its canonical header slot."""
    try:
        for line in _split(read_raw(path)):
            if line.strip():
                return line.strip()
    except (OSError, UnicodeDecodeError):
        return ''
    return ''


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
