# From Marcus (PM) → Ralph — Sprint 13 closeout + carryforward

**Date**: 2026-04-19 (Session 23)
**Subject**: Sprint 13 closed at MILESTONE — engineering deliverables for US-167/US-168 carry to Sprint 14 + 2 new TDs to triage

## TL;DR

Sprint 13 is closed. CIO+PM ran the Run-phase live drill in the garage tonight. **First real Eclipse OBD-II data EVER persisted to local SQLite — 149 rows in 60s.** US-167, US-168 marked passes:true on milestone basis. US-170 blocked on TD-024. **Three new TDs filed (TD-023, TD-024, TD-025) — all yours.**

Don't reset US-167 / US-168. The technical sprint goal was met. What's owed are the engineering deliverables (script in repo, mocked tests, reboot survival, doc updates) — file as housekeeping in your next iteration.

**Bonus carryforward (2nd half of Session 23)**: CIO asked PM to push the milestone end-to-end. `python scripts/sync_now.py` crashed (TD-025). PM bypassed with manual `client.pushDelta()` per-table loop and successfully delivered **176 rows to chi-srv-01:8000** (149 realtime_data + 11 statistics + 16 connection_log). Profiles errored with `int()` on string PK 'daily' — TD-026 filed as a sibling. **End-to-end milestone IS won — the real Eclipse data is on the server now.** Fix TD-025 + TD-026 so the regular `sync_now.py` works without the bypass.

## What happened in the drill (so you have context)

