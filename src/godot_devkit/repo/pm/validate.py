"""validate.py — structural + referential integrity of the PM tree.

A DIFFERENT question from `check pm`'s drift rules. Drift asks "are these
statuses consistent with each other?"; validation asks "is this tree
well-formed, and are its references real?" A milestone can be perfectly
undrifted and still depend on a feature that does not exist.

    V1  frontmatter is well-formed (a leading fence, with `id:` and `status:`)
    V2  the id matches the path (the id==path convention the resolvers rely on)
    V3  parentage is consistent — a story's `feature:`/`milestone:` and a
        feature's `milestone:` name the grains that actually own them
    V4  `depends_on` / `consumed_by` refs resolve
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
"""
from __future__ import annotations

import re
from pathlib import Path

from godot_devkit.repo.pm import model

# A story FILE may carry an ordering prefix (`01-slug.md`) that its ID does not:
# the number sequences the build, it is not identity.
_ORDINAL = re.compile(r'^\d\d-')

_REF_KEYS = ('depends_on', 'consumed_by')


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
        mfile = mdir / 'milestone.md'
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
                stem = sfile.stem
                if cfg.story_ordinal_prefix:
                    stem = _ORDINAL.sub('', stem)
                s_expect = f'{expect}/{stem}'
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
                for ref in _safe_refs(sfile, 'depends_on', bad, cfg.rel(sfile)):
                    census['refs'] += 1
                    got = _grain_exists(cfg, ref)
                    if got is None:
                        census['unverifiable'] += 1
                    elif not got and 'V4' in on:
                        bad(f'{cfg.rel(sfile)}: depends_on {ref!r} resolves to '
                            f'nothing (its milestone IS in the tree)')

            for key in _REF_KEYS:
                for ref in _safe_refs(ffile, key, bad, cfg.rel(ffile)):
                    census['refs'] += 1
                    got = _grain_exists(cfg, ref)
                    if got is None:
                        census['unverifiable'] += 1
                        continue
                    if not got:
                        if 'V4' in on:
                            bad(f'{cfg.rel(ffile)}: {key} {ref!r} resolves to '
                                f'nothing (its milestone IS in the tree)')
                    elif key == 'depends_on' and fid and ref.count('/') == 1:
                        graph[fid].append(ref)

        for ref in _safe_refs(mfile, 'depends_on', bad, cfg.rel(mfile)):
            census['refs'] += 1
            got = _grain_exists(cfg, ref)
            if got is None:
                census['unverifiable'] += 1
            elif not got and 'V4' in on:
                bad(f'{cfg.rel(mfile)}: depends_on {ref!r} resolves to nothing '
                    f'(its milestone IS in the tree)')

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

    def walk(node: str, trail: list[str]) -> None:
        colour[node] = GREY
        for dep in graph.get(node, []):
            if dep not in colour:
                continue
            if colour[dep] == GREY:
                loop = trail[trail.index(dep):] if dep in trail else [dep]
                out.append(f'dependency CYCLE among features: '
                           f'{" -> ".join([*loop, node, dep])}')
            elif colour[dep] == WHITE:
                walk(dep, [*trail, node])
        colour[node] = BLACK

    for node in sorted(graph):
        if colour[node] == WHITE:
            walk(node, [])

    return out
