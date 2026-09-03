"""cli.py — the PM-tree status CLI.

Moves a story/feature/milestone `status:` through code rather than a regex: the
verb validates the value against that grain's vocabulary, writes ONLY the
`status:` line (plus `reviewed:` on the feature-done step), preserves every
other byte and line ending, and is idempotent.

It does NOT own a transition graph. Nothing checks an EDGE — D3/D4/D5 check the
tree's END STATE — so a graph here would only tax whoever used the sanctioned
tool while a `sed` of the same line reached the state it refused. The one
convenience that remains is the `feature done` cascade, and it is OPT-IN: a run
without `--cascade` touches the feature and no story file, so a closed feature
over unclosed stories is the DEFAULT outcome and an intended one. A verb writes
what it was named; what the tree is then left holding is D5's question, asked of
the tree. Every run reports the stories it did not touch, closed feature or not.

Its companion is `godot-devkit check pm`, which imports the same predicates
from model.py and makes an inconsistent END STATE loud.

Every verb here that CHANGES a grain also appends one timestamped row to that
milestone's `ledger.jsonl` (D6/D8), after its own write lands and never before
— see `_stamp` below. The row is a side effect on disk: no verb's output line
or exit code depends on it.

Exit codes: 0 ok (incl. idempotent no-op) · 1 a refusal — a precondition said
no and nothing was written (`--review-record` naming no file is the one that
ships) · 2 usage / resolution error.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from godot_devkit.core import apply
from godot_devkit.repo.pm import ledger, model, templates

PROG = 'godot-devkit pm'

USAGE = """usage: godot-devkit pm <command>
  story <status> <story-id>               (any status in [pm] story_states)
  bug <status> <bug-id>                   (any status in [pm] bug_states;
                                           bug-id is <milestone>/bugs/<slug>)
  feature <status> <feature-id>           (any status in [pm] feature_states)
  feature done <feature-id> [--cascade] [--review-record <path>]
                                          (--cascade also closes that feature's
                                           stories that are at `review`; without
                                           it, no story file is touched)
  milestone <status> <milestone-id>       (any state; reports features not done)
  retire <milestone-id> [<summary...>] [--dry-run]
                                          (removes the milestone directory and
                                           appends its row to ROADMAP.md;
                                           reports an undone status or live
                                           children rather than refusing on
                                           their account — refuses only when
                                           the id or ROADMAP.md itself is
                                           missing)
  move <story-id> <feature-id>            (re-parents a story: renames its
                                           file under the target feature and
                                           rewrites id/feature/milestone —
                                           whole, or not at all)
  status [<milestone>]
  list [--status <s>[,<s>…]] [--owner <name>] [--milestone <id>]
                                          (one tab-separated line per story:
                                           id, status, owner, feature)
  get <grain-id> <key>                    (read one frontmatter field)
  set <grain-id> <key> <value>            (write one frontmatter field)
  templates [--force]                     (copy the templates into the project to edit)
  sync [--check]                          (re-render the execution lists)
  vocabulary [--json]                     (the closed state set + the rule ids)
  validate                                (structural + referential integrity)
  install-skills [--force] [--diff]       (write the shared rule + operations skill)
  init                                    (scaffold a fresh tree + install guidance)
  new milestone <ver> [<name...>]         (scaffold the grain file in its own dir;
                                           no sub-slot dirs, and a shared doc appears
                                           on first WRITE. Idempotent — re-run to fill)
  new feature <milestone> <slug> [<name...>]
  new story <feature-id> <slug> <name...>
                                          (under [pm] story_ordinal_prefix
                                           a slug may lead with `NN-`: the
                                           FILE keeps it, the id never does)
  new bug <milestone> <slug>
  decide <grain-id> <title...>            (append one dated, ordinal-stamped
                                           heading, minting decisions.md if this is
                                           the first; the prose under it is yours.
                                           A title containing ; & | must be QUOTED
                                           all the way through — through `make pm
                                           ARGS=` too, whose shell cuts an unquoted
                                           title in half and runs the remainder:
                                           ARGS='decide <id> "a; b"')"""



# A heading ENDING in one of these is what a consumer's unquoted `make ARGS`
# leaves behind when its shell cuts the title in half — see cmd_decide.
SHELL_SPLITTERS = (';', '&', '|')


class Refused(Exception):
    """A precondition said no. Exit 1."""


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


def _was(path: Path) -> str:
    """The status a grain currently carries, FOR THE MESSAGE ONLY.

    Never for a decision. A status verb validates the state it was ASKED for
    against the closed vocabulary and writes it; what the file held before is
    posterity, printed as `wombat -> done`. Gating on it made the verb refuse
    exactly the drift D4 reports — the gate diagnosed a hand-edited `wombat`
    and the tool that exists to spare a person the hand-edit declined to
    repair it, leaving the editor as the only way out. `(none)` when the key is
    absent, which is the same fact and equally repairable.
    """
    return model.field_of(path, 'status') or '(none)'


def _set_status(cfg: model.PmConfig, path: Path, value: str, note: str = '') -> None:
    if not model.set_field(path, 'status', value):
        raise Usage(f'could not rewrite status in {cfg.rel(path)} '
                    f'(malformed frontmatter, or the file is not writable)'
                    + (f'. {note}' if note else ''))


# --- the ledger ---------------------------------------------------------------
# Every verb below that CHANGES the tree appends one row to the milestone's
# `ledger.jsonl` (D6/D8). Three rules hold everywhere, and the tests pin all
# three:
#
#   * AFTER the write, never before. A row is the record of a write that
#     landed; a row for a refused flip is rule 4's cardinal sin with a
#     timestamp on it.
#   * A NO-OP still appends. Somebody ran the verb at that instant, and the
#     ledger records what happened, not what changed.
#   * The row never changes the verb's OUTPUT or its EXIT CODE (hard rule 6).
#     A ledger that cannot be written is said out loud on stderr and does not
#     turn a landed status write into a failure — the flip is what the caller
#     asked for and it is already on disk.
def _ledger_id(path: Path, fallback: str) -> str:
    """The id a row names: the grain's OWN `id:`, the caller's when absent.

    The frontmatter id is the file's own claim about itself, which is what a
    report joins rows on. A grain missing the key at all (the drift V2 and D4
    report) still gets a row, under the id the caller resolved it by — an
    unnamed row would be worse than an imperfectly-named one.
    """
    return model.unquote(model.field_of(path, 'id')) or fallback


def _stamp(cfg: model.PmConfig, path: Path, row: dict) -> None:
    """Append one row to the ledger of the milestone that owns `path`.

    Never raises, and never changes an exit code: by the time this runs the
    tree has already been changed and the verb has already reported it. The
    two ways it can come up empty — a grain that resolves outside any
    milestone directory, and a ledger that cannot be written — are both
    printed on stderr naming the path, because a missing row is a fact the
    next report needs and silence here is the one thing that would hide it.
    """
    mdir = model.milestone_dir_of(cfg, path)
    if mdir is None:
        print(f'[pm] WARNING — no milestone directory owns {cfg.rel(path)}, so '
              f'no {ledger.LEDGER_FILE_NAME} row was appended for it; the '
              f'write itself landed', file=sys.stderr)
        return
    try:
        ledger.append_row(mdir, row)
    except OSError as err:
        print(f'[pm] WARNING — {cfg.rel(ledger.ledger_path(mdir))} could not be '
              f'appended to ({err}); the write itself landed, but this '
              f'transition is NOT in the ledger', file=sys.stderr)


def _stamp_status(cfg: model.PmConfig, path: Path, frm: str, to: str,
                  gid: str) -> None:
    """One status row for a flip that has already landed on disk."""
    _stamp(cfg, path, ledger.status_row(_ledger_id(path, gid), frm, to))


# --- story --------------------------------------------------------------------
def cmd_story(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 2:
        raise Usage(USAGE)
    to, sid = args
    if to not in cfg.story_states:
        raise Usage(f'{to!r} is not a story status ({" ".join(cfg.story_states)})')
    sf = model.story_file(cfg, sid)
    if sf is None:
        raise Usage(f'no story resolves from id {sid!r} '
                    f'(expected <milestone>/<feature-slug>/<story-slug>)')
    cur = _was(sf)
    if cur == to:
        _ok(f'story {sid} already {to} (no-op)')
        _stamp_status(cfg, sf, cur, to, sid)
        return 0
    _set_status(cfg, sf, to)
    _ok(f'story {sid}: {cur} -> {to}')
    _stamp_status(cfg, sf, cur, to, sid)
    return 0


# --- bug ------------------------------------------------------------------
def cmd_bug(cfg: model.PmConfig, args: list[str]) -> int:
    """Move a bug's `status:` through code — exactly `cmd_story`'s shape.

    A bug's status is the one fact that "matters most" (its own docstring in
    `checks/pm.py`), and today only a hand edit or the untyped `pm set`
    reaches it — a typo'd status the vocabulary would have refused going
    straight into the file the vocabulary exists to police. This closes that.

    `bid` must NAME a bug (contain `/bugs/`) before `_grain_file` ever runs:
    `_grain_file` resolves a milestone/feature/story id too when `/bugs/` is
    absent, and a bug verb resolving to a FEATURE file would flip that
    file's `status:` to a word validated against `bug_states` instead of its
    own vocabulary — a cross-grain write no caller asked for.
    """
    if len(args) != 2:
        raise Usage(USAGE)
    to, bid = args
    if to not in cfg.bug_states:
        raise Usage(f'{to!r} is not a bug status ({" ".join(cfg.bug_states)})')
    if '/bugs/' not in bid:
        raise Usage(f'no bug resolves from id {bid!r} '
                    f'(expected <milestone>/bugs/<slug>)')
    bf = _grain_file(cfg, bid)
    cur = _was(bf)
    if cur == to:
        _ok(f'bug {bid} already {to} (no-op)')
        _stamp_status(cfg, bf, cur, to, bid)
        return 0
    _set_status(cfg, bf, to)
    _ok(f'bug {bid}: {cur} -> {to}')
    _stamp_status(cfg, bf, cur, to, bid)
    return 0


# --- feature ------------------------------------------------------------------
def _feature_or_usage(cfg: model.PmConfig, fid: str) -> tuple[Path, str]:
    ff = model.feature_file(cfg, fid)
    if ff is None:
        raise Usage(f'no feature resolves from id {fid!r}')
    return ff, _was(ff)


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
        _stamp_status(cfg, ff, cur, to, fid)
        return 0
    _set_status(cfg, ff, to)
    _ok(f'feature {fid}: {cur} -> {to}')
    _stamp_status(cfg, ff, cur, to, fid)
    return 0


def cmd_feature_review(cfg: model.PmConfig, args: list[str]) -> int:
    if len(args) != 1:
        raise Usage(USAGE)
    fid = args[0]
    ff, cur = _feature_or_usage(cfg, fid)
    if cur == 'review':
        _ok(f'feature {fid} already review (no-op)')
        _stamp_status(cfg, ff, cur, 'review', fid)
        return 0
    pending = [f'{p.name}({st})' for p, st in _story_states(cfg, fid)
               if st not in ('review', 'done')]
    _set_status(cfg, ff, 'review')
    _ok(f'feature {fid}: {cur} -> review')
    _stamp_status(cfg, ff, cur, 'review', fid)
    # Reported, never refused. "A feature cannot be under review while its own
    # work is unfinished" is a claim about how a team works; which stories are
    # where is a fact, and it is the caller's to act on.
    if pending:
        _ok(f'  {len(pending)} story/ies not at review: {" ".join(pending)}')
    return 0


def _resolve_record(cfg: model.PmConfig, rec: str) -> Path:
    return Path(rec) if rec.startswith('/') else cfg.root / rec


def _take_flags(args: list[str], flags: tuple[str, ...],
                noun: str = 'a value') -> tuple[list[tuple[str, str]],
                                                list[str]]:
    """Parse `--flag value` / `--flag=value` out of `args`, in order.

    One home for the loop `feature done` and `list` each hand-rolled. Returns
    (the (flag, value) pairs seen, everything else in its original order). A
    flag with nothing after it refuses, naming what it needed; an EMPTY value
    is the caller's question — the `=` spelling with nothing after it once
    stored '' and silently skipped `--review-record`'s stamp, so that caller
    refuses it where a filter flag folds it away.
    """
    pairs: list[tuple[str, str]] = []
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        for flag in flags:
            if a == flag:
                if i + 1 >= len(args):
                    raise Usage(f'{flag} needs {noun}')
                pairs.append((flag, args[i + 1]))
                i += 2
                break
            if a.startswith(f'{flag}='):
                pairs.append((flag, a.split('=', 1)[1]))
                i += 1
                break
        else:
            rest.append(a)
            i += 1
    return pairs, rest


def cmd_feature_done(cfg: model.PmConfig, args: list[str]) -> int:
    """Close a feature. Touches the feature's own `status:` and nothing else.

    `--cascade` additionally moves that feature's stories that are at `review`
    to `done`, in the same run. It is OPT-IN: writing to files the caller did
    not name is the tool acting on its own initiative, and a story flipped by a
    command aimed at a feature is exactly that. With the flag, it was asked for.

    Either way the verb REPORTS what it saw — the stories it did not touch, and
    why — and refuses nothing on their account. What the tree is left holding is
    D5's question, and D5 asks it of the tree rather than of the caller.

    A feature that is ALREADY `done` is not a short circuit. The flip is the
    idempotent part; the cascade, the record stamp and the report each run on
    their own terms, so the two-step (close, then re-run with `--cascade`) does
    what the first run said it would. Run twice with the same flags and the
    second is a no-op, because there is nothing left at `review` to move.
    """
    pairs, rest = _take_flags(args, ('--review-record',), noun='a path')
    rec = ''
    for _, value in pairs:
        # Both spellings refuse an empty path the same way (see _take_flags).
        if not value:
            raise Usage('--review-record needs a path')
        rec = value
    fid = ''
    cascade = False
    for a in rest:
        if a == '--cascade':
            cascade = True
        elif a.startswith('-'):
            raise Usage(f'unknown flag {a!r}')
        elif fid:
            raise Usage(f'unexpected arg {a!r}')
        else:
            fid = a
    if not fid:
        raise Usage(USAGE)
    # `--cascade` writes `done` into STORY files, so that target state is
    # validated against the story vocabulary before anything is touched — a
    # custom `story_states` without `done` used to get it written anyway.
    if cascade and 'done' not in cfg.story_states:
        raise Usage(f"--cascade writes story status 'done', which is not a "
                    f'story status ({" ".join(cfg.story_states)})')
    ff, cur = _feature_or_usage(cfg, fid)
    # NOT short-circuited on `cur == 'done'`. An early return there made the
    # two-step this verb's own output recommends — close, read "--cascade
    # closes the ones at `review`", re-run with the flag — print
    # "already done (no-op)" at exit 0 and touch nothing, with the untouched
    # stories no longer even reported. The feature flip is what is idempotent;
    # the cascade and the report are computed either way, so every run answers
    # for the whole tree it was pointed at.
    states = _story_states(cfg, fid)
    to_close = [p for p, st in states if st == 'review'] if cascade else []
    # What it noticed, said out loud. Never a refusal: the caller asked for a
    # feature to be closed, and this is a fact about its stories.
    untouched = [f'{p.name}({st})' for p, st in states
                 if st != 'done' and p not in to_close]

    if rec:
        # The one thing checked about a record: the path RESOLVES. Whether the
        # prose under it is long enough is not this tool's question — the floor
        # it replaced refused an honest 15-byte "LGTM. Ship it.".
        target = _resolve_record(cfg, rec)
        if not model.record_resolves(target):
            raise Refused(
                f'feature {fid} -> done: review record {rec!r} names no file '
                f'({cfg.rel(target)}). Nothing was written — stamping a pointer '
                f'to nothing is the drift D1 reports.')
        if not model.set_field(ff, 'reviewed', rec):
            raise Usage(f'could not stamp reviewed: in {cfg.rel(ff)}')
        _ok(f'feature {fid}: reviewed -> {rec}')
    record = model.review_record_for(cfg, fid)

    # Stories first: if the FEATURE flip is the one that fails, the gate still
    # sees a non-done feature and a re-run completes the close cleanly.
    #
    # THE LEDGER READS THE OTHER WAY ROUND — the feature's row first, then one
    # per story it closed — so a report reads the close as the one act it was.
    # Each story's row is still BUILT the moment its own write lands (that is
    # its timestamp), held until the feature's row is on disk, and flushed even
    # when the feature flip fails: a write that landed always has its row.
    story_rows = []
    try:
        for p in to_close:
            _set_status(cfg, p, 'done',
                        'CASCADE ABORTED — some stories may already be done; '
                        're-run the same command to finish (it is idempotent).')
            story_rows.append(ledger.status_row(
                _ledger_id(p, f'{fid}/{model.story_slug_of(cfg, p.stem)}'),
                'review', 'done'))
            _ok(f'  story {p.name}: review -> done')
        if cur == 'done':
            _ok(f'feature {fid} already done (no-op)')
        else:
            _set_status(cfg, ff, 'done',
                        'Stories were flipped; re-run to finish closing the '
                        'feature.')
            _ok(f'feature {fid}: {cur} -> done'
                + (f' (review record: {record})' if record
                   else ' (no review record)'))
        _stamp_status(cfg, ff, cur, 'done', fid)
    finally:
        for row in story_rows:
            _stamp(cfg, ff, row)
    if untouched:
        _ok(f'  {len(untouched)} story/ies not done and NOT touched: '
            f'{" ".join(untouched)}'
            + ('' if cascade else ' (--cascade closes the ones at `review`)'))
    return 0


def cmd_feature(cfg: model.PmConfig, args: list[str]) -> int:
    if not args:
        raise Usage(USAGE)
    sub, rest = args[0], args[1:]
    # The TARGET state is validated against the closed vocabulary before ANY
    # dispatch — `done` and `review` used to dispatch first, so a project whose
    # custom `feature_states` excluded them had the sanctioned tool writing the
    # exact out-of-vocabulary status D4 reports. (The CURRENT state is still
    # never gated on — repair from any state stays.)
    if sub not in cfg.feature_states:
        raise Usage(f'{sub!r} is not a feature status '
                    f'({" ".join(cfg.feature_states)})')
    # `done` is the only verb with behaviour of its own — the cascade.
    if sub == 'done':
        return cmd_feature_done(cfg, rest)
    if sub == 'review':
        return cmd_feature_review(cfg, rest)
    return cmd_feature_simple(cfg, sub, rest)


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
    cur = _was(mf)
    if cur == to:
        _ok(f'milestone {mid} already {to} (no-op)')
        _stamp_status(cfg, mf, cur, to, mid)
        return 0
    pending: list[str] = []
    if to == 'done':
        mdir = model.milestone_dir(cfg, mid)
        assert mdir is not None
        pending = [f'{ff.parent.name}({model.field_of(ff, "status")})'
                   for ff in model.feature_files(mdir)
                   if model.field_of(ff, 'status') != 'done']
    _set_status(cfg, mf, to)
    _ok(f'milestone {mid}: {cur} -> {to}')
    _stamp_status(cfg, mf, cur, to, mid)
    # Reported, never refused — and D3 asks the same question of the tree, so
    # the state this leaves is not unwatched.
    if pending:
        _ok(f'  {len(pending)} feature(s) not done: {" ".join(pending)}')
    return 0


def _known_milestone_ids(cfg: model.PmConfig) -> list[str]:
    return sorted(mid or mdir.name
                  for mdir, mid in model.known_milestones(cfg))


def cmd_retire(cfg: model.PmConfig, args: list[str]) -> int:
    """Retire a shipped milestone: remove its directory, record its row.

    `pm init` seeds ROADMAP.md's table (`skills.ROADMAP_SEED`) and nothing
    used to fill it — a retirement was a hand-rolled `git rm -r` plus a
    hand-typed row, the two ever agreeing only by care. This is the one
    write that fills the table the tool itself mints.

    Refuses on exactly two impossibilities, both named: an id that resolves
    to no milestone, and no ROADMAP.md to append to. What it does NOT refuse
    on — the milestone not being `done`, or still holding a feature that
    isn't — is a fact about the tree, not a precondition; it is REPORTED the
    same way `milestone done` already reports its own unfinished features,
    below the line that says what moved. The caution that removed `pm prune`
    was about an AUTOMATIC sweep over every closed milestone, with no name
    in the command at all; this is the opposite shape — one milestone, named
    by the caller, on the command line, every time.

    `--dry-run` runs every decision (which id, which row, which notices) and
    prints them, then returns before the plan is ever built — the same
    "decide everything, write nothing" the whole-or-nothing verbs use, so a
    dry run is byte-identical to not having run it at all.
    """
    dry_run = False
    mid = ''
    summary_words: list[str] = []
    for a in args:
        if a == '--dry-run':
            dry_run = True
        elif not mid:
            mid = a
        else:
            summary_words.append(a)
    if not mid:
        raise Usage(USAGE)
    mdir = model.milestone_dir(cfg, mid)
    if mdir is None:
        known = _known_milestone_ids(cfg)
        raise Usage(f'{mid!r} is not a milestone in {cfg.roadmap_dir} '
                    f'({" ".join(known) if known else "none scaffolded"})')
    index = cfg.roadmap / model.ROADMAP_DOC
    if not index.is_file():
        raise Refused(f'{cfg.rel(index)} does not exist — looked in '
                      f'{cfg.rel(cfg.roadmap)} (run `pm init` first; it seeds '
                      f'the table this command appends to)')

    mfile = mdir / model.MILESTONE_DOC
    notices: list[str] = []
    if not mfile.is_file():
        notices.append(f'{cfg.rel(mfile)} is missing')
        status, canonical_id, name = '', mid, ''
    else:
        status = model.field_of(mfile, 'status')
        canonical_id = model.unquote(model.field_of(mfile, 'id')) or mid
        name = model.field_of(mfile, 'name')
        if status != 'done':
            notices.append(f'milestone {mid} is {status or "(no status)"}, '
                           f'not done')
    open_features = sorted(ff.parent.name for ff in model.feature_files(mdir)
                           if model.field_of(ff, 'status') != 'done')
    if open_features:
        notices.append(f'{len(open_features)} feature(s) not done: '
                       f'{" ".join(open_features)}')
    open_bugs = sorted(bf.stem for bf in model.bug_files(mdir)
                       if model.field_of(bf, 'status') == 'open')
    if open_bugs:
        notices.append(f'{len(open_bugs)} bug(s) still open: '
                       f'{" ".join(open_bugs)}')

    date = (model.field_of(mfile, 'actual_date') if mfile.is_file() else '') \
        or datetime.now(timezone.utc).date().isoformat()
    summary = ' '.join(summary_words)
    row = f'| {canonical_id} | {name} | {date} | {summary} |'

    existing = model.read_raw(index)
    eol = '\r\n' if '\r\n' in existing else '\n'
    padded = existing if not existing or existing.endswith(('\n', '\r')) \
        else existing + eol
    new_index_text = padded + row + eol

    if dry_run:
        _ok(f'[dry-run] would remove {cfg.rel(mdir)}')
        _ok(f'[dry-run] would append to {cfg.rel(index)}: {row}')
        for n in notices:
            _ok(f'  noticed: {n}')
        return 0

    plan = apply.Plan()
    plan.delete_tree(mdir, label=cfg.rel(mdir))
    plan.overwrite(index, new_index_text, newline='', label=cfg.rel(index))
    blocked = plan.decide()
    if blocked:
        raise Refused('; '.join(b.describe() for b in blocked)
                      + ' — nothing was retired')
    applied = plan.apply(decide=False)
    if applied.failed is not None:
        raise Refused(
            f'{applied.failed.label} could not be written ({applied.error}) — '
            + ('nothing was written' if not applied.landed else
               'ALREADY LANDED: ' + ', '.join(s.label for s in applied.landed))
            + '. Fix the obstruction and re-run.')
    _ok(f'milestone {mid}: retired — {cfg.rel(mdir)} removed, '
        f'{cfg.rel(index)} carries the row')
    for n in notices:
        _ok(f'  noticed: {n}')
    return 0


# --- move -----------------------------------------------------------------
def _known_feature_ids(cfg: model.PmConfig) -> list[str]:
    out = []
    for mdir in model.milestone_dirs(cfg):
        mid = model.unquote(model.field_of(mdir / model.MILESTONE_DOC, 'id')) \
            or mdir.name
        out.extend(f'{mid}/{ff.parent.name}' for ff in model.feature_files(mdir))
    return sorted(out)


def cmd_move(cfg: model.PmConfig, args: list[str]) -> int:
    """Re-parent a story to a different feature. Whole, or not at all.

    Two things happen — the file is renamed under the target feature's
    `stories/`, and its `id`/`feature`/`milestone` are rewritten to match —
    and a caller must never see only one of them: an id that still claims
    the old feature after the file moved, or a file sitting in the old
    feature's directory with a new feature's id, is worse than either half
    alone. Everything is DECIDED — the rename's every obstruction — before
    either byte is written, so a decided obstruction (a same-named story
    already at the destination, an unwritable target directory, …) refuses
    with nothing touched: `sf` is unread past resolution, `dest` is never
    created. Only once that decision comes back clean does the frontmatter
    get rewritten (still at the OLD path, through `model.set_fields` — one
    read, one write, all three keys together) and the file renamed last, so
    the one failure mode neither `decide()` nor a permissions check can rule
    out — an OS failure between the two writes — is reported by name rather
    than left to look like a clean move.
    """
    if len(args) != 2:
        raise Usage(USAGE)
    sid, target_fid = args
    sf = model.story_file(cfg, sid)
    if sf is None:
        raise Usage(f'no story resolves from id {sid!r} '
                    f'(expected <milestone>/<feature-slug>/<story-slug>)')
    target_ff = model.feature_file(cfg, target_fid)
    if target_ff is None:
        known = _known_feature_ids(cfg)
        raise Usage(f'no feature resolves from id {target_fid!r} '
                    f'({" ".join(known) if known else "none scaffolded"})')
    target_mid = model.unquote(model.field_of(target_ff, 'milestone')) \
        or target_fid.partition('/')[0]
    target_fslug = target_ff.parent.name
    canonical_fid = f'{target_mid}/{target_fslug}'
    if sf.parent.parent == target_ff.parent:
        _ok(f'story {sid} already under feature {canonical_fid} (no-op)')
        return 0

    dest = target_ff.parent / 'stories' / sf.name
    # `stories/` is minted on first write, never scaffolded (`pm new` mints
    # no empty directory) — so the target feature's OWN first story lands
    # here with no `stories/` to rename into yet. `Plan.move` renames; it
    # does not `mkdir -p` a missing destination parent the way OVERWRITE
    # does, so that has to be its own decided, idempotent step.
    plan = apply.Plan()
    plan.make_dir(dest.parent, label=f'{cfg.rel(dest.parent)}/')
    plan.move(sf, dest, label=f'{cfg.rel(sf)} -> {cfg.rel(dest)}')
    blocked = plan.decide()
    if blocked:
        raise Refused('; '.join(b.describe() for b in blocked)
                      + ' — nothing was moved')

    orig_id = model.field_of(sf, 'id')
    story_slug = orig_id.rpartition('/')[2] or sf.stem
    updates = {'id': f'{canonical_fid}/{story_slug}', 'feature': canonical_fid,
               'milestone': f'"{target_mid}"'}
    if not model.set_fields(sf, updates):
        raise Usage(f'could not rewrite id/feature/milestone in {cfg.rel(sf)} '
                    f'(malformed frontmatter, or the file is not writable) — '
                    f'nothing was moved')

    applied = plan.apply(decide=False)
    if applied.failed is not None:
        raise Refused(
            f'{applied.failed.label} could not be written ({applied.error}) — '
            f'the frontmatter at {cfg.rel(sf)} was ALREADY rewritten to '
            f'{canonical_fid}; move the file to {cfg.rel(dest)} by hand, or '
            f'clear the obstruction and re-run (the rewrite is idempotent).')
    _ok(f'story {sid}: moved to {canonical_fid} '
        f'({cfg.rel(sf)} -> {cfg.rel(dest)})')
    return 0


# --- status -------------------------------------------------------------------
def cmd_status(cfg: model.PmConfig, args: list[str]) -> int:
    only = args[0] if args else ''
    # The same census discipline `pm list` already has: an empty print at
    # exit 0 is what a wrong `roadmap_dir`, an emptied tree, and a typo'd
    # milestone id all used to produce, and rule 4 says a scan that saw
    # nothing must say so rather than pass in silence.
    known = model.known_milestones(cfg)
    if not known:
        raise Usage(f'{cfg.roadmap_dir} holds no milestone at all — nothing to '
                    f'report, so this is a scope problem (wrong [pm] '
                    f'roadmap_dir, or an empty tree?), not a status')
    if only and only not in {mid for _, mid in known}:
        ids = sorted(mid for _, mid in known if mid)
        raise Usage(f'{only!r} is not a milestone in {cfg.roadmap_dir} '
                    f'({" ".join(ids)})')
    for mdir, mid in known:
        mfile = mdir / model.MILESTONE_DOC
        if only and only != mid:
            continue
        print(f'milestone {mid:<10} [{model.field_of(mfile, "status")}]')
        rows = []
        for ffile in model.feature_files(mdir):
            view = model.read_feature(ffile)
            # Drift markers reuse the SAME predicates the gate runs on, so the
            # report and the gate can never describe drift differently.
            reason = (model.drift_dangling_record(cfg, view.fid)
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


def cmd_list(cfg: model.PmConfig, args: list[str]) -> int:
    """One tab-separated line per story, filtered. A view over facts.

    `pm status` answers "what is the whole tree doing" and prints 165 lines on
    one consumer. The question a person actually arrives with is "what is open
    right now", and there the real answer was two stories. This is that filter
    and nothing more — no ranking, no scoring, no verb that picks THE next
    thing, because a tool with an opinion about your priorities is the thing
    this release removes.

    Rows go to stdout so the output pipes into `cut`/`grep`/`wc` unchanged; the
    census goes to stderr, so a run that matched nothing is still
    distinguishable from a run that SCANNED nothing (a wrong `roadmap_dir`).
    """
    pairs, rest = _take_flags(args, ('--status', '--owner', '--milestone'))
    if rest:
        raise Usage(USAGE if not rest[0].startswith('-')
                    else f'unknown flag {rest[0]!r}')
    statuses: set[str] = set()
    owner = ''
    milestone = ''
    for flag, value in pairs:
        if flag == '--status':
            statuses |= {v for v in value.split(',') if v}
        elif flag == '--owner':
            owner = value
        else:
            milestone = value
    unknown = sorted(statuses - set(cfg.story_states))
    if unknown:
        raise Usage(f'--status names {", ".join(unknown)}, which is not a story '
                    f'status ({" ".join(cfg.story_states)})')

    # Enumerated ONCE, and used both to refuse a typo and to filter. A
    # `--milestone` naming nothing used to print `0 of 0` at exit 0, which is
    # what an emptied milestone and a wrong `roadmap_dir` also print. The ids
    # are right there in the tree, so the set gets named the way `--status`
    # already names its own.
    known = model.known_milestones(cfg)
    if milestone and milestone not in {mid for _, mid in known}:
        ids = sorted(mid for _, mid in known if mid)
        raise Usage(f'--milestone names {milestone!r}, which is not a milestone '
                    + (f'in {cfg.roadmap_dir} ({" ".join(ids)})' if ids else
                       f'— {cfg.roadmap_dir} holds no milestone at all, so this '
                       f'is a scope problem, not a typo'))

    shown = 0
    scanned = 0
    for mdir, mid in known:
        if milestone and milestone != mid:
            continue
        for ffile in model.feature_files(mdir):
            view = model.read_feature(ffile)
            for sfile in view.stories:
                scanned += 1
                status = model.field_of(sfile, 'status')
                who = model.unquote(model.field_of(sfile, 'owner'))
                if statuses and status not in statuses:
                    continue
                if owner and who != owner:
                    continue
                shown += 1
                print(f'{model.unquote(model.field_of(sfile, "id"))}\t{status}'
                      f'\t{who or "-"}\t{view.fid}')
    print(f'[pm] {shown} of {scanned} story/ies', file=sys.stderr)
    return 0


def _grain_file(cfg: model.PmConfig, gid: str) -> Path:
    """Resolve any grain id — milestone, feature, story or bug — to its file."""
    if '/bugs/' in gid:
        mid, _, rest = gid.partition('/bugs/')
        # The resolution twin of _check_slug's creation guard. bugs/ is
        # walked recursively, so nested slugs are legal — but a `..` (or an
        # empty) segment would resolve OUTSIDE bugs/ and hand the status
        # write to a sibling grain, the cross-grain write the docstring
        # above promises cannot happen.
        parts = rest.replace('\\', '/').split('/')
        if not rest or any(p in ('', '.', '..') for p in parts):
            raise Usage(f'no bug resolves from id {gid!r} '
                        f'(a bug slug holds no dot or empty segments)')
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
    # Zero grains refuses in BOTH modes. `--check` used to print
    # `all 0 execution list(s) current` at exit 0 over an empty or
    # mis-scoped tree — a gate that scanned nothing, passing.
    if not execlist.targets(cfg):
        raise Usage(f'no grains found under {cfg.roadmap_dir}/ '
                    f'(wrong [pm] roadmap_dir, or an empty tree?)')
    try:
        results = execlist.sync(cfg, write=not check, existing_only=check)
    except execlist.Refusal as err:
        raise Refused(str(err)) from err
    changed = [p for p, c in results if c]
    for path in changed:
        _ok(f'{"stale" if check else "updated"} {cfg.rel(path)}')
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
    """Print the CLOSED sets this package knows, machine-readably with --json.

    Its audience is the pin bump. This toolkit ships a shape, a project bumps
    its pin, and then has to see what changed and decide — so the set of states
    a grain may hold, and the set of rule ids `[pm] checks` may name, have to be
    readable FROM the tool rather than scraped out of help text or a changelog.
    That is the same need `check pm`\'s roster refusal serves from the other
    side, and the reason this verb keeps running when `[pm] checks` names an id
    this release retired.

    There are no TRANSITIONS to print. Any state in a grain\'s own set is
    reachable directly; nothing here decides which may follow which, and
    `check pm` reports a tree whose statuses contradict each other.
    """
    as_json = '--json' in args
    for a in args:
        if a != '--json':
            raise Usage(f'unknown flag {a!r}')
    grains = {
        'milestone': cfg.milestone_states,
        'feature': cfg.feature_states,
        'story': cfg.story_states,
        'bug': cfg.bug_states,
    }
    if as_json:
        import json
        print(json.dumps({
            'grains': {g: {'states': list(states)}
                       for g, states in grains.items()},
            'notes': {
                'transitions': 'there is no transition graph — any state in a '
                               'grain\'s own set is reachable directly, and '
                               '`check pm` reports an inconsistent END STATE',
                'feature_done': 'the story cascade is OPT-IN: `pm feature '
                                'done <id>` touches the feature only, and '
                                '`--cascade` additionally moves that feature\'s '
                                'stories at `review` to `done`. Either way the '
                                'stories it did not touch are reported, never '
                                'refused',
            },
            'checks': list(model.KNOWN_CHECKS),
        }, indent=2))
        return 0
    width = max(len(g) for g in grains)
    for g, states in grains.items():
        print(f'{g:<{width}}  {" ".join(states)}')
    print()
    print('Any state in a grain\'s own set is reachable directly — there is no')
    print('transition graph. The story cascade is OPT-IN: `pm feature done <id>`')
    print('touches the feature only, and `--cascade` additionally moves that')
    print('feature\'s stories at `review` to `done`. Either way the stories it did')
    print('not touch are reported, never refused. A tree whose statuses')
    print('contradict each other is what `check pm` reports.')
    print()
    print(f'rules  {" ".join(model.KNOWN_CHECKS)}')
    return 0


def cmd_validate(cfg: model.PmConfig, args: list[str]) -> int:
    """Structural + referential integrity. The same predicates `check pm` runs."""
    if args:
        raise Usage(USAGE)
    # Same placement as the gate's: `pm validate` is the other reader a stale
    # rule id would silently narrow, and the only two that must refuse it.
    stale = model.config_complaints(cfg)
    if stale:
        raise Usage('\n         '.join(stale))
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
def _scaffold(cfg: model.PmConfig, kind: str, gdir: Path,
              values: dict[str, str]) -> int:
    """Fill a grain's canonical slots and report only what CHANGED."""
    try:
        templates.render(templates.load(cfg, kind), values)
    except templates.MissingTemplate as err:
        raise Usage(str(err)) from err
    except (OSError, UnicodeDecodeError) as err:
        # A template the project cannot even decode is a REFUSAL, not a
        # traceback: rule 6 reserves exit 1 for findings a consumer's hook can
        # print, and a stack trace is not one.
        raise Refused(f'the {kind} template cannot be read ({err}) — nothing '
                      f'was written') from err
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
        name = name or model.field_of(mdir / model.MILESTONE_DOC, 'name')
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
        if not _exists(fdir / model.FEATURE_DOC) and not name:
            raise Usage(f'feature {mid}/{slug!r} does not exist yet — a new one '
                        f'needs a name')
        name = name or model.field_of(fdir / model.FEATURE_DOC, 'name')
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
        mid = model.field_of(fdir / model.FEATURE_DOC, 'milestone')
        # The FILE may carry an ordering prefix (`01-`); the ID never does.
        # Stamping the prefix into `id:` scaffolded a story that `pm validate`
        # V2 rejected against that same file's path — the tool minting the
        # drift its own gate reports.
        sid_slug = model.story_slug_of(cfg, slug)
        if not sid_slug:
            raise Refused(f'story slug {slug!r} is an ordering prefix and '
                          f'nothing else — the number sequences the build, the '
                          f'slug after it is the id')
        sf = fdir / 'stories' / f'{slug}.md'
        if _exists(sf):
            raise Refused(f'story {fid}/{slug!r} already exists')
        sid = f'{fid}/{sid_slug}'
        claimed = model.story_file(cfg, sid)
        if claimed is not None:
            raise Refused(f'story id {sid!r} is already held by '
                          f'{cfg.rel(claimed)} — two files claiming one id is '
                          f'addressable by neither')
        body = templates.render(
            templates.load(cfg, 'story'),
            {'id': sid, 'feature': fid, 'milestone': mid, 'name': name})
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
        _mint(cfg, bf, body)
        _ok(f'created {cfg.rel(bf)}')
        return 0
    raise Usage(USAGE)


