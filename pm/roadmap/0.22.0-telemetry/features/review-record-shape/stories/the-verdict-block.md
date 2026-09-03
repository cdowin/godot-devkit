---
id: 0.22.0/review-record-shape/the-verdict-block
feature: 0.22.0/review-record-shape
milestone: "0.22.0"
name: reviewer and simplifier records carry one parseable verdict block with findings by severity and disposition
status: review
owner:
depends_on: []
---

# reviewer and simplifier records carry one parseable verdict block with findings by severity and disposition

## Goal
A fenced block the report parses, written by the installed reviewer-shaped agents at the end of their pass:
```
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| W1 | WARNING | landed 3a42f19ad |
| S3 | SUGGESTION | rejected: pause regression |
| D2 | DELTA | deferred: 0.90.3/throwable-as-behavior |
```
`install-agents` updates `reviewer.md`, `simplifier.md`, `milestone-reviewer.md`, `verification-reviewer.md` to emit it (there is no `code-reviewer.md` installable; the repo-local one carries the block too); a parser in `pm/` reads it (exit 2 on a malformed block, never a guess).
## Verification
`make test` (parser: the four verdicts, every disposition, a malformed row), the agent-definition files assert the block text is present.
## Commit prefix
`feat(0.22.0/review-record-shape/S1):`
## Size
s
