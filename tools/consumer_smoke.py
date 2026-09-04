#!/usr/bin/env python3
"""consumer_smoke.py — every verb against the live consumer checkouts.

THE CONSUMERS ARE THE FIXTURES. Two shipping game repos pin this package, and a
regression here reaches their commit gates before anyone notices it here. That
made a smoke run mandatory before a release — as a PROCEDURE, written in a skill,
performed by hand, differently each time. `make smoke` is the same thing as a
target, which is the only form of it that gets run.

WHAT IT ASSERTS, and why each is more than "it did not crash":

  * a gate that PASSES with the wrong census is a false PASS, so every printed
    count is compared against an INDEPENDENT one computed here from `git
    ls-files` and `project.godot`. Agreement is the check; the exit code alone
    is not.
  * the checkout is byte-clean before and after. Write verbs never run here —
    the consumers are shipping repos with their own dirty-tree gates — and a
    smoke run that leaves one dirty is a broken smoke run, not a thorough one.
  * THE GATES RUN AGAINST THE RUNNERS THE RELEASE WOULD SHIP, in a `git
    worktree` of the consumer. Run in place they graded the working tree's
    checks against the runners the consumer's PIN installed — a combination a
    consumer occupies for the minutes between a pin bump and `install-runners
    --force`, and never the one a release ships. v0.23.0 found it: `check
    test-shape` asks its roster through `make integration-list`, nullbound had
    opted into the header rule, its `Makefile.devkit` predated the target, and
    the smoke was red on a consumer state the release's own adoption note says
    to leave. So `check all` and the two censuses run inside a throwaway
    worktree with `install-runners --force` applied to it; the read-only verbs
    stay on the main checkout, because they are what the consumer's pin runs
    today.
  * a consumer that is not checked out is SKIPPED LOUDLY and named in the
    summary. Silence about what was not run is the thing this file's own
    contract forbids.
  * FIVE CHECKS THAT USED TO BE UNIT TESTS live here now. `test_defaults`,
    `test_check_props`, `test_canonicalize`, `test_tscn_roundtrip` and
    `test_uid_codec` each carried a case that walked ~/workspace behind a
    `skipUnless`, so a tree that is not this repo's was read by four
    interpreters per matrix run and by nothing at all on CI. They assert the
    same things here, once, named per consumer. The two WRITE verbs among them
    run over a `tempfile` COPY, never the checkout — same rule as everything
    else in this file.
  * THE FRESH PROJECT is smoked too, and it is the one probe here that writes:
    an empty Godot 4 project in a temp dir, `godot-devkit init`, then the REAL
    `make doctor`. The suite proves the written file set and dry-runs every
    target; only a real host can run the engine-facing half, so this is where
    it happens. Never inside a consumer checkout — write verbs do not run
    against a shipping game repo.

Read-only, no network, no Godot boot. Runs the WORKING TREE build via
PYTHONPATH — never `uvx --from .`, which caches by version and will happily
serve pre-fix code from a fix's own verification run.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEVKIT = Path(__file__).resolve().parent.parent
# The WORKING TREE build, for the one thing this file needs to KNOW rather than
# observe: which files `install-hooks` puts under tools/hooks/. Everything else
# here runs the CLI out of process on purpose (a probe that imports what it is
# probing can agree with a bug); a roster is not behaviour, and a literal copy
# of one is the drift this import removes.
sys.path.insert(0, str(DEVKIT / 'src'))
from godot_devkit.repo import install  # noqa: E402
# The two moved checks that no CLI verb can ask. Round-trip fidelity is
# `parse -> serialise == the bytes on disk`, and the uid differential grades
# the codec against a positional restatement written below — both anchored
# OUTSIDE the module under test, which is what the out-of-process rule above
# is protecting. Everything with a verb still goes through `devkit()`.
from godot_devkit.godot.format.tscn_document import TscnDocument  # noqa: E402
from godot_devkit.godot.index.uid_codec import (INVALID_ID,  # noqa: E402
                                                UID_PREFIX, canonical,
                                                text_to_id)

CONSUMERS = (Path.home() / 'workspace' / 'trail',
             Path.home() / 'workspace' / 'nullbound')
SCENE_SUFFIXES = ('.tres', '.tscn')
DEFAULT_EXCLUDES = ('addons/',)

# --- the release's runners, in a worktree of the consumer ---------------------
RUNNERS = 'install-runners'
FORCE = '--force'
WORKTREE_PREFIX = 'gdk-release-runners-'
WORKTREE_DIR = 'wt'
# What the install says it wrote, per file. READ rather than assumed: the row
# compares it against a census computed here from the installable bodies, and a
# count taken from the thing being graded agrees with any bug it has.
WROTE_RE = re.compile(r'^\[install\] wrote (.+)$', re.MULTILINE)
EXECUTABLE_BITS = 0o111

# --- the fresh-project probe --------------------------------------------------
FRESH = 'fresh project'
GODOT = 'godot'
HOOKS_PATH = 'tools/hooks'
# DERIVED, never a literal. doctor.sh counts what is IN the directory — asked
# of the tree, not of a roster, so a hook added after it was written is still
# covered — and this probe compares that count against what the install verb
# ships. A hardcoded 6 here made the two couriers (0.22.0) read as a census
# failure in `make smoke` on the day they landed: the roster this file could
# not see had moved and the number it carried could not. `_*` and `*.local`
# are doctor's own exclusions, mirrored so the two censuses count one thing.
TRACKED_HOOKS = sum(
    1 for _, rel in install.PLANS['install-hooks']
    if rel.startswith(f'{HOOKS_PATH}/')
    and not Path(rel).name.startswith('_')
    and not rel.endswith('.local'))
FRESH_PROJECT_GODOT = ('config_version=5\n\n[application]\n\n'
                       'config/name="Fresh"\nconfig/version="0.1.0"\n')
FRESH_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>\n'
# The doctor rows `init` is RESPONSIBLE for. Everything else doctor reports is
# a fact about the HOST (godot, gdlint, uv on PATH) or about a project that has
# not added GUT yet — real, worth printing, and not this probe's finding.
INIT_OWNED = ('core.hooksPath', 'tracked hook')
# `make check`'s verdict shape, and the one FAIL that is not this probe's
# finding. A blank Godot project holds no .tscn/.tres, so the three gates that
# read them report a 0-file census and correctly redden — the stock roster
# being wrong for a repo with no scenes yet, which the seed devkit.toml names
# and narrows in one line. ANY OTHER FAIL is a finding about a file `init`
# itself wrote, which is exactly how a `compile_sweep.gd` with no `.uid`
# sidecar shipped: the suite dry-ran `precommit`, and a dry run reaches no
# verdict to read.
CHECK_VERDICT_RE = re.compile(r'^\[check:([a-z-]+)\] (PASS|FAIL) — (.*)$',
                              re.MULTILINE)
CHECK_EMPTY_CENSUS = 'scanned 0 of 0 tracked'
CHECK_LOG = '.gate-reports/check.log'


def devkit(root: Path, *argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, '-m', 'godot_devkit.cli', *argv],
        cwd=root, capture_output=True, text=True,
        env={**_env(), 'PYTHONPATH': str(DEVKIT / 'src')})
    return proc.returncode, proc.stdout + proc.stderr


def _env() -> dict:
    import os
    return dict(os.environ)


def working_tree_devkit() -> str:
    """`make check` resolves `DEVKIT` to `uvx --from git+…@<pin>` — the
    RELEASED tag, over the network. This whole file runs the WORKING TREE, so
    the override goes on the command line; it is not a hand edit to the
    project, and without it the probe would grade the last release."""
    return (f'DEVKIT=env PYTHONPATH={DEVKIT / "src"} '
            f'{sys.executable} -m godot_devkit.cli')


def git_run(root: Path, *argv: str) -> subprocess.CompletedProcess:
    """One git invocation. `git()` reads its lines; the worktree verbs need the
    EXIT CODE and the stderr, because a removal that failed quietly leaves a
    worktree behind in somebody's live repo. One spawner, two readings."""
    return subprocess.run(['git', *argv], cwd=root,
                          capture_output=True, text=True)


