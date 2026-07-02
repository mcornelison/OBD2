# BL-015: US-422 cannot complete -- the orchestrator drain-event recording path was removed (SS-T5), and battery_health_log has no SoC%-pct column for the value to survive US-423's column drop

| Field        | Value                                                                                     |
|--------------|-------------------------------------------------------------------------------------------|
| Status       | **OPEN** -- routed to Atlas (architecture + data-contract decision) per PM Rule 10         |
| Priority     | Medium (P2 -- blocks US-422 + its dependent US-423; sprint NOT blocked, US-424/425 remain) |
| Filed By     | Rex (Ralph Agent 1), Sprint 51 Session (V0.29.5)                                           |
| Filed Date   | 2026-07-01                                                                                 |
| Sprint       | Sprint 51 / V0.29.5                                                                        |
| Affects      | US-422 (wire UpsMonitor SoC% -> recorder -> battery_health_log), US-423 (deps US-422)      |
| Related      | BL-013 (US-309 recorder seam, Step 1), B-060 (this = the deferred "Step 2"), US-234, US-289 |
| Refusal Rule | Rule 1 (Refuse First -- ambiguity is a blocker); precedent US-421/BL-014 this same sprint  |

## TL;DR

US-422 is groomed as "wire `UpsMonitor.getBatteryPercentage()` **through the orchestrator** to the recorder so start/end SoC% land in `battery_health_log`." A pre-flight audit shows the story's premise no longer matches the code, and completing it as written requires **three separate unratified decisions** that belong to Atlas, not the implementer:

1. **The named recording path does not exist anymore.** BL-013 (2026-05-09) cited `src/pi/power/orchestrator.py` (`PowerDownOrchestrator`) as the sole production caller that opened a drain at WARNING and closed it at TRIGGER. That file was **deleted** in the SS-T5 redesign (2026-05-19). The current shutdown path is `ShutdownSequencer` (`src/pi/power/power_watch/controller.py`), which runs an abstract `runPipelineFn`. The V1 task list ships **exactly one** task -- `SyncWithServerTask` (`src/pi/power/power_watch/__main__.py:136-149`). **There is no drain-event recording anywhere in `src/`** (grep for `startDrainEvent`/`endDrainEvent` -> only tests + `scripts/record_drain_test.py`). The `batteryHealthRecorder` constructed in `lifecycle.py` and passed into `hardware_manager` (`src/pi/hardware/hardware_manager.py:182-183, 233-234`) is a **dead reference** -- stored, never called.

2. **There is no column for the SoC% to survive into.** `battery_health_log` has **no** `soc_pct` column. The only existing SoC%-write seam (BL-013 Step 1, `battery_health.py:378/432-434/458/531-536`) puts SoC% into the *legacy* `start_soc`/`end_soc` columns. But **US-423 (which explicitly depends on US-422) drops `start_soc`/`end_soc`** -- and its AC says consumers migrate to "`start_vcell_v`/`end_vcell_v` **(+ the US-422 SoC%)**", treating the SoC% as a field that *survives* the drop. That is only coherent if US-422 adds **new dedicated `start_soc_pct`/`end_soc_pct` columns on both tiers** (Pi SQLite rebuild-migration + server MariaDB `ALTER TABLE ADD COLUMN` + models.py + sync mapping). Using the existing `startSocPct->start_soc` seam is self-defeating: US-423 would delete the SoC% the very next story.

3. **Recording register SoC% at drain time reintroduces the exact hazard US-234 removed.** US-234 (Sprint 19) deliberately moved the shutdown ladder OFF SoC% and ONTO VCELL because the MAX17048 ModelGauge mis-reads SoC by 30-40 points for the first ~3 minutes after a cold power-up (documented in `ups_monitor.getBatteryPercentage` docstring; called out in BL-013 §2). A drain event that opens in that cold-start window records a calibration-garbage SoC% that a "0-100 range" acceptance check will happily pass. Whether/how to guard the calibration window is a design decision, not an implementation detail.

Refusing per Rule 1 before any code change, exactly as US-421 refused into BL-014 this sprint (a story that named an SSOT provider that did not exist).

## Evidence (read-only audit; no production code touched)

### Finding 1 -- the orchestrator drain-event path is gone

- `src/pi/power/` contains **no** `orchestrator.py` (BL-013 §Category-A cited `orchestrator.py:862/893/917/933` -- all deleted).
- Current shutdown owner: `ShutdownSequencer` (`src/pi/power/power_watch/controller.py`). Its `handleOnBattery()` fires on a confirmed power-LOST signal and runs `runPipelineFn` once, then powers off. It has **no** drain-event recorder reference and **no** WARNING/TRIGGER open/close split -- only `grace -> flushing -> powering_off`, all inside a single ~10s window.
- The V1 task registry is the single edit point and returns `[syncTask]` only: `src/pi/power/power_watch/__main__.py:136-149` (`buildV1Tasks`).
- `grep -rn "startDrainEvent\|endDrainEvent" src/` -> **0 callers** (only the definitions in `battery_health.py`).
- `hardware_manager` stores `self._batteryHealthRecorder` (`src/pi/hardware/hardware_manager.py:233`) but **never** calls it.
- Implication: "the orchestrator" the story wants to wire SoC% "through" either (a) must be **rebuilt** (a new drain-event open/close task inside the sequencer pipeline -- but a drain that opens AND closes inside the ~10s poweroff window records `runtime_seconds ~= 10`, not the real battery-backed drain, so the semantic no longer maps), or (b) the story actually means the **bench-drill CLI** `scripts/record_drain_test.py` (which the validation criteria "run a UPS-drain bench drill" points at). These are different scopes with different correctness contracts. The implementer must not pick unilaterally.

