"""test_verdict.py — the verdict block: what it reads, and what it refuses.

An INPUT SURFACE (SDLC.md §5), so the refusals are enumerated here rather than
left to the intended path: a parser over a fenced block written by an LLM is
going to be handed near-misses, and the two ways to get this wrong are both
worse than a crash. Reading a nearly-right block as "no verdict" is rule 4's
read-side sin — the report prints a clean number over a pass it never counted.
Reading a partly-right one as a partial list is the write-side twin: a yield
figure that looks legitimate and is not.

So every test below is one of three claims:

    it parses      the shape the four installed agent definitions emit,
                   whitespace, case and CRLF tolerance included;
    it refuses     with the line number and the offending line, for every
                   near-miss the grammar admits;
    it is there    the block's text is actually in each of the four shipped
                   definitions — a parser for a block nobody is told to write
                   is a parser that always returns NoVerdict.
"""
from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402,F401  (puts src/ on the path)

from godot_devkit.repo import install  # noqa: E402
from godot_devkit.repo.pm import verdict  # noqa: E402

# The four reviewer-shaped definitions `install-agents` ships. The story names a
# `code-reviewer` as the fourth; there is no INSTALLABLE by that name. This repo
# carries a repo-local `.claude/agents/code-reviewer.md` which says in its own
# opening line that it has no installables counterpart and sits outside the
# byte-currency test on purpose — so it is not one of these, and
# `verification-reviewer.md` is the fourth reviewer-shaped definition that ships.
REVIEWER_AGENTS = ('reviewer.md', 'simplifier.md',
                   'milestone-reviewer.md', 'verification-reviewer.md')

HEADER_ROW = '| id | severity | disposition |'
FENCE = '```'


def block(*rows: str, verdict_line: str = 'verdict: SHIP-WITH-FIXES',
          header: str = HEADER_ROW, info: str = 'text') -> str:
    """A review record: prose, the fenced block, prose."""
    return '\n'.join((
        '# Feature Review — a thing',
        '',
        'Some prose the human reads, which mentions a verdict in passing.',
        '',
        f'{FENCE}{info}',
        verdict_line,
        header,
        *rows,
        FENCE,
        '',
        'A trailing paragraph.',
        ''))


def malformed(text: str) -> verdict.MalformedVerdict:
    with pytest.raises(verdict.MalformedVerdict) as caught:
        verdict.parse(text)
    return caught.value


# --- what it reads ------------------------------------------------------------
@pytest.mark.parametrize('name', verdict.VERDICTS)
def test_every_verdict_in_the_closed_set_parses(name):
    """All six, each proven — a set with an untested member is a set with a
    typo in it, and the typo surfaces the day a reviewer uses that verdict."""
    parsed = verdict.parse(block(verdict_line=f'verdict: {name}'))
    assert parsed.verdict == name
    assert parsed.findings == []


def test_a_pass_that_raised_nothing_is_a_verdict_with_no_rows():
    """The header row alone is a complete block. A clean pass must not be
    indistinguishable from a record that never wrote one."""
    parsed = verdict.parse(block(verdict_line='verdict: SHIP'))
    assert parsed == verdict.Verdict('SHIP', [])


def test_every_disposition_kind_and_its_raw_value():
    """The story's own example, field for field. `disposition_value` is the
    RAW thing (D5): the hash, the reason, the grain id — nothing inferred."""
    parsed = verdict.parse(block(
        '| W1 | WARNING | landed 3a42f19ad |',
        '| S3 | SUGGESTION | rejected: pause regression |',
        '| D2 | DELTA | deferred: 0.90.3/throwable-as-behavior |'))
    assert parsed.verdict == 'SHIP-WITH-FIXES'
    assert parsed.findings == [
        verdict.Finding('W1', 'WARNING', 'landed', '3a42f19ad'),
        verdict.Finding('S3', 'SUGGESTION', 'rejected', 'pause regression'),
        verdict.Finding('D2', 'DELTA', 'deferred', '0.90.3/throwable-as-behavior'),
    ]
    assert {f.disposition_kind for f in parsed.findings} == set(verdict.DISPOSITION_KINDS)


@pytest.mark.parametrize('severity', verdict.SEVERITIES)
def test_every_severity_in_the_closed_set_parses(severity):
    """The set is the union of the four definitions' grades. A severity an
    installed agent is told to assign and this parser rejects would be a
    parser that exits 2 on its own tooling's correct output."""
    parsed = verdict.parse(block(f'| F1 | {severity} | landed 3a42f19ad |'))
    assert parsed.findings[0].severity == severity


