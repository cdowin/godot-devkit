# Feature Review — 0.22.0/review-record-shape

**Commit range:** `236af3f..HEAD` (`2250e76`, `d923103`, and the two
`pm(0.22.0/review-record-shape)` closes).
**Reviewer:** independent, cold. Adversarial input, run — no diff-reading (SDLC § 5).

## What I ran

- **Parser matrix, 28 hostile records** through `verdict.parse`, each written
  against a "never" / "only" / "exactly one" the module's docstring states:
  two blocks separated by prose and two adjacent → `MalformedVerdict` naming the
  second block's line and the first's; an unfenced `verdict:` → `NoVerdict`; a
  `**Verdict: SHIP**` prose line → `NoVerdict`; a fence that never closes over a
  verdict → `MalformedVerdict`; an unclosed NON-verdict fence after a good block →
  parses (correctly — it is `check doc`'s finding, not this one's); tilde fences,
  info strings, 3-space indents, CRLF, `VERDICT:` and `| ID | SEVERITY |` uppercase
  → all parse; a markdown separator row `|---|---|---|` → refused as an unknown
  severity; four columns → refused; a header-less block → refused; an unknown
  severity → refused; `landed` with 6 hex, 45 hex, and a non-hex word → refused;
  `rejected:` with an empty reason → refused; `deferred:` with four segments and
  with a space → refused. **28/28 landed where the docstring says.** Detection is
  generous and acceptance is strict, as claimed, with the one exception at R3.
- **`caused_by` refusal matrix:** `pm new bug --caused-by` with a story id, a
  milestone id, a non-existent feature, `../../../etc/passwd`, `0.1/*`,
  `/etc/passwd`, and empty → 7/7 refused, **and the bug file was not written** in
  any of them (directory listing compared before and after).
- **D1, both readers, live:** a bug carrying `caused_by: 0.1/ghost` →
  `pm validate` prints `  INVALID  …: caused_by '0.1/ghost' resolves to nothing (its
  milestone IS in the tree)` and `check pm` prints the same claim with `  DRIFT  `
  and `[check:pm] FAIL`. Both readers see it; neither passes what the other fails.
- **The retire case, which the story does not name:** a bug whose `caused_by` names
  a feature in a milestone that is later retired. Before retire: `VALID — 5 grain(s),
  2 ref(s)` / `PASS`. After `pm retire`: `VALID — 3 grain(s), 2 ref(s) (1
  UNVERIFIABLE — the ref names a milestone no longer in the tree; git history is the
  archive)`, exit 0, and `check pm` the same. This is the case I expected to find a
  false red in and did not — an escape naming a retired feature does not turn a
  consumer's pre-push red, and the count says what could not be checked.
- **`caused_by` into `zz_archive/`:** accepted at write time and resolved at
  validate time, consistently by both. Right answer — the feature that caused an
  escape is usually not the current one.
- **The four installed definitions, parsed:** `reviewer.md`, `simplifier.md`,
  `milestone-reviewer.md`, `verification-reviewer.md` and this repo's own
  `.claude/agents/code-reviewer.md` — **all five parse to `SHIP-WITH-FIXES` with the
  same three findings**, so no installed agent ships an example its own parser
  rejects. Every severity token each file names its author is in `SEVERITIES`; the
  verdict-block paragraph is byte-identical across all five.
- **Gate mutation, 5 mutants** in `verdict.py` against `test_verdict.py` and the
  suite: second block accepted; unknown severity accepted; hash length unbounded;
  unterminated fence ignored; `deferred:` grain id unchecked. **5/5 CAUGHT.**
  (30/30 across the whole milestone — see the `ledger` record.)
- **Suite:** `test_verdict.py` 85 passed, `test_pm_gate.py` 4 passed,
  `test_pm_scaffold.py` 9 passed. Full suite 1371 → 1397 (my +4 are in the `ledger`
  record's fix; none of this feature's code changed).

## Fixed in place

Nothing. Every finding below is either a contract decision that is not mine to make
or a documentation delta.

## Findings

### MAJOR

**R1 — three of the four installed definitions instruct their author in two
mutually-exclusive verdict vocabularies, twenty lines apart.**

- `src/godot_devkit/repo/installables/reviewer.md:90` —
  `**Verdict:** PASS | PASS WITH WARNINGS | FAIL (has CRITICALs)`
- `src/godot_devkit/repo/installables/reviewer.md:110` —
  ``verdict:` is exactly one of SHIP, SHIP-WITH-FIXES, HOLD, RELEASE-SAFE,
  RELEASE-WITH-FIXES or NOT-RELEASE-SAFE`
