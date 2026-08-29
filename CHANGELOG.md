# Changelog

## Unreleased

**A milestone now has release notes, and they are a log the tooling writes.** `changelog.md` joins
`milestone.md` / `handoff.md` / `decisions.md` / `review.md` as a canonical **milestone** file slot —
not a feature one, because a release is a milestone and a feature contributes to it through the
entry's `Evidence:` pointer. It is **durable**, and unlike the transient `review.md` it is *not*
skipped on a `done` grain: a closed milestone is exactly when its notes matter most.

**The entry is deliberately small.** Two required fields, and no vocabulary to learn:

```
## C1 — 2026-08-29 — the hub remembers where you parked
**What:** Your loadout is where you left it when you come back to the hub.
**Evidence:** `64e89ad5b`
```

`**What:**` is one sentence a player would recognise; `**Evidence:**` is a reference — a commit hash,
a `path[:line]` or a number — because a changelog entry with nothing behind it is a rumour. The
*reasoning* behind a change is a decision and stays in `decisions.md`; a changelog carrying it is a
commit log with a nicer name.

**`pm changelog <milestone-id> --what … --evidence … [--title …]`** appends one. It is the same
machinery as `pm decide`, not a second copy of it: the same entry parser, the same fence and HTML-
comment masking out of `core.markdown.fenced_flags`, the same ordinal allocator (an empty log starts
at `C1`, a log already numbering `R7` keeps numbering `R`), and the same load-bearing property — the
composed entry is **re-parsed through the gate's own predicates** before anything is written, so the
writer refuses exactly what the gate reports and the two cannot drift. Every refusal leaves the log
**byte-identical**, including a CRLF log's line endings. `--title` defaults to `--what`, and a
`--what` too long to be a title is refused naming the flag that fixes it rather than silently
truncated.

**`pm changelog --render [--milestone <id>]`** writes the union of every milestone's log to
**stdout**, newest release first — a render the consumer redirects, so every count, skip and
half-written entry goes to stderr where redirecting the document cannot swallow it. Ordering is
deterministic by construction: milestones by **declared version compared component-wise**, entries in
the order their append-only log holds them. It compares through the same `version_key` `prune`'s
lag-by-one already uses, and that comparison is the point of the feature — sorted as strings descending,
`0.90.3, 0.9, 0.10, 0.1` publishes `0.9` as newer than `0.10`, wrong in the one place a reader trusts
a changelog most.

**`pm decisions <grain-id>`** is the read half of the contract `pm decide` writes: that grain's
entries, parsed and deterministic, with a milestone printing its own log **and its features'**.
Both reads exist so that answering "what shipped in / what did we decide in milestone xyz" is never a
`find` piped to a `grep` — that is a second parser with none of the fence and comment handling, and
it disagrees with the gate on exactly the logs where it matters.

**Two new opt-in rules, both OFF by default.** **D15** holds every `changelog.md` entry to the schema,
and is the *same function* as D12 over different data — same census, same case-variant reporting, same
unterminated-fence and unclosed-comment defects, and a `changelog_grandfather` ledger with D12's
per-entry `"<path>:N"` cap so a consumer's legacy text can stay put while every NEW entry must
conform. Like D12's, that ledger may only **shrink**: an exemption suppressing nothing, a cap reaching
past the end of its log, and a line naming no log each FAIL. **D16** fails a `done` milestone whose
changelog is missing, empty, or holds only entries D15 already reports — D15 asks whether what is
written conforms, and a conforming *empty* log satisfies it forever. D16 reads the same ledger D15
does, so an entry D15 has been told to accept is never one D16 rejects.

**Migration.** Adding a canonical slot means D13 reports every existing consumer milestone as missing
`changelog.md` until it is re-scaffolded, and the fix is the idempotent `pm new milestone` — verified
across a 22-milestone consumer tree: one pass creates exactly 22 `changelog.md` files and changes
nothing else, and the passes after it are clean no-ops with every file byte-identical.

**Internals.** The decision machinery is now schema-parameterised rather than duplicated: one
`LogSchema` value describes each log's field list, ordinal prefix, file name and ledger key, and one
implementation of the parser, the validator, the writer, the ledger parser and the gate serves both.
The `decision_*` names generalised to `log_*` / `entry_*` accordingly.

**The PM tree now has a prose budget, and it is a ratchet.** Everything written into a PM tree is
grep-reachable, so every line of prose is context some future agent pays for — the scaffolding
should not be twice the size of the thing it scaffolds. **D17** caps a story, a `feature.md`, a bug,
a feature's `decisions.md` and a milestone's `changelog.md`, with two finding classes: **OVERCAP**
(over its grain's cap and not on the ledger) and **GREW** (on the ledger and larger than its recorded
ceiling). **D18** is the other half: a `done` milestone still carrying its **raw decision trail**.
Milestone close evidence is pointers — "a line and a link" — so a done milestone with a 1,600-line
trail was not closed, it was abandoned, and D18's threshold comes from that rule rather than from any
distribution.

Both live **inside `check pm`**, not in a gate of their own, because the ledger needs the same grain
vocabulary D13/D14 already own — splitting them would mean two implementations that have to agree
about what a grain document even is. The walk reuses `milestone_dirs` / `feature_files` /
`story_files` / `dir_entries`, and D14's recursive bug walk became a shared `bug_files`, so a bug the
lifetime rule can see is never one the prose cap cannot. Both are **OFF by default**, like D8–D16.

**`[pm] prose_grandfather` is a DEBT ledger — its length is the metric and it may only ever shrink.**
Same `"<path>:<N>"` shape `decision_grandfather` and `changelog_grandfather` already use (one parser
serves all three), with the number reading as a **line ceiling** and being **required**: an entry
with no ceiling would be a permanent uncapped pass, which is the one thing a ratchet cannot have. The
same integrity rules apply — an entry that suppresses nothing, a ceiling reaching past the end of its
file, and a line naming no document each **FAIL**. **`pm prose-ledger`** regenerates the block to
stdout and **REFUSES to raise** an existing ceiling; without that refusal every growth would be
absorbed by a regeneration and the gate would be decorative. A document back inside its cap is
dropped rather than re-recorded, so what it prints is gate-clean by construction.

**Three things that are load-bearing and easy to lose.** *One:* a **milestone's own `decisions.md` is
not capped while its milestone is open** — it is the append-only autonomous-mode trail by design, and
capping it fights the process; only a **closed** milestone's raw log is a finding, which is D18.
*Two:* the **tool-mandated instruction header is excluded from every line count**. D13 asserts that
header is present, so it is a constant an author cannot trim, and counting it against a prose budget
would make the budget uncompliable and silently shrink every cap by two — `doc_lines` drops it for
**every** slot header, not just the decisions one, off the same `SLOT_HEADER` table D13 reads.
*Three:* **the caps are config, not constants** — `story_lines_max` (120), `feature_lines_max` (200),
`bug_lines_max` (125), `decisions_lines_max` (150), `changelog_lines_max` (150) and
`closed_log_lines_max` (60). The defaults sit at roughly the p90 of **one** consumer's measured
distribution, so the median document is untouched and only the outliers must shrink; they are that
consumer's numbers, not a law, and a cap under 1 is a config error rather than a finding.
`changelog.md` gets its own cap class because it accumulates by design exactly as a decision log
does.

