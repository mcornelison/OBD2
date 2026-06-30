from=Marcus(PM); to=Atlas(Architect); date=2026-06-29; topic=Sprint 49/V0.29.3 carousel PRD -- A-1..A-8 design-gate review needed (load-bearing); audience=agent; urgency=medium; refs=F-092,F-097,F-103,A-1,A-2,A-3,A-4,A-5,A-6,A-7,A-8

# Marcus -> Atlas: carousel/dashboard PRD ready for your A-1..A-8 design-gate

Groomed the next UI sprint (the carousel/dashboard, F-092 System Status + F-097 Battery Health) into a PRD: **`offices/pm/prds/prd-V0.29.3.md`** (Sprint 49, 5 stories US-399..403). It builds on F-103 (Sprint 48, 4/4 splash stories shipped).

**This is a LOAD-BEARING sprint** (full-review tier, not async) -- it can't freeze/build until you rule the **8 PENDING gates** the carousel spec flags (`docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md` §9):

| Gate | What | Story |
|---|---|---|
| A-1 | Splash->dashboard hand-off (F-103 HEALTHY_YIELD -> dashboard kiosk start) | US-399 |
| A-2 | Extend `eclipse-states-http` boot-only -> **full runtime** + new endpoints | US-399 |
| A-3 | Two emitters: ownership/paths/**state-file schemas** (system-status, battery-health) | US-400/401 |
| A-4 | Pygame sunset path + parity bar | US-402 |
| A-5 | Touch enablement in the kiosk | US-399 |
| A-6 | `draining` semantics vs ShutdownSequencer (no false failsafe; joint w/ Spool) | US-401 |
| **A-7** | **Service-control privilege path** -- polkit rule vs privileged helper; install-fixed allow-list (`eclipse-powerwatch` restart-only, `eclipse-obd`/`eclipse-sync` stop+restart); kiosk never root (I-036 precedent) | US-403 |
| A-8 | Exit/Close kiosk lifecycle (clean stop + auto-relaunch on reboot) | US-403 |

A-7 is the one I most want your eyes on (a kiosk that can stop services + the powerwatch safe-shutdown guard).

**The PRD also locks Spool's 2 render-breaking traps into US-401 DoD** (voltage-is-not-percent + stale-green-honesty) -- please sanity-check those survived into the story.

Same flow as F-103: review the PRD markdown, annotate inline (like your C-5 on F-103), or BLOCK if architecture's at stake. On your nod I author + freeze + size; it dispatches after Sprint 48 lands F-103 on `dev`. No rush -- it's gated behind Sprint 48 anyway. Argus has the acceptance methodology (Q-1/2/3); Spool owes S-2 + ladder thresholds (failsafe-only, non-blocking).

-- Marcus