- `src/godot_devkit/repo/installables/milestone-reviewer.md:83` —
  `**Verdict:** EXECUTION-READY / READY-WITH-FIXES / NOT-READY`
- `src/godot_devkit/repo/installables/milestone-reviewer.md:110` — the same
  SHIP/RELEASE sentence
- `.claude/agents/code-reviewer.md` carries the same pairing.

Repro:

```text
$ PYTHONPATH=src python3 -c "
from godot_devkit.repo.pm import verdict as V
for v in ('PASS','PASS WITH WARNINGS','FAIL','EXECUTION-READY','READY-WITH-FIXES','NOT-READY'):
    try: V.parse('\`\`\`\nverdict: %s\n| id | severity | disposition |\n\`\`\`\n' % v)
    except Exception as e: print(v, '->', type(e).__name__)"
PASS -> MalformedVerdict
PASS WITH WARNINGS -> MalformedVerdict
FAIL -> MalformedVerdict
EXECUTION-READY -> MalformedVerdict
READY-WITH-FIXES -> MalformedVerdict
NOT-READY -> MalformedVerdict
```

`verdict.py:46-51` states the invariant this violates: *"A grade an installed agent
emits and this module rejected would be a parser that refuses its own tooling's
correct output."* That check was made for the SEVERITY axis (I re-verified it: every
severity all five files name is in the closed set) and not for the VERDICT axis. The
outcome is loud rather than silent — exit 2, not a wrong number — so it is not
rule 4's cardinal sin. It is still the single most likely way a real pass produces a
record the report cannot read, in a feature whose whole point is that it can.

I did not fix it because both resolutions are contract decisions with different
costs and neither is obviously right. Widening `VERDICTS` makes "the verdict of a
pass" mean three different scales the report would have to reconcile. Aligning the
prose templates onto the SHIP/RELEASE family changes four installed agents' output
shape, and `verdict.py:19-25` argues deliberately that the prose line and the block
are *different* claims — the fence is what separates the narration from the counted
fact. If that separation is intended, then the fix is a cross-reference sentence in
each template saying so, which is a wording change the orchestrator applies. The
architect picks.

**R2 — there is no disposition for a fix that landed in place and is not yet
committed, which is the reviewer's own position in this SDLC.**
`src/godot_devkit/repo/pm/verdict.py:122-123` (`_LANDED`), and the paragraph at
`installables/reviewer.md:110-132` that mandates the three forms.

`landed` takes a 7–40 character hex hash and nothing else. SDLC § 2 says builders
"never commit" and the orchestrator "commits per feature by explicit pathspec";
§ 5's close protocol has the cross-cutting reviewer "land wrap-up fixes" and the
orchestrator commit and re-green afterwards. So at the moment the record is written
— which the reviewer contract says is before going idle — the hash does not exist.
Verified:

```text
| W1 | WARNING | landed in place, uncommitted |   -> MalformedVerdict
| W1 | WARNING | landed inplace |                 -> MalformedVerdict
```

The three available outs are all wrong. Invent a plausible hash: a disposition
nobody can follow up, which is the exact thing `HASH_MIN_LEN`/`HASH_MAX_LEN` exist
to prevent. Write `rejected:` for a fix that landed: a lie in the column the report
counts. Omit the row: the yield number under-counts, silently, for precisely the
findings that were acted on — and "findings by severity and disposition" is the
first of the report's five sections. I took the third option in all three records
this pass and said so in prose, which is the least-bad of three bad choices and is
not a mechanism.

The feature's ship criterion is *"`pm ledger report` computes yield from a record
written by the installed agents with no hand editing"*. Under R2 that criterion is
met only for passes where every fix was committed by someone else first. A fourth
form — `landed: in place` with no hash, or a `pending` kind — is a small parser
change and a paragraph, but it is a vocabulary decision, so it goes to the architect
rather than into this pass.

### WARNING

**R3 — a block whose `verdict:` is not its FIRST line is reported as "no verdict",
which is the miss the module says it refuses.** `verdict.py:219-221`
(`_opens_a_verdict` matches `rows[0]` only).

A fenced block whose four lines are, in order: `some note`, `verdict: SHIP`,
`| id | severity | disposition |` — that is, the shape with one stray line above the
marker — raises `NoVerdict`, not `MalformedVerdict`. (Written out rather than shown
as a fence, because a nested fence in this record would itself be a second block.)

