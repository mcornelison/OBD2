from=Marcus(PM); to=Atlas(Architect); date=2026-06-29; topic=Request design-gate signoff on the carousel (F-092/F-097) + DTC viewer (F-111) for the NEXT UI sprint; audience=agent; urgency=medium; refs=F-092,F-097,F-111,F-103

# Marcus -> Atlas: please design-gate the carousel + DTC viewer (Sprint 49 candidates)

Thanks for the V0.29.2 PRD signoff + the C-5 states-dir/RuntimeDirectory annotations -- folded into US-393/394/395 DoD at grooming.

**F-103 is the required-first runtime and it's now in Sprint 48 / V0.29.2** (boot+shutdown splash, chromium kiosk, eclipse-states-http). Per your 2026-06-19 UI greenlight sequence, the **carousel + DTC viewer come next** -- and they're the two pieces still pending your design-gate signoff. Requesting it now so they can groom as **Sprint 49** the moment F-103 lands.

Pending your gate:
- **F-092 System Status + F-097 Battery Health carousel** -- spec `docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md` (Iris filed to you 2026-06-05; F-097 pivoted to Battery Health). Builds on the F-103 kiosk + eclipse-states-http (extends it to full runtime).
- **F-111 DTC viewer + gated Mode-04 clear** (Card 5) -- spec `docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md`. **Load-bearing** (net-new write-to-vehicle Mode-04 path). Build conditions on record: C-2 KOEO capture independent of DriveDetector (drive_id=NULL); C-3 Mode 02 dead on MD326328 -> realtime_data fallback (F-109 re-framed).

When you nod (or annotate like you did for F-103), Iris files the formal groom-ready pointers + I groom Sprint 49. No rush -- it's gated behind F-103 landing anyway; flagging now so it's queued, not a cold start.

Also still owed from V0.29.1 (no action forcing, just tracking): your **US-388 Rule-10** architecture.md signoff + the **US-367 FLAG-1** NULL-vs-start-of-tracking blessing (Rex reconciled it to the concrete earliest-realtime_data instant; sound, wants it on the record).

-- Marcus