def git(root: Path, *argv: str) -> list[str]:
    return [ln for ln in git_run(root, *argv).stdout.splitlines() if ln.strip()]


class Report:
    """Rows and a verdict. Every row says what was compared against what."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.failed = 0
        self.skipped: list[str] = []

    def ok(self, consumer: str, what: str, detail: str) -> None:
        self.rows.append((consumer, f'ok    {what}', detail))

    def bad(self, consumer: str, what: str, detail: str) -> None:
        self.rows.append((consumer, f'FAIL  {what}', detail))
        self.failed += 1

    def check(self, consumer: str, what: str, cond: bool, detail: str) -> bool:
        (self.ok if cond else self.bad)(consumer, what, detail)
        return cond


def _scene_population(root: Path) -> int:
    """An INDEPENDENT count of the files the .tscn/.tres gates scan.

    Computed here from git rather than asked of the tool: a census compared
    against the tool's own idea of its scope would agree with any scoping bug
    the tool has.
    """
    excludes = _excludes(root)
    files = git(root, 'ls-files', '*.tres', '*.tscn')
    return sum(1 for f in files
               if f.endswith(SCENE_SUFFIXES)
               and not any(f.startswith(p) for p in excludes))


def _excludes(root: Path) -> tuple[str, ...]:
    cfg = root / 'devkit.toml'
    if not cfg.is_file():
        return DEFAULT_EXCLUDES
    import tomllib
    with cfg.open('rb') as fh:
        data = tomllib.load(fh)
    found = data.get('tres', {}).get('exclude_prefixes')
    return tuple(found) if isinstance(found, list) else DEFAULT_EXCLUDES


def _autoload_count(root: Path) -> int:
    body = (root / 'project.godot').read_text(encoding='utf-8', errors='replace')
    section = body.partition('[autoload]')[2].partition('\n[')[0]
    return sum(1 for line in section.splitlines() if '=' in line)


def _first(root: Path, pattern: str) -> str | None:
    """The first tracked match OUTSIDE addons/.

    Vendored plugin scenes are the same handful of files in every consumer, so
    smoking those tells you the tool still parses `addons/gut/GutScene.tscn` and
    nothing about the repo that pins this package.
    """
    found = [f for f in git(root, 'ls-files', pattern)
             if not f.startswith(DEFAULT_EXCLUDES)]
    return found[0] if found else None


def _a_class_name(root: Path) -> str | None:
    tracked = [f for f in git(root, 'ls-files', '*.gd')
               if not f.startswith(DEFAULT_EXCLUDES)]
    for rel in tracked[:400]:
        try:
            body = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        match = re.search(r'^class_name\s+(\w+)', body, re.MULTILINE)
        if match:
            return match.group(1)
    return None


# --- the five checks that used to be `skipUnless(available_consumers())` ------
# Each number below arrived with the test it came from; none of them was
# loosened on the way. A floor is here so a broken harvest reads as broken
# rather than as a small repo, and the ceiling is a calibration, not a target.
PROPS_DEAD_CEILING = 30      # test_check_props.NoFalsePositivesOnRealRepos
ROUND_TRIP_FLOOR = 100       # test_tscn_roundtrip: `corpus too small to prove anything`
UID_CENSUS_FLOOR = 200       # test_uid_codec.CORPUS_UID_FLOOR
UID_HARVEST_SUFFIXES = ('.tscn', '.tres', '.uid', '.import')
UID_TEXT = re.compile(r'uid://[0-9a-z]+')
# What `ResourceSaver.save()` drops, restated from test_canonicalize.degrade:
# no header uid, path-only refs, no `index=` on instance-child overrides.
UID_ATTR = re.compile(r' uid="uid://[0-9a-z]+"')
INDEX_ATTR = re.compile(r' index="(\d+)"')
# The engine's uid constants, restated independently of the codec being graded.
UID_BASE = 34
UID_CHAR_COUNT = 25
UID_ID_BITS = 63


def degrade(text: str) -> str:
    """A scene as `PackedScene.pack()` + `ResourceSaver.save()` would leave it."""
    lines = []
    for line in text.split('\n'):
        if line.startswith(('[ext_resource ', '[gd_scene ', '[gd_resource ')):
            line = UID_ATTR.sub('', line)
        elif line.startswith('[node '):
            line = INDEX_ATTR.sub('', line)
        lines.append(line)
    return '\n'.join(lines)


def _independently_canonical(text: str) -> bool:
    """Positional restatement: alphabet a-y / 0-8, no leading 'a', fits 63 bits.

    Shares NO code with the codec's round trip — that is the whole point, and
    it is why this is spelled out here rather than imported. A predicate graded
    against itself agrees with any bug it has.
    """
    body = text[len(UID_PREFIX):]
    if not body or body[0] == 'a' or any(c in 'z9' for c in body):
        return False
    value = 0
    for char in body:
        value = value * UID_BASE + (ord(char) - ord('a') if char.isalpha()
                                    else ord(char) - ord('0') + UID_CHAR_COUNT)
    return value < (1 << UID_ID_BITS)


def _tracked(root: Path, *patterns: str) -> list[str]:
    """Tracked paths outside addons/ that are on disk."""
    return [f for f in git(root, 'ls-files', *patterns)
            if not f.startswith(DEFAULT_EXCLUDES) and (root / f).is_file()]


def props_findings(root: Path, report: Report) -> None:
    """The consumers are the calibration set: every finding here must be real
    drift, so the count is pinned. If this row changes, look at the diff before
    changing the number."""
    name = root.name
    code, out = devkit(root, 'check', 'props')
    dead = [ln for ln in out.splitlines() if ln.startswith('  DEAD')]
    faults = []
    if 'all accounted for' not in out:
        faults.append('no `all accounted for` line in the output')
    if 'BUG' in out:
        faults.append('the gate reported a BUG')
    if len(dead) > PROPS_DEAD_CEILING:
        faults.append(f'{len(dead)} DEAD finding(s), ceiling {PROPS_DEAD_CEILING}')
    if code != (1 if dead else 0):
        faults.append(f'exit {code} with {len(dead)} DEAD finding(s)')
    report.check(name, 'check props findings', not faults,
                 f'{len(dead)} DEAD, ceiling {PROPS_DEAD_CEILING}, exit {code}'
                 if not faults
                 else '; '.join(faults) + f'\n{chr(10).join(dead[:10])}')


def scene_round_trip(root: Path, report: Report) -> None:
    """parse -> serialise with NO mutation, byte-identical, over the whole tree.

    If it is not, the toolkit is more dangerous than `sed`, because it silently
    touches lines nobody asked it to touch.
    """
    name = root.name
    checked = 0
    changed: list[str] = []
    for path in (*root.rglob('*.tscn'), *root.rglob('*.tres')):
        if '/.git/' in str(path):
            continue
        try:
            original = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        checked += 1
        if TscnDocument(original, path).text != original:
            changed.append(str(path))
    if changed:
        detail = (f'round trip CHANGED {len(changed)} of {checked} file(s): '
                  + ', '.join(changed[:5]))
    elif checked <= ROUND_TRIP_FLOOR:
        detail = (f'{checked} file(s) read — at or below the floor of '
                  f'{ROUND_TRIP_FLOOR}; too small to prove anything')
    else:
        detail = (f'{checked} .tscn/.tres parsed and re-serialised '
                  f'byte-identical (floor {ROUND_TRIP_FLOOR})')
    report.check(name, 'scene round trip',
                 not changed and checked > ROUND_TRIP_FLOOR, detail)


def uid_differential(root: Path, report: Report) -> None:
    """Every uid this checkout ships, both verdict formulations, zero
    disagreements allowed — and every repair target itself stable, or `--fix`
    churns."""
    name = root.name
    uids: set[str] = set()
    for path in root.rglob('*'):
        if (not path.is_file() or path.suffix not in UID_HARVEST_SUFFIXES
                or '.git' in path.parts or '.godot' in path.parts):
            continue
        try:
            uids.update(UID_TEXT.findall(
                path.read_text(encoding='utf-8', errors='replace')))
        except OSError:
            continue
    undecodable, disagreed, unstable = [], [], []
    noncanonical = 0
    for text in sorted(uids):
        if text_to_id(text) == INVALID_ID:
            undecodable.append(text)
            continue
        round_tripped = canonical(text)
        if (round_tripped == text) != _independently_canonical(text):
            disagreed.append(text)
        if round_tripped != text:
            noncanonical += 1
            if canonical(round_tripped) != round_tripped:
                unstable.append(text)
    faults = [*(f'undecodable: {t}' for t in undecodable[:3]),
              *(f'the two formulations disagree on {t}' for t in disagreed[:3]),
              *(f'repair target for {t} is not itself stable' for t in unstable[:3])]
    if faults:
        detail = '; '.join(faults)
    elif len(uids) < UID_CENSUS_FLOOR:
        detail = (f'harvest broke — {len(uids)} uid(s), below the floor of '
                  f'{UID_CENSUS_FLOOR}')
    else:
        detail = (f'{len(uids)} uid(s) (floor {UID_CENSUS_FLOOR}), '
                  f'{noncanonical} non-canonical, both formulations agreed '
                  f'on every one')
    report.check(name, 'uid codec differential',
                 not faults and len(uids) >= UID_CENSUS_FLOOR, detail)


def canonicalize_restores_a_real_scene(root: Path, report: Report) -> None:
    """Degrade a REAL scene exactly the way `save()` does, then check that
    canonicalize puts it back byte-for-byte. Anything the tool invents rather
    than derives shows up as a diff.

    The scene is the one the degradation costs the MOST lines — a rule rather
    than a name, decided before any restoration is attempted, so the pick
    cannot be a pick that passes. (On nullbound it selects
    scenes/world/maps/quarantine.tscn, which is the file the unit test named.)
    The header uid is the one loss unrecoverable for a file outside its own
    repo path, so it must still be ABSENT: inventing one would be worse than
    the missing ref.
    """
    name = root.name
    best, losses = None, 0
    for rel in _tracked(root, '*.tscn'):
        original = (root / rel).read_text(encoding='utf-8', errors='replace')
        damaged = degrade(original)
        cost = sum(1 for a, b in zip(original.split('\n'), damaged.split('\n'))
                   if a != b)
        if cost > losses:
            best, losses = (rel, original, damaged), cost
    if best is None:
        report.skipped.append(
            f'{name}: canonicalize round trip (no tracked .tscn that '
            f'`save()` would degrade)')
        return
    rel, original, damaged = best
    with tempfile.TemporaryDirectory() as tmp:
        packed = Path(tmp) / 'packed.tscn'
        packed.write_text(damaged, encoding='utf-8')
        devkit(root, 'scene', 'canonicalize', str(packed))
        restored = packed.read_text(encoding='utf-8')
    head, *body = restored.split('\n')
    faults = []
    if UID_ATTR.sub('', head) != head:
        faults.append(f'a header uid was invented for a file outside the repo: {head}')
    if body != original.split('\n')[1:]:
        differing = [i + 2 for i, (a, b) in
                     enumerate(zip(body, original.split('\n')[1:])) if a != b]
        faults.append(f'restored != original at line(s) '
                      f'{differing[:5] or "[length]"}')
    report.check(name, 'canonicalize round trip', not faults,
                 f'{rel}: {losses} degraded line(s) restored byte-for-byte'
                 if not faults else f'{rel}: ' + '; '.join(faults))


# How many scenes one `canonicalize` invocation is handed. The verb takes
# `nargs='+'`, so the whole corpus would fit in about 50KB of argv — under any
# ARG_MAX this runs on — but a consumer's tree only grows, and a row that
# starts failing with "argument list too long" would read as a canonicalize
# regression. Chunking costs three spawns instead of one.
CANON_CHUNK = 100


def _index_attrs(text: str) -> dict[str, str | None]:
    """`[node ...]` header (index= removed) -> its index, or None if it had none.

    The header minus its index is the node's identity: `name=` + `parent=` are
    unique within a scene, so this pairs each node before with itself after
    without depending on line numbers, which a restored uid can shift.
    """
    found: dict[str, str | None] = {}
    for line in text.split('\n'):
        if line.startswith('[node '):
            match = INDEX_ATTR.search(line)
            found[INDEX_ATTR.sub('', line)] = match.group(1) if match else None
    return found


def canonicalize_invents_no_index(root: Path, report: Report) -> None:
    """The INVENT direction, over EVERY tracked scene rather than the one the
    round-trip row picks: degrade the way `save()` does, canonicalize, and count
    the `index=` attributes that came back on a node which never had one.

    This is the direction that cannot be widened away. The round-trip row is
    pinned to one scene per consumer because a created node's authored `index=`
    is not derivable and trail's inherited scenes disagree with each other about
    whether the attribute is even written (0.24.0: 10 created nodes directly
    under an inherited root carry one, 10 more at the same position carry none).
    But "restores nothing it cannot derive" is true of every scene in both trees
    TODAY, so it is asserted over all of them today — and a plausible-looking
    widening of the restoration is what it exists to catch. Measured against the
    rules proposed for that widening: keying restoration off "the parent is an
    instanced subtree" invents 38 attributes on trail and 87 on nullbound, and
    the narrowest form of it still invents 4.

    Read-only: every degraded scene is written to a temp dir, never the
    checkout, and the verb runs with the consumer as cwd so `res://` still
    resolves against the real base scenes.
    """
    name = root.name
    files = _tracked(root, '*.tscn')
    if not files:
        report.skipped.append(f'{name}: canonicalize invents no index (no tracked .tscn)')
        return
    authored = restored = invented = lost = 0
    differing: list[str] = []
    culprits: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        probes = {}
        for rel in files:
            probe = Path(tmp) / rel.replace('/', '__')
            probe.write_text(degrade((root / rel).read_text(
                encoding='utf-8', errors='replace')), encoding='utf-8')
            probes[rel] = probe
        ordered = list(probes)
        for start in range(0, len(ordered), CANON_CHUNK):
            chunk = ordered[start:start + CANON_CHUNK]
            devkit(root, 'scene', 'canonicalize',
                   *(str(probes[rel]) for rel in chunk))
        for rel in ordered:
            before = _index_attrs((root / rel).read_text(
                encoding='utf-8', errors='replace'))
            after = _index_attrs(probes[rel].read_text(encoding='utf-8'))
            for header, was in before.items():
                now = after.get(header)
                if was is not None:
                    authored += 1
                    restored += now == was
                    lost += now is None
                elif now is not None:
                    invented += 1
                    if len(culprits) < 5:
                        culprits.append(f'{rel} {header[:60]} -> index="{now}"')
            if before != after:
                differing.append(rel)
    # The round-trip count is REPORTED, never gated: pinning it would be the
    # known-fail list this package refused to write. It is here so it cannot go
    # stale — the last census of it was wrong within a day of being taken.
    report.check(
        name, 'canonicalize invents no index', invented == 0,
        f'{len(files)} scene(s): {invented} invented, {restored}/{authored} '
        f'authored index= restored, {lost} not derivable '
        f'({len(differing)} scene(s) not index-identical)'
        if invented == 0 else
        f'{invented} invented over {len(files)} scene(s): ' + '; '.join(culprits))


def defaults_elision(root: Path, report: Report) -> None:
    """Over a real repo `--elide-defaults` must stay a pure, stable deletion.

    A WRITE verb, so the corpus is copied into a throwaway git repo first and
    the checkout is never opened for writing. A consumer already canonical
    exercises nothing, which is reported rather than counted as proof.
    """
    name = root.name
    tracked = _tracked(root, '*.tres', '*.gd', '*.gd.uid')
    files = [rel for rel in tracked if rel.endswith('.tres')]
    if not files:
        report.skipped.append(f'{name}: defaults elision (no .tres tracked)')
        return
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / 'repo'
        copy.mkdir()
        # The consumer's OWN project.godot: the point of this row is a real
        # tree, and repo_root() needs the marker file to find one.
        shutil.copy2(root / 'project.godot', copy / 'project.godot')
        for rel in tracked:
            target = copy / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, target)
        subprocess.run(['git', 'init', '-q'], cwd=copy, check=True,
                       capture_output=True)
        subprocess.run(['git', 'add', '-A'], cwd=copy, check=True,
                       capture_output=True)
        read = {rel: (copy / rel).read_text(encoding='utf-8', errors='replace')
                for rel in files}
        code, out = devkit(copy, 'scene', 'canonicalize', '--elide-defaults', *files)
        once = {rel: (copy / rel).read_text(encoding='utf-8', errors='replace')
                for rel in files}
        devkit(copy, 'scene', 'canonicalize', '--elide-defaults', *files)
        twice = {rel: (copy / rel).read_text(encoding='utf-8', errors='replace')
                 for rel in files}
    faults = []
    if code != 0:
        faults.append(f'exit {code}\n{out[-1200:]}')
    if once != twice:
        moved = sorted(rel for rel in files if once[rel] != twice[rel])
        faults.append(f'not idempotent over {len(moved)} file(s): {moved[:5]}')
    changed = 0
    for rel in files:
        old, new = read[rel].split('\n'), once[rel].split('\n')
        if old != new:
            changed += 1
        # Deletion only: every surviving line is an original line, in order.
        if new != [line for line in old if line in new] or len(new) > len(old):
            faults.append(f'not a pure deletion: {rel}')
            break
    if not changed:
        report.skipped.append(
            f'{name}: defaults elision changed NOTHING — the corpus is already '
            f'canonical, so this row exercised the fixer on no file')
    report.check(name, 'defaults elision', not faults,
                 f'{len(files)} .tres copied, {changed} elided, deletion-only '
                 f'and idempotent' if not faults else '; '.join(faults))


def runners_ahead(root: Path) -> list[str]:
    """The `install-runners` entries the WORKING TREE would change in `root`.

    Computed from the installable bodies and the destination's mode — the two
    ways the installer has something to write, restated here from the disk
    rather than read off the install's own report, because the row below
    compares the two against each other.

    The caller passes the WORKTREE, not the consumer's checkout: the worktree
    is what the install writes into, and a consumer with an uncommitted runner
    edit would otherwise make the two counts disagree over a file the install
    never saw.
    """
    ahead = []
    for name, rel in install.PLANS[RUNNERS]:
        target = root / rel
        try:
            current = target.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            # Missing, or not text this can compare: either way the install
            # has that file to write.
            ahead.append(rel)
            continue
        armed = (not rel.endswith(install.EXECUTABLE_SUFFIX)
                 or target.stat().st_mode & EXECUTABLE_BITS)
        if current != install.body_of(name) or not armed:
            ahead.append(rel)
    return ahead


def _worktree_paths(rows: list[str]) -> set[str]:
    """The PATH column of `git worktree list`, resolved.

    A worktree LEFT BEHIND is a path. The other two columns are the commit and
    the branch, which move whenever anybody commits in the repo — and on a live
    consumer somebody does: a peer agent committed in nullbound during this
    row's own first real run, and a whole-line comparison called it a finding.
    """
    return {os.path.realpath(row.split()[0]) for row in rows if row.split()}


def worktree_verdict(before: list[str], after: list[str], ours: Path,
                     removed: subprocess.CompletedProcess) -> tuple[bool, str]:
    """(clean, detail) for the `worktree list unchanged` row.

    Three outcomes, and the middle one is why this is a function: OUR worktree
    still listed is the failure this row exists for — loud, naming the removal
    that did not work, never retried blind. Any OTHER path appearing or leaving
    is still a finding, because a smoke run has no business being unable to
    tell those apart. A list whose paths are unchanged but whose text moved is
    somebody else's commit, and it is REPORTED rather than dropped.
    """
    added = sorted(_worktree_paths(after) - _worktree_paths(before))
    gone = sorted(_worktree_paths(before) - _worktree_paths(after))
    if os.path.realpath(ours) in added:
        return False, (f'LEAKED a worktree into a live repo: {ours} — `git '
                       f'worktree remove --force` exit {removed.returncode}: '
                       f'{removed.stderr.strip()[-500:]}')
    if added or gone:
        return False, (f'the worktree list changed and none of it is this '
                       f'run\'s: appeared {added}, left {gone}')
    same = f'{len(before)} worktree(s), the same before and after'
    if after != before:
        return True, (f'{same} — the text moved because somebody committed '
                      f'under the run, which is not this run\'s: '
                      f'{sorted(set(after) ^ set(before))}')
    return True, same


def against_the_release_runners(root: Path, report: Report) -> None:
    """`check all` and the two censuses, in a throwaway `git worktree` of the
    consumer carrying the runners the working tree would INSTALL.

    THE MAIN CHECKOUT IS NEVER WRITTEN TO, which is the whole reason this is a
    worktree and not an install: `git worktree add` costs a checkout and no
    copy, every write lands inside it, and the removal is in a `finally`
    reported as its own row — a worktree leaked into somebody's live repo is
    worse than a red smoke.

    The worktree carries HEAD, so uncommitted work in the consumer is not
    graded here. The read-only verbs above still see it.

    A FAILING INSTALL IS A RED ROW, never a fallback to the in-place run. The
    fallback would be the exact blind spot this exists to close, and it would
    look green.

    `--force` is what makes this usable on a real consumer: every runner ships
    an editable `project config` header, and a run that refused on one would
    redden the smoke on every consumer that edited theirs — 0.24.0/m1's shape,
    from the other side. The consequence is said out loud rather than hidden:
    a consumer whose header edits are load-bearing sees the STOCK runners
    here, and a gate that then fails is a finding about the release's
    defaults, not a false red.
    """
    name = root.name
    before = git(root, 'worktree', 'list')
    holder = tempfile.mkdtemp(prefix=WORKTREE_PREFIX)
    worktree = Path(holder) / WORKTREE_DIR
    try:
        added = git_run(root, 'worktree', 'add', '--detach',
                        str(worktree), 'HEAD')
        if added.returncode != 0:
            report.bad(name, 'release worktree',
                       f'`git worktree add` exit {added.returncode}: '
                       f'{added.stderr.strip()[-800:]}')
            report.skipped.append(
                f'{name}: check all + the two censuses — no worktree, and this '
                f'run does NOT fall back to the consumer\'s own runners')
            return

        ahead = runners_ahead(worktree)
        code, out = devkit(worktree, RUNNERS, FORCE)
        wrote = WROTE_RE.findall(out)
        if code != 0:
            report.bad(name, 'runners ahead',
                       f'`{RUNNERS} {FORCE}` exit {code} — the release\'s '
                       f'runners are NOT in the worktree:\n{out[-1500:]}')
            report.skipped.append(
                f'{name}: check all + the two censuses — the release\'s '
                f'runners would not install, and this run does NOT fall back '
                f'to the consumer\'s own')
            return
        report.check(name, 'runners ahead', sorted(wrote) == sorted(ahead),
                     f'{len(ahead)} file(s) ahead of the consumer\'s install'
                     + (f': {", ".join(ahead)}' if ahead else
                        ' — the consumer is current with the working tree')
                     if sorted(wrote) == sorted(ahead) else
                     f'{len(ahead)} ahead by body+mode, {len(wrote)} written by '
                     f'the install: only-ahead {sorted(set(ahead) - set(wrote))}, '
                     f'only-written {sorted(set(wrote) - set(ahead))}')

        code, out = devkit(worktree, 'check', 'all')
        report.check(name, 'check all', code == 0,
                     f'exit {code} against the release\'s runners'
                     + ('' if code == 0 else f'\n{out[-2000:]}'))

        population = _scene_population(worktree)
        for gate, pattern in (('check tres', r'across (\d+) \.tres/\.tscn'),
                              ('check uid', r'across (\d+) file\(s\)')):
            code, out = devkit(worktree, *gate.split())
            match = re.search(pattern, out)
            if not match:
                report.bad(name, f'{gate} census', 'no census line in output')
                continue
            report.check(name, f'{gate} census',
                         int(match.group(1)) == population,
                         f'gate says {match.group(1)}, git ls-files says '
                         f'{population}')
    finally:
        removed = git_run(root, 'worktree', 'remove', '--force', str(worktree))
        git_run(root, 'worktree', 'prune')
        shutil.rmtree(holder, ignore_errors=True)
        clean, detail = worktree_verdict(
            before, git(root, 'worktree', 'list'), worktree, removed)
        report.check(name, 'worktree list unchanged', clean, detail)


def smoke(root: Path, report: Report) -> None:
    name = root.name
    before = git(root, 'status', '--porcelain')
    if before:
        # Reported, not fatal: somebody else's uncommitted work is not this
        # run's finding. What WOULD be this run's finding is a difference
        # between before and after, which is checked at the end regardless.
        report.ok(name, 'pre-existing dirty tree',
                  f'{len(before)} path(s) already modified — not this run')

    against_the_release_runners(root, report)

    code, out = devkit(root, 'autoloads')
    declared = _autoload_count(root)
    match = re.search(r'census \((\d+)\)', out)
    if match:
        report.check(name, 'autoloads census',
                     int(match.group(1)) == declared,
                     f'tool says {match.group(1)}, project.godot declares {declared}')
    else:
        report.bad(name, 'autoloads census', 'no census line in output')

    scene = _first(root, '*.tscn')
    if scene:
        code, out = devkit(root, 'scene', scene)
        report.check(name, 'scene', code == 0 and 'node tree' in out,
                     f'{scene}: exit {code}')
    else:
        report.skipped.append(f'{name}: scene (no .tscn tracked)')

    symbol = _a_class_name(root)
    if symbol:
        code, out = devkit(root, 'refs', symbol)
        report.check(name, 'refs', code == 0 and out.strip() != '',
                     f'{symbol}: exit {code}, {len(out.splitlines())} line(s)')
    else:
        report.skipped.append(f'{name}: refs (no class_name found)')

    for argv in (('pm', 'status'), ('pm', 'validate'), ('check', 'pm')):
        code, out = devkit(root, *argv)
        report.check(name, ' '.join(argv), code == 0,
                     f'exit {code}' + ('' if code == 0 else f'\n{out[-1500:]}'))

    props_findings(root, report)
    scene_round_trip(root, report)
    uid_differential(root, report)
    canonicalize_restores_a_real_scene(root, report)
    canonicalize_invents_no_index(root, report)
    defaults_elision(root, report)

    after = git(root, 'status', '--porcelain')
    # The SYMMETRIC difference: a path that LEFT the dirty list matters too, and
    # naming only the additions printed `DIRTIED the tree: []` on the run where
    # a peer agent committed in nullbound mid-smoke. A red row that names
    # nothing is the silence this file's own contract forbids.
    report.check(name, 'checkout unchanged', after == before,
                 'clean' if after == before
                 else f'the tree changed under the run — appeared '
                      f'{sorted(set(after) - set(before))}, left '
                      f'{sorted(set(before) - set(after))}')


def fresh_project(report: Report) -> None:
    """init an empty Godot 4 project in scratch, then run the REAL make doctor
    and the REAL make check.

    The ship criterion of the bootstrap milestone, on a real host: `init`, then
    `make doctor` green and no `make check` finding about anything the install
    wrote, with zero hand edits. What this can assert everywhere is the half
    `init` OWNS — the hooks armed, git pointed at them, and every gate quiet
    about the files the verb just wrote. Whether doctor is GREEN also depends
    on the host having godot, gdlint and uv, so the verdict distinguishes the
    two: an init-owned FAIL is this probe's finding, a missing host tool is
    named and is not.
    """
    if shutil.which('make') is None or shutil.which('git') is None:
        report.skipped.append(f'{FRESH}: needs make and git')
        return
    if shutil.which(GODOT) is None:
        report.skipped.append(
            f'{FRESH}: `{GODOT}` is not on PATH — the real `make doctor` was '
            f'NOT run (the suite still proves the file set and `make -n`)')
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'game'
        root.mkdir()
        (root / 'project.godot').write_text(FRESH_PROJECT_GODOT, encoding='utf-8')
        (root / 'icon.svg').write_text(FRESH_ICON, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)

        code, out = devkit(root, 'init')
        if not report.check(FRESH, 'godot-devkit init', code == 0,
                            f'exit {code}' + ('' if code == 0 else f'\n{out[-2000:]}')):
            return

        doctor = subprocess.run(['make', 'doctor'], cwd=root, text=True,
                                capture_output=True, env=dict(os.environ),
                                timeout=300)
        rows = doctor.stdout.splitlines()
        failed = [r.strip() for r in rows if r.strip().startswith('FAIL')]
        mine = [r for r in failed if any(k in r for k in INIT_OWNED)]
        report.check(FRESH, 'make doctor: hooks armed', not mine,
                     'git points at the installed hooks and every one is '
                     'executable' if not mine else '; '.join(mine))
        armed = sum(1 for r in rows
                    if 'tracked hook' in r and 'present + executable' in r)
        report.check(FRESH, 'make doctor: hook census', armed == TRACKED_HOOKS,
                     f'{armed} tracked hook(s) armed, {TRACKED_HOOKS} installed')
        host_gaps = [r for r in failed if r not in mine]
        report.check(FRESH, 'make doctor verdict',
                     doctor.returncode == 0 or bool(host_gaps),
                     f'exit {doctor.returncode}'
                     + (f'; host gaps, not this install: {"; ".join(host_gaps)}'
                        if host_gaps else ' — green on a fresh project'))
        if host_gaps:
            report.skipped.append(
                f'{FRESH}: `make doctor` is not green on this host — '
                f'{"; ".join(host_gaps)}')

        # …and the REAL `make check`. It boots nothing — the roster is pure
        # parse — so unlike doctor there is no host to blame and no reason
        # this was ever a dry run. Committed first: every gate resolves its
        # scope through `git ls-files`, and an uncommitted tree is a 0-file
        # census for all of them.
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(['git', '-c', 'user.email=smoke@example.com',
                        '-c', 'user.name=smoke', 'commit', '-qm',
                        'godot-devkit init', '--', '.'],
                       cwd=root, check=True, capture_output=True)
        subprocess.run(['make', 'check', working_tree_devkit()], cwd=root,
                       text=True, capture_output=True, env=_env(), timeout=300)
        transcript = (root / CHECK_LOG)
        verdicts = CHECK_VERDICT_RE.findall(
            transcript.read_text(encoding='utf-8') if transcript.is_file()
            else '')
        report.check(FRESH, 'make check: gates ran',
                     bool(verdicts), f'{len(verdicts)} gate verdict(s)')
        ours = [f'[check:{gate}] {detail}' for gate, outcome, detail in verdicts
                if outcome == 'FAIL' and CHECK_EMPTY_CENSUS not in detail]
        report.check(FRESH, 'make check: nothing init wrote is a finding',
                     not ours,
                     'no gate has a finding about an installed file'
                     if not ours else '; '.join(ours))
        empty = [gate for gate, outcome, detail in verdicts
                 if outcome == 'FAIL' and CHECK_EMPTY_CENSUS in detail]
        if empty:
            report.skipped.append(
                f'{FRESH}: {", ".join(empty)} report a 0-file census — a blank '
                f'project holds no .tscn/.tres; the roster is narrowed in '
                f'devkit.toml, not softened here')


def main() -> int:
    report = Report()
    fresh_project(report)
    present = [c for c in CONSUMERS if c.is_dir()]
    for absent in (c for c in CONSUMERS if not c.is_dir()):
        report.skipped.append(f'{absent} is not checked out')
    for root in present:
        smoke(root, report)

    width = max((len(r[1]) for r in report.rows), default=0)
    current = ''
    for consumer, what, detail in report.rows:
        if consumer != current:
            print(f'\n=== {consumer} ===')
            current = consumer
        print(f'  {what.ljust(width)}  {detail}')
    print()
    for line in report.skipped:
        print(f'[smoke] NOT RUN — {line}')
    if report.failed:
        print(f'[smoke] FAIL — {report.failed} check(s) across '
              f'{len(present)} consumer(s) + the fresh project')
        return 1
    if not present:
        # Loud, and exit 0: a machine without the consumers checked out has not
        # found a defect, and failing here would make the full gate unrunnable
        # anywhere but one laptop. What it must never do is imply it ran.
        print('[smoke] SKIPPED — no consumer checkout available; NOTHING was '
              'smoked against a live consumer. This is not a pass.')
        return 0
    print(f'[smoke] PASS — {len(report.rows)} check(s) across '
          f'{len(present)} consumer(s) + the fresh project, every census '
          f'matched an independent count, the gates run against the release\'s '
          f'own runners, both checkouts unchanged and no worktree left behind')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
