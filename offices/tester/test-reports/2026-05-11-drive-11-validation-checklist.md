# Drive-11 Validation Checklist — V0.27 Chain IRL Acceptance

**Date prepared**: 2026-05-11
**Prepared by**: Tester agent
**Trigger**: Run this immediately after the first clean car-coupled drive on the post-B-063 power feed (`drive_id = 11` or higher).
**Goal**: One drive closes the bulk of the V0.27 chain's outstanding IRL acceptance criteria. This checklist says exactly which evidence to pull, where, and which `bigDefinitionOfDone` clause each piece closes.

**Pre-conditions for "Drive 11" to count:**
- B-063 done: Pi on the fuse-box switched-12 V → buck-converter → 5 V/5 A feed. During the drive, `power=car` should stay steady (no `power=battery` flicker).
- Engine actually run long enough for a real drive: RPM > 500 for ≥ 10 s, then a real `drive_end` (key-off or ECU-silence). Idle-only doesn't exercise the writers the same way.
- Return home so the WiFi sync sweep runs (or wait for it). Sync needs to complete for the server-side checks.

---

## Step 0 — establish baseline (do this BEFORE Drive 11, optional but recommended)

```
# Pi
ssh chi-eclipse-01 'sqlite3 ~/Projects/Eclipse-01/data/obd.db \
  "SELECT (SELECT last_drive_id FROM drive_counter), (SELECT COUNT(*) FROM drive_summary), (SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL);"'
# Server
mysql -h 10.27.27.10 -u obd2 -p<pw> obd2db -e \
  "SELECT (SELECT last_drive_id FROM drive_counter), (SELECT COUNT(*) FROM drive_summary), (SELECT COUNT(*) FROM drive_statistics);"
```
Record the numbers. As of 2026-05-11: Pi `drive_counter=10`, Pi `drive_summary=4`, Pi NULL-`drive_id` realtime rows `=61,293`; server `drive_counter=3`, server `drive_summary=3` (ghosts), server `drive_statistics=0`.

---

## Step 1 — Pi journal: the `FORENSIC` trail (US-319 self-validates here)

```
ssh chi-eclipse-01 'journalctl -u eclipse-obd.service --since "<drive start time>" --no-pager | grep "FORENSIC"'
```

| Look for | Closes |
|----------|--------|
| `FORENSIC drive_check \| RPM=… \| state=… \| above_start=… \| drive_id=11` (many lines, one per RPM tick) | confirms DriveDetector saw real RPM and evaluated the start/end thresholds — US-319 detector surface |
| `FORENSIC drive_state_transition \| from=stopped \| to=starting \| drive_id=11` then `… to=running …` then later `… to=stopping …` → `… to=stopped …` | the monotonic state machine ran end-to-end on a real drive — and is the discriminator for the I-019 / US-311 warm-restart hypothesis (watch whether a warm-restart-cranking sequence produces a spurious extra drive_id) |
| `FORENSIC drive_summary_writer_entry \| drive_id=11 \| from_state=… \| force_insert=…` (at least once at drive-start) | the drive_summary writer was actually invoked (US-310 / US-317) — fires even if it defers, so its presence is the proof the code path ran |
| `FORENSIC sync_push_table_advance \| table=drive_summary \| old_id=… \| new_id=11 \| old_modified_at=… \| new_modified_at=… \| rows=…` | the drive_summary row got pushed/updated to the server (US-315 drive_summary side) |
| `FORENSIC sync_push_drive_counter \| last_drive_id=11` | the drive_counter advance was POSTed (US-314 / US-315) |
| `RECONNECT HEARTBEAT` lines throughout; a `DRIVE STARTED` / `DRIVE ENDED` INFO pair; no `ERROR` lines except known engine-off ones | general health |

Also check power stability for B-063: `journalctl -u eclipse-obd.service --since "<drive>" | grep -iE "power=|brownout|battery"` — should be `power=car` the whole drive, no flapping.

---

## Step 2 — Pi DB after the drive (before/after the sync sweep)

```
ssh chi-eclipse-01 'sqlite3 -header -column ~/Projects/Eclipse-01/data/obd.db "
  SELECT * FROM drive_summary WHERE drive_id=11;
  SELECT COUNT(*) AS rt11 FROM realtime_data WHERE drive_id=11;
  SELECT last_drive_id FROM drive_counter;
  SELECT * FROM startup_log ORDER BY rowid DESC LIMIT 1;
"'
```

