# Drain Test Procedure — UPS / V0.24.1 Ladder Validation

> **Purpose**: Validate that the UPS HAT + V0.24.1 staged-shutdown ladder fires correctly under the current code version. Run this whenever a release ships that touches power management, drain handling, sync of battery_health_log, or startup_log writers.
>
> **Owner**: Spool (Tuning SME) — but this is a Pi-tier infrastructure validation, not engine tuning. Tuning matters because corrupted drains = corrupted realtime_data window = corrupted baseline shelf data.
>
> **Authoritative reference run**: Drain Test 15, 2026-05-10T13:57:00Z–14:13:49Z, V0.27.3 (`47e6aa5`), 4 of 5 targets PASS (B-065 server sync gap not in V0.27.3 scope, expected fail). See "Reference Result" section below. Drain Test 13 (V0.27.2) preserved in Historical Drain Test Log as the prior reference.

---

## When to run

| Trigger | Why |
|---|---|
| New release deployed that touched `src/pi/power/` or `src/pi/hardware/ups_monitor.py` | Verify the ladder + close-event writers still work |
| New release that claims to fix a power-management bug (V0.27.2 close-event race, V0.27.3 sync-update gap, etc.) | Verify the fix actually lands in production |
| Pi has been on UPS battery for an unusual reason (USB-C flicker, unintentional unplug, etc.) | Calibration check — does the ladder still fire from the current battery state? |
| Periodic regression — suggested every 4-6 weeks | Detect silent drift |
| Per-sprint validation if the sprint touched B-043 (PowerLossOrchestrator) | Sprint validation gate |

**Do NOT run** during car-coupled testing where the engine is being driven — this procedure is for bench-unplug only. Use the post-fuse-box-wiring procedure (TBD) for in-vehicle drain tests.

---

## Pre-requisites

