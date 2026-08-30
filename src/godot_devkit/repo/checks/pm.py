"""check pm — tier-1 guard against PM-tree status DRIFT.

The status CLI (`godot-devkit pm ...`) moves a `status:` through code; this
makes an INCONSISTENT tree loud. Nothing checks an EDGE — a status move is a
write, and what these rules read is the END STATE it left behind. It imports
the vocabularies, the review-record definition and the feature-grain drift
predicates from `godot_devkit.repo.pm.model`, so the gate and the tool can never
describe "reviewed" or "drift" differently — one definition, two readers.

DRIFT RULES (each FAILs, naming the offending path):
  D1  a `reviewed:` pointer naming a file that is not there. The
      dangling-POINTER half only — the same shape V4 checks for `depends_on`.
      "This feature carries no `reviewed:` at all" is not drift; it is the
      absence of a document, which is a fact about a team rather than a tree.
  D2  a feature still planning/ready/building while ALL its stories are `done`
      (a forgotten advance).
  D3  a `done` milestone with a non-`done` feature child.
  D4  a status outside the schema's vocabulary — milestone, feature, story
      AND bug. It matters most for a bug: every reader that asks "is this one
      still open" tests for a NAME, so a typo reads as closed and passes in
      silence.
  D5  a `done` story under a non-`done` feature. The story terminal a team
      works to is `review`; `done` is where a CLOSE leaves it, so this is a
      close that did not finish — or `pm story done` run on its own. (A done
      story under a DONE feature is the valid historical closed state.)
  D6  a `building` milestone whose features are ALL `done` (the milestone
      analogue of D2).
  D8  the shipped version equals the `building` milestone's id (bump-at-START:
      the version names what is being built, so every crash report, save file
      and dev build carries that fact for free). EXACT string equality — the
      milestone id IS the version.
  D9  a `building` milestone declares the `branch:` its work lives on. A fresh
      checkout of the trunk sees the PM records but not the code; without the
      stamp the only recourse is guessing at `git branch -a`.
  D8/D9 encode the branch-per-milestone / bump-at-start flow and are OFF by
  default; a project shipping from the trunk and bumping at close is running a
  different valid flow, not drifting. Opt in via `[pm] checks`.

Which rules run is `[pm] checks` in devkit.toml (default: D1-D6 + V1-V5).
V6 is known but OPT-IN, as are the two flow rules named just above.

Scope: the ACTIVE tree only — archived milestones predate the convention. This
MUST pass on the legitimate mid-build state: a building milestone with mixed
children, and a feature at `review` with its stories at their `review` terminal
(nothing moves a story off `review` until a close does, and the story cascade is
opt-in, so a closed feature over `review` stories is a state a team chooses).
"""
from __future__ import annotations

import sys

from godot_devkit.repo.pm import model


