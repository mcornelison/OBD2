################################################################################
# File Name: test_boot_state_emitter.py
# Purpose/Description: Tests for the F-103 boot-state emitter (honest-instrument
#   verdict logic): the US-494 CORE-readiness contract (Pi core/UI up, NOT
#   vehicle-connected), the non-gating informational eclipse-obd tier, the
#   dashboard-asset readiness gate, hard-cap degrade, atomic state write, and
#   C-5 states-dir provisioning.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# 2026-07-29    | Ralph (Rex)  | US-494 S1: readiness = Pi-core-up. eclipse-obd
#               |              | tier is informational/non-gating; dashboard
#               |              | assets join the gate; obdProbeFn absence is
#               |              | reported as not-probed, never as "starting".
# ================================================================================
################################################################################

"""Tests for ``pi.splash.boot_state_emitter``."""

import json

from pi.splash.boot_state_emitter import (
    CORE_SERVICES_DEFAULT,
    INFORMATIONAL_SERVICES_DEFAULT,
    OBD_ADAPTER_MISSING,
    OBD_ADAPTER_NO_SYNC,
    OBD_NOT_PROBED,
    OBD_STARTING,
    OBD_SYNCED_WITH_DATA,
    UI_ASSETS_MISSING,
    UI_ASSETS_PRESENT,
    BootStateEmitter,
    assessObdTier,
    buildEmitter,
    computeBootState,
    ensureStatesDir,
    main,
    runForever,
)

_CORE = ["eclipse-states-http", "eclipse-powerwatch", "boot-progress-finalize"]
_TS = "2026-06-29T12:00:00Z"


def _coreUp():
    """All three CORE services terminal-and-good (a normal Pi-core boot)."""
    return dict.fromkeys(_CORE, "active")


def _compute(**overrides):
    """computeBootState with the healthy-core-boot baseline, overridable."""
    kwargs = {
        "coreServiceStates": _coreUp(),
        "uiAssetsPresent": True,
        "elapsedSeconds": 3.0,
        "hardCapSeconds": 12.0,
        "coreServices": _CORE,
        "nowIso": _TS,
    }
    kwargs.update(overrides)
    return computeBootState(**kwargs)


# --- US-494 AC-1: the gate is Pi-core/UI-up, NOT vehicle-connected ------------


def test_coreServicesDefault_excludesEclipseObd_includesStatesHttp():
    """AC-1: the OBD tier is NOT a member of the handoff gate; the states server
    (which serves boot-state + the dashboard assets) is."""
    assert "eclipse-obd" not in CORE_SERVICES_DEFAULT
    assert "eclipse-states-http" in CORE_SERVICES_DEFAULT
    assert "eclipse-powerwatch" in CORE_SERVICES_DEFAULT
    # The tier is still SAMPLED -- just informationally.
    assert "eclipse-obd" in INFORMATIONAL_SERVICES_DEFAULT


def test_computeBootState_coreUpNoVehicle_isHealthyAndHandsOff():
    """AC-2 (the S1 bug): a bench boot with NO vehicle present must reach
    healthy so the splash yields to the dashboard."""
    state = _compute(obdTier=OBD_NOT_PROBED)

    assert state["healthy"] is True
    assert state["degraded"] is False
    assert state["degradedReason"] is None
    assert state["progress"] == 1.0


def test_computeBootState_obdTierNeverProbed_doesNotBlockHealthyPastHardCap():
    """The exact V0.29.19 regression: obdProbeFn defaulted to a permanent
    'starting', so past the 12 s cap the splash pinned at
    'eclipse-obd: not ready (starting)' until reboot. A never-probed tier must
    not degrade a core-up boot no matter how long it runs."""
    state = _compute(obdTier=OBD_STARTING, elapsedSeconds=60.0)

    assert state["healthy"] is True
    assert state["degraded"] is False
    assert state["degradedReason"] is None


def test_computeBootState_obdAdapterMissing_isNotDegraded():
    """No car on the bench is NORMAL, not a fault (F-7 alarm-fatigue guard).
    A T1 adapter-missing tier must not paint the boot amber."""
    state = _compute(obdTier=OBD_ADAPTER_MISSING)

    assert state["degraded"] is False
    assert state["healthy"] is True
    assert state["degradedReason"] is None


