> # ⛔ SUPERSEDED (2026-07-20) — do NOT act on this finding
> **Both load-bearing conclusions below were later DISPROVEN. Superseded by
> `findings/2026-07-17-CORRECTED-rca-dtc-read-bypasses-iolock-kills-capture.md`.**
>
> 1. **Verdict "hardware/dead-SPP, NOT software" is WRONG — the root cause was SOFTWARE**
>    (`dtc_client.py` DTC reads bypassed F-117's `_ioLock`; the CIO insisted it was software and
>    was right). A raw single-threaded read got **6/6 live RPM on the real dongle** the service
>    failed on — the decisive software proof.
> 2. **"Factory reset changed the BT MAC `00:04:3E:85:0D:FB` → `00:04:3C:84:15:6B`" is WRONG.**
>    A BT MAC is burned into hardware — a factory reset does NOT change it. `…3C…` was a
>    **phantom / stranger's device** I mis-identified in the marathon. The **real OBDLink LX MAC
>    is `00:04:3E:85:0D:FB`** (broadcast name `OBDLink LX`), triple-confirmed 2026-07-20: the CIO's
>    phone-paired Device-details screen, MEMORY.md, and every product file in the repo
>    (`addresses.sh`, `.env.production.example`, all tests/docs). **Any config or story that
>    repoints to `…3C…` would break capture — do not.** (This mistake propagated into my
>    2026-07-19 PM routing note and PM backlog US-477; both corrected.)
>
> _Original 2026-07-17 text preserved below verbatim as the point-in-time record._

---

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

## Resolution status (2026-07-17 EOD — PARTIAL: config fixed, dongle bond BLOCKED)

**Fixed + proven:**
- CIO factory-reset the LX (15s hold). **The reset CHANGED the dongle's BT MAC** from
  `00:04:3E:85:0D:FB` → **`00:04:3C:84:15:6B`** (discovered live in a scan). This is why every
  connect/bind after the reset failed — all config still pointed at the dead old MAC.
- **Live RPM proven:** with the new MAC, `rfcomm bind` + a single-threaded raw read returned
  **6/6 RPM** off the running engine (ISO 9141-2, ~760-784 idle). Dongle hardware = healthy.
- **Config corrected + persisted:** `/etc/default/obdlink` (the authoritative source — an
  EnvironmentFile-style `OBD_BT_MAC=`; `.env` can't override it because `secrets_loader.py:90`
  is `if key not in os.environ`) + `.env` both updated to the new MAC; survives reboot. Backups:
  `/etc/default/obdlink.bak-20260717`, `.env.bak-pre-macfix-20260717`.

**BLOCKED — dongle will not stay on Bluetooth:**
- After the one good read, the LX went **catatonic again** and would not return to a
  discoverable/connectable state — through button-holds (solid blue), unplug/replug power-cycles,
  a full engine-off + **Pi reboot**, a `systemctl restart bluetooth` + `hciconfig hci0 reset`.
- **Pi BT radio is HEALTHY** — a classic inquiry (`hcitool scan`) discovered a nearby Pioneer head
  unit (`DMH-W2770NEX`) but **not** the OBDLink across 5 passes while CIO held the button. The
  dongle simply isn't broadcasting.
- **Tooling drift found:** `bluetoothctl scan on` is wedged on this Trixie bluez (`Discovering: no`,
  0 devices) while legacy `hcitool scan` works — and the sanctioned `scripts/pair_obdlink.sh` is
  **broken on this bluez** (pexpect waits for the old `[bluetooth]#` prompt; new is `[bluetoothctl]>`).
- The always-on service needs the new MAC **bonded** (paired+trusted) to auto-reconnect; without a
  bond it only connected the one time while the ACL link was transiently up. The bond could not be
  completed remotely (dongle undiscoverable) — needs a bench/interactive pair or a new adapter.

**This is the 3rd catatonic-dongle episode (07-03, earlier 07-17, EOD 07-17).** Recommendation
elevated: **replace the flaky BT OBDLink LX with a wired/USB adapter for the always-on capture role.**

**Pi left clean:** `eclipse-obd` running (honestly failing to connect the dead dongle — no fabricated
data), config on the correct new MAC. Capture resumes the instant the dongle is reliably bonded.
Helper scripts left on Pi: `~/atlas_rawread.py`, `~/atlas_pair.py|2|3.py` (throwaway ops tools).

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
