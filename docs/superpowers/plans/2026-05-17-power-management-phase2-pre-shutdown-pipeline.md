# Power Management Phase 2 — Bounded Pre-Shutdown Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deleted-by-Phase-1 in-app shutdown ladder with a minimal, isolated systemd power-watch service that, on sustained-on-battery, runs a hard-bounded best-effort pre-shutdown task pipeline (today: server-sync) and then unconditionally `systemctl poweroff` — with power-return aborting and resuming.

**Architecture:** A dedicated long-running systemd service (`eclipse-powerwatch`), a *separate process* from the OBD app, reuses the proven `UpsMonitor`/`PowerSource` detector (no new detector, no VCELL ladder). On sustained-on-battery it runs an ordered list of best-effort, individually time-boxed, interruption-safe tasks; an independent backstop (per-task timeout + total cap + VCELL-floor) forces graceful `poweroff` regardless of task state; external-power-return at any point aborts the pipeline + pending poweroff and resumes. Spec: `docs/superpowers/specs/2026-05-17-power-management-phase2-pre-shutdown-pipeline-design.md`.

**Tech Stack:** Python 3.11 (stdlib: `enum`, `json`, `os`, `time`, `threading`, `subprocess`, `argparse`), the existing `src/pi/hardware/ups_monitor.py` detector, the existing `src/pi/sync/client.py` + `src/pi/network/home_detector.py`, systemd, `deploy/deploy-pi.sh`, the validator (`src/common/config/validator.py`), pytest.

**Scope (spec §7):** IN — the power-watch service + bounded pipeline + sync task + the typed-record *producer* + clean deletion of the legacy `PowerDownOrchestrator` ladder. OUT — the record *consumer* (separate process), update-apply, Phase-3 BT, the instrument `CLEAN_COMPLETE` fix (housekeeping). Bug-1 needs no work (eliminated by design).

**Conventions:** camelCase funcs/vars, PascalCase classes, UPPER_SNAKE consts; project file-header banner on new files; runtime imports use `src.*` form; **the V0.27.12-DOA lesson is mandatory** — any new systemd unit's `PYTHONPATH` MUST be `<repo>:<repo>/src` (repo root *and* src/, mirroring `src/pi/main.py:47-57`); tests under `tests/pi/...`; `ruff check` clean; `pytest tests/` before each commit. Build the replacement (T1–T8) and prove it BEFORE the legacy cutover (T9) — replacement-before-removal, no gap.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/pi/power/power_watch/__init__.py` (NEW) | package marker |
| `src/pi/power/power_watch/contract.py` (NEW) | single source of truth: `OutcomeKind` enum, `PipelineTask` Protocol, record schema constants |
| `src/pi/power/power_watch/outcome.py` (NEW) | `writeOutcomeRecord()` — atomic, fail-safe, fdatasync'd JSON producer (consumer is out of scope) |
| `src/pi/power/power_watch/pipeline.py` (NEW) | `runPipeline(tasks, perTaskTimeout)` — ordered best-effort, per-task timeout, isolated, never raises |
| `src/pi/power/power_watch/controller.py` (NEW) | `PowerWatch` — sustained-on-battery trigger (reuses `UpsMonitor`), hard bound (total cap + VCELL floor), power-return abort, `systemctl poweroff` |
| `src/pi/power/power_watch/tasks/sync_with_server.py` (NEW) | the CIO sync state machine; reachability + sync bound by DI to the real `home_detector`/`sync.client` |
| `src/pi/power/power_watch/__main__.py` (NEW) | service entrypoint (`python -m src.pi.power.power_watch`) |
| `deploy/eclipse-powerwatch.service` (NEW) | dedicated systemd service (dual-path PYTHONPATH) |
| `deploy/deploy-pi.sh` (MOD) | `step_install_power_watch_unit()` + call site |
| `src/common/config/validator.py` (MOD) | `pi.powerWatch.*` DEFAULTS + `_validatePowerWatch` (conservative interim values) |
| `tests/pi/power/power_watch/test_*.py` (NEW) | unit + the real-invocation guard test |
| (CUTOVER, T9) `src/pi/power/orchestrator.py` + ~13 wiring files | delete the legacy `PowerDownOrchestrator` ladder + its wiring (inventory-first) |

---

## Task 1: Contract — single source of truth