def test_computeBootState_obdAdapterNoSync_isNotDegraded():
    state = _compute(obdTier=OBD_ADAPTER_NO_SYNC)

    assert state["degraded"] is False
    assert state["healthy"] is True


def test_computeBootState_reportsObdTierAsItsOwnNonGatingField():
    """The tier stays VISIBLE for post-boot consumers -- it just does not gate.
    `services` carries systemctl states only (one vocabulary per field)."""
    state = _compute(
        obdTier=OBD_SYNCED_WITH_DATA,
        informationalServiceStates={"eclipse-obd": "active"},
    )

    assert state["obdTier"] == OBD_SYNCED_WITH_DATA
    assert state["services"]["eclipse-obd"] == "active"
    assert state["coreServices"] == _CORE


# --- AC-3: a genuinely-degraded CORE boot still holds the splash --------------


def test_computeBootState_coreServiceFailed_isDegradedWithServiceReason():
    states = _coreUp()
    states["eclipse-powerwatch"] = "failed"

    state = _compute(coreServiceStates=states)

    assert state["degraded"] is True
    assert state["healthy"] is False
    assert state["degradedReason"] == "eclipse-powerwatch: failed to start"


def test_computeBootState_statesHttpFailed_isDegraded():
    """The states server IS core -- without it the dashboard has no data source."""
    states = _coreUp()
    states["eclipse-states-http"] = "failed"

    state = _compute(coreServiceStates=states)

    assert state["degraded"] is True
    assert state["degradedReason"] == "eclipse-states-http: failed to start"


def test_computeBootState_coreStillActivating_isNeitherHealthyNorDegraded():
    states = _coreUp()
    states["eclipse-powerwatch"] = "activating"

    state = _compute(coreServiceStates=states, elapsedSeconds=2.0)

    assert state["healthy"] is False
    assert state["degraded"] is False
    assert state["progress"] < 1.0


def test_computeBootState_pastHardCapCoreNotReady_degradesNamingTheCoreService():
    """Hard-cap degrade survives -- but its reason can only ever name a CORE
    component, never the informational OBD tier."""
    states = _coreUp()
    states["eclipse-powerwatch"] = "activating"

    state = _compute(
        coreServiceStates=states, obdTier=OBD_STARTING, elapsedSeconds=12.5
    )

    assert state["degraded"] is True
    assert state["degradedReason"] == "eclipse-powerwatch: not ready (activating)"
    assert "eclipse-obd" not in state["degradedReason"]


# --- AC-1: "dashboard assets present" is part of UI readiness ----------------


def test_computeBootState_dashboardAssetsMissing_isDegradedNotHealthy():
    """A-16: handing off to a dashboard whose assets were never installed is the
    blank-screen bug. Hold the splash and SAY so, rather than yield to nothing."""
    state = _compute(uiAssetsPresent=False)

    assert state["healthy"] is False
    assert state["degraded"] is True
    assert "dashboard assets" in state["degradedReason"]
    assert state["uiAssets"] == UI_ASSETS_MISSING


def test_computeBootState_dashboardAssetsPresent_reportedInPayload():
    state = _compute(uiAssetsPresent=True)

    assert state["uiAssets"] == UI_ASSETS_PRESENT


def test_computeBootState_failedCoreServiceOutranksMissingAssets():
    """One-line degradedReason discipline: the more fundamental fault wins."""
    states = _coreUp()
    states["eclipse-powerwatch"] = "failed"

    state = _compute(coreServiceStates=states, uiAssetsPresent=False)

    assert state["degradedReason"] == "eclipse-powerwatch: failed to start"


# --- eclipse-obd tier probe (retained: still assessed, informationally) ------


def test_assessObdTier_transientNoSync_retriesOnceThenSettles():
    """ISO 9141-2 K-line slow-init: a T2 transient must retry once before the
    verdict settles (Spool S-1 retry-once)."""
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


