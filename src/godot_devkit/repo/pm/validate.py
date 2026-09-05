"""validate.py — structural + referential integrity of the PM tree.

A DIFFERENT question from `check pm`'s drift rules. Drift asks "are these
statuses consistent with each other?"; validation asks "is this tree
well-formed, and are its references real?" A milestone can be perfectly
undrifted and still depend on a feature that does not exist.

    V1  frontmatter is well-formed (a leading fence, with `id:` and `status:`)
    V2  the id matches the path (the id==path convention the resolvers rely on)
    V3  parentage is consistent — a story's `feature:`/`milestone:` and a
        feature's `milestone:` name the grains that actually own them
    V4  `depends_on` / `consumed_by` refs resolve — and, on a bug, `caused_by:`
    V5  the feature dependency graph is ACYCLIC — a cycle means no build order
        exists at all
    V6  a generated execution-list block, WHERE ONE EXISTS, matches the tree it
        was rendered from (the list is opt-in per file; absence is not
        staleness). OPT-IN via `[pm] checks`: a generated view going stale
        while ordinary work moves the tree is not a defect in the tree, and
        `pm sync --check` asks the same question on demand.

**Pruned milestones are not errors.** Git history is the archive, so a ref like
`0.19.4` naming a milestone no longer in the working tree is expected. V4
resolves only refs whose MILESTONE is present and censuses the rest as
UNVERIFIABLE — the same discipline `check props` uses. Failing them would
punish the prune model; ignoring them silently would hide a typo, so they are
counted and reported in the summary.

**A bug is walked for its ONE ref, by both readers.** `caused_by:` is a ref like
any other, so V4 resolves it and `pm validate` and `check pm` report it in the
same line — one definition, two readers, which is the property the whole
`test_pm_*` quartet exists to hold. A ref naming nothing is an INTEGRITY fact,
the class this package keeps as a gate; whether a given cause counts as an
escape is a judgement, and that belongs to `pm ledger report`. There is no
switch here to run one reader narrower than the other: that would be a second
answer to one question, which is how the two ever diverge.

**A bug is NOT counted in `census['grains']`.** The walk reaches it for
`caused_by:` alone, so `census['refs']` moves and the grain count does not —
V1/V2/V3 are still stated over milestones, features and stories exactly as
they always were, and `check pm` remains the one home of the bug census
(`N bug(s)`, from `model.bug_status_findings`).
"""
from __future__ import annotations

from pathlib import Path

from godot_devkit.repo.pm import model

_REF_KEYS = ('depends_on', 'consumed_by')

# The bug field that names the feature whose change produced the bug. A SCALAR,
# not a list: one bug has one cause, and `caught_in:` already holds the other
# half of the provenance (which milestone FOUND it).
CAUSED_BY = 'caused_by'


class Unparseable(Exception):
    """A ref list this parser cannot read. NEVER silently an empty list.

    Returning [] would mean "no refs to check" — so a trailing comment, a YAML
    block sequence, or a bare scalar would take every ref out of V4's reach and
    still report clean. An unreadable value is a finding.
    """


def _refs(path: Path, key: str) -> list[str]:
    """The ids inside a `key: ["a", "b"]` frontmatter list.

    Deliberately narrow: the scaffolder mints exactly this flat inline form, so
    anything else is either hand-authored drift or a shape this parser would
    misread. Both get reported rather than skipped.
    """
    raw = model.field_of(path, key).strip()
    if not raw or raw in ('[]', 'null', '~'):
        return []
    if not (raw.startswith('[') and raw.endswith(']')):
        raise Unparseable(f'{key}: {raw!r} is not an inline list — write '
                          f'{key}: ["a", "b"] (a block sequence or trailing '
                          f'comment cannot be read from the frontmatter line)')
    inner = raw[1:-1]
    if '[' in inner or ']' in inner:
        raise Unparseable(f'{key}: {raw!r} nests brackets — only a flat list '
                          f'of ids is supported')
    out = []
    for part in inner.split(','):
        part = part.strip()
        if not part:
            continue
        if part[0] in '"\'' and part[-1] == part[0]:
            part = part[1:-1]
        if ',' in part or ' ' in part.strip():
            raise Unparseable(f'{key}: entry {part!r} contains a separator — '
                              f'ids never contain spaces or commas')
        if part:
            out.append(part)
    return out


def _safe_refs(path: Path, key: str, bad, rel: str) -> list[str]:
    try:
        return _refs(path, key)
    except Unparseable as err:
        bad(f'{rel}: {err}')
        return []


