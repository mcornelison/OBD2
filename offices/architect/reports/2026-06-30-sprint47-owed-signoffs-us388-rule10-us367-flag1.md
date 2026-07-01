# Atlas — Sprint 47 owed sign-offs cleared: US-388 Rule-10 PASS + US-367 FLAG-1 blessed

**By:** Atlas (Architect) · **Date:** 2026-06-30 · **Tasked by:** CIO ("proceed" — clear the owed items)
**Verdict: both PASS — verified against landed code, not the narrative.** Sprint 47 / V0.29.1 merged; these are the two on-record sign-offs I owed Marcus.

## 1. US-388 — Rule-10 design-gate PASS (Root-2 guaranteed-close)

The Rule-10 DoD is that `specs/architecture.md` documents the load-bearing DriveDetector close-path change in-sprint, faithfully. Verified `§10.7.1.2` (architecture.md:2076-2121) against my 2026-06-29 C-α…δ shape ruling AND the landed code:

| My constraint | architecture.md §10.7.1.2 + code | Verdict |
|---|---|---|
| **C-α off-tick** | new `DriveDetector.evaluateTimeouts(now)` runs the close paths off the reading-tick; `orchestrator/core.py::runLoop` calls it every pass (verified `core.py:778-782`, exception-isolated) — "close fires when the deadline elapses even if no further reading ever arrives, **reusing the existing periodic loop rather than adding a watchdog thread**" | ✅ (incl. my preferred mechanism — reuse the loop, no new thread) |
| **C-β under the existing lock** | `evaluateTimeouts` acquires the **existing** `self._lock` before mutating `_currentSession`/`_driveState`, like `processValue`; "no new lock, no lock-free mutation" (verified `detector.py:304` lock, US-388 changelog) | ✅ |
| **C-γ deadline-anchored, don't regress US-361** | `_maybeCloseOnDeadline(now)` called FIRST in the STOPPING branch; debounce completes inside a reading gap → key-on past deadline closes the stale drive + mints fresh (no absorption); a blip resuming **before** the deadline stays RUNNING → "US-361 is not regressed" | ✅ (the non-regression condition explicitly honored) |
| **Fresh-mint vs re-attach (gap-fence corollary)** | a confirmed deadline close does NOT set the ECU-silence continuation marker → next `_startDrive` mints a fresh id; deadline forces an explicit-NULL row | ✅ |

`§10.7.1.1` likewise documents US-389 (single-instance guard ⇄ `RuntimeDirectory` matched-pair, my C-5). **Rule-10 PASS.** A-9 stays **OPEN** until the live IRL re-gate (short / back-to-back / key-on-after-missed-close / deploy-double-start) passes — the architecture.md says so; my sign-off is on the *design-gate DoD*, not the IRL acceptance.

## 2. US-367 — FLAG-1 (NULL-vs-start-of-tracking) BLESSED

My 2026-06-28 2-row ruling described the prior-ECU install as the "gapless partition start (NULL/unbounded lower bound)." `src/server/cli/backfill_ecu_lineage.py` documents the reconciliation (lines 55-72): the shipped schema declares `vehicle_info.ecu_install_timestamp_utc` **NOT NULL**, and the resolver (`_resolveVehicleInfoIdForCapture`) matches `install <= captured_at`, so a literal SQL `NULL` install is both unstorable and unmatchable — it would make the prior era resolve **zero** captures, breaking the exact drives 1-24 partition the backfill repairs.

Rex realized the unbounded lower bound as the **grounded START-OF-TRACKING instant = earliest `realtime_data.timestamp` = `2026-04-23 16:36:50 UTC`**, which sits at-or-before every tracked capture → operationally identical to an unbounded start over all real data.

**Blessed.** This is the correct, faithful realization of my ruling — it preserves the gapless single-active partition (start-of-tracking → swap → NULL-open) and resolves all drives 1-24 to the prior `MD346675` era. It is a documented reconciliation of the ruling's wording with the shipped NOT-NULL schema, **not** a silent deviation. (My ruling itself specified "install = start-of-tracking / earliest tracked capture," so the concrete instant *is* what I asked for.)

## Disposition
- US-388 Rule-10 PASS recorded; US-367 FLAG-1 blessed. Both routed to Marcus.
- **Still owed by me:** Rule-13 on Sprint 49 (V0.29.3) when Marcus freezes; the NEW Sprint-50 EDR design-gate request (`inbox/2026-06-30-from-marcus-sprint50-edr-design-gate-request.md`) — separate, larger ask.
- A-9 remains OPEN (HIGH) pending the live IRL re-gate.

— Atlas
