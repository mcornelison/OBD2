From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 4 complete (one pass, per the ruling). Design-gate requested.**

Your A1+B1+C+D ruling implemented as specified, no improvisation, no scope drift.

## Task #
**Task 4** — Retire `UpsMonitor.getPowerSource` from the source path; UI fed by
the `PowerSourceProvider` SSOT via a dedicated transition-detecting bridge.

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`b729a5c`** (11 files,
+498/-1565 — the negative delta is the retired source-decision machinery):

**Code (3 files, in-scope):**
- `src/pi/hardware/ups_monitor.py` — A1 surgery: `getPowerSource` def → loud
  `NotImplementedError` tripwire; `_isVcellSustainedBelowThreshold` /
  `_computeVcellSlopeVoltsPerMinute` / `_isVcellDecisiveAboveThreshold` /
  `_cachedSource` / `_lastPowerSource` removed; `_pollingLoop` source-decision
  + transition + `onPowerSourceChange` firing removed; `getTelemetry`'s
  `'powerSource'` key removed; US-279 `registerSourceChangeCallback` /
  `_invokeSourceChangeCallbacks` / `_sourceChangeCallbacks` removed.
  VCELL/SOC + `recordHistorySample` retained (battery-health intact).
- `src/pi/obdii/orchestrator/lifecycle.py` — `_PowerSourceUiBridge` class (B1:
  transition-detecting adapter, dedicated daemon thread); new
  `_subscribePowerMonitorToPowerSourceProvider` method replaces
  `_subscribePowerMonitorToUpsMonitor`; caller updated;
  `_getPowerSourceClosure` (UpdateApplier consumer) repointed to provider
  (Ruling C); `_shutdownPowerSourceUiBridge` added, called before
  `_shutdownPowerMonitor` (producer-before-sink).
- `src/common/config/validator.py` — `pi.powerWatch.uiPollSec=2` (B1 cadence,
  validated positive-bound; zero magic numbers).

**Tests (4 files in-scope, "their tests"):**
- `tests/pi/orchestrator/test_lifecycle_power_source_ssot.py` (NEW) — Ruling-D
  behavioural test (fake provider, present→lost→present, sink receives
  transitions); plan Step 1 static SSOT inspect guard; bridge-no-raise-out.
- `tests/pi/orchestrator/test_lifecycle_power_monitor.py` — class refactor:
  replaced 6 retired-UpsMonitor-fan-out tests with 3 SSOT wiring tests
  (constructs provider+bridge / idempotent / skip-when-no-PowerMonitor).
- `tests/pi/hardware/test_ups_monitor_degradation.py` — removed the retired
  `test_powerSourceChange_callbackInvokedOnVcellDropUnderLoad`; updated
  `test_getTelemetry_returnsAllExpectedKeys` to drop the `powerSource` key.
- `tests/test_config_validator.py` — new `uiPollSec` default+reject test.

**Deleted (retired-with-feature, 3 files):**
- `tests/pi/hardware/test_ups_monitor_battery_detection.py`
- `tests/pi/hardware/test_ups_monitor_battery_detection_recovery.py`
- `tests/pi/hardware/test_ups_monitor_power_source.py`

**TD filed (Ruling C):**
- `offices/pm/tech_debt/TD-054-shutdown-handler-dead-source-reaction.md` —
  tracked-not-silently-dead. ShutdownHandler.py NOT touched (out of scope).

## Pre-registered gate criteria — evidence

**#1 — TDD red→green (with exact commands + PASS):**
- `pi.powerWatch.uiPollSec` config (T4.B): RED `KeyError: 'uiPollSec'` → GREEN
  `pytest tests/test_config_validator.py -k powerWatch` → **5 passed** (was 4).
- B1 bridge (T4.C): RED `ImportError: cannot import name '_PowerSourceUiBridge'`
  → GREEN `pytest tests/pi/orchestrator/test_lifecycle_power_source_ssot.py`
  → **3 passed** (criterion-D transition + plan-step-1 inspect + no-raise).
- A1 surgery (T4.D): degradation suite GREEN
  `pytest tests/pi/hardware/test_ups_monitor_degradation.py` → **19 passed**
  (UpsMonitor polling thread starts + records VCELL history source-free —
  battery-health intact).

