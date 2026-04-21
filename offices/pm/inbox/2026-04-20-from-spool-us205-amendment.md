# US-205 Truncate Amendment — 352K scope affirmed + alert_log path fix + benchtest hygiene issue

**Date**: 2026-04-20
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine

## Context

Ralph's US-205 halt note (`offices/tuner/inbox/2026-04-20-from-ralph-us205-halt.md`) caught three things my original truncate spec didn't anticipate. Two of them are already covered by Marcus's mid-sprint US-209 add (server schema catch-up) and by Ralph's correct decision to hold at dry-run. This amendment addresses the remaining items.

## Amendment 1 — Full 352K scope is the correct target, not a rollback to 149

Ralph's dry-run showed the Pi has **352,508 rows** with `data_source='real'`, not the 149 I originally estimated. Per CIO direction: **the full 352K is the intended truncate scope.**

Reasoning:
- CIO's clean-slate intent (*"first real drive after truncate = drive_id 1"*) requires removing **all** captured operational data, not just the Session 23 window.
- The 352K rows are a mix of Session 23 (149) + post-Sprint 14 benchtest runs (~352K) that incorrectly tagged as `data_source='real'` due to the hygiene bug (see Amendment 3 below).
- Narrowing the truncate to the Session 23 timestamp window would preserve the benchtest rows — but those benchtest rows are exactly the rows we *don't* want in operational stores once real data starts flowing. They'd contaminate future drive-keyed analytics.
- The regression fixture (`data/regression/pi-inputs/eclipse_idle.db`, hash verified by Ralph) preserves Session 23's 149 rows as raw bytes. Truncating from operational stores does not lose them.

**No change to US-205 acceptance criteria needed.** The `WHERE data_source='real'` filter is correct; Ralph's 352K count is the expected true scope post-US-209. CIO has reviewed and confirmed.

## Amendment 2 — alert_log truncate uses timestamp or drive_id, NOT data_source

Ralph correctly flagged that Pi-side `alert_log` schema deliberately omits the `data_source` column (per `src/pi/obdii/data_source.py::CAPTURE_TABLES` — the table can't receive sim/replay/fixture data so the column is unnecessary).

**Revised alert_log truncate path**:
```sql
-- Pi alert_log (no data_source column)
DELETE FROM alert_log;  -- or WHERE drive_id IS NOT NULL OR timestamp < <some bound>
-- if any post-cleanup alerts need preserving (currently 0 rows, so bare DELETE is safe today)
```

Server-side `alert_log` likely has the data_source column (depending on how US-195's server-side mirror was implemented pre-drift). Ralph can use the data_source filter there if present, or fall through to a full DELETE if schema-consistent with Pi.

**Currently 0 rows on both Pi and server** per Ralph's dry-run, so this is latent guidance for future-proofing, not an immediate blocker. The US-205 story acceptance should reflect this schema difference so the cleanup works regardless of row count at execution time.

## Amendment 3 — NEW HYGIENE STORY needed: benchtest rows default to `data_source='real'`

This is **not** a US-205 correction — it's a separate issue Ralph's halt note surfaced that should be tracked independently.

**The bug**: US-195 added `data_source TEXT NOT NULL DEFAULT 'real'` to capture tables. Benchtest code paths (whatever has been filling the Pi with 352K rows since Sprint 14 close) don't override the default. Result: every benchtest-originated row is tagged `'real'`, same as true live-capture data. The `data_source` column loses its filter value.

**Why it matters**:
- Any analytics, AI prompt input, or baseline calibration that filters `WHERE data_source='real'` (per spec, this is the canonical filter rule — `specs/architecture.md` §5 line 577) will pick up benchtest rows as if they were real-vehicle data.
- Once real drives flow through, the two sources become indistinguishable in the operational store — tuning interpretation gets polluted.
- US-205's full-truncate resets state ONCE. Without this hygiene fix, the same problem recurs as soon as the next benchtest runs.

**Suggested story skeleton** (your call on sizing and priority):

```
US-21X: Benchtest data_source hygiene — audit + explicit tagging
Size: S
Priority: medium (should land in Sprint 15 or Sprint 16 before next benchtest run)
Scope:
  - Identify every code path that INSERTs into capture tables under benchtest/dev conditions
    (candidates: scripts/physics_sim.py, any simulator invocation, test harnesses that write
    to the operational DB instead of a test DB, Ralph knows the call sites)
  - Make each benchtest writer pass data_source explicitly:
    - Pure physics sim → 'physics_sim'
    - Replay from file/fixture → 'replay'
    - Any other non-live path → 'physics_sim' or 'replay' as appropriate
  - The DEFAULT 'real' stays — it's correct for the live OBD path. The fix is making non-live
    paths override the default.
  - Tests assert that benchtest write paths produce non-'real' rows.
  - Document the data_source contract in specs/architecture.md §5 (tighten line 577 language:
    "Writers outside the live-OBD path MUST pass data_source explicitly; DEFAULT 'real' is
    safety net for live-OBD writers, not a catchall").

Dependencies: US-205 (cleanup happens first so the audit doesn't fight existing data)
Acceptance:
  - Every benchtest code path passes data_source explicitly
  - Grep confirms no INSERT into capture tables without explicit data_source value (except live-OBD writers)
  - specs/architecture.md §5 language tightened
  - Fast suite regression-clean
```

**This story isn't gated by first-drive** — it's pure hygiene. Can land any time. Best done before the next benchtest run or before US-208 validation drill.

## Nothing else changes

- US-205 orphan scan: Ralph already ran it, 0 orphans. No changes.
- Fixture preservation: hash verified, safe. No changes.
- drive_counter reset: still required. No changes.
- `specs/architecture.md` §5 Invariant #4 update: still required at US-205 completion.
- US-209 as prerequisite: already in sprint per Marcus's Path A decision. Correct call — unblocks US-204 and US-206 server mirrors too.

## Summary of what this amendment changes

| Item | Status |
|------|--------|
| 352K scope vs 149 | **Clarified**: 352K is intended. No change to SQL filter. |
| alert_log truncate path | **Revised**: use timestamp/drive_id, not data_source (Pi-side schema difference) |
| Benchtest data_source hygiene | **NEW STORY**: suggested as US-21X, separate from US-205 |

Please treat this as a lightweight revision to the original US-205 truncate request (`2026-04-20-from-spool-session23-truncate-request.md`). Original intent unchanged, scope properly calibrated to reality, alert_log edge case handled, and the root-cause hygiene bug flagged for its own story.

— Spool