| Assert | Closes |
|--------|--------|
| `drive_summary` has a `drive_id=11` row, written within ~30 s of `drive_end`, with **non-NULL** `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start` | **F-005** (drive_summary INSERT on drive_end) + V0.27.2 US-304 + V0.27.3 US-310 (12-field) — this is the headline acceptance |
| `realtime_data` rows for `drive_id=11` > 0 and roughly proportional to drive length (Drive 8 did 459 rows/min on healthy power; anything ≪ that suggests a brownout — re-open B-063) | F-003 / F-006 re-confirmation + B-063 sanity |
| `drive_counter.last_drive_id` advanced to 11 | F-004 re-confirmation |
| latest `startup_log` row's `prior_boot_clean` is `1` if the last shutdown was a graceful ladder poweroff, `0` if it was a hard crash | V0.27.2 US-308 (only meaningful if there was a power cycle around the drive) |

If `drive_summary.drive_id=11` is **missing or has NULL metadata fields** → the B-059/US-310 fix did NOT hold; file a gap, do not merge the chain.

---

## Step 3 — server DB after the sync sweep (`obd2db`)

```
mysql -h 10.27.27.10 -u obd2 -p<pw> obd2db --table -e "
  SELECT * FROM drive_summary WHERE source_device='chi-eclipse-01' AND drive_id=11;
  SELECT drive_id, COUNT(*) FROM realtime_data WHERE drive_id=11 GROUP BY drive_id;
  SELECT last_drive_id FROM drive_counter;
  SELECT id, drive_id, COUNT(*) FROM drive_statistics WHERE drive_id=11 GROUP BY drive_id;
"
```

| Assert | Closes |
|--------|--------|
| server `drive_summary` has a row for `drive_id=11` with all 12 fields populated, within ~30 s of the sync round-trip | **F-007** (sync to chi-srv-01) + V0.27.4 US-315 (drive_summary metadata UPDATE) + US-317 (drive_summary regardless of Ollama) |
| server `realtime_data` got the `drive_id=11` rows | F-007 re-confirmation |
| server `drive_counter.last_drive_id` advanced to 11 (it was stuck at 3) | V0.27.4 US-315 / V0.27.3 US-314 watch-item |
| server `drive_statistics` has per-parameter rows for `drive_id=11` | **only if Sprint 32 US-324 (drive_statistics writer) has shipped+deployed by then** — otherwise expect 0 and note it as "US-324 pending" rather than a failure |

Server journal cross-check: `ssh chi-srv-01 'journalctl -u obd-server.service --since "<sync time>" | grep "FORENSIC ensureDriveSummary_entry"'` — should show `… drive_id=11 \| device=chi-eclipse-01 …` (server confirms it processed the drive's summary).

---

## Step 4 — calibration smoke (only if ≥ 5 real drives now exist)

`calibration` needs `MIN_REAL_DRIVES=5` with populated `drive_statistics` rows. Drive 11 alone won't be enough. Once enough real drives accumulate (and US-324's writer is producing `drive_statistics`), run on chi-srv-01:
```
cd /mnt/projects/O/OBD2v2 && DATABASE_URL=<from .env> python scripts/report.py --calibrate --device chi-eclipse-01
# then with --apply, then:
mysql -h 10.27.27.10 -u obd2 -p<pw> obd2db -e "SELECT * FROM baselines;"
```
Assert: it runs to completion (no `ModuleNotFoundError: pymysql` — US-320), and `baselines` gets rows. This is the V0.27.4 US-316 *intent* check, but it's downstream of US-324 + 5 drives, so it likely lands in a later validation pass, not Drive 11.

---

## Outcome → action

- **All Step 1-3 asserts green** → tell the PM: F-005 + F-007 ready for `/sprint-validated` on Sprints 28-30 (per the chain-end-merge rule, those updates accumulate and the chain merges together). Also a green light to run `/chain-validated` for the V0.27 chain (after confirming the aggregate's sprint.json/archive dedup is sane — see the chain-validate gap file).
- **Any Step 2-3 assert red** → file a gap, name the failing clause, do NOT merge the chain. The most likely failure mode is `drive_summary` still not writing on `drive_end` (i.e. US-310 didn't fully fix B-059) — that would be a real regression and a V0.27.7 bug-fix sprint.
- **`drive_check` lines present but `drive_state_transition` shows a duplicate/extra drive_id on a warm-restart-cranking sequence** → I-019 / US-311 not fully fixed; note it, it's a P2 not a chain-blocker.