**Files:** Create `src/pi/power/power_watch/__init__.py`, `src/pi/power/power_watch/contract.py`; Test `tests/pi/power/power_watch/test_contract.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/pi/power/power_watch/test_contract.py
"""Contract: outcome kinds + pipeline-task protocol are the single source of truth."""
from src.pi.power.power_watch.contract import OutcomeKind, RECORD_SCHEMA_VERSION


def test_outcomeKinds_exact():
    assert {k.value for k in OutcomeKind} == {
        "server_unavailable", "sync_failed_after_retry", "real_error", "ok"
    }


def test_schema_version_is_int():
    assert isinstance(RECORD_SCHEMA_VERSION, int) and RECORD_SCHEMA_VERSION >= 1
```
- [ ] **Step 2: Run — expect FAIL** `pytest tests/pi/power/power_watch/test_contract.py -v` → `ModuleNotFoundError`.
- [ ] **Step 3: Implement** — create `__init__.py` (empty package marker + the project file-header banner as a comment) and `contract.py` with the standard file-header banner, then:
```python
from __future__ import annotations

import enum
from typing import Protocol

__all__ = ["OutcomeKind", "PipelineTask", "RECORD_SCHEMA_VERSION"]

RECORD_SCHEMA_VERSION = 1


class OutcomeKind(enum.Enum):
    OK = "ok"
    SERVER_UNAVAILABLE = "server_unavailable"        # benign, expected
    SYNC_FAILED_AFTER_RETRY = "sync_failed_after_retry"
    REAL_ERROR = "real_error"                        # a genuine fault -> record


class PipelineTask(Protocol):
    name: str
    def run(self) -> "OutcomeKind": ...   # MUST NOT raise; MUST be interruption-safe
```
- [ ] **Step 4: Run — expect PASS** (2 passed).
- [ ] **Step 5: Commit**
```bash
git -C Z:/o/OBD2v2 add src/pi/power/power_watch/__init__.py src/pi/power/power_watch/contract.py tests/pi/power/power_watch/test_contract.py
git -C Z:/o/OBD2v2 commit -m "feat(power_watch): contract -- OutcomeKind + PipelineTask protocol (Phase-2 T1)"
```

---

## Task 2: Outcome-record producer (atomic, fail-safe)

**Files:** Create `src/pi/power/power_watch/outcome.py`; Test `tests/pi/power/power_watch/test_outcome.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/pi/power/power_watch/test_outcome.py
import json
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.outcome import writeOutcomeRecord


def test_writes_typed_record(tmp_path):
    p = tmp_path / "powerwatch_outcome.json"
    writeOutcomeRecord(str(p), OutcomeKind.REAL_ERROR, detail="boom", task="sync_with_server")
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rec["kind"] == "real_error"
    assert rec["detail"] == "boom"
    assert rec["task"] == "sync_with_server"
    assert rec["schema"] == 1 and "ts" in rec


def test_never_raises_on_unwritable_path(caplog):
    writeOutcomeRecord("/proc/cpuinfo/nope/x.json", OutcomeKind.REAL_ERROR, detail="d", task="t")
    assert any("powerwatch outcome" in r.message for r in caplog.records)
```
- [ ] **Step 2: Run — expect FAIL** (`ImportError: writeOutcomeRecord`).
- [ ] **Step 3: Implement** `outcome.py` (file-header banner; reuse the proven atomic+fdatasync pattern from `boot_progress`):
```python
from __future__ import annotations

import json
import logging
import os

from src.common.time.helper import utcIsoNow
from src.pi.diagnostics.boot_progress import _fdatasyncBestEffort  # proven helper
from src.pi.power.power_watch.contract import RECORD_SCHEMA_VERSION, OutcomeKind

logger = logging.getLogger(__name__)
__all__ = ["writeOutcomeRecord"]


def writeOutcomeRecord(path: str, kind: OutcomeKind, *, detail: str, task: str) -> None:
    """Producer ONLY. Atomic write-temp+rename+fdatasync; never raises
    (a draining-Pi failure must not block shutdown). The consumer (next
    boot, separate process) is out of scope."""
    try:
        rec = {"schema": RECORD_SCHEMA_VERSION, "kind": kind.value,
               "detail": detail, "task": task, "ts": utcIsoNow()}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")))
            fh.flush()
            _fdatasyncBestEffort(fh.fileno())
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 -- producer must never block shutdown
        logger.warning("powerwatch outcome record write failed: %s", exc)
```
- [ ] **Step 4: Run — expect PASS** (2 passed).
- [ ] **Step 5: Commit** (`feat(power_watch): atomic fail-safe outcome-record producer (T2)`), files scoped to the 2.

---

## Task 3: Bounded pipeline runner

**Files:** Create `src/pi/power/power_watch/pipeline.py`; Test `tests/pi/power/power_watch/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**
```python
# tests/pi/power/power_watch/test_pipeline.py
import time
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.pipeline import runPipeline


class _Task:
    def __init__(self, name, fn): self.name = name; self._fn = fn
    def run(self): return self._fn()


def test_runs_in_order_and_isolates_failure():
    seen = []
    def a(): seen.append("a"); return OutcomeKind.OK
    def b(): seen.append("b"); raise RuntimeError("explode")  # task contract says don't raise; runner still isolates
    def c(): seen.append("c"); return OutcomeKind.OK
    results = runPipeline([_Task("a", a), _Task("b", b), _Task("c", c)], perTaskTimeoutSec=1.0)
    assert seen == ["a", "b", "c"]                       # one failure never blocks the next
    assert results["a"] == OutcomeKind.OK
    assert results["b"] == OutcomeKind.REAL_ERROR        # raised -> real_error, isolated
    assert results["c"] == OutcomeKind.OK