def run() -> int:
    try:
        cfg = model.load()
    except model.ConfigError as err:
        # Exit 2, never 1: a config typo is not a finding, and CI must not read
        # it as "drift found" (the contract project.py states).
        print(f'[check:pm] ERROR — {err}', file=sys.stderr)
        return 2
    # The roster is validated HERE rather than in `model.load()`: a stale rule
    # id must not take `pm status` down with the gate. This is the reader a
    # narrowed roster would lie to, so this is where it has to be loud.
    stale = model.config_complaints(cfg)
    if stale:
        for msg in stale:
            print(f'[check:pm] ERROR — {msg}', file=sys.stderr)
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

    # Always walked, so the census can state how many bug files this scan
    # opened whatever the roster says; only REPORTED under D4, which owns
    # "a status outside the vocabulary" for every grain.
    bug_findings, n_bugs = model.bug_status_findings(cfg)
    if 'D4' in enabled:
        for path, why in bug_findings:
            report(f'{cfg.rel(path)}: {why}')

    n_features = 0
    n_stories = 0

    for mdir in mdirs:
        mfile = mdir / 'milestone.md'
        mid = model.field_of(mfile, 'id')
        mstat = model.field_of(mfile, 'status')

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
                reason = model.drift_dangling_record(cfg, view.fid)
                if reason:
                    report(f'feature {view.fid}: {reason} — point it at a real '
                           f'file or remove the field  [{frel}]')

            for sfile in view.stories:
                sid = model.field_of(sfile, 'id')
                sstat = model.field_of(sfile, 'status')
                srel = cfg.rel(sfile)
                if 'D4' in enabled and sstat not in cfg.story_states:
                    report(f'story {sid}: status {sstat!r} not in '
                           f'({" ".join(cfg.story_states)})  [{srel}]')
                if 'D5' in enabled and sstat == 'done' and view.status != 'done':
                    report(f'story {sid} is done but its feature {view.fid} is '
                           f'{view.status!r} (two places in this tree '
                           f'disagree)  [{srel}]')

            if 'D2' in enabled:
                reason = model.drift_stalled(view.status, view.done_n, view.total)
                if reason:
                    report(f'feature {view.fid}: {reason} (should be '
                           f'review/done)  [{frel}]')

        if ('D6' in enabled and mstat == 'building'
                and feat_total > 0 and feat_done_n == feat_total):
            report(f'milestone {mid} is {mstat!r} but all {feat_total} features '
                   f'are done (should be done)  [{cfg.rel(mfile)}]')

    # --- D8/D9: the flow checks, only when opted into ---------------------
    building = model.building_milestones(cfg) if enabled & set(model.FLOW_CHECKS) else []

    if 'D8' in enabled and building:
        version = model.shipped_version(cfg)
        ids = [mid for mid, _, _ in building]
        if version is None:
            report(f'no version found in {cfg.version_file} — D8 cannot verify '
                   f'the building milestone(s) {", ".join(ids)}')
        elif len(ids) > 1:
            # "The version names what is being built" cannot hold for two. A
            # matching sibling used to mask exactly the drift D8 exists for: a
            # milestone left at `building` when the next one started.
            report(f'{len(ids)} milestones are building ({", ".join(ids)}) — the '
                   f'version can only name one; close the finished one (D8)')
        elif version != ids[0]:
            report(f'{cfg.version_file} version {version!r} does not match the '
                   f'building milestone {ids[0]!r} — bump at milestone START, '
                   f'and the id IS the version (D8)')

    for mid, branch, mfile in building:
        if 'D9' in enabled and not branch:
            report(f'building milestone {mid} declares no branch: — a fresh '
                   f'checkout cannot find where its work lives  [{cfg.rel(mfile)}]')

    # --- V1-V6: structural + referential integrity ------------------------
    v_on = enabled & set(model.VALIDATE_CHECKS)
    v_census = {}
    if v_on:
        from godot_devkit.repo.pm import validate as _validate
        v_findings, v_census = _validate.run(cfg, v_on)
        for msg in v_findings:
            report(msg)


    print()
    census = (f'{len(mdirs)} milestone(s), {n_features} feature(s), '
              f'{n_stories} story/ies')
    # A census must never assert the opposite of the filesystem. The grain walk
    # narrows `stories/` and `bugs/` to documents that OPEN frontmatter — a
    # README parked beside a bug is a note, not a bug — and a scan that narrows
    # has to say by how much, or "0 bug(s)" reads as a fact about the directory
    # when it is a fact about the filter.
    #
    # This line is no longer a list of remembered disclosures. `Walk` records
    # every narrowing under a closed-enum reason and renders them all, in enum
    # order, printing nothing for a walk that skipped nothing — so a filter
    # added to `model.slot_walk` next year discloses itself here without
    # anybody editing this file. That is the whole difference between fixing
    # the instance and fixing the shape.
    census += model.tree_walk(cfg).disclosures()
    census += f', {n_bugs} bug(s)'
    if v_census:
        census += f', {v_census["refs"]} ref(s)'
        if v_census['unverifiable']:
            # Named, never hidden: a ref into a pruned milestone is not a pass.
            census += (f' ({v_census["unverifiable"]} UNVERIFIABLE — the ref '
                       f'names a milestone no longer in the tree)')
    what = 'status-drift / integrity violation(s)' if v_on else 'status-drift violation(s)'
    if findings:
        print(f'[check:pm] FAIL — {len(findings)} {what} across {census}')
        return 1
    clean = 'no PM-tree drift or integrity problems' if v_on else 'no PM-tree status drift'
    print(f'[check:pm] PASS — {clean}; scanned {census}')
    return 0
