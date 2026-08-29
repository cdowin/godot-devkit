"""cli.py — the precondition-checked PM-tree status CLI.

The ONLY sanctioned way to transition a story/feature/milestone status. A
free-text edit of a `status:` line is the drift vector this exists to close:
flips batched at the end, features reaching `done` without the review the flow
requires. Every command validates the transition graph plus its preconditions,
writes ONLY the `status:` line (plus `reviewed:` on the feature-done step), and
is idempotent — running it twice is a no-op the second time.

Its companion is `godot-devkit check pm`, which imports the same predicates
from model.py and makes the resulting inconsistency loud.

Exit codes: 0 ok (incl. idempotent no-op) · 1 precondition/transition refused
· 2 usage / resolution error.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from godot_devkit.repo.pm import model, templates

PROG = 'godot-devkit pm'

USAGE = """usage: godot-devkit pm <command>
  story <wip|review|blocked> <story-id>   (review is the story terminal — no story done)
  feature <ready|building> <feature-id>
  feature review <feature-id>
  feature done <feature-id> [--review-record <path>]   (cascade-closes review stories)
  milestone <ready|building|done> <milestone-id>       (done refuses unless all features done;
                                                        building also places branch: in the trunk
                                                        when [pm] place_branch_on_building)
  status [<milestone>]
  get <grain-id> <key>                    (read one frontmatter field)
  set <grain-id> <key> <value>            (write one — never `status`)
  claim <grain-id> <owner>                (sugar for set … owner)
  release <grain-id>                      (clear owner)
  templates [--force]                     (copy the templates into the project to edit)
  sync [--check]                          (re-render the execution lists)
  vocabulary [--json]                     (the transition graph, for checkers)
  validate                                (structural + referential integrity)
  install-skills [--force]                (write the shared rule + operations skill)
  init                                    (scaffold a fresh tree + install guidance)
  new milestone <ver> [<name...>]         (scaffold every canonical slot; idempotent —
                                           re-run on an existing grain to fill gaps)
  new feature <milestone> <slug> [<name...>]
  new story <feature-id> <slug> <name...>
  new bug <milestone> <slug>
  decide <grain-id> --chose <what> --over <rejected> --because <why>
         --evidence <hash|path[:line]|number> [--title <short>]
                                          (append a schema-conforming decision; the
                                           tool stamps the date and the next ordinal)
  prune                                   (delete cooled archives; stamp the prune log)"""



class Refused(Exception):
    """A precondition or transition rule said no. Exit 1."""


class Usage(Exception):
    """Bad arguments, or an id that resolves to nothing. Exit 2."""


def _ok(msg: str) -> None:
    print(f'[pm] {msg}')


def _check_slug(kind: str, value: str) -> str:
    """A slug becomes a path component AND half an id. Reject anything else.

    `_slugify` was applied to a grain's NAME only, never to the slug or version
    argument, and `id_is_literal` guards resolution rather than creation — so
    `pm new bug 0.1 ../../../pwned` wrote outside the repo root and exited 0.
    A write verb that touches what it was not asked to is the cardinal sin.
    """
    if not value:
        raise Usage(f'{kind} may not be empty')
    if value in ('.', '..') or any(c in value for c in '/\\'):
        raise Refused(f'{kind} {value!r} contains a path separator — a slug is '
                      f'one path component, never a path')
    if '..' in value:
        raise Refused(f'{kind} {value!r} contains "..", which would escape the '
                      f'tree')
    if value.startswith('-') or any(c in value for c in '*?[]!'):
        raise Refused(f'{kind} {value!r} contains a glob or leading dash — ids '
                      f'are literals')
    return value


def _slugify(text: str) -> str:
    """ASCII-only, because the result becomes a permanent directory name.

    `str.isalnum()` is Unicode-aware, so it would happily mint `café-niño` or a
    CJK path — an NFC/NFD and Windows-encoding hazard for something that is an
    id forever after.
    """
    keep = 'abcdefghijklmnopqrstuvwxyz0123456789'
    out = ''.join(c if c in keep else '-' for c in text.lower())
    while '--' in out:
        out = out.replace('--', '-')
    return out.strip('-')


def _set_status(cfg: model.PmConfig, path: Path, value: str, note: str = '') -> None:
    if not model.set_field(path, 'status', value):
        raise Usage(f'could not rewrite status in {cfg.rel(path)} '
                    f'(malformed frontmatter, or the file is not writable)'
                    + (f'. {note}' if note else ''))


# --- story --------------------------------------------------------------------
def cmd_story(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 2:
        raise Usage(USAGE)
    to, sid = args
    if to not in cfg.story_states:
        raise Usage(f'{to!r} is not a story status ({" ".join(cfg.story_states)})')
    if to == 'done':
        raise Refused("stories don't go to 'done' directly — finish with "
                      "'pm story review', then close the stack with 'pm feature done'")
    sf = model.story_file(cfg, sid)
    if sf is None:
        raise Usage(f'no story resolves from id {sid!r} '
                    f'(expected <milestone>/<feature-slug>/<story-slug>)')
    cur = model.field_of(sf, 'status')
    if cur not in cfg.story_states:
        raise Usage(f'story {sid!r} has an unknown current status {cur!r}')
    if cur == to:
        _ok(f'story {sid} already {to} (no-op)')
        return 0
    # `blocked` is reachable from any state; everything else follows the graph.
    if to != 'blocked' and not model.transition_legal(cfg.story_transitions, cur, to):
        raise Refused(f'illegal story transition {cur} -> {to} for {sid!r}')
    _set_status(cfg, sf, to)
    _ok(f'story {sid}: {cur} -> {to}')
    return 0


# --- feature ------------------------------------------------------------------
def _feature_or_usage(cfg: model.PmConfig, fid: str) -> tuple[Path, str]:
    ff = model.feature_file(cfg, fid)
    if ff is None:
        raise Usage(f'no feature resolves from id {fid!r}')
    cur = model.field_of(ff, 'status')
    if cur not in cfg.feature_states:
        raise Usage(f'feature {fid!r} has an unknown current status {cur!r}')
    return ff, cur


def _story_states(cfg: model.PmConfig, fid: str) -> list[tuple[Path, str]]:
    ff = model.feature_file(cfg, fid)
    assert ff is not None
    return [(s, model.field_of(s, 'status')) for s in model.story_files(ff)]


def cmd_feature_simple(cfg: model.PmConfig, to: str, args: list[str]) -> int:
    if len(args) != 1:
        raise Usage(USAGE)
    fid = args[0]
    ff, cur = _feature_or_usage(cfg, fid)
    if cur == to:
        _ok(f'feature {fid} already {to} (no-op)')
        return 0
    if not model.transition_legal(cfg.feature_transitions, cur, to):
        raise Refused(f'illegal feature transition {cur} -> {to} for {fid!r}')
    _set_status(cfg, ff, to)
    _ok(f'feature {fid}: {cur} -> {to}')
    return 0


def cmd_feature_review(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 1:
        raise Usage(USAGE)
    fid = args[0]
    ff, cur = _feature_or_usage(cfg, fid)
    if cur == 'review':
        _ok(f'feature {fid} already review (no-op)')
        return 0
    if not model.transition_legal(cfg.feature_transitions, cur, 'review'):
        raise Refused(f'illegal feature transition {cur} -> review for {fid!r}')
    pending = [f'{p.name}({st})' for p, st in _story_states(cfg, fid)
               if st not in ('review', 'done')]
    if pending:
        raise Refused(f'feature {fid} -> review: stories not at review: {" ".join(pending)}')
    _set_status(cfg, ff, 'review')
    _ok(f'feature {fid}: {cur} -> review')
    return 0


def cmd_feature_done(cfg: model.PmConfig, args: list[str]) -> int:
    fid = ''
    rec = ''
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--review-record':
            if i + 1 >= len(args):
                raise Usage('--review-record needs a path')
            rec, i = args[i + 1], i + 2
            continue
        if a.startswith('--review-record='):
            rec, i = a.split('=', 1)[1], i + 1
            continue
        if a.startswith('-'):
            raise Usage(f'unknown flag {a!r}')
        if fid:
            raise Usage(f'unexpected arg {a!r}')
        fid, i = a, i + 1
    if not fid:
        raise Usage(USAGE)
    ff, cur = _feature_or_usage(cfg, fid)

    # Idempotent no-op, but still allow a late --review-record correction on an
    # already-done feature without re-transitioning it.
    if cur == 'done':
        if rec:
            if not model.set_field(ff, 'reviewed', rec):
                raise Usage(f'could not stamp reviewed: in {cfg.rel(ff)}')
            _ok(f'feature {fid}: reviewed -> {rec}')
        _ok(f'feature {fid} already done (no-op)')
        return 0
    if not model.transition_legal(cfg.feature_transitions, cur, 'done'):
        raise Refused(f'illegal feature transition {cur} -> done for {fid!r} '
                      f'(must pass through review)')

    # Preconditions clear BEFORE any write — the cascade is all-or-nothing, and
    # a refused close must leave feature.md byte-identical (never a stale stamp).
    states = _story_states(cfg, fid)
    pending = [f'{p.name}({st})' for p, st in states if st not in ('review', 'done')]
    if pending:
        raise Refused(f'feature {fid} -> done: stories not at review: {" ".join(pending)}')
    to_close = [p for p, st in states if st == 'review']

    if rec:
        target = Path(rec) if rec.startswith('/') else cfg.root / rec
        if not model.record_is_substantive(cfg, target):
            raise Refused(
                f'feature {fid} -> done: review record {rec!r} is missing/empty/'
                f'whitespace (needs >= {cfg.review_min_content_bytes} non-whitespace '
                f'bytes). feature.md left untouched.')
        if not model.set_field(ff, 'reviewed', rec):
            raise Usage(f'could not stamp reviewed: in {cfg.rel(ff)}')
        _ok(f'feature {fid}: reviewed -> {rec}')
    record = model.review_record_for(cfg, fid)
    if record is None:
        raise Refused(
            f'feature {fid} -> done: NO substantive review record. Re-run with '
            f'--review-record <path> pointing at a non-empty record (or add a '
            f'resolvable "reviewed:" to the feature.md).')

    # Stories first: if the FEATURE flip is the one that fails, the gate still
    # sees a non-done feature and a re-run completes the close cleanly.
    for p in to_close:
        _set_status(cfg, p, 'done',
                    'CASCADE ABORTED — some stories may already be done; '
                    're-run the same command to finish (it is idempotent).')
        _ok(f'  story {p.name}: review -> done')
    _set_status(cfg, ff, 'done',
                'Stories were flipped; re-run to finish closing the feature.')
    _ok(f'feature {fid}: {cur} -> done (review record: {record})')
    return 0


def cmd_feature(cfg: model.PmConfig, args: list[str]) -> int:
    if not args:
        raise Usage(USAGE)
    sub, rest = args[0], args[1:]
    if sub in ('ready', 'building'):
        return cmd_feature_simple(cfg, sub, rest)
    if sub == 'review':
        return cmd_feature_review(cfg, rest)
    if sub == 'done':
        return cmd_feature_done(cfg, rest)
    raise Usage(USAGE)


# --- branch placement ---------------------------------------------------------
# Opt-in via `[pm] place_branch_on_building`: the flip to `building` also checks
# the milestone's `branch:` out in the TRUNK worktree. D10 asserts that state,
# and one command creating an obligation another has to satisfy by hand is the
# gap where drift lives — a milestone flips, the checkout is forgotten, and the
# gate fails on a difference nobody meant to make.
#
# The ORDERING is the contract:
#   * every refusal is decided BEFORE the flip, so a refused placement leaves
#     milestone.md byte-identical. The status never records a build the tree
#     cannot host.
#   * the flip lands BEFORE the checkout, because the flip is the fact and the
#     checkout is its consequence. If the checkout then fails, that is exit 2
#     with a re-run instruction rather than a rollback: D10 already reports the
#     outstanding placement, and `pm milestone building <id>` is idempotent —
#     its already-building no-op path re-runs placement, which IS the repair.
def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run git without raising on a non-zero exit — callers read `returncode`.

    An ABSENT git is a different failure from a git that said no: nothing about
    the tree is wrong, the tool simply is not there, so that is a usage error.
    """
    try:
        return subprocess.run(['git', *args], cwd=cwd, capture_output=True,
                              text=True, check=False)
    except OSError as err:
        raise Usage(f'git is unavailable ({type(err).__name__}) — cannot place '
                    f'the milestone branch') from err


