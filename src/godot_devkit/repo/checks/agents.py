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

from godot_devkit.core.config import ConfigError, config_section, str_tuple
from godot_devkit.core.markdown import code_spans, non_fenced_lines
from godot_devkit.core.project import repo_root
from godot_devkit.repo.pm import model

DEFAULT_SCOPE = ('.claude/agents/*.md', '.claude/rules/*.md', '.claude/skills/**/*.md')
SKILL_DIR = '.claude/skills'
SKILL_FILENAME = 'SKILL.md'

# `pm story wip <id>` / `tools/pm/pm feature done` / `godot-devkit pm milestone ready`
# Matched only INSIDE a backtick span: prose that merely uses the words ("the pm
# story lifecycle") is not an invocation, and reading it as one turns the gate
# red on correct text — the failure this file's own docstring calls fatal.
_INVOCATION = re.compile(r'\bpm\s+(milestone|feature|story)\s+([a-z][a-z-]*)')
# `review -> done`, `review → done`, `wip → review`. Split rather than findall:
# a non-overlapping findall over `a -> b -> c` yields (a,b) and silently drops
# (b,c), so a chained lifecycle line hid an illegal middle edge.
_ARROW = re.compile(r'\s*(?:->|→)\s*')
_WORD = re.compile(r'[a-z]+')


def _transitions(line: str) -> list[tuple[str, str]]:
    """Adjacent (from, to) pairs, including the middle of a chain.

    `re.findall` is non-overlapping, so scanning `a -> b -> c` for pairs yields
    (a, b) and resumes past b — silently dropping (b, c). A lifecycle line
    written as a chain therefore hid an illegal middle edge. Split on the arrow
    instead and take the word adjacent to each side of it.
    """
    parts = _ARROW.split(line)
    if len(parts) < 2:
        return []
    lefts = [(_WORD.findall(p) or [''])[-1] for p in parts[:-1]]
    rights = [(_WORD.findall(p) or [''])[0] for p in parts[1:]]
    return [(a, b) for a, b in zip(lefts, rights) if a and b]


# A line that PROHIBITS a transition is documenting the rule, not instructing
# the breach — and flagging the doc that gets it right is the fastest way to get
# a gate switched off. Conservative by design: these words are unambiguous, and
# a missed real finding is survivable where a false one is not.
_NEGATION = re.compile(
    r"\b(never|not|no|refus\w*|reject\w*|illegal|invalid|cannot|can't|"
    r"forbidden|prohibit\w*|doesn't|won't|wrong|hole|drift)\b", re.I)

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
    defects: list[str] = []
    unverified = 0
    skipped = 0

    def report(msg: str) -> None:
        findings.append(msg)
        print(f'  INSTRUCTS  {msg}')

    def defect(msg: str) -> None:
        # Not an INSTRUCTS: the definition contradicts nothing, the SCAN of it
        # is what cannot be trusted. Separated so the FAIL line can say which
        # of the two it found.
        defects.append(msg)
        print(f'  MALFORMED  {msg}')

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

        # A3 — a flat skill file never loads as a skill. But `<name>/SKILL.md`
        # legitimately sits beside references/, scripts/ and assets/, so only a
        # .md at depth 1 under skills/ is the defect; anything deeper is a
        # supporting file of a correctly-shaped skill.
        parts = path.relative_to(root).parts
        flat_skill = (len(parts) == 3 and parts[:2] == ('.claude', 'skills')
                      and path.suffix == '.md')
        if flat_skill:
            report(f'{rel}: a skill must be <name>/{SKILL_FILENAME}; a flat '
                   f'.md does NOT load as a skill (its description never fires)')

        # Fenced blocks are illustrations, not claims (core/markdown.py). An
        # unterminated one illustrates nothing and hides everything after it,
        # so it skips no line here and is reported instead.
        lines, unterminated = non_fenced_lines(text)
        skipped += len(text.split('\n')) - len(lines)
        if unterminated:
            defect(f'{rel}:{unterminated}: opens a code fence that is never '
                   f'terminated — the rest of the file was scanned UNMASKED; '
                   f'close the fence, or shorten the run of backticks if you '
                   f'meant an inline span')
        for n, line in lines:
            for span in code_spans(line):
              for grain, verb in _INVOCATION.findall(span):
                if verb not in verbs[grain] and verb not in ('new', 'status'):
                    report(f'{rel}:{n}: `pm {grain} {verb}` — the CLI has no '
                           f'{verb!r} verb for a {grain} '
                           f'(it accepts: {", ".join(sorted(verbs[grain]))})')
            for src, dst in _transitions(line):
                grain = _grain_on_line(line)
                if grain is None:
                    if src in cfg.story_states or dst in cfg.story_states:
                        unverified += 1
                    continue
                states = {'milestone': cfg.milestone_states,
                          'feature': cfg.feature_states,
                          'story': cfg.story_states}[grain]
                if src not in states or dst not in states:
                    # A determined grain but an unrecognised state: not a
                    # finding, but it IS undecided, so it must be censused.
                    unverified += 1
                    continue
                if _NEGATION.search(line):
                    # Documenting the refusal, not instructing it.
                    unverified += 1
                    continue
                if not model.transition_legal(_graph(cfg, grain), src, dst):
                    extra = (' — a story reaches `done` only through '
                             '`pm feature done`\'s cascade'
                             if grain == 'story' and dst == 'done' else '')
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
    # The census counts FILES, and files are not what a fence hides — so it
    # also says how much text was skipped, or a PASS is a PASS over an unknown
    # amount of unread definition.
    census = f'{len(files)} definition(s), {skipped} fenced line(s) skipped'
    if unverified:
        census += (f', {unverified} transition mention(s) UNVERIFIED (the line '
                   f'names no single grain, an unknown state, or prohibits '
                   f'rather than instructs)')
    if findings or defects:
        what = ', '.join(part for part in (
            f'{len(findings)} definition(s) instruct what the tooling refuses'
            if findings else '',
            f'{len(defects)} definition(s) this gate cannot honestly scan'
            if defects else '') if part)
        print(f'[check:agents] FAIL — {what}, across {census}')
        return 1
    print(f'[check:agents] PASS — no definition contradicts the pm CLI; '
          f'scanned {census}')
    return 0


if __name__ == '__main__':
    sys.exit(run())
