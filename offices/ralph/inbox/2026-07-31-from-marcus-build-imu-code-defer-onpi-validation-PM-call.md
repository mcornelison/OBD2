from=Marcus(PM); to=Rex(Dev); date=2026-07-31; topic=PM CALL -- build US-478/US-497 code-complete against the contract + fixture; on-Pi validation DEFERRED to my bench session (don't gate the code on the flapping Pi); audience=agent; refs=US-478,US-497,BL-026,V0.29.20

# The design gates are lifted; the Pi flapping is NOT your gate. Build the code.

First: **read `offices/ralph/inbox/2026-07-30-from-marcus-BL026-cleared-imu-contract-and-pi-address.md`** (commit d585617) if you haven't -- it carries the full `states/imu` contract Atlas rendered (it had been mis-routed to the PM inbox; my miss). Both design gates are lifted:
- **Contract (Q-A/Q-B):** in that note -- `gLat`/`gLon` (g), `headingDeg`, `gradePct=tan(pitch)*100`, `altitude` typed-NULL+`reason:"no_source"`, `available`+`ts`. `states/imu` is a STATE FILE (same seam as `states/light`); raw stays on the EDR bus (A-4). That IS the buildable contract.
- **Hardware:** IMU genuine @0x69 (Atlas WHO_AM_I=0xEA).

## The PM call you asked for (your conditionalOutcome + BL-026 "ship code, defer validation")
The Pi is **intermittently reachable** -- it reboots / WiFi-blacks-out and its address moves (`.28` dead; `.9` wired + `.100` wlan0 both flap; right now `.9` is up, `.100` down). **Do NOT gate your CODE build on reaching it.** Writing the emitter bridge + the card + unit/fixture tests needs NO live Pi.

**Authorized, explicitly:**
1. **Build US-478 (emitter)** -- the `raw.imu.* -> states/imu` derived-field bridge (per the contract) + enable `pi.sensors.imu.enabled`, unit-tested against a `states/imu` **fixture**. Code-complete.
2. **Build US-497 (card)** -- the IMU live-instrument card consuming the `states/imu` fixture shape. Code-complete.
3. **Mark both code-complete with a clear note: "on-Pi live-hardware validation DEFERRED to the PM sprint-close bench session."** That's not a shortcut -- the live check (i2cdetect + live `states/imu` + card render on the real IMU) is **owed and tracked**, it's just MINE to run at the bench session when the Pi is reachable, not a per-iteration gate for you.
4. The **4 owed render checks (US-494/495/496/498)** are likewise the PM bench session, not yours -- you've already built + unit-verified them.

So: the sprint's remaining CODE is buildable now, Pi or no Pi. Build US-478 then US-497 against the contract + fixtures. I run the single on-Pi bench validation (all 6 checks) at sprint close on whichever address answers. Ping at 7/7 code-complete.

— Marcus
