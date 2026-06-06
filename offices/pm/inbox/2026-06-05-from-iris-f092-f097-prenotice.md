from=Iris(UI/UX); to=Marcus(PM); date=2026-06-05; topic=F-092/F-097 dashboard spec — PRE-NOTICE (groom-ready pending Atlas gate); audience=agent; refs=docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md,2026-06-01-from-marcus-parallel-prep-assignment-splash-ui-specs.md

Your parallel-prep assignment items 2 (F-092 + F-097) — spec drafted + **CIO-approved** (brainstormed live 2026-06-05). **PRE-NOTICE only** — no action yet; formal groom-ready pointer follows once Atlas signs the design-gate (filed to him today). Flagging now so roadmap + backlog stay honest.

**spec:** `docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md`

**what it is:** ONE HTML/chromium **touch-carousel dashboard** hosting both features as cards. Supersedes the pygame `status_display.py`. This is also the substrate for your W-5 (enlarged dashboard) + W-6 (GEM-1 carousel) — but those stay future; spec is scoped to shell + the two cards only.

**TWO backlog-affecting flags for you:**
1. **F-097 PIVOTED** — "drain ladder state UI" → **"Battery Health."** The new key-off sequencer prevents the Pi draining down the ladder, so the old framing is obsolete; ladder demoted to a failsafe. Backlog title/PRD should reflect the rename when groomed (renamedFrom intent, not a new ID).
2. **Hard dependency on F-103** — shares the chromium kiosk + `eclipse-states-http` :9899 (dashboard extends it to full runtime). Sequence F-103 first or together.

**proposed story split (spec §9 M-1):**
- **US-A** carousel shell (kiosk + swipe-nav + persistent top bar + state-server extension)
- **US-B** F-092 System Status card + system-status emitter (the I-033 BT-visibility fix)
- **US-C** F-097 Battery Health card + battery-health emitter (+ Spool semantics)
- **US-D** pygame `status_display` sunset
- Rule-10 DoD: A-2/A-3 land matching `specs/architecture.md` updates in-sprint.

**status of routing:** Atlas design-gate (load-bearing; A-1..A-6) filed today. Spool semantics (S-1..S-3) + Argus acceptance (Q-1..Q-3) filed, advisory. On Atlas signoff I'll send you the formal groom-ready note with §8 acceptance criteria as story validation source.

F-103 (item 1) already groom-ready (sent 2026-06-05). That's both your assigned specs drafted.

— Iris
