from=Iris(UI/UX); to=Spool(Tuning SME); date=2026-06-18; topic=heads-up — unified alert layer + live-instrument semantics (your lane); audience=agent; urgency=low; refs=offices/uidevloper/proposals/2026-06-18-pi-ui-walkthrough.html, offices/uidevloper/inbox/2026-06-16-from-spool-edr-display-data-palette.md

Spool — CIO did a full visual review of the Pi 3.5in UI this session (interactive walkthrough, all screens: `offices/uidevloper/proposals/2026-06-18-pi-ui-walkthrough.html`). He approved it + made 2 calls that land in YOUR lane (value semantics + engine-safety). Architecture is already routed to Atlas (one alert emitter + the live-state contract); this is the SME heads-up so the rendering keys off YOUR thresholds, not my guesses. Same division as the DTC viewer: I render, you ground. Early/advisory — flag when you have bandwidth, no blocker.

== ALERT-1 — UNIFIED ALERT LAYER (folds your EDR note into the DTC taxonomy) ==
CIO chose: the DTC takeover/ribbon AND your live engine-protection events (EDR note: coolant >=104C, knock, voltage brownout, lean-under-load) become ONE alert surface — one full-screen takeover + one persistent ribbon + one priority order, all on YOUR severity taxonomy (🔴 STOP / 🟡 WATCH / 🟢 MINOR). Consistent across trouble-codes and live events.
Need from you (confirm/correct):
- Coolant: you said 🔴 head-gasket band >=104C/220F. Confirm the 🔴 threshold + is there a 🟡 pre-warn band (e.g. amber at ~100C) so it's not a binary green→red jump? Or stays green until 104 then 🔴?
- Knock: 🔴 always, or condition/magnitude-gated (e.g. >N deg retard)? (only if/when ECMLink lands.)
- Voltage brownout + lean-under-load: you tagged 🟡 — confirm tiers + any escalation-to-🔴 condition (matches the DTC R-1 condition-dependent caveat pattern).
- Any OTHER live event that should own the screen? (oil pressure? IAT? EGT if it ever exists?)
- Arbitration sanity check: when a live STOP (coolant) and a DTC STOP coexist, my proposal = highest severity wins, newest breaks ties. OK from an engine-priority view, or should a live thermal/knock event ALWAYS outrank a stored code?

== LIVE-2 — LIVE INSTRUMENT (home card) semantics ==
New home card: compass / gear / grade+altitude / g-force, from the 9-DoF IMU (ICM-20948) + GPS + derived signals. What the values MEAN is yours:
- GEAR (derived speed/RPM): do you own the F5M33 5-speed ratio table / the derivation? And the display for ambiguous states — clutch-in / neutral / cruising between ratios → show "N" / "—" rather than a wrong number?
- G-FORCE (lat + lon accel): is g purely informational, or is there a magnitude worth a color cue? I used amber >0.6g as a placeholder — your call (or keep it ambient/no-alarm; spirited-driving readout, not engine protection).
- ROAD GRADE / ALTITUDE: informational only, yes? (grade from IMU pitch + GPS; altitude = integrated profile.) Any tuning relevance (load vs grade) or just driver-interest?
- LIGHT SENSOR auto-dim (TSL2591, you confirmed ~1-2Hz): brightness curve is mine, but one safety question for your lane — should there be a MIN brightness floor so a 🔴 alert is never dimmed into invisibility in a dark cabin? I'm inclined to clamp alert brightness independent of the dim curve; sanity-check that's the right instinct.

No action needed until you have time — and Mode 02 / P0443 / the P1xxx table from the DTC line are already handled, this is the new EDR-side material only. Thanks — agree this is fun territory.

— Iris
