---
id: 0.21.0/bugs/decide-title-eats-flags-and-shell-metacharacters
milestone: "0.21.0"
name: pm decide's title is argv — a title containing --all, a semicolon or an apostrophe is refused or truncated through make ARGS
status: open
caught_in: "0.21.0"
fix_milestone: "0.21.0"
---

# decide-title-eats-flags-and-shell-metacharacters

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

Three fixup commits in one consumer session (2026-09-02): a title with `;` truncated (fixed in
0.18.0 to REFUSE — still a failed call), a title with an apostrophe (`enemy's`) errored through
`make ARGS`, a title containing `--all` was parsed as a flag (exit 2), and in every case the
prose the orchestrator appended after the failed call landed under the previous heading. The verb
is used dozens of times a day by an agent that cannot see the shell.

## Root cause

`decide <grain> <title...>` takes the title as bare argv, so the shell and argparse both get a
vote. Fix: accept `--title "<text>"` (one quoted argument) AND read a title from stdin when
`--title -` / no argv title, document `make pm ARGS='decide <grain> --title "…"'` as the
sanctioned spelling, and print the heading it wrote so a caller can verify before appending prose.
Same class as `new bug` taking no name (consumer-migration-findings D).

## Fix
