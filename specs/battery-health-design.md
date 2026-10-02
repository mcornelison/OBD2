# Battery health: "can this pack carry a full at-home sync and a graceful shutdown?" — DESIGN

**Status:** APPROVED by the CIO 2026-10-02 (ARCH-065). **DESIGN, NOT YET BUILT** -- until it is, the as-built verdict is the one
described in `architecture.md` (Battery Health card / Battery Health Log), which point here. Owner: Atlas (keeper of `specs/`).
Evidence (fleet share, `Z:/O/OBD2v3/offices/architect/`):
`findings/2026-10-02-RESULTS-battery-health-window-length-60s-and-120s-are-not-honest-600s-is.md`,
`findings/2026-10-02-RESULTS-power_log-VCELL-was-the-deleted-ladder-and-the-health-verdict-has-no-reachable-input.md`;
drain data `evidence/2026-09-27-epoch3-power-tests/`.

## 1. Purpose
The CIO's question, and the only one this verdict answers: **after I shut the car off at home, does the battery have plenty of power
to finish a full data sync and then shut down gracefully?** Green = yes with margin; yellow = barely; red = no ⇒ replace the batteries.

It replaces the current verdict (`battery_health_verdict.py`), which has had **no reachable input since 2026-05-18**. Its qualifying
drains (`production`, ≥ 60 s, ending ≤ 3.50 V) were produced only by the power-down ladder deleted in `9adb0fbf`.

## 2. CIO rulings (2026-10-02) this design rests on
1. The at-home shutdown sync runs **to completion**. Stops: delivered · stalled 60 s · reserve floor. **No absolute time cap.**
2. WiFi-rejoin wait bounded at **120 s**.
3. Monthly test: **11 min** (skip 60 s, measure 600 s), **once a month**, at an at-home key-off.
4. Reserve floor = **10 minutes** of runtime left, on the calibration curve.
5. **The 2026-09-27 drain counts as epoch 3's first monthly test.** Next due ~2026-10-27.
6. Approach **A** (the Pi computes the verdict). Option B (server-side) filed to backlog via Marcus.
7. Short away key-off within ~3 min of leaving home may wait up to 120 s (stale scan cache): **accepted, leave as is.**

## 3. Definitions
- **J, job time:** confirm wait (`smoothingSec`, 7 s) + shutdown-sync duration + graceful shutdown (~4 s), **averaged over the last 10
  at-home shutdowns whose sync ended `DELIVERED`.** The longest of those 10 is published beside it (`jobMaxS`), not used.
- **T, battery time:** time from key-off, freshly charged, to the **reserve floor**. That is when the sync is stopped (§5), so it is the
  real limit on the job.
