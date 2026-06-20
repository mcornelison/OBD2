# I-024: drive_statistics writer does not exist in production code

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium (P2)               |
| Status       | Open (V0.27.6 candidate)  |
| Category     | analytics / writer gap    |
| Found In     | (no production code writes to drive_statistics; schema exists but writer missing) |
| Found By     | Spool 2026-05-11 audit    |
| Related      | I-021 (drive_summary writer Ollama-coupled); US-310 + US-315 don't own drive_statistics |
| Created      | 2026-05-11                |

## Description

Spool 2026-05-11 audit asked: "is anyone tracking 'drive_statistics writer fires on real drives'?" -- because `drive_statistics` table exists in schema, `proposeCalibration()` joins through it for baselines, but **no production code writes to drive_statistics**.

PM 2026-05-11 verified via `rg "INSERT INTO drive_statistics|drive_statistics.*INSERT|writeDriveStatistics"` across the codebase: **1 hit total, in a test file**. No production writer.

This means even with all of US-310 (drive_summary 12-field) + US-315 (sync UPDATE) + US-317 (Ollama-decouple) landing IRL, calibration via `scripts/report.py --calibrate` will **always** return "Need 5 more real drives" because `drive_statistics` table stays empty.

## Impact

`scripts/analytics/calibration.py` `proposeCalibration()` joins drive_statistics for per-parameter aggregates. Empty drive_statistics = empty `proposals` list = no baselines ever written = calibration workflow permanently inert.

This is the missing link between "drive completes successfully" and "calibration produces actionable baselines." Without it, the entire calibration/tuning analytics pipeline downstream of drive_summary is dead.

## Steps to Reproduce

```bash
ssh mcornelison@chi-srv-01 "mysql -uobd2 -p<PWD> obd2db -e 'SELECT COUNT(*) FROM drive_statistics;'"
# 0 (zero rows)

# Even after V0.27.4 + Drive 11+ produces drive_summary 12-field rows + US-315 syncs them
# drive_statistics will still be empty because no writer exists
```

## Expected Behavior

Drive completes -> drive_summary INSERT/UPDATE -> **drive_statistics INSERT** with per-parameter aggregates (mean / min / max / stddev for RPM, COOLANT_TEMP, SPEED, LTFT, STFT, etc. across the drive's realtime_data rows). One drive_statistics row per (drive_id, parameter_name) combination.

## Actual Behavior

drive_statistics table exists in schema but has no writer. Table stays empty regardless of drive activity.

## Resolution (V0.27.6 candidate)

Build the drive_statistics writer. Two implementation approaches (sprint grooming decides):

### Approach 1 — Server-side computed at sync-time

When sync arrives with new drive_summary row, server-side computes per-parameter aggregates from corresponding realtime_data rows + inserts drive_statistics rows. Pro: server has full data; aggregation is single-pass. Con: server-side compute load.

### Approach 2 — Pi-side computed at drive_end

When drive_end fires, Pi computes per-parameter aggregates from local realtime_data + inserts drive_statistics rows locally + sync propagates. Pro: distributed compute; Pi-side already has the data. Con: Pi resource cost during drive_end (latency-sensitive).

**Recommendation**: Approach 1 (server-side). Aligns with V0.27.3 US-310 pattern (server-side analytics writer for drive_summary). Pi stays lean.

## Acceptance Criteria

- [ ] Pre-flight audit: rg `drive_statistics|DriveStatistic` src/ -- map schema definition + downstream consumers (proposeCalibration, etc.)
- [ ] Writer triggered post-drive_summary INSERT (server-side) OR post-drive_end (Pi-side; sprint decides)
- [ ] Per-parameter aggregates computed: mean / min / max / stddev for at least the canonical PIDs (RPM, COOLANT_TEMP, SPEED, IAT, MAF, TPS, LTFT_1, STFT_1, TIMING_ADVANCE, BAT_V)
- [ ] One drive_statistics row per (drive_id, parameter_name) combination
- [ ] Integration test asserts: synthetic drive -> drive_end -> drive_statistics has N rows (where N = number of canonical PIDs); would FAIL pre-fix (writer doesn't exist)
- [ ] Real-world validation gate: post-V0.27.6 deploy + Drive 11+ produces drive_statistics rows on server

## Cross-references

- I-021 V0.27.4 US-317 (drive_summary Ollama-decouple; writer fires now)
- US-310 V0.27.3 (drive_summary 12-field writer; pattern reference for server-side aggregation)
- US-315 V0.27.4 (sync UPDATE for delta-tables; drive_statistics is in DELTA_SYNC_TABLES per sync_log.py audit)
- Spool's calibration dependency: `proposeCalibration()` joins drive_statistics -> empty drive_statistics = no proposals

## Source

`offices/pm/inbox/archive/2026-05/2026-05-11-from-spool-calibration-cli-pymysql-missing.md` Story E ("Question for Marcus" section)
