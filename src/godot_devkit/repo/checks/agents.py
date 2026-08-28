"""check agents — agent/rule/skill definitions that instruct the impossible.

An agent definition is prose, so nothing stops it describing a workflow the
tooling refuses. That drift is invisible until an agent follows the instruction
and the CLI says no — by which time a story sits in the wrong state and someone
hand-edits around it, which is the exact failure the PM CLI exists to prevent.

The rules, and why each is mechanically decidable:

  A1  a `pm <grain> <verb>` invocation naming a verb the CLI does not have.
  A2  a `<state> -> <state>` transition claim that the grain's own graph
      refuses. The grain is read from the SAME LINE; a line naming no grain, or
      naming two, is censused UNVERIFIED rather than guessed at.
  A3  a skill that is a flat `<name>.md` instead of `<name>/SKILL.md`, which
      does not load as a skill at all.
  A4  project-configured forbidden instruction patterns — `[agents] forbidden`.

The vocabulary for A1/A2 comes from the pm model itself, never from scraping
help text, so the checker cannot drift from the tool it checks against.

Precision over reach, as everywhere in this package: a false FAIL gets the gate
switched off and then nothing is checked. Anything not decidable is censused.
"""
from __future__ import annotations

import re
import sys

from godot_devkit.core.project import ConfigError, config_section, repo_root, str_tuple
from godot_devkit.repo.pm import model

DEFAULT_SCOPE = ('.claude/agents/*.md', '.claude/rules/*.md', '.claude/skills/**/*.md')
SKILL_DIR = '.claude/skills'
SKILL_FILENAME = 'SKILL.md'

# `pm story wip <id>` / `tools/pm/pm feature done` / `godot-devkit pm milestone ready`
_INVOCATION = re.compile(r'\bpm\s+(milestone|feature|story)\s+([a-z][a-z-]*)')
# `review -> done`, `review → done`, `wip → review`
_TRANSITION = re.compile(r'\b([a-z]+)\s*(?:->|→)\s*([a-z]+)\b')
_GRAIN_WORDS = {'milestone': 'milestone', 'milestones': 'milestone',
                'feature': 'feature', 'features': 'feature',
                'story': 'story', 'stories': 'story'}


def _verbs(cfg: model.PmConfig) -> dict[str, set[str]]:
    """The verbs the CLI actually accepts per grain, from the graphs themselves."""
    return {
        'milestone': {t.split('->')[1] for t in cfg.milestone_transitions},
        'feature': {t.split('->')[1] for t in cfg.feature_transitions},
        # `blocked` is reachable from any state, so it is a verb without an edge.
        'story': {t.split('->')[1] for t in cfg.story_transitions} | {'blocked'},
    }


def _graph(cfg: model.PmConfig, grain: str) -> tuple[str, ...]:
    return {'milestone': cfg.milestone_transitions,
            'feature': cfg.feature_transitions,
            'story': cfg.story_transitions}[grain]


def _grain_on_line(line: str) -> str | None:
    """The single grain this line is about, or None when it is ambiguous."""
    found = {_GRAIN_WORDS[w] for w in re.findall(r'[a-z]+', line.lower())
             if w in _GRAIN_WORDS}
    return found.pop() if len(found) == 1 else None


def run() -> int:
    cfg = model.load()
    sect = config_section('agents')
    scope = str_tuple(sect, 'agents', 'scope', DEFAULT_SCOPE)
    forbidden = str_tuple(sect, 'agents', 'forbidden', ())
    root = repo_root()

    findings: list[str] = []
    unverified = 0

    def report(msg: str) -> None:
        findings.append(msg)
        print(f'  INSTRUCTS  {msg}')

    files = sorted({p for glob in scope for p in root.glob(glob) if p.is_file()})
    print(f'[check:agents] scanning {len(files)} definition(s) against the pm CLI '
          f'vocabulary')
    if not files:
        print()
        print(f'[check:agents] FAIL — scanned 0 definitions; check [agents] scope')
        return 1

    verbs = _verbs(cfg)
    for path in files:
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue

        # A3 — a flat skill file never loads as a skill.
        if rel.startswith(SKILL_DIR) and path.name != SKILL_FILENAME:
            report(f'{rel}: a skill must be <name>/{SKILL_FILENAME}; a flat '
                   f'.md does NOT load as a skill (its description never fires)')

        for n, line in enumerate(text.splitlines(), 1):
            for grain, verb in _INVOCATION.findall(line):
                if verb not in verbs[grain] and verb not in ('new', 'status'):
                    report(f'{rel}:{n}: `pm {grain} {verb}` — the CLI has no '
                           f'{verb!r} verb for a {grain} '
                           f'(it accepts: {", ".join(sorted(verbs[grain]))})')
            for src, dst in _TRANSITION.findall(line):
                grain = _grain_on_line(line)
                if grain is None:
                    if src in model.DEFAULT_STORY_STATES or dst in model.DEFAULT_STORY_STATES:
                        unverified += 1
                    continue
                states = {'milestone': cfg.milestone_states,
                          'feature': cfg.feature_states,
                          'story': cfg.story_states}[grain]
                if src not in states or dst not in states:
                    continue
                if not model.transition_legal(_graph(cfg, grain), src, dst):
                    extra = ('' if grain != 'story' else
                             ' — a story reaches `done` only through '
                             '`pm feature done`\'s cascade')
                    report(f'{rel}:{n}: describes a {grain} going '
                           f'{src} -> {dst}, which the CLI refuses{extra}')
            for pattern in forbidden:
                try:
                    if re.search(pattern, line):
                        report(f'{rel}:{n}: matches [agents] forbidden pattern '
                               f'{pattern!r}')
                except re.error as err:
                    raise ConfigError(
                        f'[agents] forbidden pattern {pattern!r} is not a valid '
                        f'regex: {err}') from err

    print()
    census = f'{len(files)} definition(s)'
    if unverified:
        census += (f', {unverified} transition mention(s) UNVERIFIED (the line '
                   f'names no single grain)')
    if findings:
        print(f'[check:agents] FAIL — {len(findings)} definition(s) instruct '
              f'what the tooling refuses, across {census}')
        return 1
    print(f'[check:agents] PASS — no definition contradicts the pm CLI; '
          f'scanned {census}')
    return 0


if __name__ == '__main__':
    sys.exit(run())
