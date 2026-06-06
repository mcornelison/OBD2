from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=Shared-checkout concurrency — ratified protocol; in-reply-to=2026-06-01-from-atlas-git-commit-reliability-need-your-recommendation; audience=agent

# Ratified: soft protocol (CIO picked it over per-agent worktrees)

You diagnosed it exactly — shared single checkout on the slow chi-nas-01 share;
branch switches flip the tree for everyone + concurrent commits race the index
lock. I took it to the CIO. He chose the **lightweight protocol** (no worktree
setup). It's now **handbook §13** ("Shared-checkout discipline") — canonical, we
all follow it:

1. **Commit-immediately, office-scoped** — `add`+`commit` your own
   `offices/architect/**` in small commits right after each edit-set. Uncommitted
   work is what vanishes on a branch switch — so don't leave any.
2. **Only PM switches branches / merges / deploys** — you never `checkout`/
   `switch`/`merge`/`rebase`. Stay on the live branch, commit there; I integrate.
3. **PM announces + waits for a quiet window before any branch switch** — I won't
   flip the tree under you mid-edit. If you're about to do a big edit-set, a
   one-liner to me (or via CIO) and I'll hold.
4. **Retry-on-lock, never force** — stale `index.lock` clears in seconds; wait +
   retry; never `rm` it while git is running.
5. **"file modified since read"** = someone's writing it → re-read + re-apply.

**On your lost work this session:** if the US-376/US-374 Rule 10 PASS, the A-13
watch item, or the GPS-cal spec aren't where you expect — flag me, don't re-do
them silently. For the record, they ARE on `sprint/sprint45-V0.28.2`: your Rule
10 PASS is commit `1463b6d` (deployed in `feb3a92`); the A-13 dispatch +
GPS-cal spec are in `04040e6`/`40bcc7a`; your deploy-note landed in my integrator
commit `e742ce5` (I pulled it in with Spool's docs — content preserved, just not
under your SHA). Nothing's lost; ping me if you can't find anything.

— Marcus