def test_the_block_is_found_with_prose_and_other_fenced_blocks_around_it():
    """A real record is mostly prose and quotes commands. Neither may hide the
    block, and neither may be mistaken for one."""
    text = ('# Review\n\nEvidence:\n\n```console\n$ make precommit\n'
            'PASS\n```\n\nMore prose.\n\n' + block('| N1 | NIT | rejected: taste |')
            + '\n```python\nverdict = "not this one"\n```\n')
    parsed = verdict.parse(text)
    assert parsed.verdict == 'SHIP-WITH-FIXES'
    assert [f.id for f in parsed.findings] == ['N1']


def test_whitespace_in_the_cells_is_tolerated_and_the_shape_is_not():
    """Tolerant on the cells, strict on the shape — the one rule the module
    states. Ragged column padding is how a human edits a markdown table."""
    parsed = verdict.parse(block(
        '|   W1    |   WARNING   |   landed 3a42f19ad   |',
        '',
        '|D2|DELTA|deferred: 0.22.0/review-record-shape|'))
    assert [(f.id, f.severity, f.disposition_value) for f in parsed.findings] == [
        ('W1', 'WARNING', '3a42f19ad'),
        ('D2', 'DELTA', '0.22.0/review-record-shape')]


def test_the_fixed_keywords_fold_case_and_the_closed_set_values_come_back_canonical():
    """Detection is generous so nothing is silently missed; the stored value is
    canonical so the report groups `Warning` and `WARNING` as one severity
    instead of two rows in its own output."""
    parsed = verdict.parse(block('| w1 | Warning | LANDED 3A42F19AD |',
                                 verdict_line='Verdict: ship-with-fixes'))
    assert parsed.verdict == 'SHIP-WITH-FIXES'
    assert parsed.findings[0].severity == 'WARNING'
    assert parsed.findings[0].disposition_kind == 'landed'
    assert parsed.findings[0].disposition_value == '3A42F19AD'  # raw: not a closed set


def test_crlf_line_endings_parse_identically():
    """A record round-tripped through a Windows editor or a CRLF-normalising
    git config is the same record. `\\r` on the end of every cell would fail
    the severity lookup and report a malformed block over a correct one."""
    text = block('| W1 | WARNING | landed 3a42f19ad |')
    assert verdict.parse(text.replace('\n', '\r\n')) == verdict.parse(text)


def test_a_tilde_fence_carries_a_block_too():
    """`core.markdown` owns the fence rules; this module must not have quietly
    re-implemented half of them as 'a line of three backticks'."""
    text = '# R\n\n~~~\nverdict: HOLD\n' + HEADER_ROW + '\n~~~\n'
    assert verdict.parse(text).verdict == 'HOLD'


# --- what it refuses: no block is a FACT, not a failure -----------------------
def test_a_record_with_no_block_raises_NoVerdict_not_MalformedVerdict():
    """The two failures are different questions for a human: "nobody wrote one
    yet" is a line in the report, "this one is broken" is exit 2. A caller
    cannot tell them apart if they arrive as the same exception."""
    with pytest.raises(verdict.NoVerdict):
        verdict.parse('# Review\n\nAll good.\n\n```\nmake precommit\n```\n')


def test_a_prose_verdict_line_is_not_a_block():
    """The corpus's own shape — `**Verdict: RELEASE-WITH-FIXES**` heads two
    milestone records. Reading the narration is the one source this package's
    SDLC refuses to trust, so the fence is load-bearing, not decoration."""
    with pytest.raises(verdict.NoVerdict):
        verdict.parse('# Review\n\n**Verdict: RELEASE-WITH-FIXES** — one MAJOR.\n')


def test_NoVerdict_says_how_much_it_read():
    """Rule 4: a reader that found nothing says what it looked at. "No verdict
    block" over a record it never opened and over a 400-line one are different
    reports, and only one of them prints."""
    message = str(pytest.raises(
        verdict.NoVerdict,
        verdict.parse, '# Review\n\n```\nnothing\n```\n').value)
    assert '1 fenced block(s) read' in message


# --- what it refuses: a block that cannot be read correctly -------------------
def test_two_blocks_refuse_and_name_the_second():
    """"The verdict of this pass" is a single fact. Taking the first, the last,
    or the "better" one is the guess this parser exists not to make."""
    text = block('| W1 | WARNING | landed 3a42f19ad |') + '\n' + block(
        verdict_line='verdict: HOLD')
    error = malformed(text)
    assert 'second verdict block' in error.why
    assert error.line == 'verdict: HOLD'
    assert text.split('\n')[error.lineno - 1] == 'verdict: HOLD'


def test_a_row_with_two_cells_refuses_with_its_line_number():
    text = block('| W1 | WARNING | landed 3a42f19ad |', '| S3 | rejected: no |')
    error = malformed(text)
    assert '2 cell(s)' in error.why
    assert error.line == '| S3 | rejected: no |'
    assert text.split('\n')[error.lineno - 1] == error.line