def test_per_task_timeout_does_not_hang():
    def slow(): time.sleep(5); return OutcomeKind.OK
    t0 = time.monotonic()
    results = runPipeline([_Task("slow", slow)], perTaskTimeoutSec=0.5)
    assert time.monotonic() - t0 < 3.0                    # bounded, not 5s
    assert results["slow"] == OutcomeKind.REAL_ERROR      # timed out -> real_error
```
- [ ] **Step 2: Run — expect FAIL** (`ImportError: runPipeline`).
- [ ] **Step 3: Implement** `pipeline.py` (file-header banner). Each task runs in a worker thread with a join-timeout (a hung task cannot block the pipeline; its thread is daemonized and abandoned — acceptable: the process is about to power off):
```python
from __future__ import annotations

import logging
import threading

from src.pi.power.power_watch.contract import OutcomeKind, PipelineTask

logger = logging.getLogger(__name__)
__all__ = ["runPipeline"]


def runPipeline(tasks: list[PipelineTask], *, perTaskTimeoutSec: float) -> dict[str, OutcomeKind]:
    """Run tasks in order, best-effort, each hard-bounded by
    perTaskTimeoutSec. A task that raises OR times out -> REAL_ERROR for
    that task; never blocks the next task; never raises out of here."""
    results: dict[str, OutcomeKind] = {}
    for task in tasks:
        box: dict[str, OutcomeKind] = {}
        def _runner(t=task, b=box):
            try:
                b["r"] = t.run()
            except Exception as exc:  # noqa: BLE001 -- isolate per task
                logger.error("powerwatch task %s raised: %s", t.name, exc)
                b["r"] = OutcomeKind.REAL_ERROR
        th = threading.Thread(target=_runner, name=f"pw-{task.name}", daemon=True)
        th.start()
        th.join(timeout=perTaskTimeoutSec)
        if th.is_alive():
            logger.error("powerwatch task %s exceeded %.1fs -- abandoning (shutdown imminent)",
                         task.name, perTaskTimeoutSec)
            results[task.name] = OutcomeKind.REAL_ERROR
        else:
            results[task.name] = box.get("r", OutcomeKind.REAL_ERROR)
    return results
```
- [ ] **Step 4: Run — expect PASS** (2 passed).
- [ ] **Step 5: Commit** (`feat(power_watch): bounded per-task pipeline runner (T3)`).

---

## Task 4: Controller — trigger, hard bound, power-return abort

**Files:** Create `src/pi/power/power_watch/controller.py`; Test `tests/pi/power/power_watch/test_controller.py`

- [ ] **Step 1: Write the failing tests** (inject fakes for the detector, the pipeline, and the poweroff fn so no real I2C/shutdown):
```python
# tests/pi/power/power_watch/test_controller.py
from src.pi.power.power_watch.controller import PowerWatch


def test_on_sustained_battery_runs_pipeline_then_powers_off():
    calls = []
    pw = PowerWatch(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=3.40, totalCapSec=2.0,
    )
    pw.handleOnBattery()
    assert calls == ["pipeline", "poweroff"]            # pipeline first, then unconditional poweroff


def test_vcell_floor_short_circuits_pipeline():
    calls = []
    pw = PowerWatch(isOnBattery=lambda: True, vcell=lambda: 3.30,  # below floor
                     runPipelineFn=lambda: calls.append("pipeline"),
                     powerOffFn=lambda: calls.append("poweroff"),
                     vcellFloor=3.40, totalCapSec=2.0)
    pw.handleOnBattery()
    assert calls == ["poweroff"]                         # skip pipeline entirely, poweroff now


def test_power_return_during_window_aborts_and_resumes():
    calls = []
    # power returns mid-window: isOnBattery flips False before pipeline finishes
    flips = iter([True, False])
    pw = PowerWatch(isOnBattery=lambda: next(flips, False), vcell=lambda: 3.9,
                    runPipelineFn=lambda: calls.append("pipeline"),
                    powerOffFn=lambda: calls.append("poweroff"),
                    vcellFloor=3.40, totalCapSec=2.0)
    pw.handleOnBattery()
    assert "poweroff" not in calls                        # aborted, resumed normal op
```
- [ ] **Step 2: Run — expect FAIL** (`ImportError: PowerWatch`).
- [ ] **Step 3: Implement** `controller.py` (file-header banner). DI everything (no real I2C/poweroff in unit tests). `handleOnBattery()`: re-check power-return at each decision point; VCELL-floor short-circuit → poweroff now; else run pipeline (bounded by total cap, in a thread joined with `totalCapSec`); if power returned at any checkpoint → abort, do NOT poweroff, return (resume); else unconditional `powerOffFn()`. The poweroff is reached on EVERY path that isn't an explicit power-return abort. Google docstrings on the public method.
```python
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)
__all__ = ["PowerWatch"]


