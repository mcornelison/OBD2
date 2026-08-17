from=Atlas(Architect); to=Marcus(PM); date=2026-06-19; topic=Pi UI line GREEN-LIT for grooming + 2 EDR-gated deltas; audience=mixed; refs=offices/architect/reports/2026-06-19-iris-unified-alert-gate-ruling.md

# Atlas → PM: Pi UI near-term line is GREEN-LIT to groom (+ 2 deltas parked for the EDR epic)

**Context.** CIO did a full visual walkthrough of the Pi 3.5″ surface (Iris,
2026-06-18) and made two design deltas + asked that the UI route through me to
get onto the Pi. I gated both. Full ruling:
`offices/architect/reports/2026-06-19-iris-unified-alert-gate-ruling.md`. CIO is
steering this UI line.

## Recommended action — groom the near-term UI line (V0.28+)

The near-term line is the work I already CONDITIONAL-PASSED on 2026-06-05; the two
new deltas do **not** touch it, so it's clear to scope. Sequence (unchanged from my
prior gate's §"Sequencing recommendation"):

1. **F-103** (chromium kiosk + `eclipse-states-http` + token SSOT + `HEALTHY_YIELD`) — **still unbuilt; must be first.**
2. Dashboard carousel shell → 3. System Status + Battery Health cards (+ their emitters) → 4. System Setup + polkit service-control → 5. pygame sunset (parity-gated) → 6. DTC Card 5 (emitter + **KOEO capture** + takeover + Alerts/detail + **Mode-04 clear path**).

**Standing conditions that ride with it (carry into the sprint contract):**
- **C-1** F-103 first (spec only today — don't scope cards as if the runtime exists).
- **C-2** KOEO capture path (DTC-A9): key-on Mode 03(+07) read independent of DriveDetector, `drive_id=NULL`, or the DTC viewer is blank at key-on.
- **C-3** Mode 02 confirmed dead on MD326328 → build the `realtime_data` fallback; no Mode 02 capture path; fix the stale caveat.
- **Rule-10 DoD:** state-server extension, emitters, the Mode-04 path, and the `--green-ok` token each land with matching `specs/architecture.md` (+ `specs/UI/`) updates **in-sprint** (design-gate governance §3a).
- **Iris owes pre-groom-ready:** fold C-2/C-3 + Spool's P1xxx severity/fix subset into the DTC/dashboard specs (she's committed to this).

When Iris files groom-ready, I'll forward on my nod. This note is the green-light;
the spec rev is the artifact you groom from.

## The two deltas — do NOT pull into the near-term line (both EDR-gated)

| Delta | Verdict | Why it's parked |
|---|---|---|
| **DELTA-1 Unified Alert Layer** (merge DTC alerts + live engine-protection events into one takeover/ribbon/priority) | APPROVED as target shape — an **arbiter** that aggregates two separate producers (NOT a generalized single emitter). | Near-term has **one** alert source (DTC) → nothing to arbitrate. The arbiter is built when the live engine-protection source lands (the EDR epic). Track as an **A-14 / EDR-epic** item, not a V0.28 story. |
| **DELTA-2 Live-Instrument home card** (compass/gear/grade/g-force from 9-DoF IMU) | APPROVED contract (pure consumer, single-reader-owned state file). | Presupposes the IMU pipeline; sensors arrive ~end-June→mid-July (A-14 hardware gate). EDR-epic slice, not near-term. |

**System impact:** keeping both deltas out of the near-term sprint is what lets the
UI actually ship to the Pi soon — they're V0.3x+ EDR work. They're logged under my
Watch item A-14 (EDR direction) as concrete gate sub-items; no new BLOCK, no change
to A-9 / A-15. No `tests/` impact (Argus's lane untouched).

— Atlas
