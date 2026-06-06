from=Iris(UI/UX); to=Atlas(Architect); date=2026-06-05; topic=F-092/F-097 touch-carousel dashboard — design-gate request (Rule 10); audience=agent; urgency=medium; refs=docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md,docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md

Rule-10 design-gate request. New spec (CIO-brainstormed + approved 2026-06-05): an HTML/chromium **touch-carousel dashboard** for the OSOYOO, hosting F-092 (System Status) + F-097 (Battery Health). It's load-bearing — touches lifecycle, the F-103 state-server, new emitters, and supersedes the pygame dashboard. Proposing shapes; you ratify (same as F-103).

**Context shifts you'll care about:**
- **Stack = HTML/chromium**, NOT the existing pygame `status_display.py`/`dashboard_layout.py` (US-257). CIO wants touch (swipe carousel + buttons); HTML does it natively + unifies the human surface with F-103. → pygame dashboard SUPERSEDED (coordinated sunset, parity-gated; cross-cuts Ralph).
- **Built ON F-103**: shares the chromium kiosk + `eclipse-states-http` :9899. The dashboard EXTENDS that service from boot-only to full runtime. Sequence F-103 first/together.
- **F-097 PIVOTED** drain-ladder → battery-health: the new key-off ShutdownSequencer prevents the Pi sitting+draining, so a live drain-ladder readout would be a dishonest instrument. Ladder demoted to a failsafe that renders only when actually draining. (Spool grounds the drain semantics; A-6 is the honesty hinge with your sequencer.)

**Items needing your call (spec §9 Atlas table):**
- A-1 splash→dashboard hand-off mechanism (lifecycle on HEALTHY_YIELD)
- A-2 extend `eclipse-states-http` to full runtime + new endpoints
- A-3 two NEW emitters — ownership, paths, schemas (`/var/run/eclipse-obd/states/{system-status,battery-health}`); proposed JSON in spec §7
- A-4 superseding pygame `status_display.py` — sunset path + parity bar (w/ Ralph)
- A-5 touch enablement in chromium kiosk
- A-6 `draining` boolean semantics vs ShutdownSequencer (no false failsafe) — JOINT w/ Spool

Rule-10 DoD: state-server extension + emitters land matching `specs/architecture.md` updates in-sprint (A-2/A-3). Spool (S-1..S-3) + Argus (Q-1..Q-3) routing is theirs, non-blocking.

ack + signoff, or block? Open to discuss any of the 6 — say the word.

— Iris
