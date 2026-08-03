from=Marcus(PM); to=Atlas(Architect); date=2026-08-03; topic=F-126 settings screen -- 2 design-gate items (overlay contract + token-gate write seam); audience=agent; urgency=medium; refs=F-126,US-530,US-531,US-525

New CIO feature, groomed: a Pi Settings screen (V0.29.26 / Sprint 71). PRD: `offices/pm/prds/prd-V0.29.26-settings-screen.md`. 2 items in your design-gate lane before build:

1. **US-530 -- config overlay contract (LOAD-BEARING SSOT seam).** CIO chose (over writing config.json directly) a **Pi-local overlay file** that layers over config.json: effective = overlay-override ELSE config.json default. config.json stays read-only shipped default; overlay is gitignored + added to deploy-pi.sh rsync excludes (like .env) so deploy never clobbers it. **Your call:** the overlay file shape, the layered-read seam, and the overridable-key ALLOW-LIST mechanism (Slice-1 allow-list = pi.display.carousel.autoRotate, pi.power.mode, pi.alerts.audioAlerts, pi.calibration.mode, pi.analysis.triggerAfterDrive). Honest-instrument: malformed/absent overlay -> default; out-of-allow-list key ignored+logged.

2. **US-531 -- token-gated write endpoint on states_http_server.** The kiosk (chromium JS) can't write files, so a toggle POSTs to a write endpoint that writes the overlay. **Your US-525 ruling stands: token-gated with the US-393 SSOT token, never weaken/bypass _tokenOk, no un-authenticated write surface (that = your BLOCK / TD-067).** Confirm the endpoint shape + that reusing the existing token gate is the right seam.

Not blocking you: US-532 (screen UX) is routed to Iris; US-533 wires it. Deferred (pending, not this sprint): US-534 Battery/Power Test (needs Spool), US-535 Updates (own epic).

On your ruling I finalize + it's ready for the sprint pipeline.

-- Marcus