class PowerWatch:
    def __init__(self, *, isOnBattery: Callable[[], bool], vcell: Callable[[], float],
                 runPipelineFn: Callable[[], None], powerOffFn: Callable[[], None],
                 vcellFloor: float, totalCapSec: float):
        self._isOnBattery = isOnBattery
        self._vcell = vcell
        self._runPipeline = runPipelineFn
        self._powerOff = powerOffFn
        self._vcellFloor = vcellFloor
        self._totalCapSec = totalCapSec

    def handleOnBattery(self) -> None:
        """Called once when sustained-on-battery is detected. Bounded; on
        external-power-return at any checkpoint -> abort + resume (no
        poweroff); else run the bounded pipeline then unconditional
        graceful poweroff."""
        if not self._isOnBattery():
            logger.info("powerwatch: power returned before window start -- resume")
            return
        try:
            v = self._vcell()
        except Exception as exc:  # noqa: BLE001
            logger.error("powerwatch: vcell read failed (%s) -- treat as safe-floor", exc)
            v = self._vcellFloor - 1.0   # force the safe short-circuit
        if v <= self._vcellFloor:
            logger.warning("powerwatch: VCELL %.3f <= floor %.3f -- skip pipeline, poweroff now",
                           v, self._vcellFloor)
            self._powerOff()
            return
        done = threading.Event()
        def _pipe():
            try:
                self._runPipeline()
            except Exception as exc:  # noqa: BLE001 -- runner already isolates; belt+braces
                logger.error("powerwatch: pipeline wrapper raised: %s", exc)
            finally:
                done.set()
        th = threading.Thread(target=_pipe, name="pw-pipeline", daemon=True)
        th.start()
        done.wait(timeout=self._totalCapSec)   # total cap; a hung pipeline cannot block poweroff
        if not self._isOnBattery():
            logger.info("powerwatch: power returned during window -- abort, resume normal op")
            return
        logger.warning("powerwatch: pre-shutdown window resolved -- graceful poweroff")
        self._powerOff()
```
- [ ] **Step 4: Run — expect PASS** (3 passed).
- [ ] **Step 5: Commit** (`feat(power_watch): bounded controller w/ VCELL-floor + power-return abort (T4)`).

---

## Task 5: `sync_with_server` task (CIO state machine)

**Files:** Create `src/pi/power/power_watch/tasks/__init__.py`, `src/pi/power/power_watch/tasks/sync_with_server.py`; Test `tests/pi/power/power_watch/test_sync_task.py`

- [ ] **Step 1: Write the failing tests** (DI: `serverReachable()` bool, `runSync()` -> None|raises). State machine: not reachable → `SERVER_UNAVAILABLE`; reachable + sync ok → `OK`; sync fails then retry ok → `OK`; fails twice → `SYNC_FAILED_AFTER_RETRY`; a non-network exception → `REAL_ERROR`. Real errors emit a record (DI'd record writer).
```python
# tests/pi/power/power_watch/test_sync_task.py
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask


def _task(reachable, sync_seq, rec):
    it = iter(sync_seq)
    def runSync():
        x = next(it)
        if isinstance(x, Exception): raise x
    return SyncWithServerTask(serverReachable=lambda: reachable, runSync=runSync,
                              writeRecord=rec)


def test_server_unavailable_is_benign_skip():
    recs = []
    assert _task(False, [], recs.append).run() == OutcomeKind.SERVER_UNAVAILABLE
    assert recs == []                                   # benign -> no real-error record


def test_sync_ok_first_try():
    assert _task(True, [None], [].append).run() == OutcomeKind.OK


def test_sync_fails_then_retry_ok():
    assert _task(True, [RuntimeError("net"), None], [].append).run() == OutcomeKind.OK


def test_sync_fails_twice():
    recs = []
    assert _task(True, [RuntimeError("net"), RuntimeError("net")], recs.append).run() \
        == OutcomeKind.SYNC_FAILED_AFTER_RETRY
    assert len(recs) == 1                                # logged + recorded, then continue


def test_real_error_is_recorded():
    recs = []
    assert _task(True, [ValueError("corrupt db")], recs.append).run() == OutcomeKind.REAL_ERROR
    assert recs and recs[0][0] == OutcomeKind.REAL_ERROR
