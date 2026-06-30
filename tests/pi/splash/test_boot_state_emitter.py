################################################################################
# File Name: test_boot_state_emitter.py
# Purpose/Description: Tests for the F-103 boot-state emitter (honest-instrument
#   verdict logic): 3-tier eclipse-obd health, alarm-fatigue guard, retry-once,
#   hard-cap degrade, atomic state write, and C-5 states-dir provisioning.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# ================================================================================
################################################################################

"""Tests for ``pi.splash.boot_state_emitter``."""

import json

from pi.splash.boot_state_emitter import (
    OBD_ADAPTER_MISSING,
    OBD_ADAPTER_NO_SYNC,
    OBD_STARTING,
    OBD_SYNCED_NO_DATA,
    OBD_SYNCED_WITH_DATA,
    BootStateEmitter,
    assessObdTier,
    computeBootState,
    ensureStatesDir,
    runForever,
)

_CRIT = ["eclipse-powerwatch", "eclipse-obd", "boot-progress-finalize"]
_TS = "2026-06-29T12:00:00Z"


def _healthyServices():
    return {"eclipse-powerwatch": "active", "boot-progress-finalize": "active"}


def test_computeBootState_allActiveSyncedWithData_isHealthyNotDegraded():
    state = computeBootState(
        _healthyServices(), OBD_SYNCED_WITH_DATA, 3.0, 12.0, _CRIT, _TS
    )
    assert state["healthy"] is True
    assert state["degraded"] is False
    assert state["degradedReason"] is None
    assert state["progress"] == 1.0
    assert state["services"]["eclipse-obd"] == OBD_SYNCED_WITH_DATA


def test_computeBootState_engineOffSyncedNoData_isHealthyNotDegraded():
    """Alarm-fatigue guard (Spool S-1 / F-7): engine-off ECU silence (T3 fail)
    is legitimate -- must NOT flip degraded."""
    state = computeBootState(
        _healthyServices(), OBD_SYNCED_NO_DATA, 3.0, 12.0, _CRIT, _TS
    )
    assert state["degraded"] is False
    assert state["healthy"] is True
    assert state["services"]["eclipse-obd"] == OBD_SYNCED_NO_DATA


def test_computeBootState_adapterMissing_isDegradedWithT1Reason():
    state = computeBootState(
        _healthyServices(), OBD_ADAPTER_MISSING, 3.0, 12.0, _CRIT, _TS
    )
    assert state["degraded"] is True
    assert state["healthy"] is False
    assert state["degradedReason"] == "OBD adapter not detected"


def test_computeBootState_adapterNoSync_isDegradedWithT2Reason():
    state = computeBootState(
        _healthyServices(), OBD_ADAPTER_NO_SYNC, 3.0, 12.0, _CRIT, _TS
    )
    assert state["degraded"] is True
    assert state["degradedReason"] == "OBD adapter not responding"


def test_computeBootState_criticalServiceFailed_isDegradedWithServiceReason():
    services = {"eclipse-powerwatch": "failed", "boot-progress-finalize": "active"}
    state = computeBootState(services, OBD_SYNCED_WITH_DATA, 3.0, 12.0, _CRIT, _TS)
    assert state["degraded"] is True
    assert state["degradedReason"] == "eclipse-powerwatch: failed to start"


def test_computeBootState_starting_isNeitherHealthyNorDegraded():
    services = {"eclipse-powerwatch": "activating", "boot-progress-finalize": "active"}
    state = computeBootState(services, OBD_STARTING, 2.0, 12.0, _CRIT, _TS)
    assert state["healthy"] is False
    assert state["degraded"] is False
    assert state["progress"] < 1.0


def test_computeBootState_pastHardCapNotHealthy_degradesOnTimeout():
    services = {"eclipse-powerwatch": "activating", "boot-progress-finalize": "active"}
    state = computeBootState(services, OBD_STARTING, 12.5, 12.0, _CRIT, _TS)
    assert state["degraded"] is True
    assert state["degradedReason"] is not None


def test_assessObdTier_transientNoSync_retriesOnceThenSettles():
    """ISO 9141-2 K-line slow-init: a T2 transient must retry once before the
    verdict flips (Spool S-1 retry-once)."""
    results = iter([OBD_ADAPTER_NO_SYNC, OBD_SYNCED_WITH_DATA])
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return next(results)

    final = assessObdTier(probe)

    assert final == OBD_SYNCED_WITH_DATA
    assert calls["n"] == 2


def test_assessObdTier_t1FailNotRetried():
    """T1 (adapter physically missing) is NOT a slow-init transient -- no retry."""
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return OBD_ADAPTER_MISSING

    final = assessObdTier(probe)

    assert final == OBD_ADAPTER_MISSING
    assert calls["n"] == 1


def test_ensureStatesDir_createsNestedDir(tmp_path):
    target = tmp_path / "run" / "eclipse-obd" / "states"
    ensureStatesDir(str(target))
    assert target.is_dir()
    # idempotent
    ensureStatesDir(str(target))
    assert target.is_dir()


def test_emitter_runOnce_writesBootStateJson(tmp_path):
    statesDir = tmp_path / "states"

    emitter = BootStateEmitter(
        statesDir=str(statesDir),
        criticalServices=_CRIT,
        hardCapSeconds=12.0,
        serviceQueryFn=lambda name: "active",
        obdProbeFn=lambda: OBD_SYNCED_WITH_DATA,
        elapsedFn=lambda: 3.0,
        nowIsoFn=lambda: _TS,
    )

    state = emitter.runOnce()

    written = json.loads((statesDir / "boot-state").read_text(encoding="utf-8"))
    assert written == state
    assert written["healthy"] is True
    assert written["degraded"] is False


def test_runForever_loopsStopAfterTimes_sleepingBetween(tmp_path):
    statesDir = tmp_path / "states"
    emitter = BootStateEmitter(
        statesDir=str(statesDir),
        criticalServices=_CRIT,
        serviceQueryFn=lambda name: "active",
        obdProbeFn=lambda: OBD_SYNCED_WITH_DATA,
        elapsedFn=lambda: 3.0,
        nowIsoFn=lambda: _TS,
    )
    sleeps = []

    runForever(
        emitter,
        pollSeconds=0.5,
        sleepFn=sleeps.append,
        stopAfter=3,
    )

    # 3 emissions, sleeping only BETWEEN them (no trailing sleep) -> 2 sleeps.
    assert len(sleeps) == 2
    assert all(s == 0.5 for s in sleeps)
    assert (statesDir / "boot-state").exists()
