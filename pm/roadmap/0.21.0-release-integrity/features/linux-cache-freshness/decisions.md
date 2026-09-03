# Decisions — linux-cache-freshness

## R1 — 2026-09-03 — review record (code-reviewer, two passes)

- **Finding (MINOR, pass 1):** a `stat` that echoes its format string exits 0, so `mtime_ns`
  returned `%9Y0000000`, `[ -lt ]` errored, and `|| continue` read the artifact as fresh.
  **Resolved:** any non-numeric result answers nothing and routes to the strictly-newer `find`
  fallback. Probed: BSD `%Fm` shape, a fraction shorter than nine digits, whole-second GNU output,
  absent stat, busybox's echoed format.
- **Verified by the reviewer:** `--self-test` 13/13; the `touch -r` equal-timestamp case MISSes
  against the HEAD function; bash 3.2 constructs by eye; `shellcheck -x` clean.
- **Rejected:** shifting the stamp one second into the past (would read an artifact written up to a
  second before the run as fresh); `[ -nt ]` (whole seconds on bash 3.2).
