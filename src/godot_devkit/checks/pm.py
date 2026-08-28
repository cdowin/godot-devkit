"""check pm — tier-1 guard against PM-tree status DRIFT.

The transition CLI (`godot-devkit pm ...`) makes each status move
precondition-checked; this makes the resulting INCONSISTENCY loud. It imports
the vocabularies, the review-record definition and the feature-grain drift
predicates from `godot_devkit.pm.model`, so the gate and the tool can never
describe "reviewed" or "drift" differently — one definition, two readers.

DRIFT RULES (each FAILs, naming the offending path):
  D1  a `done` feature with NO substantive review record (the CLI's own
      `feature done` precondition, inverted into a post-hoc check).
  D2  a feature still planning/ready/building while ALL its stories are `done`
      (a forgotten advance).
  D3  a `done` milestone with a non-`done` feature child.
  D4  a status outside the schema's vocabulary (milestone/feature/story).
  D5  a `done` story under a non-`done` feature. The story terminal is
      `review`; `done` comes only from the feature cascade, so this is a
      hand-edit or a half-applied cascade. (A done story under a DONE feature
      is the valid historical closed state.)
  D6  a `building` milestone whose features are ALL `done` (the milestone
      analogue of D2).
  D7  archive presence — git history IS the archive. A `zz_archive/` dir under
      the roadmap or the review dir, or MORE than one `done` milestone dir at
      the roadmap root (lag-by-one keeps exactly the most recently closed),
      means a prune is due.

Which rules run is `[pm] checks` in devkit.toml (default: all seven).

Scope: the ACTIVE tree only — archived milestones predate the convention. This
MUST pass on the legitimate mid-build state: a building milestone with mixed
children, and a feature at `review` with its stories at their `review` terminal
(the cascade holds stories there until the atomic feature->done flip).
"""
from __future__ import annotations

import sys

from godot_devkit.pm import model


def run() -> int:
    try:
        cfg = model.load()
    except model.ConfigError as err:
        # Exit 2, never 1: a config typo is not a finding, and CI must not read
        # it as "drift found" (the contract project.py states).
        print(f'[check:pm] ERROR — {err}', file=sys.stderr)
        return 2
    findings: list[str] = []

    def report(msg: str) -> None:
        findings.append(msg)
        print(f'  DRIFT  {msg}')

    enabled = set(cfg.checks)
    print(f'[check:pm] scanning active PM tree ({cfg.roadmap_dir}/, '
          f'excluding {model.ARCHIVE_DIR_NAME}/)')

    mdirs = model.milestone_dirs(cfg)
    # Rule 4 — a gate that scans nothing must say so. A misconfigured
    # roadmap_dir would otherwise print a serene PASS over zero files.
    if not mdirs:
        print()
        print(f'[check:pm] FAIL — no milestones found under {cfg.roadmap_dir}/ '
              f'(wrong [pm] roadmap_dir, or an empty tree?)')
        return 1

    # Always on, never gated by `checks`: these are not a drift RULE, they are
    # the scan telling you it could not see part of the tree.
    for path, why in model.orphan_dirs(cfg):
        report(f'{cfg.rel(path)}/ is a {why} — every grain under it was SKIPPED '
               f'by this scan')

    n_features = 0
    n_stories = 0
    done_milestone_dirs = 0

    for mdir in mdirs:
        mfile = mdir / 'milestone.md'
        mid = model.field_of(mfile, 'id')
        mstat = model.field_of(mfile, 'status')
        if mstat == 'done':
            done_milestone_dirs += 1

        if 'D4' in enabled and mstat not in cfg.milestone_states:
            report(f'milestone {mid}: status {mstat!r} not in '
                   f'({" ".join(cfg.milestone_states)})  [{cfg.rel(mfile)}]')

        feat_total = 0
        feat_done_n = 0
        for ffile in model.feature_files(mdir):
            view = model.read_feature(ffile)
            frel = cfg.rel(ffile)
            feat_total += 1
            n_features += 1
            n_stories += view.total
            if view.status == 'done':
                feat_done_n += 1

            if 'D4' in enabled and view.status not in cfg.feature_states:
                report(f'feature {view.fid}: status {view.status!r} not in '
                       f'({" ".join(cfg.feature_states)})  [{frel}]')

            if 'D3' in enabled and mstat == 'done' and view.status != 'done':
                report(f'milestone {mid} is done but feature {view.fid} '
                       f'is {view.status!r}  [{frel}]')

            if 'D1' in enabled:
                reason = model.drift_done_no_record(cfg, view.fid, view.status)
                if reason:
                    report(f'feature {view.fid} is {reason} (stamp it via '
                           f'pm feature done --review-record <path>)  [{frel}]')

            for sfile in view.stories:
                sid = model.field_of(sfile, 'id')
                sstat = model.field_of(sfile, 'status')
                srel = cfg.rel(sfile)
                if 'D4' in enabled and sstat not in cfg.story_states:
                    report(f'story {sid}: status {sstat!r} not in '
                           f'({" ".join(cfg.story_states)})  [{srel}]')
                if 'D5' in enabled and sstat == 'done' and view.status != 'done':
                    report(f'story {sid} is done but its feature {view.fid} is '
                           f'{view.status!r} (a done story only comes from the '
                           f'feature cascade)  [{srel}]')

            if 'D2' in enabled:
                reason = model.drift_stalled(view.status, view.done_n, view.total)
                if reason:
                    report(f'feature {view.fid}: {reason} (should be '
                           f'review/done)  [{frel}]')

        if ('D6' in enabled and mstat == 'building'
                and feat_total > 0 and feat_done_n == feat_total):
            report(f'milestone {mid} is {mstat!r} but all {feat_total} features '
                   f'are done (should be done)  [{cfg.rel(mfile)}]')

    if 'D7' in enabled:
        for archive in (cfg.roadmap / model.ARCHIVE_DIR_NAME,
                        cfg.root / cfg.review_dir / model.ARCHIVE_DIR_NAME):
            if archive.is_dir():
                report(f'{cfg.rel(archive)}/ exists — a prune is due '
                       f'(git history is the archive)')
        if done_milestone_dirs > 1:
            report(f'{done_milestone_dirs} done milestone dirs at the roadmap '
                   f'root — lag-by-one allows 1; a prune is due')

    print()
    census = (f'{len(mdirs)} milestone(s), {n_features} feature(s), '
              f'{n_stories} story/ies')
    if findings:
        print(f'[check:pm] FAIL — {len(findings)} status-drift violation(s) '
              f'across {census}')
        return 1
    print(f'[check:pm] PASS — no PM-tree status drift; scanned {census}')
    return 0
