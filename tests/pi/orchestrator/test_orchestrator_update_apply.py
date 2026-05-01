################################################################################
# File Name: test_orchestrator_update_apply.py
# Purpose/Description: Orchestrator <-> UpdateApplier wiring regression tests
#                      (US-248 / B-047 US-D). Verifies that lifecycle.
#                      _initializeUpdateApplier produces a non-None applier
#                      when pi.update.enabled=true AND that the runLoop
#                      cadence trigger fires correctly with the marker fast-path.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Orchestrator <-> UpdateApplier wiring tests (US-248).

Three categories:

1. **Lifecycle wiring** -- ``_initializeUpdateApplier`` retains the applier
   when ``pi.update.enabled=true``; leaves it None when disabled; soft-
   fails on construction error.
2. **Interval cadence + fast-path** -- ``_maybeTriggerUpdateApply`` short-
   circuits when no marker exists; gates on ``intervalMinutes`` since
   last attempt; never raises out of runLoop.
3. **Closure wiring** -- ``isDrivingFn`` / ``getPowerSourceFn`` /
   ``getLastObdActivitySecondsAgoFn`` closures all default to fail-OPEN
   so a missing component never perma-blocks updates.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.update.update_applier import ApplyOutcome, ApplyResult

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig(
    *,
    updateEnabled: bool = True,
    applyEnabled: bool = True,
    intervalMinutes: int = 60,
) -> dict[str, Any]:
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 3,
                "retryBackoffSeconds": [1, 2, 4, 8, 16],
            },
            "sync": {
                "enabled": True,
                "intervalSeconds": 60,
                "triggerOn": ["interval"],
            },
            "update": {
                "enabled": updateEnabled,
                "intervalMinutes": intervalMinutes,
                "markerFilePath": "/tmp/update-pending.json",
                "localVersionPath": "/tmp/.deploy-version-test",
                "applyEnabled": applyEnabled,
                "stagingPath": "/tmp/eclipse-obd-staging",
                "rollbackEnabled": True,
            },
        },
        "server": {},
    }


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    return ApplicationOrchestrator(config=config, simulate=True)


def _makeApplyResult(
    outcome: ApplyOutcome = ApplyOutcome.NO_MARKER,
) -> ApplyResult:
    return ApplyResult(
        outcome=outcome,
        targetVersion="V0.20.0",
        priorRef="prior123",
        rationale="test",
    )


# ================================================================================
# 1. Lifecycle wiring
# ================================================================================


class TestInitializeUpdateApplier:
    def test_enabledConfig_createsApplier(self) -> None:
        orch = _makeOrch(_baseConfig(updateEnabled=True))

        orch._initializeUpdateApplier()

        assert orch.updateApplier is not None

    def test_updateDisabled_leavesApplierNone(self) -> None:
        orch = _makeOrch(_baseConfig(updateEnabled=False))

        orch._initializeUpdateApplier()

        assert orch.updateApplier is None

    def test_constructionFailure_swallowedAsWarning(
        self, monkeypatch, caplog,
    ) -> None:
        """Boot must not crash if UpdateApplier constructor raises."""
        from src.pi.update import update_applier as ua_mod

        def _badCtor(*_a, **_kw):
            raise RuntimeError("ctor boom")

        monkeypatch.setattr(ua_mod, "UpdateApplier", _badCtor)
        orch = _makeOrch(_baseConfig(updateEnabled=True))

        import logging
        with caplog.at_level(logging.WARNING):
            orch._initializeUpdateApplier()

        assert orch.updateApplier is None
        assert any(
            "UpdateApplier initialization failed" in rec.getMessage()
            for rec in caplog.records
        )


# ================================================================================
# 2. Interval cadence + marker fast-path
# ================================================================================


