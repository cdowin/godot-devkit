"""patterns.py — check patterns: forbidden code patterns a PROJECT declares.

The devkit holds no rules. A project lists its own in `godot-devkit.toml`; each
rule is a regex over the lines of the files its globs match. A hit prints
`path:line: <id>: <message>` and the gate exits 1. With no rules the gate does
nothing and exits 0.

    [[patterns.rule]]
    id = "no-print"
    regex = "\\\\bprint\\\\("
    paths = ["src/**/*.gd"]
    exclude = ["src/debug/**"]          # optional
    message = "Use the logger, not print()."

A line opts out with a comment that names the rule: `# lint-allow: no-print`
(several ids: `# lint-allow: no-print, other-id`).

Rule 4: a rule whose globs match no tracked file FAILS. A typo in a glob must
not read as a clean tree. Config mistakes (a missing key, a bad regex, a
duplicate id) are exit 2.

HONEST SCOPE: matching is per line, over the raw text. Nothing is inferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from godot_devkit.core.config import ConfigError, config_section, str_tuple, text
from godot_devkit.core.project import git_lines, repo_root

SECTION = 'patterns'
RULE_KEY = 'rule'
TAG = '[check:patterns]'
ALLOW_RE = re.compile(r'lint-allow:\s*([\w\-]+(?:\s*,\s*[\w\-]+)*)')
KNOWN_KEYS = frozenset(('id', 'regex', 'paths', 'exclude', 'message'))


@dataclass(frozen=True)
class Rule:
    id: str
    regex: re.Pattern
    paths: tuple[re.Pattern, ...]
    exclude: tuple[re.Pattern, ...]
    message: str


def glob_re(glob: str) -> re.Pattern:
    """A repo-relative glob as a regex: `**` crosses `/`, `*` and `?` do not."""
    out, i = '', 0
    while i < len(glob):
        if glob.startswith('**/', i):
            out += '(?:.*/)?'
            i += 3
        elif glob.startswith('**', i):
            out += '.*'
            i += 2
        elif glob[i] == '*':
            out += '[^/]*'
            i += 1
        elif glob[i] == '?':
            out += '[^/]'
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return re.compile(out + r'\Z')


def _rules(sect: dict) -> list[Rule]:
    raw = sect.get(RULE_KEY, [])
    if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
        raise ConfigError(f'[{SECTION}] {RULE_KEY} must be an array of tables '
                          f'([[{SECTION}.{RULE_KEY}]])')
    rules: list[Rule] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw, start=1):
        where = f'[[{SECTION}.{RULE_KEY}]] #{index}'
        unknown = sorted(set(entry) - KNOWN_KEYS)
        if unknown:
            raise ConfigError(f'{where} has unknown key(s) {", ".join(unknown)}')
        for key in ('id', 'regex', 'paths', 'message'):
            if key not in entry:
                raise ConfigError(f'{where} needs {key!r}')
        rule_id = text(entry, SECTION, 'id', '')
        if not re.fullmatch(r'[\w\-]+', rule_id):
            raise ConfigError(f'{where} id {rule_id!r} must be letters, digits, _ or -')
        if rule_id in seen:
            raise ConfigError(f'{where} repeats id {rule_id!r}')
        seen.add(rule_id)
        try:
            regex = re.compile(text(entry, SECTION, 'regex', ''))
        except re.error as err:
            raise ConfigError(f'{where} regex is not valid: {err}') from err
        paths = str_tuple(entry, SECTION, 'paths', ())
        exclude = str_tuple(entry, SECTION, 'exclude', ()) if 'exclude' in entry else ()
        rules.append(Rule(rule_id, regex, tuple(glob_re(g) for g in paths),
                          tuple(glob_re(g) for g in exclude),
                          text(entry, SECTION, 'message', '')))
    return rules


def scan_text(content: str, path: str, rule: Rule) -> list[str]:
    """The `path:line: id: message` lines for one rule over one file."""
    hits = []
    for lineno, line in enumerate(content.split('\n'), start=1):
        if not rule.regex.search(line):
            continue
        allowed = ALLOW_RE.search(line)
        if allowed and rule.id in re.split(r'\s*,\s*', allowed.group(1)):
            continue
        hits.append(f'{path}:{lineno}: {rule.id}: {rule.message}')
    return hits


def run() -> int:
    rules = _rules(config_section(SECTION))
    if not rules:
        print(f'{TAG} PASS — no rules declared in [{SECTION}]')
        return 0
    root = repo_root()
    tracked = git_lines('ls-files')
    findings: list[str] = []
    empty: list[str] = []
    for rule in rules:
        files = [rel for rel in tracked
                 if any(g.match(rel) for g in rule.paths)
                 and not any(g.match(rel) for g in rule.exclude)]
        if not files:
            empty.append(rule.id)
        for rel in files:
            try:
                content = (root / rel).read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            findings.extend(scan_text(content, rel, rule))
    for rule_id in empty:
        print(f'  EMPTY  {rule_id} — its paths match no tracked file; check the globs')
    for finding in findings:
        print(finding)
    if findings or empty:
        print(f'\n{TAG} FAIL — {len(findings)} hit(s), {len(empty)} empty rule(s) '
              f'across {len(rules)} rule(s)')
        return 1
    print(f'{TAG} PASS — {len(rules)} rule(s), no hits')
    return 0
