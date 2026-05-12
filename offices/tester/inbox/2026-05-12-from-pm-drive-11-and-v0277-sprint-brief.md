# From: Marcus (PM) -- 2026-05-12
# To: Tester / QA
# Subject: Drive 11 result + V0.27.7 sprint groomed

## TL;DR

**Drive 11 happened (post-B-063 fuse-box install).** First clean car-coupled drive of the V0.27 chain. **Pi-side capture green; server-side analytics tier broken at every layer.** V0.27.7 sprint groomed on `sprint/sprint33-bugfixes-V0.27.7` with 5 stories to close the gaps. Awaiting `/sprint-deploy-pm` -> Ralph -> Drive 12 for re-validation.

## Drive 11 forensic summary

| Tier | Result | Evidence |
|---|---|---|
| Pi capture (realtime_data) | **PASS** | 10,839 rows / 470 rows/min during drive window |
| Pi drive_summary writer (Pi-side 6-col schema) | **PASS** | Row exists Pi-side with all Pi fields populated |
| Pi -> server sync (drive_summary row arrival) | **PASS** | Server row id=15, source_id=11 |
| Server-side drive_summary analytics fields (cols 3-8) | **FAIL** | `drive_id`, `start_time`, `end_time`, `duration_seconds`, `row_count`, `is_real` ALL NULL |
| Server-side drive_statistics (per-PID aggregates) | **FAIL** | 0 rows for Drive 11; Pi-side table missing entirely |
| Server-side drive_counter | **FAIL** | Still `last_drive_id=3` (Pi at 11) -- 8-drive gap |
| Pi startup_log post-Drain-17 boot | **REGRESSION** | `prior_boot_clean` field empty (V0.27.4/5 had `=1`) |
| US-323 backfill script for stranded battery_health_log rows 11-15 | **NEVER RAN** | Rows still NULL server-side |

**What this means for the regression manifest**: F-005 still REGRESSED (drive_summary insert on drive_end -- Pi-side works, server-side analytics tier doesn't). F-007 (sync Pi -> server) PARTIAL -- mechanism works for delta tables (battery_health_log via US-315 IRL evidence on drain_event 16 + 17), drive_summary delta still broken.

## V0.27.7 sprint (5 stories)

Branch: `sprint/sprint33-bugfixes-V0.27.7` (commit `0599d24`). Combines Spool's Drive 11 findings (Stories X/Y/Z/W) + my PM finding (I-030 startup_log regression).

| ID | Size | Pri | Closes | Theme |
|---|---|---|---|---|
| US-326 | M | P1 | I-026 | drive_summary server-side analytics NULL (Hypothesis A/B pre-flight) |
| US-327 | M | P1 | I-027 | US-323 backfill wired into deploy-server.sh idempotent |
| US-328 | **L (pmSignOff)** | P1 | I-028 | drive_statistics Pi migration + writer architecture decision |
| US-329 | S | P3 | I-029 | drive_counter compute-from-drive_summary (Option 2) |
| US-330 | S | P2 | I-030 | startup_log prior_boot_clean regression on V0.27.6 |

**Deferred to V0.28+ feature sprint**: B-074 MAP PID (Spool's boost-pressure-for-knock-correlation ask). V0.27.X = bug-fixes only per standing rule.

## What you can validate now (pre-V0.27.7 deploy)

- Pi-side Drive 11 capture: connect to `chi-eclipse-01` -> `sqlite3 /var/lib/eclipse-obd/obd_data.db "SELECT COUNT(*), MAX(timestamp), MIN(timestamp) FROM realtime_data WHERE drive_id=11"` should return ~10,839 rows / 2026-05-12 ~01:10-01:35Z window
- Server-side gap reproduction: `mysql -h 10.27.27.10 -u <user> obd2db -e "SELECT * FROM drive_summary WHERE source_id=11\\G"` -> expect all analytics fields NULL (this is the Spec 3 bug I-026 captures)
- Drain 17 boot regression: query `startup_log` ORDER BY recorded_at DESC LIMIT 5 -> most recent row has empty `prior_boot_clean` (regression cliff at V0.27.6)
- US-323 backfill gap: `mysql ... "SELECT id, source_id, end_timestamp FROM battery_health_log WHERE id BETWEEN 14 AND 20"` -> rows 14/15 (source 14/15) still NULL; row 18 (source 17, drain 17) populated via US-315 forward path

## What you can validate after V0.27.7 deploy + Drive 12

- US-326 PASS: server drive_summary row for drive 12 has `start_time`/`end_time`/`duration_seconds`/`row_count`/`is_real=1` within 30s of drive_end
- US-327 PASS: server battery_health_log rows 11-15 have `end_timestamp`/`end_soc`/`runtime_seconds` populated; deploy idempotent (re-run = no-op)
- US-328 PASS: Pi-side has `drive_statistics` table; per-parameter rows present for Drive 12 for canonical PIDs (RPM/COOLANT_TEMP/IAT/MAF/TPS/LTFT/STFT/TIMING_ADVANCE/BAT_V); server-side rows populated per chosen architecture
- US-329 PASS: server `drive_counter` returns `last_drive_id=12` (auto-computed)
- US-330 PASS: post-Drain-18 boot writes `startup_log` row with `prior_boot_clean=1` + `prior_last_entry_ts` populated

## What I need from you (no urgency)

- Refresh the Drive 11 validation checklist (`test-reports/2026-05-11-drive-11-validation-checklist.md`) with the actual results -- the checklist was pre-Drive-11; now we have ground truth
- If you spot anything I missed in the 5 stories during your forensic-pull, drop a finding into `findings/` or push directly to PM inbox; I want to bake any V0.27.7 scope additions before Ralph picks it up
- After V0.27.7 ships + Drive 12 happens, the chain may finally clear for `/chain-validated` -- you'll be the gate on that

## Open questions for you to noodle on (no answer required now)

- Should drive_summary side of US-315 be in the same `IN_SCOPE_TABLES` mechanism as battery_health_log, or does drive_summary need a different update channel? Ralph pre-flight will identify; your read on architectural consistency would be valuable
- For US-328 architecture: Approach 1 (server computes from synced realtime_data) vs Approach 2 (Pi computes at drive_end + syncs the per-parameter rows). I'm leaning Approach 2 (matches Spool's spec frame + symmetric with drive_summary) but open to your read
- Anything else you saw on Drive 11 that I haven't captured? You have a better feel for the end-to-end picture than I do

Marcus