Verified against that consumer's live 45,849-line corpus with its 58-entry ledger translated into the
config form: the same 599 documents and the same 45,849 lines its own scanner measures (printed as
45,802 under D17 plus the 47-line closed log under D18, each rule's population beside its own
verdict), and the same zero OVERCAP / GREW / CLOSED-LOG findings it reports. The one difference is deliberate — devkit's shrink-only ledger rule reports the single entry
whose document has since fallen back inside its cap, and dropping it leaves 57.

**A too-short reference is no longer called prose.** `--evidence aaa111` is a real commit hash git
printed one character short of the seven this accepts, and the refusal said it "is prose, not a
reference" — wrong about the cause and naming nothing the author could do. It now says how many
characters it got, states the minimum, and prints the `git rev-parse --short=7` that lengthens it.
One predicate behind both writers and both gates, so `pm decide`, `pm changelog`, D12 and D15 all say
the same thing. Real prose is still called prose, including a sentence whose first bad word happens
to be hex.

## v0.13.0 — 2026-08-29

**One uniform grain structure, all lowercase.** Every milestone and feature dir carries the same
slots, and the split that makes it worth having is durable vs transient:

```
<milestone>/                       <feature>/
  milestone.md                       feature.md
  handoff.md                         —          (milestone-only)
  decisions.md                       decisions.md
  review.md                          review.md
  bugs/                              —          (milestone-only)
  design/                            design/
  features/                          stories/
```

`decisions.md` is **durable** — appended during the grain's life, it survives close and collapses to
pointers when a milestone closes. `review.md` is **transient** — simplifier and reviewer both append,
and it is **deleted at close** with anything durable promoted into `decisions.md` first.

**`pm new milestone` and `pm new feature` are now idempotent**, which is how a consumer migrates. Run
against an existing grain they fill the missing slots, rename a slot present under another case, and
leave every existing byte alone; `<name>` is optional there, since the name only ever mints the
directory. The case rename goes through **`git mv --force`** when git tracks the path, and through a
temp name when it does not. Both halves are load-bearing and neither is optional: macOS is
case-INSENSITIVE, so `open('decisions.md', 'w')` next to an existing `DECISIONS.md` truncates the
very content the migration exists to carry forward — and git's default there is
`core.ignorecase = true`, under which a worktree-only rename leaves the INDEX on the old spelling.
The worktree says `decisions.md`, `git ls-files` says `DECISIONS.md`, and an explicit `git add` of
the new name stages nothing: the migration goes green on the laptop, gets committed, and CI on Linux
checks out the old name with D13 reporting every renamed grain missing and D12 scanning nothing. If
git tracks the path and refuses the move, the scaffolder **refuses too**, printing the exact command
— a half-done rename is the one outcome worse than none. A file slot that exists as a DIRECTORY is
likewise refused rather than crashed, because exit 1 is reserved for findings; that refusal reads the
KIND of every spelling, not just the canonical one, so a `DECISIONS.md/` directory is refused where a
name-only variant scan would have queued it as a rename, renamed it, and then opened it as a file.
A slot that is a SYMLINK is refused for the same reason from the other side: a verb asked to fill
THIS grain does not follow a link and rewrite a file outside it.

Every refusal the grain can raise is decided **before the first rename runs**, so `nothing was
written` is a claim about the whole grain rather than about the slot the refusal happened to land on:
the slot order is `milestone.md, handoff.md, decisions.md, review.md`, and a refusal keyed on
`decisions.md` used to leave `HANDOFF.md -> handoff.md` on disk and staged, where it rides out on the
next commit under somebody else's message. That now covers a leftover `.pm-case-rename` temp file
too — it is in the directory listing, so it is decidable in the pre-pass, and deciding it inside the
moving loop was the last way an earlier slot's rename reached disk under a "nothing was written".
**And the write phase is pre-decided the same way**: every template the grain will need is loaded and
DECODED, and every existing doc due a header prepend is proved writable, before the first byte lands
— a latin-1 byte in a project's `template_dir` and a read-only legacy `handoff.md` both used to
escape as tracebacks with two slots already created. What genuinely cannot be inspected in advance —
git declining a `git mv --force`, a mode changed underneath the run — becomes a refusal that names
what already landed instead of claiming nothing did, and says whether a landed rename was **staged by
`git mv`** or only moved on disk: advice to unstage a worktree-only rename sends an operator to a
`git status` that shows them nothing. The two halves of that composed sentence no longer contradict
each other either: the inner refusal states what became of ITS OWN file (*its content is untouched,
still at …*) and the NOTE states what became of the ones before it, where one message used to say
both `nothing was written` and `1 earlier rename(s) already landed`.

**Exit 1 is a finding, not a stack trace, on every path a rename takes** — the last two paths out
from under that are closed. A rename writes the DIRECTORY, not the file, and the pre-pass checked
only the file: a `0555` grain dir holding a `0644` `DECISIONS.md` passed every inspection and came
out of `os.rename` as a raw `PermissionError` traceback. Directory writability is trivially inspectable, so it is inspected,
and anything still escaping the two-step temp rename becomes a refusal that **names where the bytes
actually are** — the second step failing parks the log at `decisions.md.pm-case-rename`, which no
later run looks for, so a message saying only that the rename failed left an operator hunting for
content sitting right there. A SYMLINK in a file slot is also identified as a link before its kind is
read: `is_dir()` follows the link, so one pointing at a directory got the DIRECTORY refusal — the
right answer with advice aimed at the wrong problem. Measured on
scratch copies of both consumers, with a second full pass changing nothing:

| | grain dirs | slots created | renamed | headers restored |
|---|---|---|---|---|
| nullbound | 158 | 469 | 60 | 60 |
| trail | 32 | 132 | 4 | 4 |

**Each shared doc opens with a one-line instruction**, and D13 asserts it is still there. `.claude/
rules/*` never reach a dispatched subagent — measured — so a file's own first line is the one
delivery channel with a 100% hit rate for the action its reader is about to take. Each line is an
instruction for that action, not an explanation of what the file is:

- `decisions.md` — *Append with `godot-devkit pm decide <grain-id>` — never by hand; the command
  stamps the date and the next ordinal.* It points at the command rather than restating D12's four
  fields: the gate already owns that schema, and a second copy in 178 files is a drift generator.
- `review.md` — *Transient. Deleted at close — promote anything durable into decisions.md first.*
- `handoff.md` — *Cold-start only. Never restate what `pm status` computes.*
- `milestone.md` / `feature.md` get none. V1–V6 already validate their frontmatter.

