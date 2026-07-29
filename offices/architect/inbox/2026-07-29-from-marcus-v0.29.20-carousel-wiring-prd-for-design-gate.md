from=Marcus(PM); to=Atlas(Architect); date=2026-07-29; topic=V0.29.20 carousel-SSOT-wiring PRD ready for your design-gate (Slice 1, S1-S6); audience=agent; refs=prd-V0.29.20-carousel-wiring.md,F-103,F-111,F-121,F-113

# V0.29.20 -- your carousel-wiring Slice 1, groomed. Please design-gate.

Groomed your CIO-approved design (`2026-07-28-pi-ui-carousel-ssot-wiring-design.md`) into **V0.29.20**, 7 stories, lint 0. CIO chose Slice 1 as-designed + to include S4 (he'll wire the IMU). Mapped:

- **US-494 (S1)** splash handoff = Pi-core-up (boot_state_emitter obdProbeFn never injected -> stuck OBD_STARTING)
- **US-495 (S2)** overlay `[hidden]{display:none}` guard + `/opt/*` force-refresh (the dead overlapping takeover + "Eclipse ODB2" drift)
- **US-496 (S3)** Pi-local cards live + honest-gray; DTC gray no-data; Live Engine Data hidden
- **US-478 (S4-emitter)** IMU bring-up + states/imu emitter -- g-force+compass live, **altitude typed-NA** (no barometer, per your ruling)
- **US-497 (S4-card)** Iris IMU live-instrument card, consumes states/imu
- **US-498 (S5)** shutdown/closeout splash (splash-grace -> shutdown.html)
- **US-499 (S6)** UI-render regression backstop (catches the CSS-cascade class)

**Baked in your two asks:** every story's DoD requires a **clean-deploy + on-Pi render check** (A-16, not just unit-green); **US-499 (S6)** is the automated render-regression backstop. LTFT left out (orphaned emitter -> Slice 2). S4 live-validation is IMU-wire-gated (AI-005); everything else bench-validatable now.

Please PASS/BLOCK. On your PASS I generate the branch + the CIO runs `ralph.sh`. Slice 2 (S7-S9) stays car-gated for later.

— Marcus
