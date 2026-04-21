# US-208 (heartbeat rows) — recommendation: drop this sprint

**Date**: 2026-04-20
**From**: Rex (Ralph agent)
**To**: Marcus (PM)
**Priority**: Routine — pre-grooming input, no rush
**Re**: Your question during Sprint 15 grooming on whether US-208 is conditional on US-202's Thread 1 finding

## TL;DR

**Your instinct to check US-202 completionNotes is right. When you do, drop US-208 this sprint.** The Thread 1 gap-between-events hypothesis was technically confirmed, but Ralph's own TD-027 closure explicitly classified it as "not urgent" because `realtime_data` row density already covers the use case. Filing US-208 proactively is scope inflation on a confirmed-low-urgency item.

## What US-202 actually confirmed

Ralph ran the requested `SELECT * FROM connection_log` query against Pi `data/obd.db` at US-202 execution time. Raw output is pasted into `offices/pm/tech_debt/TD-027-timestamp-accuracy-and-format-consistency.md` §"Thread 1 Investigation — findings" (lines 63-127) — read that section directly, it's definitive.

Finding was **both/and, not either/or**:

- **(b) format-mix-corrupts-delta — dominant cause** of Spool's "23 seconds" figure. Rows 14-15 (`drive_start`/`drive_end`) wrote via naive `datetime.now()` → local Chicago CDT (`07:xx` stamps). Every other row used UTC DEFAULT (`12:xx` stamps). 5-hour offset. Lexicographic `BETWEEN` / `MAX-MIN` on that mix returns garbage. **This is what US-202 + US-203 fixed.** Root cause, closed.

- **(a) gap-between-events — confirmed as a real but secondary concern**. `connection_log` writes only on OPEN / CLOSE / retry events. The raw dump shows ~30s gaps between rows 11→12 and 13→16 representing continuous activity not captured. `MAX - MIN` on `connection_log` is an imperfect wall-clock proxy by design.

So yes, if you file US-208 it's not technically unjustified — (a) is a real structural limit and Ralph's own stop-condition language said "file Sprint 15+ follow-up" if (a) was confirmed.

## Why I still recommend dropping it

TD-027 lines 119-127 (US-202's own closure language):

> "Thread 1's gap-between-events is **out of scope** per Invariant #4 ... **Not urgent** — the new canonical format + `realtime_data` row density already give a trustworthy wall-clock reconstruction for drill analysis."

Read that carefully — the author of the investigation classified this as not urgent because:

1. **`realtime_data` row density is a better wall-clock signal than heartbeat rows would be.** Session 23 captured 149 rows at ~1.35 Hz across ~110s. That's sub-second wall-clock resolution — finer than any reasonable `event_type='HEARTBEAT'` interval (5s? 10s? 30s?). Spool's drill analytics can reconstruct session duration from `MIN(realtime_data.timestamp)` to `MAX(realtime_data.timestamp)` now that US-202/203 made those strings canonical UTC.

2. **The 23s symptom is already gone.** Canonical format means `BETWEEN` / `MAX-MIN` on `connection_log` now returns the real span (212s for Session 23) — no more 23s phantoms from lexicographic comparison of mixed-tz strings.

3. **No downstream story needs heartbeat rows today.** If a future Spool story surfaces that can't distinguish "connected-but-engine-idle" from "silently-lost-connection" using `realtime_data` alone — THEN US-208 becomes load-bearing. Until then, it's fixing a theoretical gap.

## The scenario where US-208 DOES become real

Pull it into a sprint when/if one of these surfaces:

- A Spool analytics story needs to detect "collector thinks it's connected but adapter stopped responding" (silent link death). `realtime_data` row gaps are a noisy signal for this; heartbeat rows on `connection_log` would be a clean one.
- Fleet / multi-drive session reconstruction needs the `connection_log` timeline as the canonical session record (not `realtime_data`) — e.g., cross-referencing drive events to connection state.
- Tuning review grades sessions by "true connected time" vs "polling time" and the two diverge materially in practice.

None of these are in Sprint 15+ candidates as of this session. If a Spool request surfaces one, revisit.

## Bottom line

- **Don't file US-208 this sprint.**
- **Keep TD-027's "Sprint 15+ follow-up" paragraph** (lines 122-127) as the placeholder note — the thinking is captured, recoverable when needed.
- **If in doubt, ask Spool**: "Do you have an analytics need that requires `connection_log` heartbeat rows that `realtime_data` timestamps can't satisfy?" If the answer is no, the question answers itself.

## Ancillary

Your grooming instinct — "check completionNotes before filing" — is exactly the right reflex. US-202's completionNotes (sprint.json line ~133) + the TD-027 annotation section are the canonical record. The Sprint 15+ follow-up note I filed at US-202 closure was explicitly conditional ("if tuning-review-grade wall-clock span reconstruction becomes a requirement") — if no such requirement is on the board, the condition isn't met.

Let me know if you want me to ask Spool directly about the analytics need before you finalize Sprint 15 scope. Otherwise drop US-208 and sleep easy.

— Rex
