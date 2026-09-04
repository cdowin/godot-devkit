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
  D3  a `done` milestone with a non-`done` feature child. `done` means every
      thing inside this tree's authority is finished, so it cannot be true of
      a milestone while one of its features says otherwise.
  D4  a status outside the schema's vocabulary — milestone, feature, story
      AND bug. It matters most for a bug: every reader that asks "is this one
      still open" tests for a NAME, so a typo reads as closed and passes in
      silence.
  D5  a story at WORK under a feature that says it has not started. Not "a
      done story under a non-done feature": under one ordered lifecycle a
      story reaches `done` while its feature is still `reviewing`, `accepted`
      or `packaging`, and that is the normal path — the feature's remaining
      work is not story work. The disagreement is across the one split each
      vocabulary carries (`building`, where the shaping half ends): the story
      is building or later, the feature is still planning or ready.
  D6  a `building` milestone whose features are ALL `done` (the milestone
      analogue of D2). It keys off the literal `building`, so a milestone that
      has advanced to `reviewing` silences it and the release gate RUNS —
      which is the whole point: the gate that informs the ship decision has to
      run while that decision is still open.
  D8  the shipped version equals the `building` milestone's id (bump-at-START:
      the version names what is being built, so every crash report, save file
      and dev build carries that fact for free). EXACT string equality — the
      milestone id IS the version — or a hotfix of a RELEASED milestone: a
      `done` id in the tree plus one positive integer (0.90.3 -> 0.90.3.1).
  D9  a `building` milestone declares the `branch:` its work lives on. A fresh
      checkout of the trunk sees the PM records but not the code; without the
      stamp the only recourse is guessing at `git branch -a`.
  D10 a `building` milestone's `branch:` is empty, or equals the configured
      mainline (`[repo_hygiene] mainline`, `origin/`-stripped — stock
      `origin/main` reads as `main`). D9 only requires SOME stamp; D10 also
      refuses the trunk itself, so a repo may run D9 alone (branch declared,
      wherever it points) or add D10 for the stricter guarantee. A repo may
      also rely on D9 without D10.
  D8/D9/D10 encode the branch-per-milestone / bump-at-start flow and are OFF
  by default; a project shipping from the trunk and bumping at close is
  running a different valid flow, not drifting. Opt in via `[pm] checks`.

Which rules run is `[pm] checks` in devkit.toml (default: D1-D6 + V1-V5).
V6 is known but OPT-IN, as are the three flow rules named just above.

