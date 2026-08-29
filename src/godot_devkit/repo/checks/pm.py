"""check pm — tier-1 guard against PM-tree status DRIFT.

The transition CLI (`godot-devkit pm ...`) makes each status move
precondition-checked; this makes the resulting INCONSISTENCY loud. It imports
the vocabularies, the review-record definition and the feature-grain drift
predicates from `godot_devkit.repo.pm.model`, so the gate and the tool can never
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
  D8  the shipped version equals the `building` milestone's id (bump-at-START:
      the version names what is being built, so every crash report, save file
      and dev build carries that fact for free). EXACT string equality — the
      milestone id IS the version.
  D9  a `building` milestone declares the `branch:` its work lives on. A fresh
      checkout of the trunk sees the PM records but not the code; without the
      stamp the only recourse is guessing at `git branch -a`.
  D10 that branch is CHECKED OUT IN THE TRUNK. D9 proves a milestone says where
      its code lives; D10 proves it is where a human can follow it. A milestone
      declaring a trunk branch is skipped — it is not using an integration
      branch at all.

  D8-D10 encode the branch-per-milestone / bump-at-start flow and are OFF by
  default; a project shipping from the trunk and bumping at close is running a
  different valid flow, not drifting. Opt in via `[pm] checks`.

  D7  archive presence — git history IS the archive. A `zz_archive/` dir under
      the roadmap or the review dir, or MORE than one `done` milestone dir at
      the roadmap root (lag-by-one keeps exactly the most recently closed),
      means a prune is due.

  D11 review-dir RETENTION — a findings doc outlives its purpose. A `*.md` in
      the review dir is legitimate while the grain it NAMES is still open; once
      that feature or milestone is `done` the durable record is the grain's own
      review record and the transient doc is dead weight a `grep` still finds.
      A file naming NO grain is reported separately: it is unreachable by
      definition. OFF by default (see RETENTION_CHECKS).

  D12 decision-record SCHEMA — a decision log rots into description. Every
      `## <ID> — <ISO date> — <title>` entry in a DECISIONS.md carries exactly
      **Chose:** / **Over:** / **Because:** / **Evidence:**, in that order, one
      per line, each value <= 200 chars, the title <= 80. `Over:` is the
      load-bearing one: an entry that cannot name what it ruled out is a
      description, not a decision. `Evidence:` must be a REFERENCE — a commit
      hash, a path[:line] or a number — never a sentence. A prose `##` heading
      is not an entry and is not checked; a log may have a preamble. Legacy
      logs migrate through `[pm] decision_grandfather` (see below), whose size
      the gate PRINTS every run so it stays visibly temporary. OFF by default.

Which rules run is `[pm] checks` in devkit.toml (default: all seven).

Scope: the ACTIVE tree only — archived milestones predate the convention. This
MUST pass on the legitimate mid-build state: a building milestone with mixed
children, and a feature at `review` with its stories at their `review` terminal
(the cascade holds stories there until the atomic feature->done flip).
"""
from __future__ import annotations

import sys

from godot_devkit.repo.pm import model


