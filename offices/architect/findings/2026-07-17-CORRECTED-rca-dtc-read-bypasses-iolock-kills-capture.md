# CORRECTED RCA — OBD capture failure = unlocked DTC read races the realtime logger (SOFTWARE, not hardware)

**Supersedes my hardware conclusion in `2026-07-17-obd-capture-rca-dongle-dead-spp-link.md`.**
The CIO was right: this is a **software regression** from the last two sessions, not the dongle.
I misdiagnosed it twice tonight; the decisive evidence I under-weighted is below.

## Decisive evidence (why it is software, not hardware)

After I corrected the dongle MAC, a **single-threaded raw `python-obd` read returned 6/6 live RPM
on `/dev/rfcomm0`**, while the **eclipse-obd service failed on the SAME MAC at the SAME moment**
("device disconnected while reading", 0 rows). Same dongle, same address, same second: raw code
works, the multithreaded service does not → the defect is in the service's concurrency, not the
hardware. (The dongle later going dormant was a red herring — likely the failing service's
connect/disconnect/rfcomm thrash wedging its BT firmware.)

## Root cause (code-cited)

The realtime logger reads through the **serialized** wrapper `ObdConnection.query()` under the single
`_ioLock` (US-441/F-117, `logger.py:220`). But the **DTC read path never got that fix** — it hit the
**raw** connection:

- `dtc_client.py:244` `readStoredDtcs` → `connection.obd.query(cmd)` (RAW, bypasses `_ioLock`)
- `dtc_client.py:276` `readPendingDtcs` → `connection.obd.query(cmd)` (RAW)
- `dtc_client.py:321` `clearDtcs` (Mode 04) → `connection.obd.query(clearCmd)` (RAW)
- Documented in the Protocol at `dtc_client.py:141`: *"Only isConnected() + .obd.query(cmd) are touched."*

On the **connection-restored edge** (`event_router.py::_handleConnectionRestored`), the handler
**(1) restarts the realtime logger** (`_restartDataLoggerOnConnectionRestored`) and **(2) fires the
key-on DTC read** `_dispatchKeyOnDtcs` (US-404) → `logKeyOnDtcs` → `dtc_client.readStoredDtcs` →
**raw `connection.obd.query()`**, on the handler thread, **concurrently with the logger thread's
locked read**. The two interleave on the one non-thread-safe python-obd serial port →
**"device disconnected while reading"** → logger `logged=0` → the drive never arms (no RPM captured)
→ `isDriving()` stays False → the KOEO read re-fires on **every** reconnect → **permanent capture
failure** (a self-sustaining loop). Journal signature: `_dispatchKeyOnDtcs failed 'NoneType'…close /
[Errno 9] Bad file descriptor` at the exact instant of the logger's `Device disconnected while reading`.

## Why it worked for months then broke in the last two sessions

F-117 (US-441, V0.29.8 — last two sessions) introduced `_ioLock` and moved the **logger** onto it,
but **left the DTC client on the raw `.obd.query()` path**. That created a mixed regime: locked
logger + unlocked DTC read on the SAME connection. Combined with US-404 (KOEO read on the connect
edge) and US-432/BL-016 (forced connect-edge queries widening the window), the previously-benign DTC
read now deterministically collides with the logger. Before F-117 the reads shared the old scheme;
after F-117 they don't. **This is the errant regression the CIO identified.**

## Fix (implemented this session — UNVALIDATED on car)

`dtc_client.py`: added `_serializedQuery(connection, cmd)` that routes through the wrapper's locked
`connection.query()` when present (falls back to raw `.obd.query` only for duck-typed test fakes),
and pointed all three DTC read/clear sites at it. Now **every** connection read/write — logger AND
DTC (key-on, session-start, during-drive, clear) — shares the single `_ioLock`; they can no longer
interleave. Extends F-117's own proven pattern to the site it missed.

- Unit-validated: `test_dtc_client.py` 18/18 pass, `test_dtc_logger.py` 18/18 pass, syntax OK.
- **DEPLOYED to the Pi 2026-07-17** (out-of-band surgical push onto the V0.29.11 tree — deployed file
  was byte-identical md5 to my base `282c40a`, so push = deployed + this fix only; pushed md5 ==
  repo HEAD md5 `7f470b7…`). Service restarted **clean: active, NRestarts=0, no import/DTC errors**.
  Backup: `dtc_client.py.bak-pre-a17fix-20260717`. Committed to `dev` (`4a17bc1`) so a full deploy keeps it.
- **NOT yet validated on car** — Pi was on WALL power (no running ECU) at deploy, so capture can't be
  exercised. Real proof = next engine-on drive: sustained realtime rows + `drive_start` + drive 35.
  I will NOT claim it fixed until that passes (tonight's lesson).
- Dongle caveat for that drive: config points at the correct new MAC (`…3C…`) but it's unbonded; the
  service should still `rfcomm bind` + open a freshly-powered dongle (as the raw read did). If the
  dongle connects even once, the fix should let capture hold (no more DTC-read collision / reconnect
  thrash). If the dongle stays catatonic, that's the separate hardware reliability item.

## Routing / follow-ups (PM + Ralph)

- Ralph: proper cleanup — add `query()` to the `ObdConnectionLike` Protocol + update fakes so the
  `getattr` fallback becomes a typed contract; run the full pi test suite; deploy.
- On-car validation gate: engine-on → sustained realtime rows + `drive_start` + single clean
  attribution (folds into the A-9 / A-17 / BL-016 re-gate).
- Separate but real: OBDLink LX BT catatonia + MAC-change-on-reset (the dongle finding) — the
  wired/USB-adapter recommendation still stands as reliability hardening, but it is NOT the cause of
  the capture failure. The reconnect-thrash from THIS bug likely aggravated the dongle's BT wedging.
- I owe an apology-in-substance: I asserted "hardware/dongle" against the CIO's correct "software"
  call. Verify-before-asserting failure — I let the dongle-dormancy red herring override the decisive
  raw-works/service-fails-same-MAC evidence.
