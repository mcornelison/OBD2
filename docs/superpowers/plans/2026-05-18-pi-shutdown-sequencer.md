# Pi Shutdown Sequencer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Team note (overrides the skill's default execution handoff):** In this project Ralph implements, Atlas owns the architecture/design gate, Marcus orchestrates the sprint. This plan is the contract of record; it does not get executed by Atlas. Marcus folds it into a sprint; Ralph executes under TDD + sprint-branch discipline; Atlas reviews against the design gate.

**Goal:** Replace the power-watch trigger tangle with a small, single-source-of-truth ShutdownSequencer: one GPIO6 power-source provider, a 5 s smoothed trigger, a bounded extensible pre-shutdown task window (one SyncTask), graceful poweroff, and `POWER_OFF_ON_HALT=1` so the Pi restores on next power.

**Architecture:** One `PowerSourceProvider` (SSOT, wraps the sound `PldSensor` GPIO6 line) is the *only* power-source acquisition site; the UI and the sequencer both consume it and differ only by policy. `ShutdownSequencer` (renamed from `PowerWatch`, debounce logic from `84b5469` kept) owns the trigger policy and a bounded task window (Option B). The existing `pipeline.py`/`outcome.py`/`SyncWithServerTask` are reused as-is. `UpsMonitor.getPowerSource()` is retired from the power-source path (kept only as battery-health/VCELL telemetry).

