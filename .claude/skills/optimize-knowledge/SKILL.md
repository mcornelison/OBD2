---
name: optimize-knowledge
description: Periodic housekeeping for any agent office. Shrinks the file loaded at every session start by moving detail into lazy-loaded knowledge files, removes redundancy, repairs stale pointers, and flags content the whole team needs. Use monthly, when CLAUDE.md grows past ~6KB, when knowledge/ passes ~30 files, or when asked to tidy, optimize or clean up knowledge.
---

# optimize-knowledge — periodic housekeeping

**The goal is a smaller startup file.** `CLAUDE.md` is read in full at every session
start, by every agent, forever. Every kilobyte in it is a tax on every session.
Everything else here serves that: remove redundancy, push detail into files that
load only when needed, and leave `CLAUDE.md` as a thin index plus pointers.

Scope: **your own office only**. Paths are relative — your working directory is
your office. This skill is identical in every office of every project.

> ## NEVER TOUCH `knowledge/MEMORY.md`
> It is append-only and lives inside the tree you are compacting, so structure does
> not protect it — this rule does. Do not summarise, reorder, dedupe against, or
> tidy it. Compacting an append-only decision log destroys what makes it
> trustworthy.

**Measure first.** Record `CLAUDE.md`'s size and the file count under `knowledge/`
before you start. You will report the delta.

Four passes, strictly in this order — lossless before lossy.

## Pass 1 — Deduplicate (lossless)

Hash every file in scope except `MEMORY.md`. Exact duplicates: keep one canonical
copy, leave a stub naming the new path.

Report **near**-duplicates (same subject, different wording) as a list for a human.
**Never merge them automatically** — consolidating two documents that disagree in a
detail you did not notice is how a wrong fact becomes the canonical one.

Some duplication is **load-bearing**; exclude it before hashing: anything under
`.claude/` (skills and commands are discovered by proximity — each office needs its
own copy), live/archived pairs, and files a script opens by path (a stub is valid to
a human and garbage to `grep`).

## Pass 2 — Shrink the startup file (the point of this skill)

Work through `CLAUDE.md` line by line and ask of each: **does a session need this
before it knows what it is doing?**

- **No** → move it into a `knowledge/<topic>.md` file and leave a one-line pointer.
  Create the sub-file when a topic exceeds a few lines. Name it for the topic, not
  the date.
- **Live state** → replace the value with a **pointer to the source-of-truth data
  file**, never a snapshot. Snapshots are stale by the next session and are the most
  common reason these files grow.
- **Resolved incidents** → one line: date, root cause, durable fix, link. Long form
  goes in one canonical home under `knowledge/`.
- **Anything repeated** in both `CLAUDE.md` and `CHARTER.md` → keep it in
  `CHARTER.md` (the mandate) and point at it.

**Move content; do not retype it.** If something you expected is missing, SAY SO.
Never fill a gap by inference.

Target: `CLAUDE.md` under ~6KB. Identity, pointers, and a live-state table should
be nearly all of it.

## Pass 3 — Repair stale pointers

A pointer that resolves to nothing is worse than a missing one: it looks like
information. Check, and fix or remove:

- Every path mentioned in `CLAUDE.md` and `CHARTER.md` — does it exist?
- `.claude/settings.local.json` permission globs — do they still match real paths?
  A glob that no longer matches does not error; it produces a **permission prompt**,
  and a headless agent hangs on one.
- References to files, directories or commands that were renamed or evicted.

Report every stale entry you find, with what you did about it.

## Pass 4 — Shareability audit

Knowledge the team needs must not stay private to this office:

| Content | Belongs in |
|---|---|
| Architecture, interfaces, data contracts, invariants | `specs/` (repo) |
| Runbooks, deploy and recovery steps | `docs/` or `server/` (repo) |
| Cross-office vocabulary and definitions | `../_shared/library/` |
| Know-how useful to every office | `../_shared/knowledge/` |

**Propose; do not promote unilaterally.** Write the proposal to `outbox/` and file
it to the architect's inbox (the PM's, for process content). Promotion into the repo
is a repo change and goes through a ticket — an office cannot merge to trunk.

Keep in the office: session narrative, working notes, in-progress reasoning.

Never edit another office's files. Surface drift you notice; do not fix it yourself.

## Report

    CLAUDE.md      <before> -> <after> bytes   (the headline number)
    knowledge/     <before> -> <after> files
    exact duplicates removed:   <n>
    near-duplicates for review: <list>
    stale pointers repaired:    <list>
    promotion candidates:       <list>
    MEMORY.md unmodified:       confirmed