```
- [ ] **Step 2: Run — expect FAIL** (`ImportError`).
- [ ] **Step 3: Implement** `tasks/__init__.py` (package marker) + `sync_with_server.py` (file-header banner). `SyncWithServerTask` satisfies `PipelineTask` (has `.name`, `.run()`; `run()` NEVER raises). `serverReachable`/`runSync`/`writeRecord` are constructor-injected callables. Logic exactly per the CIO state machine; `writeRecord(kind, detail)` invoked only for `SYNC_FAILED_AFTER_RETRY` and `REAL_ERROR` (benign `SERVER_UNAVAILABLE` does NOT record). "Real error" = any exception that is not the retry-eligible sync failure path — model it as: `runSync` raising once is retryable; a second raise of the *same* class → `SYNC_FAILED_AFTER_RETRY`; but if classification is ambiguous, treat unexpected exception types as `REAL_ERROR` (the test pins `ValueError` → REAL_ERROR vs `RuntimeError` → retry/sync-failed). Implement with a small, explicit try/except producing exactly those OutcomeKinds; log success/error per the CIO spec.
- [ ] **Step 4: Run — expect PASS** (5 passed).
- [ ] **Step 5: Commit** (`feat(power_watch): sync_with_server task -- CIO state machine (T5)`).

> **Wiring note for T6 (NOT a placeholder — an explicit bind step):** the production `serverReachable`/`runSync` are bound in `__main__.py` to the REAL components. The implementer MUST inventory the exact public entrypoints first: `grep -n "^class \|^def \|def create" src/pi/network/home_detector.py src/pi/sync/client.py src/pi/sync/sync_cadence_controller.py`, pick the reachability check + the one-shot sync call, and bind them with a hard per-call timeout. Do NOT guess method names — bind to what the grep shows. If no clean one-shot sync entrypoint exists, STOP and report NEEDS_CONTEXT (do not invent one).

---

## Task 6: Service entrypoint + systemd unit + deploy step

**Files:** Create `src/pi/power/power_watch/__main__.py`, `deploy/eclipse-powerwatch.service`; Modify `deploy/deploy-pi.sh`; Test `tests/pi/power/power_watch/test_units.py`

- [ ] **Step 1: Write the failing tests** (static unit asserts + the dual-path PYTHONPATH guard — the V0.27.12-DOA lesson):
```python
# tests/pi/power/power_watch/test_units.py
from pathlib import Path
PI = "/home/mcornelison/Projects/Eclipse-01"
SVC = Path("deploy/eclipse-powerwatch.service").read_text(encoding="utf-8")


def test_dualpath_pythonpath_and_entrypoint():
    # The DOA root cause: PYTHONPATH must be repo root AND <repo>/src.
    assert f"Environment=PYTHONPATH={PI}:{PI}/src" in SVC
    assert f"WorkingDirectory={PI}" in SVC
    assert "ExecStart=" in SVC and "-m src.pi.power.power_watch" in SVC
    assert "User=mcornelison" in SVC
    assert "Restart=always" in SVC          # a watcher that dies must come back
```
- [ ] **Step 2: Run — expect FAIL** (`FileNotFoundError`).
- [ ] **Step 3a: Implement `__main__.py`** (file-header banner): build the real `PowerWatch` — reuse `UpsMonitor` for `isOnBattery` (`getPowerSource() == PowerSource.BATTERY`, debounced via the monitor's own sustained rule) and `vcell` (`getVcell()`); bind `runPipeline` to `runPipeline([SyncWithServerTask(...)], perTaskTimeoutSec=cfg)`; `powerOffFn = lambda: subprocess.run(["systemctl","poweroff"], timeout=cfg)`; load all numbers from config (Task 7). Register `UpsMonitor.registerSourceChangeCallback` so a BATTERY transition invokes `PowerWatch.handleOnBattery()` once (debounced). Bind `serverReachable`/`runSync` per the T5 wiring note (inventory-first).
- [ ] **Step 3b: Implement `deploy/eclipse-powerwatch.service`** — mirror `deploy/boot-progress-arm.service` structure INCLUDING the corrected dual-path guard comment + `Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01:/home/mcornelison/Projects/Eclipse-01/src`, `WorkingDirectory=/home/mcornelison/Projects/Eclipse-01`, `User=mcornelison`, `Type=simple`, `Restart=always`, `RestartSec=5`, `ExecStart=/home/mcornelison/obd2-venv/bin/python -m src.pi.power.power_watch`, `[Install] WantedBy=multi-user.target`. File-header `#`-banner like the other deploy units.
- [ ] **Step 3c: Modify `deploy/deploy-pi.sh`** — add `step_install_power_watch_unit()` mirroring `step_install_boot_progress_units()` byte-for-byte (cmp-if-changed install + daemon-reload-on-change + `systemctl enable --now eclipse-powerwatch.service`); add its call adjacent to the other `step_install_*_unit` calls.
- [ ] **Step 4: Verify** `pytest tests/pi/power/power_watch/test_units.py -v` (pass); `bash -n deploy/deploy-pi.sh`; `bash deploy/deploy-pi.sh --dry-run 2>&1 | grep -i power.watch` (prints the step).
- [ ] **Step 5: Commit** (`feat(power_watch): service entrypoint + systemd unit + deploy step (T6)`), scoped files only.

---

## Task 7: Config — `pi.powerWatch.*` (conservative interim; Spool-tune flagged)

**Files:** Modify `src/common/config/validator.py`; Test `tests/test_config_validator.py`