def _scalar_ref(path: Path, key: str) -> list[str]:
    """The ONE id inside a `key: <id>` frontmatter scalar, as a 0-or-1 list.

    The scalar twin of `_refs`, and it returns a list for the same reason: the
    census / UNVERIFIABLE / V4 block downstream is one home, not two.

    Narrow on purpose, and for `_refs`'s reason inverted: a value wearing a
    LIST's clothes (`["0.1/a"]`) would reach the resolver as a milestone id
    that no `milestone_dir` glob matches, and be censused UNVERIFIABLE — a
    hand-written list quietly reported as "its milestone was pruned". An id
    holds no bracket, comma, quote or space, so a value that does is a finding.
    """
    raw = model.field_of(path, key).strip()
    if not raw or raw in ('[]', 'null', '~'):
        return []
    if raw[0] in '[{' or raw[-1] in ']}':
        raise Unparseable(f'{key}: {raw!r} is a list or a mapping — {key} is '
                          f'one id, written bare ({key}: 0.1/some-feature)')
    if any(c in raw for c in ',\'" \t'):
        raise Unparseable(f'{key}: {raw!r} is not a single id — ids hold no '
                          f'commas, quotes or whitespace')
    return [raw]


def _safe_scalar_ref(path: Path, key: str, bad, rel: str) -> list[str]:
    try:
        return _scalar_ref(path, key)
    except Unparseable as err:
        bad(f'{rel}: {err}')
        return []


def _grain_exists(cfg: model.PmConfig, ref: str) -> bool | None:
    """True/False if resolvable, None when the owning milestone is not present.

    None is the honest answer for a ref into a pruned milestone: it is not a
    finding, and it is not a pass either.
    """
    mid = ref.partition('/')[0]
    if model.milestone_dir(cfg, mid) is None:
        return None
    depth = ref.count('/')
    if depth == 0:
        return True
    if depth == 1:
        return model.feature_file(cfg, ref) is not None
    return model.story_file(cfg, ref) is not None


def _feature_exists(cfg: model.PmConfig, ref: str) -> bool | None:
    """`_grain_exists` for a ref that must name a FEATURE — `caused_by:`'s shape.

    The same three answers, including None for a ref into a pruned milestone.
    A milestone id or a story id is False here rather than True: `caused_by:`
    records the CHANGE that produced a bug, and a milestone is a container of
    changes, not one. Accepting either would make the escape count in
    `pm ledger report` attribute a bug to something that cannot own it.

    An OSError is False, never a traceback: `Path.is_dir()` RAISES on a
    component longer than the filesystem's NAME_MAX up to 3.13 and answers
    False from 3.14 on, so a hand-typed over-long id would fail `pm validate`
    with a stack trace on one interpreter and a finding on another. A value the
    filesystem itself refuses names no feature — the same answer `cli._exists`
    settled for paths.
    """
    try:
        if model.milestone_dir(cfg, ref.partition('/')[0]) is None:
            return None
        return model.feature_file(cfg, ref) is not None
    except OSError:
        return False


def _check_ref_ids(cfg: model.PmConfig, path, key: str, refs: list[str],
                   on: set[str], bad, census: dict, exists=_grain_exists) -> list[str]:
    """The census / unverifiable / V4 block for a ref key's already-parsed ids.

    One home for the shape every grain kind runs (a V7 author touches this
    block, not three pastes of it) — over a LIST key or a scalar one, because
    the parser hands both in as ids. Returns the refs that RESOLVED, so the
    feature site can build its graph edges from them.
    """
    resolved: list[str] = []
    for ref in refs:
        census['refs'] += 1
        got = exists(cfg, ref)
        if got is None:
            census['unverifiable'] += 1
        elif not got:
            if 'V4' in on:
                bad(f'{cfg.rel(path)}: {key} {ref!r} resolves to '
                    f'nothing (its milestone IS in the tree)')
        else:
            resolved.append(ref)
    return resolved


def _check_refs(cfg: model.PmConfig, path, key: str, on: set[str], bad,
                census: dict) -> list[str]:
    """`_check_ref_ids` over an inline-list ref key."""
    return _check_ref_ids(cfg, path, key, _safe_refs(path, key, bad, cfg.rel(path)),
                          on, bad, census)


def _check_caused_by(cfg: model.PmConfig, path, on: set[str], bad,
                     census: dict) -> None:
    """`_check_ref_ids` over a bug's scalar `caused_by:`, resolved as a feature."""
    _check_ref_ids(cfg, path, CAUSED_BY,
                   _safe_scalar_ref(path, CAUSED_BY, bad, cfg.rel(path)),
                   on, bad, census, exists=_feature_exists)


