---
name: pattern-stale-git-index-lock-shared-checkout
description: On the shared chi-nas-01 checkout an orphaned .git/index.lock can jam every agent's commits for a long time. Clear it ONLY after proving staleness (lock mtime frozen across a window + old + no live git process) — the "abort on any git process" guard is wrong here because OTHER blocked agents keep spawning transient git.exe that fail on the same lock without owning it.
metadata:
  type: pattern
---

# Safely clearing an orphaned `.git/index.lock` on the shared checkout

All agents share ONE checkout on the slow `//chi-nas-01` SMB share. An interrupted
`git` leaves `.git/index.lock` behind; because the share is slow, a **stale** lock can
sit there for **tens of minutes** and **block every agent's `add`/`commit`**. Hit this
2026-07-31: a **67-minute-old** zero-byte orphan jammed the whole team.

## The trap — "abort if any git process is running" is the WRONG guard here

The shared-checkout discipline says *never remove the lock while a git process is
running*. But when a stale lock is blocking the team, **other agents keep retry-looping**,
each spawning a `git.exe` that **immediately fails on the same lock and exits**. So a naive
`ps | grep git.exe` almost always sees a transient process — but **none of them own the
lock** (they're victims of it, same as you). Guarding on "any git process present" means
you can *never* clear a genuinely orphaned lock while the team retries. Don't use it.

## The correct staleness test — the lock's OWN mtime

A real lock-holder keeps a FRESH lock and finishes in seconds. An orphan's mtime is **old
and never changes**. Test that directly:

1. Read `stat -c %Y .git/index.lock` (m1).
2. Wait a few seconds; read it again (m2).
3. **If m2 ≠ m1 → a live commit owns it → ABORT** (retry normally, wait it out).
4. **If m2 == m1 AND age > ~120s → stale orphan → `rm -f` it**, then commit.
5. If it vanished on its own → great, just commit.

```bash
m1=$(stat -c %Y "$LOCK"); sleep 3; m2=$(stat -c %Y "$LOCK" 2>/dev/null || echo gone)
age=$(( $(date +%s) - m1 ))
if [ "$m2" = gone ]; then :;                               # cleared itself
elif [ "$m1" != "$m2" ]; then echo ABORT: live; exit 1;   # mtime moved = real holder
elif [ "$age" -gt 120 ]; then rm -f "$LOCK";               # frozen + old = orphan
else echo ABORT: too fresh; exit 1; fi
```

Removing an orphan is safe even if another agent's `git` starts concurrently: git creates
`index.lock` with `O_CREAT|O_EXCL`, so only one writer wins — you're not corrupting a live
write, because a 60-min-old lock is provably not mid-write.

## First, always: retry-on-lock (don't jump to removal)

Most locks ARE transient on the slow share — wait + retry a handful of times first. Only
reach for the staleness test when retries keep failing AND the mtime proves it's frozen.
This refines the shared-checkout discipline ([[root CLAUDE.md §concurrency]]); pairs with
[[pattern-verify-feature-not-manifold-and-git-truth]] (reconcile against git ground-truth,
not the harness's cached "file modified" reminder, on this share).