def _placement_target(cfg: model.PmConfig, mid: str,
                      mfile: Path) -> tuple[Path, str] | None:
    """(trunk, branch) to check out, or None when there is nothing to place.

    Every reason not to place is decided here — this runs before any write.
    """
    branch = model.unquote(model.field_of(mfile, 'branch'))
    if not branch:
        raise Refused(
            f'milestone {mid} declares no branch:, so there is nothing to place '
            f'(D9 asks for the same stamp). Set it with '
            f'`pm set {mid} branch <name>`, then re-run.')
    if branch in cfg.trunk_branches:
        # Loud, not silent: "builds on the trunk" is a real answer, and a
        # placement command that printed nothing would read as a failure.
        _ok(f'milestone {mid} builds on {branch}, a trunk branch — nothing to place')
        return None

    entries, reason = model.git_worktrees(cfg)
    # NO entries is the refusal — not "no branch". A DETACHED-but-present trunk
    # is still a place to put the branch (this gate is opt-in, and the
    # dirty-check below still guards the tree), so it gets placed. An empty
    # listing means git could not answer at all: the target is unverifiable, and
    # a write verb does not guess at its target.
    if not entries:
        raise Refused(f'cannot place branch {branch!r}: {reason} — the trunk '
                      f'worktree is unverifiable, so nothing was flipped')
    trunk, on_branch = entries[0]
    if on_branch == branch:
        _ok(f'trunk {trunk} is already on {branch}')
        return None

    if _git(['rev-parse', '--verify', '--quiet',
             f'refs/heads/{branch}'], cfg.root).returncode != 0:
        raise Refused(
            f'branch {branch!r} does not exist. A milestone declares WHERE its '
            f'work lives; it does not authorize minting the ref. Create it with '
            f'`git -C {trunk} checkout -b {branch}`, then re-run '
            f'(nothing was flipped)')
    holder = next((p for p, b in entries[1:] if b == branch), None)
    if holder is not None:
        raise Refused(
            f'branch {branch!r} is checked out in another worktree ({holder}) — '
            f'git allows one worktree per branch, so the trunk cannot take it. '
            f'Build there, or retire it with `git worktree remove {holder}`, '
            f'then re-run (nothing was flipped)')

    status = _git(['status', '--porcelain'], trunk)
    if status.returncode != 0:
        raise Refused(
            f'cannot read the trunk worktree status at {trunk} '
            f'({status.stderr.strip() or "git failed"}) — nothing was flipped')
    if status.stdout.strip():
        raise Refused(
            f'trunk {trunk} is dirty — a checkout would drag the uncommitted '
            f'changes onto {branch}. Commit or stash there, then re-run '
            f'(nothing was flipped)')
    return trunk, branch


