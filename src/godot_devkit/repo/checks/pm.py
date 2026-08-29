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

  D11 review RETENTION — a `done` grain must not have a `review.md`. The slot
      is the TRANSIENT half of the pair: simplifier and reviewer append to it
      while the grain is open, and at close anything durable is promoted into
      `decisions.md` and the file goes. Co-located at a known path, so there is
      no filename to resolve, no exemption list and nothing to guess. OFF by
      default (see RETENTION_CHECKS).

  D13 canonical grain STRUCTURE — every milestone and feature dir carries
      exactly its slots. MISSING is drift and EXTRA is drift, and each shared
      doc must still open with its one-line instruction header, so the
      breadcrumb the dispatched agent actually reads cannot rot. Directory
      slots are permitted, never required: git does not store an empty
      directory. `pm new milestone|feature <id>` is idempotent and fills gaps.

  D14 bug LIFETIME — a bug lives in the milestone that will FIX it, so an OPEN
      bug under a `done` milestone is drift: nothing schedules the fix, and
      `prune`'s lag-by-one deletes the file where it sits. Also reports a bug
      status outside `[pm] bug_states`, which D4 does not cover and which would
      otherwise read as "closed" and pass in silence.

  D15 changelog SCHEMA — the same machinery as D12 over `changelog.md`, whose
      entries carry `**What:**` (one sentence a player would recognise) and
      `**Evidence:**` (the reference proving it shipped). Deliberately the
      smaller schema: the reasoning behind a change is a DECISION and lives in
      decisions.md, so a changelog carrying it is a commit log with a nicer
      name. Legacy logs migrate through `[pm] changelog_grandfather`, capped
      per-entry exactly as D12's ledger is.

  D16 release NOTES — a `done` milestone must have a non-empty changelog.md
      holding at least one entry D15 does not report. D15 asks whether what is
      written conforms; a conforming EMPTY log satisfies it forever, and this
      is what stops a release shipping with nothing a player can read.

  D17 grain PROSE CAPS, as a RATCHET. Everything written into a PM tree is
      grep-reachable, so every line of prose is context some future agent pays
      for — the scaffolding should not be twice the size of the thing it
      scaffolds. A story, a feature.md, a bug, a feature's decisions.md and a
      milestone's changelog.md each have a line cap, and two finding classes:
      OVERCAP (over cap, not on the ledger) and GREW (on the ledger, larger
      than its recorded ceiling). `[pm] prose_grandfather` is a DEBT ledger —
      its length is the metric, it may only shrink, and `pm prose-ledger`
      REFUSES to raise a ceiling. Without that refusal the gate is decorative.
      The caps are CONFIG (`[pm] *_lines_max`); the defaults are one consumer's
      measured p90, not a law. The mandated instruction header D13 asserts is
      excluded from every count — it is a constant an author cannot trim, so
      counting it would make the budget uncompliable.

      NOT capped: an OPEN milestone's own decisions.md. It is the append-only
      autonomous-mode trail by design, and capping it fights the process.

  D18 CLOSED-LOG — a `done` milestone still carrying its raw decision trail.
      Milestone close evidence is pointers, "a line and a link", so a done
      milestone with a 1,600-line trail was not closed, it was abandoned. Its
      threshold is derived from that rule rather than from the distribution.
      Shares D17's ledger: one `[pm]` key, so its integrity is one fact.

  D11/D13/D14/D15/D16/D17/D18 are OFF by default like D8-D12 — a tree predating the
  canonical slots is missing most of them, and a rule that turns a consumer red
  on upgrade day is unshippable. Scaffold first, then hold the line.

  D12 decision-record SCHEMA — a decision log rots into description. Every
      `## <ID> — <ISO date> — <title>` entry in a decisions.md carries exactly
      **Chose:** / **Over:** / **Because:** / **Evidence:**, in that order, one
      per line, each value <= 200 chars, the title <= 80. `Over:` is the
      load-bearing one: an entry that cannot name what it ruled out is a
      description, not a decision. `Evidence:` must be a REFERENCE — a commit
      hash, a path[:line] or a number — never a sentence. A prose `##` heading
      is not an entry and is not checked; a log may have a preamble. Legacy
      logs migrate through `[pm] decision_grandfather` (see below), whose size
      the gate PRINTS every run so it stays visibly temporary. OFF by default.

