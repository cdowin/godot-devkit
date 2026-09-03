---
id: 0.21.0/linux-cache-freshness/nanosecond-at-or-after
feature: 0.21.0/linux-cache-freshness
milestone: "0.21.0"
name: mtime_ns and an equal-timestamp corpus case
status: review
owner:
depends_on: []
---

# mtime_ns and an equal-timestamp corpus case

Replace `find -newer` in `stale_cache_artifacts` with an `mtime_ns` compare (GNU `stat -c '%.9Y'`, BSD `stat -f '%Fm'`, strictly-newer `find` as the fallback) and add the `touch -r` equal-timestamp corpus case. Proof: the case MISSes against HEAD's function, the corpus is 13/13, nullbound's `make check` is green in a Linux container.
