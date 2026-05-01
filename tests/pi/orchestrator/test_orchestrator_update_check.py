################################################################################
# File Name: test_orchestrator_update_check.py
# Purpose/Description: Orchestrator <-> UpdateChecker wiring regression tests
#                      (US-247 / B-047 US-C). Verifies that lifecycle.
#                      _initializeUpdateChecker produces a non-None checker
#                      when pi.update.enabled=true AND that the runLoop
#                      interval trigger fires at the configured cadence,
#                      gated on drive_state.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Orchestrator <-> UpdateChecker wiring tests (US-247).

Three categories:

1. **Lifecycle wiring** -- ``_initializeUpdateChecker`` retains the checker
   when ``pi.update.enabled=true``; leaves it None when disabled.
2. **Interval cadence** -- ``_maybeTriggerUpdateCheck`` gates on
   ``intervalMinutes`` since last attempt.  The first call fires; sub-
   interval calls return False.  An exception in the underlying check
   never propagates out of runLoop.
3. **Drive-state gating** -- with ``isDriving()`` True, the trigger fires
   the checker but the checker self-skips with SKIPPED_DRIVING; with
   isDriving False, a normal check runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.update.update_checker import CheckOutcome, CheckResult

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig(
    *,
    updateEnabled: bool = True,
    intervalMinutes: int = 60,
    companionEnabled: bool = True,
) -> dict[str, Any]:
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "companionService": {
                "enabled": companionEnabled,
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
            },
        },
        "server": {},
    }


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-update")


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    return ApplicationOrchestrator(config=config, simulate=True)


def _makeCheckResult(
    outcome: CheckOutcome = CheckOutcome.UP_TO_DATE,
) -> CheckResult:
    return CheckResult(
        outcome=outcome,
        localVersion="V0.19.0",
        serverVersion="V0.19.0",
        markerPath=None,
        rationale="test",
    )


# ================================================================================
# 1. Lifecycle wiring
# ================================================================================


class TestInitializeUpdateChecker:
    def test_enabledConfig_createsChecker(self, stubApiKey) -> None:
        orch = _makeOrch(_baseConfig(updateEnabled=True))

        orch._initializeUpdateChecker()

        assert orch.updateChecker is not None

    def test_updateDisabled_leavesCheckerNone(self) -> None:
        orch = _makeOrch(_baseConfig(updateEnabled=False))

        orch._initializeUpdateChecker()

        assert orch.updateChecker is None

    def test_constructionFailure_swallowedAsWarning(
        self, monkeypatch, caplog
    ) -> None:
        """Boot must not crash if UpdateChecker constructor raises."""
        from src.pi.update import update_checker as uc_mod

        def _badCtor(*_a, **_kw):
            raise RuntimeError("ctor boom")

        monkeypatch.setattr(uc_mod, "UpdateChecker", _badCtor)
        orch = _makeOrch(_baseConfig(updateEnabled=True))

        import logging
        with caplog.at_level(logging.WARNING):
            orch._initializeUpdateChecker()

        assert orch.updateChecker is None
        assert any(
            "UpdateChecker initialization failed" in rec.getMessage()
            for rec in caplog.records
        )


# ================================================================================
# 2. Interval cadence
# ================================================================================


