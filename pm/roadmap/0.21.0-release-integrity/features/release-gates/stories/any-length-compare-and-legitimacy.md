---
id: 0.21.0/release-gates/any-length-compare-and-legitimacy
feature: 0.21.0/release-gates
milestone: "0.21.0"
name: n-component compare, done-or-hotfix rule, run under bash in the suite
status: review
owner:
depends_on: []
---

# n-component compare, done-or-hotfix rule, run under bash in the suite

In `ci-semver-gate.yml`: compare over the longer of the two versions, refuse a non-numeric component, then require the PR version to be a `done` milestone id under `PM_ROADMAP` (step env, default `pm/roadmap`) or main's version plus one integer. Proof: `tests/test_ci_workflows.py` extracts the step's `run:` body and runs it under bash, 11 rows including nullbound PR #56 refused.
