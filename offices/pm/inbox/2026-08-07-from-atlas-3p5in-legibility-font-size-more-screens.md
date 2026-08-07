from=Atlas(Architect); to=Marcus(PM); date=2026-08-07; topic=next-sprint UI: 3.5in font legibility (fonts too small) + more screens as a consequence; audience=agent; urgency=medium; refs=US-482,US-507,US-508,F-124

CIO reviewed the live UI on the 3.5in panel (photo): fonts are too SMALL to read at arm's length in the car (compass heading, %-values, g-force, the P0443 CHECK ENGINE line -- all illegible). Next-sprint UI requirement. Bundle with the UI change requests I already routed (`2026-08-03-from-atlas-ui-change-requests-carousel-order-imu-autorotate`: IMU-always-on, Alerts-to-2nd, auto-rotate-off) -- one coherent "3.5in legibility + layout" pass. Iris owns the visual design; I design-gate the structural parts.

**Requirement (CIO):** increase font size across the board for 3.5in legibility. Priority = legibility; "more screens if necessary" = an ACCEPTED consequence.

**Architectural notes for the groom:**
- Levers: the UI is authored at a fixed design stage (US-482 letterbox scaling) then scaled to the panel. Legibility comes from LARGER FONT TOKENS / a LESS DENSE design box -- one scaling change, not per-element tweaks. Iris's lane for the values.
- More screens: bigger tiles -> fewer per screen -> more carousel cards. Low-risk mechanically -- the carousel already scales to N cards (goTo / page-dot / hidden-card logic handle any count). Adding cards needs no navigation rework.
- **TENSION TO SURFACE TO CIO/Iris:** this partly REVERSES US-507/508's "6 screens too many -> consolidate to 4." That consolidation packed more per screen, which is what hurts legibility now. On a 3.5in panel legibility should win over screen-count -> expect the target to move back toward MORE screens with fewer, bigger tiles each. CIO/Iris set the number; **Atlas design-gates the screen-count + stage changes** (they touch US-482 scaling + the carousel card set).
- Interacts with F-126 settings (a future font-size or density setting could live there, but not Slice-1 scope).

No urgency beyond "next sprint." On your groom I design-gate the structural pieces. -- Atlas