**New — `pm decide <grain-id> --chose … --over … --because … --evidence … [--title …]`.** Appends a
D12-conforming entry to that milestone's or feature's `decisions.md`, stamping the two things authors
get wrong: the ISO date, and the next ordinal (in the log's OWN id prefix, so a tree numbering `M27`
keeps numbering `M`). `--over` is **required** — a decision with no rejected alternative is a
description, and a required flag enforces that at write time, where the author still remembers the
alternative, instead of at gate time weeks later. Every value is validated by re-parsing the composed
entry through D12's own predicates, so the writer refuses exactly what the gate would report and the
two cannot drift; prose evidence, an over-long value and a `--chose` too long to serve as the header
title are all refused with the log left byte-identical.

**`check pm` D11 is rewritten around the co-located `review.md`: a `done` grain must not have one.**
No `review_dir`, no filename matching, no exemption, no ambiguity. What it replaces resolved a
findings-doc FILENAME back to the grain it "named", and a real corpus got that exactly backwards — on
trail it resolved 6 of 123 docs, and those 6 were precisely the durable ones `reviewed:` already
points at, so after the previous release's fixes trail reported **0 findings over 123 stale docs**.
Anchoring the match could only ever remove matches. `grain_named_by()` and the `KNOWN_DEFECT` test
that pinned its substring bug are gone. The rule-4 loudness stays: a tree with no `done` grain is
NAMED in the output rather than passing in silence, and the census carries the done-grain count.

**`check pm` D13 — the canonical structure.** Every grain dir carries exactly its slots: **missing is
drift AND extra is drift**, and each templated file must still open with its instruction header so
the breadcrumb cannot rot. The extra half is the one that earns the rule — `plans/`, `findings/`,
`AUDIT-REPORT.md`, `audit-prompt.md` and `DELETED-SCENARIO-LEDGER.md` all exist in a real tree
because no slot was scaffolded *and* nothing flagged the invention, and a missing-only check leaves
every one of them there forever. Existence is decided from a directory LISTING, never `Path.is_file`:
macOS resolves `decisions.md` to an existing `DECISIONS.md` and Linux does not, so the same tree
would be clean on a laptop and drifting in CI. Directory slots are permitted, never required — git
does not store an empty directory, so requiring `design/` would mean 178 placeholder files.
`review.md` is required exactly while the grain is open and forbidden once it is done, D11 owning
that half, so a closed grain is never told both to have it and to delete it.

**`check pm` D14 — bug lifetime.** A bug lives in the milestone that will FIX it: `caught_in:` keeps
the provenance, `fix_milestone:` names the decision, and the directory is that decision made real. An
**open bug under a `done` milestone** is therefore drift, and not cosmetically: `prune`'s lag-by-one
deletes a done milestone's directory the moment the next one closes, so those bugs are already
scheduled for deletion. This rule is what makes prune safe by construction. It also reports a bug
status outside `[pm] bug_states` — D4 does not cover bugs, so a typo would otherwise read as "closed"
and pass in silence. Two new config keys, `bug_states` (default `open`/`fixed`/`closed`) and
`bug_open_states` (default `open`); naming an open state the vocabulary lacks is a config error.
The bug census is **recursive and case-insensitive in the extension**: a `glob('*.md')` saw neither
`bugs/<topic>/<bug>.md` nor `<BUG>.MD`, and since `bugs/` is a permitted slot that D13 never descends
into, both were invisible to every rule at once while the census printed the smaller number without
saying it had looked less far. D14 is the rule that stops `prune` deleting an open bug along with its
done milestone, so one that undercounts is not a weaker safety net — it is a false one.

D11, D13 and D14 are OFF by default like D8–D12 — a tree predating the canonical slots is missing
most of them, and a rule that turns a consumer red on upgrade day is unshippable. Scaffold first,
then hold the line. Measured on scratch copies:

| after scaffolding | D13 missing | D13 extra | D13 header | D11 stale | D14 open-bug-under-done |
|---|---|---|---|---|---|
| nullbound | 0 | 12 | 0 | 0 | 28 of 91 bugs |
| trail | 0 | 10 | 0 | 0 | 8 of 13 bugs |

The residual extras are the genuine inventions a human has to place: `plans/` (8 + 10),
`AUDIT-REPORT.md`, `audit-prompt.md`, `findings/` and `DELETED-SCENARIO-LEDGER.md`.

**`check pm` D12 — the decision-record schema.** Every `## <ID> — <ISO date> — <title>` entry in a
`decisions.md` carries `**Chose:**` / `**Over:**` / `**Because:**` / `**Evidence:**`, in that order,
one per line, values <= 200 chars and the title <= 80. `Over:` is the load-bearing field — an entry
that cannot name what it ruled out is a description, not a decision — and `Evidence:` must be a
REFERENCE (a commit hash, a `path[:line]`, a number), never a sentence.

Entry DETECTION reads the entry's BODY, never only its title: a `##` heading is an entry if it
carries an id or a date **or** if any `**Word:**` field line appears beneath it. The field line is
the positive signal, and it is what a title-reading detector cannot see — this package's own retired
template told authors to write `## <short title>` with `**Decision:/Because:/Rejected:/Costs:**`
underneath, and against trail's live corpus a heading-only test called 8 of 9 real decision blocks
prose and passed the whole file, its single finding landing on the one heading that happened to
contain a bug id. A heading with neither an id/date nor a field line is prose and is never
schema-checked, so a log may open with a preamble. A CLOSED `<!-- -->` block is not in the log at
all, and neither is a TERMINATED fenced code block — both are text the entry parser steps over. Its
two edges are symmetric and both keep their live half: the opening line keeps what precedes `<!--`,
and the closing line keeps what follows `-->`, so a conforming `**Over:**` written after a spanning
aside is still read rather than failed for naming no rejected alternative.

**Neither marker may mask in silence.** An unclosed `<!--` suppresses nothing and is itself reported,
and **so is an unterminated code fence** — one stray ` ``` `, a `~~~` "closed" by ` ``` `, an
unbalanced three-backtick span leading a line. Either would otherwise mark every line after it
dead and D12 would print PASS over the entries it ate, which is the exact sin the comment scan
already refuses to commit; the fence masking added to stop a quoted `<!--` eating a log had reopened
it by the other route, silently, and `pm decide` then refused every append to that log forever with
`the composed entry does not parse as a decision entry`. A marker inside backticks or a terminated
fence is a marker being named, not a comment being opened.