1. **BT pair**: Used a `pexpect` helper script to drive `bluetoothctl` interactively because the OBDLink LX uses SSP with passkey confirmation (not legacy PIN), and bluez agent NoInputNoOutput didn't auto-confirm. Helper script saved on Pi at `~/Projects/Eclipse-01/scripts/pair_obdlink.sh`. **Lift this into the repo as part of US-167 deliverables.**
2. **rfcomm bind**: Manual one-shot via `sudo rfcomm bind 0 00:04:3E:85:0D:FB 1`. Helper script saved on Pi at `~/Projects/Eclipse-01/scripts/connect_obdlink.sh`. **Lift this too.** Reboot survival not implemented — needs `/etc/bluetooth/rfcomm.conf` entry or systemd unit (US-167 AC #5 owed).
3. **python-obd handshake**: `obd.OBD("/dev/rfcomm0", baudrate=38400, fast=False, timeout=10)` returned `Car Connected | ISO 9141-2 | ELM327 v1.4b`. Real ECU talking.
4. **Production orchestrator**: `src/pi/main.py` ran 60s headless. **149 rows persisted** to `data/obd.db` across 11 PIDs at warm idle. ECU transitioned cold→closed-loop fueling cleanly. LTFT=0.00% across all samples (CIO's tune is dialed). 3 PIDs confirmed unsupported by stock 2G ECU (Fuel Pressure 0x0A, MAP 0x0B, Control Module Voltage 0x42 — matches `specs/obd2-research.md`).
5. **US-170 HDMI display crashed**: `pi.hardware.status_display` hit `Could not make GL context current: BadAccess` under X11 and killed the orchestrator runLoop at `uptime=0.6s`. Headless (`SDL_VIDEODRIVER=dummy`) avoided the crash.

## Two new TDs (yours to triage and fix)

### TD-023 — OBD connection layer treats macAddress as serial-port path

`src/pi/obdii/obd_connection.py:285` passes `self.macAddress` directly into `obd.OBD(port=...)` which expects `/dev/rfcomm0`, not a MAC. Drill workaround: edited `.env` to `OBD_BT_MAC=/dev/rfcomm0` (restored at session close).

Fix: detect MAC vs path, do `rfcomm bind` idempotently if MAC, pass the resolved path. Or split into two config keys (`macAddress` + derived `serialPort`). See `~/Projects/Eclipse-01/scripts/connect_obdlink.sh` for the exact rfcomm-bind incantation.

Full spec: `offices/pm/tech_debt/TD-023-obd-connection-mac-as-serial-path.md`

### TD-024 — pi.hardware.status_display GL BadAccess under X11

Crashes the orchestrator runLoop at 0.6s. Distinct from `pi.display.manager` (primary OSOYOO display, which works fine under X11 per Session 22). Likely the status_display overlay requests GL accel that X11 doesn't grant.

Fix: force software renderer for the overlay, or add config flag to disable status_display when primary display is in use, or refactor the overlay to use the same surface as primary display.

Full spec: `offices/pm/tech_debt/TD-024-status-display-gl-badaccess-x11.md`

### TD-025 — SyncClient assumes every in-scope table has an `id` column

`src/pi/data/sync_log.py:getDeltaRows()` runs `SELECT * FROM {tableName} WHERE id > ?` for every table in `IN_SCOPE_TABLES`. Two tables don't have `id`: `vehicle_info` (PK is `vin TEXT`) and `calibration_sessions` (PK is `session_id INTEGER`). On a fresh-init Pi DB, the sync crashes on the first id-less table.

Sprint 11's e2e drill didn't catch this because it used a fixture DB that had been exported with `id` columns everywhere — a property of the export format, not the production schema. The production `database.py:initialize()` correctly preserves natural PKs.

Fix: either add a per-table PK-column registry, or move upsert/static tables (vehicle_info, calibration_sessions) out of the delta-sync set entirely. Option B (move them out) is probably cleaner — the delta-by-id model only fits append-only tables.

Full spec: `offices/pm/tech_debt/TD-025-sync-assumes-id-column-on-all-tables.md`

### TD-026 — SyncClient `int(lastId)` cast fails on TEXT-PK tables

Sibling of TD-025. `src/pi/data/sync_log.py:188` does `int(lastId)` unconditionally. The `profiles` table uses `id TEXT PRIMARY KEY` with values like `'daily'` and `'performance'`. Push of profiles errors:

```
ValueError: invalid literal for int() with base 10: 'daily'
```

Probably solved automatically by TD-025 Option B (move profiles to a separate snapshot/upsert path). Or with Option A (PK registry), drop the int() cast or make it type-aware per the registry.

Full spec: `offices/pm/tech_debt/TD-026-sync-profiles-non-numeric-id.md`

## US-167 + US-168 engineering carryforward (Sprint 14 housekeeping)

**US-167 carryforward**:
- Lift `~/Projects/Eclipse-01/scripts/pair_obdlink.sh` into git-tracked `scripts/pair_obdlink.sh`
- Lift `~/Projects/Eclipse-01/scripts/connect_obdlink.sh` into git-tracked `scripts/connect_obdlink.sh`
- Implement reboot survival (`/etc/bluetooth/rfcomm.conf` or systemd-rfcomm unit) — AC #5
- Write `tests/pi/obdii/test_obd_connection_bt.py` mocked-BT path tests — AC #7
- Update `specs/architecture.md` with the actual BT pair flow — AC #8
- Update `docs/testing.md` with CIO BT-pairing walkthrough — AC #9

**US-168 carryforward**:
- Write `scripts/verify_live_idle.sh` SSH-driven driver — AC #1
- VIN decode (didn't run separately during drill) — AC #3
- Capture `~/Projects/Eclipse-01/data/eclipse_supported_pids.txt` (Spool wants this for ECMLink Phase 2) — AC #5
- Export `data/regression/pi-inputs/eclipse_idle.db` regression fixture (snapshot of tonight's 149 rows) — AC #7
- Write `tests/pi/obdii/test_live_idle_ranges.py` range-check assertions — AC #8
- Update `specs/grounded-knowledge.md` with measured Eclipse values (RPM 793 ± 50 at warm idle, coolant 73-74°C steady, etc.) — AC #9
- Write full completion-note doc with range-check table — AC #10

## US-170 retry (Sprint 14)

File US-192 once TD-024 lands. Re-run main.py with X11 + verify primary display shows live numbers. Reuse the drill chain — engine doesn't need to be running for the display refresh test (cached values render fine).

## Post-session Pi state

- LX paired/bonded/trusted (persistent)
- /dev/rfcomm0 bound at session close (will not survive reboot)
- /home/mcornelison/Projects/Eclipse-01/scripts/{pair,connect}_obdlink.sh exist (uncommitted)
- /home/mcornelison/Projects/Eclipse-01/.env restored to OBD_BT_MAC=00:04:3E:85:0D:FB (clean state — TD-023 will fail any fresh main.py launch until you fix it)
- /home/mcornelison/Projects/Eclipse-01/data/obd.db has 149 real rows (your regression fixture source — DON'T DELETE before exporting)
- /home/mcornelison/Projects/Eclipse-01/data/obd.db.bak-20260419-071703 is the pre-drill backup (12,075 rows from Sprint 11 sync fixture, already on chi-srv-01 — safe to delete after you've absorbed what you need)

## Sprint 14 setup (when CIO is ready)

CIO's near-future hardware task: wire Pi to car accessory power line. Until that's done, B-043 (auto-shutdown on power loss) full lifecycle isn't testable in-vehicle. Sprint 14 candidates:
- US-189, US-190 (B-043 PowerLossOrchestrator + lifecycle test)
- US-192 (US-170 retry, post-TD-024)
- TD-023 + TD-024 + TD-025 + TD-026 fixes (these gate US-189/190/192 + clean sync)
- US-167 + US-168 engineering carryforward (the lists above)
- US-169 (UPS in-car ignition cycles, gated on Pi accessory wiring)

## NEW from Spool — Data Collection roadmap (Session 23, post-milestone review)

Spool independently reviewed the milestone data on the server end and surfaced two critical findings + a 4-story bundle for Sprint 14. Read both Spool notes in full:
- `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md`
- `offices/pm/inbox/2026-04-19-from-spool-data-collection-gaps.md`

### Framing correction Ralph must know

**Real OBD-connected data window was ~23 seconds, not 10 minutes.** CIO described the drill as ~10 min idle but `connection_log` shows 2 connection windows totaling ~23s of actual collected data (147 rows in window 2 alone). Pipeline proved end-to-end, but no warmup curve / cold-start enrichment / closed-loop transitions in the actual capture window. The next post-TD-023 drill needs **uninterrupted ~10 min capture from cold start** to produce a tuning-review-grade datalog.

### "Data Collection Completeness v2" bundle (Sprint 14, Spool-spec'd)

Should be sized + groomed BEFORE the post-TD-023 second drill so the new capture lands in the new schema from row zero (no retroactive UPDATE).

**Story 1 (M)** — Add missing PIDs to Pi collector poll set:
- `ELM_VOLTAGE` (battery voltage via ELM327 ATRV adapter command — closes Spool CR #1, fills primary display gap left by 2G ECU lacking PID 0x42)
- Mode 01 PID 0x03 (Fuel System Status — open/closed loop indicator, gates correct STFT/LTFT interpretation)
- Mode 01 PID 0x01 (MIL on/off + DTC count, poll 0.5 Hz)
- Mode 01 PID 0x1F (Runtime since engine start, poll 0.2 Hz)
- Mode 01 PID 0x33 (Barometric pressure, poll once per drive at start)
- Mode 01 PID 0x15 (Post-cat O2 — PROBE FIRST via PID 0x00 response; 1998 2G may not support; skip silently if unsupported, note in grounded-knowledge)
- Persist to `realtime_data` as new parameter_names. Threshold values for ELM_VOLTAGE per Spool's Phase 1 spec: normal 12.0–15.0V; caution <12.0V (engine running) or >15.0V; danger <11.0V or >15.5V.

**Story 2 (M)** — Add `drive_id` column + engine-state detection:
- New BIGINT/UUID column on `realtime_data`, `connection_log`, `statistics`, `alert_log`
- Engine-start detection: RPM transition 0 → ≥cranking-threshold (~250 RPM)
- Engine-end detection: RPM=0 AND speed=0 for N seconds (suggested N=30s start)
- Existing rows tagged `drive_id = 0` or NULL
- All per-drive analytics + AI prompts filter on drive_id

**Story 3 (L)** — DTC handling (new capability, not just PIDs):
- Mode 03 retrieval at session start + on MIL illumination events
- Mode 07 retrieval at session start (pending codes — may not be 2G-supported, probe + skip)
- New `dtc_log` table: `(dtc_code, description, status [stored|pending|cleared], first_seen_timestamp, last_seen_timestamp, drive_id)`
- Server-side mirror

**Story 4 (S)** — Drive-metadata capture:
- `ambient_temp_at_start` (IAT at key-on before crank — best-available proxy for ambient on 2G)
- Starting battery voltage
- Barometric pressure (from Story 1's PID 0x33)
- Add to `drive_summary` table (already exists server-side per Spool note)

### CR #4 — `data_source` column (CIO-directed via Spool, do BEFORE Sprint 14 second drill)

Add `data_source` column (`'real' | 'replay' | 'physics_sim' | 'fixture'`) to every capture table that can receive non-real data:
- `realtime_data` (highest priority)
- `connection_log`, `statistics`, `calibration_sessions`
- Server-side: `drive_statistics`, `drive_summary`, `analysis_history`

Default `'real'` for live-OBD path. US-191 flat-file replay tags `'replay'`. Physics-sim historical rows tag `'physics_sim'`. Test fixtures tag `'fixture'`. **All server-side analytics + AI prompt inputs + baseline calibrations MUST filter `data_source = 'real'` (or explicit opt-in)** to prevent baseline contamination from sim rows.

Pair with Stories 2-4 schema migration above — same sprint, same migration, do them together.

I'll groom the Sprint 14 contract once CIO greenlights.

— Marcus (with Spool input)
