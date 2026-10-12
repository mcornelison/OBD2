---
name: read-inbox
description: Read and triage this office's inbox at any point in a session, without a full boot. Use when asked to check messages, check the inbox, or see what came in.
---

# read-inbox — check and triage messages

Paths are relative: your working directory **is** your office.

1. List `inbox/`, newest first. Treat anything newer than the "Last Updated" in
   your context file as unread.
2. Messages are written in **A2AL** shorthand — use the `a2al` skill to read them.
   Markdown is reserved for content a human wrote.
3. Do **not** read `inbox/archive/` unless the task needs it.

## Triage each item

- **Act now** — inside your mandate (`CHARTER.md`) and blocking someone.
- **Queue** — yours, not urgent. Note it; do not silently drop it.
- **Not mine** — belongs to another office. Reply via `outbox/` saying so and who
  should own it. Do not fix it yourself, and do not edit another office's files.

## Report

For each unread item: sender · date · subject · your triage decision. Then state
what you intend to do next.

Archiving is part of `closeout`, not this skill. Reading an inbox must not change it.
