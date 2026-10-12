# Battery health: "can this pack carry a full at-home sync and a graceful shutdown?" — DESIGN

**Status:** APPROVED by the CIO 2026-10-02 (ARCH-065). **BUILT on `architect/ARCH-065a-battery-health-build`** (CIO-directed build by
Atlas; merges after Sprint 95 and the ARCH-064 set). `architecture.md` (Battery Health card / Battery Health Log) points here; this file
governs where they differ. §16 records the build-time rulings and supersedes §1–§15 where they differ. Owner: Atlas (keeper of `specs/`).
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
| **`drain_trigger`** ∈ `keyoff` · `monthly_test` · `calibration` (§15.1) | `battery_health_log` | NEW; supersedes `load_class` as the qualifying key |
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
- The reserve floor IS the existing `pi.powerWatch.drainFloorVolts` (3.6 V today) with the dwell (§15.3). Calibration (§7) re-sets its value.

## 6. Monthly test (11 min)
- **Due when:** an at-home key-off (the home state AT THE LOSS is in `AT_HOME_STATES`, `home_detector.py` — §16.14), and no completed `monthly_test` row for the CURRENT `cell_epoch` in the
  last **30 days**. A new pack's first at-home key-off runs one.
- **Behaviour:** a normal at-home shutdown, sync to completion included, but powerwatch holds power until **660 s after the cut**, then
  shuts down gracefully.
- **Window:** 60–660 s after the cut, so it includes the sync's own load (conservative; month-to-month noise from varied syncs accepted).
  `drain_rate_mv_s` = least-squares slope of `vcell_v` over the window.
- **Interrupted** (wall power returns early) → a `drain_trigger=monthly_test` row with `runtime_seconds` < 660: not counted (§15.2);
  retried next at-home key-off. **Reserve floor hit during the test** → verdict `replace` immediately.
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
- **Uncalibrated:** T = `window_end_s` + straight line from the window's end VCELL to the reserve floor (`pi.powerWatch.drainFloorVolts`,
  the ONE floor — §16.12), published with `provisional = true`. A straight line OVER-projects near empty, which is why it is labelled.
- **Typed unknowns (never a guessed green):** `no_monthly_test` (none for this `cell_epoch`), `monthly_test_stale` (> 45 days),
  `too_few_syncs` (< 3 at-home `DELIVERED` jobs), plus the existing `no_database` / `log_unreadable` / `clock_unreadable`. Obsolete:
  `no_qualifying_drains`, `too_few_drains`, `health_data_stale`. The renderer table `carousel.js#BATTERY_HEALTH_REASON_TEXT` and its guard
  test are updated in the same story.
- **Published:** `health`, `reasons`, `lastHealthCheckTs` (= the monthly test's time; the F-9 stale-green line stays), `timeToFloorS` (T),
  `jobAvgS` (J), `jobMaxS`, `provisional`. The verdict is also written onto the monthly-test row for server history.

## 9. Sudden failure: `cut_step_mv`
Recorded at EVERY key-off (home or away) and published as a 30-day trend. **No colour yet.** Its threshold is set from about a month of
epoch-3 key-offs (factor over the observed spread, with n and filters stated: `facts/README.md` rule 2a), not invented now.
Basis: 119 mV at ~2.55 W on 2026-09-27. ⚠️ **Two instruments:** the 2026-09-27 seed's step is (last wall reading − the reading at
cut + 1 s) from the witness log; live rows use (powerwatch's wall value, ≤ 15 s old at the loss − the collector's `start_vcell_v`).
Compare like with like when the threshold is set.

## 10. What changes where (blast radius)
- Pi: `power_watch/tasks/sync_with_server.py` (stops, outcomes, times) · the powerwatch controller (monthly hold, floor dwell) ·
  `power_watch/outcome.py` + `boot_progress.py` (sync times) · `battery_health_verdict.py` (replaced) · the battery-health emitter ·
  `power_db.py` (new columns, `cut_step_mv`) · `database_schema.py` (replay-safe ADD COLUMNs) · validator + config keys below.
- Server: ONE migration (v0035) for the new `battery_health_log` and `startup_log` columns; models. No `close_reason` change (§15.2). 🔴 **SERVER BEFORE PI, and PROBE before
  the Pi:** a Pi ahead of the server makes every `battery_health_log` DELTA push FAIL (the delta path refuses unknown columns ⇒
  `tablesFailed > 0` ⇒ every at-home sync ends `AT_HOME_SERVER_DOWN`), and the `startup_log` SNAPSHOT path drops the new columns
  silently and forever. Gate: v0035 applied AND its columns probed on the server, then the Pi.
