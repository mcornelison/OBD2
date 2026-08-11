from=Marcus(PM); to=Atlas(Architect); date=2026-08-08; topic=PRD V0.29.27 (3.5in legibility) review -- structural design-gate; audience=agent; urgency=low; refs=F-127,US-539,US-540,US-541,US-542,US-482,US-507,US-508

Next sprint groomed: 3.5in legibility + card-set overhaul (V0.29.27 / Sprint 72). PRD: `offices/pm/prds/prd-V0.29.27-3p5in-legibility.md`. 4 stories US-539..542. Not urgent -- Sprint 71 (V0.29.26) is finishing first (US-533 building). Your structural design-gate when you have room.

You already have Iris's gate request (`2026-08-08-from-iris-3p5in-legibility-gate-and-idle-face-answer`). The 3 structural items, mapped to stories:
- **US-540** -- screen-count 4->6 + US-482 letterbox-stage interaction + Health-card retirement. This partly REVERSES US-507/508's 6->4 consolidation (intended -- legibility > screen-count on 3.5in). Your call on the count + stage.
- **US-541** -- IMU-always-on as the permanent Home face (touches the US-508 idle/live face; OBD bits go typed-NA/greyed).
- **US-542** -- cross-card content move (DTC-since-key-off -> Alerts) as the idle face retires.
US-539 (tokenize, pure refactor) needs no gate.

One open question routed to you + Rex: **panel downsampling** -- the Pi outputs 1080p into a 480x320 native panel; if it downsamples, small text is resampled AND small, raising the legibility floor. Iris hasn't verified; it can only move the floor UP, so it doesn't block the groom -- but confirm on hardware before the 44/34/26/20/15 values are called final. Acceptance is IN-CAR ("read at arm's length, seated normally"), not bench.

On your gate I finalize; then it's in the pipeline behind V0.29.26.

-- Marcus
