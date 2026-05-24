# US-338 / I-033 — BT-no-reconnect after engine cycle (P1)

**From:** Marcus (PM)
**To:** Ralph (Developer)
**Date:** 2026-05-13
**Sprint:** V0.27.10 bug-fix patch (interactive — no sprint.json this time; CIO will work with you live as questions come up)
**Branch:** `sprint/sprint36-bugfixes-V0.27.10` (Marcus created; branched from V0.27.9 deployed tip @ 872580a)
**Priority:** P1 (telemetry loss on every multi-leg trip)
**Size estimate:** M (PM read; Ralph to confirm)

---

## What broke

On 2026-05-13 CIO drove a 2-leg trip (home → pharmacy → ~9 min engine-off errand → home). Pi stayed powered throughout. **Drive 12 captured leg 1 cleanly** (3591 rows, 19:01:59 → 19:10:24 UTC). **Leg 2 was completely lost** — no `drive_start`, no realtime_data with `drive_id=13`, no `connection_log` row for the reconnect attempt that never happened. 549 orphan `drive_id=NULL` realtime_data rows on Pi (631 on server window) capture the post-drive_end polling that continued at the data-logger level without a drive context.

Spool already sent you the technical fix-direction note this morning: **`offices/ralph/inbox/2026-05-13-from-spool-bt-no-reconnect-after-engine-cycle.md`**. Read that FIRST — it has the empirical timeline, the repro signature, the candidate fix directions (A/B/C), and the operational context (the "Pi has two normal power modes: car-fuse-box AND wall-power-debug" warning that rules out the AC-blip-trigger approach).

PM framing this note adds on top of Spool's tech depth:
- **Bug paper:** `offices/pm/issues/I-033-bt-no-reconnect-after-engine-cycle.md` (full forensic timeline + impact analysis + cross-refs)
- **Sprint home:** branch above; commit when ready, push when you want PM review
- **Coordination:** CIO Mike will work with you interactively on this sprint — if you need to clarify scope, fix direction, or hit a blocker, just ask in chat (no formal BL- needed for this sprint unless we hit something architectural)

## Acceptance (PM-level)

1. **Pre-flight audit:** `rg "_performConnect|_handleConnection|reconnect|heartbeat" src/pi/obdii/` — map the current reconnect lifecycle; confirm the gap matches Spool's "fix direction B" (heartbeat-fail handler gives up silently) and/or "fix direction C" (no periodic BT-state poll when DriveDetector idle).

2. **Fix:** implement Spool's preferred direction (B = heartbeat-fail kicks fresh `_performConnect` cycle on drop) OR hybrid (B + C). Mode-agnostic — must work in BOTH car-fuse-box AND wall-power-debug scenarios. Do NOT tie reconnect to `power_log` AC-blip — that false-fires in debug mode (Spool's note explains why).

3. **DriveDetector re-arm:** on successful reconnect, DriveDetector must mint a fresh `drive_id` when the next engine-on fires. Today's failure mode left `drive_counter.last_drive_id=12` because no second `drive_start` was issued.

4. **Observability:** every `connect_attempt` should write a row to `connection_log` (so the next time this bug class appears, it's auditable from the DB instead of requiring journal grep).

5. **Synthetic regression test:** mirror Spool's repro signature:
   1. start with paired BT + adapter powered → `connect_success` → DriveDetector sees `drive_start`
   2. cut adapter power (simulated BT drop)
   3. wait >5s, restore adapter power
   4. **assert:** `connect_attempt` row appears in `connection_log` within 60s; second `drive_start` appears within 90s
   - This test MUST fail against current code (regression-strength per the runtime-validation rule).

6. **IRL gate (post-deploy, CIO-runs):** CIO repeats the 2-leg pharmacy pattern (drive → engine-off ≥5min → drive); expect drive 13+14 (or whatever the counter is at) both materialize with > 100 rows + correct `drive_id` populated.

## What is NOT in scope for this story

- The alternator-voltage proxy (ELM ATRV for engine-state detection independent of BT). Spool filed that as a P3 V0.28+ backlog ask — complementary fix, not a substitute.
- The `wifi.powersave` mitigation (already deployed; verified post-redeploy 2026-05-13).
- Sibling bugs US-339 (I-034 SQLite disk-I/O) and US-340 (I-035 WiFi soft-off) — those are independent stories in this sprint.

## Cross-references

- `offices/ralph/inbox/2026-05-13-from-spool-bt-no-reconnect-after-engine-cycle.md` — Spool's tech depth; **read first**
- `offices/pm/issues/I-033-bt-no-reconnect-after-engine-cycle.md` — PM bug paper
- V0.27.1 hotfix (US-301/US-302) — closed initial-connect + AC-power-restored paths; **did NOT close adapter-present-but-session-stale path** (this story)
- I-025 (BT reconnect no-backoff when adapter absent) — opposite end of same code path; orthogonal

## Ack expected

Confirm: (a) Spool's repro understood, (b) fix direction picked (B or hybrid B+C), (c) flag any blockers. Then commit + push when first cut is ready.