- [ ] **Step 1: Write the failing test**
```python
def test_powerWatch_defaults_applied():
    cfg = ConfigValidator().validate(_baseCfg())   # reuse the existing _baseCfg helper
    pw = cfg["pi"]["powerWatch"]
    assert pw["perTaskTimeoutSec"] == 20
    assert pw["totalWindowCapSec"] == 45
    assert pw["vcellFloorVolts"] == 3.50
    assert pw["poweroffTimeoutSec"] == 30
```
- [ ] **Step 2: Run — expect FAIL** (`KeyError: 'powerWatch'`).
- [ ] **Step 3: Implement** — in `DEFAULTS`, after the `pi.power.power_monitor.enabled` entry, add (comment block flags these as CONSERVATIVE INTERIM, to be tuned from Spool battery-runtime data per spec §9 before Phase-2 IRL acceptance — interim values are deliberately generous-but-bounded, never optimistic):
```python
    # Phase-2 power-watch (spec 2026-05-17). CONSERVATIVE INTERIM values --
    # MUST be tuned from Spool real-battery-runtime data before Phase-2 IRL
    # acceptance (see this plan's Task 7 follow-up + spec sec 9). They are
    # bounded + safe as shipped (worst case: we power off a little early),
    # never optimistic.
    'pi.powerWatch.perTaskTimeoutSec': 20,
    'pi.powerWatch.totalWindowCapSec': 45,
    'pi.powerWatch.vcellFloorVolts': 3.50,
    'pi.powerWatch.poweroffTimeoutSec': 30,
```
Add `_validatePowerWatch` (mirror `_validatePiSync` bool-then-type-then-range; each must be a positive number; `vcellFloorVolts` in (3.0, 4.3)); call it in `validate()` after `_validateBootProgress`. Modhist row.
- [ ] **Step 4: Run** `pytest tests/test_config_validator.py -k powerWatch -v` (pass) + `python validate_config.py` (exit 0).
- [ ] **Step 5: Commit** (`feat(config): pi.powerWatch.* conservative-interim defaults + validator (T7)`).
- [ ] **Step 6 (explicit follow-up, NOT a placeholder — a tracked task):** add a one-line row to `offices/pm/issues/` or surface to the CIO: *"Phase-2 numeric bounds (perTaskTimeoutSec/totalWindowCapSec/vcellFloorVolts) pending Spool battery-runtime tuning before Phase-2 IRL acceptance."* Commit that note separately.

---

## Task 8: Real-invocation guard test (the institutionalized DOA lesson)

**Files:** Test `tests/pi/power/power_watch/test_real_invocation.py`

- [ ] **Step 1: Write the test** — run the service entrypoint EXACTLY as systemd does (subprocess; PYTHONPATH = `<repo>:<repo>/src`; no conftest sys.path leak; inject env so it does ONE on-battery handle then exits, with `subprocess.run`/poweroff stubbed via a `PW_TEST_*` env hook the `__main__` honors only when set). Assert: process rc==0, **no `No module named 'pi'` / no traceback** in output, the outcome-record file was produced, and the (stubbed) poweroff was invoked exactly once. This is the test that would have caught the V0.27.12 DOA — it must run in the normal gate (NOT marked slow).
- [ ] **Step 2: Run — expect FAIL** until `__main__` honors the `PW_TEST_*` one-shot hook; then **PASS**.
- [ ] **Step 3: Implement** the minimal `PW_TEST_ONESHOT`/`PW_TEST_POWEROFF_MARKER` env hook in `__main__.py` (only active when env set) so the entrypoint is testable as-invoked without a real I2C bus or a real poweroff.
- [ ] **Step 4: Run — expect PASS**; then `pytest tests/pi/power/ -q` (no regressions).
- [ ] **Step 5: Commit** (`test(power_watch): real systemd-invocation guard (DOA-class) (T8)`).

---

## Task 9: LEGACY-LADDER CLEAN CUTOVER (inventory-first — T10 discipline)

**Files:** `src/pi/power/orchestrator.py` + its ~13-file wiring blast radius; Tests adjusted.

> This is a high-blast-radius deletion. It is INVENTORY-FIRST by design — pre-writing a 13-file deletion diff would be fake precision (the T10 cutover proved inventory-first + escalate-on-surprise is the correct approach; it caught the lifecycle.py trap). Replacement (T1–T8) MUST be built + green BEFORE this task runs (no gap).

- [ ] **Step 1: Inventory & report (no edits yet).** Run and record:
  `grep -rn "PowerDownOrchestrator\|power\.orchestrator\|createPowerDownOrchestrator\|pi.power.shutdownThresholds\|pi.power.power_monitor" src/ tests/ deploy/`
  For EACH hit classify: (a) the ladder definition (`src/pi/power/orchestrator.py`) — DELETE; (b) construction/wiring (e.g. `hardware_manager.py`, `obdii/orchestrator/lifecycle.py`, `obdii/orchestrator/core.py`, the `ups_monitor.registerSourceChangeCallback` feed) — REWIRE/REMOVE so the data app no longer constructs or depends on it; (c) tests of the ladder — DELETE; (d) comment/modhist text — leave; (e) the new `power_watch` — keep. Confirm the new `eclipse-powerwatch.service` is the SOLE shutdown decider. **If reality differs materially from this classification (an unexpected live consumer), STOP and report NEEDS_CONTEXT — do not guess-delete.**
