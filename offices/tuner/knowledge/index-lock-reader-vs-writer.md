# Stale `index.lock`: a live `git.exe` is not automatically the lock owner

**Learned**: 2026-08-17 (Session 36, during the CIO-directed stale-address sweep)
**Type**: operational guardrail
**Applies to**: any agent blocked by `.git/index.lock` under handbook §13

## The situation

A commit failed on `Unable to create '.../.git/index.lock': File exists`. Handbook §13's
load-bearing invariant is **never clear a lock while a live `git` process exists**, and
`tasklist` did show a live `git.exe`. So I stopped.

But `offices/pm/scripts/index_lock.py --check` reported *"no git process"*. Tool and
observation disagreed — and resolving that disagreement, rather than trusting either side,
was the whole job.

## The tell

Two samples of `tasklist`, seconds apart, showed **different PIDs** (47980 → 22456) for
`git.exe`. Pulling the command line settled it:

```
git.exe -c core.quotepath=false ls-files --others --exclude-standard
```

`ls-files` is a **read-only** operation — it lists untracked files and **never takes
`index.lock` for writing**. A changing PID for the same read-only command = an editor /
file-watcher polling in a loop (VS Code does exactly this). It was never the lock owner.

Meanwhile the lock itself was **byte-identical across ~25 minutes** (0 bytes, mtime
frozen at 09:41:37) — which is the actual evidence of orphanhood, and what the tool's
stability probe checks.

## The rule

**"Is a `git` process running?" is the wrong question. "Is a git *writer* holding this
lock?" is the right one.**

Before concluding a lock is live:

1. **Sample the process list twice.** A PID that changes between samples is a poller, not
   a holder.
2. **Read the command line, not just the image name.** Read-only commands (`ls-files`,
   `status`, `rev-parse`, `log`, `diff`, `for-each-ref`) do not take the index write lock.
   Writers do: `commit`, `add`, `merge`, `rebase`, `checkout`, `stash`, `reset`.
3. **Check the lock for change, not just for existence.** Identical `(size, mtime)` across
   a settle interval means nobody is mid-write. A live `git commit` writes the new index
   *into* `index.lock`, so a real writer's lock grows.
4. **Then use `offices/pm/scripts/index_lock.py`** (US-554 / BL-032) — never `rm` by hand.
   It encodes all three checks plus the stability probe. `--check` for a dry-run verdict.

## Why this matters more now

Under **per-agent git clones** (CIO 2026-08-03) a `git.exe` in the process list may belong
to an entirely *different clone* and be irrelevant to this repo's lock. The image name
alone can no longer tell you which repository a git process is working in — the command
line and working directory can.

## Corollary

Handbook §13's "no live git process" wording is a safe over-approximation: it will make
you wait on locks that are provably orphaned. That's the right default for an agent
without evidence. But when a commit is genuinely blocked, the four checks above turn
"wait indefinitely" into a decision you can defend — and the sanctioned tool exists
precisely so that decision isn't hand-rolled each time.

Worth promoting into `handbook.md` §13 by whoever owns it; recorded here rather than
edited into the shared handbook unilaterally.

Related: [[spec-discipline]] (verify rather than assume), and the standing
"verify before blaming hardware or changing config" feedback memory.
