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

from godot_devkit.pm import model

PROG = 'godot-devkit pm'

USAGE = """usage: godot-devkit pm <command>
  story <wip|review|blocked> <story-id>   (review is the story terminal — no story done)
  feature <ready|building> <feature-id>
  feature review <feature-id>
  feature done <feature-id> [--review-record <path>]   (cascade-closes review stories)
  milestone <ready|building|done> <milestone-id>       (done refuses unless all features done)
  status [<milestone>]
  validate                                (structural + referential integrity)
  new milestone <ver> <name...>           (scaffold; statuses move via the commands above)
  new feature <milestone> <slug> <name...>
  new story <feature-id> <slug> <name...>
  new bug <milestone> <slug>
  prune                                   (delete cooled archives; stamp the prune log)"""

# Stock scaffold schemas: ordered (key, literal-value) pairs emitted after the
# computed identity fields. Override wholesale per grain with
# `[pm.scaffold.<grain>]` in devkit.toml when a project's schema differs.
STOCK_SCAFFOLD: dict[str, tuple[tuple[str, str], ...]] = {
    'milestone': (('theme', ''), ('target_date', ''), ('actual_date', ''),
                  ('depends_on', '[]'), ('risk', 'low'), ('track', ''), ('labels', '[]')),
    'feature': (('reviewed', ''), ('risk', 'medium'), ('size', 'm'),
                ('depends_on', '[]'), ('consumed_by', '[]'), ('labels', '[]')),
    'story': (('owner', ''), ('estimate', ''), ('depends_on', '[]'), ('labels', '[]')),
    'bug': (('name', ''), ('severity', 'medium'), ('labels', '[]')),
}


class Refused(Exception):
    """A precondition or transition rule said no. Exit 1."""


class Usage(Exception):
    """Bad arguments, or an id that resolves to nothing. Exit 2."""


def _ok(msg: str) -> None:
    print(f'[pm] {msg}')


def _scaffold_fields(cfg: model.PmConfig, grain: str) -> tuple[tuple[str, str], ...]:
    override = cfg.scaffold.get(grain)
    if not override:
        return STOCK_SCAFFOLD[grain]
    return tuple((str(k), '' if v is None else str(v)) for k, v in override.items())


def _write_grain(path: Path, identity: list[tuple[str, str]],
                 fields: tuple[tuple[str, str], ...], body: str) -> None:
    lines = ['---']
    for key, val in [*identity, *fields]:
        lines.append(f'{key}: {val}' if val != '' else f'{key}:')
    lines += ['---', '', body.rstrip(), '']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')


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
    if cur == to:
        _ok(f'milestone {mid} already {to} (no-op)')
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
    _set_status(cfg, mf, to)
    _ok(f'milestone {mid}: {cur} -> {to}')
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


def cmd_validate(cfg: model.PmConfig, args: list[str]) -> int:
    """Structural + referential integrity. The same predicates `check pm` runs."""
    if args:
        raise Usage(USAGE)
    from godot_devkit.pm import validate as _validate
    findings, census = _validate.run(cfg)
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
def cmd_new(cfg: model.PmConfig, args: list[str]) -> int:
    if not args:
        raise Usage(USAGE)
    grain, rest = args[0], args[1:]
    if grain == 'milestone':
        if len(rest) < 2:
            raise Usage(USAGE)
        ver, name = rest[0], ' '.join(rest[1:])
        if model.milestone_dir(cfg, ver) is not None:
            raise Refused(f'milestone {ver!r} already exists')
        mdir = cfg.roadmap / f'{ver}-{_slugify(name)}'
        if mdir.exists():
            raise Refused(f'{cfg.rel(mdir)} already exists')
        (mdir / 'features').mkdir(parents=True, exist_ok=True)
        (mdir / 'bugs').mkdir(parents=True, exist_ok=True)
        _write_grain(mdir / 'milestone.md',
                     [('id', f'"{ver}"'), ('name', name), ('status', 'planning')],
                     _scaffold_fields(cfg, 'milestone'), f'# v{ver} — {name}')
        _ok(f'milestone {ver} scaffolded: {cfg.rel(mdir / "milestone.md")}')
        return 0
    if grain == 'feature':
        if len(rest) < 3:
            raise Usage(USAGE)
        mid, slug, name = rest[0], rest[1], ' '.join(rest[2:])
        mdir = model.milestone_dir(cfg, mid)
        if mdir is None:
            raise Usage(f'no milestone resolves from {mid!r}')
        fdir = mdir / 'features' / slug
        if (fdir / 'feature.md').exists():
            raise Refused(f'feature {mid}/{slug!r} already exists')
        (fdir / 'stories').mkdir(parents=True, exist_ok=True)
        (fdir / 'plans').mkdir(parents=True, exist_ok=True)
        _write_grain(fdir / 'feature.md',
                     [('id', f'{mid}/{slug}'), ('milestone', f'"{mid}"'),
                      ('name', name), ('status', 'planning')],
                     _scaffold_fields(cfg, 'feature'), f'# {name}')
        _ok(f'feature {mid}/{slug} scaffolded: {cfg.rel(fdir / "feature.md")}')
        return 0
    if grain == 'story':
        if len(rest) < 3:
            raise Usage(USAGE)
        fid, slug, name = rest[0], rest[1], ' '.join(rest[2:])
        fdir = model.feature_dir(cfg, fid)
        if fdir is None:
            raise Usage(f'no feature resolves from id {fid!r}')
        # The milestone comes from the FEATURE's own frontmatter — single
        # source, never re-derived from the id string.
        mid = model.field_of(fdir / 'feature.md', 'milestone')
        sf = fdir / 'stories' / f'{slug}.md'
        if sf.exists():
            raise Refused(f'story {fid}/{slug!r} already exists')
        _write_grain(sf, [('id', f'{fid}/{slug}'), ('feature', fid),
                          ('milestone', f'"{mid}"'), ('name', name),
                          ('status', 'todo')],
                     _scaffold_fields(cfg, 'story'), f'# {name}')
        _ok(f'story {fid}/{slug} scaffolded: {cfg.rel(sf)}')
        return 0
    if grain == 'bug':
        if len(rest) != 2:
            raise Usage(USAGE)
        mid, slug = rest
        mdir = model.milestone_dir(cfg, mid)
        if mdir is None:
            raise Usage(f'no milestone resolves from {mid!r}')
        bf = mdir / 'bugs' / f'{slug}.md'
        if bf.exists():
            raise Refused(f'bug {mid}/bugs/{slug!r} already exists')
        # Bugs anchor to where they were CAUGHT, not where they get fixed — the
        # file path preserves the catch history.
        _write_grain(bf, [('id', f'{mid}/bugs/{slug}'), ('milestone', f'"{mid}"'),
                          ('status', 'open'), ('caught_in', f'"{mid}"'),
                          ('fixed_in', '')],
                     _scaffold_fields(cfg, 'bug'),
                     f'# {slug}\n\n## Symptom\n\n## Root cause\n\n## Fix')
        _ok(f'bug {mid}/bugs/{slug} scaffolded: {cfg.rel(bf)}')
        return 0
    raise Usage(USAGE)


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
    index.write_text(text, encoding='utf-8')

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
        'validate': cmd_validate,
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