# --- decide -------------------------------------------------------------------
def _decision_log(cfg: model.PmConfig, gid: str) -> tuple[Path, str]:
    """(the decisions.md of the grain `gid` names, its text — MINTED if absent).

    The log is minted on FIRST WRITE, from the same template `pm templates`
    copies out, rather than at scaffold time. An empty decisions.md in every
    grain is sprawl the tool made: 204 such files, ~1,900 lines, a quarter of
    one consumer's PM tree, minted by the verb that exists to stop sprawl.

    Nothing is written here — the body comes back and the caller writes once,
    so a refusal further down still leaves the grain byte-identical.
    """
    depth = gid.count('/')
    gdir = (model.milestone_dir(cfg, gid) if depth == 0 else
            model.feature_dir(cfg, gid) if depth == 1 else None)
    if depth > 1 or '/bugs/' in gid:
        raise Refused(f'{gid!r} is a story or a bug — those have no decision '
                      f'log; name the feature or milestone that owns the choice')
    if gdir is None:
        raise Usage(f'no milestone or feature resolves from id {gid!r}')
    log = gdir / model.DECISION_FILE_NAME
    if model.dir_entries(gdir).get(model.DECISION_FILE_NAME) == 'file':
        try:
            return log, model.read_raw(log)
        except (OSError, UnicodeDecodeError) as err:
            raise Usage(f'cannot read {cfg.rel(log)} ({err})') from err
    try:
        return log, templates.render(
            templates.load(cfg, model.SLOT_TEMPLATE[model.DECISION_FILE_NAME]),
            {'id': gid, 'name': model.field_of(
                gdir / f'{"milestone" if depth == 0 else "feature"}.md', 'name')})
    except (OSError, UnicodeDecodeError, templates.MissingTemplate) as err:
        raise Usage(f'the decisions template cannot be read ({err}) — '
                    f'{cfg.rel(log)} was not created') from err


