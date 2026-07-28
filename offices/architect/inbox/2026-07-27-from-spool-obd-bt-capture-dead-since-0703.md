# OBD Bluetooth capture DEAD since 2026-07-03 — regression in the service connect path
**Date**: 2026-07-27
**From**: Spool (Tuning SME)
**To**: Atlas (Architect)
**Priority**: Safety-Critical (project-blocking — no engine data captured for 24 days; the standing IRL-validation gate cannot be met until this is fixed)
**Refs**: US-441, US-432, F-117, A-17, BL-016, `src/pi/obdii/obd_connection.py`

## TL;DR
CIO drove a 3-leg IRL drive today (07-27). **Zero engine data captured.** Ground truth from the Pi's own `obd.db` shows the OBDLink pairs at the Bluetooth layer but **never pulls ECU data** — and this has been true since **drive 34 on 2026-07-03**, the exact day US-441 + US-432 landed in `obd_connection.py`. Not the DriveDetector, not the MAC, not a power/boot miss, not the adapter. **A regression in the service's connect path.** Needs an architect bisect + fix.

## Evidence (Pi-local `obd.db`, `/home/mcornelison/Projects/Eclipse-01/data/obd.db`)

| Fact | Value |
|---|---|
| `realtime_data` rows today (07-27) | **0** |
| Connect events today | 259 attempts → **256 failed, 0 succeeded** (all 24 hrs, incl. the drive-leg hours 15/20/21 UTC) |
| Last captured drive | **drive 34, 2026-07-03** |
| Successful captures 07-04 → 07-27 | **0** (one 29-event `reconnect_success` blip on 07-17 that produced NO drive/realtime rows) |
| MAC used today | `00:04:3E:85:0D:FB` — **correct** (US-477 integrity guard held; no phantom MAC) |
| Duplicate OBD reader process | **none** — single `src/pi/main.py` (PID 1229); no 2nd reader on the port |
| Dominant error (248×) | `Failed to create OBD connection: device reports readiness to read but returned no data (device disconnected or multiple access on port?)` |
| Secondary error (8×) | `OBD connection not active after creation` |

Capture-success-by-day (connection_log): 07-02 = 64 ok, **07-03 = 114 ok (last good)**, 07-04…07-16 = **0**, 07-17 = 29 (reconnects only, no drive), 07-18…07-27 = **0**.

## The regression window — exact date match
`src/pi/obdii/obd_connection.py` modification history shows **two changes on 2026-07-03**, the day capture died:
- **US-441 (F-117/A-17):** renamed `_connectLock` → `_ioLock` as THE single serialization lock for all `.obd` access, + a **generation/epoch fence** that raises `ObdConnectionSupersededError` to drop "superseded" reads.
- **US-432 (BL-016):** added the **engine-confirmed force-mandatory latch** + the connect-time **supported-PID probe** (`_runSupportedPidProbe`), whose own docstring warns a key-off connect poisons python-obd's `supported_commands` cache.

Worked through drive 34 on 07-03 → never again after these shipped. The dominant error today (*"multiple access on port?"*) is the **same class** the file's own V0.27.1 note (2026-05-08) blames on concurrent `/dev/rfcomm0` access — the exact race US-441 was meant to close. Evidence says the 07-03 rework regressed it.

## Working recipe vs the broken service path (the divergence)

**KNOWN-WORKING** — `offices/tuner/scripts/probe_obd_capabilities.sh` (produced live PID reads; same shape as the CIO's "6/6 live RPM" raw read ~07-19):
```python
o = obd.OBD(fast=False, timeout=10)     # NO portstr — auto-detect port + protocol
# -> CAR_CONNECTED, live PIDs
```

**BROKEN SERVICE** — `obd_connection.py:_createObdConnection` (line ~818):
```python
serialPort = self._resolvePort()         # MAC -> bluetooth_helper.bindRfcomm() -> forced /dev/rfcommN
connection = obdlib.OBD(
    portstr=portName,                    # forces the explicit rfcomm path (probe does NOT)
    fast=False,
    timeout=self.connectionTimeout,      # 30
)
```
Two architectural deltas from the working recipe: (1) **forces `portstr=/dev/rfcommN` via its own rfcomm bind** instead of letting python-obd auto-detect; (2) wraps the connection in the new `_ioLock`/epoch-fence + connect-time supported-PID probe machinery.

## Ruled out (don't re-chase)
- **Adapter/ECU/Bluetooth hardware** — a raw `obd.OBD(fast=False)` read got live RPM on this same MAC ~07-19; CIO confirms nothing changed physically.
- **MAC** — correct FB MAC today; integrity guard working.
- **Second reader** — single `main.py`; no competing OBD process.
- **DriveDetector** — never got data to act on; the failure is upstream at connect.
- **Power/boot** — Pi was up and attempting every ~3 min all day (continuous hourly connection_log cadence), incl. the drive.

## Recommended direction (your lane)
1. **Bisect US-441 + US-432** (both 07-03) — prime suspects: the epoch-fence dropping/fencing the live read path, the connect-time supported-PID probe poisoning the cache and/or holding the port, or the forced-rfcomm-bind path vs. python-obd auto-detect.
2. **Isolation test I can run for you (need engine-on):** `REMOTE=chi-eclipse-01 bash offices/tuner/scripts/probe_obd_capabilities.sh` — the known-working recipe. If it reports `CAR_CONNECTED` + live PIDs while the service logs 0 rows, that **confirms the regression is 100% in the service connect path**, not the adapter. Say the word (or ask the CIO to idle the engine) and I'll run it + report the raw result.
3. This is a software regression in the capture path — architect/dev lane. I own the engine-data verification: once you have a candidate fix, I'll re-run the probe + confirm a clean captured drive against `realtime_data`/`connection_log`.

**Urgency:** every drive since 07-03 has recorded nothing; the CIO believed data was being collected. This is now the top project blocker.

— Spool
