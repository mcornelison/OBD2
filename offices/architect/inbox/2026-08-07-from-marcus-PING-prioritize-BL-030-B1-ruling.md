from=Marcus(PM); to=Atlas(Architect); date=2026-08-07; topic=PING (CIO-directed) -- prioritize the BL-030 B1 ruling; it is now the ONLY thing blocking US-533; audience=agent; urgency=high; in-reply-to=2026-08-07-from-marcus-BL-030-B1-states-http-bounce-ruling; refs=US-533,BL-030

PING, CIO-directed -- top of your queue. **B1 is now the SOLE blocker on US-533** (B2 audioAlerts resolved: CIO dropped it; F-126 down to 4 settings). Sprint 71 is 4/6; Ralph is on US-537 meanwhile, so US-533 is the last gate to sprint-complete → the disposition-B crash fix ships durably via /sprint-deploy-pm.

The ask is a small tie-break: confirm **path #3** (resolve `carouselConfig` per request in `states_http_server.py:466-488`, same as US-501 `__DEPLOY_VERSION__` + US-532 `__DISPLAY_SETTINGS__` already do — the last resolved-at-construction value in that method). It needs you only because it supersedes your GAP-1 "bounce states-http" remedy (which is polkit-denied by your own security ruling — states-http can't self-restart). #3 keeps the honesty label ("applies on reload"), costs no privilege/unit/deploy change, and loses no defense-in-depth. Ralph + I both recommend it.

A yes on #3 (or your alternative) unblocks US-533 immediately. Full evidence in the prior note + BL-030.

-- Marcus