1. **Pi at bench**, on stable wall power (NOT car-coupled — bench AC, portable inverter, or the UPS HAT's pass-through wall input).
2. **No active drive** in progress — `drive_counter` should be quiescent.
3. **CIO physically present** to (a) unplug, (b) read the dashboard, (c) re-plug, (d) report timestamps.
4. **Network reachable** (SSH to Pi must work). If network's flaky, expect to fall back to dashboard-narrate-only mode (visible = mostly capturable).
5. **Battery not exhausted** — start_soc should be ≥ 3.9V (`SOC ≥ 75%`). If lower, give the battery 30+ minutes of AC charging before starting.

---

## Step 1 — Pre-drain baseline capture

Spool runs this from the workstation:

```bash
ssh mcornelison@chi-eclipse-01 "
echo '=== deploy-version ==='
cat /home/mcornelison/Projects/Eclipse-01/.deploy-version

echo '=== eclipse-obd.service status ==='
systemctl is-active eclipse-obd.service
systemctl show eclipse-obd.service -p ActiveEnterTimestamp -p MainPID --no-pager

echo '=== open drain rows (note these so they don't confuse post-test query) ==='
sqlite3 /home/mcornelison/Projects/Eclipse-01/data/obd.db 'SELECT drain_event_id, start_timestamp, end_timestamp FROM battery_health_log WHERE end_timestamp IS NULL ORDER BY drain_event_id DESC LIMIT 5;'

echo '=== latest power_log entries (note last id; new stage rows will be id+1+) ==='
sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db 'SELECT id, timestamp, power_source, vcell, event_type FROM power_log ORDER BY id DESC LIMIT 5;'

echo '=== current UTC ==='
date -u +%Y-%m-%dT%H:%M:%SZ
"
```

**Record into the test log**: deploy-version (with gitHash + theme), service uptime, the LAST power_log id (so post-test we can filter `WHERE id > N`), the current open drains (so we don't confuse them with the new test drain), and the current UTC timestamp.

---

## Step 2 — Start the independent bash logger

Backup data path. Captures VCELL/SOC/CRATE every 5 seconds via direct i2cget calls — ZERO shared code with the orchestrator's Python writer. If both agree post-test, we have high confidence the production logger is trustworthy.

```bash
ssh mcornelison@chi-eclipse-01 "
sudo -n systemd-run --unit=spool-drain-log --no-block /home/mcornelison/Projects/Eclipse-01/scripts/drain_log_simple.sh
sleep 6
# Confirm running + writing valid data (not i2c_err)
LATEST=\$(ls -t /var/log/eclipse-obd/drain-bash-*.csv 2>/dev/null | head -1)
echo \"file: \$LATEST\"
tail -3 \"\$LATEST\"
systemctl is-active spool-drain-log.service
"
```

**Why systemd-run instead of nohup**: The bash script needs i2c access via `/usr/sbin/i2cget`. Without sudo, `i2cget` is "command not found" (PATH issue) AND lacks i2c device permissions. systemd-run with `sudo -n` gives both. Also: systemd-run survives SSH session disconnect, which `nohup` does not reliably do over SSH.

**Confirm the CSV header has real values, not `i2c_err`**, before proceeding:
```
timestamp_utc,seconds_since_start,vcell_v,soc_pct,crate_pct_per_hr,cpu_temp_c,core_v,throttled_hex,load_1min
2026-05-10T02:17:18Z,0,4.22625,90,disabled,46.1,0.8359,0x0,0.34
```

If you see `i2c_err` in the vcell_v column, STOP — sudo isn't working. Check passwordless sudo with `sudo -n true`. Don't proceed without the bash logger; the cross-check is load-bearing.

---

## Step 3 — The drain itself

CIO actions:

1. **Note wall-clock time** (phone, NTP-synced) immediately before the unplug. Report to Spool as the unplug timestamp.
2. **Unplug wall power.** Watch the dashboard.
3. **Narrate stage transitions to Spool** as they fire:
   - "WARNING fired at HH:MM:SS, VCELL=X.XXX"
   - "IMMINENT fired at HH:MM:SS, VCELL=X.XXX"
   - "TRIGGER fired at HH:MM:SS, VCELL=X.XXX"
   - "Pi powered off at approximately HH:MM:SS"
4. After Pi powers off, **wait at least 30 sec**, then **plug wall power back in.**
5. **Note the replug timestamp.**
6. Wait for Pi to boot — should be ~30-60 sec for OS, another 30-60 sec for orchestrator service.
7. **Report when dashboard is responsive again.**

**Expected timing** (from a healthy battery near full charge):
- Power-source flip on dashboard: <30 sec after unplug
- WARNING fires: 5-7 min after unplug, at VCELL ≈ 3.70V
- IMMINENT: 9-11 min after unplug, at VCELL ≈ 3.55V
- TRIGGER: 12-13 min after unplug, at VCELL ≈ 3.41V
- Pi off: TRIGGER + 5 sec
- Total drain runtime (WARNING → TRIGGER): ~10:00-10:30

**If battery was partially cycled** (typical on a USB-C-flicker day), runtime can shrink to 7-10 min. That's NOT a fail — just shorter. The threshold VCELL values are absolute, not relative-to-full.

---

## Step 4 — Post-drain validation query

Spool runs this once Pi is back up:

```bash
ssh mcornelison@chi-eclipse-01 "
echo '=== 1. V0.24.1 ladder stage rows from THIS drain ==='
sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db \"SELECT id, timestamp, vcell, event_type FROM power_log WHERE timestamp >= '<UNPLUG_TIMESTAMP>' AND event_type LIKE 'stage_%' ORDER BY id;\"

echo '=== 2. AC->battery transition logged ==='
sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db \"SELECT id, timestamp, power_source, vcell, event_type FROM power_log WHERE timestamp >= '<UNPLUG_TIMESTAMP>' ORDER BY id LIMIT 10;\"

echo '=== 3. THIS drain row in battery_health_log (close-event check) ==='
sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db \"SELECT drain_event_id, start_timestamp, end_timestamp, runtime_seconds, start_soc, end_soc FROM battery_health_log WHERE start_timestamp >= '<UNPLUG_TIMESTAMP>';\"

echo '=== 4. startup_log latest 3 (US-308 graceful detection check) ==='
sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db 'SELECT boot_id, prior_boot_clean, prior_last_entry_ts, current_boot_first_entry_ts, recorded_at FROM startup_log ORDER BY rowid DESC LIMIT 3;'

echo '=== 5. bash logger CSV summary ==='
LATEST=\$(ls -t /var/log/eclipse-obd/drain-bash-*.csv 2>/dev/null | head -1)
echo \"file: \$LATEST\"
echo \"total rows: \$(wc -l < \"\$LATEST\")\"
echo 'first 3:'; head -4 \"\$LATEST\"
echo 'last 3:'; tail -3 \"\$LATEST\"
"

# Server-side cross-check (NEW V0.27.3+ test target — sync of close-event UPDATE)
ssh mcornelison@chi-srv-01 'mysql -uobd2 -p<DB_PASSWORD> obd2db -e "
SELECT id, source_id AS pi_drain_id, start_timestamp, end_timestamp, runtime_seconds, start_soc, end_soc
FROM battery_health_log
WHERE source_id = <NEW_DRAIN_ID>;
"'
```

**Replace placeholders**:
- `<UNPLUG_TIMESTAMP>` = the UTC timestamp Mike reported in Step 3.1.
- `<NEW_DRAIN_ID>` = the drain_event_id from query 3 above.
- `<DB_PASSWORD>` = read from `.env` `DATABASE_URL` line.

---

## Step 5 — Pass/Fail evaluation

Apply each validation target against the query results:

| Target | Pass criterion | Fail signature |
|---|---|---|
| **V0.24.1 ladder fires** | Three rows in power_log with event_type `stage_warning` / `stage_imminent` / `stage_trigger`, monotonically increasing timestamp, monotonically decreasing VCELL, all timestamps ≥ unplug | <3 stage rows OR rows out of VCELL order OR timestamps before unplug |
| **WARNING threshold** | stage_warning VCELL within 3.69-3.71V | ≥3.75V or ≤3.65V |
| **IMMINENT threshold** | stage_imminent VCELL within 3.50-3.60V | ≥3.65V or ≤3.40V |
| **TRIGGER threshold** | stage_trigger VCELL within 3.40-3.46V | ≥3.50V or ≤3.30V |
| **Close-event-on-poweroff race FIXED** (V0.27.2 contract) | battery_health_log row for THIS drain has non-NULL `end_timestamp`, `runtime_seconds`, `end_soc` | Any of those 3 columns NULL = race not fixed |
| **`runtime_seconds` matches stage timing** | `runtime_seconds` ≈ (stage_trigger.timestamp - stage_warning.timestamp), within ±2s | Wildly different = writer logic broken |
| **US-308 startup_log writer** (V0.27.2 contract) | Latest startup_log row has `prior_boot_clean = 1`, recorded_at after unplug timestamp | Empty row OR prior_boot_clean = 0 = US-308 not detecting graceful shutdown |
| **Bash logger cross-check** | CSV first/last rows show full drain curve from ~4.2V down to TRIGGER level; no `i2c_err` rows | Logger silent or i2c_err = sudo/permission issue, not a code regression |
| **Server-side sync of drain closure** (V0.27.3+ contract — pending B-065) | Server's battery_health_log row for `source_id = <NEW_DRAIN_ID>` has non-NULL `end_timestamp` + `runtime_seconds` + `end_soc` | Server has NULL on those columns = sync UPDATE-propagation bug. **Confirmed reproducible 5-of-5 on V0.27.2** (drains 10-14). Sync client INSERTs new rows fine; never propagates UPDATEs. **CRITICAL**: when filing a "close-event race" bug, explicitly state whether you queried Pi-side or server-side — same NULL on different DBs has DIFFERENT bug shapes. Never claim "close-event broken" from server-side data alone. |

**Record the verdict per target.** Don't average — a 4/5 pass is meaningfully different from 5/5.

---

## Step 6 — Test result write-up

Append to this file's "Historical Drain Test Log" section below. Format:

```
### Drain Test N — YYYY-MM-DDTHH:MM:SSZ — V0.X.Y (gitHash)
- Pass: A/B/C/D (where applicable)
- Stage timings: WARNING@HH:MM:SS@X.XXXV / IMMINENT@HH:MM:SS@X.XXXV / TRIGGER@HH:MM:SS@X.XXXV
- runtime_seconds: NNN (target ~600)
- prior_boot_clean: 1 / 0
- Server sync of closure: PASS / FAIL
- Notable observations: ...
```

Also: send a brief PM note if anything failed, OR if a previously-failing target now passes (regression-fix landed).

---

## Reference Result — Drain Test 15 (V0.27.3 baseline, AUTHORITATIVE)

| Field | Value |
|---|---|
| **Test date** | 2026-05-10 |
| **Code version** | V0.27.3 (`47e6aa5`) |
| **Theme** | Sprint 29 bug-fix (US-310/311/312/314, US-313 wontfix) |
| **Two-observer validated** | Yes (Spool + Marcus reports matched on 8 load-bearing fields) |
| **Pre-drain VCELL** | 4.178V (96% SOC, fully rested + recharged) |
| **Unplug timestamp** | 2026-05-10T13:57:00Z |
| **transition_to_battery logged** | 13:57:02Z (+0:02 lag) |
| **WARNING fired** | 14:00:43Z (+3:43, VCELL **3.695V**) |
| **IMMINENT fired** | 14:09:48Z (+12:48, VCELL **3.544V**) |
| **TRIGGER fired** | 14:13:49Z (+16:49, VCELL **3.445V**) |
| **runtime_seconds** | 786 (13:06 from WARNING to TRIGGER — longest clean drain on record) |
| **drain_event_id** (Pi) | 15 |
| **start_soc** (NB: holds VCELL post-handoff, not pre-unplug — see notable observation below) | 3.93875V |
| **end_soc** (same caveat) | 3.445V |
| **Bash logger rows** | 274 (full curve from 4.178V → 3.219V, no `i2c_err`) |
| **prior_boot_clean** (current boot row) | **1** ✓ US-308 working |
| **boot_id** (current boot) | `88c03212cbc5417aabb4c128814743f5` |

**Verdict (4 of 5 PASS)**:
- ✅ V0.24.1 ladder fires correctly (no regression from V0.27.2)
- ✅ Pi-side close-event written (V0.27.2 fix carry-forward)
- ✅ US-308 startup_log graceful detection (V0.27.2 fix carry-forward)
- ✅ Bash logger cross-check (independent VCELL stream agrees)
- ❌ Server-side sync of close-event UPDATE — NULL on server; **B-065 not in V0.27.3 scope, expected**, scheduled for V0.27.4

**Why this replaces Drain Test 13 as the bench reference**: Drain Test 15 captures cleaner data (96% SOC pre-drain, no flicker baggage), runs longer (13:06 vs 10:17), validates one more fix (US-308 carry-forward under V0.27.3 not just V0.27.2), and is two-observer-validated with Marcus.

**Notable observation — `start_soc` captures POST-handoff VCELL, not pre-unplug**:

The bash logger trace shows:
```
13:56:57Z  4.176V  (3 sec pre-unplug, AC steady)
13:57:02Z  3.939V  (AC just dropped — initial sag)  <-- start_soc captures this
13:57:18Z  3.819V  (settled load curve)
```

`drain_event_id=15.start_soc = 3.939V` — the recorder captures VCELL at the moment of `transition_to_battery`, by which time cell voltage has already sagged from the initial load handoff. **`start_soc` is NOT "VCELL at unplug"** — it's "VCELL post-handoff." For analytics that compare drain start states across drives, this distinction matters. Pre-drain VCELL needs to come from somewhere else (the bash logger, or a snapshot taken before unplug). Adding to `specs/grounded-knowledge.md` is recommended (PM channel — out of Spool's edit lane).

---

## Reference Result — Drain Test 13 (V0.27.2 baseline, prior reference)

| Field | Value |
|---|---|
| **Test date** | 2026-05-10 |
| **Code version** | V0.27.2 (`f9be758`) |
| **Theme** | Sprint 28 bug-fix (US-304/306/307/308/309) |
| **Unplug timestamp** | 2026-05-10T02:18:15Z |
| **transition_to_battery logged** | 02:18:21Z (+0:06 lag) |
| **WARNING fired** | 02:24:42Z (+6:27, VCELL **3.69875V**) |
| **IMMINENT fired** | 02:30:23Z (+12:08, VCELL **3.530V**) |
| **TRIGGER fired** | 02:34:59Z (+16:44, VCELL **3.44375V**) |
| **runtime_seconds** | 617 (10:17 from WARNING to TRIGGER) |
| **drain_event_id** (Pi) | 13 |
| **start_soc** (note: holds VCELL not SOC, separate P3 bug) | 4.15125V |
| **end_soc** (same caveat) | 3.44375V |
| **Bash logger rows** | 247 (across drain + reboot) |
| **Bash logger first VCELL** | 4.226V (90% SOC) |
| **prior_boot_clean** (current boot row) | **1** ✓ US-308 working |
| **boot_id** (current boot) | `9d7d085e420b4015a314debb600bd45f` |
| **Pi-back-online** | 02:37:02Z (+18:47 from unplug) |

**Verdict (3 of 4 PASS)**:
- ✅ V0.24.1 ladder fires correctly
- ✅ Close-event-on-poweroff race FIXED (V0.27.2 contract met)
- ✅ US-308 startup_log writer firing correctly (V0.27.2 contract met)
- ❌ Server-side sync of close-event UPDATE — NEW BUG, scheduled for V0.27.3

**Notable observations**:
- 6-second lag between unplug and `transition_to_battery` log entry — within tolerance.
- Battery had been micro-cycling all day from USB-C flicker, but runtime came in slightly LONGER than my estimate (16:44 elapsed unplug-to-trigger, 10:17 stage WARNING-to-TRIGGER). Battery less degraded than I had pessimistically assumed.
- Bash logger SURVIVED the Pi reboot via systemd-transient (`spool-drain-log.service`) — same CSV file continued post-reboot for charging-curve data.
- Network flaked ~once during the test window (SSH timeout from gateway "destination host unreachable"). Pi was up locally; recovered after Mike's reboot. Doesn't invalidate the test.
- Drains 10, 11, 12 from earlier the same day (V0.27.1 era? ambiguous — actually V0.27.2 deploy was 01:16:30Z, so drains 11+12 were post-deploy) ALSO closed cleanly on Pi but with NULL closure on server — same sync bug pattern.

---

## Historical Drain Test Log

### Drain Test 13 — 2026-05-10T02:18:15Z — V0.27.2 (`f9be758`)

See "Reference Result" section above. **3 of 4 PASS**, sync-side close-event-UPDATE bug discovered.

### Drain Test 12 — 2026-05-10T01:12:28Z — V0.27.1/V0.27.2 transition

Triggered by USB-C flicker mid-Drive-10 (parking maneuver). 30-sec drain (battery already partially depleted). Stage rows fired correctly. Pi-side close-event clean (runtime_seconds=15). Server-side sync of close-event NULL (bug exposed by this drain too). Not a deliberate test, but produced data.

### Drain Test 11 — 2026-05-10T00:46:12Z — V0.27.1 era

Triggered by USB-C flicker around Drive 9 boundary. 6:16 drain. Same pattern as Drain 12.

### Drain Test 10 — 2026-05-10T00:00:57Z — V0.27.1 era

Triggered by USB-C flicker between Drive 8 and Drive 9. 11:36 drain. Same pattern.

### Drain Test 8 — 2026-05-09T01:24:04Z — V0.27.0

CIO's "normal simulated power off" post-Sprint-27 deploy. 12:42 drain. Cleaned up correctly per Sprint 27 close note. Reference for V0.27.0 baseline.

### Drain Tests 1-7 (historical — V0.24.1 development era)

See `knowledge.md` "UPS HAT Dropout Characteristics" section. Drain 7 (2026-05-02) is the canonical pre-V0.24.1-fix baseline. Drain 10 (2026-05-04) was the first post-V0.24.1-fix successful ladder fire.

---

## Future-Spool: post-fuse-box-wiring drain test variants

Once Mike completes the fuse-box wiring (proper 12V→5V/5A buck converter on switched circuit), there will be TWO additional drain test variants worth running:

**Variant A — Key-off triggered drain**: Instead of unplugging, turn the car key OFF. Pi should detect AC loss the same way (via UPS HAT), and the V0.24.1 ladder should fire identically. Validates that key-off behaves the same as bench-unplug.

**Variant B — Mid-drive ignition cycle**: Engine running → key off → key back on within 30 sec. Validates DriveDetector warm-restart-cranking gap (V0.27.3 P1 candidate) AND validates the orchestrator handles brief AC blips without false-firing the ladder.

Both gated on the wiring fix. Procedure stubs to add here when the time comes.