def cmd_decide(cfg: model.PmConfig, args: list[str]) -> int:
    """Append one dated, ordinal-stamped heading. The prose is the author's.

    The two things an author writing this by hand gets wrong are the DATE and
    the ORDINAL — a duplicate `D7` in one log is invisible until somebody cites
    it — so the verb stamps both and stops. It does NOT impose a field schema:
    the four-field one this replaced produced zero conforming entries across a
    consumer's 158 decision logs and 320 hand-written headings, so what it
    actually gated was whether anyone used the verb at all.

    The title is every remaining argv token, joined with one space — so a `;`
    a caller ESCAPED (`a\\; b`, two tokens) rebuilds intact, and a `;` a caller
    QUOTED arrives whole and is written verbatim. A `;` a caller left BARE was
    consumed by their own shell before this process started; what that leaves
    behind is refused rather than written, as far as it is visible from here.

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
    if title.split()[0].startswith('--'):
        # The one caller who leads the title with a flag is a caller speaking
        # the retired four-field interface — writing their flag soup into a
        # durable log at exit 0 would be a quiet lie.
        raise Usage(f'{title.split()[0]!r} looks like a flag — decide takes '
                    f'none: everything after the grain id is the heading')
    if '\n' in title or '\r' in title:
        raise Refused('a heading is one line — put the reasoning under it')
    if title[-1] in SHELL_SPLITTERS:
        # The residue of a shell split. `make pm ARGS="decide <id> a; b"`
        # expands UNQUOTED, so the consumer's shell cuts at the `;`, hands this
        # process `a`, and runs `b` as a command of its own — which is how one
        # consumer's log ended up carrying two half-headings. A cut that lands
        # BETWEEN words is invisible from in here and always will be; a cut
        # that leaves the operator dangling on the end is not, and that is the
        # one shape this can refuse instead of writing a truncated heading.
        raise Refused(
            f'the heading ends with {title[-1]!r} — a shell cut it there and '
            f'the rest never reached this process; nothing was written. Quote '
            f'the whole title: make pm ARGS=\'decide {gid} "first half; '
            f'second half"\'')
    log, text = _decision_log(cfg, gid)
    eid = model.next_entry_id(text)
    when = datetime.now(timezone.utc).date().isoformat()
    try:
        model.write_raw(log, model.append_heading(text, eid, when, title))
    except OSError as err:
        raise Usage(f'could not append to {cfg.rel(log)} ({err})') from err
    _ok(f'{cfg.rel(log)}: {eid} — {when} — {title}')
    # The heading is on disk; the row records that it is. `decisions.md` is
    # per-grain and the ledger is per-milestone (D6), so a feature's decision
    # lands in its milestone's file, named by the grain it was made about.
    _stamp(cfg, log, ledger.decision_row(gid, eid, title))
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
    # Deferred: `skills` imports this module's shared vocabulary (Usage,
    # Refused, _ok), so binding it at call time keeps the load order a
    # non-question whichever module a caller imports first.
    from godot_devkit.repo.pm import skills
    table = {
        'story': cmd_story, 'bug': cmd_bug, 'feature': cmd_feature,
        'milestone': cmd_milestone, 'retire': cmd_retire, 'move': cmd_move,
        'status': cmd_status, 'list': cmd_list, 'new': cmd_new,
        'validate': cmd_validate, 'install-skills': skills.cmd_install_skills,
        'init': skills.cmd_init, 'set': cmd_set, 'get': cmd_get,
        'templates': skills.cmd_templates, 'sync': cmd_sync,
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
