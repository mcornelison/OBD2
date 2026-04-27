# Post-Deploy System Test — Deploy-Gap Findings (Sprint 17 additions)

**Date:** 2026-04-23
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Important — four deploy gaps surfaced, Sprint 17 fold-in recommended
**Tie-in:** Extends `2026-04-22-from-spool-sprint17-tuning-priorities.md`

## Context

CIO asked me to system-test the Pi + server after the new deploy (Sprint 15 + 16 bundle). Ran remote validation from my seat — Pi service state, rfcomm, BT response to OBDLink, DB schema, deployed config, journald, server process. CIO will run a short physical test later today to validate capture end-to-end.

## What's working (positive confirmation)

- **US-210 fully deployed on Pi**: `eclipse-obd.service` active with `--simulate` removed, `Restart=always`, `RestartSec=5` ✓
- **US-216 (Power-Down Orchestrator) shipped!** Deployed `config.json` has `pi.power.shutdownThresholds = {enabled: true, warningSoc: 30, imminentSoc: 25, triggerSoc: 20, hysteresisSoc: 5}`. The 30/25/20 SOC ladder I scoped yesterday is live. That means Sprint 17 doesn't need to carry US-216 as carryforward — one less "must-ship" on my yesterday's priorities list.
- **TD-B partially closed**: `pi.batteryMonitoring` removed from deployed config. Dead BatteryMonitor code is now orphaned even from config accidents. (Verify source deletion hasn't happened yet; config removal is sufficient for safety.)
- **Schema state clean**: `realtime_data` + `connection_log` carry `data_source` (real/replay/physics_sim/fixture) + `drive_id` correctly. `battery_health_log` + `dtc_log` tables present. US-195, US-200, US-204, US-217 all reflected in live schema.
- **Bluetooth healthy**: OBDLink LX responds, correctly reports "Adapter connected, but ignition is off" (car not running). Pair + rfcomm0 bind persisted from Sprint 14 US-196.

## Deploy gaps found — recommend as Sprint 17 stories

### 1. 🔴 HIGH — 2.9M stale `real`-tagged rows in drive_id=1 (Pi DB pollution)

Pi `realtime_data` holds **2,939,278 rows** tagged `data_source='real'`, all in `drive_id=1`, spanning **2026-04-21 02:27 → 2026-04-23 03:12 UTC**. Car was not running during this window. That's ~49 hours of ~17 rows/sec synthetic data mis-tagged as real.

Almost certainly a repeat of Sprint 15's 352K-row issue: simulator or benchtest leaked into production DB before US-212's hygiene took effect, and nothing truncated it when deploy landed.

**Impact:**
- Any "real-data baseline" query (including my Session 23 fingerprint lookups + the US-219 review ritual's `--drive-id latest`) is polluted today.
- `drive_id=1` spans both garbage and whatever was supposed to be the first real-collector run — can't easily separate.

**Recommended story:** "US-2XX — Pi operational truncate, Sprint 17 edition" (S, P0). Mirrors US-205 exactly. Keep fixture DB (`eclipse_idle.db`) untouched; hash-verify preservation as before. Pi + server both truncate `realtime_data` + reset `drive_counter`. CIO physical test should ideally run AFTER this truncate so the baseline is clean.

### 2. 🟡 MEDIUM — Persistent journald drop-in installed but NOT effective

`/etc/systemd/journald.conf.d/99-obd-persistent.conf` present with `Storage=persistent` on Pi. **But `/var/log/journal/` is empty** (only `.` and `..`). That means systemd-journald never picked up the new config — either `systemctl restart systemd-journald` didn't fire in the deploy step, or it failed silently, or journal is being written to /run/log/journal (tmpfs) still.

**Impact:**
- US-210's whole point was persistent logs across reboots. Currently we're still running ephemeral.
- Next Pi crash → log evidence gone (the exact pattern Session 6 UPS drain test hit).
- Blocks US-216 testing strategy: if the orchestrator fires stage transitions and the Pi crashes, we lose the forensic trail.

**Recommended story:** "US-2XX — Harden journald persistence deploy step" (S, high). Deploy-pi.sh's `step_install_journald_persistent` needs a post-check that verifies `/var/log/journal/<machine-id>/` actually exists after the `systemctl restart systemd-journald` call. If missing, log and fail loudly. Also add an acceptance test that SSH-verifies persistent journal after a fresh deploy.

### 3. 🟡 MEDIUM — Server runs uvicorn unmanaged (no systemd unit)

Chi-Srv-01 has `uvicorn src.server.main:app --host 0.0.0.0 --port 8000` running as user-mode process PID 3985160 under `mcornelison`. **No `obd-server.service` systemd unit.** No Restart policy. No autostart on reboot.

**Impact:**
- Any Chi-Srv-01 reboot → server stays down until CIO manually restarts it.
- Any server process crash → same.
- Parallel to the pre-US-210 Pi state, but on the server tier.
- Sync from Pi → server will silently fail post-reboot; no alert.

**Recommended story:** "US-2XX — Server tier systemd unit" (M). Mirror of US-210 for the server side:
- Create `deploy/obd-server.service` with `Restart=always`, `RestartSec=5`, correct `WorkingDirectory`, `EnvironmentFile` for DB creds, `User=mcornelison`, `After=network.target mariadb.service`
- Deploy step in `deploy/deploy-server.sh` that installs + enables the unit
- Acceptance: verify server restarts on process kill + on host reboot
- Migrate the currently-running manual uvicorn cleanly (one-time cutover)

### 4. 🟡 LOW — 1,853 physics_sim rows in drive_id=2 (verify intent)

At 2026-04-23 03:12–03:14 UTC today, 1,853 rows landed in Pi DB tagged `data_source='physics_sim'` under `drive_id=2`. The tagging is correct (US-212 hygiene worked — good validation signal), but the presence itself is curious. Could be an intentional benchtest someone ran during Sprint 16 validation, or unintentional leakage.

**Recommended:** Not necessarily a sprint story — CIO or Ralph just confirms whether this was intentional. If intentional, we have evidence US-212 is correctly tagging physics_sim (good!). If unintentional, there's a benchtest process with DB access that shouldn't have it.

## Updated Sprint 17 must-ship list (consolidating yesterday + today)

Revised from yesterday's note based on today's findings:

1. ~~**US-216 Power-Down Orchestrator**~~ ✅ **SHIPPED** — remove from Sprint 17
2. **US-140–144 legacy threshold hotfix bundle** — unchanged, still 10+ days overdue, still safety-dormant
3. **US-211 BT-resilience integration wiring** — still needed before next real drive beyond today's short test
4. **🆕 Pi operational truncate** (above Item 1) — P0, blocks clean baseline
5. **🆕 Journald persistence hardening** (above Item 2) — blocks US-216 forensic testing
6. **🆕 Server systemd unit** (above Item 3) — blocks server reboot resilience
7. **First real-drive review ritual execution** — unchanged (post-today's physical test, if successful)

Lower-priority items from yesterday's note still stand:
- Delete dead BatteryMonitor + battery.py source (config removal done; source still lingers)
- `pi.hardware.enabled` key path fix
- `record_drain_test.py` CLI default flip
- Telemetry logger → UpsMonitor audit follow-up
- DSM DTC cheat sheet

## Positive signal for US-216 validation

Because US-216 shipped, today's physical test can also implicitly validate one piece of the orchestrator: `pi.power.shutdownThresholds.enabled=true` + live service means the monitoring path is presumably running on the Pi right now. I'll confirm against the Pi journal after CIO's test whether the orchestrator's logger emits any baseline telemetry (AC source detected = no action expected, but the heartbeat signature is the tell).

## Physical test plan (CIO today)

90-second test: cold start → idle 30 sec → key off. Detailed in my separate working conversation with CIO. Will report back to you with a drive-review note once the test completes and data lands. If the truncate story lands first, so much the better for clean baseline signal.

## What I did NOT do

- Did not query server MariaDB directly (DB creds not in expected .env location on server; didn't dig further since remote DB inspection isn't critical to this round of system testing)
- Did not audit server logs (no systemd unit = no clean `journalctl -u` path; would need to grep uvicorn stderr if uncaptured, or the systemd logs if redirected — not necessary for today's pass)
- Did not verify US-216 orchestrator code paths in source (config confirms deployment; source audit is for when the orchestrator actually fires a stage transition)

— Spool
