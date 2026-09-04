Cold-start only. Never restate what `pm status` computes.

# 0.24.0 gate-cost — handoff

Read this, then [`milestone.md`](milestone.md), then [`review.md`](review.md).

## 1. Where the work lives

- Branch **`milestone/0.24.0-gate-cost`**, trunk at `/Users/cdowin/workspace/godot-devkit`.
  `main` is merge-commit-only; the self-hosted `pre-push` blocks a direct push to it.
- Hooks are **armed here** (`core.hooksPath` → `tools/hooks`). A fresh clone is NOT — see § 3.
- `uv run python -m godot_devkit.cli pm status 0.24.0` is the scoreboard.

## 2. State — the milestone is BUILT and unreleased

Four features `done` or `reviewing`, **ten bugs resolved** (9 fixed, 1 explicitly parked with its
posture written into the bug), and `make milestone` **measured at 3:36** against a criterion of 8
minutes, from ~20 before this milestone. The matrix is where it went: the floor runs 1714 tests in
172 s, the other three interpreters run 265 each in ~3 s — nine seconds between them where they used
to cost ~13 minutes, same verdict line.

**Two review passes ran and both are recorded:**

- `review.md` — the `verification-reviewer` release-gate pass. **RELEASE-WITH-FIXES**; its M1 and m2
  landed. Two MINORs it deferred are still open and named there.
- A `code-reviewer` precondition pass returned **NOT-RELEASE-SAFE** with four blockers (CI red on
  every clean checkout; the new gate passing over a broken-symlink hook; canonicalize writing a wrong
  `index=` on a chained base; release notes that would have destroyed a consumer's CI). **All four
  are fixed and pushed**, plus two the pass surfaced and left for the orchestrator.

## 3. What is left before the tag

**Everything except the release protocol itself.** Run [`.claude/skills/release`](../../../.claude/skills/release/SKILL.md)
— it was RE-ORDERED by this milestone and the new order is the point:

> 1 version sync → 2 README pins → **3 review each feature, then ACCEPT — `make milestone` runs HERE,
> at `accepted`** → **4 PACKAGE (`pm milestone packaging`, then the CHANGELOG retitle)** →
> **5 `pm milestone done`, the LAST PM action** → 6 branch/PR/merge/tag → 7 prove the artifact →
> 8 consumer follow-up.

`done` does **not** mean shipped. Chris, 2026-09-04: *"done gets flipped when everything is done.
Changelog written, reviewers all done. Done does not necessarily mean shipped — that's a
branching/PR/push thing outside the scope of the pm tree."* The flip is itself a commit that has not
shipped when it is written, so a `done` meaning shipped is unrepresentable.

**`make milestone` has not been run since the lifecycle change landed.** It was 3:36 at `838d969`.

**CI arms the hooks now** (`ci-verify.yml` gained the step). Before that fix, `check hooks` joined
`[checks] all` and `actions/checkout` produces a checkout that has never had `core.hooksPath` set —
so `make milestone` was red on every clean checkout and the release could not complete. Verified on a
clean clone: exit 1 unarmed → exit 0 after the arming step.

## 4. The lifecycle change is the headline, and consumers must migrate

```
planning → ready → building → reviewing → accepted → packaging → done
```

One vocabulary across milestone / feature / story; transitions stay open, so a grain skips what it
does not need. Bug states are a different machine and did not change.

**D5 is the rule that changed logic**, not D6. It used to assert a `done` story's feature is also
`done` — false on the normal path once a story can finish while its feature is `reviewing`. It now
fires when a child is **at work under a parent that says it has not started**, compared across
`building` (the split where shaping ends) inside each grain's own set. D6 keeps its predicate; only
its message changed.

**Consumer follow-up when the tag lands** — the CHANGELOG carries the accurate version:

- Bump `DEVKIT_VERSION`. **nullbound must not bump until the tag exists** (M48 caught the reverse).
- `install-ci --diff` then decide **per file**. **Never blanket `--force`** — it rewrites all four
  workflows with no per-file option, and it would replace trail's deliberate two-job sharded
  `verify.yml` (177 lines of difference) and drop a path filter from nullbound's `auto-tag.yml`.
- `install-hooks`, `install-runners`, one `pm init` re-run.
- **Migrate `status:` lines.** Measured 2026-09-04: nullbound 37 story `todo` → `ready` and 9 story
  `review` → `reviewing`; trail 24 and 1. **No feature in any tree holds `review`.** trail's 8
  `active` grains live in `features/*/plans/*.md`, a slot the PM walker never visits — `check pm` in
  trail exits 0 today and the new set does not change that.

## 5. Traps this milestone sprung

1. **`make milestone` could not run before the close it gates.** `check pm` D6 refused a `building`
   milestone whose features were all `done`, so the release gate demanded the ship decision it
   exists to inform. Filed as `bugs/the-release-gate-cannot-run-before-the-close-it-gates`; the
   lifecycle change is its fix, and the bug should be re-checked and closed after the first release
   through the new order.
2. **A milestone status flip that lived only in a worktree** reddened CI for a second reason
   underneath the first. `git show HEAD:<file>` before believing a status.
3. **`install-ci --force` cannot be used on this repo at all** — it would write three workflows this
   repo deliberately does not carry. Re-install a single file through its plan entry instead.
4. **Two shipped surfaces named a repair no consumer has** (`make hooks`). Fixed in `check hooks`,
   `README.md` and `setup-hooks.sh` — the last of which `install-hooks` writes into every consumer.
5. **This package defines rules and does not always run them on itself.** Twice in this milestone:
   `CLAUDE.md` claimed the hook corpus was self-hosted while `core.hooksPath` was unset in every
   checkout, and this file did not exist while `model.py` has defined `HANDOFF_FILE_NAME` and ruled
   it milestone-only for releases. See `bugs/a-milestone-in-flight-has-no-handoff`.