**#2 — `grep -rn "getPowerSource" src/` shows NO power-source caller:**
```
$ rg -n "\.getPowerSource\(" src/
(no output — zero call sites)

$ rg -n "getPowerSource" src/
src/common/config/validator.py:177:    # 2026-05-18 bricking-loop HOTFIX. UpsMonitor.getPowerSource() is a
src/pi/power/power_source_provider.py:8:#                      sequencer = smoothed). UpsMonitor.getPowerSource() (the
src/pi/hardware/ups_monitor.py:137:    source = monitor.getPowerSource()                  # VCELL-trend + CRATE
src/pi/hardware/ups_monitor.py:304:    `UpsMonitor.getPowerSource()`.
```
**All remaining hits are comments/docstrings (historical context); ZERO call
sites.** The `def getPowerSource()` is retained as the tripwire (criterion #2:
"raises NotImplementedError ... no callers, not no-definition"). `getVcell` /
`getBatteryVoltage` / `getBatteryPercentage` / `getChargeRatePercentPerHour` /
`recordHistorySample` intact.

**#3 — UI power-source flows from PowerSourceProvider (test, not inspection):**
- Ruling-D behavioural test `test_powerSourceUiBridge_feedsCheckPowerStatusFromProviderOnTransitions`
  drives fake provider present→lost→present; asserts sink (PowerMonitor's
  `checkPowerStatus`) receives `[True, False, True]`, sourced from the provider.
  PASS.
- Static SSOT inspect guard `test_lifecycle_subscribeMethod_doesNotReferenceGetPowerSource`
  asserts NO `.getPowerSource(` call site in `_subscribePowerMonitorToPowerSourceProvider`
  AND `PowerSourceProvider` referenced. PASS.

**#4 — No-broken-intermediate:**
- `pytest tests/pi/hardware/ tests/pi/power/ tests/pi/orchestrator/ tests/test_config_validator.py -m "not slow"`
  → **360 passed, 4 skipped, 0 failed** in ~3 min.
- `pytest tests/pi/power/power_watch/ -m "not slow"` → **21 passed** (T2 alias
  not touched; powerwatch path stays green across T2→T5 window).
- `python validate_config.py` → **exit 0**.
- `python -m ruff check` on the 7 touched files → **All checks passed!**

**#5 — Scope fence:** the 11 files in `b729a5c` are exactly: ups_monitor.py +
lifecycle.py + validator.py + their tests + the new TD. `shutdown_handler.py`
NOT touched (Ruling C → TD-054 instead). `power_watch/` controller/__main__ NOT
touched (T5).

**Additional grep — Ruling C US-279 gate (recorded for the trail):**
```
$ rg -n "registerSourceChangeCallback" src/
src/pi/hardware/ups_monitor.py:42:#  ...
src/pi/hardware/ups_monitor.py:64:#  ...
src/pi/hardware/ups_monitor.py:739:# (``registerSourceChangeCallback`` ...
src/pi/obdii/orchestrator/lifecycle.py:181:#  ...
```
All comments. **ZERO callers in src/** — gate satisfied pre-removal AND post-removal.

## Design invariants preserved
- **SSOT integrity:** one acquisition site (`PowerSourceProvider.isExternalPowerPresent()`); the tripwire makes any reintroduction of the heuristic source path fail loudly at the call site.
- **No mock-theatre:** Ruling-D test exercises real bridge `pollOnce`; criterion-#3 proven by behavior, not inspection.
- **Zero magic numbers:** `uiPollSec` is validated config.
- **5 s smoothing in V1:** untouched.
- **Out-of-scope honored:** `shutdown_handler.py` untouched + TD-054 filed; controller/`__main__.py` (T5) untouched; T2 confirm* alias intact (powerwatch suite still 21+).

## Cross-module-identity gotcha (flagged, not improvised)
The orchestrator test's initial `isinstance` check failed under the broader-suite run because `lifecycle.py` is reachable as both `pi.obdii.orchestrator.lifecycle` and `src.pi.obdii.orchestrator.lifecycle` (sys.path includes both) — two `_PowerSourceUiBridge` class objects, isinstance across paths fails ([[feedback-cross-module-enum-identity]]). Resolved by switching to a duck-typed shape check (`hasattr start/stop/pollOnce`); flagged here per Task-2 lesson (surfaced before submission, not at it).

## Out-of-scope stale comments — NOT touched (flagged for follow-up cleanup)
- `src/pi/obdii/orchestrator/core.py:209/453` — comments still reference the old `_subscribePowerMonitorToUpsMonitor` method name. core.py is out of T4 scope; comments don't break the code. Suggest a 1-line cleanup later.
- `tests/pi/power/test_power_monitor_db_write.py:112` — docstring reference to old method name; comment-only.

## Gate request
Per the per-task discipline I **STOP here** and await your gate before Task 5
(PowerWatch → ShutdownSequencer; trigger = provider + smoothing). All criteria
met by construction with evidence cited above. — Ralph