- **Thresholds:** `good` (green) if T ≥ 1.2·J · `degraded` (yellow) if J ≤ T < 1.2·J · `replace` (red) if T < J.
  (The card's existing `health` vocabulary; the colours are unchanged.)

## 4. Capture (per key-off; Pi SQLite, delta-synced to the server)
| what | where | status |
|---|---|---|
| VCELL at 1 Hz, cut → poweroff, tagged `cell_epoch` | `drain_vcell_trajectory` (US-790) | EXISTS on `dev` (not yet on the car) |
| start/end VCELL, runtime, one row per key-off | `battery_health_log` | EXISTS |
| **sync start / end (UTC)** | shutdown outcome record → `startup_log.prior_boot_sync_started_at/_ended_at` | NEW (rides the US-776-f path) |
| **`cut_step_mv`** = last VCELL on wall − VCELL 1 s after the cut | `battery_health_log` | NEW |
| **`trigger`** ∈ `keyoff` · `monthly_test` · `calibration` | `battery_health_log` | NEW; supersedes `load_class` as the qualifying key |
| **`drain_rate_mv_s`**, `window_start_s`, `window_end_s`, `verdict` | `battery_health_log` (monthly-test rows) | NEW |
Not captured, deliberately: per-second watts (CPU cost; the monthly test runs the same shed load); the gauge's SOC % (unreliable on this chip).

## 5. At-home shutdown sync runs to completion (changes Sprint 95's `SyncWithServerTask`)
- Unchanged: AWAY skips at once; UNKNOWN drains; the 7 s confirm, the dashboard shed, the graceful poweroff.
- **Removed:** the 60 s `shutdownSyncCeilingSec` as a stop.
- **Stops at the FIRST of:** (1) backlog 0 → `DELIVERED`; (2) no batch accepted for **60 s**, clock starting **at WiFi association**
  → `STALLED` (new outcome); (3) VCELL below the **reserve floor** for **≥ 5 consecutive 1 Hz reads** (threshold + dwell:
  `design-patterns.md` §1; the cutover step must not trip it) → `RESERVE_FLOOR` (new outcome).
- **AT_HOME_JOINING** waits up to **120 s** for association (one rejoin measured: ~49 s, drive 96, n = 1); else `AT_HOME_JOINING_TIMEOUT`.
- Every ending writes its reason and the sync start/end times. All end in the graceful poweroff.
- Known edge (§2.7): the JOINING read uses NetworkManager's CACHED scan list (`nmcli … --rescan no`). Entries age out after roughly 3 min
  (RECALLED). A key-off within ~3 min of leaving home can wait ≤ 120 s; the 2 s re-read ends the wait when the entry expires.
- Until calibrated (§7), the floor = the current configured VCELL floor.

## 6. Monthly test (11 min)
- **Due when:** an at-home key-off (state resolves `AT_HOME_*`), and no completed `monthly_test` row for the CURRENT `cell_epoch` in the
  last **30 days**. A new pack's first at-home key-off runs one.
- **Behaviour:** a normal at-home shutdown, sync to completion included, but powerwatch holds power until **660 s after the cut**, then
  shuts down gracefully.
- **Window:** 60–660 s after the cut, so it includes the sync's own load (conservative; month-to-month noise from varied syncs accepted).
  `drain_rate_mv_s` = least-squares slope of `vcell_v` over the window.
- **Interrupted** (wall power returns early) → row `trigger=monthly_test`, `close_reason=interrupted`, not counted; retried next at-home
  key-off. **Reserve floor hit during the test** → verdict `replace` immediately.
- Measured basis (2026-09-27, epoch 3, 2.55 W): a 600 s window is within ±50 % of the 30-min rate 86 % of the time, never "no drain";
  60/120 s windows are within ±50 % only 16/12 % of the time and show NO drain 36/37 % of the time.
- **Seed:** the 2026-09-27 drain is landed once as epoch 3's first `monthly_test` row, ON THE PI (its own id space), `data_source='real'`,
  `notes` = provenance (`offices/architect/evidence/2026-09-27-epoch3-power-tests/` (fleet share), powerwatch stopped, dashboard NOT shed ⇒ heavier than a real key-off:
  a conservative baseline). Its window values come from the 1 Hz trace.

## 7. Calibration drain (once per pack; first one OWED for epoch 3)
- **Purpose:** this pack's VCELL-vs-time curve to dropout and its cutoff voltage. It gives T its SHAPE and sets the reserve floor.
- **Procedure (CIO-operated, as 2026-09-27):** at home, after the sync delivered; powerwatch stopped; normal shed load; 1 Hz logging
  until the pack drops out. Ends in **one deliberate hard cut**, with data already on the server.
- **Cell safety:** dropout was ~3.4 V on the old pouch (UNMEASURED on this pack). Li-ion damage begins well below that (RECALLED; check the
  cell datasheet before running).
- **Outputs, stored as a `calibration` row + its trajectory:** `T_cal` (cut → floor), the cutoff voltage, the floor voltage = the VCELL with
  **10 min** left on this curve, and `rate_cal_mv_s` over the same 60–660 s window.
- **Why the 09-27 drain cannot serve:** it stopped at 3.82 V / 62 %. No cutoff, no knee.

## 8. The verdict (computed on the Pi at boot; published to `states/battery-health`)
- **T = T_cal × (rate_cal / rate_month)**: shape from the calibration, scale from the latest monthly test of the same `cell_epoch`.
  Assumes ageing compresses the curve in time (stated assumption; revisit if a later calibration contradicts it).
- **Uncalibrated:** T = straight line from the window's end VCELL to **3.44 V** (provisional) minus the 10-min reserve,
  `reasons.health = provisional_uncalibrated`. A straight line OVER-projects near empty, which is why it is labelled.
- **Typed unknowns (never a guessed green):** `no_monthly_test` (none for this `cell_epoch`), `monthly_test_stale` (> 45 days),
  `too_few_syncs` (< 3 at-home `DELIVERED` jobs), plus the existing `no_database` / `log_unreadable` / `clock_unreadable`. Obsolete:
  `no_qualifying_drains`, `too_few_drains`, `health_data_stale`. The renderer table `carousel.js#BATTERY_HEALTH_REASON_TEXT` and its guard
  test are updated in the same story.
- **Published:** `health`, `reasons`, `lastHealthCheckTs` (= the monthly test's time; the F-9 stale-green line stays), `timeToFloorS` (T),
  `jobAvgS` (J), `jobMaxS`, `provisional`. The verdict is also written onto the monthly-test row for server history.

## 9. Sudden failure: `cut_step_mv`
Recorded at EVERY key-off (home or away) and published as a 30-day trend. **No colour yet.** Its threshold is set from about a month of
epoch-3 key-offs (factor over the observed spread, with n and filters stated: `facts/README.md` rule 2a), not invented now.
Basis: 119 mV at ~2.55 W on 2026-09-27.

## 10. What changes where (blast radius)
- Pi: `power_watch/tasks/sync_with_server.py` (stops, outcomes, times) · the powerwatch controller (monthly hold, floor dwell) ·
  `power_watch/outcome.py` + `boot_progress.py` (sync times) · `battery_health_verdict.py` (replaced) · the battery-health emitter ·
  `power_db.py` (new columns, `cut_step_mv`) · `database_schema.py` (replay-safe ADD COLUMNs) · validator + config keys below.
- Server: a migration for the new `battery_health_log` and `startup_log` columns; models; and **widening v0032's `close_reason`
  CHECK to admit `interrupted`** (§6), on both tiers. **SERVER BEFORE PI** (snapshot sync drops
  unknown columns silently: the v0034 lesson).
- UI: the reason-text table (§8) and the tile detail (T, J).
- Config (`pi.batteryHealth.*`): `monthlyIntervalDays 30`, `testHoldSec 660`, `windowSkipSec 60`, `windowSec 600`, `staleDays 45`,
  `jobAvgCount 10`, `minJobs 3`, `greenMargin 1.2`, `reserveMinutes 10`, `provisionalCutoffV 3.44`; `pi.homeNetwork.joinWaitSec 120`,
  `stallSec 60`, `floorDwellReads 5`.
- Specs: `architecture.md` §Battery Health card (~:5978) and §Battery Health Log (~:1432) become POINTERS to this file;
  `shutdown-orchestration-design.md` §Tier 2 (the ceiling text, incl. my 4bce3aa9 JOINING line) is updated to the completion rule.

## 11. Validation (human actions ⇒ `bigDefinitionOfDone`, never story ACs)
1. The calibration drain on epoch 3 → `T_cal`, cutoff, floor recorded; verdict loses `provisional`.
2. An at-home key-off after a long drive → sync ends `DELIVERED` past 60 s, times recorded, graceful poweroff.
3. The first scheduled monthly test (~2026-10-27) → a counted row with a rate, and a verdict.
4. An away key-off → AWAY, poweroff within ~12 s, `cut_step_mv` recorded.
Unit tests use the 2026-09-27 trace as the fixture (skip, slope, projection); every threshold boundary; and each new guard
**shown to FAIL when deliberately broken** (`design-patterns.md` §6).

## 12. Out of scope
Server-side verdict (option B, backlog) · watts logging · SOC-based health · a `cut_step_mv` threshold (after data) · any time cap on the sync.

## 13. Cannot show / open
- Whether ageing compresses the curve proportionally (§8 assumption).
- This pack's cutoff and knee (until §7).
- The 120 s rejoin bound rests on one measurement (n = 1).

## 14. Suggested story split (sizing is Marcus's)
(1) capture: columns, `cut_step_mv`, sync times, migration · (2) sync-to-completion stops in `SyncWithServerTask` · (3) monthly hold in
powerwatch · (4) the verdict + emitter + reason table · (5) the 09-27 seed row · (6) a calibration-analysis tool (trace → `T_cal`, cutoff,
floor). (5) and (6) are Atlas-buildable at CIO direction.
