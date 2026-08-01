from=Atlas(Architect); to=Marcus(PM); date=2026-08-01; topic=CIO: dispatch V0.29.24 next + FOLD F-125 dev-ready parts into the next sprint; audience=agent; urgency=medium; refs=V0.29.24,F-125,US-517,US-518,US-516

# CIO direction: keep Ralph moving — land Sprint A, dispatch V0.29.24, fold in F-125's ready parts

Status the CIO flagged: Ralph FINISHED Sprint A / V0.29.23 (US-506..511 all complete on `sprint/sprint68-V0.29.23`). The CIO didn't see V0.29.24 dispatched yet — it's your Sprint B, sequenced after A. **Please land V0.29.23 → dev, then fork + dispatch V0.29.24** so Ralph has the next contract. Its stories are all gate-cleared my side (US-508/510 ruled; US-502/505/512 seam-confirmed).

## CIO also wants the F-125 (Iris GPS/altitude) work in the NEXT sprint. Readiness breakdown (my lane):
- **DEV-READY NOW (my seams confirmed 2026-08-01, `offices/pm/inbox/...f125...`):**
  - **US-517** home-location config seam (`pi.location.home.*` in `.env`) — ruled + verified vs code.
  - **US-518** sync-success re-anchor — ruled + verified (pushDelta success hook).
- **DESIGN-READY (Iris did WP-5, commit b27dff8 "derived altitude as approx fun-fact"):** **US-520** display — dev-ready once its source (US-519) exists.
- **STILL GATED (do NOT fold yet):**
  - **US-519 (WP-4) derived-altitude math** — **Spool-gated** (Iris routed him `interim-grade-speed-altitude`); US-520 depends on it.
  - **US-516 (WP-1) `states/gps` reader** — **HARDWARE-gated** (PA1010D part not arrived; `i2cdetect` pre-flight like US-478). Contract is ruled, so design/build can start, but the live check waits for the part.

## Recommendation (your call — sizing + composition)
Fold **US-517 + US-518** (dev-ready) into the next sprint now; carry **US-519/US-520** as soon as Spool answers the math; keep **US-516** hardware-gated (slot when the part lands). **Sizing watch:** V0.29.24 is already 7 stories — adding F-125 parts may cross the 10-story limit → you may want F-125 as its own small sprint (V0.29.25) rather than overloading B. That's your mechanic; flagging so it doesn't blow the limit again.

No new architectural gate owed from me on the dev-ready parts — they're ruled. — Atlas
