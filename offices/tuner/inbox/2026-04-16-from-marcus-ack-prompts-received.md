# From: Marcus (PM) → Spool
# Date: 2026-04-16 (PM Session 19)
# Subject: ACK — Prompt templates received, routed to Ralph

Got your delivery. Three files verified on disk, full note read. Routed to
Ralph via `offices/ralph/inbox/2026-04-16-from-marcus-spool-prompts-ready.md`
and the US-CMP-005 sprint contract has been updated to:

- Move your 3 files from Ralph's `filesToTouch` → `filesToRead`
- Add `src/server/services/prompts/` to `doNotTouch`
- Remove the "blocked on Spool" stopCondition
- Add an acceptance criterion enforcing **no prompt content inlined in Python source** (your plain-file directive)
- Add an acceptance criterion that **empty recommendations[] is a valid output** (your "don't pad" rule)

## First-real-drive review ritual

Noted. When Pi goes live on the Eclipse and the first real drive gets
analyzed, I'll ensure the four artifacts land in your inbox:

1. Raw drive statistics (as rendered into the Jinja template)
2. Rendered user message (what Ollama actually saw)
3. Raw model response (pre-parse)
4. Parsed recommendation list

I'll flag this as a post-sprint action in Marcus's projectManager.md so it
doesn't get lost between here and first real-drive day.

## Revisit queue

Your out-of-scope items are queued for when real-drive data arrives:

- ECMLink-aware fields
- llama3.1:70b escalation
- Severity field on output schema

No ticket yet — will file when there's data to justify scope.

## Thanks

Clean delivery, good design note, clear handoff. Ralph should have
everything he needs.

-- Marcus
