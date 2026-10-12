---
name: closeout
description: End-of-session closeout for any agent office. Writes an append-only log entry, updates context, records durable decisions to memory, delivers outbound messages, and states blockers. Use when finishing a session, wrapping up, or handing off.
---

# closeout — session close

Leave the office readable by the next session, which may be a different agent.
Paths are relative: your working directory **is** your office.

1. **Append one timestamped file to `log/`.** Never edit an existing log file —
   one file per entry is what makes concurrent writes safe without locking.

2. **Update your context file** (the one `CLAUDE.md` names), including its
   "Last Updated" line.

3. **Record durable decisions** by appending to `knowledge/MEMORY.md`.
   A decision is durable if a future session would otherwise re-litigate it.
   State the decision, why, and what it rules out.
   **Append only — never edit or delete an existing entry.**

4. **Deliver outbound messages.** Write to `outbox/` and place a copy in the
   recipient's `inbox/`. Use the `a2al` skill for agent-to-agent messages;
   markdown is for content a human reads.

5. **State open blockers explicitly.** An unstated blocker is a blocker nobody
   owns. If you are headless, this is the only way a human learns you are stuck.

## Report

Log entry written · context updated · memory entries appended · messages sent ·
blockers outstanding.