def test_a_row_with_four_cells_refuses():
    assert '4 cell(s)' in malformed(
        block('| W1 | WARNING | landed 3a42f19ad | extra |')).why


def test_an_unknown_severity_refuses():
    """The closed set is the point: a free-text severity column makes "findings
    by severity" a column of one-off strings."""
    error = malformed(block('| W1 | SEVERE | landed 3a42f19ad |'))
    assert "unknown severity 'SEVERE'" in error.why


def test_an_unknown_verdict_refuses_and_lists_the_set():
    error = malformed(block(verdict_line='verdict: LGTM'))
    assert "unknown verdict 'LGTM'" in error.why
    for name in verdict.VERDICTS:
        assert name in error.why


def test_an_empty_verdict_refuses():
    assert "unknown verdict ''" in malformed(block(verdict_line='verdict:')).why


@pytest.mark.parametrize('disposition', (
    'landed',                 # no hash at all
    'landed ',                # the separator and nothing after it
    'landed 3a42f1',          # six — shorter than git's short hash
    'landed ' + 'a' * 41,     # longer than a full hash
    'landed zzzzzzz',         # right length, not hex
    'landed 3a42f19ad and also 9b1',   # two, so which one
    'landed: 3a42f19ad',      # the colon form; the grammar uses a space
))
def test_a_landed_without_a_usable_hash_refuses(disposition):
    """`landed <not-a-commit>` is a disposition nobody can follow up, which
    makes it worse than a missing row — it reads as evidence."""
    error = malformed(block(f'| W1 | WARNING | {disposition} |'))
    assert 'unreadable disposition' in error.why


@pytest.mark.parametrize('target', (
    '..',                     # traversal
    '../0.21.0',
    '0.22.0/../../etc',
    '.',                      # the dot segment
    '0.22.0//story',          # an empty segment
    '/0.22.0',                # absolute
    '0.90.3/*',               # a glob
    '0.90.3/throw[ab]le',
    'a\\b',                   # a backslash
    'a/b/c/d',                # deeper than milestone/feature/story
))
def test_a_deferred_that_is_not_a_grain_id_refuses(target):
    """A deferral names the grain that will carry the finding. The segment
    guard is the resolvers' own, so what `pm` refuses to resolve this refuses
    to record."""
    error = malformed(block(f'| D2 | DELTA | deferred: {target} |'))
    assert 'is not a grain id' in error.why or 'unreadable disposition' in error.why


def test_a_deferred_with_no_target_refuses():
    assert 'unreadable disposition' in malformed(
        block('| D2 | DELTA | deferred: |')).why


def test_a_rejected_with_no_reason_refuses():
    """"Rejected" with nothing after it is the finding the report most wants a
    sentence for."""
    assert 'unreadable disposition' in malformed(
        block('| S3 | SUGGESTION | rejected: |')).why


def test_an_unknown_disposition_kind_refuses():
    assert 'unreadable disposition' in malformed(
        block('| W1 | WARNING | wontfix |')).why


@pytest.mark.parametrize('row', (
    'W1 | WARNING | landed 3a42f19ad',        # no delimiters at all
    '| W1 | WARNING | landed 3a42f19ad',      # unclosed
    'W1 | WARNING | landed 3a42f19ad |',      # unopened
    '|',                                      # a lone delimiter
    'a sentence that wandered into the block',
))
def test_a_line_in_the_block_that_is_not_a_row_refuses(row):
    error = malformed(block(row))
    assert 'opens and closes' in error.why
    assert error.line == row


def test_a_markdown_separator_row_refuses_loudly():
    """`| --- | --- | --- |` is the habit every markdown table trains. It is
    not in the shape, so it refuses with a line number rather than becoming a
    finding whose id is three hyphens."""
    error = malformed(block('| --- | --- | --- |',
                            '| W1 | WARNING | landed 3a42f19ad |'))
    assert "unknown severity '---'" in error.why


def test_a_block_with_no_header_row_refuses():
    text = ('# R\n\n' + FENCE + 'text\nverdict: SHIP\n' + FENCE + '\n')
    assert 'no header row' in malformed(text).why


@pytest.mark.parametrize('header', (
    '| id | severity |',
    '| id | grade | disposition |',
    '| severity | id | disposition |',
    '| W1 | WARNING | landed 3a42f19ad |',
))
def test_a_wrong_header_row_refuses(header):
    """The header is part of the shape. Without it the first finding silently
    becomes the header and vanishes from the count."""
    error = malformed(block(header=header))
    assert 'header row must read' in error.why or 'cell(s)' in error.why