### Finding 2 -- the bench-drill CLI does not read the register today

`scripts/record_drain_test.py:306-316` opens+closes the row from **operator-typed** `--start-soc`/`--end-soc`, passed as `startSoc=`/`endSoc=` (the **voltage** slot), and never touches `UpsMonitor`. So even the bench path currently records operator input into `start_vcell_v`/`start_soc`, not register SoC%. Making it read `getBatteryPercentage()` is a behavior change to a CIO-facing tool + still needs a surviving column (Finding 3).

### Finding 3 -- no dedicated SoC%-pct column; US-423 drops the only one currently used

- Schema (`src/pi/power/battery_health.py`, `SCHEMA_BATTERY_HEALTH_LOG`): columns are `start_soc`/`end_soc` (US-289-DEPRECATED, hold VCELL volts), `start_vcell_v`/`end_vcell_v`, `runtime_seconds`, `ambient_temp_c`, `load_class`, `notes`, `data_source`. **No `*_soc_pct`.**
- BL-013 seam writes SoC% into `start_soc`/`end_soc` (`battery_health.py:432-434`, `531-536`).
- US-423 AC (this sprint): "removes start_soc/end_soc ... consumers migrated to start_vcell_v/end_vcell_v **(+ the US-422 SoC%)**". For the US-422 SoC% to exist after US-423, US-422 must land it in a **new** column, on **both** Pi + server, with a sync mapping -- an unratified data-contract change (server tier is normally out of a single Pi wiring story's scope).

## What Atlas / PM need to decide

1. **Recording path** -- pick one and make it authoritative:
   - **(A) Bench-drill only (recommended, matches the validation criteria).** US-422 = `record_drain_test.py` optionally reads `UpsMonitor.getBatteryPercentage()` at open/close (fallback to operator `--start-soc-pct` when hardware absent / cold-start window), writing the new dedicated pct column. No orchestrator rebuild. Smallest correct scope; honors "run a UPS-drain bench drill" verbatim.
   - **(B) Rebuild an auto drain-event path** inside the sequencer pipeline (a new `RecordDrainEventTask`). Larger; must define the open/close semantic given the sequencer has no WARNING/TRIGGER split (a ~10s in-window drain is not a real drain). This is arguably its own feature, not an M story.

2. **Schema / data contract** -- confirm US-422 adds dedicated `start_soc_pct`/`end_soc_pct` (Pi SQLite rebuild-migration + server MariaDB `ADD COLUMN` + `models.py` + sync mapping), so US-423's `start_soc`/`end_soc` drop does not delete the SoC%. If instead the intent is to keep SoC% in `start_soc`/`end_soc`, then US-423 must be re-scoped (it currently drops them). One of the two stories has to change.

3. **Calibration-window guard** -- ratify whether a cold-start SoC% (first ~N minutes / until NTP-of-fuel-gauge stabilizes) is recorded verbatim, flagged, or suppressed (echoing US-234's rationale). This is the honest-instrument decision.

## Recommendation (Rex)

**Option A + dedicated pct columns + a cold-start flag.** It matches the validation criteria ("bench drill"), avoids rebuilding a removed subsystem with an ill-fitting semantic, and lands the SoC% in a column that survives US-423. Concretely, once ratified, US-422 becomes an M-sized story:

- add `start_soc_pct`/`end_soc_pct` (Pi migration mirroring `ensureBatteryHealthLogVcellColumns` + server `ADD COLUMN` + models + sync map);
- have `record_drain_test.py` read `getBatteryPercentage()` (with an operator-override + cold-start guard) and pass it to a new recorder kwarg that writes the pct column (NOT the soon-dropped `start_soc`);
- US-423 then drops `start_soc`/`end_soc` cleanly, leaving `start_vcell_v`/`end_vcell_v` + the new pct columns.

## Impact on the sprint

- **US-422 -> blocked** (this file). **US-423 -> blocked** (deps US-422).
- **Sprint NOT blocked:** US-424 (foreign-vehicle marker, L, Atlas-ruled pmSignOff present) and US-425 (doc-sync) remain pickable. Ralph continues to US-424.

## Decision needed

- [ ] Atlas: rule on recording path (A vs B) + the dedicated-pct-column data contract + the cold-start guard.
- [ ] PM: re-scope US-422 (and reconcile US-423's column-drop) per the ruling; add `scope.filesToTouch` (bench CLI + battery_health recorder + Pi/server schema + sync mapping + tests) so the next implementer has a fenced scope.
