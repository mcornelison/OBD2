---
name: hello
description: Session startup for any agent office. Loads the office charter, memory and knowledge index, scans the inbox, and reports what was loaded. Use at the start of every session, or when asked to boot, start up, or get current.
---

# hello — session startup

Paths are relative: your working directory **is** your office. This skill is
identical in every office of every project.

## Load, in this order

1. `CLAUDE.md` — who you are, your pointers, your live-state table.
2. `CHARTER.md` — your mandate: what you decide, and what you never decide.
3. `knowledge/MEMORY.md` — durable decisions for this office. Append-only.
4. `../_shared/knowledge/MEMORY.md` — decisions shared across all agents.
5. `inbox/` — anything newer than the "Last Updated" in your context file.

Then **lazy-load only what the task needs** from `knowledge/`. Read the index or
filenames; do not read the tree.

## Report

State plainly, so the operator can confirm you are current:

- Current state and phase
- New inbox items — sender, date, subject for each
- Active risks or blockers
- **Recommended next action**

## Do not

- Do not read backlogs, reference sets, or history at boot. On demand only.
- Do not read another office's files.
- If a pointer in `CLAUDE.md` resolves to nothing, **say so**. Do not infer what it
  probably meant.