def _place_branch(cfg: model.PmConfig, mid: str, trunk: Path, branch: str) -> None:
    """Check `branch` out in the trunk. Runs only AFTER the status flip landed."""
    res = _git(['checkout', '--quiet', branch], trunk)
    if res.returncode != 0:
        raise Usage(
            f'milestone {mid} is now building, but checking {branch!r} out in '
            f'{trunk} FAILED ({res.stderr.strip() or "git failed"}). The status '
            f'flip stands — re-run `pm milestone building {mid}` — it is '
            f'idempotent and re-runs the placement.')
    _ok(f'trunk {trunk}: checked out {branch}')


# --- milestone ----------------------------------------------------------------
def cmd_milestone(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 2:
        raise Usage(USAGE)
    to, mid = args
    if to not in cfg.milestone_states:
        raise Usage(f'{to!r} is not a milestone status '
                    f'({" ".join(cfg.milestone_states)})')
    mf = model.milestone_file(cfg, mid)
    if mf is None:
        raise Usage(f'no milestone resolves from id {mid!r}')
    cur = model.field_of(mf, 'status')
    if cur not in cfg.milestone_states:
        raise Usage(f'milestone {mid!r} has an unknown current status {cur!r}')
    place = to == 'building' and cfg.place_branch_on_building
    if cur == to:
        _ok(f'milestone {mid} already {to} (no-op)')
        # The no-op is also the REPAIR: a trunk that drifted off the milestone's
        # branch (or a placement that failed after the flip) is put back by
        # re-running the very command D10's finding names.
        if place:
            target = _placement_target(cfg, mid, mf)
            if target is not None:
                _place_branch(cfg, mid, *target)
        return 0
    if not model.transition_legal(cfg.milestone_transitions, cur, to):
        raise Refused(f'illegal milestone transition {cur} -> {to} for {mid!r}')
    if to == 'done':
        mdir = model.milestone_dir(cfg, mid)
        assert mdir is not None
        pending = [f'{ff.parent.name}({model.field_of(ff, "status")})'
                   for ff in model.feature_files(mdir)
                   if model.field_of(ff, 'status') != 'done']
        if pending:
            raise Refused(f'milestone {mid} -> done: features not done: '
                          f'{" ".join(pending)}')
    target = _placement_target(cfg, mid, mf) if place else None
    _set_status(cfg, mf, to)
    _ok(f'milestone {mid}: {cur} -> {to}')
    if target is not None:
        _place_branch(cfg, mid, *target)
    return 0


# --- status -------------------------------------------------------------------
def cmd_status(cfg: model.PmConfig, args: list[str]) -> int:
    only = args[0] if args else ''
    for mdir in model.milestone_dirs(cfg):
        mfile = mdir / 'milestone.md'
        mid = model.field_of(mfile, 'id')
        if only and only != mid:
            continue
        print(f'milestone {mid:<10} [{model.field_of(mfile, "status")}]')
        rows = []
        for ffile in model.feature_files(mdir):
            view = model.read_feature(ffile)
            # Drift markers reuse the SAME predicates the gate runs on, so the
            # report and the gate can never describe drift differently.
            reason = (model.drift_done_no_record(cfg, view.fid, view.status)
                      or model.drift_stalled(view.status, view.done_n, view.total))
            drift = f'  <DRIFT: {reason}>' if reason else ''
            phase = view.phase or 'unphased'
            # Numeric phases first, then the seam bucket, then unphased — the
            # reading order of the milestone's own board.
            sort = (0, int(phase)) if phase.isdigit() else (
                (1, 0) if phase == 'seam' else (2, 0))
            rows.append((sort, phase, view.status,
                         f'  feature {view.fid.partition("/")[2]:<40} '
                         f'[{view.status:<8}] stories {view.done_n}/{view.total} done{drift}'))
        if not rows:
            continue
        buckets: list[str] = []
        for _, phase, _, _ in sorted(rows, key=lambda r: r[0]):
            if phase not in buckets:
                buckets.append(phase)
        # A milestone that declares no phases prints exactly as it always did:
        # the lone `unphased` bucket suppresses its own header.
        for phase in buckets:
            members = [r for r in rows if r[1] == phase]
            n_done = sum(1 for r in members if r[2] == 'done')
            if phase == 'unphased':
                if buckets != ['unphased']:
                    print(f'  -- unphased ({n_done}/{len(members)} done)')
            elif phase == 'seam':
                print(f'  -- seam ({n_done}/{len(members)} done)')
            else:
                print(f'  -- phase {phase} ({n_done}/{len(members)} done)')
            for r in members:
                print(r[3])
    return 0


GUIDANCE_HEADER = 'GENERATED by godot-devkit'

ROADMAP_SEED = """# Roadmap

The permanent index: one row per shipped milestone, in ship order. Active detail lives
in each milestone's own `milestone.md` — anything more than the table belongs deeper in
the tree.

| Version | Name | Delivered | What shipped |
|---|---|---|---|

## Prune log

The working tree keeps only active milestones — git history is the archive. Each entry
records the last commit that still CONTAINS the pruned paths: browse with
`git ls-tree -r <hash> <path>` and resurrect any file with `git show <hash>:<old-path>`.
"""


def cmd_init(cfg: model.PmConfig, args: list[str]) -> int:
    """Stand up a PM tree in a repo that has none, and say what is left to do."""
    if args:
        raise Usage(USAGE)
    made = []
    if not cfg.roadmap.is_dir():
        cfg.roadmap.mkdir(parents=True)
        made.append(f'{cfg.roadmap_dir}/')
    index = cfg.roadmap / 'ROADMAP.md'
    if not index.is_file():
        index.write_text(ROADMAP_SEED, encoding='utf-8')
        made.append(cfg.rel(index))
    for m in made:
        _ok(f'created {m}')
    if not made:
        _ok(f'{cfg.roadmap_dir}/ already exists — leaving it alone')
    cmd_install_skills(cfg, [])

    # Everything below is the consumer's to wire; printing it beats a README
    # they have to go find, and it is short enough to paste.
    print()
    print('Next, in your own repo:')
    print()
    print('  1. Wire the gate into your per-change gate set:')
    print()
    print('       pm-scan:')
    print('       \t@godot-devkit check pm')
    print()
    print('  2. Declare any schema differences in devkit.toml (all optional):')
    print()
    print('       [pm]')
    print('       review_dir = "docs/reviews"   # where review records live')
    print('       # story_ordinal_prefix = true # if story FILES are NN-slug.md')
    print('       # checks = [...]              # add D8/D9/D10 for'
          ' branch-per-milestone')
    print()
    print('  3. Scaffold your first milestone, then check it:')
    print()
    print('       godot-devkit pm new milestone 0.1 "First Milestone"')
    print('       godot-devkit pm validate')
    print()
    print('  4. Keep your OWN vocabulary local — what a milestone means here, which')
    print('     surfaces exist, who reviews what. The two installed files carry only')
    print('     what the CLI enforces and explains.')
    return 0


def cmd_install_skills(cfg: model.PmConfig, args: list[str]) -> int:
    """Write the execution-loop guidance into the consuming repo.

    Installed as a RULE, not a skill file, deliberately: `.claude/rules/*.md`
    with a `paths:` header auto-load for any agent touching the matched files,
    while a skill has to be invoked. The execution loop has to reach every
    agent that edits the PM tree without being asked for.

    Only the loop the CLI itself enforces ships here. Branching, versioning,
    release ceremony, dispatch, review rosters — the project's own SDLC — stay
    in the project's own rules, because they differ per repo and always will.
    """
    force = False
    for a in args:
        if a == '--force':
            force = True
        else:
            raise Usage(f'unknown flag {a!r}')

    from importlib import resources
    from godot_devkit import __version__

    # (source markdown, destination). Two delivery modes on purpose:
    #   rule  — auto-loads for any agent touching the tree; the per-edit loop
    #           has to arrive unasked or it does not arrive at all.
    #   skill — invoked deliberately; the operations manual is what you reach
    #           for when planning or restructuring, not on every edit.
    plan = [
        ('pm-execution.md', cfg.root / '.claude' / 'rules' / 'pm-execution.md'),
        ('pm-operations.md',
         cfg.root / '.claude' / 'skills' / 'pm-operations' / 'SKILL.md'),
    ]
    wrote = 0
    for name, target in plan:
        body = (resources.files('godot_devkit.repo.pm.guidance')
                .joinpath(name).read_text(encoding='utf-8'))
        body = body.replace('{version}', f'v{__version__}')
        if target.is_file():
            existing = target.read_text(encoding='utf-8')
            if existing == body:
                _ok(f'{cfg.rel(target)} already current')
                continue
            # A file we did not generate — or one somebody edited — is theirs,
            # not ours. Clobbering it silently is how a project loses a local
            # decision it made on purpose.
            if GUIDANCE_HEADER not in existing and not force:
                raise Refused(
                    f'{cfg.rel(target)} exists and was not generated by this '
                    f'tool — move your version aside, or pass --force')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
        _ok(f'installed {cfg.rel(target)}')
        wrote += 1
    if wrote:
        _ok(f'godot-devkit v{__version__} — these two carry only what the pm CLI '
            f'itself enforces and explains. Your project\'s SDLC (branching, '
            f'versioning, release, dispatch, review rosters) stays in your own '
            f'rules and agents.')
    return 0


# `status:` is deliberately NOT settable here. It is the one field with a
# transition graph and preconditions behind it, and a `pm set` that could move
# it would reopen the exact hole the CLI exists to close.
PROTECTED_FIELDS = ('status',)


def _grain_file(cfg: model.PmConfig, gid: str) -> Path:
    """Resolve any grain id — milestone, feature, story or bug — to its file."""
    if '/bugs/' in gid:
        mid, _, rest = gid.partition('/bugs/')
        mdir = model.milestone_dir(cfg, mid)
        bf = (mdir / 'bugs' / f'{rest}.md') if mdir else None
        if bf and bf.is_file():
            return bf
        raise Usage(f'no bug resolves from id {gid!r}')
    depth = gid.count('/')
    found = (model.milestone_file(cfg, gid) if depth == 0 else
             model.feature_file(cfg, gid) if depth == 1 else
             model.story_file(cfg, gid))
    if found is None:
        raise Usage(f'no grain resolves from id {gid!r}')
    return found


def cmd_get(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 2:
        raise Usage(USAGE)
    gid, key = args
    print(model.field_of(_grain_file(cfg, gid), key))
    return 0


def cmd_set(cfg: model.PmConfig, args: list[str]) -> int:
    """Set one frontmatter field. The point is that a tool does this, not a regex.

    Every hand-rolled `sed` over frontmatter is a chance to rewrite a line
    ending, drop a field, or move a `status:` that had preconditions on it.
    """
    if len(args) != 3:
        raise Usage(USAGE)
    gid, key, value = args
    if key in PROTECTED_FIELDS:
        raise Refused(
            f'{key!r} has a transition graph and preconditions behind it — move '
            f'it with `pm story|feature|milestone <transition>`, not `pm set`')
    if not key or not key.replace('_', '').isalnum():
        raise Usage(f'{key!r} is not a frontmatter key')
    if '\n' in value or '\r' in value:
        raise Refused('a frontmatter scalar is one line')
    path = _grain_file(cfg, gid)
    before = model.field_of(path, key)
    if not model.set_field(path, key, value):
        raise Usage(f'could not write {key}: in {cfg.rel(path)} '
                    f'(malformed frontmatter, or the file is not writable)')
    _ok(f'{gid}: {key} {before!r} -> {value!r}')
    return 0


def cmd_claim(cfg: model.PmConfig, args: list[str]) -> int:
    """Set `owner:` — the field that was hand-edited everywhere `status:` was not."""
    if len(args) != 2:
        raise Usage(USAGE)
    return cmd_set(cfg, [args[0], 'owner', args[1]])


def cmd_release(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 1:
        raise Usage(USAGE)
    return cmd_set(cfg, [args[0], 'owner', ''])


def cmd_templates(cfg: model.PmConfig, args: list[str]) -> int:
    """Copy the packaged templates into the project so they can be edited."""
    force = '--force' in args
    for a in args:
        if a != '--force':
            raise Usage(f'unknown flag {a!r}')
    try:
        written, variants = templates.install(cfg, force)
    except templates.MissingTemplate as err:
        raise Usage(str(err)) from err
    for path in written:
        _ok(f'installed {cfg.rel(path)}')
    for other, slot in variants:
        _ok(f'{cfg.template_dir}/{other} is a case variant of {slot} and was '
            f'NOT written past — the loader reads EXACT names, so that file is '
            f'never used; `git mv --force {cfg.template_dir}/{other} '
            f'{cfg.template_dir}/{slot}`, then re-run')
    if not written:
        _ok(f'{cfg.template_dir}/ already populated (--force to overwrite)')
    return 0


def cmd_sync(cfg: model.PmConfig, args: list[str]) -> int:
    """Re-render every execution list from the tree.

    The list a milestone/feature shows is generated, never authored — which is
    what makes it safe to have one at all. `--check` reports without writing
    (the same predicate V6 gates on).
    """
    check = '--check' in args
    for a in args:
        if a != '--check':
            raise Usage(f'unknown flag {a!r}')
    from godot_devkit.repo.pm import execlist
    results = execlist.sync(cfg, write=not check, existing_only=check)
    changed = [p for p, c in results if c]
    for path in changed:
        _ok(f'{"stale" if check else "updated"} {cfg.rel(path)}')
    if not results and not check:
        raise Usage(f'no grains found under {cfg.roadmap_dir}/')
    if not changed:
        _ok(f'all {len(results)} execution list(s) current')
        return 0
    if check:
        print(f'[pm] {len(changed)} stale execution list(s) — run `pm sync`',
              file=sys.stderr)
        return 1
    _ok(f'{len(changed)} of {len(results)} updated')
    return 0


def cmd_vocabulary(cfg: model.PmConfig, args: list[str]) -> int:
    """Print the transition vocabulary, machine-readably with --json.

    Exists so a checker never has to scrape help text. A tool that states its
    own rules in a parseable form is the only way an external scanner can stay
    honest when those rules change.
    """
    as_json = '--json' in args
    for a in args:
        if a != '--json':
            raise Usage(f'unknown flag {a!r}')
    grains = {
        'milestone': (cfg.milestone_states, cfg.milestone_transitions),
        'feature': (cfg.feature_states, cfg.feature_transitions),
        'story': (cfg.story_states, cfg.story_transitions),
    }
    if as_json:
        import json
        print(json.dumps({
            'grains': {g: {
                'states': list(states),
                'transitions': [dict(zip(('from', 'to'), t.split('->')))
                                for t in trans],
                'verbs': sorted({t.split('->')[1] for t in trans}
                                | ({'blocked'} if g == 'story' else set())),
            } for g, (states, trans) in grains.items()},
            'notes': {
                'story_terminal': 'review',
                'story_done_via': 'pm feature done (cascade); there is no '
                                  'per-story done transition',
                'status_edits': 'the CLI is the only sanctioned path; never '
                                'hand-edit a status: line',
            },
            'checks': list(model.KNOWN_CHECKS),
        }, indent=2))
        return 0
    for g, (states, trans) in grains.items():
        print(f'{g}:')
        print(f'  states      {" ".join(states)}')
        print(f'  transitions {" ".join(trans)}')
    print()
    print('A story\'s terminal is `review`. It reaches `done` ONLY through')
    print('`pm feature done`\'s cascade — there is no per-story done transition.')
    return 0


def cmd_validate(cfg: model.PmConfig, args: list[str]) -> int:
    """Structural + referential integrity. The same predicates `check pm` runs."""
    if args:
        raise Usage(USAGE)
    from godot_devkit.repo.pm import validate as _validate
    findings, census = _validate.run(cfg, set(cfg.checks) & set(model.VALIDATE_CHECKS))
    for msg in findings:
        print(f'  INVALID  {msg}')
    if not census['grains']:
        # Rule 4 again: a scan that saw nothing must say so, not print VALID.
        print(f'[pm] ERROR — no grains found under {cfg.roadmap_dir}/ '
              f'(wrong [pm] roadmap_dir, or an empty tree?)', file=sys.stderr)
        return 2
    summary = (f'{census["grains"]} grain(s), {census["refs"]} ref(s)')
    if census['unverifiable']:
        summary += (f' ({census["unverifiable"]} UNVERIFIABLE — the ref names a '
                    f'milestone no longer in the tree; git history is the archive)')
    print()
    if findings:
        print(f'[pm] INVALID — {len(findings)} problem(s) across {summary}')
        return 1
    print(f'[pm] VALID — {summary}')
    return 0


# --- new ----------------------------------------------------------------------
INITIAL_STATUS = {'milestone': 'planning', 'feature': 'planning',
                  'story': 'todo', 'bug': 'open'}


def _guard_initial_status(grain: str, body: str) -> None:
    """A template may not mint a grain past its own starting state.

    Otherwise `pm templates` + one edit is a supported path to a `done` story
    that never passed a precondition — the transition graph enforced on every
    move, bypassed at creation.
    """
    for line in body.split('\n'):
        if line.startswith('status:'):
            got = line[len('status:'):].strip().strip('"\'')
            want = INITIAL_STATUS[grain]
            if got and got != want:
                raise Refused(
                    f'the {grain} template sets `status: {got}` — a grain is '
                    f'created at {want!r} and moves only through the CLI')
            return


def _scaffold(cfg: model.PmConfig, kind: str, gdir: Path,
              values: dict[str, str]) -> int:
    """Fill a grain's canonical slots and report only what CHANGED."""
    # The guard runs on the rendered grain template even when the grain already
    # exists: a project that edits its template into `status: done` must not be
    # able to mint one through the fill-gaps path either.
    _guard_initial_status(kind, templates.render(templates.load(cfg, kind), values))
    try:
        actions = templates.scaffold(cfg, kind, gdir, values)
    except templates.ScaffoldRefused as err:
        raise Refused(str(err)) from err
    except templates.MissingTemplate as err:
        raise Usage(str(err)) from err
    for what, path in actions:
        _ok(f'{what} {cfg.rel(path)}')
    if not actions:
        _ok(f'{cfg.rel(gdir)}/ already has every canonical slot (no-op)')
    else:
        _ok(f'{cfg.rel(gdir)}/: {len(actions)} slot(s) filled')
    return 0


def cmd_new(cfg: model.PmConfig, args: list[str]) -> int:
    if not args:
        raise Usage(USAGE)
    grain, rest = args[0], args[1:]
    # `new milestone` and `new feature` are IDEMPOTENT: run against an existing
    # grain they fill the missing slots and leave every existing byte alone.
    # That is how a consumer migrates a tree of 22 milestones and 136 features
    # to the canonical shape, which is why the name is optional there — the
    # name only ever mints the directory, and the directory already exists.
    if grain == 'milestone':
        if not rest:
            raise Usage(USAGE)
        ver, name = _check_slug('milestone version', rest[0]), ' '.join(rest[1:])
        mdir = model.milestone_dir(cfg, ver)
        if mdir is None:
            if not name:
                raise Usage(f'milestone {ver!r} does not exist yet — a new one '
                            f'needs a name (the name mints the directory)')
            mdir = cfg.roadmap / f'{ver}-{_slugify(name)}'
            if mdir.exists():
                raise Refused(f'{cfg.rel(mdir)} already exists')
        name = name or model.field_of(mdir / 'milestone.md', 'name')
        return _scaffold(cfg, 'milestone', mdir, {'id': ver, 'name': name})
    if grain == 'feature':
        if len(rest) < 2:
            raise Usage(USAGE)
        mid, slug = rest[0], _check_slug('feature slug', rest[1])
        name = ' '.join(rest[2:])
        mdir = model.milestone_dir(cfg, mid)
        if mdir is None:
            raise Usage(f'no milestone resolves from {mid!r}')
        fdir = mdir / 'features' / slug
        if not (fdir / 'feature.md').exists() and not name:
            raise Usage(f'feature {mid}/{slug!r} does not exist yet — a new one '
                        f'needs a name')
        name = name or model.field_of(fdir / 'feature.md', 'name')
        return _scaffold(cfg, 'feature', fdir,
                         {'id': f'{mid}/{slug}', 'milestone': mid, 'name': name})
    if grain == 'story':
        if len(rest) < 3:
            raise Usage(USAGE)
        fid, slug = rest[0], _check_slug('story slug', rest[1])
        name = ' '.join(rest[2:])
        fdir = model.feature_dir(cfg, fid)
        if fdir is None:
            raise Usage(f'no feature resolves from id {fid!r}')
        # The milestone comes from the FEATURE's own frontmatter — single
        # source, never re-derived from the id string.
        mid = model.field_of(fdir / 'feature.md', 'milestone')
        sf = fdir / 'stories' / f'{slug}.md'
        if sf.exists():
            raise Refused(f'story {fid}/{slug!r} already exists')
        body = templates.render(
            templates.load(cfg, 'story'),
            {'id': f'{fid}/{slug}', 'feature': fid, 'milestone': mid,
             'name': name})
        _guard_initial_status('story', body)
        templates.write(sf, body)
        _ok(f'created {cfg.rel(sf)}')
        return 0
    if grain == 'bug':
        if len(rest) != 2:
            raise Usage(USAGE)
        mid, slug = rest[0], _check_slug('bug slug', rest[1])
        mdir = model.milestone_dir(cfg, mid)
        if mdir is None:
            raise Usage(f'no milestone resolves from {mid!r}')
        bf = mdir / 'bugs' / f'{slug}.md'
        if bf.exists():
            raise Refused(f'bug {mid}/bugs/{slug!r} already exists')
        # Bugs anchor to where they were CAUGHT, not where they get fixed —
        # the file path preserves the catch history.
        body = templates.render(
            templates.load(cfg, 'bug'),
            {'id': f'{mid}/bugs/{slug}', 'milestone': mid, 'slug': slug})
        _guard_initial_status('bug', body)
        templates.write(bf, body)
        _ok(f'created {cfg.rel(bf)}')
        return 0
    raise Usage(USAGE)


# --- decide -------------------------------------------------------------------
# The two things authors get wrong are the date and the ordinal, so the tool
# stamps both. `--over` is REQUIRED because a decision with no rejected
# alternative is a description — making it a flag you cannot omit enforces that
# at WRITE time, where the author still remembers the alternative, instead of at
# gate time weeks later. Every value is validated through D12's own predicates
# (`model.append_decision` re-parses the composed entry), so a non-conforming
# entry is refused rather than written and then reported.
DECIDE_FLAGS = {'--chose': 'Chose', '--over': 'Over',
                '--because': 'Because', '--evidence': 'Evidence'}


def _decision_log(cfg: model.PmConfig, gid: str) -> Path:
    """The decisions.md of the milestone or feature `gid` names."""
    depth = gid.count('/')
    gdir = (model.milestone_dir(cfg, gid) if depth == 0 else
            model.feature_dir(cfg, gid) if depth == 1 else None)
    if depth > 1 or '/bugs/' in gid:
        raise Refused(f'{gid!r} is a story or a bug — those have no decision '
                      f'log; name the feature or milestone that owns the choice')
    if gdir is None:
        raise Usage(f'no milestone or feature resolves from id {gid!r}')
    entries = model.dir_entries(gdir)
    if entries.get(model.DECISION_FILE_NAME) != 'file':
        kind = 'milestone' if depth == 0 else 'feature'
        raise Refused(
            f'{cfg.rel(gdir)}/ has no {model.DECISION_FILE_NAME} — run '
            f'`{PROG} new {kind} {gid.replace("/", " ")}` to fill the '
            f'canonical slots (it is idempotent), then re-run')
    return gdir / model.DECISION_FILE_NAME


def cmd_decide(cfg: model.PmConfig, args: list[str]) -> int:
    gid = ''
    title = ''
    values: dict[str, str] = {}
    i = 0
    while i < len(args):
        a = args[i]
        key, sep, inline = a.partition('=')
        if key in DECIDE_FLAGS or key == '--title':
            if sep:
                val, i = inline, i + 1
            elif i + 1 < len(args):
                val, i = args[i + 1], i + 2
            else:
                raise Usage(f'{key} needs a value')
            if key == '--title':
                title = val
            else:
                values[DECIDE_FLAGS[key]] = val
            continue
        if a.startswith('-'):
            raise Usage(f'unknown flag {a!r}')
        if gid:
            raise Usage(f'unexpected arg {a!r}')
        gid, i = a, i + 1
    if not gid:
        raise Usage(USAGE)
    for flag, name in DECIDE_FLAGS.items():
        if values.get(name):
            continue
        why = (' — a decision with no rejected alternative is a description, '
               'not a decision') if flag == '--over' else ''
        raise Usage(f'{flag} is required{why}')
    for name, val in values.items():
        if '\n' in val or '\r' in val:
            raise Refused(f'**{name}:** is one line — a decision field that '
                          f'needs a paragraph is two decisions')

    log = _decision_log(cfg, gid)
    try:
        text = model.read_raw(log)
    except (OSError, UnicodeDecodeError) as err:
        raise Usage(f'cannot read {cfg.rel(log)} ({err})') from err
    entries = model.decision_entries_in(text)
    eid = model.next_decision_id(entries)
    when = datetime.now(timezone.utc).date().isoformat()
    # The title defaults to the choice, which is right most of the time and
    # wrong loudly the rest: a `--chose` too long to be a title is refused with
    # the flag that fixes it, never silently truncated into a header.
    if not title:
        title = values['Chose']
        if len(title) > model.DECISION_TITLE_MAX:
            raise Refused(
                f'--chose is {len(title)} chars, over the header\'s '
                f'{model.DECISION_TITLE_MAX}-char title cap — pass --title '
                f'with a short one (nothing was written)')
    body, problems = model.append_decision(text, eid, when, title, values)
    if problems:
        raise Refused(f'{cfg.rel(log)} left untouched — the entry would not '
                      f'conform: ' + '; '.join(problems))
    try:
        model.write_raw(log, body)
    except OSError as err:
        raise Usage(f'could not append to {cfg.rel(log)} ({err})') from err
    _ok(f'{cfg.rel(log)}: {eid} — {when} — {title}')
    return 0


# --- prune --------------------------------------------------------------------
def cmd_prune(cfg: model.PmConfig, args: list[str]) -> int:
    if args:
        raise Usage(USAGE)
    try:
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=cfg.root,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        raise Usage('git not available') from err
    if dirty:
        raise Refused('working tree dirty — commit or stash first '
                      '(the prune must be its own commit)')
    try:
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=cfg.root,
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except subprocess.CalledProcessError as err:
        raise Usage('cannot resolve HEAD — a repo with no commits has no '
                    'resurrect anchor to record, so there is nothing safe to '
                    'prune against') from err

    targets: list[tuple[Path, str]] = []
    for archive in (cfg.roadmap / model.ARCHIVE_DIR_NAME,
                    cfg.root / cfg.review_dir / model.ARCHIVE_DIR_NAME):
        if archive.is_dir():
            targets.append((archive, f'{cfg.rel(archive)}/ (all)'))
    done_dirs = sorted(
        (d for d in model.milestone_dirs(cfg)
         if model.field_of(d / 'milestone.md', 'status') == 'done'),
        key=lambda d: model.version_key(d.name))
    if len(done_dirs) > 1:
        keep = done_dirs[-1]
        for d in done_dirs:
            if d != keep:
                targets.append((d, f'{cfg.rel(d)}/ (done, cooled)'))
        _ok(f'keeping newest done milestone (lag-by-one): {cfg.rel(keep)}')
    if not targets:
        _ok('prune: nothing to prune')
        return 0

    # The anchor is the ONLY way back to what this deletes, so it is written
    # BEFORE the delete and the index is CREATED if absent. Skipping the stamp
    # because the file happened not to exist — while still printing "resurrect
    # anchor ... stamped" — is a destructive command lying about recoverability.
    index = cfg.roadmap / 'ROADMAP.md'
    text = index.read_text(encoding='utf-8') if index.is_file() else '# Roadmap\n'
    if '## Prune log' not in text:
        text += (
            '\n## Prune log\n\nThe working tree keeps only active milestones — git '
            'history is the archive. Each entry\nrecords the last commit that still '
            'CONTAINS the pruned paths: browse with\n`git ls-tree -r <hash> <path>` and '
            'resurrect any file with `git show <hash>:<old-path>`.\n')
    stamp = datetime.now(timezone.utc).date().isoformat()
    text += f'\n- **{stamp}** — pruned from commit `{head}`:\n'
    for _, label in targets:
        text += f'  - `{label}`\n'
    index.parent.mkdir(parents=True, exist_ok=True)
    try:
        # newline='' for the same reason model.py does it: never rewrite a
        # file's line endings as a side effect of appending to it.
        with index.open('w', encoding='utf-8', newline='') as fh:
            fh.write(text)
    except OSError as err:
        raise Usage(f'could not stamp the resurrect anchor into '
                    f'{cfg.rel(index)} ({err}) — nothing was deleted') from err

    for path, _ in targets:
        subprocess.run(['git', 'rm', '-r', '-q', '--ignore-unmatch', cfg.rel(path)],
                       cwd=cfg.root, capture_output=True, text=True, check=False)
        shutil.rmtree(path, ignore_errors=True)
    _ok(f'pruned {len(targets)} dir(s); resurrect anchor {head} stamped in '
        f'{cfg.rel(index)}. Review + commit.')
    return 0


# --- dispatch -----------------------------------------------------------------
def main(argv: list[str]) -> int:
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(USAGE)
        return 0 if argv else 2
    try:
        cfg = model.load()
    except model.ConfigError as err:
        print(f'[pm] ERROR — {err}', file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    table = {
        'story': cmd_story, 'feature': cmd_feature, 'milestone': cmd_milestone,
        'status': cmd_status, 'new': cmd_new, 'prune': cmd_prune,
        'validate': cmd_validate, 'install-skills': cmd_install_skills,
        'init': cmd_init, 'set': cmd_set, 'get': cmd_get, 'claim': cmd_claim,
        'release': cmd_release, 'templates': cmd_templates, 'sync': cmd_sync,
        'vocabulary': cmd_vocabulary, 'decide': cmd_decide,
    }
    fn = table.get(cmd)
    if fn is None:
        print(f'{PROG}: unknown command {cmd!r}', file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    try:
        return fn(cfg, rest)
    except Refused as err:
        print(f'[pm] REFUSED — {err}', file=sys.stderr)
        return 1
    except (Usage, model.AmbiguousStory) as err:
        print(f'[pm] ERROR — {err}', file=sys.stderr)
        return 2