class TestUpdateCheckCadence:
    def test_firstCall_triggersCheck(self, stubApiKey) -> None:
        """First runLoop pass calls the checker once."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateChecker = MagicMock()
        orch._updateChecker.check_for_updates.return_value = _makeCheckResult()

        fired = orch._maybeTriggerUpdateCheck()

        assert fired is True
        assert orch._updateChecker.check_for_updates.call_count == 1

    def test_subInterval_doesNotTrigger(self, stubApiKey) -> None:
        """Second call within intervalMinutes is a no-op."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateChecker = MagicMock()
        orch._updateChecker.check_for_updates.return_value = _makeCheckResult()

        orch._maybeTriggerUpdateCheck()
        fired = orch._maybeTriggerUpdateCheck()

        assert fired is False
        assert orch._updateChecker.check_for_updates.call_count == 1

    def test_pastInterval_triggersAgain(self, stubApiKey) -> None:
        """Once intervalMinutes has elapsed, the next tick fires again."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateChecker = MagicMock()
        orch._updateChecker.check_for_updates.return_value = _makeCheckResult()

        orch._maybeTriggerUpdateCheck()
        # Backdate so we cross the 60-minute window.
        orch._lastUpdateCheckTime = datetime.now() - timedelta(minutes=120)

        fired = orch._maybeTriggerUpdateCheck()

        assert fired is True
        assert orch._updateChecker.check_for_updates.call_count == 2

    def test_noUpdateChecker_isNoOp(self) -> None:
        """A None updateChecker gates the trigger -- no crash."""
        orch = _makeOrch(_baseConfig(updateEnabled=False))
        orch._updateChecker = None

        fired = orch._maybeTriggerUpdateCheck()

        assert fired is False

    def test_checkCrash_swallowedCleanly(self, stubApiKey) -> None:
        """An exception inside check_for_updates must not crash runLoop."""
        orch = _makeOrch(_baseConfig(intervalMinutes=60))
        orch._updateChecker = MagicMock()
        orch._updateChecker.check_for_updates.side_effect = RuntimeError("boom")

        fired = orch._maybeTriggerUpdateCheck()  # must not raise

        assert fired is False


# ================================================================================
# 3. Drive-state gating
# ================================================================================


class TestDriveStateGating:
    """The orchestrator forwards the live drive state into the checker."""

    def test_passesIsDrivingFn_pointingAtDriveDetector(self, stubApiKey) -> None:
        """
        The checker is constructed with an isDrivingFn that delegates to
        the live drive detector.  We validate this by capturing the kwarg
        the orchestrator passed at construction time.
        """
        orch = _makeOrch(_baseConfig())
        captured: dict[str, Any] = {}

        from src.pi.update import update_checker as uc_mod

        def _captureCtor(config, **kwargs):
            captured.update(kwargs)
            mock = MagicMock()
            mock.check_for_updates.return_value = _makeCheckResult()
            return mock

        import unittest.mock as _mock
        with _mock.patch.object(uc_mod, "UpdateChecker", side_effect=_captureCtor):
            orch._initializeUpdateChecker()

        assert "isDrivingFn" in captured
        assert callable(captured["isDrivingFn"])

    def test_isDrivingFn_returnsFalse_whenNoDriveDetector(
        self, stubApiKey
    ) -> None:
        """
        With no drive detector wired (early boot), the isDrivingFn the
        orchestrator hands the checker must default to 'not driving' so
        the safety gate is OPEN by default -- a missing detector cannot
        be interpreted as 'drive in progress' (that would prevent ALL
        update checks indefinitely).
        """
        orch = _makeOrch(_baseConfig())
        orch._driveDetector = None
        captured: dict[str, Any] = {}

        from src.pi.update import update_checker as uc_mod

        def _captureCtor(config, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        import unittest.mock as _mock
        with _mock.patch.object(uc_mod, "UpdateChecker", side_effect=_captureCtor):
            orch._initializeUpdateChecker()

        fn = captured["isDrivingFn"]
        assert fn() is False

    def test_isDrivingFn_followsDriveDetector(self, stubApiKey) -> None:
        """Wired through to driveDetector.isDriving() when detector exists."""
        orch = _makeOrch(_baseConfig())
        captured: dict[str, Any] = {}

        from src.pi.update import update_checker as uc_mod

        def _captureCtor(config, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        import unittest.mock as _mock
        with _mock.patch.object(uc_mod, "UpdateChecker", side_effect=_captureCtor):
            orch._initializeUpdateChecker()

        fn = captured["isDrivingFn"]
        # Wire a live mock detector AFTER init (lifecycle-late wiring case).
        detector = MagicMock()
        detector.isDriving.return_value = True
        orch._driveDetector = detector
        assert fn() is True
        detector.isDriving.return_value = False
        assert fn() is False