- UI: the reason-text table (§8) and the tile detail (T, J).
- Config (powerwatch behaviour only, §15.9): `pi.batteryHealth.monthlyIntervalDays 30`, `pi.homeNetwork.joinWaitSec 120`,
  `pi.homeNetwork.stallSec 60`, `pi.powerWatch.drainFloorDwellReads 5`. The test timings (60 / 600 / 660 s) live ONLY in
  `src/pi/power/battery_capacity.py` (§16.1); verdict constants in `battery_health_verdict.py`.
- Specs: `architecture.md` §Battery Health card (~:5978) and §Battery Health Log (~:1432) become POINTERS to this file;
  `shutdown-orchestration-design.md` §Tier 2 (the ceiling text, incl. my 4bce3aa9 JOINING line) is updated to the completion rule.

## 11. Validation (human actions ⇒ `bigDefinitionOfDone`, never story ACs)
1. The calibration drain on epoch 3 → `T_cal`, cutoff, floor recorded; verdict loses `provisional`.
2. An at-home key-off after a long drive → sync ends `DELIVERED` past 60 s, times recorded, graceful poweroff. (`DELIVERED` needs the
   backlog to read exactly 0; if shutdown-time writes keep it above 0 the sync ends `STALLED` — this item is the instrument for that.)
**Expected card sequence after deploy (not failures):** `no monthly battery test yet` → after the 09-27 seed: `too few home syncs to
judge · last health check 2026-09-27` → after 3 DELIVERED at-home syncs with times: `GOOD … (provisional)`.
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

## 15. Amendments (2026-10-02, from reading the code at Sprint 95 `4bce3aa9`; CIO-ratified the same day)
These supersede any text above that differs.
1. The column is **`drain_trigger`**, not `trigger` (`TRIGGER` is an SQL keyword). Default `keyoff`.
2. **No `close_reason` widening.** A `monthly_test` row with `runtime_seconds` < 660 is "interrupted" and not counted. (Widening the
   Pi CHECK would need a table rebuild; SQLite cannot alter a CHECK.)
3. The reserve floor is the EXISTING `pi.powerWatch.drainFloorVolts` plus `pi.powerWatch.drainFloorDwellReads` (5). Not a second floor.
4. The 60–660 s window is timed from the drain row's `start_timestamp` (the cut). The trajectory begins at the confirmation read,
   ~`smoothingSec` after the cut.
5. Stall = the backlog did not FALL for 60 s, re-read after every attempt. `runSync` can return having pushed nothing.
6. `battery_health_log` also gains `cell_epoch`, `window_start_s`, `window_end_s`, `drain_rate_mv_s`, `verdict`.
7. `cut_step_mv` = powerwatch's last on-wall VCELL minus the drain row's `start_vcell_v`. *(Superseded in mechanism by §16.3: no new
   I2C read; the value comes from the existing 5 s UPS poll and is snapshotted once at the loss.)*
8. Calibration and the 2026-09-27 seed are computed from the **1 Hz witness log** by `tools/power/drain_calibration.py`; powerwatch,
   which writes the trajectory, is stopped during a calibration drain.
9. Verdict constants live in code; config only for powerwatch behaviour (§10).
10. ~~The current pack = the `cell_epoch` of the newest `battery_health_log` row.~~ *(Superseded by §16.12: the pack is
    `resolveCellEpoch(config)`.)* Calibration results are stored in `t_floor_s`, `floor_vcell_v`, `cutoff_vcell_v`.

Implementation plan: `Z:/O/OBD2v3/offices/architect/reports/2026-10-02-PLAN-ARCH-065-battery-health.md`.

## 16. As built (ARCH-065a, 2026-10-03) — rulings made during the build
Each was reviewed; the full ledger is in the build's SDD workspace. CIO directive during the build: **"always use a SSOT approach"** —
every value has one owner and every consumer imports or reads it.
1. **One owner for the test timings:** `src/pi/power/battery_capacity.py` — `WINDOW_SKIP_S = 60`, `WINDOW_S = 600`,
   `TEST_HOLD_S = 660`. No `testHoldSec` config key. Imported by the hold task, the boot finaliser, the verdict and the calibration tool.