class TestUpdateApplyCadence:
    def test_noApplier_isNoOp(self) -> None:
        """A None applier gates the trigger -- no crash."""
        orch = _makeOrch(_baseConfig(updateEnabled=False))
        orch._updateApplier = None

        fired = orch._maybeTriggerUpdateApply()

        assert fired is False

    def test_noMarker_skipsApplyCallEntirely(self) -> None:
        """The fast-path probe (markerExists) keeps the apply path cheap."""
        orch = _makeOrch(_baseConfig())
        orch._updateApplier = MagicMock()
        orch._updateApplier.markerExists.return_value = False

        fired = orch._maybeTriggerUpdateApply()

        assert fired is False
        orch._updateApplier.markerExists.assert_called_once()
        orch._updateApplier.apply.assert_not_called()

    def test_markerPresent_firstCall_triggersApply(self) -> None:
        """First runLoop pass with a marker on disk fires apply."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateApplier = MagicMock()
        orch._updateApplier.markerExists.return_value = True
        orch._updateApplier.apply.return_value = _makeApplyResult(
            ApplyOutcome.SUCCESS,
        )

        fired = orch._maybeTriggerUpdateApply()

        assert fired is True
        orch._updateApplier.apply.assert_called_once()

    def test_subInterval_doesNotTrigger(self) -> None:
        """Second tick within intervalMinutes is a no-op (cadence gate)."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateApplier = MagicMock()
        orch._updateApplier.markerExists.return_value = True
        orch._updateApplier.apply.return_value = _makeApplyResult()

        orch._maybeTriggerUpdateApply()
        fired = orch._maybeTriggerUpdateApply()

        assert fired is False
        # Only the first call invoked apply().
        assert orch._updateApplier.apply.call_count == 1

    def test_pastInterval_triggersAgain(self) -> None:
        """Once intervalMinutes elapsed, next tick fires again."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateApplier = MagicMock()
        orch._updateApplier.markerExists.return_value = True
        orch._updateApplier.apply.return_value = _makeApplyResult()

        orch._maybeTriggerUpdateApply()
        # Backdate so we cross the 60-minute window.
        orch._lastUpdateApplyTime = datetime.now() - timedelta(minutes=120)

        fired = orch._maybeTriggerUpdateApply()

        assert fired is True
        assert orch._updateApplier.apply.call_count == 2

    def test_applyCrash_swallowedCleanly(self) -> None:
        """An exception inside apply() must not crash runLoop."""
        orch = _makeOrch(_baseConfig())
        orch._updateApplier = MagicMock()
        orch._updateApplier.markerExists.return_value = True
        orch._updateApplier.apply.side_effect = RuntimeError("boom")

        # Must not raise.
        fired = orch._maybeTriggerUpdateApply()

        assert fired is False


# ================================================================================
# 3. Closure wiring (fail-open invariants)
# ================================================================================


class TestClosureWiring:
    """The closures the orchestrator hands the applier must default OPEN."""

    def _captureCtorKwargs(
        self, orch: ApplicationOrchestrator,
    ) -> dict[str, Any]:
        """Patch UpdateApplier ctor; run init; return captured kwargs."""
        from src.pi.update import update_applier as ua_mod
        captured: dict[str, Any] = {}

        def _captureCtor(_config, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        import unittest.mock as _mock
        with _mock.patch.object(
            ua_mod, "UpdateApplier", side_effect=_captureCtor,
        ):
            orch._initializeUpdateApplier()
        return captured

    def test_passesAllThreeClosures(self) -> None:
        orch = _makeOrch(_baseConfig())
        kwargs = self._captureCtorKwargs(orch)

        assert callable(kwargs.get("isDrivingFn"))
        assert callable(kwargs.get("getPowerSourceFn"))
        assert callable(kwargs.get("getLastObdActivitySecondsAgoFn"))

    def test_isDrivingFn_returnsFalse_whenNoDriveDetector(self) -> None:
        orch = _makeOrch(_baseConfig())
        orch._driveDetector = None
        kwargs = self._captureCtorKwargs(orch)

        assert kwargs["isDrivingFn"]() is False

    def test_getPowerSourceFn_returnsExternal_whenNoHardwareManager(
        self,
    ) -> None:
        orch = _makeOrch(_baseConfig())
        orch._hardwareManager = None
        kwargs = self._captureCtorKwargs(orch)

        assert kwargs["getPowerSourceFn"]() == "external"

    def test_getPowerSourceFn_returnsExternal_whenUpsMonitorMissing(
        self,
    ) -> None:
        orch = _makeOrch(_baseConfig())
        # Wire a hardware manager whose upsMonitor attr is None.
        hwManager = MagicMock()
        hwManager.upsMonitor = None
        orch._hardwareManager = hwManager
        kwargs = self._captureCtorKwargs(orch)

        assert kwargs["getPowerSourceFn"]() == "external"

    def test_getLastObdActivitySecondsAgoFn_returnsNone_whenNoDatabase(
        self,
    ) -> None:
        orch = _makeOrch(_baseConfig())
        orch._database = None
        kwargs = self._captureCtorKwargs(orch)

        assert kwargs["getLastObdActivitySecondsAgoFn"]() is None
