Read CLAUDE.md first and follow it.

## Agents and models (agentic-sdlc 3.0)

- Before you delegate to a subagent, read the model guide:
  https://github.com/cdowin/agentic-sdlc/blob/v4.0.0/AGENTS-AND-MODELS.md
- Set the model and effort on every delegation. Never inherit them. Effort is capped at
  `high`.
- Take any unclaimed task you have the capabilities for. A `needs:<capability>` label
  names a capability the task needs; a task with no `needs:` label is open to you. Claim the
  issue before you start.
- Deliver the full vertical slice: art, code, data, wiring and proof. Do not stop for
  another agent. Merge your own PR when CI is green, then remove your worktree and local
  branch.
- The primary session integrates and reviews architecture. Delegate only independent,
  bounded work. For straightforward code or a focused review, use `gpt-6-luna` at low
  effort, with a precise brief, scope and acceptance criteria.
- Use the verified Codex tier mappings and capability limits in
  `plugin/contract/runtimes.json`. The model guide explains spawn and role configuration.
- The author of the code owns its proof. Run each proof once.
- Never force-push, `git reset --hard`, `git clean -f`, or discard the whole tree
  (`git checkout -- .`, `git restore .`). Commit by path: `git commit -m <msg> -- <paths>`.
- Keep `AGENTS.md` under 100 lines and `CLAUDE.md` under 200. CI checks it.