- [ ] **Step 2:** Remove the `PowerDownOrchestrator` ladder + its construction/wiring per the inventory. The OBD app must still boot and collect data with zero reference to the ladder. Keep `UpsMonitor` (now consumed by `power_watch`). Retire ladder-only config (`pi.power.shutdownThresholds.*`) if nothing else uses it (verify via the grep) — else leave + note.
- [ ] **Step 3:** Update/delete the ladder's tests; do NOT recreate them. Any non-ladder test that asserted ladder wiring → minimally update to the new reality.
- [ ] **Step 4: Verify (the gate):** `pytest tests/pi/ -m "not slow" -q` (full suite green — the app boots/collects without the ladder); `ruff check` on every touched file; `grep -rn "PowerDownOrchestrator" src/` → zero outside historical modhist comments; the Task-8 real-invocation guard still green.
- [ ] **Step 5: Commit** (`refactor(power): delete legacy PowerDownOrchestrator ladder; eclipse-powerwatch is sole decider (Phase-2 T9)`), exactly the inventoried files.

---

## Task 9 — CORRECTED (supersedes the original Task 9 above; inventory done 2026-05-18)

> The original Task 9 estimated "~13 files, delete orchestrator.py". Inventory-first
> revealed three material differences (the escalate-on-surprise gate fired correctly):
> (1) `orchestrator.py` co-houses the `PowerLogWriter` type alias that KEPT
> data-collection code (`lifecycle._createPowerLogWriter`, `hardware_manager`)
> depends on -> RELOCATE, not blind-delete. (2) `ShutdownHandler.suppressLegacyTriggers`
> is ladder-coupled -> a safety decision, now MADE below. (3) ~22 ladder test files +
> 3 whole-system drill suites, not ~13. CIO chose "re-plan now then execute"; the
> ShutdownHandler call was deferred to this plan.

**DECISION 1 (safety, spec-grounded): suppress the legacy ShutdownHandler auto
low-battery trigger UNCONDITIONALLY.** Spec sec 6.1/sec 8 delete the in-app shutdown
decision/execution; `eclipse-powerwatch` (separate process) is the SOLE decider.
The legacy auto-trigger IS an in-app decider -> keeping it = the dual-decider /
I-036 entanglement this whole pivot exists to eliminate. The physical GPIO
shutdown-button path is a MANUAL user action (not the auto-trigger) and stays
functional -- only the automatic battery-driven in-app trigger is removed.

**DECISION 2 (coverage philosophy): delete the in-app shutdown drill/integration
suites.** `test_power_mgmt_lifecycle`, `test_power_mgmt_e2e_drain`,
`test_staged_shutdown_drill` encode the OLD in-app ladder shutdown model. With
shutdown moved to the isolated `eclipse-powerwatch` service, these no longer
describe the system. Coverage is replaced by T1-T8 unit + the T8 real-invocation
guard + the spec sec 10 IRL Phase-2 acceptance. (Flagged: this is a deliberate
shift from in-app drill tests to service-isolation + IRL acceptance.)

### T9 steps

- [ ] **S1 (additive, zero-risk first): relocate `PowerLogWriter`.** Move
  `PowerLogWriter = Callable[[str, float], None]` from `orchestrator.py:413` into
  `src/pi/power/types.py` (add to its `__all__`). Repoint importers:
  `hardware_manager.py:105-109` and `obdii/orchestrator/lifecycle.py`
  (`_createPowerLogWriter` type ref) to `from src.pi.power.types import PowerLogWriter`.
  Run `pytest tests/pi/ -m "not slow"` -> still green (pure move). Commit.
- [ ] **S2: rewire `hardware_manager.py`.** Remove the `PowerDownOrchestrator`/
  `ShutdownThresholds` import; ctor param `shutdownThresholds` + `self._shutdownThresholds`;
  `self._powerDownOrchestrator`; `self._powerDownTickThread` (+ its stop() join L378-380
  + its `_startComponents` spawn L575-588); `_initializePowerDownOrchestrator` (L419-473);
  `_powerDownTickLoop` (L638-710+); the L336 call; the `createHardwareManager` factory
  `shutdownThresholds` param/passthrough (L1133/1148). In `_initializeShutdownHandler`
  (L403-416) hardcode `suppressLegacyTriggers=True` per DECISION 1 (drop the
  `_shutdownThresholds`-derived `suppressLegacy`). App must still boot + collect.
- [ ] **S3: cut upstream ladder wiring in `obdii/orchestrator/lifecycle.py`.** Remove
  `_subscribeOrchestratorToUpsMonitor` (L2072-2175) + its call site (L1390) + any
  `shutdownThresholds` passthrough in `_initializeHardwareManager` (L1104). KEEP
  `_createPowerLogWriter` (data-collection) -- only repoint its `PowerLogWriter`
  type import (S1). This is the lifecycle.py trap the T10 cutover hit -- handle
  explicitly, do not guess.