2. **One pack-ID resolver:** `resolveCellEpoch(config)` (`battery_health.py`); `pi.power.cellEpoch`, else `unknown`.
3. **No new I2C read for the cut step.** The wall VCELL cache is fed by powerwatch's EXISTING ~5 s UPS poll (`recordHistorySample`),
   only when the PLD reads power present AFTER the read; a value older than 15 s at the loss is dropped. **It is snapshotted ONCE at the
   loss** (`HomeStateAtLoss.observe()`), and every record reads that snapshot. The PLD trigger thread does GPIO only (an I2C read there
   could delay loss detection 7–11 s through `I2cClient` retries).
4. **One owner for the loss time:** `HomeStateAtLoss` stamps it (monotonic + wall) once per loss; the outcome record carries `loss_at`,
   landed as `startup_log.prior_boot_loss_at`.
5. **The boot finaliser targets the loss's own row:** the newest `battery_health_log` row with `start_timestamp` in
   [`loss_at` − 5 s, `loss_at` + 30 s], OPEN OR CLOSED (after a hard cut the row is still open at boot; the reaper runs after `arm`).
   No `loss_at` ⇒ no-op.
6. **"A counted monthly test" ≡ `drain_rate_mv_s IS NOT NULL`** — one definition for the due check, the verdict and the history write.
   The rate is stamped when the trajectory covers cut+60..cut+660 s with ≥ 480 points spanning ≥ 480 s (independent of closure).
7. **The monthly-test mark is scoped to this loss** (open rows with `start_timestamp ≥ loss_at − 5 s`), attempted before AND after the hold
   (the collector opens its row up to ~2 s late); a mark failure never skips the hold.
8. **Reserve floor ⇒ `replace` (spec §6, broadened):** an AT-HOME drain (monthly test or ordinary key-off) that the reserve floor ended is
   stamped `verdict = 'replace'` by the finaliser; it outranks an older counted test. AWAY / UNKNOWN home states are not stamped.
9. **Sync to completion:** the backlog is re-read after every attempt; with no backlog reader at all, a clean `runSync` counts as delivered
   (production always passes one — pinned by an AST test). A late sync record after `RESERVE_FLOOR` is dropped for that loss.
10. **Verdict output:** `provisional` is a boolean field (reasons only explain `unknown`); a negative T is published as 0; unusable test
    data ⇒ `unknown` / `log_unreadable` with the test's date; the history write uses a ≤ 500 ms busy timeout and runs only when the value
    changes; jobs are ordered by `startup_log` rowid (a dead RTC can mis-order timestamps).
11. **Calibration must END ON BATTERY** (a restored log is refused); a PLD flap inside cut..cut+660 s is refused in both modes; a restore
    after the window is fine for a monthly-test seed. The 2026-09-27 log seeds epoch 3's first monthly test (rate −0.065 mV/s, runtime
    8169 s, cut step 118.8 mV) and cannot serve as the calibration (power was restored).
12. **One current pack, one reserve floor (final review, SSOT):** the verdict's pack is `resolveCellEpoch(config)` — the same resolver the
    writers and the due check use (a new pack reads `no_monthly_test` until its own first test). The provisional T projects to
    `pi.powerWatch.drainFloorVolts` — the floor the sequencer actually stops at; the 3.44 V figure and its extra reserve are gone
    (reference: end 4.07 V, rate −0.04 mV/s, floor 3.6 V, window end 660 s ⇒ T = 12 410 s).
13. **One owner of "this loss's drain row":** `lossRowBand(lossAt)` (`battery_health.py`), [loss − 5 s, loss + 30 s], used by the finaliser
    and the monthly-test mark (the mark adds "still open").
14. **One owner of "at home":** `AT_HOME_STATES` / `AT_HOME_STATE_NAMES` (`home_detector.py`); the hold is gated on the home state at the
    loss (not on a sync outcome), and the finaliser's floor rule uses the same set.
15. **Cancelled losses:** `HomeStateAtLoss` carries a loss GENERATION; the sync and the hold capture it at their start, and a record from an
    older generation is dropped. Known residuals (follow-up): a stale pipeline whose hold STARTS during the next loss can label that loss's
    row if it too is cancelled (never rated); a stale sync in the JOINING poll can take the next loss's at-loss state handoff.
16. **CIO ruling 2026-10-03 (I4):** a reserve-floor `replace` stands until the regular monthly test — no early re-test (*"at replacement time
    I should have new batteries"*; a new pack is a new `cell_epoch` with its own first test).
