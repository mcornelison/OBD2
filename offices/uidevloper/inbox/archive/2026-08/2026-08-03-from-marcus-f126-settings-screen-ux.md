from=Marcus(PM); to=Iris(UI/UX); date=2026-08-03; topic=F-126 Settings screen -- UX design (US-532); audience=agent; urgency=medium; refs=F-126,US-532,US-403

New CIO feature groomed: a Pi Settings screen (V0.29.26 / Sprint 71). PRD: `offices/pm/prds/prd-V0.29.26-settings-screen.md`. US-532 is yours -- the screen UX.

**What it shows (Slice 1, 5 config-backed settings):**
- Carousel auto-rotate (on/off)
- Power mode (car / wall / unknown -- 3-state, not a toggle)
- Audio alerts (on/off)
- Calibration mode (on/off)
- Auto-analyze after drive (on/off)

**Design asks:**
- The CIO called it a "screen" -- lean toward a **Settings card in the carousel** (a swipe-to system screen like System Status). But **you decide the shape** and **reconcile with the existing US-403 setup menu** (the kebab/long-press service-control overlay): is Settings a card, reachable from that menu, or both? No duplicate/competing surfaces. Confirm the card-vs-menu presentation with the CIO in your design.
- Each control shows its **real current effective value** (read via the US-530 layered config read, surfaced through the state server) -- never a hardcoded default.
- **Honest apply-state**: where a setting applies live, reflect it; where it needs a service restart, say so plainly -- never a silent no-op that looks applied.
- Match the F-124 carousel design system (tokens, Oswald wordmark).

**Seams (not your build, just context):** persistence = a Pi-local overlay (US-530, Atlas contract); writes go through a token-gated endpoint (US-531); US-533 wires the controls end-to-end. Deferred/future (not this sprint): a System screen with a Battery/Power Test + an Updates sub-screen.

Route your design back when ready + confirm the shape with the CIO.

-- Marcus (Iris)
