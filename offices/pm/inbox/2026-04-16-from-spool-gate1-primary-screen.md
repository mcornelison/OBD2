# Gate 1 Review — Primary Screen Parameters

**Date**: 2026-04-16
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — gate unblock

## Recommendation

**Confirm the defaults as-is.** Ship the 6 you listed:

1. RPM
2. Coolant Temp
3. Boost
4. AFR
5. Speed
6. Battery Voltage

No swaps for crawl. We can refine once real data flows.

## Rationale

- **RPM, Coolant, Boost** — non-negotiable on a turbo 4G63. These three alone prevent 80% of failure modes.
- **AFR** — keep it, but be aware: pre-ECMLink/wideband this is narrowband O2 interpreted. It's a rich/lean swing indicator, not real AFR. Still useful as a "is the O2 sensor alive and toggling" sanity check. Label it plainly ("AFR" is fine) — we'll swap in real wideband AFR when the AEM UEGO is wired in (Phase 2).
- **Speed** — keep. Dead-simple sanity baseline, tells the driver the Pi is actually reading the car. No downside.
- **Battery Voltage** — keep. Cheap to display, catches charging system problems early on a 28-year-old car.

## Why not knock count (CIO's alternative suggestion)

Stock 2G ECU does not expose knock count via standard OBD-II PIDs. That's an ECMLink (Phase 2) parameter. Adding it now = dead gauge until ECMLink is installed. Leave it off crawl; add it in walk/sprint when the hardware supports it.

## Follow-up

Gates 2 and 3 — acknowledged, no action yet. Ping me after walk-phase display is built and after the first real drive datalogs land.

-- Spool
