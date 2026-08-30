# Changelog

## Unreleased

- **consumer smoke is a target** — `make smoke` runs every read verb against the live game checkouts, compares each printed census against an independent count, and fails if it leaves either checkout dirty. (tools/consumer_smoke.py)
- **one walk** — Filesystem enumeration moves into core/walk.py, which returns what it KEPT and what it SKIPPED under a closed-enum reason; Walk has no length, so a census cannot reach a count without its disclosures. (6ac90c3)
- **the two allowlists** — An AST test asserts glob/rglob/iterdir/os.walk live only in core/walk.py and write_text/open-for-write/rename/unlink/rmtree/mkdir only in core/apply.py, naming file:line otherwise. (tests/test_boundaries.py)
- **one apply** — Filesystem mutation moves into core/apply.py: a Plan is an explicit list of Steps, decide() names every obstruction from a closed enum before anything runs, and Applied says which landed. (7134e72)
- **the toolkit stops managing your prose** — The prose ratchet (D17/D18, `pm collapse`, `pm prose-ledger`, six line caps) is gone. Its entire output over two releases was 41 lines of markdown. (b8dc7c4)
- **`pm decide` writes a heading, not a form** — The four-field decision schema produced ZERO conforming entries across a consumer's 158 decision logs. `pm decide <grain-id> <title>` now stamps the date and the next ordinal and stops; the reasoning under it is yours. (6de5b0e)
- **`pm new` stops minting empty files** — Scaffolding a `decisions.md` and `handoff.md` into every grain put 204 empty files and ~1,900 lines into one consumer's tree. A shared doc now appears on first WRITE. (b1c9629)
- **BREAKING: `pm changelog`, `pm decisions`, `pm collapse`, `pm prose-ledger`, `pm claim`, `pm release`, `task` and `check tasks` are removed** — No consumer invoked any of them. `pm set <id> owner <x>` replaces claim/release; `CHANGELOG.md` is hand-maintained. (4e034a4, 56ffaf4)
- **`install-ci` and `install-agents` are back** — They were cut on a census reading 0 consumer references; the verbs had shipped hours earlier and had been held read-only against both consumers, so the census measured a restriction rather than disuse. Restored from history. (56ffaf4, src/godot_devkit/repo/install.py)
- **`install-ci` emits ONE opinionated workflow** — checkout, uv, `make milestone`. The `[ci]` config block, its hand-rolled TOML→YAML emitter and the PyYAML dev dependency do NOT come back: a project that wants a different workflow edits the file, which after the write is its own. The assumption that `make milestone` exists is a comment in the emitted file, not a discovery mechanism. (src/godot_devkit/repo/installables/ci-verify.yml)
- **`install-hooks`** — The shared-tree commit guard, the raw-engine-boot guard and `setup-hooks.sh`, which were forked between two consumers and drifting. Canonical here, each script STANDALONE: the project-name-prefixed JSON helper (`<project>_hook_json_field`, defined in a `_scope.sh` this package does not ship) collapses to one neutral `hook_json_field` defined where it is used, because a `source` of a library a fresh repo lacks fails open and a guard that fails open is not there. (src/godot_devkit/repo/installables/)
- **`--diff` on every install verb** — Prints a unified diff of what a run would change and writes nothing; an absent destination is named as an addition, an undecodable one as a whole-file replace. (src/godot_devkit/repo/install.py)
- **an install refuses on ANY difference** — The install-* verbs used to overwrite, without asking, any destination still carrying their generated header — so a project that edited an installed file lost the edit on the next run. A destination that exists and is not byte-for-byte what would be written is now refused by path, with `--force` named. (src/godot_devkit/repo/install.py)
- **BREAKING: D11, D12, D15, D16, D17 and D18 no longer exist** — `[pm] checks` naming any of them is exit 2. Neither consumer enabled one; every rule they do run (D1-D10, V1-V6) is byte-identical. `review.md` is a permitted file rather than a mandatory slot. (355b671)
- **`actual_date:` is not minted and not stamped** — `pm milestone done` stopped writing it and the milestone template stopped minting the field when the changelog render that read it was removed. Git records when a milestone closed; existing values in a tree are left alone. (src/godot_devkit/repo/pm/templates/milestone.md)
- **one gate roster** — `[checks] all` and the dispatch table were two lists holding one fact; a gate now carries its own default-in-`all` flag, and a test walks the roster to prove every name dispatches. (1c744f8)
- **BREAKING: `pm prune` is removed, with D7 and D14** — On the default roster an open bug under a `done` milestone was PASS, and prune then deleted it. Nothing here deletes a grain. (repo/pm/cli.py)
- **D4 covers a bug's status** — D14's one fact about a FILE (a status outside `bug_states`) moves to the rule that already owns it, on by default. `bug_open_states` goes with its only reader.
- **the census always counts bugs** — `N bug(s)` used to ride the opt-in D14, so a default run said nothing about a directory it had walked. (repo/checks/pm.py)

## v0.14.0 — 2026-08-29

