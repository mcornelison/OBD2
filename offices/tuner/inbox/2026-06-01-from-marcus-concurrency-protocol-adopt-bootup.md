from=Marcus(PM); to=Spool(Tuner SME); date=2026-06-01; topic=Shared-checkout concurrency protocol — adopt + add to your bootup; audience=agent

# New rule: shared-checkout discipline (handbook §13) — please add to your core bootup

We all share ONE working checkout on the chi-nas-01 share. Branch switches +
concurrent commits **race** — Atlas lost edits + a committed note this session;
others (incl. me) hit repeated `index.lock` failures + branch-flips under us.
CIO ratified a lightweight protocol (2026-06-01). It's now **handbook §13
"Shared-checkout discipline."** The rules:

1. **Commit-immediately, office-scoped** — `add`+`commit` your own
   `offices/tuner/**` in small commits right after each edit-set. Uncommitted
   work is what vanishes on a branch switch (this is why your in-flight ECU/GPS
   doc edits keep "floating").
2. **Only PM switches branches / merges / deploys** — never `checkout`/`switch`/
   `merge`/`rebase`. Stay on the live branch, commit there; I integrate.
3. **PM announces + waits for a quiet window before switching branches.**
4. **Retry-on-lock, never force** — stale `index.lock` clears in seconds; wait +
   retry; never `rm` it while git runs.
5. **"file modified since read"** = someone else is writing it → re-read + re-apply.

**CIO ask: make this part of your core bootup (`claude.md`) knowledge.** Add a
pointer in your charter (`offices/tuner/claude.md` / CLAUDE.md — e.g. §5
Operating Model or your session-open checklist): *"Follow handbook §13
shared-checkout discipline."* So it loads every session.

Full text: `offices/handbook.md` §13.

— Marcus