# --- states-dir provisioning + atomic write (C-5, unchanged) ------------------


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
        coreServices=_CORE,
        hardCapSeconds=12.0,
        serviceQueryFn=lambda name: "active",
        obdProbeFn=lambda: OBD_SYNCED_WITH_DATA,
        uiAssetProbeFn=lambda: True,
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
        coreServices=_CORE,
        serviceQueryFn=lambda name: "active",
        obdProbeFn=lambda: OBD_SYNCED_WITH_DATA,
        uiAssetProbeFn=lambda: True,
        elapsedFn=lambda: 3.0,
        nowIsoFn=lambda: _TS,
    )
    sleeps = []

    runForever(emitter, pollSeconds=0.5, sleepFn=sleeps.append, stopAfter=3)

    # 3 emissions, sleeping only BETWEEN them (no trailing sleep) -> 2 sleeps.
    assert len(sleeps) == 2
    assert all(s == 0.5 for s in sleeps)
    assert (statesDir / "boot-state").exists()


# --- the WIRING the systemd unit actually exercises (the S1 root cause) -------


def test_emitter_noObdProbeInjected_reportsNotProbedAndStillReachesHealthy(tmp_path):
    """ROOT CAUSE GUARD. eclipse-boot-state.service constructs the emitter with
    NO obdProbeFn. That absence must (a) be reported as `not-probed` -- an
    un-taken reading, never the confident claim "starting" -- and (b) not stop a
    core-up boot from reaching healthy, even far past the hard cap."""
    emitter = BootStateEmitter(
        statesDir=str(tmp_path / "states"),
        coreServices=_CORE,
        serviceQueryFn=lambda name: "active",
        uiAssetProbeFn=lambda: True,
        elapsedFn=lambda: 60.0,
        nowIsoFn=lambda: _TS,
    )

    state = emitter.runOnce()

    assert state["obdTier"] == OBD_NOT_PROBED
    assert state["healthy"] is True
    assert state["degraded"] is False


def test_emitter_uiAssetProbe_readsTheRealAssetPath(tmp_path):
    """Perturb the SOURCE, not the value: move the asset file on disk and the
    verdict must follow. Proves the probe reads the path rather than a constant."""
    assetPath = tmp_path / "dashboard" / "dashboard.html"
    assetPath.parent.mkdir(parents=True)

    def makeEmitter():
        return BootStateEmitter(
            statesDir=str(tmp_path / "states"),
            coreServices=_CORE,
            serviceQueryFn=lambda name: "active",
            uiAssetPath=str(assetPath),
            elapsedFn=lambda: 3.0,
            nowIsoFn=lambda: _TS,
        )

    missing = makeEmitter().runOnce()
    assetPath.write_text("<html></html>", encoding="utf-8")
    present = makeEmitter().runOnce()

    assert missing["uiAssets"] == UI_ASSETS_MISSING
    assert missing["healthy"] is False
    assert present["uiAssets"] == UI_ASSETS_PRESENT
    assert present["healthy"] is True


def test_buildEmitter_gateExcludesTheObdTier(tmp_path):
    """The unit's entry point must build an emitter whose GATE is core-only.
    Asserted on the object main() actually constructs, not on a re-spelling."""
    emitter = buildEmitter(
        statesDir=str(tmp_path / "states"),
        hardCapSeconds=12.0,
        uiAssetPath=str(tmp_path / "dashboard.html"),
    )

    assert "eclipse-obd" not in emitter.coreServices
    assert emitter.coreServices == CORE_SERVICES_DEFAULT


def test_main_wiresTheCoreOnlyGate(tmp_path, monkeypatch):
    """End of the wiring chain: `main` (= the systemd ExecStart) hands
    runForever an emitter with the core-only gate and a real asset probe."""
    captured = {}

    def fakeRunForever(emitter, pollSeconds, **kwargs):
        captured["emitter"] = emitter
        captured["pollSeconds"] = pollSeconds

    monkeypatch.setattr(
        "pi.splash.boot_state_emitter.runForever", fakeRunForever
    )

    rc = main(
        [
            "--states-dir",
            str(tmp_path / "states"),
            "--ui-asset-path",
            str(tmp_path / "dashboard.html"),
        ]
    )

    assert rc == 0
    assert "eclipse-obd" not in captured["emitter"].coreServices
    assert captured["pollSeconds"] == 0.5
