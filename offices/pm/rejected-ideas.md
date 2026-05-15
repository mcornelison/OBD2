# Rejected ideas — audit trail

Ideas considered for the backlog and rejected, with rationale. Saved here so the same idea resurfacing six months later doesn't get re-litigated from scratch.

## REJECT-A — Shift light / redline cue as primary display element
- **Source:** Spool gem-filter note 2026-05-14
- **Rationale:** 4G63 redline = 7500 RPM; on stock turbo + no knock log we should NEVER be there. Screen feature would encourage redline behavior; conflicts with conservative-until-proven principle.
- **Re-evaluation trigger:** ECMLink V3 + wideband + knock log installed.

## REJECT-B — 0-60 / 30-70 / trip timer estimates
- **Source:** Spool gem-filter note 2026-05-14
- **Rationale:** Fun but encourages aggressive driving; same safety conflict as REJECT-A. Not aligned with weekend-cruiser summer-car usage profile.

## REJECT-C — Boost gauge as "watch this number" tile
- **Source:** Spool gem-filter note 2026-05-14
- **Rationale:** Needs B-074 MAP PID (not captured yet). Even when captured, on stock TD04 + no wideband, gauge-watching encourages boost-chasing.
- **Safer alternative:** surface peak-boost-this-drive in post-drive summary, NOT real-time on screen.

## REJECT-D — "Coach Mode" / "Performance Coaching" framing
- **Source:** Spool gem-filter note 2026-05-14
- **Rationale:** Enthusiast-tuner phrasing conflicts with project framing.
- **REFRAME possibility:** "drivability + efficiency coaching" — safer surface; same data; different framing. Only RPM-vs-throttle-efficiency and shift-point analysis are safe coaching topics on this build.

## REJECT-E — AFR tuning recommendations / boost targets / ignition timing
- **Source:** Spool gem-filter note 2026-05-14
- **Rationale:** OBD-II telemetry is too coarse + too late; tuning belongs in ECMLink V3 with wideband + knock log. (Brainstorm itself flagged these as out-of-scope; agreeing for the record.)

## REJECT-F — AAStream "mirror any app" to Android Auto
- **Source:** Spool gem-filter note 2026-05-14 (brainstorm itself flagged this)
- **Rationale:** High driver-distraction risk. Explicit no.

## REJECT-G — RETRACTED 2026-05-14 — Dense 8-9 tile driving UI
- **Source:** Spool gem-filter note 2026-05-14
- **Status:** RETRACTED post-CIO-clarification. Prior version misread mockups as "all tiles visible at once"; CIO clarified each tile is 90-95% of full screen + tap rotates between tiles (carousel of focused views, NOT busy dashboard). Carousel pattern is good UX.
