---
id: 0.17.0/bugs/tracked-but-deleted-traceback
milestone: "0.17.0"
name:
status: open
caught_in: "0.17.0"
fix_milestone:
---

# tracked-but-deleted-traceback

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

## Root cause

## Fix

`check uid`, `check tres`, and `check props` open every `git ls-files` entry with no OSError guard:
a file tracked in the index but deleted on disk (partial checkout, mid-rebase) raises
FileNotFoundError — exit 1 with a stack trace a hook reads as "findings". Loud, not a false PASS,
but the contract is a refusal or a censused skip. `uid_index.from_repo_references` already guards
this; mirror it in the three gates with an UNVERIFIED census bucket. Found by the v0.16.0 release
review (finding 5).