`verdict.py:32-35` says the alternative to strictness is *"quietly reporting 'no
verdict' over a block that was nearly right"* and calls that rule 4's read-side sin.
A fenced block that carries a `verdict:` line and a well-formed header row, with one
stray line above them, is exactly a block that was nearly right — and the report
will list that record beside the ones nobody finished, which are a different fact
needing a different answer from a human.

I did not fix it: making detection scan the whole block would make every fenced
`verdict:` example in a document — including the five agent definitions, and the
repro above — a candidate block, and the second-block refusal would then start
firing on prose that merely quotes the shape. The narrow fix is to detect on the
first line as now, and additionally refuse when a block's first line is a
well-formed header row (`| id | severity | disposition |`) with a `verdict:` line
under it. That is a real behaviour decision about the surface, not a local
correction, so it is the architect's.

### MINOR

**R4 — the story names an installable that does not exist.**
`pm/roadmap/0.22.0-telemetry/features/review-record-shape/stories/the-verdict-block.md`
and `features/review-record-shape/feature.md` both say `install-agents` updates
`reviewer.md`, `simplifier.md`, **`code-reviewer.md`**, `milestone-reviewer.md`.
There is no `installables/code-reviewer.md`, and `install.py:90-108`'s roster has no
such entry, so `install-agents` cannot ship or update it. The fourth definition as
built is `verification-reviewer.md`, which is what `verdict.py:14-17` names.
`.claude/agents/code-reviewer.md` exists but is this repo's own local agent, outside
`install.PLANS` and therefore outside
`test_install.py:562`'s byte-currency assertion.

The code is right and the story is stale; this is a doc delta, not a defect. It
matters because a reader auditing "did all four get the paragraph?" against the
story would look for the wrong file and find nothing.

### NIT

**R5 — a `rejected:` reason containing `|` is unrepresentable.**
`verdict.py:224-244`. `| W1 | WARNING | rejected: a|b |` splits into four cells and
raises `MalformedVerdict` about the cell count, which is a confusing message for the
actual cause. No escape exists. Reasons are free prose written by an LLM and a pipe
in one is not exotic. One sentence in the paragraph ("no `|` in a reason") costs
nothing; the alternative is a reviewer meeting a cell-count error it cannot explain.

## Passed

- The parser's stated split — generous detection, strict acceptance — is real, and I
  could not find a near-miss it guessed at. `MalformedVerdict` carries the line
  number and the offending line every time, and nothing partial is returned from a
  block with one bad row (verified: a block with a good row before a bad one yields
  no findings at all).
- The fence-as-separator argument at `verdict.py:19-25` earns its length. A prose
  `**Verdict: RELEASE-WITH-FIXES**` is correctly `NoVerdict`, which is the one
  behaviour that keeps the report off the record's narration.
- D1 is right and is implemented as it reads: one reader does not pass what the
  other fails, and the shared `_check_ref_ids` path is why. The `UNVERIFIABLE` count
  after `retire` is the best thing in this feature — it is rule 4 answered honestly
  on a case the story never mentions.
- `--caused-by` writes nothing on an unresolvable ref. Seven refusals, seven
  unwritten files.
- The five agent definitions all carry a byte-identical verdict paragraph and all
  parse. The `install-agents` byte-currency test would catch a local edit to the
  four that ship.

## Not verified

- `make milestone`, `make gates`, `make smoke` — not run.
- `pm ledger report`'s consumption of these blocks: a live peer owns `report.py`.
  I proved records parse; I did not prove the report aggregates them correctly, and
  R2 is the finding that lands hardest there.
- Whether a real reviewer agent, given `reviewer.md` cold, actually writes a
  parseable block. I proved the file's example parses, not that the instruction
  produces one — this record is a sample of one, and R1 and R2 are what that sample
  hit.
- `install-agents --force` against a consumer with locally-edited agents.

## Note on the verdict block

Nothing was fixed in place for this feature, so every finding above has a row below.
R1, R2 and R3 are marked `rejected` in the sense the vocabulary defines — I raised
them and chose not to act — and the reason column says why each is the architect's
call rather than a local correction. R2 is the finding about that column itself.

```text
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| R1 | MAJOR | rejected: widening VERDICTS and re-wording four installed templates are both contract decisions, not local corrections |
| R2 | MAJOR | rejected: a fourth disposition form is a vocabulary decision for the architect; I took the omit-the-row option and said so in prose |
| R3 | WARNING | rejected: changing detection would make every quoted example a candidate block; the narrow fix is a surface decision |
| R4 | MINOR | deferred: 0.22.0/review-record-shape |
| R5 | NIT | rejected: one sentence in the shared paragraph, applied with R1 |
```