Which rules run is `[pm] checks` in devkit.toml (default: D1-D7 + V1-V6).

Scope: the ACTIVE tree only — archived milestones predate the convention. This
MUST pass on the legitimate mid-build state: a building milestone with mixed
children, and a feature at `review` with its stories at their `review` terminal
(the cascade holds stories there until the atomic feature->done flip).
"""
from __future__ import annotations

import sys

from godot_devkit.repo.pm import model


def _retention(cfg, report) -> int:
    """D11 — the transient `review.md` slot outliving the grain that owns it.

    Returns the number of `done` grains scanned, so the census can carry it:
    this rule's population is not "every grain", it is the closed ones, and a
    run where nothing had closed must not read like a run where everything was
    clean.

    Co-located, so there is no resolution step and nothing to guess. The rule
    this replaced matched a findings-doc FILENAME back to the grain it "named",
    and against a real corpus that got the answer backwards: 6 of 123 docs
    resolved, and those 6 were the durable ones `reviewed:` already pointed at.
    A known path deletes the question rather than narrowing it.
    """
    stale = model.stale_review_files(cfg)
    n_done = sum(1 for g in model.grain_dirs(cfg) if g.status == 'done')
    if not n_done:
        # Printed, NOT reported. "Nothing has closed yet" is this rule's own
        # success state; D12 fails on a zero census because a missing log means
        # it can never fire, which is the opposite situation.
        print(f'[check:pm] D11: no `done` grain in the tree — nothing to retire')
        return 0
    for grain, rfile in stale:
        report(f'{cfg.rel(rfile)} is transient but {grain.kind} {grain.gid} is '
               f'done — promote anything durable into '
               f'{model.DECISION_FILE_NAME}, then delete it (D11)')
    return n_done


def _structure(cfg, report) -> int:
    """D13 — the canonical grain shape. Returns the grain dirs checked.

    Missing is drift AND extra is drift. The extra half is the one that earns
    the rule: `plans/`, `findings/`, `AUDIT-REPORT.md`, `audit-prompt.md` and
    `DELETED-SCENARIO-LEDGER.md` all exist in a real tree because no slot was
    scaffolded AND nothing flagged the invention. A missing-only check would
    leave every one of them there forever.
    """
    grains = model.grain_dirs(cfg)
    for path, why in model.structure_findings(cfg):
        report(f'{cfg.rel(path)}: {why} (D13)')
    print(f'[check:pm] D13: {len(grains)} grain dir(s) held to the canonical '
          f'slots; `pm new milestone|feature <id>` fills a gap')
    return len(grains)


def _bug_lifetime(cfg, report) -> int:
    """D14 — an open bug under a `done` milestone. Returns the bugs scanned.

    Not cosmetic: `prune`'s lag-by-one deletes a done milestone's directory the
    moment the next one closes, so an open bug parked in a closed milestone is
    scheduled for deletion. Moving it to the milestone that will FIX it is what
    makes prune safe by construction.
    """
    findings, scanned = model.open_bugs_under_done(cfg)
    if not scanned:
        # This rule's own success state, like D11's: a tree with no bugs filed
        # is not a tree whose bug lifetime is broken.
        print(f'[check:pm] D14: no bug files under {cfg.roadmap_dir}/ — '
              f'nothing to place')
        return 0
    for path, why in findings:
        report(f'{cfg.rel(path)} {why} (D14)')
    return scanned


def _log_schema(cfg, report, schema) -> tuple[int, int]:
    """D12 / D15 — one append-only log's entry schema, and the ledger that lets
    it ship. Returns (logs scanned, entries scanned).

    ONE implementation over both rules. A decisions.md and a changelog.md differ
    in their field list and their file name — data the schema carries — and in
    nothing else this function does, so a second copy of it would be a second
    chance to get the census, the case-variant handling or the shrink-only
    ledger subtly different between two rules a reader believes are the same.

    The census is not decoration. Without it "scanned 58 logs / 294 entries",
    "scanned 1 log" and "scanned 2 logs / 0 entries" print identically, and that
    is what let a case-folded census and a title-guessing detector both pass in
    silence. A rule's population belongs on stdout beside its verdict.

    The ledger is the whole migration story: 57 logs in one consumer conform to
    none of D12, and a rule that turns a consumer red on upgrade day is
    unshippable. So an exempted log is named in the schema's own `[pm]` ledger
    key, the gate PRINTS how many are exempt on every run, and the ledger can
    only shrink — an exemption that suppresses nothing, or a cap reaching past
    the entries it claims to cover, is itself reported.
    """
    rule, name = schema.rule, schema.plural
    ledger = model.ledger_for(cfg, schema)
    logs, variants = model.log_files(cfg, schema)
    whole = sum(1 for cap in ledger.values() if cap is None)
    print(f'[check:pm] {rule} grandfather: {len(ledger)} {name}(s) exempt '
          f'({whole} whole, {len(ledger) - whole} capped) — this ledger may '
          f'only shrink')

    # A log spelled another way is a log this rule cannot see. Never folded in:
    # the two platforms would then emit opposite findings about the same file.
    for path in variants:
        report(f'{cfg.rel(path)} is a case variant of '
               f'{schema.file_name} — {rule} reads EXACT names, so this '
               f'log is invisible to it; rename it via `pm new` ({rule})')

    # Rule 4: a rule that scanned nothing must say so rather than print PASS.
    if not logs:
        report(f'{rule} is enabled but no {schema.file_name} exists under '
               f'{cfg.roadmap_dir}/ — the rule scanned nothing')

    n_entries = 0
    seen: set[str] = set()
    for log in logs:
        key = model.relkey(cfg, log)
        cap = ledger.get(key, 0)  # 0 == not listed: nothing is exempt
        if key in ledger:
            seen.add(key)
        try:
            text = model.read_raw(log)
        except (OSError, UnicodeDecodeError) as err:
            # Reported, never counted as scanned-with-zero-entries: an
            # unreadable log would otherwise be exempt from the rule for free.
            report(f'{key} cannot be read ({err}) — a log {rule} cannot open is '
                   f'not a log {rule} has checked ({rule})')
            continue
        # Reported whatever the ledger says: an unclosed comment and an
        # unterminated fence are defects of the FILE, not of an entry — they are
        # the reason the entry count below may be a lie. Both, never one: the
        # fence mask was added to stop a quoted `<!--` eating the log, and an
        # unterminated fence then ate it the other way round in silence.
        for defect in (model.log_comment_defect(text, rule),
                       model.log_fence_defect(text, rule)):
            if defect:
                report(f'{key}: {defect} ({rule})')
        entries = model.log_entries_in(text)
        n_entries += len(entries)
        n_suppressed = 0
        for ordinal, eid, why in model.entry_violations_in(entries, schema):
            if cap is None or ordinal < cap:
                n_suppressed += 1
                continue
            report(f'{key}: {eid} — {why} ({rule})')
        if key not in ledger:
            continue
        # Shrink-only, both directions: an exemption covering no violation has
        # done its job and must go, and a cap reaching past the end of the log
        # is a claim the file no longer supports.
        if not n_suppressed:
            report(f'{key} is in {schema.ledger_key} but every entry conforms '
                   f'— drop it from the ledger ({rule})')
        if cap is not None and cap > len(entries):
            report(f'{key} is grandfathered to {cap} entries but the log has '
                   f'{len(entries)} — lower the cap ({rule})')

    for key in ledger:
        if key not in seen:
            report(f'{key} is in {schema.ledger_key} but no such log exists '
                   f'— drop it from the ledger ({rule})')

    print(f'[check:pm] {rule}: {len(logs)} {name}(s), {n_entries} entry/ies '
          f'held to the schema')
    return len(logs), n_entries


def _prose(cfg, report, enabled) -> tuple[int, int, int]:
    """D17 / D18 — the prose ratchet. Returns (docs, corpus lines, closed logs).

    ONE implementation over both rules, for the reason `_log_schema` is one
    over D12 and D15: they share the grain walk, the line measurement, the
    ledger and the shrink-only rules, and differ only in which document each
    reports. Two implementations would be two chances to disagree about what a
    grain document even is.

    MEASUREMENT IS NOT GATED BY `enabled`; only reporting is. A ledger entry
    for a story suppresses a story finding whether or not D17 is switched on,
    and computing it otherwise would tell a D18-only consumer to delete the
    debt record of every document nobody had looked at.
    """
    docs = model.prose_docs(cfg)
    ledger_rule = 'D17' if 'D17' in enabled else 'D18'
    print(f'[check:pm] {ledger_rule} ledger: {len(cfg.prose_grandfather)} '
          f'document(s) carrying prose debt — this ledger may only shrink')
    for rule, msg in model.prose_findings(cfg, docs):
        if rule == model.LEDGER_FINDING:
            # One `[pm]` key serves both rules, so its hygiene is reported
            # under whichever of them is on rather than going unchecked when
            # the consumer enabled only the other.
            report(f'{msg} ({ledger_rule})')
        elif rule in enabled:
            report(f'{msg} ({rule})')

    capped = [d for d in docs if d.rule == 'D17']
    closed = [d for d in docs if d.rule == 'D18']
    if 'D17' in enabled:
        # Rule 4: a rule that scanned nothing must say so rather than print
        # PASS. An empty capped population means a misconfigured tree, never a
        # clean one.
        if not capped:
            report('D17 is enabled but no story, feature.md, bug, feature '
                   f'decisions.md or changelog.md exists under '
                   f'{cfg.roadmap_dir}/ — the rule scanned nothing')
        print(f'[check:pm] D17: {len(capped)} grain document(s), '
              f'{sum(d.lines for d in capped)} line(s) of capped prose — this '
              f'number should only shrink')
    if 'D18' in enabled:
        if closed:
            print(f'[check:pm] D18: {len(closed)} closed milestone log(s) held '
                  f'to the close-evidence budget '
                  f'({cfg.closed_log_lines_max} lines)')
        else:
            # This rule's own success state, like D11's and D16's: a tree where
            # nothing has closed is not a tree with an abandoned decision log.
            print('[check:pm] D18: no `done` milestone with a decisions.md — '
                  'no raw trail to collapse')
    return len(capped), sum(d.lines for d in capped), len(closed)


def _release_notes(cfg, report) -> int:
    """D16 — a `done` milestone with no release notes. Returns done milestones.

    D15 asks whether what is written conforms; this asks whether anything is
    written at all, and a perfectly conforming EMPTY log satisfies D15 forever.
    A milestone closing with nothing a player could read is the release that
    ships without notes, and there is no later moment when somebody reconstructs
    them.
    """
    findings, scanned = model.milestones_without_notes(cfg)
    if not scanned:
        # This rule's own success state, like D11's and D14's: a tree where
        # nothing has shipped yet is not a tree shipping without notes.
        print('[check:pm] D16: no `done` milestone in the tree — nothing has '
              'shipped yet')
        return 0
    for path, why in findings:
        report(f'{cfg.rel(path)}: {why} (D16)')
    return scanned


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

    n_done_grains = 0
    if 'D11' in enabled:
        n_done_grains = _retention(cfg, report)

    n_logs = 0
    n_entries = 0
    if 'D12' in enabled:
        n_logs, n_entries = _log_schema(cfg, report, model.DECISION_SCHEMA)

    n_clogs = 0
    n_centries = 0
    if 'D15' in enabled:
        n_clogs, n_centries = _log_schema(cfg, report, model.CHANGELOG_SCHEMA)

    n_grain_dirs = _structure(cfg, report) if 'D13' in enabled else 0
    n_bugs = _bug_lifetime(cfg, report) if 'D14' in enabled else 0
    n_shipped = _release_notes(cfg, report) if 'D16' in enabled else 0

    n_prose = n_prose_lines = n_closed_logs = 0
    if enabled & set(model.PROSE_CHECKS):
        n_prose, n_prose_lines, n_closed_logs = _prose(cfg, report, enabled)

    print()
    census = (f'{len(mdirs)} milestone(s), {n_features} feature(s), '
              f'{n_stories} story/ies')
    if 'D11' in enabled:
        census += f', {n_done_grains} done grain(s)'
    if 'D12' in enabled:
        census += f', {n_logs} decision log(s), {n_entries} entry/ies'
    if 'D15' in enabled:
        census += f', {n_clogs} changelog(s), {n_centries} entry/ies'
    if 'D13' in enabled:
        census += f', {n_grain_dirs} grain dir(s)'
    if 'D14' in enabled:
        census += f', {n_bugs} bug(s)'
    if 'D16' in enabled:
        census += f', {n_shipped} shipped milestone(s)'
    if 'D17' in enabled:
        census += (f', {n_prose} capped document(s), {n_prose_lines} line(s) '
                   f'of prose')
    if 'D18' in enabled:
        census += f', {n_closed_logs} closed milestone log(s)'
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
