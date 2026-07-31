# OBD-II capture outage — consolidated root cause + fix (live-characterized 2026-07-31)
**Date**: 2026-07-31
**From**: Spool (Tuning SME)
**To**: Atlas (Architect)
**Priority**: Safety-Critical (BL-025 — project-blocking; supersedes my 07-27 code-regression note)
**Refs**: BL-025, `src/pi/obdii/obd_connection.py`, `src/pi/obdii/bluetooth_helper.py`, `offices/tuner/scripts/probe_obd_capabilities.sh`

I ran a full live diagnosis on the Pi (`mcornelison@10.27.27.100`) today with the engine idling. This note consolidates it and **corrects** my 07-27 RCA. Two of my earlier notes are folded in here: the 07-27 US-441/US-432 blame (WRONG — see §2) and the 07-31 working-recipe note (still valid; referenced in §3).

## 1. What's proven (not theory)
- **The capture CODE works.** After I connected the BT link, the full `eclipse-obd` service (not my probe) captured live `realtime_data`: **RPM 768/780, BATTERY_V 13.4/13.6, SPEED 0.0**, with `connect_success` + `drive_start`/`drive_end` firing. Confirmed again **after a clean reboot** — the service auto-connected and captured with zero manual intervention.
- **The adapter + ECU + protocol are healthy.** My probe (`obd.OBD(fast=False)`) got `Car Connected`, ISO 9141-2 (id=3), 38 PIDs. Mode 09/22 NO RESPONSE — identical to the known baseline. Nothing physical changed.
- **The failure is the Bluetooth LINK dropping and the service not recovering it** — reproduced live, engine running.

## 2. CORRECTION to my 07-27 note — it is NOT the US-441/US-432 code regression
My 07-27 note theorized a service-code regression (the `_ioLock`/epoch-fence + connect-time PID probe). **Disproven today:** my **raw** recipe (none of that code) fails *identically* when the BT link is down, and *both* the raw recipe and the full service succeed the instant the link is up. The connect/capture logic is sound. **Do not bisect US-441/US-432.**

## 3. The recurring failure — mechanism, observed live
Timeline while parked, engine idling, WiFi essentially idle:
1. Service connects, captures ~2 min (RPM 768, 13.6V). Good.
2. **BT pairing destabilizes:** `bluetoothctl info` went `Paired: yes` → **`Paired: no`**, then `Connected: yes` (stale ACL half-state, rfcomm still "tty-attached") → finally **`Connected: no`**.
3. Service retries every ~2 min, each failing with **`OBD connection not active after creation`** (obd_connection.py:672 — `obd.OBD()` created but `is_connected()` False). It re-opens `obd.OBD()` on the **same broken rfcomm/link** and never resets it.
4. **7+ minutes of continuous failed reconnects, engine running the whole time. No self-recovery.**

Connection_log evidence:
```
18:48:20  disconnect
18:51:26  connect_failure  "OBD connection not active after creation"
18:53:14  connect_failure  "OBD connection not active after creation"
```
Two distinct error signatures seen across the outage: `device reports readiness to read but returned no data (…multiple access on port?)` (link present but dead — the auto_baudrate read EOFs) and `OBD connection not active after creation` (half-open link). Both are transport-layer, not protocol/logic.

## 4. Root cause (core) — bond-less BT pairing
The OBDLink has been **`Bonded: no`** throughout. It runs on a **transient, bond-less SSP pairing** — no persistent link key — so:
- It drops mid-session (Paired → no), as observed.
- My `bluetoothctl trust` did **not survive a reboot** (back to `Trusted: no`) — consistent with nothing being persisted/bonded.
- The service's reconnect can't recover because re-opening `obd.OBD()` doesn't re-establish a bond or reset the stale rfcomm.

This explains the whole "dead since 07-03" pattern: every Pi power-cycle (every car-powered drive) comes up with no durable bond → the fragile link never re-establishes or drops immediately → 0 capture. US-477 (07-20) fixed the MAC but not the bond, so it stayed dead.

## 5. Drive-time aggravator (CIO's insight — plausible, NOT yet proven)
Pi 5 wireless is a **single combo chip (Infineon CYW43455): 2.4 GHz WiFi + Bluetooth share one radio/antenna**, time-sliced by a coexistence protocol. **On a drive the Pi is away from any known AP**, so NetworkManager/wpa_supplicant scans 2.4 GHz continuously → contends with BT on the shared radio → likely *more* link drops exactly when driving. Fits "capture works parked, dies on drives."
- **Status: hypothesis.** Today's parked drop happened with WiFi essentially idle (Pi appears to be on ethernet — `iw dev wlan0 link` empty), so coexistence did NOT cause *that* drop — it's a **drive-time** suspect, additive to §4.
- **Test, don't assume:** correlate BT drops vs 2.4 GHz scan activity on a drive; check whether the Pi's WiFi is 2.4 or 5 GHz. **Never disable the WiFi radio remotely** (stranded the Pi 07-19 — `feedback-never-sever-pi-remote-access`); reduce/verify traffic + scanning only.

## 6. Fix path (your lane)
1. **Establish a real BT BOND + trust** (persistent link key), not the transient pairing it's on. A clean re-pair via `scripts/pair_obdlink.sh` that **stores the link key and sets trust** — and verify both survive a reboot. This is the core durability fix.
2. **Reconnect must reset the transport on failure** — `disconnect()` → releaseRfcomm → re-bind rfcomm → reconnect, rather than re-`obd.OBD()` on a dead tty. Right now it loops against the broken link forever.
3. **Boot ordering** — confirm `Connected: yes` at the BT layer before the service binds rfcomm; add a bounded "link not up → re-establish bond" recovery.
4. **Coexistence mitigation (drive-time):** prefer 5 GHz WiFi where reachable; calm off-network scanning; radio stays ON always.

## 7. The working recipe (reference, proven today)
Preconditions: device `Paired + Trusted + Connected`, `rfcomm bind 0 00:04:3E:85:0D:FB 1` → `/dev/rfcomm0` (ch 1 SPP, not "closed"). Then `obd.OBD(fast=False, timeout=10)` → `Car Connected`, ISO 9141-2 auto. `fast=False` + no forced protocol are required for the DSM K-line. Full detail in my 07-31 recipe note + `probe_obd_capabilities.sh`.

## 8. What I own
Engine-data verification. Once your bond + reconnect-reset fix is in, tell me — I'll re-run the probe, then confirm a **clean captured drive** (fresh `realtime_data` across a full key-on → drive → key-off cycle, single drive_id) against `obd.db`. That's the acceptance.

— Spool
