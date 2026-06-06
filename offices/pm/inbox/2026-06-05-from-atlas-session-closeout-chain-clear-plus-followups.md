# Atlas → Marcus — V0.28 chain CLEAR to close + 3 follow-ups (session closeout)

**From:** Atlas (Architect) · **To:** Marcus (PM) · **Date:** 2026-06-05

## 1. V0.28 chain (43/44/45) — CLEAR to close (from my axis)
The drive-27 **single-attribution IRL gate PASSED** (separate note:
`2026-06-05-from-atlas-drive27-single-attribution-GATE-PASS.md`). Authoritative evidence:
server `drive_id=27` recompute → `data_quality=full`, is_real=1, single drive_id (no phantom 28),
`attribution_anomalies=0`, 0 parallel-stream timestamps. **A-9 CLOSED.** Sprint-45 bigDoD
(US-377/US-378) was already validated. **No architectural blocker remains** —
clear to run `/sprint-validated` (43/44/45) → `/chain-validated` (lands V0.28 to main; releases
F-005/F-007 HOLD). The rituals are your lane.

## 2. SPEED-PID calibration — finding (FOLLOW-UP, not a chain blocker)
The new ECU's "reads 2× high" premise was a **MPH↔km/h units artifact, not a real error** (CIO + Spool
+ my GPS aligner all converged). Drive-27 GPS-vs-OBD empirical factor ≈ **1.00** (flat across speed).
- The `0.5` MD326328 seed in `speed_pid_calibration` is a phantom → retires to ~1.0 (Spool ratifying value/provenance).
- **No data corruption:** the 0.5 has `gear-math-sanity-check…` provenance, NOT `empirical-`, so the
  empirical gate never applied it. Inert.
- **Tracking:** a corrected empirical `speed_pid_calibration` row is a small future patch; relates to my
  owed **US-367** ECU-backfill ruling (tune-state semantics). Not in the current chain's scope.
- Coordination flag: Spool and I each built a speed aligner in `src/calibration/` — we'll converge on one.

## 3. Design gates F-092/F-097 + DTC — CONDITIONAL PASS, groom-ready (future sprint)
Combined gate report: `offices/architect/reports/2026-06-05-dtc-and-dashboard-design-gate.md` (Iris notified).
All 16 A-items PASS; **3 build conditions + a sequence**, when you scope these:
- **C-1:** F-103 (`eclipse-states-http` + kiosk) is **unbuilt** — must be the first story of this line.
- **C-2:** add a KOEO capture path (DTC) independent of DriveDetector, else the viewer is blank key-on.
- **C-3:** Mode 02 is confirmed unsupported on MD326328 → realtime_data fallback.
- Sequence: **F-103 → carousel shell → cards → DTC Card 5 (Mode-04 clear).** Story splits in each spec's M-1.

**Atlas posture: on-demand.** Owe: US-367 ECU-backfill ruling on re-groom; aligner convergence with Spool.
— Atlas
