# Decisions — release-gates

## R1 — 2026-09-03 — review record (code-reviewer, two passes)

Pass 1 returned NOT RELEASE-SAFE; pass 2 confirmed every blocker fixed with one rule-4 gap left,
landed in the third cut.

- **CRITICAL (pass 1):** a BUILDING milestone whose id is main plus one integer passed as a hotfix —
  the exact class the rule exists to refuse (nullbound's live tree: main `0.90.3`, building
  `0.90.3.2`). **Resolved:** every milestone whose id equals the PR version decides — `done` admits,
  any other status refuses naming the status, overriding the hotfix reading. Row added.
- **MAJOR (pass 1):** `status:` was grepped across the whole file, unanchored, so a schema example in
  the body vouched for the file. **Resolved:** `fm()` reads the front block only (opening fence to
  the CLOSING fence — an unclosed fence yields nothing), anchored, either quote style, CR stripped,
  trailing whitespace trimmed. Tests: body `status: done` under planning refuses; single-quoted id
  admits; unclosed fence refuses; `done   ` admits.
- **MAJOR (pass 1):** D8's hotfix tolerance keyed on ANY milestone in the tree, so `0.90.5.1`
  (planning) and `0.90.3.2.7` (building) passed. **Resolved:** only a `done` milestone qualifies —
  the released one retire's lag-by-one keeps — and N is an ASCII positive integer without a leading
  zero. Tests moved to a released sibling; `0.1.1` on the building id refuses, `٣` and `01` refuse.
- **MAJOR (pass 2, rule 4):** the milestone loop never counted its census, so a hotfix-shaped PR over
  an absent or empty `PM_ROADMAP` printed OK with nothing scanned. **Resolved:** a non-directory
  `PM_ROADMAP` and a roadmap with no `milestone.md` are refusals. Two rows added.
- **MINOR:** header, README row and D8 docstring said only "strictly greater". **Resolved.**
- **Accepted NITs:** mismatched quote pairs (`id: "0.9'`) are read as the id; a done and a building
  milestone both carrying the PR id in different dirs refuses (verified).
- **Not verified:** a real GitHub Actions run of the workflow; macOS/bash 3.2 execution (by eye).
