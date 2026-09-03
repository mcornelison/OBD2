---
name: optimize-knowledge
description: Periodic knowledge maintenance for any agent office. Deduplicates losslessly, compacts knowledge into lazy-loaded files, and flags content that belongs to the whole team. Use monthly, when knowledge grows past ~30 files, or when asked to tidy or optimize knowledge.
---

# optimize-knowledge — periodic maintenance

Scope: `knowledge/` in **your own office only**. Paths are relative.

> ## NEVER TOUCH `knowledge/MEMORY.md`
> It is append-only and it lives inside the tree you are compacting, so structure
> does not protect it — this rule does. Do not summarise it, reorder it, dedupe
> against it, or "tidy" it. Compacting an append-only decision log destroys the
> property that makes it trustworthy.

Three passes, strictly in this order — the lossless one first.

## Pass 1 — Deduplicate (lossless)

Hash every file in `knowledge/` except `MEMORY.md`. Exact duplicates: keep one
canonical copy, leave a stub naming the new path.

Report **near**-duplicates (same subject, different wording) as a list for a human.
**Never merge them automatically** — consolidating two documents that disagree in a
detail you did not notice is how a wrong fact becomes the canonical one.

Some duplication is **load-bearing** and must be excluded before you hash: files
discovered by proximity (anything under `.claude/`), live/archived pairs, and files
a script opens by path — a stub is valid to a human and garbage to `grep`.

## Pass 2 — Compact (lossy, therefore fenced)

"Do not forget" means **load-bearing, not verbatim**.

- Lift detail out of `CLAUDE.md` into the right lazy-loaded file under `knowledge/`,
  leaving a thin index plus pointers.
- Live state is a **pointer to the source-of-truth data file**, never a snapshot.
  Snapshots drift the moment the next session runs.
- Resolved incidents compress to one line — date, root cause, durable fix, link —
  with the long form in one canonical home.
- **Move content; do not retype it.** If something you expected is missing, SAY SO.
  Never fill a gap by inference.

## Pass 3 — Shareability audit

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

## Report

Files and bytes before/after · exact duplicates removed · near-duplicates listed for
review · promotion candidates proposed · **confirmation that `MEMORY.md` was not
modified**.
