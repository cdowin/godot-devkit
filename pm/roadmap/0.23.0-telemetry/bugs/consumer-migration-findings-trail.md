---
id: 0.23.0/bugs/consumer-migration-findings-trail
milestone: "0.23.0"
name: Seven findings from a consumer migration v0.18.0 → v0.20.0, five of them one class — an install silently resets project config
status: open
caught_in: "0.20.0"
fix_milestone: "0.23.0"
---

# consumer-migration-findings-trail

Filed 2026-09-02 from the thing the bootstrap release is ultimately for: an EXISTING consumer
adopting it. The consumer went v0.18.0 → v0.20.0, ran `install-hooks` + `install-runners`,
restructured its 280-line Makefile onto the include, and proved the result with
`integration-all` (271 passed, 0 failed). Everything below was hit, not imagined. The release is
measured against a fresh `init`; these are what a **migration** hits, the other half of the same
verb. (Record as written by the consumer's agent; nullbound's adoption hit the same class the same
day — its four extra defects are § H.)

## A — MAJOR: an install resets `project config` values with no report

Five times the installer overwrote a file and silently reset a value the consumer had
deliberately set. Each had to be noticed by hand and restored from git:

| File | Knob | Stock wrote | Consumer had |
|---|---|---|---|
| `runners/unit.sh` | `GDK_UNIT_BOOT_MARKERS` | *empty* | the project's boot-marker ERE |
| Makefile settings | `GDK_SMOKE_SCENARIO` | `smoke` | the project's smoke scenario |
| `hooks/pre-push` | `PUSH_GATE` | `(make check)` | `(make check uid-scan)` |
| `hooks/cc-stop-gate.sh` | `GATE_STATIC` | `(make check)` | `(make check uid-scan)` |
| `hooks/prepare-commit-msg` | `TRAILER` | generic | the project's model line |

**This is a class, not five incidents.** `--diff` shows a textual diff, which across a
4,714-line change is exactly where a one-line config reset hides. The `project config` block is
already a delimited, machine-recognizable region of `KEY=value` lines — so the install can parse
the destination's block before overwriting and **report every assignment whose value differs
from the stock one it is about to write**:

```
[install] tools/dev/runners/unit.sh — 1 project config value differs from stock:
            GDK_UNIT_BOOT_MARKERS  yours: 'mount_map\(|\.IN_GAME\)|…'   stock: (empty)
          re-apply after the write, or pass --carry-config
```

A `--carry-config` that preserves the destination's block outright would be better still.
Refuse-on-any-difference already says the package cares about not clobbering; this is the same
principle one level down, inside a file it is *sanctioned* to overwrite.

## B — MAJOR: the empty `GDK_UNIT_BOOT_MARKERS` silently disarms the tier's cardinal guard

Worth its own entry even with (A), because the blast radius differs. A unit tier that must never
boot the game ships with the guard enforcing that **off by default**. The consumer's tier had
been guarded for months; after the install it was not.

**The verdict line is what saved it** — `[UNIT] PASS (40/40 scripts loaded — full coverage;
no-boot guard not configured)`. That parenthetical is excellent design and the only reason this
was caught, so keep it exactly as is. But it is passive, and a fresh `init` writes a project whose
tier guard is off with nothing else ever mentioning it.

Suggestion: `doctor` warns when the unit-tier root exists and holds test scripts but
`GDK_UNIT_BOOT_MARKERS` is empty — `doctor` is where a consumer goes to ask "is my toolchain
actually wired?"

## C — NIT: `check`'s default-`all` roster is undiscoverable

`godot-devkit check` prints the general CLI help. `check --help` errors with the valid names
(`uid, tres, props, doc, shell, defaults, repo-hygiene, pm, rng, tres-comment, unit-disk,
test-shape, all`) but does **not** say which of the thirteen `all` runs. The only way to learn it
is five is to run it and count verdicts. That matters precisely because of `[gates] extra`: a
consumer wiring its own gates must know what `all` already covers, or it double-runs some and
silently omits others. Mark membership in the usage line, or add `check --list`.

## D — NIT: `pm new bug` takes no name, so every bug is minted nameless

`new feature <milestone> <slug> <name...>` and `new story <feature-id> <slug> <name...>` take a
name; `new bug <milestone> <slug>` does not. Three bugs were scaffolded in one consumer in one
session and all three shipped with `name:` empty; nothing gates it. The sibling verbs already
have the shape: `new bug <milestone> <slug> <name...>`.

## E — NIT: `pm bug <status>` does not stamp `fix_milestone:`

`pm feature done --review-record <path>` stamps `reviewed:` — the CLI writes the fact that
accompanies the transition. `pm bug fixed <id>` moves `status:` only, leaving `fix_milestone:` for
a hand edit, which is the thing the CLI exists to prevent. Either
`pm bug fixed <id> [--fix-milestone <ver>]`, or infer it from the bug id's own milestone.

## F — NIT: `Makefile.devkit`'s `milestone` omits `repo-hygiene`

`check repo-hygiene` ships and is a natural close gate (clean tree, no stashes, no dangling
worktrees, no dead branches). No standard target runs it, so the consumer's close gate lost it in
the migration and it had to be re-added as a prerequisite. Either fold it into `milestone`, or
state in the include's header why not — it fetches the remote, a defensible reason to leave it
opt-in, but the reason belongs where the omission is.

## G — NIT: `GDK_LINT_EXCLUDE_RE` assumes GUT is the only vendored addon

Default `^addons/(gut)/`. The consumer vendored three, so the first `make lint` linted
third-party code and failed on it. Not obviously wrong to default narrow — a project may author
its own code under `addons/` — but the default deserves a one-line note in the header saying it
assumes GUT is the only vendored tree.

## H — from the second consumer's adoption, same day

(b) the stock `WRAPPER_ROSTER` omits `make capture`, which `Makefile.devkit` itself defines;
(c) `verify.yml` installs uv only, then runs `make milestone`, which boots Godot and shells to
gdlint + shellcheck — green nowhere it is installed until the toolchain steps are added;
(d) README documents `[rng] allowlist = {…}` / `[unit_disk] forbidden_calls` as inline tables
across lines — invalid TOML; a real allowlist needs `[rng.allowlist]` sub-table syntax the README
never shows; (e) `check` has `[gates] extra` but `milestone` has no config hook, so a
close-time-only gate has no sanctioned home (the same gap as F, from the other side).

---

## What went RIGHT, so it does not get refactored away

- **Every quiet-gate verdict names its log.** `check` went 750 lines → 4.
- **The verdict lines state what they did NOT check** (`no-boot guard not configured`, the
  0-file census). That is what turned (B) from a silent regression into a five-minute fix. This
  is the single best thing in the release.
- **`scenario.sh` had already generalized the noise allowlist** to
  `GDK_SCENARIO_NOISE_ALLOWLIST`, defaulting to the consumer's own path.
- **The self-tests are why the migration was believable.** `gdk_runners.sh` 46 cases,
  `scenario.sh` 16, the sandbox hook 13 block / 16 allow — all green on arrival, and the restored
  no-boot guard was mutation-proved by planting a boot call in a unit test.
- **`parse` being two-stage** (boot + compile sweep) caught strictly more than the consumer's
  boot-grep ancestor, at zero configuration cost.
- **The sandbox guard's quoting fix**, shipped with a corpus, so the fix is executable rather than
  asserted.
