# RCA — OBD capture failure on 2026-07-17 engine-on test = OBDLink LX dead-SPP/BT link (NOT software)

**Context:** CIO ran an engine-on test on V0.29.11 (the deployed stack carrying F-117/A-17,
BL-016, F-116). Screen showed a black X desktop (carousel kiosk inactive) and **no diagnostics**.
Investigation into "no diagnostics" split into two independent problems: (1) **display/kiosk not
rendering** (A-16 Bug-3, separate), and (2) **OBD capture producing zero rows** — this finding.

## Verdict

**Capture failure root cause = the OBDLink LX dongle is in a dead-Serial-Port-Profile state on
Bluetooth — a hardware/link fault, NOT the eclipse-obd software and NOT any recent commit.**

Fix = **factory-reset the dongle + fresh re-pair** (same class as the 2026-07-03 pairing saga).
This is the **second** time the LX has gone catatonic and needed a physical reset → recurring
reliability problem (see Follow-ups).

## Evidence chain (live, engine running)

1. **Zero capture confirmed both tiers:** server `realtime_data` max drive_id=34, latest 2026-07-03;
   Pi `obd.db` zero rows for 2026-07-17. No drive 35.
2. **Journal signature (engine on, 17:22–17:25):** connect succeeds (`Connected… attempts=1/3`),
   even probes 16 PIDs once (`_runSupportedPidProbe discovered=16`), then
   `[obd.elm327] Device disconnected while reading` → realtime logger `logged=0` → reconnect loop
   fails with *"device reports readiness to read but returned no data (multiple access on port?)"*.
   Also `Realtime logger already running` (double-start) + `_dispatchKeyOnDtcs` firing on the same
   connect edge → these LOOK like the A-17 thread race.
3. **Isolation test REFUTES the thread-race hypothesis (verify-before-asserting).** With
   `eclipse-obd` **stopped**, `fuser /dev/rfcomm0` = **none** (single-access), fresh `rfcomm` rebind,
   a **single-threaded raw `python-obd` read fails identically** at `auto_baudrate`
   (`__port.read` → "readiness but no data"). A lone reader cannot race itself → **not concurrency.**
4. **Same call path proven:** deployed `_createObdConnection` = `obd.OBD(portstr, fast=False,
   timeout=…)` — no baudrate/protocol → **auto-baudrate, identical to the raw test.** No confound.
5. **Recent commits exonerated:** the raw reader imports **none** of eclipse-obd. US-441 (F-117),
   US-432 (BL-016), US-424 (F-116) — the only commits touching this code since the last good
   capture — cannot cause an `auto_baudrate` failure in a process that doesn't load them.
6. **The actual fault localized to Bluetooth SPP:** `bluetoothctl connect` →
   `Connected: yes, ServicesResolved: yes` **but** `Failed: br-connection-profile-unavailable`;
   a forced reconnect earlier → `br-connection-page-timeout` (dongle not answering BT pages).
   SDP browse shows SPP correctly advertised (`STN-SPP`, 0x1101, RFCOMM **channel 1** — the channel
   we bound), device **Paired/Bonded/Trusted/Connected** — yet the rfcomm channel passes **zero
   bytes**. "Fully bonded but no SPP data" = stale dongle-side pairing/session.
7. **Software recoveries from the Pi all failed** (BT disconnect/reconnect, fresh rfcomm rebind,
   dongle power-cycle via unplug/replug) → only a dongle **factory reset** clears it (07-03 precedent).

## Resolution (in progress)

CIO factory-reset the LX (15s hold) → LEDs solid-green + slow-blink-blue (healthy, advertising).
Pi-side stale bond removed. Clean re-pair interrupted when the **Pi dropped off WiFi** mid-scan —
likely the **Pi 5 WiFi/BT shared-radio coexistence** issue (sustained BT inquiry starves WiFi).
Pending Pi power-cycle → finish re-pair with short scan bursts → confirm raw RPM → start service →
verify drive 35 mints.

## Follow-ups (route to PM once capture restored)

- **Reliability story:** the LX recurringly drops into a dead-SPP state needing a physical reset
  (07-03 + 07-17). Options: (a) service-level auto-recovery that does a full BT re-page / re-pair
  after N consecutive read-failures (not just rfcomm rebind); (b) dongle power management / keep-alive;
  (c) evaluate a more robust adapter (wired/USB) for the always-on capture role.
- **Pi 5 WiFi/BT coexistence:** remote BT re-pair over WiFi risks dropping the Pi's own link.
  Any auto-recovery that scans must burst-scan, and ops re-pairs should prefer short inquiries.
- **A-17 note:** the thread-race smells (double-start "already running", KOEO `_dispatchKeyOnDtcs`
  on the connect edge) are real code hygiene but were NOT today's root cause. Keep on the watch list;
  do not let them mask the dongle-link fault again.
- **A-16 Bug-3 (separate):** carousel kiosk (`eclipse-kiosk`) inactive → black X desktop, no live
  tiles; font too small; no shutdown animation; boot-splash timing wish. Display-side, needs Iris/QA.