def test_an_empty_id_refuses():
    assert 'id cell is empty' in malformed(
        block('|  | WARNING | landed 3a42f19ad |')).why


def test_an_id_carrying_whitespace_refuses():
    assert 'one token' in malformed(
        block('| W 1 | WARNING | landed 3a42f19ad |')).why


def test_an_over_long_id_refuses():
    long_id = 'W' * (verdict.MAX_ID_LEN + 1)
    assert f'{len(long_id)} characters' in malformed(
        block(f'| {long_id} | WARNING | landed 3a42f19ad |')).why


def test_an_unterminated_fence_over_a_verdict_refuses_instead_of_reporting_none():
    """The quiet miss, closed. An unclosed fence masks nothing, so the block is
    in no block list at all — and NoVerdict over a record whose verdict is
    sitting right there is the read-side cardinal sin."""
    text = ('# R\n\n' + FENCE + 'text\nverdict: SHIP\n' + HEADER_ROW + '\n')
    error = malformed(text)
    assert 'never closed' in error.why
    assert error.lineno == 3


def test_an_unterminated_fence_over_something_else_is_not_this_modules_finding():
    """Scoped: a stray fence elsewhere in the record is `check doc`'s finding.
    Claiming it here would make every malformed markdown file a verdict
    error."""
    with pytest.raises(verdict.NoVerdict):
        verdict.parse('# R\n\n' + FENCE + 'text\n$ make precommit\n')


def test_nothing_partial_survives_a_bad_row():
    """The docstring's own claim, attacked: a block whose FIRST row is perfect
    and whose second is not returns no findings, not one. A yield number built
    from the rows that happened to parse is the write-side sin in a report."""
    error = malformed(block('| W1 | WARNING | landed 3a42f19ad |',
                            '| S3 | WHATEVER | rejected: no |'))
    assert not hasattr(error, 'findings')
    assert 'unknown severity' in error.why


def test_the_exception_carries_the_line_number_and_the_line_for_every_refusal():
    """The contract the caller maps to exit 2. A refusal without them sends the
    reader to grep a 400-line record for a block they cannot describe."""
    text = block('| W1 | NOPE | landed 3a42f19ad |')
    error = malformed(text)
    assert error.lineno > 0
    assert text.split('\n')[error.lineno - 1] == error.line
    assert str(error.lineno) in str(error) and error.line in str(error)


# --- it is there: the four shipped definitions ask for the block --------------
def installable(name: str) -> str:
    """The body `install-agents` writes, read the way `install.py` reads it."""
    return resources.files(install.PACKAGE).joinpath(name).read_text(encoding='utf-8')


@pytest.mark.parametrize('name', REVIEWER_AGENTS)
def test_each_reviewer_shaped_definition_carries_the_block(name):
    """A parser for a block nobody is instructed to write always returns
    NoVerdict — so the instruction is half the feature, and it is pinned per
    file rather than once, because a rewrite drops one file at a time."""
    body = installable(name)
    assert 'verdict: SHIP-WITH-FIXES' in body, f'{name} shows no verdict: line'
    assert HEADER_ROW in body, f'{name} shows no {HEADER_ROW} header'


@pytest.mark.parametrize('name', REVIEWER_AGENTS)
def test_each_definition_names_the_closed_verdict_set_and_the_dispositions(name):
    """The agent picks from the set this module accepts. A definition listing a
    verdict the parser refuses ships a record that exits 2 on arrival."""
    body = installable(name)
    for value in verdict.VERDICTS:
        assert value in body, f'{name} does not offer the verdict {value}'
    for kind in verdict.DISPOSITION_KINDS:
        assert kind in body, f'{name} does not name the disposition {kind}'


@pytest.mark.parametrize('name', REVIEWER_AGENTS)
def test_the_example_block_in_each_definition_is_one_this_parser_accepts(name):
    """The strongest form of the assertion above: the shipped example is fed to
    the shipped parser. A definition demonstrating a block the parser rejects
    is how every review record in a consumer starts exiting 2."""
    parsed = verdict.parse(installable(name))
    assert parsed.verdict == 'SHIP-WITH-FIXES'
    assert {f.disposition_kind for f in parsed.findings} == set(verdict.DISPOSITION_KINDS)


def test_the_paragraph_is_identical_across_the_four_definitions():
    """One shared contract, four files. Four near-copies drift, and the drift
    lands as a record the report cannot read months later."""
    marker = 'verdict: SHIP-WITH-FIXES'
    excerpts = set()
    for name in REVIEWER_AGENTS:
        body = installable(name)
        start = body.rindex('### ', 0, body.index(marker))
        excerpts.add(body[start:body.index(marker) + len(marker)])
    assert len(excerpts) == 1, 'the verdict-block paragraph has drifted apart'