**Tech Stack:** Python 3.11, pytest (TDD, no mocks of real behavior), gpiozero (DI'd), systemd unit, bash + pytest wrapper for the EEPROM enforcement script.

**Spec:** `docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md` (authoritative; read §2 SSOT, §3 architecture, §11 decisions).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/pi/power/power_source_provider.py` | SSOT for the power-source fact; wraps `PldSensor`; exposes `isExternalPowerPresent()` + `startupArmCheck()` | **Create** |
| `src/pi/hardware/pld_sensor.py` | GPIO6 line read + safe-direction fallback | Keep as-is (sound) |
| `src/pi/power/power_watch/controller.py` | Trigger policy + bounded window (rename `PowerWatch`→`ShutdownSequencer`) | Modify |
| `src/pi/power/power_watch/contract.py` | Task protocol (rename `PipelineTask`→`ShutdownTask`) | Modify |
| `src/pi/power/power_watch/__main__.py` | Entrypoint wiring (consume provider; task registry seam) | Modify |
| `src/pi/power/power_watch/{pipeline,outcome}.py`, `tasks/sync_with_server.py` | Bounded runner / durable record / the one V1 task | Keep; update import names only |
| `src/common/config/validator.py` | `pi.powerWatch.*` DEFAULTS + `_validatePowerWatch` (add `smoothingSec`; rename `confirmWindowSec`→`smoothingSec`, `confirmPollSec`→`smoothingPollSec`) | Modify |
| `src/pi/obdii/orchestrator/lifecycle.py` | UI power-source consumer — rewire from `UpsMonitor.getPowerSource` to `PowerSourceProvider` | Modify |
| `src/pi/hardware/ups_monitor.py` | `getPowerSource()` retired from the source path (keep `getVcell` for battery-health) | Modify (deprecate path) |
| `deploy/enforce-eeprom-power-off-on-halt.sh` | Enforce `POWER_OFF_ON_HALT=1` (was force-`0`) | Modify |
| `tests/deploy/test_eeprom_power_off_on_halt.sh` + `tests/deploy/test_deploy_pi_eeprom_config.py` | EEPROM script scenarios flipped to `=1` | Modify |
| `tests/pi/power/test_power_source_provider.py` | Provider unit tests | **Create** |
| `tests/pi/power/power_watch/test_systemd_parity.py` | Orchestration-proof: run entrypoint as systemd does | **Create** |
| `specs/architecture.md` §2/§10.6/§11, `docs/hardware-reference.md` | Reconcile to the new design (design-gate, same-sprint) | Modify |
| `offices/ralph/phase2-deploy-and-acceptance-runsheet.md` | IRL bench-drill runsheet | Modify |

---

## Task 1: Regression-first investigation (NO production code — gates the build)

**Files:**
- Create: `offices/ralph/findings/2026-05-18-what-regressed-shutdown-restore.md`
- Create: `offices/ralph/phase2-bench-observations-checklist.md` (CIO runs this)

- [ ] **Step 1: Identify the "worked ~2 sprints back" candidate range**

Run: `git log --oneline --first-parent -- src/pi/power deploy/enforce-eeprom-power-off-on-halt.sh deploy/eclipse-powerwatch.service | head -40`
Record the commits spanning V0.27.11 → V0.27.15 that touch the shutdown/EEPROM/trigger path.

- [ ] **Step 2: Diff the trigger + EEPROM path across that range**

Run: `git diff <V0.27.12-tip>..<HEAD> -- src/pi/power/power_watch/__main__.py src/pi/power/power_watch/controller.py deploy/enforce-eeprom-power-off-on-halt.sh`
Write, in the findings file, the precise change(s) that altered shutdown→restore behavior (expected: trigger moved off ground-truth onto the VCELL heuristic; EEPROM forced `0`).

- [ ] **Step 3: Produce the one-page "what regressed" note**

Findings file MUST state: (a) the single regression that broke the working loop, (b) whether the clean target design already subsumes it, (c) any behavior from the working version worth preserving. No speculation — cite commits/lines.

- [ ] **Step 4: Produce the CIO bench-observations checklist**

`phase2-bench-observations-checklist.md` MUST contain exactly these two
zero-interpretation checks for the CIO to run once, before any redeploy.
Vendor-confirmed context (Geekworm X1209 wiki + Suptronics official `pld.py`):
the X1209 exposes AC-loss detection on **BCM GPIO 6, digital, HIGH = power
present**, no I2C. The MAX17048 (I2C fuel gauge) is unrelated and is NOT
tested. Check A only confirms it on this physical unit.

```
A. GPIO6 read-only watch — uses OUR shipped PldSensor, NO poweroff, binary:
   ssh chi-eclipse-01
   cd ~/Projects/Eclipse-01
   PYTHONPATH=.:src ~/obd2-venv/bin/python - <<'PY'
   import time
   from src.pi.hardware.pld_sensor import PldSensor
   p = PldSensor(pin=6, powerPresentHigh=True)
   print("PldSensor available:", p.isAvailable)
   for _ in range(120):
       print(time.strftime("%H:%M:%S"),
             "EXTERNAL POWER PRESENT" if p.isExternalPowerPresent() else "POWER LOST")
       time.sleep(1)
   PY
   # While it prints: UNPLUG the adapter -> expect the word flip to "POWER LOST"
   #                   RE-PLUG           -> expect it flip back to "...PRESENT"
   #   It flips both ways      => GPIO6 confirmed; ship pldPowerPresentHigh=true
   #   "available: False"      => gpiozero/lgpio not in venv; install, re-run
   #   No flip on unplug       => escalate to Atlas (board variant; do NOT ship)
   # (Read-only: this never powers the Pi off.)

B. Wake mechanism at POWER_OFF_ON_HALT=1:
   sudo rpi-eeprom-config | grep POWER_OFF_ON_HALT   # confirm =1
   sudo systemctl poweroff
   (Pi dark)  remove external power, wait 5 s, reapply external power
   Pi auto-boots unattended?  YES => "=1" mechanism confirmed (rail power-cycles)
                              NO  => "=1" needs GPIO3/button assist; escalate to Atlas
```

- [ ] **Step 5: Commit (per sprint-branch discipline; Ralph commits, not Atlas)**

```bash
git add offices/ralph/findings/2026-05-18-what-regressed-shutdown-restore.md offices/ralph/phase2-bench-observations-checklist.md
git commit -m "docs(shutdown-seq): regression-first note + CIO bench-observations checklist (plan Task 1)"
```

**GATE:** Task 1's findings + the two CIO bench measurements must be reviewed by Atlas before Task 5's trigger wiring is considered final. Tasks 2–4, 6–9 do not depend on the bench result and may proceed.

---

## Task 2: Config surface — add `smoothingSec`, rename confirm→smoothing

**Files:**
- Modify: `src/common/config/validator.py:178-180` (DEFAULTS) and `:622-631` (`_validatePowerWatch`)
- Test: `tests/common/config/test_config_validator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_validate_powerWatch_appliesSmoothingDefaults_andRejectsNonPositive():
    from src.common.config.validator import ConfigValidator, ConfigValidationError
    base = {"protocolVersion": 1, "schemaVersion": 1, "deviceId": "t",
            "logging": {}, "pi": {}, "server": {}}
    cfg = ConfigValidator().validate(dict(base))
    pw = cfg["pi"]["powerWatch"]
    assert pw["smoothingSec"] == 5
    assert pw["smoothingPollSec"] == 1
    assert "confirmWindowSec" not in pw and "confirmPollSec" not in pw
    bad = dict(base); bad["pi"] = {"powerWatch": {"smoothingSec": 0}}
    import pytest
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/common/config/test_config_validator.py::test_validate_powerWatch_appliesSmoothingDefaults_andRejectsNonPositive -v`
Expected: FAIL (`smoothingSec` not in defaults).

- [ ] **Step 3: Edit DEFAULTS**

In `src/common/config/validator.py`, replace the three lines:
```python
    'pi.powerWatch.bootGraceSec': 120,
    'pi.powerWatch.confirmWindowSec': 20,
    'pi.powerWatch.confirmPollSec': 5,
```
with:
```python
    'pi.powerWatch.bootGraceSec': 120,
    # smoothingSec: a power-LOST reading must hold continuously this long
    # before the shutdown window opens (blip rejection -- spec sec 3, the
    # safety property that prevents the 2026-05-18 boot-sag bricking loop).
    # smoothingPollSec: re-sample cadence during the smoothing interval.
    'pi.powerWatch.smoothingSec': 5,
    'pi.powerWatch.smoothingPollSec': 1,
```

- [ ] **Step 4: Edit `_validatePowerWatch` key tuple**

In the `for key in (...)` tuple (`validator.py:622-631`) replace
`'pi.powerWatch.confirmWindowSec',` and `'pi.powerWatch.confirmPollSec',`
with
`'pi.powerWatch.smoothingSec',` and `'pi.powerWatch.smoothingPollSec',`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/common/config/test_config_validator.py -k powerWatch -v`
Expected: PASS. Then `python validate_config.py` → exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/common/config/validator.py tests/common/config/test_config_validator.py
git commit -m "feat(config): pi.powerWatch.smoothingSec (5s, in-V1 safety); rename confirm->smoothing"
```

---

## Task 3: `PowerSourceProvider` — the SSOT module

**Files:**
- Create: `src/pi/power/power_source_provider.py`
- Test: `tests/pi/power/test_power_source_provider.py`

- [ ] **Step 1: Write the failing test**

```python
from src.pi.power.power_source_provider import PowerSourceProvider

class _FakePld:
    def __init__(self, present, available=True):
        self._present, self.isAvailable = present, available
    def isExternalPowerPresent(self): return self._present
    def isPowerLost(self): return self.isAvailable and not self._present
    def startupPolarityOk(self): return self.isAvailable and self._present

def test_provider_isTheSingleSourceForPowerFact():
    p = PowerSourceProvider(pld=_FakePld(present=True))
    assert p.isExternalPowerPresent() is True
    assert p.startupArmCheck() is True
    lost = PowerSourceProvider(pld=_FakePld(present=False))
    assert lost.isExternalPowerPresent() is False
    assert lost.startupArmCheck() is False

def test_provider_unavailable_isSafeDirection():
    p = PowerSourceProvider(pld=_FakePld(present=False, available=False))
    assert p.isExternalPowerPresent() is True   # uncertain => do NOT shut down
    assert p.startupArmCheck() is False          # but refuse to arm
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/power/test_power_source_provider.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Create the module**

```python
################################################################################
# File Name: power_source_provider.py
# Purpose/Description: Single Source of Truth for the "power source" fact. The
#                      ONLY place in the codebase that acquires power-source
#                      state. Wraps the sound PldSensor (X1209 GPIO6 PLD).
#                      UI and ShutdownSequencer both consume THIS; they differ
#                      only by the policy they apply (UI = instantaneous;
#                      sequencer = smoothed). UpsMonitor.getPowerSource() (the
#                      VCELL-trend heuristic) is retired from this fact.
# Author: (shutdown-sequencer plan 2026-05-18)
# Creation Date: 2026-05-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""SSOT for the power-source fact (wraps the GPIO6 PLD line)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
__all__ = ["PowerSourceProvider"]


class PowerSourceProvider:
    """The single authoritative provider of the power-source fact.

    Consumers apply their own policy; they never acquire power source any
    other way. ``isExternalPowerPresent()`` is instantaneous ground truth
    (UI consumes this directly; the ShutdownSequencer applies smoothing on
    top). Unavailable/unreadable resolves to power-present -- the
    deliberate "uncertain => do NOT shut down" safe direction; the arm
    self-check is the separate guard that refuses to arm in that case.
    """

    def __init__(self, *, pld: Any) -> None:
        """Args:
            pld: A PldSensor-shaped object exposing isExternalPowerPresent(),
                isPowerLost(), startupPolarityOk(), isAvailable.
        """
        self._pld = pld

    def isExternalPowerPresent(self) -> bool:
        """Instantaneous ground-truth power-source reading."""
        return bool(self._pld.isExternalPowerPresent())

    def isPowerLost(self) -> bool:
        """True only when the line is readable AND says power lost."""
        return bool(self._pld.isPowerLost())

    def startupArmCheck(self) -> bool:
        """The Pi only booted because power is live, so at start the line
        MUST read power-present. False => wrong pin/polarity/unreadable =>
        caller refuses to arm the shutdown path."""
        ok = bool(self._pld.startupPolarityOk())
        if not ok:
            logger.error(
                "PowerSourceProvider arm self-check FAILED -- refusing to arm "
                "(uncertain power source => do NOT shut down)."
            )
        return ok
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/power/test_power_source_provider.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/pi/power/power_source_provider.py tests/pi/power/test_power_source_provider.py
git commit -m "feat(power): PowerSourceProvider — SSOT for the power-source fact"
```

---

## Task 4: Retire `UpsMonitor.getPowerSource()` from the source path; rewire the UI to the SSOT

**Files:**
- Modify: `src/pi/obdii/orchestrator/lifecycle.py:1829-1902` (`_subscribePowerMonitorToUpsMonitor`)
- Modify: `src/pi/hardware/ups_monitor.py` (`getPowerSource` → raise/deprecate on the source path; keep `getVcell`)
- Test: `tests/pi/obdii/orchestrator/test_lifecycle_power_source_ssot.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
def test_uiPowerSource_comesFromProvider_notUpsHeuristic():
    """The UI power indicator must be fed by PowerSourceProvider (GPIO6),
    never by UpsMonitor.getPowerSource (the retired VCELL heuristic)."""
    import inspect
    from src.pi.obdii.orchestrator import lifecycle
    src = inspect.getsource(lifecycle._subscribePowerMonitorToUpsMonitor)
    assert "getPowerSource" not in src, (
        "UI still wired to UpsMonitor.getPowerSource (SSOT violation)"
    )
    assert "PowerSourceProvider" in src or "_powerSourceProvider" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/obdii/orchestrator/test_lifecycle_power_source_ssot.py -v`
Expected: FAIL (current method bridges `UpsMonitor.onPowerSourceChange`).

- [ ] **Step 3: Rewire the UI consumer**

In `lifecycle.py`, the method that today bridges `upsMonitor.onPowerSourceChange → PowerMonitor.checkPowerStatus`: replace the UpsMonitor subscription with a poll/callback off `self._powerSourceProvider.isExternalPowerPresent()` feeding the same `PowerMonitor.checkPowerStatus(onAcPower: bool)` bridge. The provider is constructed once (alongside `_initializePowerMonitor`, `lifecycle.py:1593`) from the shared `PldSensor`. Keep the fan-out wrapper shape; only the *source* changes. Rename the method `_subscribePowerMonitorToPowerSourceProvider`; update its single caller (`lifecycle.py:1224`).

- [ ] **Step 4: Demote `UpsMonitor.getPowerSource`**

In `src/pi/hardware/ups_monitor.py`, change `getPowerSource()` to raise
`NotImplementedError("power source is owned by PowerSourceProvider (SSOT); "
"UpsMonitor provides battery-health only — use getVcell()")` and delete the
`onPowerSourceChange` callback wiring. `getVcell()` and battery-health remain
untouched.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pi/obdii/orchestrator/test_lifecycle_power_source_ssot.py tests/pi/hardware/ -k "ups or power" -v`
Expected: PASS; no test still asserts `getPowerSource` returns a source.

- [ ] **Step 6: Commit**

```bash
git add src/pi/obdii/orchestrator/lifecycle.py src/pi/hardware/ups_monitor.py tests/pi/obdii/orchestrator/test_lifecycle_power_source_ssot.py
git commit -m "refactor(power): UI consumes PowerSourceProvider SSOT; retire UpsMonitor.getPowerSource from the source path"
```

---

## Task 5: `PowerWatch` → `ShutdownSequencer`; trigger = provider + smoothing

**Files:**
- Modify: `src/pi/power/power_watch/controller.py` (rename class; param names)
- Modify: `src/pi/power/power_watch/__main__.py:199-260` (wire provider; smoothing)
- Test: `tests/pi/power/power_watch/test_controller.py` (rename refs)

- [ ] **Step 1: Write the failing test**

```python
def test_shutdownSequencer_blipRejectedBySmoothing_noPoweroff():
    from src.pi.power.power_watch.controller import ShutdownSequencer
    calls = {"off": 0}
    seq = ShutdownSequencer(
        isOnBattery=iter([True, False]).__next__,   # blip then recovered
        vcell=lambda: 3.9,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: calls.__setitem__("off", calls["off"] + 1),
        vcellFloor=3.50, totalCapSec=45,
        smoothingSec=5, smoothingPollSec=0,
        sleepFn=lambda _s: None,
    )
    seq.handleOnBattery()
    assert calls["off"] == 0      # blip => never powered off
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/power/power_watch/test_controller.py::test_shutdownSequencer_blipRejectedBySmoothing_noPoweroff -v`
Expected: FAIL (`ShutdownSequencer` not defined; param is `confirmWindowSec`).

- [ ] **Step 3: Rename + reparametrize the controller**

In `controller.py`: rename class `PowerWatch` → `ShutdownSequencer` (keep `__all__` updated); rename ctor params `confirmWindowSec`→`smoothingSec`, `confirmPollSec`→`smoothingPollSec`, and the internal `_confirmSustainedOnBattery`→`_smoothedPowerLost` (logic unchanged — it already implements exactly the spec §3 smoothing: a single not-on-battery read aborts → no poweroff; failed-VCELL never powers off; Option-B floor on a successful low read). Update the docstrings to "smoothing".

- [ ] **Step 4: Rewire the entrypoint to the provider**

In `__main__.py`: build `PowerSourceProvider(pld=PldSensor(pin=pldGpioPin, powerPresentHigh=pldPowerPresentHigh))`; pass `isOnBattery=provider.isPowerLost`, keep `vcell=monitor.getVcell` (battery-health only). Replace the `pld.startupPolarityOk()` arm-check call with `provider.startupArmCheck()`. Replace `confirmWindowSec/confirmPollSec` reads with `smoothingSec/smoothingPollSec`. The `_pldWatchLoop` boot-grace + edge-trigger stays.

- [ ] **Step 5: Run tests**

Run: `pytest tests/pi/power/power_watch/ -m "not slow" -v`
Expected: PASS (rename-updated suite, incl. transient-blip + failed-vcell regression tests).

- [ ] **Step 6: Commit**

```bash
git add src/pi/power/power_watch/controller.py src/pi/power/power_watch/__main__.py tests/pi/power/power_watch/test_controller.py
git commit -m "refactor(power): PowerWatch -> ShutdownSequencer; trigger = PowerSourceProvider + smoothing"
```

---

## Task 6: Formalize the `ShutdownTask` interface + single-task V1 seam

**Files:**
- Modify: `src/pi/power/power_watch/contract.py:41-48` (`PipelineTask`→`ShutdownTask`)
- Modify: importers: `pipeline.py:24`, `sync_with_server.py:25`, `__main__.py`
- Test: `tests/pi/power/power_watch/test_task_seam.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
def test_v1_hasExactlyOneShutdownTask_andSeamIsPluggable():
    from src.pi.power.power_watch.contract import ShutdownTask
    from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask
    t = SyncWithServerTask(serverReachable=lambda: False,
                           runSync=lambda: None, writeRecord=lambda _x: None)
    assert isinstance(t, ShutdownTask)          # satisfies the protocol
    from src.pi.power.power_watch import __main__ as m
    assert hasattr(m, "buildV1Tasks")           # the documented registry seam
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/power/power_watch/test_task_seam.py -v`
Expected: FAIL (`ShutdownTask` undefined; `buildV1Tasks` absent).

- [ ] **Step 3: Rename the protocol + add the seam**

In `contract.py` rename `PipelineTask`→`ShutdownTask` (Protocol body unchanged), update `__all__`. Update the `from ...contract import` lines in `pipeline.py:24` and `sync_with_server.py:25`. In `__main__.py` add an explicit single-point registry seam:
```python
def buildV1Tasks(syncTask) -> list:
    """The ordered V1 shutdown task list. EXACTLY one task in V1 (Option A).
    Future tasks (e.g. update-check) append here -- the ONLY edit point;
    ShutdownSequencer and runPipeline never change."""
    return [syncTask]
```
and call `runPipeline(buildV1Tasks(syncTask), perTaskTimeoutSec=...)`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/pi/power/power_watch/ -m "not slow" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pi/power/power_watch/ tests/pi/power/power_watch/test_task_seam.py
git commit -m "refactor(power): PipelineTask -> ShutdownTask; explicit single-point V1 task seam"
```

---

## Task 7: Orchestration-proof — systemd-parity test

**Files:**
- Create: `tests/pi/power/power_watch/test_systemd_parity.py`

- [ ] **Step 1: Write the failing test**

```python
import os, subprocess, sys, json, tempfile, pathlib

def test_entrypoint_runs_exactly_as_systemd_invokes_it(tmp_path):
    """Spawn `python -m src.pi.power.power_watch` as a SUBPROCESS under the
    unit's exact PYTHONPATH (repo root + repo/src), exercising the real
    import graph. Positive execution evidence required: a marker file the
    real chain writes. Absence of an error is NOT accepted as proof."""
    repo = pathlib.Path(__file__).resolve().parents[4]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo}{os.pathsep}{repo / 'src'}"
    env["PW_TEST_ONESHOT"] = "1"
    marker = tmp_path / "poweroff.marker"
    env["PW_TEST_POWEROFF_MARKER"] = str(marker)
    r = subprocess.run([sys.executable, "-m", "src.pi.power.power_watch"],
                        env=env, cwd=str(repo), capture_output=True,
                        text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert marker.exists(), (
        "entrypoint did not reach the (stubbed) poweroff -- the wired chain "
        "did not actually execute (DOA-class failure)"
    )
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/pi/power/power_watch/test_systemd_parity.py -v`
Expected: PASS if the `PW_TEST_ONESHOT` chain (already in `__main__.py:104-158`) still produces the marker after Tasks 5–6 renames; FAIL loudly if a rename broke the import graph (this test is the regression net for exactly that).

- [ ] **Step 3: If FAIL, fix the import/rename breakage** (no new code — it means a Task 5/6 rename left a dangling import; fix the import, re-run).

- [ ] **Step 4: Commit**

```bash
git add tests/pi/power/power_watch/test_systemd_parity.py
git commit -m "test(power): systemd-parity orchestration-proof (positive execution evidence)"
```

---

## Task 8: Fix the EEPROM defect — enforce `POWER_OFF_ON_HALT=1`

**Files:**
- Modify: `deploy/enforce-eeprom-power-off-on-halt.sh`
- Modify: `tests/deploy/test_eeprom_power_off_on_halt.sh`, `tests/deploy/test_deploy_pi_eeprom_config.py`

- [ ] **Step 1: Update the bash test scenarios first (TDD)**

In `tests/deploy/test_eeprom_power_off_on_halt.sh`, invert the expectations: absent → rewrite to `=1`; `=0` → rewrite to `=1`; `=1` → no-op; `=2` → rewrite to `=1`; tool-missing → exit 1; apply-fails → exit 2; idempotency on `=1`.

- [ ] **Step 2: Run to verify it fails**

Run: `bash tests/deploy/test_eeprom_power_off_on_halt.sh`
Expected: FAIL (script still enforces `0`).

- [ ] **Step 3: Flip the script target to `1`**

In `deploy/enforce-eeprom-power-off-on-halt.sh`: rewrite the header block to state the **locked decision and rationale** (Pi 5 + X1209-HAT: `=1` powers the PMIC fully off so USB-C power-return is a real boot; `=0` leaves the PMIC active while the HAT holds the rail → no wake edge → Finding B). Change the no-op condition from `value = 0` to `value = 1`; change the `sed` rewrite target `POWER_OFF_ON_HALT=0` → `POWER_OFF_ON_HALT=1`; change the absent-line branch from "defaults to 0; OK" to "absent → rewrite to explicit `=1` (default 0 is WRONG on this HAT topology)". Update echo messages.

- [ ] **Step 4: Run tests to verify pass**

Run: `bash tests/deploy/test_eeprom_power_off_on_halt.sh && pytest tests/deploy/test_deploy_pi_eeprom_config.py -v`
Expected: PASS (all scenarios converge on `=1`).

- [ ] **Step 5: Commit**

```bash
git add deploy/enforce-eeprom-power-off-on-halt.sh tests/deploy/test_eeprom_power_off_on_halt.sh tests/deploy/test_deploy_pi_eeprom_config.py
git commit -m "fix(deploy): enforce POWER_OFF_ON_HALT=1 (was force-0; the deploy step was reverting the correct setting every deploy)"
```

---

## Task 9: Design-gate doc reconciliation (same-sprint, load-bearing)

**Files:**
- Modify: `specs/architecture.md` §2 (lines 95-131), §10.6 (1654+), §11 (2125-2177)
- Modify: `docs/hardware-reference.md` (lines 40-62, 93-129)

- [ ] **Step 1: §2 power-source** — replace the VCELL-heuristic narrative with: power source is the `PowerSourceProvider` SSOT over the GPIO6 PLD line; `UpsMonitor` is battery-health/VCELL telemetry only; cite the 2026-05-18 bricking incident as rationale.

- [ ] **Step 2: §10.6** — replace the deleted `PowerDownOrchestrator` ladder section with the `ShutdownSequencer` design (Option B window, smoothing, arm-self-check, task seam). Retain the VCELL-calibration history as an explicitly-marked *superseded* note.

- [ ] **Step 3: §11 EEPROM** — rewrite: on Pi 5 + X1209-HAT, `POWER_OFF_ON_HALT=1` is the locked setting (mechanism + Finding-B rationale); **remove the now-false "=0 ✅" table and the F-6 KNOWN-FALSE banner becomes unnecessary** because the section is now correct; state the empirical bench drill is the arbiter.

- [ ] **Step 4: `hardware-reference.md`** — delete the fictitious I2C power-source register section (F-3); mark UPS-HAT identity "believed X1209-class, UNVERIFIED pending CIO bench confirmation" (F-4).

- [ ] **Step 5: Commit**

```bash
git add specs/architecture.md docs/hardware-reference.md
git commit -m "docs(arch): reconcile power/shutdown spec to ShutdownSequencer + EEPROM=1 (design-gate, F-1..F-6)"
```

---

## Task 10: IRL acceptance runsheet

**Files:**
- Modify: `offices/ralph/phase2-deploy-and-acceptance-runsheet.md`

- [ ] **Step 1: Rewrite the runsheet** to the spec §10 gate, in order: (a) CIO bench-observations checklist from Task 1 (GPIO6 polarity + rail-cycle at `=1`) BEFORE redeploy; (b) **precondition: boot the Pi N times on external power, confirm it stays up > bootGrace + smoothing and does NOT self-poweroff**; (c) on-battery cycles: battery-detected → window runs (sync when reachable, skip when not) → graceful poweroff → **unattended restore on next power**; acceptance = 5 consecutive clean unattended cycles (CIO ratifies the count); (d) recovery procedure if powerwatch misbehaves (`stop; disable; rm unit; daemon-reload`).

- [ ] **Step 2: Commit**

```bash
git add offices/ralph/phase2-deploy-and-acceptance-runsheet.md
git commit -m "docs(runsheet): shutdown-sequencer IRL acceptance (bench-obs + stays-up precondition + restore cycles)"
```

---

## Self-Review

**1. Spec coverage:** §2 SSOT → T3/T4; §3 architecture/Option-B/smoothing → T2/T5; §4 config → T2; §5 orchestration-proof → T7; §6 regression-first + bench obs → T1; §7 retire/keep → T4 (heuristic retired) + T5 (controller reused) + T6 (task contract); §8 GPIO6 gate → T1, EEPROM defect → T8; §9 non-goals — no update-check task exists (correct, Option A); §10 acceptance → T10; §11 decisions → T2/T5/T8 enforce the locked values. All sections mapped.

**2. Placeholder scan:** No "TBD/TODO/handle edge cases". Task 1 is intentionally a no-code investigation with a concrete written deliverable + a runnable CIO checklist (not a placeholder — it is the spec-mandated regression-first gate).

**3. Type/name consistency:** `ShutdownSequencer` (T5), `ShutdownTask` (T6), `PowerSourceProvider.isExternalPowerPresent/isPowerLost/startupArmCheck` (T3, consumed identically in T4/T5), `pi.powerWatch.smoothingSec/smoothingPollSec` (T2, consumed in T5), `buildV1Tasks` (T6) — consistent across tasks. `PldSensor` API used by the provider matches the real `pld_sensor.py` (`isExternalPowerPresent`, `isPowerLost`, `startupPolarityOk`, `isAvailable`).

**Dependency note:** T1 GATE only blocks *finalizing* T5's trigger (polarity/mechanism). T2–T4, T6–T9 are independent. T5 code lands behind the arm-self-check (safe even if the bench result is pending). T10 documents the gate.