- [ ] **S4: delete `src/pi/power/orchestrator.py`** (now only the ladder +
  `ShutdownThresholds` + `createShutdownThresholdsFromConfig` remain in it; the
  typedef was moved in S1). Grep `PowerDownOrchestrator|ShutdownThresholds|
  createShutdownThresholdsFromConfig` in `src/` -> zero non-comment hits.
- [ ] **S5: retire ladder-only config.** Delete the 5 `pi.power.shutdownThresholds.*`
  DEFAULTS (`validator.py:137-141`) + the `power.shutdownThresholds` block
  (`config.json:523-529`). KEEP `pi.power.power_monitor.*` (separate power_log gate).
  `python validate_config.py` semantics unchanged.
- [ ] **S6: delete pure-ladder tests** (~18): test_power_down_orchestrator,
  test_orchestrator_{vcell_thresholds,vcell_hysteresis,stage_behavior_wiring,
  state_file,battery_callback,boot_progress}, test_stage_latching,
  test_tick_internal_instrumentation, test_tick_gating_no_silent_bail,
  test_staged_shutdown_actually_fires, test_logshutdown_stage_fsync_and_error_propagation,
  test_drain_event_close_forensic_logging, test_ladder_vs_legacy_race,
  test_us216_retro_pre_sprint19_failure_mode, test_powersource_module_identity
  (regression -- ladder enum-identity; the ups_monitor self-aliasing guard STAYS,
  it now protects power_watch), test_power_down_tick_thread_health. Plus the 3
  drill suites per DECISION 2 (test_power_mgmt_lifecycle, test_power_mgmt_e2e_drain,
  test_staged_shutdown_drill).
- [ ] **S7: trim kept-component tests** (do NOT delete): test_shutdown_handler_legacy_suppress
  (rewrite for unconditional-suppress per DECISION 1), test_ups_monitor_degradation
  (drop ladder refs only), test_drain_forensics_logger (drain-forensics observer:
  pd_* journald columns now vestigial -- minimal trim/xfail-note, the tool stays).
- [ ] **S8: gate.** `pytest tests/pi/ -m "not slow" -q` green (app boots/collects,
  zero ladder ref); `grep -rn PowerDownOrchestrator src/` -> modhist comments only;
  the T8 real-invocation guard still green; `ruff check` on every touched file;
  `python validate_config.py` exit 0. Commit S2-S8 as the cutover.
- [ ] **S9 (leave, note only):** `deploy/drain-forensics.service:69` stale comment
  ("imports PowerDownOrchestrator") -> optional 1-line comment correction.

## Final verification (before declaring complete)
- [ ] `pytest tests/pi/ -m "not slow" -q` → green, no regressions.
- [ ] `pytest tests/test_config_validator.py -q` + `python validate_config.py` → green / exit 0.
- [ ] `ruff check` on all touched files → clean.
- [ ] `bash -n deploy/deploy-pi.sh && bash deploy/deploy-pi.sh --dry-run` → the power-watch step prints, no error.
- [ ] `grep -rn "PowerDownOrchestrator" src/` → no live references (modhist comments only).
- [ ] **Human/IRL gate (not code, post-deploy):** the spec §10 Phase-2 acceptance — on-battery → chi-srv-01 reachable? → sync/skip → bounded → graceful poweroff → Phase-1 auto-boot — run by CIO, Spool re-verifies read-only, with the Spool-tuned numbers (Task 7 Step 6) in place. Acceptance count CIO-ratified (mirror Phase-1's 3).

---

## Self-Review (completed by plan author)
- **Spec coverage:** §6.1 isolated systemd service → T6/T9; §6.2 sustained-on-battery trigger via reused detector → T6 (`UpsMonitor.registerSourceChangeCallback`); §6.3 bounded extensible pipeline + task contract → T1/T3; §6.4 sync state machine → T5; §6.5 typed durable producer-only record → T2; §6.6 hard bound (per-task+total+VCELL-floor) → T3/T4; §6.7 power-return abort → T4; §6.8 `systemctl poweroff` + Phase-1 wake → T4/T6; §8 delete legacy ladder → T9; §9 config + Spool-tune dependency → T7 (incl. the explicit follow-up step); §10 verification incl. real-invocation guard → T8 + Final. No gap.
- **Placeholder scan:** the T5 "wiring note" and the T9 "inventory-first" are NOT placeholders — they are the correct, concrete (grep commands + classification + escalation) way to plan a DI-bind and a 13-file high-blast-radius deletion; pre-guessing unread APIs/13 files would be the *worse* fake-precision failure (explicitly the T10-proven approach). Conservative-interim config values (T7) are real shipped values + a tracked tuning follow-up, not gaps.
- **Type consistency:** `OutcomeKind` (T1) used identically in T2/T3/T5; `PipelineTask` Protocol (T1) satisfied by `SyncWithServerTask` (T5) and consumed by `runPipeline` (T3); `PowerWatch` ctor kwargs (T4) match the `__main__` binding (T6); `writeOutcomeRecord(path, kind, *, detail, task)` signature consistent T2↔T5↔T8.
