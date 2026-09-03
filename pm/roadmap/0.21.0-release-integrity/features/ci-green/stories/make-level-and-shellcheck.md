---
id: 0.21.0/ci-green/make-level-and-shellcheck
feature: 0.21.0/ci-green
milestone: "0.21.0"
name: drop the recursion variables in the makefile tests and clear the six shellcheck findings
status: review
owner:
depends_on: []
---

# drop the recursion variables in the makefile tests

In the two makefile test helpers, pop `MAKELEVEL`, `MAKEFLAGS`, `MFLAGS` from the spawned make's env. Drop the never-passed parameter from the hooks' `is_agent_context`; add the SC2317 spelling to the hermetic scan's indirect-invocation directives. Proof: `make test` (under make) and `make smoke` with shellcheck installed, then `make milestone`.
