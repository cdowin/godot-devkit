---
id: 0.21.0/linux-cache-freshness
milestone: "0.21.0"
name: import_cache.sh reads at-or-after freshness on Linux
status: building
reviewed:
phase:
depends_on: []
consumed_by: []
---

# import_cache.sh reads at-or-after freshness on Linux

What it makes true: `stale_cache_artifacts` reads an artifact as fresh when its mtime is at or after
the stamp's, at nanosecond resolution on GNU and BSD `stat` alike, falling back to strictly-newer
`find` only when neither answers. A corpus case pins it: an artifact `touch -r`'d to the stamp's
exact timestamp reads fresh — deterministic on every platform, a MISS against the old comparison.

Why: Linux stamps two files written in the same clock tick (~ms) with identical nanoseconds, so
`find -newer` (strictly newer) reported a cache refreshed right behind the stamp as stale, the
runner's `--self-test` was red on every Linux container, and `make check` failed for a reason
unrelated to the tree. macOS's fine clock hid it for a release.
