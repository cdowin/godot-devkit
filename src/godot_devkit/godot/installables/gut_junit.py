"""Check a GUT JUnit report against the scripts selected for this run.

GUT emits one testsuite per loaded script. Its success exit alone can hide a
script it refused to load, so compare exact script paths, not just totals.
This standalone consumer runner helper cannot depend on the devkit CLI package.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _local(value: str) -> Path:
    return Path(value.removeprefix('res://').rstrip('/'))


def read_config(config: str) -> dict:
    if not config or not _local(config).is_file():
        return {}
    opts = json.loads(_local(config).read_text(encoding='utf-8'))
    if opts.get('junit_xml_timestamp') is True:
        raise ValueError('junit_xml_timestamp must be false for a stable JUnit path')
    if opts.get('errors_do_not_cause_failure') is True:
        raise ValueError('errors_do_not_cause_failure must be false for a gate')
    if opts.get('no_error_tracking', False) is not False:
        raise ValueError('no_error_tracking must be false for a gate')
    if 'failure_error_types' in opts and (not isinstance(opts['failure_error_types'], list)
            or any(not isinstance(item, str) for item in opts['failure_error_types'])
            or set(opts['failure_error_types']) != {'engine', 'gut', 'push_error'}):
        raise ValueError('failure_error_types must include engine, gut and push_error')
    return opts


def selected_scripts(config: str, default_dir: str, args: list[str]) -> set[str]:
    opts = read_config(config)
    dirs = list(opts.get('dirs', []))
    tests = list(opts.get('tests', []))
    prefix = opts.get('prefix', 'test_')
    suffix = opts.get('suffix', '.gd')
    recursive = opts.get('include_subdirs', False)
    select = opts.get('selected', '')
    cli_dirs = False
    cli_tests = False
    index = 0
    while index < len(args):
        arg = args[index]
        key, sep, value = arg.partition('=')
        if not sep and key in ('-gtest', '-gdir', '-gselect', '-gprefix', '-gsuffix'):
            index += 1
            if index >= len(args):
                raise ValueError(f'{key} needs a value')
            value = args[index]
        if key == '-gtest':
            if not cli_tests:
                tests = []
                cli_tests = True
            tests = [] if value == '' else tests + value.split(',')
        elif key == '-gdir':
            if not cli_dirs:
                dirs = []
                cli_dirs = True
            dirs = [] if value == '' else dirs + value.split(',')
        elif key == '-gselect':
            select = value
        elif key == '-gprefix':
            prefix = value
        elif key == '-gsuffix':
            suffix = value
        elif arg == '-ginclude_subdirs':
            recursive = True
        index += 1
    paths = {_local(item) for item in tests if item}
    for item in dirs:
        directory = _local(item)
        if not directory.is_dir():
            continue
        glob = directory.rglob if recursive else directory.glob
        paths.update(glob(f'{prefix}*{suffix}'))
    return {path.as_posix() for path in paths if path.is_file() and (not select or select in path.name)}


def check(xml_path: str, config: str, default_dir: str, args: list[str]) -> str:
    expected = selected_scripts(config, default_dir, args)
    if not expected:
        raise ValueError(f'no test scripts selected under {default_dir}')
    root = ET.parse(xml_path).getroot()
    if root.tag != 'testsuites':
        raise ValueError('GUT JUnit root is not testsuites')
    def file_name(suite: ET.Element) -> str:
        name = suite.get('name', '').removeprefix('res://')
        return name.split('.gd.', 1)[0] + '.gd' if '.gd.' in name else name

    actual = {file_name(suite) for suite in root.findall('testsuite')}
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        raise ValueError(f'GUT JUnit script census mismatch: missing={sorted(missing)}, extra={sorted(extra)}')
    count = int(root.get('tests', '0'))
    if count < 1:
        raise ValueError('GUT JUnit reports zero tests')
    failures = int(root.get('failures', '0'))
    if failures:
        raise ValueError(f'GUT JUnit reports {failures} failure(s)')
    if root.findall('.//failure') or root.findall('.//error'):
        raise ValueError('GUT JUnit contains a failure or error element')
    by_file: dict[str, int] = {}
    for suite in root.findall('testsuite'):
        by_file[file_name(suite)] = by_file.get(file_name(suite), 0) + len(suite.findall('testcase'))
    for file, cases in by_file.items():
        if cases < 1:
            raise ValueError(f'{file} ran no tests')
    if not any(case.find('skipped') is None for case in root.findall('.//testcase')):
        raise ValueError('GUT JUnit reports only skipped tests')
    return f'{count} test(s), {len(actual)} script(s)'


def check_output(log_path: str) -> str:
    """GUT owns in-session error assertions; bootstrap and parse failures do not."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", Path(log_path).read_text(encoding="utf-8", errors="replace"))
    in_gut = False
    finished = False
    shutdown = []
    for line in text.splitlines():
        if "GUT version:" in line:
            in_gut = True
        if line.startswith("Results saved to "):
            finished = True
        if re.search(r"SCRIPT ERROR|Failed to load script|invalid UID", line):
            raise ValueError(line)
        if line.startswith("ERROR:"):
            if finished and (re.fullmatch(r"ERROR: \d+ resources still in use at exit \(run with --verbose for details\)\.", line)
                    or re.fullmatch(r"ERROR: \d+ RID allocations of type '.+' were leaked at exit\.", line)):
                shutdown.append(line)
            elif not in_gut or finished:
                raise ValueError(line)
    # These are real diagnostic debt, not test failures. Keep both the counts
    # and the complete engine transcript; never discard or relabel them clean.
    return "\n".join("[GUT] shutdown diagnostic: " + line for line in shutdown)


def main(argv: list[str]) -> int:
    if argv and argv[0] == 'output':
        if len(argv) != 2:
            return 2
        try:
            note = check_output(argv[1])
            if note:
                print(note)
        except (OSError, ValueError) as exc:
            print(f'GUT output FAIL — {exc}', file=sys.stderr)
            return 1
        return 0
    if argv and argv[0] == 'validate':
        if len(argv) != 2:
            return 2
        try:
            read_config(argv[1])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f'GUT config FAIL — {exc}', file=sys.stderr)
            return 2
        return 0
    if argv and argv[0] == 'list':
        if len(argv) < 3:
            print('usage: gut_junit.py list <config> <default-dir>', file=sys.stderr)
            return 2
        try:
            paths = selected_scripts(argv[1], argv[2], argv[3:])
            if not paths:
                raise ValueError('no test scripts selected')
            print('\n'.join(sorted(paths)))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f'GUT selection FAIL — {exc}', file=sys.stderr)
            return 1
        return 0
    if len(argv) < 3:
        print('usage: gut_junit.py <junit.xml> <config> <default-dir> [GUT args...]', file=sys.stderr)
        return 2
    try:
        print(check(argv[0], argv[1], argv[2], argv[3:]))
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f'GUT JUnit FAIL — {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
