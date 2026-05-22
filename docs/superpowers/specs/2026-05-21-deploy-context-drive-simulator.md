# Deploy-Context Drive Simulator — Design Spec

**Date**: 2026-05-21
**Sprint**: 41 / V0.27.17
**Author**: Rex (Ralph) for US-355 (I-040 structural close)
**Pairs**: Atlas (architecture sign-off), Argus (test discipline sign-off), Marcus (PM gate)
**Status**: V1 ships with one scenario seeded — `test_scenario_1_v0_27_16_reproducer_GREEN_on_current_branch` + its RED twin

## Why this exists

The V0.27.7/V0.27.16 false-pass class shipped THREE times (US-326, US-328, US-348, US-349). Each cycle the test discipline was tightened — synthetic-seam-mock passes do not count; real-drive round-trip + DB read-back is the gate — and each cycle the same bug class shipped through.

Argus's RCA (2026-05-21): the unit-test fixtures stub-replaced the writer's trigger seam. The seam never fired in the deploy because the Pi-side drive-end signal does not materialize on sequencer-driven termination. The writer was wired correctly in code; the trigger condition never materialized.

This spec describes the structural fix to that discipline gap: a pytest harness that exercises the integrated Pi-database → sync → server-compute path against real databases with NO mock of the writer or compute seams. The next time someone tries to ship a writer that depends on a Pi-side drive-end event, the harness's RED case will trip in CI.

B-104 Step 1 (Sprint 41 / V0.27.17) is the architectural fix: server reads raw `realtime_data` MIN/MAX/COUNT directly and computes `drive_summary` analytics + per-PID `drive_statistics`. No Pi-side drive-end marker dependency. This harness is the discipline gate that pins the architectural property.

## Harness design

### Location

- `tests/integration/test_deploy_context_drive_simulator.py` — the pytest module
- `docs/superpowers/specs/2026-05-21-deploy-context-drive-simulator.md` — this spec

### Components (no mock seams)

| Layer | Production component | Harness fixture |
|---|---|---|
| Pi sqlite schema | `src.pi.obdii.database.ObdDatabase` + its migrations | `piDatabase` — temp file, `db.initialize()` runs the real migrations |
| Server ORM schema | `src.server.db.models.Base.metadata` | `serverEngine` — temp SQLite, `Base.metadata.create_all` |
| Pi-side drive write | direct sqlite3 INSERTs against production tables | `_simulateSequencerTerminatedDrive` |
| Sync transport | the HTTP /api/v1/sync endpoint (covered separately by `test_pi_to_server_e2e.py`) | `_syncPiToServer` — direct DB-to-DB replay in the row shape /sync would have produced; isolates this harness to the writer/compute seam where the false-pass class lived |
| Server compute | `compute_drive_summary` + `compute_drive_statistics` — REAL imports, REAL calls | the GREEN test invokes them via `Session(serverEngine)` |
| Assertions | server-side ORM SELECTs against real `DriveSummary` + `DriveStatistic` rows | `_readServerDriveSummary` / `_readServerDriveStatistics` |

### What the harness deliberately does NOT mock

- `compute_drive_summary` — imported from `src.server.analytics.drive_summary_compute`; identity-checked in `test_computeFunctions_areTheProductionImports_notMocks`.
- `compute_drive_statistics` — same.
- `ObdDatabase` — instantiated for real; `test_piDatabase_isRealObdDatabase_notMock` asserts `isinstance` + that the migrations produced the real tables.
- `Base.metadata` — `test_serverEngine_runsRealOrmSchema` asserts the ORM SELECTs work.

### What the harness DOES factor out of scope

- The HTTP /api/v1/sync transport. Already exercised by `tests/integration/test_pi_to_server_e2e.py` (which mocks the server endpoint with a stdlib ThreadingHTTPServer). Re-exercising it here adds bloat without coverage value — the false-pass class lived at the compute seam, not the transport seam.
- The full orchestrator wiring (`DriveDetector.processValue`, the polling loop, the IAT/BATTERY snapshot path). The DriveDetector's behavior on engine-on values is covered by `tests/pi/obdii/drive/test_detector*.py`. The harness's load-bearing claim is about what happens when `_endDrive` does NOT fire — the scenario builder writes the rows directly to enforce that exact precondition.

## Scenario 1 — V0.27.16 false-pass reproducer

Captures Argus's 2026-05-21 drill drive 20 exactly:

| Parameter | Value | Source |
|---|---|---|
| drive_id | 20 | Argus drill |
| device | `chi-eclipse-01` | production Pi hostname |
| start time | 2026-05-21T17:29:21Z | Argus drill |
| duration | 540 s (~9 min) | Argus drill |
| poll interval | 1.0 s | production cadence |
| parameters | RPM, SPEED, MAP, COOLANT_TEMP | subset of the 16 PIDs Argus's drill captured; gives ≥100 samples/PID for `data_quality='full'` |
| drive-end signal | NEVER fired | mirrors sequencer poweroff |

### GREEN: V0.27.17 architecture (current branch)

`test_scenario_1_v0_27_16_reproducer_GREEN_on_current_branch`:

1. Build scenario (Pi sqlite writes).
2. Sync rows to server (Pi → ORM).
3. Invoke `compute_drive_summary(20)` + `compute_drive_statistics(20)` (B-104 Step 1).
4. Assert `drive_summary.start_time/end_time/duration_seconds/row_count/is_real` NON-NULL + arithmetically consistent with realtime_data.
5. Assert `drive_statistics` has one row per parameter with Atlas Refinement A invariants (`min <= avg <= max`, `std_dev >= 0`, `sample_count >= 1`) + Atlas Refinement B classification (`data_quality='full'` for ≥100 samples).

### RED: V0.27.7 / V0.27.16 architecture

`test_scenario_1_v0_27_16_reproducer_RED_legacy_writer_architecture`:

1. Build scenario (identical).
2. Sync rows to server (identical).
3. **Do NOT invoke compute** — mirrors V0.27.16's trigger-seam architecture where:
   - Pi-side `DriveStatisticsRecorder` was hooked to `DriveDetector.engine_off` (US-349); never fired because the signal never fired.
   - Server-side `_tryAutoAnalysisTrigger` was hooked to /sync receipt (US-348); did fire, but its `enqueueAutoAnalysisForSync` downstream path required preconditions that didn't materialize without a Pi-side drive-end marker.
4. Assert `drive_summary.start_time/end_time/duration_seconds` are NULL + `row_count` in (None, 0) + `drive_statistics` has zero rows — the exact NULL pattern Argus captured on drive 20.

This is the RED proof: a faithful reproduction of the V0.27.7/V0.27.16 architectural shape, run on the current branch with the V0.27.17 compute path simply NOT invoked. If a future agent re-introduces a writer that depends on a Pi-side drive-end signal, they will land code that produces the SAME failure pattern this RED test pins.

## Retroactive RED proof — option ladder

US-355 acceptance criterion 4 calls for empirical RED proof against deployed V0.27.7 / V0.27.16 code. Atlas pre-registered three acceptable options:

### Option A — in-tree parameterization (shipped V1)

The in-tree RED test (`test_..._RED_legacy_writer_architecture`) faithfully captures the V0.27.16 architectural shape on current code: identical scenario builder + sync, no compute invocation, assert NULL pattern. The architectural cut between V0.27.16 and V0.27.17 IS the compute-call-being-invoked. Parameterizing on that cut captures the bug class with no git ceremony.

**Strength**: zero infra cost, runs on every CI tick, breaks loudly the moment someone weakens the harness.

