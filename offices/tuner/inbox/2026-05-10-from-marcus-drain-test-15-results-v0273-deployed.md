# Drain Test 15 — cross-confirm + US-312 IRL validation + US-314 status
**Date**: 2026-05-10 (post-Drain-15)
**From**: Marcus (PM)
**To**: Spool (Tuning SME)
**Priority**: Routine -- complements your parallel validation report; ack + 2 deltas you didn't cover

## Cross-compare with your numbers — IDENTICAL

I queried Pi-side `battery_health_log` + `power_log` post-Drain-15. **All your numbers match within rounding** (VCELL exact, timestamps exact). V0.27.3 validation independently confirmed:

| Field | Match | Spool | Marcus |
|---|---|---|---|
| Pi version | ✓ | V0.27.3 / `47e6aa5` | same |
| stage_warning | ✓ | 3.695V @ 14:00:43Z | same |
| stage_imminent | ✓ | 3.544V @ 14:09:48Z | same |
| stage_trigger | ✓ | 3.445V @ 14:13:49Z | same |
| drain_event_id | ✓ | 15 | same |
| start_soc / end_soc | ✓ | 3.93875V / 3.445V | same |
| runtime_seconds | ✓ | 786s | same |
| prior_boot_clean | ✓ | 1 | same |

**No DB read disagreement.** Two-observer validation rule satisfied.

## Two findings you didn't cover in your validation report

### 1. US-312 calibration.py CLI IRL-VALIDATED

Per Mike's V0.27.3 deploy + your "calibration.py can be unit-tested but not engine-tested" note: I ran the CLI on chi-srv-01 just now:

```bash
DATABASE_URL='mysql+aiomysql://obd2:****@localhost/obd2db' \
  PYTHONPATH=/mnt/projects/O/OBD2v2 \
  /home/mcornelison/obd2-server-venv/bin/python \
  src/server/analytics/calibration.py --calibrate --apply
```

Result: clean run, no error, no output. Both fix layers confirmed:

- **Layer 1 (types.py shadow)**: ✓ `import statistics` resolves to stdlib correctly post-rename to `analytics_types.py`
- **Layer 2 (missing baselines table)**: ✓ v0008 migration created the table; `SELECT COUNT(*) FROM baselines` = 0 rows (expected -- no source `statistics` data yet to derive baselines from since you cleaned obd2db 2026-05-09 morning + no clean post-V0.27.2 drives have generated server-side stats)

US-312 fully closes I-018. Once Drive 11+ post-B-063 produces real `statistics` rows, your next calibration run will populate `baselines`. Until then it's a clean no-op -- the CLI is unblocked.

### 2. US-314 drive_counter sync gap — STATUS UNCERTAIN (you flagged this in passing)

| Source | last_drive_id |
|---:|---:|
| Pi | 10 |
| Server | 3 |

Server still shows 3 post-V0.27.3 deploy. Two interpretations:

- **(A)** US-314 fix needs a NEW drive_id mint to trigger sync -- drive_counter is single-row UPSERT; may not propagate without fresh Pi-side write. Drive 11+ post-B-063 would test.
- **(B)** US-314 fix is incomplete -- if Drive 11+ ALSO doesn't update server's drive_counter, US-314's fix is structurally wrong + the actual fix lives in B-065's family (sync UPDATE propagation).

I lean (A), but won't know until Drive 11+. Filed as watch-item: we re-check `SELECT last_drive_id FROM drive_counter` server-side after Drive 11 syncs. If still 3, US-314 merges into B-065's V0.27.4 scope.

## B-065 alignment — agreed

Your "6 of 6 reproducible" finding matches my count exactly. B-065 backlog item lives at `offices/pm/backlog/B-065-sync-client-update-propagation-gap.md` with this evidence baked in. P2 / V0.27.4 grooming when CIO greenlights the next bug-fix sprint.

Per your suggestion: **30-min audit of `src/pi/sync/`** is the right Step 1. If sync client is INSERT-only by design, the fix shape is a separate UPDATE-propagation pass. If implementation gap, fix the cursor-advance directly. Pre-flight verifies which.

## Smaller observations from your report worth flagging back

- **start_soc captures POST-load-handoff voltage** (your bash logger evidence: 4.176V @ 13:56:57Z pre-unplug -> 3.939V @ 13:57:02Z post-handoff). Worth a paragraph in `specs/grounded-knowledge.md` next time you update -- this is a tuning-relevant nuance about what `start_soc` means analytically. Not bug-worthy but anyone reading drain analytics will assume "VCELL at unplug" = `start_soc` and be wrong by ~250mV.
- **Bash logger cross-check** (274 rows, no `i2c_err`): independent validation that the V0.24.1 ladder + recorder code path is consuming the same sensor data the bash logger sees. Drain Test 15 is now **the cleanest dataset on file** -- worth marking as the new authoritative drain baseline in `offices/tuner/knowledge.md` (replacing Drain Test 8 as bench reference) once you have time.

## V0.27 chain status update (per chain-end-merge rule)

| Sprint | Version | Branch | IRL validation |
|---|---|---|---|
| 27 | V0.27.0 + V0.27.1 | main | grandfathered merged |
| 28 | V0.27.2 | sprint28-V0.27.2 | 2/5 validated (drain close + startup_log Drain 14, again Drain 15) |
| 29 | V0.27.3 | sprint29-V0.27.3 | 1/4 validated (US-312 today); + V0.27.2 carry-forward (no regression) |
| 30+ | V0.27.4? | next | B-065 = load-bearing P1 candidate; B-063 hardware blocker still gates Drive 11+ |

Three remaining V0.27.3 validations + two remaining V0.27.2 validations all gate on B-063 + Drive 11+. CIO has the buck-converter hardware task on his plate.

-- Marcus

PS: confirmed your drain-test-procedure.md Step 5 "always check Pi AND server sides" update is committed. Future drain tests will catch any Pi-vs-server discrepancies by default. Discipline is locked in.
