# I-026: drive_summary server-side analytics fields stay NULL for Drive 11 (sync UPDATE not firing for drive_summary side)

| Field | Value |
|---|---|
| Severity | High (P1) |
| Status | Open (V0.27.7 candidate -- Spool Story X) |
| Category | sync / analytics |
| Found In | server-side `_ensureDriveSummary` OR sync UPDATE handler |
| Found By | PM + Spool 2026-05-12 Drive 11 validation |
| Related | V0.27.4 US-315 (fix landed for battery_health_log; drive_summary side broken); V0.27.4 US-317 (Ollama-decouple) |
| Created | 2026-05-12 |

## Description

Drive 11 captured cleanly Pi-side (10,839 realtime_data rows, drive_summary populated with 6 Pi-side fields). Pi-sync pushed the row to server (server row id=15, source_id=11 exists). **But server-side analytics fields (Spec 3 fields 3-8) are ALL NULL.**

```sql
-- server-side drive_summary row 15:
id=15, source_id=11
drive_id=NULL, start_time=NULL, end_time=NULL, duration_seconds=NULL
row_count=0, is_real=0
data_source='real', ambient_temp_at_start_c=18, starting_battery_v=14.5
```

V0.27.4 US-317 supposedly decoupled `_ensureDriveSummary` from Ollama. V0.27.4 US-315 added sync UPDATE propagation for `supports_update_sync=True` tables (drive_summary is in that set per FORENSIC log evidence). But analytics fields still empty.

## Two hypotheses (Ralph pre-flight identifies)

**Hypothesis A (Spool's framing)**: US-315 sync UPDATE fix was extended to battery_health_log but **NOT** to drive_summary delta path. Same INSERT-only pattern as original B-065. Server-side handler INSERTs first time, ignores subsequent UPDATEs.

**Hypothesis B (PM framing)**: Server-side `_ensureDriveSummary` not firing for Drive 11. Either (a) the trigger (`enqueueAutoAnalysisForSync` -> `_writeDriveAnalytics`) isn't invoked, (b) it fires but Drive 11's row has some state that short-circuits it (NULL guard? start_time NULL?), or (c) V0.27.6 US-324's `_writeDriveAnalytics` wrapper introduced a regression.

Pre-flight: check server-side journalctl for `_ensureDriveSummary` log lines around Drive 11's sync arrival (2026-05-12 01:10-01:35Z). If log lines present, Hypothesis A. If absent, Hypothesis B.

## Impact

Calibration pipeline permanently inert until this fixes:
- `proposeCalibration()` joins `drive_summary` × `drive_statistics`
- `drive_summary.is_real=0` + `start_time=NULL` -> excluded from JOIN
- 0 baselines ever written

Plus all downstream analytics (Spool grading, AI analysis, dashboard drives view).

## Acceptance Criteria

- [ ] Pre-flight audit: server journalctl `_ensureDriveSummary|_writeDriveAnalytics` around Drive 11 sync window (2026-05-12 01:10-01:35Z); identify Hypothesis A vs B
- [ ] After fix: new drive end + sync round-trip -> server-side drive_summary row has `start_time` + `end_time` + `duration_seconds` + `row_count` + `is_real=1` + `data_source` populated within 30s
- [ ] Drives 11 + historical (3/4/5) backfill: either covered by this story OR explicitly punted (handle via Story Y / I-027 if separate)
- [ ] Integration test: synthetic Pi capture -> sync -> assert server-side analytics fields populated; would FAIL pre-fix

## Source

- Spool 2026-05-12 Drive 11 validation note (Story X)
- PM 2026-05-12 server-side query showing drive_summary row 15 analytics fields NULL
- Cross-reference: B-065 + I-021 + V0.27.4 US-315 + V0.27.4 US-317 + V0.27.6 US-324