**And `check doc` / `check agents` now answer an unterminated fence the same way**, because it was
the same defect wearing the other gate's clothes: their fence scan was a parity toggle, so an ODD
number of fence-looking lines dropped every remaining line of the document and the gate printed PASS
over them. Two dead claims that FAIL normally — `[check:doc] FAIL — 2 unresolved claim(s)` — became
`PASS — 1 doc(s), 0 unresolved claims` the moment one stray ` ``` ` was prepended above them, and
`check agents` did it too. `check doc` runs in `check all`; both run from each consumer's
`make check`. An unterminated fence now masks
nothing and is REPORTED (`malformed doc(s)` / `MALFORMED`) while a terminated one still masks, since
a rule file quoting the CLI's own refusal is documenting it. **One scanner** answers where the fences
are — `core.markdown.fenced_flags`, which D12's own mask now calls rather than keeping a second copy
— so the two families cannot drift into disagreeing about which lines a document even has. That also
brings the CommonMark rules the toggle never had: a closing fence must be the same character, at
least as long and carry no info string (so `~~~` no longer "closes" a ` ``` `), and a fence indented
four spaces is INDENTED CODE — a doc showing how a fence is written no longer opens one. Both
censuses now print **how much they skipped** (`22 doc(s), 223 fenced line(s) skipped`): the count was
of FILES, and files are not what a fence hides.

Legacy logs migrate through `[pm] decision_grandfather` — `"<path>"` exempts a whole log,
`"<path>:<N>"` only its first N entries — whose size the gate PRINTS every run and which may only
shrink: an exemption that suppresses nothing, a cap reaching past the end of its log, and a line
naming no log all FAIL.

**D12 prints its census — `N decision log(s), M entry/ies` — and carries both into the summary
line,** the way D11 prints its done-grain count and D13/D14 print theirs. Without it "scanned 58 logs
/ 294 entries", "scanned 1 log" and "scanned 2 logs / 0 entries" printed identically, which is what
kept the two defects above invisible. The log census itself comes from a directory LISTING with an
EXACT-name comparison, never `rglob('decisions.md')`: a glob whose final segment holds no wildcard
resolves through `Path.exists()`, so macOS answers an on-disk `DECISIONS.md` with the path
`x/decisions.md` — a path that does not exist, a `decision_grandfather` key authorable on exactly one
platform, and, once ONE log of a tree has been migrated, a non-empty list that silences the
scanned-nothing guard while every other log goes unopened (57 of nullbound's 58, carrying 1,467
violations, printed `PASS` and exit 0). A case-variant log is now REPORTED, never folded in; a log
that cannot be decoded is REPORTED rather than counted as scanned-with-zero-entries.

**`pm templates` no longer writes past a case variant.** It reads the target directory by exact name,
exactly as the template loader does, so a project holding a customised `DECISIONS.md` is told the
spelling to port it to instead of silently rendering from the packaged template — and the packaged
one is not written over it, since on a case-insensitive filesystem that write would truncate the
customisation.

**`decision_grandfather = []` is now legal**, and means what it looks like. Every `[pm]` key is
written so that a repo declaring the documented defaults behaves identically to one with no
`devkit.toml`; this was the single key that broke that contract, exiting 2 with *remove the key to
take the default* because an empty list usually means the reverse of what it looks like (`git
ls-files` with no pathspec is the entire repo). It does not here: this key is a LEDGER of exemptions,
so `[]` and the absent key both say "none exempt".

**Known issues, all reported and none fixed here:** `pm decide --title` is not validated for a bare
`\r`; a `decision_grandfather` cap names the wrong entry when one is inserted above it;
`ScaffoldRefused` prints an absolute path rather than a repo-relative one.