def _decision_schema(cfg, report) -> None:
    """D12 — the decision-record schema, and the ledger that lets it ship.

    The ledger is the whole migration story: 57 logs in one consumer conform to
    none of this, and a rule that turns a consumer red on upgrade day is
    unshippable. So an exempted log is named in `[pm] decision_grandfather`, the
    gate PRINTS how many are exempt on every run, and the ledger can only
    shrink — an exemption that suppresses nothing, or a cap reaching past the
    entries it claims to cover, is itself reported.
    """
    ledger = dict(cfg.decision_grandfather)
    logs = model.decision_files(cfg)
    whole = sum(1 for cap in ledger.values() if cap is None)
    print(f'[check:pm] D12 grandfather: {len(ledger)} decision log(s) exempt '
          f'({whole} whole, {len(ledger) - whole} capped) — this ledger may '
          f'only shrink')

    # Rule 4: a rule that scanned nothing must say so rather than print PASS.
    if not logs:
        report(f'D12 is enabled but no {model.DECISION_FILE_NAME} exists under '
               f'{cfg.roadmap_dir}/ — the rule scanned nothing')

    seen: set[str] = set()
    for log in logs:
        key = model.decision_relkey(cfg, log)
        cap = ledger.get(key, 0)  # 0 == not listed: nothing is exempt
        if key in ledger:
            seen.add(key)
        n_suppressed = 0
        for ordinal, eid, why in model.decision_violations(log):
            if cap is None or ordinal < cap:
                n_suppressed += 1
                continue
            report(f'{key}: {eid} — {why} (D12)')
        if key not in ledger:
            continue
        # Shrink-only, both directions: an exemption covering no violation has
        # done its job and must go, and a cap reaching past the end of the log
        # is a claim the file no longer supports.
        if not n_suppressed:
            report(f'{key} is in decision_grandfather but every entry conforms '
                   f'— drop it from the ledger (D12)')
        n_entries = len(model.decision_entries(log))
        if cap is not None and cap > n_entries:
            report(f'{key} is grandfathered to {cap} entries but the log has '
                   f'{n_entries} — lower the cap (D12)')

    for key in ledger:
        if key not in seen:
            report(f'{key} is in decision_grandfather but no such log exists '
                   f'— drop it from the ledger (D12)')


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
    all_feature_ids: list[str] = []

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
            all_feature_ids.append(view.fid)
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

    # --- D8-D10: the flow checks, only when opted into --------------------
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
        if 'D10' in enabled and branch and branch not in cfg.trunk_branches:
            trunk, why = model.trunk_checkout_branch(cfg)
            if trunk is None:
                # Named, not skipped: an unverifiable D10 must look different
                # from a satisfied one.
                print(f'  UNVERIFIED  D10 for milestone {mid}: {why}')
            elif trunk != branch:
                report(f'building milestone {mid} declares branch {branch!r} but '
                       f'the trunk tree is on {trunk!r} — the integration branch '
                       f'belongs in the trunk, checked out')

    # --- V1-V5: structural + referential integrity ------------------------
    v_on = enabled & set(model.VALIDATE_CHECKS)
    v_census = {}
    if v_on:
        from godot_devkit.repo.pm import validate as _validate
        v_findings, v_census = _validate.run(cfg, v_on)
        for msg in v_findings:
            report(msg)

    if 'D7' in enabled:
        for archive in (cfg.roadmap / model.ARCHIVE_DIR_NAME,
                        cfg.root / cfg.review_dir / model.ARCHIVE_DIR_NAME):
            if archive.is_dir():
                report(f'{cfg.rel(archive)}/ exists — a prune is due '
                       f'(git history is the archive)')
        if done_milestone_dirs > 1:
            report(f'{done_milestone_dirs} done milestone dirs at the roadmap '
                   f'root — lag-by-one allows 1; a prune is due')

    if 'D11' in enabled:
        # A file the tree still POINTS at is durable by definition, so resolve
        # the pointers once and exempt them: a project whose review records
        # live in review_dir must satisfy this trivially, or the rule would be
        # punishing the layout the setting is named for.
        pointed = {model.review_record_for(cfg, fid) for fid in all_feature_ids}
        pointed.discard(None)
        for rfile in model.review_dir_files(cfg):
            if cfg.rel(rfile) in pointed:
                continue
            named = model.grain_named_by(cfg, rfile)
            if named is None:
                report(f'{cfg.rel(rfile)} names no grain in the tree — nothing '
                       f'can reach it, and a grep still can (D11)')
            elif named[1] == 'done':
                report(f'{cfg.rel(rfile)} is transient and {named[0]} is done '
                       f'— its durable record is the grain\'s own (D11)')

    if 'D12' in enabled:
        _decision_schema(cfg, report)

    print()
    census = (f'{len(mdirs)} milestone(s), {n_features} feature(s), '
              f'{n_stories} story/ies')
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
