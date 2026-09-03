---
id: 0.23.0/ledger-report/retired-milestones-report-from-git
feature: 0.23.0/ledger-report
milestone: "0.23.0"
name: pm ledger report reads a retired milestone's ledger and frontmatter from git via the prune-log anchor
status: todo
owner:
depends_on: []
---

# pm ledger report reads a retired milestone's ledger and frontmatter from git via the prune-log anchor

## Goal
`pm ledger report <ms> --from <rev>` reads `pm/roadmap/<ms-dir>/ledger.jsonl` and the grain docs at
`<rev>` through `git show <rev>:<path>` (one subprocess per file, `git` on PATH, exit 2 with the git
error if a path is absent at that rev) and prints the same table as the live read. `ROADMAP.md`'s
prune log is where a reader finds the anchor; the verb does not search history for it (D6: history is
git, the anchor is recorded, nothing is inferred).
## Gotchas
Never writes; never checks anything out. The milestone directory name at the anchor may carry a
different suffix than today's — resolve by the version prefix the way `milestone_dir` does, over
`git ls-tree`.
## Verification
`make test`: a fixture repo with a retired milestone → identical table to the pre-retire live run;
a bad rev → exit 2.
## Commit prefix
`feat(0.23.0/ledger-report/S3):`
## Size
s