def run(cfg: model.PmConfig, enabled: set[str] | None = None) -> tuple[list[str], dict]:
    """Returns (findings, census). A finding names a path a human can open."""
    # `model.VALIDATE_CHECKS` is the ONE home of the rule-id roster. A local
    # `VALIDATE_RULES` copy used to shadow it — a second name for the same
    # fact, where a V7 added to one would silently split `pm validate` from
    # `check pm`.
    on = enabled if enabled is not None else set(model.VALIDATE_CHECKS)
    findings: list[str] = []
    census = {'grains': 0, 'refs': 0, 'unverifiable': 0}

    def bad(msg: str) -> None:
        findings.append(msg)

    # (grain path, its declared id, the id its PATH implies, parentage pairs)
    graph: dict[str, list[str]] = {}

    for mdir in model.milestone_dirs(cfg):
        mfile = mdir / model.MILESTONE_DOC
        mid = model.field_of(mfile, 'id')
        census['grains'] += 1
        if 'V1' in on and (not mid or not model.field_of(mfile, 'status')):
            bad(f'{cfg.rel(mfile)}: missing id: or status: in the frontmatter')
        # The dir carries a human suffix after the version; the id is the prefix.
        if 'V2' in on and mid and not mdir.name.startswith(f'{mid}-'):
            bad(f'{cfg.rel(mfile)}: id {mid!r} does not match its directory '
                f'{mdir.name!r} (expected {mid}-<slug>/)')

        for ffile in model.feature_files(mdir):
            census['grains'] += 1
            fid = model.field_of(ffile, 'id')
            fstat = model.field_of(ffile, 'status')
            if 'V1' in on and (not fid or not fstat):
                bad(f'{cfg.rel(ffile)}: missing id: or status: in the frontmatter')
            expect = f'{mid}/{ffile.parent.name}'
            if 'V2' in on and fid and fid != expect:
                bad(f'{cfg.rel(ffile)}: id {fid!r} does not match its path '
                    f'(expected {expect!r})')
            if 'V3' in on:
                own = model.field_of(ffile, 'milestone')
                if own and own != mid:
                    bad(f'{cfg.rel(ffile)}: milestone: {own!r} but it lives under '
                        f'milestone {mid!r}')
            if fid:
                graph[fid] = []

            for sfile in model.story_files(ffile):
                census['grains'] += 1
                sid = model.field_of(sfile, 'id')
                if 'V1' in on and (not sid or not model.field_of(sfile, 'status')):
                    bad(f'{cfg.rel(sfile)}: missing id: or status: in the frontmatter')
                # `story_ordinal_prefix` TEACHES V2 about the prefix; it must
                # never switch the check off. Skipping instead of stripping
                # left every story in such a tree unchecked while the gate
                # printed VALID — under the configuration the docs mandate.
                s_expect = f'{expect}/{model.story_slug_of(cfg, sfile.stem)}'
                if 'V2' in on and sid and sid != s_expect:
                    bad(f'{cfg.rel(sfile)}: id {sid!r} does not match its path '
                        f'(expected {s_expect!r})')
                if 'V3' in on:
                    parent = model.field_of(sfile, 'feature')
                    if parent and parent != expect:
                        bad(f'{cfg.rel(sfile)}: feature: {parent!r} but it lives '
                            f'under feature {expect!r}')
                    own = model.field_of(sfile, 'milestone')
                    if own and own != mid:
                        bad(f'{cfg.rel(sfile)}: milestone: {own!r} but it lives '
                            f'under milestone {mid!r}')
                _check_refs(cfg, sfile, 'depends_on', on, bad, census)

            for key in _REF_KEYS:
                resolved = _check_refs(cfg, ffile, key, on, bad, census)
                if key == 'depends_on' and fid:
                    graph[fid].extend(ref for ref in resolved
                                      if ref.count('/') == 1)

        _check_refs(cfg, mfile, 'depends_on', on, bad, census)

        # Bugs are walked for their ONE ref and nothing else: `census['grains']`
        # still counts milestones, features and stories, so V1/V2/V3 keep the
        # grain set they have always been stated over and this walk adds refs
        # alone. `check pm` stays the one home of the bug census itself.
        for bfile in model.bug_files(mdir):
            _check_caused_by(cfg, bfile, on, bad, census)

    if 'V5' in on:
        findings.extend(_graph_findings(graph))
    if 'V6' in on:
        # A generated list is only safe BECAUSE this fails when it drifts.
        # Without V6 it is exactly the hand-maintained second scoreboard the
        # doctrine forbids — it just happens to have been written by a tool once.
        from godot_devkit.repo.pm import execlist
        try:
            stale = execlist.sync(cfg, write=False, existing_only=True)
        except execlist.Refusal as err:
            # A grain the renderer refuses (non-UTF-8, broken markers) is a
            # FINDING here, one per line — never a crash that aborts the run
            # and takes every V1-V5 finding above down with it.
            findings.extend(str(err).split('\n'))
        else:
            for path, changed in stale:
                if changed:
                    findings.append(
                        f'{cfg.rel(path)}: the execution list is stale — the tree '
                        f'has moved since it was rendered; run `pm sync`')
    return findings, census


def _graph_findings(graph: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    # Cycles — a dependency loop means no build order exists at all.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {k: WHITE for k in graph}

    def walk(node: str, so_far: list[str]) -> None:
        colour[node] = GREY
        for dep in graph.get(node, []):
            if dep not in colour:
                continue
            if colour[dep] == GREY:
                loop = so_far[so_far.index(dep):] if dep in so_far else [dep]
                out.append(f'dependency CYCLE among features: '
                           f'{" -> ".join([*loop, node, dep])}')
            elif colour[dep] == WHITE:
                walk(dep, [*so_far, node])
        colour[node] = BLACK

    for node in sorted(graph):
        if colour[node] == WHITE:
            walk(node, [])

    return out