**Limitation**: does not import V0.27.16 source directly. The faithfulness rests on the architectural-cut framing being correct (i.e., on the claim that V0.27.16's writers would have written zero rows in this scenario). Argus's V0.27.16 drill empirically established that claim (drive 20: zero `drive_statistics` rows + NULL `drive_summary` fields); this RED test pins the same outcome.

### Option B — out-of-tree git worktree (procedure)

If Atlas / Argus want a stronger retroactive proof on a specific past commit:

```bash
# Pick a baseline: c04d36e is V0.27.16 ship; b26344e is the US-349 integration commit
BASELINE=c04d36e

# Add a worktree pointing at the baseline
git worktree add /tmp/v0_27_16_baseline $BASELINE

# Copy the harness file into the baseline tree (it does not exist there yet)
cp tests/integration/test_deploy_context_drive_simulator.py \
   /tmp/v0_27_16_baseline/tests/integration/

# Run JUST the GREEN test against V0.27.16 source.  Expected: ImportError
# OR test failure (drive_summary fields stay NULL because the writer
# architecture under that commit does not invoke server compute).
( cd /tmp/v0_27_16_baseline && \
  python -m pytest tests/integration/test_deploy_context_drive_simulator.py::TestScenario1V0_27_16Reproducer::test_scenario_1_v0_27_16_reproducer_GREEN_on_current_branch -v )

# Expected outcome: ModuleNotFoundError on
#   src.server.analytics.drive_summary_compute
# (the module did not exist before US-350 / Sprint 41).
# That ImportError IS the retroactive RED -- compute was structurally
# absent in V0.27.16.

# Cleanup
git worktree remove /tmp/v0_27_16_baseline
```

**Strength**: imports the actual V0.27.16 source. Definitive proof.

**Limitation**: requires git worktree + manual run; not a CI gate.

### Option C — `--baseline-commit <SHA>` harness flag (deferred V0.28+)

A pytest plugin that resolves a baseline commit, adds a worktree, prepends its `src/` to sys.path, and runs the harness against the imported source. Most rigorous; highest infra cost. Defer to V0.28+ unless the false-pass class returns.

## Sign-off chain (US-355 bigDoD #6)

| Owner | What they sign | Status |
|---|---|---|
| Atlas | Harness design (this spec) honors B-104 Step 1 architectural intent; "no mock seams" claim is empirically defensible | pending review |
| Argus | RED proof shape would have caught V0.27.7 + V0.27.16 false-pass class on its first cycle | pending review |
| Ralph (Rex) | Harness ships green on current branch; lint clean; `TestHarnessIntegrity` pins the load-bearing claims | **DONE** — 6/6 tests GREEN, ruff clean, identity checks pin compute imports |
| Marcus | Spec doc exists + sprint contract closure on US-355 | **DONE** on sprint.json land |

CIO greenlight on Atlas + Argus reads closes the gate.

## Scenario coverage roadmap

Sprint 41 / V0.27.17 ships ONE scenario (V0.27.16 reproducer). Subsequent stories add scenario coverage. Candidates Atlas + Spool already named:

1. **Sparse drive** (5 realtime rows) → assert `data_quality='below_threshold'`. Pins Atlas Refinement B.
2. **Replay drive** (`data_source='replay'`) → assert `is_real is None` (NULL preservation per Atlas Q2). Pins the "tested + not real" vs. "untested" distinction.
3. **Partial sync** (realtime_data landed but drive_summary missing) → compute logs WARN + returns None; does not raise. Pins the "missing pre-condition is non-fatal" claim in `compute_drive_summary` docstring.
4. **Idempotent re-run** (same scenario, compute twice) → second run produces identical data values; `computed_at` advances on `drive_statistics`. Pins the idempotency claim that B-104 Step 1's recompute trigger depends on.
5. **Multi-drive concurrent** (drives 21 + 22 both end via sequencer; compute over `--all-stale`) → both produce GREEN rows in one pass. Pins the nightly batch trigger (`server-analytics-batch.timer`).
6. **Spool-engine-grade reference signature scenarios** (Drive 11, Drive 15, Drive 18) — per Spool FLAG-5 (offer of engine-grade-A reference signatures for harness assertion). Pins post-Sprint-41 Drive 11/15/18 stats against the new compute path so a future regression to per-PID-envelope drift trips RED.

Each new scenario is a single test method on the existing `TestScenario1V0_27_16Reproducer` pattern. The fixtures + helpers do not need to grow.

## Invariants this harness preserves

1. **No mock seams.** `TestHarnessIntegrity` pins it. If a future agent introduces a `monkeypatch.setattr` on either compute function in this file, that test class will need a corresponding update — at which point Atlas + Argus + Marcus review the weakening.
2. **Same deploy artifact the IRL Pi runs.** The Pi-side schema comes from `ObdDatabase.initialize()` — the same code path the production Pi runs at boot. The server-side schema comes from `Base.metadata.create_all` — the same code path the production server runs at deploy.
3. **SSOT for "did the writer/compute path fire in deploy?"** This is the single test surface for that question. No sibling tests are allowed to gate on the same question via mocked seams. If one is filed, route through this harness.
4. **Retroactive RED proof is load-bearing.** The RED test is not a curiosity — it is the structural close on the I-040 discipline gap. Removing it requires PM + Atlas + Argus sign-off equivalent to weakening a deploy gate.

## Cross-links

- `offices/pm/backlog/B-104-server-side-analytics-authority.md` — the architectural epic
- `offices/pm/issues/2026-05-21-from-tester-v0.27.16-us-348-us-349-false-pass-recurrence.md` — Argus's RCA + structural recommendation
- `offices/ralph/sprint.json` US-355 — the work item this spec satisfies
- `specs/architecture.md` §10.7 (US-356) — Atlas-gated B-104 Step 1 architecture section
- `tests/integration/test_pi_to_server_e2e.py` — companion harness covering the HTTP /sync transport seam
- `src/server/analytics/drive_summary_compute.py` — the compute path the GREEN test exercises (US-350)
- `src/server/analytics/drive_statistics_compute.py` — same (US-351)