Six more, all pre-existing and none introduced by this release; each was found by constructing the
input and running it, and none of them fires in either consumer today. A line opening with a
*balanced* three-backtick inline span is still read as a fence opener, so a later bare ` ``` ` masks
the region between with no defect reported — the one CommonMark rule `fenced_flags` still lacks (an
info string after a backtick fence may not contain backticks); a 20,000-case differential fuzz found
it as the only divergence class, and a mask-diff over all 170 live markdown files of both consumers
reported none differing. `check agents` skips a non-UTF-8 definition while its census still counts it
as scanned, which is the one reader in the package that masks in silence rather than reporting. D14's
recursion and case-insensitive extension were not carried to `stories/`, which is the same
never-descended slot shape `bugs/` was: a story under `stories/<subdir>/` or named `.MD` goes unseen
by D4 and can flip D2 into a false finding. `pm new` has a third path out from under "exit 1 is a
finding" that the rename fixes did not reach — `gdir.mkdir` on an over-long grain name or an
unwritable `pm/roadmap/`. D14 now reports any non-bug `.md` parked under `bugs/` (a `README.md`, a
`design/` note) as a bug with a bad status. And an unterminated fence inside a *closed* HTML comment
is reported as malformed, because fence flags are computed before comment spans.

**`tiles --region` and `tiles --at` can address the negative quadrants again.** `--region -2,-2,1,1`
died with `argument --region: expected one argument` on **every Python a consumer actually runs**:
argparse before 3.14 excuses a leading `-` only for a bare number, so a coordinate list read as an
option. Godot cell coordinates are routinely negative — `tile_map_data` signs x and y precisely
because the upper-left quadrant is ordinary — so `tiles paint` / `tiles erase` / `tiles --at` could
not reach a quarter of the plane on the declared 3.11 floor, while passing on 3.14. Fixed in the
argv, not the parser (the private matcher argparse keys on was rewritten in 3.14, and a tool whose
behaviour depends on which interpreter `uvx` picked is not a tool): a token opening `-<digit>` after
one of those flags is glued into `--flag=value`, on `sys.argv` as well as on an injected argv —
applying it only to the injected one left `python -m godot_devkit.godot.read.tiles … --at -3,-3`
exiting 2 on 3.11 while working on 3.14, which is the version-dependent tool the glue exists to not
be. Narrow on purpose — `--region --tile 9/0,0` is still a usage error with exit 2, and nothing after
`--` is touched. Predates v0.12.0. The suite now runs green on 3.11, 3.12, 3.13 and 3.14; it was
296 passed / 1 failed below 3.14.

**Breaking for a tree that has one:** the decision log is `decisions.md`, not `DECISIONS.md`, and the
handoff is `handoff.md`. `pm new milestone <id>` / `pm new feature <mid> <slug>` performs the rename.
`pm new feature` scaffolds `design/`, not `plans/`. The bug template carries `fix_milestone:` in
place of `fixed_in:`.

## v0.12.0 — 2026-08-28 — `tiles`, and a `check uid` that repairs what it reports

**New family — `tiles`.** A TileMapLayer serialises its entire map into one base64 property, so every
question about it is unanswerable by reading and every edit is a throwaway script. In nullbound that
stopped being theoretical: three agents hand-rolled the same twelve-byte cell decoder in a single
day, and painting a region took a bespoke encode/decode pass each time.

```
tiles <file.tscn> [--layer NAME] [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]
tiles paint <file> --layer NAME --region X0,Y0,X1,Y1 --tile SRC/AX,AY[/ALT]
tiles erase <file> --layer NAME --region X0,Y0,X1,Y1
```

The read side prints cell count, bounds and a tile-kind histogram per layer; `--cols`/`--rows` are
the edge-finders (per-column and per-row counts show where a wall stops or a lid is missing in one
screen), `--at` answers one cell, `--region` censuses a rectangle. The write side fills or clears a
rectangle and regenerates **only** that layer's `tile_map_data` assignment — its inline `;` comment
survives, surviving cells keep their position in the stream so the encoded value changes as little
as the edit does, and a paint that changes no cell writes nothing and reports `unchanged`. Both
verbs take `--dry-run`.

Refusals land before anything is written: an unknown layer, a name two layers answer to, a malformed
`--tile`/`--region`, a coordinate the format cannot carry, and a `tile_map_data` value that does not
decode — re-encoding a partial read would silently delete the tail of a map. A full node path beats
a bare name, so `Nested/WallLayer` stays addressable in a scene that also has a root-level
`WallLayer`.

**New flag — `check uid --fix`.** The gate already computes the should-be value and prints it in
every DRIFT line; `--fix` writes it, byte-surgically (only the `uid="…"` attribute on the drifted
line changes), and exits 0 so the re-run is clean. It will NOT invent: a ref whose target has no
`.uid` at all, and check 2's untracked sidecars, both need a uid that does not exist yet — those
stay findings and `--fix` still exits 1 when one is present. `--fix` on a clean tree is a no-op that
says so.

**On upgrade — three output/behavior notes a consumer may grep.** `check uid` gains one line in its
FAIL output when fixable drift is present (`  Fix: re-run with --fix …`); the DRIFT/UNTRACKED/PASS
line shapes are unchanged. `check <gate>` now REFUSES unrecognised trailing arguments with exit 2
instead of ignoring them — `--fix` on any gate but `uid` (including `check all`) is a usage error,
because a consumer that believes it asked for a repair and got a read-only run has been lied to. And
an undecodable `tile_map_data` now renders as `PackedByteArray (unparsed)` in `scene`/`scene-diff`
rather than a bounds line computed off a partial read; a well-formed value's line is unchanged.

Internally the twelve-byte layout moved into one codec (`godot/format/tilemap.py`) that the read
side, the write side and `scene`/`scene-diff` all share, along with the command-line spelling of a
tile and a region — so the two verbs cannot drift into two dialects of the same argument.

## v0.11.0 — 2026-08-28 — `pm milestone building` can place the branch

**New opt-in — `[pm] place_branch_on_building`.** `pm milestone building <id>` also checks that
milestone's `branch:` out in the **trunk** worktree — the exact state D10 asserts. Nothing was
putting it there before: the flip and the checkout were two steps a human did by hand, and the gap
between them is where most D10 findings actually came from. Off by default; a project that does not
run branch-per-milestone sees no change. The ordering is the contract — every refusal (no `branch:`,
a branch that does not exist, a branch another worktree holds, a dirty or unreadable trunk, an
unverifiable worktree listing) is decided **before** the flip, so a refused placement leaves
`milestone.md` byte-identical, while a checkout that fails **after** the flip exits 2 naming the
re-run: `pm milestone building <id>` is idempotent, and its already-building path re-runs the
placement. A milestone declaring a trunk branch places nothing and says so.

Note what it will NOT do: create the ref. A milestone declares *where* its work lives; it does not
authorize minting a branch, so a missing `branch:` target refuses and names the `git checkout -b` to
run.

`model.git_worktrees()` is the one parse of `git worktree list --porcelain` behind both readers —
`trunk_checkout_branch()` (D10) takes the trunk's branch, placement additionally needs to know
whether some other worktree already holds the branch, since git allows exactly one.

## v0.10.0 — 2026-08-27 — templates, field mutation, execution lists, agent drift

**On upgrade — two output changes a consumer may grep.** `check doc`'s verdict line moved from
`[doc_scan]` to `[check:doc]`, bringing the last gate onto the `[check:x]` shape rule 6 declares
contract. And a gate that scans **zero files now FAILs** rather than passing — `check shell` in a repo
with no `tools/` scripts changes from exit 0 to exit 1, as do `uid`/`tres`/`doc` on an empty census.
Both are deliberate: a gate that PASSes over nothing is the read-side cardinal sin, and four of eight
gates were doing it.

`[pm.scaffold.*]` is **replaced** by template files — set `[pm] template_dir`, run `pm templates`,
edit the markdown. It is now refused rather than ignored, so a stale config says so instead of
silently doing nothing.

**New gate — `check agents`.** An agent definition is prose, so nothing stops it describing a
workflow the tooling refuses. That drift is invisible until an agent follows the instruction and the
CLI says no — by which point a story sits in the wrong state and someone hand-edits around it, which
is the exact failure the PM CLI exists to prevent. It catches a `pm <grain> <verb>` the CLI has no
verb for, a `<state> -> <state>` the grain's graph rejects, a skill written as a flat `<name>.md`
instead of `<name>/SKILL.md` (which never loads as a skill), and project-configured `[agents]
forbidden` patterns.

Run against the two live consumers on first build it found **10 and 8 real findings** — including
agent definitions that had already been hand-corrected once, in files nobody had flagged. Grain
context decides legality: `review -> done` is the feature close edge and a refusal for a story, so
the checker reads the grain from the same line and censuses a line naming two grains as UNVERIFIED
rather than guessing. Precision over reach, as everywhere: a false FAIL gets the gate switched off.

**New — `pm vocabulary [--json]`.** The states, transitions and verbs, machine-readably. `check
agents` reads the model directly, but an external scanner should never have to scrape help text; a
tool that states its own rules in a parseable form is the only way a checker stays honest when those
rules change.

> **Not tagged.** Pin `v0.9.0` until this is released.

**On upgrade:** `[pm.scaffold.<grain>]` is **replaced** by template files. Point `[pm] template_dir`
at a directory, run `pm templates` to populate it, and edit the markdown — a project can now change a
grain's whole shape, not just its frontmatter defaults. Nothing else changes; `check pm` gains V6,
which is inert until a file actually carries a generated block.

**Templates are files.** `pm new` renders `milestone|feature|story|bug` from markdown templates with
`{placeholder}` fills, and a new milestone also gets a `HANDOFF.md` (the cold-start doc) and a
`DECISIONS.md` (append-only, one block per decision that would otherwise be re-litigated). A project
template wins over the packaged one **per file**, so overriding one grain does not make you responsible
for the rest. Unknown placeholders are left visible rather than blanked — a template is prose as well
as schema, and silently emptying something that merely looked like a placeholder corrupts the file.

**`pm get` / `pm set` / `pm claim` / `pm release` — frontmatter mutation as code.** Every hand-rolled
`sed` over frontmatter is a chance to rewrite a line ending, drop a field, or move a value that had
preconditions on it. These go through the same byte-fidelity-proven writer the transitions use.
`status` is **refused**: it is the one field with a transition graph behind it, and a settable status
would reopen the hole the CLI exists to close. `claim`/`release` finally put `owner:` — hand-edited
everywhere `status:` was not — behind a command.

**`pm sync` — the execution list, generated.** A milestone states the order its features are built in;
a feature states the order its stories are. Standing doctrine forbids hand-maintaining exactly this
("a second scoreboard, and it will lie") — and it lies because a *human* maintains it. Rendered between
markers from the same tree `pm status` reads, it is not a second source of truth but a view of the only
one, and **V6** fails when the two disagree. Order is phase, then dependency (Kahn, name-tiebroken so
the output is stable), then name.

The list is **opt-in per file**: a file with no block is not stale, or the gate would go red on every
tree that never asked for the feature. `pm sync` adds blocks; `pm sync --check` and V6 only judge the
ones that exist.

## v0.9.0 — 2026-08-27 — the pm family

**The first pinnable release of everything below.** `v0.6.0`–`v0.8.0` were in-tree
version bumps during one continuous build and were never tagged; their notes are kept
for the record, but `v0.9.0` is the tag that contains all of them. Do not try to pin
them.

### the guidance ships with the tool

**Hardening from the second pre-release review.** The headline was a false PASS in the *recommended*
configuration: `[pm] story_ordinal_prefix = true` was meant to teach V2 about a story file's `NN-`
prefix, and instead switched V2's story check off entirely — so a tree under the setting these notes
mandate reported VALID over a story id of pure garbage, with nothing saying the check was disabled.
It now strips the prefix and compares. Enabling the fix immediately surfaced two genuine id/path
inconsistencies in a consumer that the broken check had been hiding.

**An unreadable ref list is now a finding, not zero refs.** `depends_on` with a trailing comment, a
YAML block sequence, a bare scalar, or nested brackets parsed to `[]` — which reads as "no refs to
check", taking every ref out of V4's reach while reporting clean. Both consumers author only the flat
inline form the scaffolder mints, so nothing was live, but the failure shape was the wrong one.

**`pm new` refused nothing.** A slug was never slugified or validated, so
`pm new bug 0.1 ../../../../pwned` wrote outside the repo root and exited 0. Slugs are now one path
component or a refusal.

**Also fixed:** a bad `version_pattern` regex (or one with no capture group) tracebacked and exited
**1**, the findings code, for what is a config typo — it is exit 2 now, and the pattern is compiled at
load. `[pm.scaffold.*]` accepted an unknown grain key or a non-table value silently, the un-fixed half
of the earlier `checks` fix. D8 passed whenever *any* building milestone matched the version, masking
exactly the drift it exists to catch; two building milestones is now itself the finding. D10 skipped
silently on a detached HEAD — which is what CI checks out — and now says `UNVERIFIED` with the reason.
The ref census counted differently depending on which rules ran. A numeric phase depending on a `seam`
or unphased feature is no longer silently exempt. `pm validate` now honours `[pm] checks` like the gate
does. `prune`'s ROADMAP write no longer translates line endings, and fails cleanly instead of
tracebacking. `KNOWN_CHECKS` listed V1–V5 twice. The FAIL summary called integrity findings "status
drift". The CLI docstring and the README's `check pm` row had both fallen behind the verbs.


**On upgrade:** nothing changes until you run `godot-devkit pm install-skills`. Nothing is written to
a consuming repo without that explicit command.

**New — `pm install-skills`.** The tool shipped without its manual: a consumer got a
precondition-checked CLI and had to reinvent the doctrine that drives it. Measured across the two
consumers, that doctrine had forked badly — the execution rule differed by 57 lines out of ~60.
`install-skills` writes it once, from here:

- `.claude/rules/pm-execution.md` — the claim→close loop, why the CLI refuses what it refuses, and
  the close-evidence promotion test. Installed as a **rule**, not a skill file, because
  `.claude/rules/*.md` with a `paths:` header **auto-loads** for any agent touching the tree while a
  skill must be invoked. A per-edit loop that has to be asked for does not arrive.
- `.claude/skills/pm-operations/SKILL.md` — the operations manual: grain schemas, scaffolding,
  decomposition, phases, reading `status`/`validate`, and the prune model. A **skill**, because you
  reach for it deliberately when planning or restructuring, not on every edit.

Both are generated and carry a header saying so. Re-running is idempotent; a stale generated file
updates in place; a file the tool did **not** write is refused rather than clobbered (`--force`
overrides), because silently overwriting is how a project loses a decision it made on purpose.

**Where the line falls.** These two carry only what the CLI enforces and explains. A project's own
SDLC — branching, versioning, release ceremony, dispatch, review rosters, and what a milestone
*means* in that codebase — stays local. No agent ships from here for the same reason: an agent
carries a project's vocabulary.

**New — `pm init`.** For a repo with no tree at all: creates `pm/roadmap/` and a seeded `ROADMAP.md`
(with the § Prune log idiom already in it), installs the guidance, and prints the remaining wiring —
the gate target, the optional `[pm]` config, and the first scaffold commands — as a checklist rather
than a README to go find.

## v0.8.0 — validate  *(never tagged — shipped inside `v0.9.0`)*

**On upgrade:** `check pm` gains five integrity rules (V1–V5), on by default, so a tree with a
dangling `depends_on` that previously passed will now fail. That is the point — but check with
`pm validate` before you bump. Projects whose story FILES carry an ordering prefix (`01-slug.md`)
while their story IDS do not **must** declare `[pm] story_ordinal_prefix = true`; without it every
such story reads as an id/path mismatch. (Measured: one consumer went from 96 findings to 0 on that
one line.)

**New verb — `pm validate`, and the same predicates inside `check pm`.** A different question from
drift. Drift asks whether statuses are consistent with each other; validation asks whether the tree
is well-formed and its references are real. A milestone can be perfectly undrifted and still depend
on a feature that does not exist — nothing checked that until now, in either consumer.

- **V1** frontmatter is well-formed (a leading fence carrying `id:` and `status:`)
- **V2** the id matches the path — the id==path convention every resolver relies on
- **V3** parentage is consistent: a story's `feature:`/`milestone:` and a feature's `milestone:`
  name the grains that actually own them
- **V4** `depends_on` / `consumed_by` resolve
- **V5** the feature dependency graph is **acyclic** and **phase-monotone** (no feature depends on
  one in a LATER phase). Both were documented in a consumer's README as properties to uphold and
  neither was implemented anywhere.

**Pruned milestones are not errors.** Git history is the archive, so a ref naming a milestone no
longer in the working tree is expected. V4 resolves only refs whose milestone is present and censuses
the rest as UNVERIFIABLE — the discipline `check props` already uses. Failing them would punish the
prune model; hiding them would conceal a typo, so they are counted and named in the summary.

**`pm validate` refuses an empty tree** (exit 2) rather than printing VALID over zero grains — the
same rule-4 guard `check pm` carries.

## v0.7.0 — the flow rules  *(never tagged — shipped inside `v0.9.0`)*

**On upgrade:** nothing changes unless you ask for it. The three new rules are **opt-in** — name them
in `[pm] checks` to enable them. A project that ships from the trunk and bumps its version at
milestone close is running a different, valid flow; failing it would make the gate a liar.

**New rules — D8, D9, D10**, gating branch-per-milestone and bump-at-start:

- **D8** — the project's shipped version equals the `building` milestone's id, by **exact string
  equality**: the milestone id IS the version. Bumping at milestone START means the manifest always
  answers "what am I working on?", a fact every crash report, save file and dev build then carries
  for free. Configurable via `version_file` + `version_pattern`, so this is not Godot-specific.
- **D9** — a `building` milestone declares the `branch:` its work lives on. A fresh checkout of the
  trunk sees a milestone's PM records but not its code; without the stamp the only recourse is
  guessing at `git branch -a`, and a wrong guess means reporting on the wrong milestone.
- **D10** — that branch is checked out **in the trunk worktree**. D9 proves a milestone says where
  its code lives; D10 proves it is where a human can actually follow it. Read from git's MAIN
  worktree, not the tree the scan happens to run from. A milestone declaring a trunk branch
  (`trunk_branches`, default `staging`/`main`) is skipped — it is not using an integration branch.

**Config:** `version_file`, `version_pattern`, `trunk_branches`, and the three rule names in `checks`.

## v0.6.0 — project management  *(never tagged — shipped inside `v0.9.0`)*

**On upgrade:** nothing a consumer must edit. Every existing subcommand, flag and output shape is
unchanged, and the new `check pm` is **opt-in** — it is deliberately excluded from `check all`,
because a repo with no PM tree has no drift to find and must not be failed for its absence.

**New tool family — `godot-devkit pm`.** Filesystem-backed milestone → feature → story tracking
(markdown + YAML frontmatter under `pm/roadmap/`), with the transitions as a precondition-checked
CLI rather than a convention: `pm story|feature|milestone <transition>`, `pm status`, `pm new`,
`pm prune`. A `status:` is the one field a human should never hand-edit — free-text flips are how a
lifecycle drifts, features reaching `done` without the review the flow requires. `pm feature done`
cascade-closes every `review` story and the feature atomically, refuses without a *substantive*
review record (the anti-rubber-stamp: it rejects emptiness, not brevity), and on refusal leaves
`feature.md` byte-identical — a half-applied cascade is worse than no cascade.

**New gate — `check pm`.** Seven drift rules: a `done` feature with no review record (D1), a feature
whose stories are all done but which never advanced (D2), a `done` milestone with live children
(D3), a status outside the schema (D4), a `done` story under a live feature (D5), a `building`
milestone with everything closed (D6), an overdue archive prune (D7). Per rule 4 it prints its
census and **fails rather than passing** when it finds no milestones at all — a misconfigured
`roadmap_dir` used to be indistinguishable from a clean tree. Each rule is proven to fire by a
deliberately-broken probe, and the gate's verdict was diffed against the shell implementation it
replaces over a live consumer tree: identical, as is `pm status` byte-for-byte.

**One definition, two readers.** The vocabularies, transition graphs, id↔path resolution,
frontmatter IO, the review-record definition and the drift predicates live in
`pm/model.py`, imported by both the CLI and the gate. That invariant is the reason this ships as one
package instead of a tool and a separate linter — the two halves cannot describe "reviewed" or
"drift" differently.

**Engine-agnostic, and the README says so.** Nothing in `pm` parses a scene; it would work in a repo
with no Godot in it. The § Scope boundary now names the two families this package actually holds —
scene structure, and repo discipline (`check doc`, `check shell`, `check repo-hygiene` never parsed
a scene either) — rather than implying everything here is `.tscn` tooling.

**Config:** `[pm]` — `roadmap_dir`, `review_dir`, `review_min_content_bytes`, `review_slug_fallback`,
`story_ordinal_prefix`, `checks`, the six vocabulary/graph lists, and `[pm.scaffold.<grain>]` for
projects whose frontmatter schema differs. Stock defaults are the strict graph.

**Hardening from the pre-release review.** The gate could be turned into a rubber stamp by a
`devkit.toml` typo: `[pm] checks` accepted any iterable, so `checks = "D1"` iterated into *characters*,
no rule name matched, and the gate walked the whole tree finding nothing while printing PASS and a
census that made it look thorough. Every `[pm]` value is now type-checked and `checks` is validated
against the known rule names; a malformed section exits **2** (config error), never 0 and never 1 —
`project.py` already stated that contract and only `TOMLDecodeError` had honoured it.

**Fix — frontmatter writes preserved every byte except the ones asked for.** `Path.read_text` /
`write_text` apply universal-newline translation, and `str.splitlines()` additionally breaks on
U+2028/U+2029/form-feed/lone-CR — so a one-field status write silently converted a CRLF file to LF
and rewrote exotic body separators. Reads and writes now pass `newline=''` and split on `\n` only,
proven byte-for-byte on CRLF and on a body carrying U+2028, form feed and a lone CR.

**Fix — `pm prune` could destroy an archive without recording the resurrect anchor, and say it had.**
The prune-log stamp was skipped when `ROADMAP.md` did not exist, while the success line still claimed
the anchor was written. The index is now created and stamped before anything is deleted.

**Fix — a mid-cascade write failure** (an unwritable story file) raised a traceback and left a
half-applied close. It now aborts with exit 2 and says the command is idempotent — re-run to finish.

**Fix — the gate and the CLI disagreed about a quoted `status: "done"`.** The CLI unquoted it, the
gate did not, so `check pm` called a tree clean while `pm prune` deleted a directory from it.
`field_of` now unquotes centrally — one definition, both readers.

**Fix — a directory with no grain file is reported, not skipped.** A milestone dir missing
`milestone.md` (or a feature dir missing `feature.md`) silently took every descendant out of the scan.
Those are now findings that name what was skipped.

**Also fixed:** ids are rejected as glob patterns (`pm milestone ready '*'` resolved to a real
milestone); `prune`'s lag-by-one now orders versions numerically, so `0.9` no longer counts as newer
than `0.11`; `prune` in a repo with no commits exits 2 instead of raising; `_slugify` is ASCII-only,
so `pm new` cannot mint a non-ASCII directory name as a permanent id.

**Fix — `__version__` had drifted from `pyproject.toml`** (`0.4.0` vs `0.5.0`), which rule 7 forbids.
Both now read `0.6.0`.

## v0.5.0

**New gate — `check defaults`.** A `.tres` assignment may not repeat the value its script already
declares as the `@export` default. Two writers, two formats: hand-authored data spells every property
out, Godot's writer omits anything equal to the default — so `trigger = 0` for
`@export var trigger: Trigger = Trigger.ALL_PLAYERS_DOWN` vanishes on the first editor save and the
file diffs forever. Precision is the design constraint, as in `check props`: both sides of every
comparison must normalise into one small closed value language (bool / number / string / empty array /
empty dict / null / numeric constructor), with enum members, `const`s and `const Alias = preload(...)`
chains resolved from the scripts themselves. Anything outside it — an accessor on the export, an
engine built-in with no default table, a `preload()` default — is censused as NOT-A-FINDING and never
reported. Calibrated against Godot's own writer over 559 real `.tres`: **0 false positives, 97.1% of
the engine's own elisions found.** Config: `[defaults] exclude_prefixes`.

**Scope, stated plainly:** the gate judges the property-ELISION dimension only. Godot's writer also
reorders properties into declaration order, respells typed arrays and floats, mints `ext_resource`
entries for typed-array element types, and drops `;` comments. A PASS means "no redundant defaults",
not "the editor would leave this file alone" — the other dimensions are not decidable by parse without
reimplementing `ResourceFormatSaverText`.

**New flag — `scene canonicalize --elide-defaults`.** The fixer for the above. Opt-in, because it
deletes lines. It is a line-deletion pass, never a re-serialisation: over 559 consumer `.tres` it
removed 2479 assignments from 384 files with **zero lines added, zero structural lines touched, every
`;` comment and every `uid=` intact, and zero change to any loaded property value** (proven by loading
every resource in Godot before and after and comparing every STORAGE property, recursively). The
contrast is the point — a headless load-and-re-save over the same corpus rewrote 558 of 559 files,
deleted 1157 comment lines, and silently emptied resources whose script failed to compile.

**Fix — `scene canonicalize` no longer reports a uid-less `.tres` as UNRESOLVED.** A `.tscn` always
leaves the editor with a header uid, so a missing one is a real `pack()` loss. A hand-authored `.tres`
legitimately has none, and when nothing references it by uid there is nothing to restore and nothing
broken. This was 372 false findings out of 559 files in one consumer.

**Internal.** `ext_index` / `ref_path` / `script_path` moved from `checks/props.py` into `tscn.py`
(one home, two consumers); `scan_line` grew `comment_in_brackets`, the one place the two grammars
differ (a `;` inside a multi-line `.tres` value is data, a `#` inside a GDScript `enum {}` is a
comment); `TscnDocument.delete_props` does batch bottom-up span deletion.

## v0.4.0 — 2026-08-23 — the .tscn toolkit

**On upgrade:** nothing a consumer must edit — every existing subcommand, flag, and output shape is
unchanged, so bumping `DEVKIT_VERSION` is a one-line diff. The new `check props` gate is **opt-in**:
it runs only when a consumer wires it into its own gate set. It currently reports 25 findings in
nullbound and 5 in trail, all of them real renamed-export assignments that Godot drops silently — so
wire it deliberately, after a cleanup pass, not as part of the version bump.

A `.tscn` is text, and now it is text we edit *through* tools instead of around them.

**New gate — `check props`.** For every section carrying a script (scene nodes, `sub_resource`s and
`.tres` resources), each assigned property must be an `@export` on the script's inheritance chain or a
built-in of the node/resource type. Catches the silent-failure class where an export is renamed and a
scene keeps assigning the old name: Godot drops the assignment without a word. Precision was the
design constraint — nothing is reported DEAD unless the script parsed, its `extends` chain landed on a
known engine class, and it declares no dynamic properties; instance roots and instance-child overrides
are followed into their base scenes, and anything still unresolved is censused as UNVERIFIED rather
than failed. Every property lands in exactly one bucket and the buckets are printed and checked to
balance. Config: `[props] exclude_prefixes`, `[props] extra_properties`.

**New write verbs — `scene set|rename|add|rm|reparent`.** Path-addressed, `--dry-run`-able,
idempotent, and refusing rather than mangling. `rename` rewrites every `parent=`, every
`[connection]`/`[editable]` reference, and every relative `NodePath("...")` literal — resolved against
the node that owns it, not text-matched. Export names (`node_paths=PackedStringArray(...)`) are left
alone, because they are not paths.

**New verb — `scene canonicalize`.** Restores what `PackedScene.pack()` + `ResourceSaver.save()` drop:
uid-in-refs on every `ext_resource`, the file's own header uid, `index=` on instance-child overrides
(without it the override reloads as a NEW SIBLING and leaks the base scene's child as an orphan on
every load), and `[editable path=]`. Restores from evidence — `.uid` sidecar, resource header,
`.import` file, or existing repo references — and reports what it could not resolve.

**Parser.** `tscn.py` sections and properties now carry line spans, and value continuation is
string-aware (brackets and `;` inside a quoted value no longer count), which fixes multi-line
dictionary values and stops inline comments being swallowed into the value. New `tscn_document.py`
edits only the spans it was asked about, so an unmutated round trip is byte-identical by construction.
`scene` gains `--paths`.

**Also:** `uid_index.py` is the one answer to "where does this resource's uid live" (`.uid` sidecar,
resource header, `.import` file, or existing repo references), shared by `canonicalize` and
`add --script`; `check all` now includes `props`; `src/godot_devkit/data/classdb.json` (a snapshot of
`--dump-extension-api`) ships with the package and is regenerated by `tools/gen_classdb.py`; a stdlib
`unittest` suite lives in `tests/`.

## v0.3.0 — 2026-07-04

Post-review release — all findings from the full code-reviewer pass fixed:

- **CRITICAL fix**: `check repo-hygiene` CHECK 3 could never detect a dangling
  worktree (`git worktree prune -n -v` reports on stderr; the gate read
  stdout). Now parses `git worktree list --porcelain` `prunable` entries.
- **Fix**: an unresolvable `[repo_hygiene] mainline` no longer silently
  disables CHECK 4 — it is a CONFIG ERROR, exit 2.
- **Fix**: a malformed `devkit.toml` exits 2 with a clean message instead of
  a traceback at exit 1 (1 is reserved for findings).
- **Change (upgrade note)**: `check uid` CHECK 1 now censuses ALL tracked
  .tres/.tscn (addons/ exempt) instead of a `[uid] scan_dirs` allowlist — the
  config key is now `exclude_prefixes`; the PASS line reports the ref/file
  census. Attribute matching is order-independent (a reordered ext_resource
  ref is censused, not skipped).
- **Fix**: top-level `--help`/`help` exits 0.

## v0.2.0 — 2026-07-04

- Converted from a vendored file-set to a real Python package: one
  `godot-devkit` entry point with subcommands (`scene`, `scene-diff`, `refs`,
  `orphans`, `autoloads`, `check <gate>`).
- Ported the four bash gates (uid, tres-format, repo-hygiene, shellcheck
  wrapper) to Python — cross-platform, config-driven.
- Per-project variation moved out of file edits into `devkit.toml` at the
  consuming repo root (`[autoloads]`, `[doc]`, `[uid]`, `[tres]`,
  `[repo_hygiene]`, `[shell]`).
- Retired `sync.sh` + the vendored-manifest model; consumers now pin a git
  tag: `uvx --from git+https://github.com/cdowin/godot-devkit@v0.2.0 godot-devkit …`.

## v0.1.0 — 2026-07-04

- Initial extraction from two shipping Godot 4.6 projects: introspect suite
  (shared .tscn/.tres parser, scene summary, structural scene-diff, refs,
  orphans, autoload census) + five static gates, consumed by vendored sync
  with a drift manifest.
