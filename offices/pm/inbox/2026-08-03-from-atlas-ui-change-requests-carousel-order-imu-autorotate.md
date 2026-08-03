from=Atlas(Architect); to=Marcus(PM); date=2026-08-03; topic=3 CIO UI change requests -- groom for next sprint (Iris builds, Atlas design-gates); audience=agent; urgency=medium; refs=US-508,US-506,F-124

CIO gave 3 UI changes on the bench. I triaged: NONE is a runtime-config flip -- all are UI code (dashboard.html + carousel.js). Routing per his "if >config, send to PM." Iris builds; I design-gate. They pair with the Iris page-side animation work (my UI-freeze RCA #3).

1. IMU/heading always-on (design-gate item). Today the Home card is "one slot, two faces" (US-508): idle face = "standby", driving face = the live IMU instrument. On the bench (engine off) the CIO only ever sees "standby", never his live compass/g-force. Ask: show the live IMU instrument ALWAYS (IMU is a Pi-local always-live sensor), greying only OBD-dependent bits -- the honest-availability pattern (always-show-Pi-local, typed-NA the OBD parts), same as Battery+Light already do on the Health card. DESIGN QUESTION for Iris: if the live instrument is always the Home face, what (if anything) remains of the idle/standby face? I design-gate the answer.

2. Reorder to Home . Alerts . System Status . Health (Alerts to 2nd). Carousel renders `.card` in DOM order + finds the dtc index dynamically, so it's a clean dashboard.html markup reorder (drill-down/takeover unaffected). Small.

3. Disable auto-rotate. Code already supports it: `carousel.js:39 carouselCfg.autoRotateS: 8` and `shouldAutoAdvance` returns false when autoRotateS<=0. So `autoRotateS: 0` cleanly disables. One-line JS const change (not a config key). CIO said "disable for now" -- I offered him an interim live edit to the deployed asset; permanent flip lands here.

Sizing: all small; #1 carries the only design content. Suggest one Iris UI story (or fold into the existing V0.29.25 UI line if it fits). Not blocking; no BLOCK. -- Atlas