Scope: the ACTIVE tree only — archived milestones predate the convention. This
MUST pass on the legitimate mid-build state: a building milestone with mixed
children, a feature at `reviewing` with its stories at their `reviewing`
terminal (nothing moves a story off `reviewing` until a close does, and the
story cascade is opt-in, so a closed feature over `reviewing` stories is a
state a team chooses), and a milestone walking `reviewing` -> `accepted` ->
`packaging` with every feature already `done`.
"""
from __future__ import annotations

import re

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

    # Rule 4 again, on a rule rather than on the walk: D5 compares a story
    # against its feature across ONE split (`building`, where the shaping half
    # ends). A project that renamed its vocabulary and dropped that word leaves
    # D5 with nothing to compare, and a rule reporting nothing must say why —
    # otherwise its silence is read as a clean tree. A NOTE, not a finding: a
    # renamed vocabulary is a valid configuration, not drift.
    if 'D5' in enabled:
        blind = model.split_blind_vocabularies(cfg)
        if blind:
            print(f'[check:pm] NOTE — D5 cannot place {model.BUILDING!r} in '
                  f'[pm] {" / ".join(blind)}, so it has no split to compare a '
                  f'story against its feature across and is reporting nothing '
                  f'for this tree')

    n_features, n_stories, retired = _drift_walk(cfg, enabled, mdirs, report)

    # Rule 4 from the other side: D4 stopped REPORTING these words, so
    # something has to keep saying they are there. The 0.24.0 window accepts a
    # status a tree already holds and 0.25.0 removes it, so the census is the
    # migration's own progress bar — live, because a number written into a
    # comment or a changelog goes stale the first time somebody rewrites a
    # file. A gate that answered the union with silence would have narrowed
    # itself into a clean PASS over exactly the migration it exists to make
    # visible. A NOTE, not a finding: the tree is not drifting, it is holding
    # a word on a deadline.
    if retired:
        census = ', '.join(
            f'{word} x{n} (replaced by {model.DEPRECATED_STATES[word]})'
            for word, n in retired.items())
        print(f'[check:pm] NOTE — {sum(retired.values())} grain(s) hold a '
              f'status the 0.24.0 deprecation window accepts and 0.25.0 '
              f'removes: {census}. Rewrite them before that pin bump; the '
              f'`pm` verbs already write the replacement.')

    _flow_findings(cfg, enabled, report)

    # --- V1-V6: structural + referential integrity ------------------------
    v_on = enabled & set(model.VALIDATE_CHECKS)
    v_census: dict = {}
    if v_on:
        from godot_devkit.repo.pm import validate as _validate
        v_findings, v_census = _validate.run(cfg, v_on)
        for msg in v_findings:
            report(msg)

    return _verdict(cfg, findings, len(mdirs), n_features, n_stories, n_bugs,
                    v_on, v_census)


# D2's and D6's shared tail. Both used to name `done` as the state to move to —
# D2 said "should be review/done", D6 "should be done" — and D6's version was
# the deadlock this vocabulary exists to break: it demanded the close BEFORE
# the gate that informs the close could run. `done` is the LAST state now, not
# the next one, and neither rule has an opinion about which state is.
ADVANCE_IT = 'advance it (`done` is the LAST state, not the next one)'


def _drift_walk(cfg: model.PmConfig, enabled: set[str], mdirs,
                report) -> tuple[int, int, dict[str, int]]:
    """D1-D6 over every grain.

    Returns the (feature, story) census plus how many grains hold each word of
    the deprecation window — counted HERE, in the one walk that already opens
    every grain file, rather than by a second pass with its own idea of which
    files are grains.
    """
    n_features = 0
    n_stories = 0
    # Seeded from the window's own declaration order, not filled by first
    # sighting: a census line whose order depends on which milestone the walker
    # reached first reads differently on two runs over one tree.
    retired = {word: 0 for word in model.DEPRECATED_STATES}

    for mdir in mdirs:
        mfile = mdir / model.MILESTONE_DOC
        mid = model.field_of(mfile, 'id')
        mstat = model.field_of(mfile, 'status')

        if model.deprecated_write(mstat, cfg.milestone_states):
            retired[mstat] += 1
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

            if model.deprecated_write(view.status, cfg.feature_states):
                retired[view.status] += 1
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
                if model.deprecated_write(sstat, cfg.story_states):
                    retired[sstat] += 1
                if 'D4' in enabled and sstat not in cfg.story_states:
                    report(f'story {sid}: status {sstat!r} not in '
                           f'({" ".join(cfg.story_states)})  [{srel}]')
                if 'D5' in enabled and model.drift_ahead_of_parent(
                        sstat, cfg.story_states,
                        view.status, cfg.feature_states):
                    report(f'story {sid} is {sstat!r} but its feature '
                           f'{view.fid} is still {view.status!r} — the story '
                           f'is at work and the feature says it has not '
                           f'started (two places in this tree disagree)'
                           f'  [{srel}]')

            if 'D2' in enabled:
                reason = model.drift_stalled(view.status, view.done_n, view.total)
                if reason:
                    report(f'feature {view.fid}: {reason} — {ADVANCE_IT}'
                           f'  [{frel}]')

        if ('D6' in enabled and mstat == model.BUILDING
                and feat_total > 0 and feat_done_n == feat_total):
            report(f'milestone {mid} is {mstat!r} but all {feat_total} '
                   f'features are done — you finished the features and the '
                   f'milestone still calls itself {mstat!r}; {ADVANCE_IT}'
                   f'  [{cfg.rel(mfile)}]')

    return n_features, n_stories, {word: n for word, n in retired.items() if n}


_HOTFIX_N = re.compile(r'[1-9][0-9]*')


def _is_hotfix_of_released(cfg: model.PmConfig, version: str) -> bool:
    """`<id>.N` for a DONE milestone in the tree — a hotfix cut from the mainline.

    A hotfix (0.90.3 -> 0.90.3.1) is the RELEASED milestone plus one positive
    integer, on a release branch off main, while the next milestone keeps
    building under its own id; retire's lag-by-one keeps that released
    milestone in the tree. Only `done` qualifies: a `.N` on a planning or
    building id is not a hotfix of anything, and D8's equality would refuse the
    release branch's version for no reason it can act on.
    """
    for mdir, mid in model.known_milestones(cfg):
        if not mid or not version.startswith(mid + '.'):
            continue
        if model.field_of(mdir / model.MILESTONE_DOC, 'status') != 'done':
            continue
        if _HOTFIX_N.fullmatch(version[len(mid) + 1:]):
            return True
    return False


def _flow_findings(cfg: model.PmConfig, enabled: set[str], report) -> None:
    """D8/D9/D10 — the branch-per-milestone / bump-at-start flow, opt-in."""
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
        elif version != ids[0] and not _is_hotfix_of_released(cfg, version):
            report(f'{cfg.version_file} version {version!r} does not match the '
                   f'building milestone {ids[0]!r} — bump at milestone START, '
                   f'and the id IS the version; a hotfix is a done milestone id in '
                   f'this tree plus one positive integer (D8)')

    mainline = model.mainline_branch() if 'D10' in enabled and building else ''

    for mid, branch, mfile in building:
        if 'D9' in enabled and not branch:
            report(f'building milestone {mid} declares no branch: — a fresh '
                   f'checkout cannot find where its work lives  [{cfg.rel(mfile)}]')
        if 'D10' in enabled:
            if not branch:
                report(f'building milestone {mid} declares no branch: — D10 '
                       f'needs a branch off the mainline ({mainline!r}) to '
                       f'declare  [{cfg.rel(mfile)}]')
            elif branch == mainline:
                report(f'building milestone {mid} declares branch: {branch!r}, '
                       f'the mainline itself — work must live off '
                       f'{mainline!r}, not on it (D10)  [{cfg.rel(mfile)}]')


def _verdict(cfg: model.PmConfig, findings: list[str], n_milestones: int,
             n_features: int, n_stories: int, n_bugs: int,
             v_on: set[str], v_census: dict) -> int:
    """Render the census + verdict from what the phases reported."""
    print()
    census = (f'{n_milestones} milestone(s), {n_features} feature(s), '
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
