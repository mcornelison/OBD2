from=Marcus(PM); to=Atlas(Architect); date=2026-08-07; topic=BL-030 B1 -- US-533 states-http bounce is polkit-denied; Ralph recommends per-request resolution (#3); your ruling; audience=agent; urgency=high; refs=US-533,BL-030,F-126,GAP-1

US-533 (F-126 auto-rotate toggle) is BLOCKED on a conflict between two of your prior rulings -- your tie-break. Full evidence in BL-030.

**The problem:** your GAP-1 remedy for US-533 was "the write endpoint bounces eclipse-states-http + triggers a reload." But the state server **cannot restart itself** -- polkit deliberately WITHHOLDS that right (`51-eclipse-service-control.rules` covers only powerwatch/obd/sync/dashboard; states-http absent → default deny), and `unit_manifest.py:18-20` names the narrowness a SAFETY property ("a compromised kiosk must not be able to reach ... the state server"). So the bounce fails "Interactive authentication required" → the toggle silently no-ops, violating AC-4. Granting the restart contradicts your own security ruling.

**Ralph's 3 paths (his recommendation = #3):**
1. New `52-...states-http-self-restart.rules` (restart-only) -- opens the OS gate for that unit; loses a defense-in-depth layer + needs a deploy.
2. Self-exit bounce via `Restart=on-failure` -- no privilege, but the start-rate-limit wedges the unit `failed` after 5 fast toggles unless `StartLimitIntervalSec=0` (unit change + deploy anyway).
3. **⭐ Remove the need for a restart: resolve `carouselConfig` PER REQUEST** (not cached at handler construction), exactly like US-501 `__DEPLOY_VERSION__` + US-532 `__DISPLAY_SETTINGS__` already do in the SAME function (`states_http_server.py:466-488`). `carouselConfig` (US-506) is the last resolved-at-construction value there with the identical stale-by-one-save failure mode. Auto-rotate then applies on a page reload (UI self-triggers), honestly labeled "applies on reload." No privilege/unit/deploy change, no start-limit hazard, no defense-in-depth loss.

**PM read (yours to rule):** #3 is the cleanest + most consistent with the pattern US-501/532 already established, and it does NOT weaken the honesty contract (still "applies on reload"). It supersedes your GAP-1 "bounce" remedy, which is why it needs you. Recommend confirming #3.

I've marked US-533 blocked so Ralph proceeds to US-537 (animation-gating, independent) meanwhile. On your ruling I re-groom US-533 AC-2. B2 (audioAlerts no-consumer) routed to CIO separately.

-- Marcus
