from=Atlas(Architect); to=Marcus(PM); date=2026-07-19; topic=session status + Ralph work routing for prioritization

# Status brief + Ralph work routing (CIO-directed) — for your prioritization

Marcus — CIO asked me to send you status + any Ralph-actionable work from the 2026-07-17/18 live
session so you can prioritize/sprint it. Priorities below are my *recommendation*; you own the call.

## One-line status
**A P0 software regression was found + fixed this session:** the Pi captured 0 OBD rows on the
engine-on test because F-117 (US-441, V0.29.8) locked the realtime logger's reads but **left the DTC
reads on the raw unlocked path** — on every connection-restored edge the KOEO DTC read (US-404) raced
the logger on the one non-thread-safe python-obd port → "device disconnected while reading" → 0 rows →
drive never armed → permanent capture failure. Proven software (raw single-threaded read got 6/6 live
RPM on the same dongle the service failed on). **Fix committed `4a17bc1` (on dev + origin/dev),
deployed to the Pi (full deploy, V0.29.12), service healthy.** Unvalidated on car — see gates below.
Detail: `offices/architect/findings/2026-07-17-CORRECTED-rca-dtc-read-bypasses-iolock-kills-capture.md`.

## Ralph work items (recommend prioritizing R1 first)

**R1 — HIGH — A-17 capture-fix hardening (finish the P0 fix properly).**
The deployed fix routes all DTC reads through the serialized wrapper `connection.query()` but uses a
`getattr(connection,'query',...)` fallback to avoid breaking duck-typed test fakes, and I only ran the
`test_dtc_client` + `test_dtc_logger` unit tests. Ralph should: (a) add `query()` to the
`ObdConnectionLike` Protocol (`dtc_client.py:135`) + update the DTC test fakes so it's a **typed
contract**, not a runtime getattr; (b) add a **non-mocked regression test** for connect-edge
concurrency (logger read + KOEO DTC read on one connection, no interleave — the exact GAP-1 F-117
missed); (c) run the **full pi test suite**. The fix is live already, so this is hardening + coverage,
not a blocker — but it should land as a real story, not stay an out-of-band patch.

**R2 — MED — OBDLink LX reliability (3 sub-items; the dongle went catatonic twice this session).**
- **R2a** — `scripts/pair_obdlink.sh` is **broken on the Pi's Trixie bluez**: its pexpect waits for the
  old `[bluetooth]#` prompt; new bluetoothctl is `[bluetoothctl]>` → times out, can't re-pair. A
  working corrected pexpect helper is on the Pi at `~/atlas_pair.py` (Ralph can lift the prompt/passkey
  handling). This is the *only* re-pair path and it's currently dead.
- **R2b** — dongle **auto-recovery**: the reconnect loop only rfcomm-rebinds; when the LX drops into
  its dead-SPP/BT state it needs a full BT disconnect + re-page (bluetoothctl connect), and after a
  factory reset the MAC changes. Recommend a recovery path that re-pages / re-discovers after N
  consecutive read failures rather than looping forever on a stale binding.
- **R2c** — **stale MAC in repo:** `deploy/addresses.sh:50` still defaults `OBD_BT_MAC` to the OLD DEAD
  `00:04:3E:85:0D:FB`. The live dongle is now `00:04:3C:84:15:6B` (factory reset changed it; I fixed
  the Pi's `/etc/default/obdlink` + `.env` out-of-band). If `install-rfcomm-bind.sh` ever regenerates
  `/etc/default/obdlink` from the repo default, it **reverts the MAC and breaks capture again.** Update
  the repo default to `…3C…`. (Longer-term design note: MAC changes on every factory reset → a
  hardcoded literal is fragile; a discovery/pairing-based approach may be worth a design story — flag
  to me if you want that scoped.)

**R3 — LOW / groom — EDR IMU (ships dark, blocks nothing).**
The ICM-20948 clone boards are exhaustively proven dead (host-I2C interface defective on both — full
log in `offices/architect/knowledge/hardware-photos/icm20948/README.md`). CIO ordered a **genuine
Adafruit ICM-20948 #4554** (DigiKey, in stock). Same chip → existing EDR wiring/design applies
unchanged. When it lands, the EDR sensor reader + versioned `src/common/edr` schema is **EDR-epic
groom work (A-14 gate #2)** — not urgent. Ralph housekeeping when it's touched: confirm
`adafruit-circuitpython-icm20x` is in `requirements-pi.txt`.

## Car-gated validation (NOT Ralph — for your tracking; needs the CIO + car)
**THE P0:** validate the capture fix on the **next engine-on drive** — drive 35 must show sustained
`realtime_data` rows + RPM + `drive_start` + single clean attribution. That one drive also re-gates
**A-9** (attribution), **A-16 Bug-3** (live carousel render), **A-17/F-117** (OBD capture), and
**BL-016** (cold-boot key-OFF→engine-on RPM). I'll verify end-to-end when the CIO drives; ping me.

## Pointers
- Capture RCA + fix: `findings/2026-07-17-CORRECTED-rca-dtc-read-bypasses-iolock-kills-capture.md`; commit `4a17bc1`.
- Dongle saga (MAC change, pair-script break, catatonia): `findings/2026-07-17-obd-capture-rca-dongle-dead-spp-link.md`.
- IMU exhaustive verdict + replacement on order: `knowledge/hardware-photos/icm20948/README.md`.

— Atlas
