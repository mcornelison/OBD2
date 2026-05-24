# Drive-11 Validation — RESULTS + Drive-12 Re-Validation Checklist

**Originally prepared**: 2026-05-11 (pre-drive) · **Refreshed with actual results**: 2026-05-12
**Tester**: Tester agent
**Drive 11**: 2026-05-11 ~20:10–20:34 CDT (= 2026-05-12 ~01:10–01:34 UTC), `drive_id=11`. First clean car-coupled drive of the V0.27 chain, on the post-B-063 fuse-box buck-converter power feed.
**Verdict**: **PARTIAL — Pi capture + sync GREEN; server-side analytics tier FAIL at every layer; one regression (`startup_log.prior_boot_clean`).** Maps cleanly to V0.27.7 (sprint33, US-326–330). Re-validate on Drive 12 after V0.27.7 deploys.

---

## PART 1 — DRIVE 11 RESULTS

### Scoreboard (each check → result → what it touches)

| # | Check | Result | Maps to |
|---|---|---|---|
| B-063 | Power steady under sustained load | **PASS** | `power_log` over the drive window: `ac_power` ~99% of the 23.5 min, **one** ~5-second `→battery→ac` blip (01:25:51–56). vs the brownout era (Drive 9: ~12× throttling, constant flapping). The fuse-box buck converter works. |
| US-319 | DriveDetector FORENSIC trail | **PASS** | `FORENSIC drive_check` ×682 (one per RPM tick, matches the ~676 realtime_data samples/PID). `FORENSIC drive_state_transition` ×3, clean monotonic: `stopped→starting` (20:10:30, drive_id None) → `starting→running` (20:10:41, **drive_id=11 assigned**) → `running→stopped` (20:34:09). **No spurious extra transition / no warm-restart double-drive.** `DRIVE STARTED \| profile=daily \| drive_id=11` + `drive_end via ECU silence (elapsed 60.9s)` + `DRIVE ENDED \| duration=1406.7s \| peakRPM=5441.25 \| peakSpeed=147.0`. |
| F-003/F-006 | RPM + realtime_data flow during drive | **PASS** | `realtime_data drive_id=11`: **10,839 rows** (Pi *and* server — fully synced), ~676 samples/PID (balanced), span 01:10:41Z–01:34:08Z (~461 rows/min). Healthy capture rate — no brownout throttling. Values all sane (RPM 574–5441, SPEED 0–147 km/h, COOLANT 19–93°C, MAF up to 158.69 g/s, LTFT/STFT in normal band, 0 DTCs, MIL off). |
| F-004 | `drive_start` fires (RPM > 500 for 10 s) | **PASS** | `drive_id=11` minted; Pi `drive_counter.last_drive_id`=11. |
| US-310 (Pi side) | `drive_summary` writer ran, captured start metadata | **PARTIAL PASS** | `FORENSIC drive_summary_writer_entry \| drive_id=11 \| from_state=unknown \| snapshot_keys=[16 PIDs] \| force_insert=False` — writer ran. Pi `drive_summary` row for drive 11 has `drive_start_timestamp` 2026-05-12T01:10:41Z, `ambient_temp_at_start_c=18`, `starting_battery_v=14.5` (alternator charging — engine running). **`barometric_kpa_at_start`=NULL** (PID 0x33 not captured/returned). **`from_state=unknown`** — engine-state machine state at drive-start wasn't determined (minor; the metadata that depends on it still landed). NOTE: the Pi-side `drive_summary` table is *start-metadata-only* — it has no end-time / duration / row_count / is_real columns. Those are meant to be **server-derived** from synced realtime_data. So "12-field" completeness isn't a Pi-side thing here; if V0.27.7 intends the Pi to write end-of-drive fields too, that's a Pi-schema gap US-326's pre-flight should call out. |
| **F-005 / I-026 / US-326** | **server `drive_summary` analytics fields populated** | **FAIL** | Server `drive_summary` id=15, source_id=11: `drive_id`=NULL, `start_time`=NULL, `end_time`=NULL, `duration_seconds`=NULL, `row_count`=0, `is_real`=0, `device_id`=NULL, `profile_id`=NULL. **All server-side analytics columns NULL.** The Pi-synced columns DID arrive (drive_start_timestamp, ambient_temp 18, starting_battery_v 14.5). So sync works; the server never *computes* the analytics columns from the 10,839 synced realtime_data rows. Root cause is structural — see migration 0006 note in §3. (`FORENSIC ensureDriveSummary_entry` on the server: couldn't confirm — needs `sudo journalctl` on chi-srv-01; the DB outcome is conclusive regardless.) |
| **F-007 / US-315** | sync round-trip + delta UPDATE-sync | **PARTIAL** | `realtime_data` round-tripped fully (10,839 rows on the server). Delta-table UPDATE-sync **works** for `battery_health_log`: row id=18 (source_id=17, Drain 17) closed on the server via UPDATE (start 00:23:26 → end 00:34:32, runtime 666 — the close came after the INSERT). But the `drive_summary` delta side is effectively moot until US-326 makes the server row carry computed fields worth re-syncing. Rows 14/15 still stranded `end_timestamp`=NULL (US-323 backfill — see below). |
| **I-029 / US-329** | server `drive_counter` advances | **FAIL** | Server `drive_counter.last_drive_id`=3, Pi=11 — 8-drive gap. **Sharper finding**: `FORENSIC sync_push_drive_counter` count in the Pi journal = **0** — the Pi never even *attempts* to POST the drive_counter. So this isn't "the update didn't propagate"; the sync path for drive_counter is dormant. (Consistent with CIO's "drop the table" directive — fix = stop syncing it / server computes `MAX(drive_id) FROM drives`; the actual `DROP TABLE` lands in the V0.28 schema epic.) |
| **I-028 / US-328** | `drive_statistics` per-PID aggregates for the drive | **FAIL** | `drive_statistics` = 0 rows for Drive 11 (and no such table on the Pi at all). Nothing computes per-PID-per-drive aggregates. Note: the *other* aggregate table, `statistics` (per-PID-per-profile), DID get 21 rows tagged `drive_id=11, profile_id='daily'` — so an aggregation path exists; US-328 may be "wire it to also emit drive-scoped rows" rather than "build a new writer." |
| **I-027 / US-327** | US-323 backfill of stranded `battery_health_log` rows | **FAIL (never ran)** | Server `battery_health_log` rows 14/15 (source 14/15) still `end_timestamp`=NULL — the backfill script was never wired into a deploy. Row 18 (source 17) IS populated, but via the US-315 *forward* path, not a backfill. |
| **I-030 / US-330** | `startup_log.prior_boot_clean` after a graceful shutdown | **REGRESSION** | Post-Drain-17 boot's `startup_log` row has `prior_boot_clean` **empty** — V0.27.4/.5 boots had `=1`. Regression cliff at V0.27.6. |
| F-008/F-011/F-012 | drain ladder + battery_health_log close | **PASS (ongoing)** | Drains 17 + 18 since Drive 11: Drain 17 closed cleanly (Pi + server, runtime 666s). Drain 18 (01:37:29Z) is the latest — `end_timestamp` NULL at time of check (recent / may still be open). The V0.24.1 ladder + close-event continue to work. |

### Net
- **What's solid now**: the in-car edge tier — power (B-063), drive detection, RPM/realtime capture, the Pi→server *transport* (realtime_data, connection_log, battery_health_log UPDATE-sync), the FORENSIC instrumentation. Drive 11 proved the edge.
- **What's broken**: everything downstream of the synced raw data on the server — the analytics writer (`drive_summary` computed fields), the per-drive aggregates (`drive_statistics`), the drive_counter sync, the backfill, plus the `startup_log` regression. All five are exactly what V0.27.7 targets.
- **Regression-manifest impact**: F-005 still REGRESSED (Pi-side works, server analytics doesn't); F-007 PARTIAL (delta UPDATE-sync works for battery_health_log; drive_summary side blocked behind F-005). F-002/F-003/F-004/F-006/F-009 re-confirmed by Drive 11. F-008/F-011/F-012 re-confirmed by Drains 17/18 (Drain Test 16 already bumped these to 2026-05-10 in my earlier manifest-rewalk note).

---

## PART 2 — DRIVE 12 RE-VALIDATION CHECKLIST (run after V0.27.7 deploys + Drive 12 happens)

Pre-conditions: V0.27.7 (sprint33) deployed to Pi + server; B-063 still in place; engine RPM > 500 for ≥ 10 s then a real `drive_end`; return home so the sync sweep runs.

### Step 1 — Pi journal (FORENSIC trail)
```
ssh chi-eclipse-01 'journalctl -u eclipse-obd.service --since "<drive start>" --no-pager | grep "FORENSIC"'
```
Expect (unchanged from Drive 11, which already passed): `drive_check` per RPM tick; `drive_state_transition` ×3 monotonic `stopped→starting→running→stopped` (drive_id=12 on the `starting→running` line) — **and if Drive 12 is a warm restart (engine restarted within a short window), watch for a spurious extra `drive_id` — that's the I-019/US-311 test, untested by the cold-start Drive 11**; `drive_summary_writer_entry \| drive_id=12` (and check `from_state` is no longer `unknown` if US-310/US-326 tightened the cold-start state detection); `sync_push_table_advance \| table=drive_summary \| ... new_id=12` (the drive's summary row pushed); **`sync_push_drive_counter \| last_drive_id=12`** ← this was count=0 on Drive 11; if US-329 keeps any counter-sync it should fire now, OR (if US-329 dropped it) confirm the line is gone and the server computes from `drives` instead.
Power check: `journalctl ... | grep -iE "transition_to_battery|power="` over the drive window — expect ~0 transitions / no flapping (B-063 regression guard).

### Step 2 — Pi DB after the drive
```
ssh chi-eclipse-01 'sqlite3 -header -column ~/Projects/Eclipse-01/data/obd.db "
  SELECT * FROM drive_summary WHERE drive_id=12;
  SELECT COUNT(*) FROM realtime_data WHERE drive_id=12;
  SELECT name FROM sqlite_master WHERE name=\"drive_statistics\";  -- US-328: should now exist
  SELECT COUNT(*) FROM drive_statistics WHERE drive_id=12;          -- US-328: per-PID rows present
  SELECT last_drive_id FROM drive_counter;                          -- 12 (or table gone if US-329 dropped it Pi-side -- unlikely; Pi keeps it)
  SELECT * FROM startup_log ORDER BY rowid DESC LIMIT 1;            -- US-330: prior_boot_clean populated (1 if last shutdown graceful)
  SELECT COUNT(*) FROM connection_log;                              -- B-NEW-1/B-NEW-2: should be much lower-growth if those fixes shipped
"'
```
PASS criteria: `drive_summary.drive_id=12` row present; `realtime_data.drive_id=12` count proportional to drive length (≥ ~400/min — anything ≪ that → re-open B-063); **`drive_statistics` table exists on the Pi AND has per-PID rows for drive 12 for the canonical PIDs (RPM/COOLANT_TEMP/INTAKE_TEMP/MAF/THROTTLE_POS/SHORT_FUEL_TRIM_1/LONG_FUEL_TRIM_1/TIMING_ADVANCE/BATTERY_V) — US-328**; `startup_log` latest row `prior_boot_clean` populated (`1` if the last shutdown was a graceful ladder poweroff, `0` if a hard crash) — **US-330**.

### Step 3 — Server DB after the sync sweep (`obd2db`)
```
mysql -h 10.27.27.10 -u obd2 -p<pw> obd2db --table -e "
  SELECT id, source_id, drive_id, start_time, end_time, duration_seconds, row_count, is_real, profile_id FROM drive_summary WHERE source_id=12;
  SELECT drive_id, COUNT(*) FROM realtime_data WHERE drive_id=12 GROUP BY drive_id;
  SELECT drive_id, COUNT(*) FROM drive_statistics WHERE drive_id=12 GROUP BY drive_id;
  SELECT last_drive_id FROM drive_counter;                          -- 12 (or table dropped per US-329 -> instead: SELECT MAX(drive_id) FROM drive_summary)
  SELECT id, source_id, end_timestamp, runtime_seconds FROM battery_health_log WHERE id BETWEEN 14 AND 22;  -- US-327: rows 14/15 now have end_timestamp/runtime
  SELECT status, COUNT(*) FROM sync_history GROUP BY status;        -- US-327 idempotency / sync health; should still be 0 'failed'
"
```
PASS criteria — **US-326**: server `drive_summary` for source_id=12 has `start_time`, `end_time`, `duration_seconds`, `row_count` (≈ realtime row count), `is_real=1`, `profile_id` populated within ~30 s of the sync round-trip. **US-327**: `battery_health_log` rows 14/15 now carry `end_timestamp`/`end_soc`/`runtime_seconds` (from the backfill); re-running the deploy is a no-op (idempotent). **US-328**: server `drive_statistics` has per-PID rows for drive 12. **US-329**: server `drive_counter`=12 (or, if dropped, the consumers compute it from `drives`). Server journal cross-check: `ssh chi-srv-01 'sudo journalctl -u obd-server.service --since "<sync time>" | grep "FORENSIC ensureDriveSummary_entry"'` → should show `... drive_id=12 | device=chi-eclipse-01 ...` (server confirms it processed the drive's analytics).

### Step 4 — calibration (only once ≥ 5 real drives exist with `drive_statistics`)
Drive 12 makes it real-drive #2. Calibration (`MIN_REAL_DRIVES=5`, needs populated `drive_statistics` per drive) still won't fire. Once enough real drives accumulate AND US-328's writer is producing rows: on chi-srv-01 `cd /mnt/projects/O/OBD2v2 && DATABASE_URL=<.env> python scripts/report.py --calibrate --device chi-eclipse-01` (then `--apply`) → expect it runs to completion (no `ModuleNotFoundError: pymysql` — US-320 done) and `baselines` gets rows. Downstream of US-328 + 5 drives — likely a later validation pass, not Drive 12.

### Outcome → action
- **All of Step 1–3 green** → tell the PM: F-005 + F-007 ready; per the chain-end-merge rule, `/sprint-validated` accumulates across Sprints 28-30 (and now 33), then `/chain-validated` merges the V0.27 chain to main (after the `chain_validate_aggregate.py` dedup fix from the gap file). Tester is the gate on that.
- **`drive_summary` analytics still NULL after Drive 12** → US-326 didn't hold → another bug-fix sprint (V0.27.8). This is the same bug class as the original B-059 / US-237 / I-026 — pre-acknowledge.
- **`drive_state_transition` shows a duplicate/extra drive_id on a warm-restart sequence** → I-019/US-311 not fully fixed → note it (P2, not a chain-blocker).
- **`drive_statistics` still empty** → US-328 didn't ship or didn't wire → blocks calibration indefinitely; escalate.

---

## PART 3 — Why the server analytics fields are NULL (root cause, for US-326's pre-flight)

The Pi-side sync writes only the Pi columns into server `drive_summary` (`drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`, plus `source_id`/`source_device`/`sync_batch_id`/`data_source`). It does **not** write `start_time` / `end_time` / `duration_seconds` / `row_count` / `is_real` / `profile_id` / `device_id` / `drive_id` — those are the server's *analytics* columns, meant to be computed server-side from the synced realtime_data. Historically the INSERT even *failed* because `start_time` was `NOT NULL` with no default (`sync_history` failures id 10685-10693, 2026-05-01: `"Field 'start_time' doesn't have a default value"`); migration `0006` (TD-043, 2026-05-01 07:31) made the server-side legacy analytics columns `NULL DEFAULT NULL`, so since then the INSERT *succeeds* but leaves them NULL. So I-026 is "the server-side analytics writer that's supposed to populate these from realtime_data either never runs for a drive, or runs without computing them." US-326's "Hypothesis A/B pre-flight" should determine which — and also untangle the 3 overlapping column families in `drive_summary` (`device_id`(varchar)/`source_device`(varchar)/`source_id`(int)/`drive_id`(int), and `start_time`/`drive_start_timestamp`) to decide which columns the writer should populate. The V0.28 `drive_summary`→`drives` rename collapses those; for V0.27.7, just pick the right targets and fill them. (Server `_ensureDriveSummary` has a `FORENSIC ensureDriveSummary_entry` line as of US-319 — grep the chi-srv-01 journal with sudo to see whether it fired for Drive 11; that disambiguates "never ran" vs "ran but didn't compute.")

---
*Original pre-Drive-11 checklist content (the speculative "expect X" version) is superseded by Part 1 above; Part 2 carries the live checklist forward to Drive 12.*
