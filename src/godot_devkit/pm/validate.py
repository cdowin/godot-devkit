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
    V5  the feature dependency graph is acyclic and phase-monotone (no feature
        depends on one in a LATER phase)

**Pruned milestones are not errors.** Git history is the archive, so a ref like
`0.19.4` naming a milestone no longer in the working tree is expected. V4
resolves only refs whose MILESTONE is present and censuses the rest as
UNVERIFIABLE — the same discipline `check props` uses. Failing them would
punish the prune model; ignoring them silently would hide a typo, so they are
counted and reported in the summary.
"""
from __future__ import annotations

from pathlib import Path

from godot_devkit.pm import model

VALIDATE_RULES = ('V1', 'V2', 'V3', 'V4', 'V5')

_REF_KEYS = ('depends_on', 'consumed_by')


def _refs(path: Path, key: str) -> list[str]:
    """The ids inside a `key: ["a", "b"]` frontmatter list."""
    raw = model.field_of(path, key)
    if not raw.startswith('[') or not raw.endswith(']'):
        return []
    out = []
    for part in raw[1:-1].split(','):
        part = part.strip().strip('"').strip("'").strip()
        if part:
            out.append(part)
    return out


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
    on = enabled if enabled is not None else set(VALIDATE_RULES)
    findings: list[str] = []
    census = {'grains': 0, 'refs': 0, 'unverifiable': 0}

    def bad(msg: str) -> None:
        findings.append(msg)

    # (grain path, its declared id, the id its PATH implies, parentage pairs)
    graph: dict[str, tuple[str, list[str]]] = {}

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
            fphase = model.field_of(ffile, 'phase')
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
                graph[fid] = (fphase, [])

            for sfile in model.story_files(ffile):
                census['grains'] += 1
                sid = model.field_of(sfile, 'id')
                if 'V1' in on and (not sid or not model.field_of(sfile, 'status')):
                    bad(f'{cfg.rel(sfile)}: missing id: or status: in the frontmatter')
                s_expect = f'{expect}/{sfile.stem}'
                if 'V2' in on and sid and sid != s_expect and not cfg.story_ordinal_prefix:
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
                if 'V4' in on:
                    for ref in _refs(sfile, 'depends_on'):
                        census['refs'] += 1
                        got = _grain_exists(cfg, ref)
                        if got is None:
                            census['unverifiable'] += 1
                        elif not got:
                            bad(f'{cfg.rel(sfile)}: depends_on {ref!r} resolves to '
                                f'nothing (its milestone IS in the tree)')

            for key in _REF_KEYS:
                for ref in _refs(ffile, key):
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
                        graph[fid][1].append(ref)

        for ref in _refs(mfile, 'depends_on'):
            census['refs'] += 1
            got = _grain_exists(cfg, ref)
            if got is None:
                census['unverifiable'] += 1
            elif not got and 'V4' in on:
                bad(f'{cfg.rel(mfile)}: depends_on {ref!r} resolves to nothing '
                    f'(its milestone IS in the tree)')

    if 'V5' in on:
        findings.extend(_graph_findings(graph))
    return findings, census


def _graph_findings(graph: dict[str, tuple[str, list[str]]]) -> list[str]:
    out: list[str] = []
    # Cycles — a dependency loop means no build order exists at all.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {k: WHITE for k in graph}

    def walk(node: str, trail: list[str]) -> None:
        colour[node] = GREY
        for dep in graph.get(node, ('', []))[1]:
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

    # Phase-monotone — a feature may not depend on one scheduled LATER.
    for fid, (phase, deps) in sorted(graph.items()):
        if not phase.isdigit():
            continue
        for dep in deps:
            dep_phase = graph.get(dep, ('', []))[0]
            if dep_phase.isdigit() and int(dep_phase) > int(phase):
                out.append(f'{fid} is phase {phase} but depends on {dep} in the '
                           f'LATER phase {dep_phase} — the buckets contradict '
                           f'the graph')
    return out
