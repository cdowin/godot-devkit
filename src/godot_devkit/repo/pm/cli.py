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

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# `install` owns the refusal wording every install verb shares — this one
# had its own copy and got the plural wrong.
from godot_devkit.repo import install
from godot_devkit.core import apply
from godot_devkit.repo.pm import model, templates

PROG = 'godot-devkit pm'

USAGE = """usage: godot-devkit pm <command>
  story <wip|review|blocked> <story-id>   (review is the story terminal — no story done)
  feature <ready|building> <feature-id>
  feature review <feature-id>
  feature done <feature-id> [--review-record <path>]   (cascade-closes review stories;
                                                        REFUSES a record pointing at the
                                                        transient review.md — D11 deletes
                                                        that at close, so the durable record
                                                        is the decision log it fed)
  milestone <ready|building|done> <milestone-id>       (done refuses unless all features done,
                                                        and stamps actual_date: — the date it
                                                        shipped; building also places branch:
                                                        in the trunk when [pm]
                                                        place_branch_on_building)
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
  decide <grain-id> <title...>            (append one dated, ordinal-stamped
                                           heading; the prose under it is yours)
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


def _exists(path: Path) -> bool:
    """`Path.exists()` that answers False for a path the FILESYSTEM refuses.

    A component longer than the filesystem's NAME_MAX raises `OSError` out of
    `stat` on 3.11, 3.12 and 3.13, and is swallowed into False from 3.14 on. So
    one `pm new` came out as a traceback or as a refusal depending on which
    interpreter `uvx` picked, and a tool whose behaviour depends on that is not
    a tool. False is the answer both readings want: nothing is there, and the
    write that follows refuses with the reason.
    """
    try:
        return path.exists()
    except OSError:
        return False


def _mint(cfg: model.PmConfig, path: Path, body: str) -> None:
    """Write one new grain FILE, turning a filesystem refusal into a REFUSED.

    `new story` and `new bug` write straight rather than through the idempotent
    scaffolder, so neither guard that verb grew covers them: a slug the
    filesystem will not take, or an unwritable `stories/`, came out as an
    `OSError` traceback under exit 1 — the code a consumer's pre-push hook
    reads as "drift found".
    """
    try:
        templates.write(path, body)
    except OSError as err:
        raise Refused(f'{cfg.rel(path)} could not be written ({err}) — nothing '
                      f'was written; shorten the slug, or make '
                      f'{cfg.rel(path.parent)}/ writable') from err


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


def _resolve_record(cfg: model.PmConfig, rec: str) -> Path:
    return Path(rec) if rec.startswith('/') else cfg.root / rec


def _refuse_transient_record(cfg: model.PmConfig, fid: str, rec: str) -> None:
    """Refuse a `reviewed:` pointer aimed at the TRANSIENT `review.md` slot.

    The close protocol contradicted itself and the contradiction was only
    resolvable by knowing a rule nobody had written down: stamp `reviewed:` at
    `review.md`, obey D11 and delete it, and the feature is `done w/o review
    record`. Enforced here rather than documented, because the whole point of
    the CLI owning `status:` is that a human never has to hold the protocol in
    their head to close something correctly.
    """
    if not model.is_transient_review_slot(cfg, _resolve_record(cfg, rec)):
        return
    durable = model.durable_record_for(cfg, fid)
    where = cfg.rel(durable) if durable else 'the feature\'s decisions.md'
    raise Refused(
        f'feature {fid} -> done: review record {rec!r} is the TRANSIENT '
        f'{model.REVIEW_FILE_NAME} slot, which D11 deletes at close — pointing '
        f'`reviewed:` at it closes the feature and then strands it '
        f'"done w/o review record". The durable record of a review is the '
        f'decision log it fed: promote what the review settled with '
        f'`{PROG} decide {fid} --chose … --over … --because … --evidence …`, '
        f'then close with --review-record {where}. feature.md left untouched.')


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
    if rec:
        # Before ANY write, and before the already-done shortcut: a late
        # correction that re-points `reviewed:` at the transient slot is the
        # same defect arriving by the other door.
        _refuse_transient_record(cfg, fid, rec)

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

    # An EXISTING `reviewed:` aimed at the transient slot is refused too, and
    # before the stories cascade: a hand-edited pointer reaches `done` by the
    # same route as a flagged one, and would strand the feature identically.
    standing = model.unquote(model.field_of(ff, 'reviewed'))
    if not rec and standing and standing != 'null':
        _refuse_transient_record(cfg, fid, standing)

    if rec:
        target = _resolve_record(cfg, rec)
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
        raise Usage(f'git is unavailable ({type(err).__name__}) — this command '
                    f'cannot run without it') from err


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
def _stamp_actual_date(cfg: model.PmConfig, mf: Path, mid: str) -> None:
    """Stamp `actual_date:` at close — the moment a milestone acquires one.

    The template mints the field empty, and close is the one moment the tree
    learns when a milestone shipped — a date reconstructed later is a guess.

    Written only when EMPTY, so re-running `milestone done` repairs a missing
    stamp — the same no-op-is-the-repair shape `place_branch_on_building` has —
    without ever moving a date already recorded.
    """
    if model.field_of(mf, 'actual_date'):
        return
    when = datetime.now(timezone.utc).date().isoformat()
    if not model.set_field(mf, 'actual_date', when):
        raise Usage(f'could not write actual_date in {cfg.rel(mf)} '
                    f'(malformed frontmatter, or the file is not writable). '
                    f'The status stands at done — re-run this command to stamp '
                    f'the date once the file is repaired')
    _ok(f'milestone {mid}: actual_date {when}')


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
        if to == 'done':
            _stamp_actual_date(cfg, mf, mid)
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
    if to == 'done':
        _stamp_actual_date(cfg, mf, mid)
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
    plan = apply.Plan()
    index = cfg.roadmap / 'ROADMAP.md'
    if not cfg.roadmap.is_dir():
        plan.make_dir(cfg.roadmap, label=f'{cfg.roadmap_dir}/')
    if not index.is_file():
        plan.overwrite(index, ROADMAP_SEED, newline=None, label=cfg.rel(index))
    apply.raise_on_error(plan.apply(decide=False))
    made = [step.label for step in plan.steps]
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
    # Decided for BOTH entries before either is written. A refusal raised
    # mid-loop installs the first file, refuses the second, and still says
    # nothing was written — `nothing was written` has to be a claim about the
    # whole command, the same rule `pm init` follows for renames.
    actions: list[tuple[str, Path, str]] = []
    collisions: list[str] = []
    defects: list[str] = []
    for name, target in plan:
        body = (resources.files('godot_devkit.repo.pm.guidance')
                .joinpath(name).read_text(encoding='utf-8'))
        body = body.replace('{version}', f'v{__version__}')
        # The same pre-decided discipline as the other two install verbs, from
        # the same helpers: a destination that is a directory, unwritable, or
        # undecodable is a refusal naming the path, never a traceback with one
        # file already on disk behind it.
        defect = install.destination_defect(target)
        if defect:
            defects.append(f'{cfg.rel(target)} {defect}')
            continue
        if target.is_file():
            existing, unreadable = install.read_destination(target)
            if unreadable:
                defects.append(f'{cfg.rel(target)} {unreadable}')
                continue
            if existing == body:
                actions.append(('current', target, body))
                continue
            # A file we did not generate — or one somebody edited — is theirs,
            # not ours. Clobbering it silently is how a project loses a local
            # decision it made on purpose.
            if (existing is None
                    or GUIDANCE_HEADER not in existing) and not force:
                collisions.append(cfg.rel(target))
                continue
        actions.append(('write', target, body))
    if collisions:
        head, tail = install.collision_refusal(collisions)
        raise Refused(f'{head}\n{tail}')
    if defects:
        raise Refused(f'{len(defects)} destination(s) cannot be written:\n'
                      + '\n'.join(f'    {d}' for d in defects)
                      + '\nNothing was written. Fix the path(s) and re-run — '
                        'the command is idempotent.')

    # ONE plan: the destinations were decided above, and `core.apply` reports
    # exactly which of them landed. A loop that decided as it wrote is what
    # made this verb's twin, `install-agents`, half-install twice.
    writes = apply.Plan()
    for kind, target, body in actions:
        if kind != 'current':
            writes.overwrite(target, body, newline=None, label=cfg.rel(target))
    result = writes.apply(decide=False)
    written = [step.label for step in result.landed]
    landed = set(written)
    for kind, target, body in actions:
        if kind == 'current':
            _ok(f'{cfg.rel(target)} already current')
        elif cfg.rel(target) in landed:
            _ok(f'installed {cfg.rel(target)}')
        else:
            break
    if result.failed is not None:
        raise Refused(
            f'{result.failed.label} could not be written '
            f'({result.error}) — '
            + ('nothing was written' if not written else
               'ALREADY WRITTEN before this was reached: '
               + ', '.join(written))
            + '. Fix the path and re-run — the command is idempotent.')
    wrote = len(written)
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
    try:
        head = templates.render(templates.load(cfg, kind), values)
    except templates.MissingTemplate as err:
        raise Usage(str(err)) from err
    except (OSError, UnicodeDecodeError) as err:
        # A template the project cannot even decode is a REFUSAL, not a
        # traceback: rule 6 reserves exit 1 for findings a consumer's hook can
        # print, and a stack trace is not one.
        raise Refused(f'the {kind} template cannot be read ({err}) — nothing '
                      f'was written') from err
    _guard_initial_status(kind, head)
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
            if _exists(mdir):
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
        if not _exists(fdir / 'feature.md') and not name:
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
        if _exists(sf):
            raise Refused(f'story {fid}/{slug!r} already exists')
        body = templates.render(
            templates.load(cfg, 'story'),
            {'id': f'{fid}/{slug}', 'feature': fid, 'milestone': mid,
             'name': name})
        _guard_initial_status('story', body)
        _mint(cfg, sf, body)
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
        if _exists(bf):
            raise Refused(f'bug {mid}/bugs/{slug!r} already exists')
        # Bugs anchor to where they were CAUGHT, not where they get fixed —
        # the file path preserves the catch history.
        body = templates.render(
            templates.load(cfg, 'bug'),
            {'id': f'{mid}/bugs/{slug}', 'milestone': mid, 'slug': slug})
        _guard_initial_status('bug', body)
        _mint(cfg, bf, body)
        _ok(f'created {cfg.rel(bf)}')
        return 0
    raise Usage(USAGE)


# --- decide -------------------------------------------------------------------
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
    """Append one dated, ordinal-stamped heading. The prose is the author's.

    The two things an author writing this by hand gets wrong are the DATE and
    the ORDINAL — a duplicate `D7` in one log is invisible until somebody cites
    it — so the verb stamps both and stops. It does NOT impose a field schema:
    the four-field one this replaced produced zero conforming entries across a
    consumer's 158 decision logs and 320 hand-written headings, so what it
    actually gated was whether anyone used the verb at all.

    Refuses WHOLE: every path out of here that is not a write leaves the log
    byte-identical.
    """
    if not args:
        raise Usage(USAGE)
    gid, title = args[0], ' '.join(args[1:]).strip()
    if gid.startswith('-'):
        raise Usage(f'unknown flag {gid!r}')
    if not title:
        raise Usage('decide needs a title — the heading is the entry')
    if '\n' in title or '\r' in title:
        raise Refused('a heading is one line — put the reasoning under it')
    log = _decision_log(cfg, gid)
    try:
        text = model.read_raw(log)
    except (OSError, UnicodeDecodeError) as err:
        raise Usage(f'cannot read {cfg.rel(log)} ({err})') from err
    eid = model.next_entry_id(text)
    when = datetime.now(timezone.utc).date().isoformat()
    try:
        model.write_raw(log, model.append_heading(text, eid, when, title))
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
    try:
        # `core.apply` writes with newline='' for the same reason model.py does:
        # never rewrite a file's line endings as a side effect of appending.
        apply.raise_on_error(apply.write(index, text))
    except OSError as err:
        raise Usage(f'could not stamp the resurrect anchor into '
                    f'{cfg.rel(index)} ({err}) — nothing was deleted') from err

    for path, _ in targets:
        subprocess.run(['git', 'rm', '-r', '-q', '--ignore-unmatch', cfg.rel(path)],
                       cwd=cfg.root, capture_output=True, text=True, check=False)
        apply.remove_tree(path)
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
