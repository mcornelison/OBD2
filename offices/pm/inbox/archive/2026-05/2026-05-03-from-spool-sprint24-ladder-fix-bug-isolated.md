# Sprint 24 Spec — Ladder Fix (Bug Fully Isolated by Drain Test 8)
**Date**: 2026-05-03
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — P0 fix candidate

## TL;DR

**The 7-drain mystery is solved.** Drain Test 8 (this morning, 08:50–09:08 CDT) ran with full Sprint 23 instrumentation. The data identifies the bug definitively: **`PowerDownOrchestrator.tick()` reads power source from a stale/decoupled view of state. UpsMonitor correctly detects BATTERY transition, but the orchestrator never sees it. Result: every tick bails at the first guard, `_enterStage` is never called, ladder never fires, Pi dies at the buck-converter dropout knee.**

This is **NOT** a threshold bug. **NOT** a write-path bug. **NOT** a thread-startup bug. **NOT** a Pi5 brownout. It's a state-propagation bug between two components.

## Drain Test 8 Forensic Summary

| Metric | Value |
|---|---|
| Power-pull | 2026-05-03 08:50:22 CDT (UpsMonitor logged transition correctly) |
| Pi death | 2026-05-03 09:07:51 CDT (hard crash, no graceful shutdown) |
| Runtime on battery | 17 min 29 sec |
| Starting VCELL | 3.91V (95% SOC — fully charged, much better than Drain 7's 3.57V start) |
| Ending VCELL | 3.39V (61% SOC reported by chip; chip calibration still suspect) |
| CSV rows | 178 (header + 177 data, 5-sec cadence) |
| `throttled_hex` | `0x0` for ENTIRE drain (Pi5 brownout DISPROVEN, again) |
| Tick health-check pulses | tickCount monotonically incremented 12/min throughout drain (thread alive) |
| **`_logTickDecision` reasons logged** | **214 ticks, 100% with `reason=power_source!=BATTERY`** |
| **`_enterStage` log lines** | **0 (zero)** |
| **`STAGE_*` rows in `power_log`** | **0 (zero)** |
| Last tick before death | `vcell=3.393 currentStage=normal willTransition=False reason=power_source!=BATTERY` |
| Forensic CSV path on Pi | `/var/log/eclipse-obd/drain-forensics-20260503T135023Z.csv` |
| Tick journal: filter | `journalctl -b -1 -u eclipse-obd \| grep _logTickDecision` |

## Hypothesis Comparison Across All 8 Drains

| Hypothesis | Status After Drain 8 | Evidence |
|---|---|---|
| **H1** Tick thread never started | **REJECTED** (Drain 7) | Sprint 23 health-check log shows tickCount incrementing every 60s on battery |
| **H2** Tick runs but gating logic bails silently | **CONFIRMED — and located** (Drain 8) | All 214 tick decisions logged `reason=power_source!=BATTERY`. UpsMonitor's view: BATTERY. Orchestrator's view: not-BATTERY. State decoupled. |
| **H3** Stages advance, write path drops rows | **UNTESTABLE** (until H2 fixed) | Write path was never reached — `_enterStage` never called |
| **H4** Pi5 SoC brownout under load (CIO hypothesis) | **REJECTED** (Drains 7 + 8) | `throttled_hex=0x0` for 17 min on battery, CPU 38–40°C, load 0.06–0.42, Pi5 was happy until buck converter quit |

The death mode is now well-characterized: Pi dies at VCELL ~3.30V because the UPS HAT's 5V buck converter loses regulation at the LiPo dropout knee. This is **expected hardware behavior**. The ladder's job is to gracefully shut down BEFORE that point. The ladder's job has been broken for 8 drain tests because of a single state-propagation bug.

## Where The Bug Lives (audit hints for Ralph)

In `src/pi/power/orchestrator.py::PowerDownOrchestrator.tick()`, the very first guard check is reading `power_source` from somewhere that is NOT being updated when UpsMonitor detects the transition. Likely culprits:

1. **Cached state at orchestrator init** — `self._powerSource` set once, never refreshed
2. **Different UpsMonitor instance** — orchestrator was given a reference to a different (or stale) UpsMonitor object than the one running the polling loop
3. **No callback subscription** — UpsMonitor's source-change event isn't propagating to the orchestrator
4. **Direct chip read with stale logic** — orchestrator does its own MAX17048 read but the source-determination logic is broken or stale (note: VCELL itself read fine — `vcell=3.393` in last log, accurate; only `power_source` is bogus)

Most likely suspect: **(1) or (3).** UpsMonitor's `_pollingLoop` logged the transition at 08:50:22, so its own state changed. Yet the orchestrator never saw it. Either the orchestrator never queries UpsMonitor's live state on each tick, or UpsMonitor doesn't notify the orchestrator.

## Sprint 24 Recommended Stories

### Story 1 (M, P0) — The Actual Ladder Fix
**File:** `src/pi/power/orchestrator.py::PowerDownOrchestrator.tick()` + likely also `src/pi/hardware/ups_monitor.py` and the orchestrator init/wiring path

**Behavior:** make `tick()`'s view of `power_source` consistent with UpsMonitor's live view. Three viable approaches; Ralph to choose based on existing architecture:

- **Option A (cleanest):** UpsMonitor exposes a `getPowerSource()` method that returns the current cached source from its own polling loop. Orchestrator calls it fresh on every tick.
- **Option B (event-driven):** UpsMonitor invokes a registered callback on every source change. Orchestrator registers itself as a callback and updates its own `self._powerSource` on each transition.
- **Option C (shared state object):** A single `PowerState` object holds source/vcell/soc; both UpsMonitor (writer) and orchestrator (reader) hold the same reference.

**Test discipline:**
- Unit test: orchestrator sees BATTERY within 5 sec of UpsMonitor detecting it (SimulatedUpsMonitor with controllable state)
- Unit test: orchestrator's tick() advances stages when VCELL crosses thresholds while on battery
- Integration test: a synthetic "drain test" harness that simulates a VCELL decline curve and asserts STAGE_WARNING → STAGE_IMMINENT → STAGE_TRIGGER rows in `power_log` plus `subprocess.run(systemctl, poweroff)` invocation
- The integration test must FAIL before the fix and PASS after — direct continuation of the methodology pattern from `specs/methodology.md` "Integration Tests for Runtime-Verifiable Bugs" (Sprint 21 US-256)

**Acceptance:** Drain Test 9 (live-drill, CIO action) shows STAGE_WARNING / STAGE_IMMINENT / STAGE_TRIGGER rows in `power_log` with timestamps matching VCELL threshold crossings, plus a clean shutdown record in `journalctl --list-boots`.

### Story 2 (S, P0) — Carry Forward: Orchestrator State File Writer
**File:** `src/pi/power/orchestrator.py`

**Status:** Sprint 23's Story 2 (US-275 or wherever) was supposed to wire this. Drain Test 8's CSV shows `pd_stage=unknown` and `pd_tick_count=-1` on **all 177 data rows** — the orchestrator is not writing `/var/run/eclipse-obd/orchestrator-state.json`. Either it didn't ship in Sprint 23 or it's broken.

**Behavior:** every tick, write the JSON state file as I specified previously (atomic rename, fields: tickCount, currentStage, lastTickTimestamp, lastVcellRead, powerSource).

**Why it matters:** the forensic logger remains half-blind without this. We diagnose using both CSV columns AND the journalctl tick log lines today; only one of two channels is delivering full value.

### Story 3 (S) — Stale-State Guard Pattern (TD)
**File:** new TD doc; reference in `specs/anti-patterns.md`

**Behavior:** Document this bug class as a project anti-pattern. Any cross-component state shared by reference (especially `power_source`, `currentStage`, sensor readings) must have one of:
- Freshness contract (TTL on the cached value with a "must refresh if older than X" rule)
- Explicit pull semantics (the consumer always calls a getter on the producer, never reads cached fields directly)
- Push-with-acknowledgment (the producer fires a callback, the consumer acks; missed acks raise an alarm)

**Why:** this exact pattern probably exists elsewhere in the codebase. We just got bit by it 8 times in production-equivalent testing. Anti-pattern doc prevents the next one.

### Story 4 (S) — Spool Hardware Spec Doc (carry from Sprint 23)
**File:** `offices/tuner/knowledge/ups_hat_dropout_characteristics.md`

**Behavior:** I write this. Document empirically-confirmed UPS HAT dropout knee (~3.30V VCELL), 17.5-min runtime under typical load (Pi5 idle, BT scan, HDMI, 0.06-0.42 load avg, 38-40°C). Cite Drain Tests 7 + 8 CSVs. Reference for car-wiring scope (US-169 / US-189 / US-190).

### Carryforward Audit (Marcus)

Sprint 22 candidates that may or may not have shipped — please confirm before close:
- TD-042 (release schema theme-field break, 24 test failures)
- TD-044 (test_migration_0005 v0006 break)
- Phantom-path drift fix in sprint.json template-generator
- US-265 boot-reason detector (Sprint 22 Story 2) — `startup_log` table exists in SQLite but schema differs from spec (no `id` column). Audit needed.

## Personal Note

This drain-test sequence has been one of the cleanest examples of TDD-on-hardware I've watched on this project. Sprint 21 fixed thread-startup. Sprint 22 added forensic logging. Sprint 23 added tick-internal instrumentation. Each sprint eliminated a hypothesis from the search space. By Drain 8 we had the answer — not a guess, a measurement. **Do not let this sprint be the one where Ralph fixes-and-prays.** The fix should be small (one file, maybe two), but the test discipline (unit + integration that fails-then-passes) is what makes this Sprint 24 instead of Sprint 25.

## Sources / Forensic Artifacts

- Drain 8 CSV: `/var/log/eclipse-obd/drain-forensics-20260503T135023Z.csv` on Pi (177 data rows + header)
- Drain 8 journalctl tick decisions: `journalctl -b -1 -u eclipse-obd | grep _logTickDecision` (214 entries, all `reason=power_source!=BATTERY`)
- Drain 8 power_log: id=351, single `battery_power` row at 13:50:22Z, no STAGE_* rows
- Drain 7 CSV: `drain7-forensics.csv` on CIO's Windows box
- 8 consecutive drain tests (1-5 pre-instrumentation, 6 post-US-252, 7 with forensic logger, 8 with full Sprint 23 instrumentation)
- Buck converter dropout characteristic: VCELL ~3.30V → 5V rail collapse → kernel halt with no logs

---

I'm available for follow-up on the fix design (Options A/B/C in Story 1) and for post-Drain-9 verdict reading. After Sprint 24 ships and Drain 9 passes, this should be the closeout of the drain-fire saga.