- **a milestone has release notes** — `pm changelog <milestone-id> --what … --evidence …` appends a release note to that milestone's own log. (e432831)
- **the whole log, newest release first** — `pm changelog --render` prints the union of every milestone's notes to stdout, newest release first. (e432831)
- **read a grain's decisions back** — `pm decisions <grain-id>` prints that grain's decision entries, parsed — a milestone printing its own log and its features'. (e432831)
- **D15 holds a changelog entry to its schema** — D15 checks every `changelog.md` entry carries **What:** and **Evidence:**, with a `changelog_grandfather` ledger for legacy text. (e432831)
- **D16 stops a release shipping with no notes** — D16 fails a `done` milestone whose changelog is missing, empty, or holds only entries D15 already reports. (e432831)
- **existing milestones need one re-scaffold** — UPGRADE: `changelog.md` is a new canonical slot, so run `pm new milestone <id>` once per existing milestone to fill the gap. (e432831)
- **D17 caps grain prose as a ratchet** — D17 caps the line count of a story, a `feature.md`, a bug, a feature's `decisions.md` and a `changelog.md`, with the caps as config. (dcb2511)
- **D18 collapses a closed milestone's trail** — D18 fails a `done` milestone still carrying its raw decision trail — close evidence is pointers, not the log. (dcb2511)
- **pm prose-ledger, which will not raise a ceiling** — `pm prose-ledger` regenerates D17's debt ledger to stdout and REFUSES to raise an existing ceiling. (dcb2511)
- **a short --evidence says how to lengthen it** — A commit hash one character short of the minimum is now refused with the count, the minimum, and the `git rev-parse` that fixes it. (dcb2511)
- **a balanced backtick span no longer opens a fence** — A paragraph opening with a balanced inline code span no longer masks the rest of the document, which had hidden real findings from `check doc` and D12. (2eaae12)
- **a fence quoted inside a comment is not malformed** — A lone fence marker inside a paired HTML comment is no longer reported MALFORMED — the two markers hide each other and document order settles it. (2eaae12)
- **check agents reports what it cannot decode** — `check agents` reports an agent definition it cannot decode and takes it OUT of the scanned count, instead of dropping it in silence. (2eaae12)
- **stories/ is walked recursively** — A story at `stories/<subdir>/<name>.md` or named `.MD` is visible to every `check pm` rule, the way bugs already were. (2eaae12)
- **a grain is its frontmatter** — A `.md` under `bugs/` or `stories/` with no frontmatter block is a note parked beside the grains, not a grain with an empty status. (2eaae12)
- **pm new refuses instead of tracebacking** — `pm new` on an over-long grain name or an unwritable `pm/roadmap/` refuses with the reason, and nothing is written. (2eaae12)
- **check doc's FAIL line carries its census** — `check doc` names how many docs it read and how many fenced lines it skipped on FAIL, not only on PASS. (2eaae12)
- **check all runs the gates that apply to your repo** — New `[checks] all` in devkit.toml names the gates `check all` runs here; an unknown name is exit 2, never a quietly narrowed run. (src/godot_devkit/cli.py:87)
- **a nested story is addressable by id** — `pm story <state> <id>` resolves a story anywhere under `stories/`, so the gate can no longer report one the verb refuses. (src/godot_devkit/repo/pm/model.py:572)
- **[uid] exclude_prefixes scopes both uid checks** — `[uid] exclude_prefixes` now scopes the sidecar-tracking check too, not just the ref-drift one. (src/godot_devkit/godot/checks/uid.py:151)
- **an empty census says what it was out of** — A `uid`/`tres`/`props` run that scans nothing now reports "0 of N tracked", so an empty repo and an over-broad exclude stop reading identically. (src/godot_devkit/godot/checks/tres.py:54)
- **the toolkit runs its own gates on itself** — godot-devkit carries its own PM tree at `pm/roadmap/`, with every rule it ships enabled, and its own CHANGELOG rendered from it. (devkit.toml:1)
- **a release heading names its tag and its date** — A rendered release heading is now `## v<id> — <actual_date>`, matching the git tag it maps to; a milestone that has not shipped renders `## v<id>` with no invented date. (src/godot_devkit/repo/pm/cli.py:1218)
- **a broken grain is reported, not dropped** — A story or bug whose frontmatter is damaged — a BOM, a blank line above the fence, no closing fence — stays in the census and is reported, instead of leaving the scan in silence. (src/godot_devkit/repo/pm/model.py:706)
- **the census says how far it looked** — check pm now names how many .md files the grain walk skipped as notes, so a zero bug count is never mistaken for an empty directory. (src/godot_devkit/repo/checks/pm.py:540)
- **a milestone stamps its release date at close** — pm milestone done writes actual_date, which is what puts the date in the changelog render's '## v<id> — <date>' heading; the render still never reads a clock. (src/godot_devkit/repo/pm/cli.py:425)
- **pm prose-ledger names what it absorbs** — Regenerating the prose debt ledger prints every newly absorbed document on stderr with a count, so new debt can no longer enter the ratchet unannounced. (src/godot_devkit/repo/pm/cli.py:1394)
- **a version-shaped changelog heading is not an entry id** — A preamble heading like '## v0.9 release notes' no longer reads as entry 'v0', so the next appended note is allocated C1 rather than v1. (src/godot_devkit/repo/pm/model.py:1138)
- **one fact, one finding, in the right vocabulary** — An over-cap finding names the grain kind it is about, and a ledgered document back inside its cap is reported once — drop the entry — rather than twice. (src/godot_devkit/repo/pm/model.py:1900)
- **a hidden document is still disclosed** — A dot-prefixed file under bugs/ or stories/ is counted in the census instead of vanishing from it. (src/godot_devkit/repo/pm/model.py:769)

---

`v0.13.0` is the only historical section retained, for one reason: it carries
the breaking `DECISIONS.md` -> `decisions.md` rename and how to absorb it, and
the `trail` consumer is still pinned below it. When trail migrates it goes.

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

Six more were reported here and all six are fixed in `## Unreleased` above: the balanced
three-backtick span read as a fence opener, `check agents` skipping a non-UTF-8 definition in
silence, `stories/` never getting D14's recursion, `pm new`'s unguarded `gdir.mkdir`, D14 reporting a
non-bug `.md` under `bugs/`, and an unterminated fence inside a *closed* HTML comment reported as
malformed.

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
