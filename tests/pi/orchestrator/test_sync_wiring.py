################################################################################
# File Name: test_sync_wiring.py
# Purpose/Description: Orchestrator sync wiring regression tests (US-226).
#                      Verifies that lifecycle._initializeSyncClient produces
#                      a non-None client when pi.sync.enabled=true AND that
#                      the interval trigger in ApplicationOrchestrator fires
#                      at the expected cadence.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Orchestrator <-> SyncClient wiring tests.

Three categories:

1. **Lifecycle wiring** -- `_initializeSyncClient` creates and retains
   the client when `pi.sync.enabled=true` + API key present.  When
   enabled=false or the key is missing, the client stays None and
   the rest of the orchestrator boots cleanly.
2. **Interval cadence** -- `_maybeTriggerIntervalSync` gates on
   `intervalSeconds` elapsed since the last attempt.  The first call
   fires (flush-on-boot); subsequent sub-interval calls return False.
3. **Drive-end trigger** -- `triggerDriveEndSync` fires only when
   ``'drive_end'`` is in ``pi.sync.triggerOn``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.sync.client import PushResult, PushStatus

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig(
    *,
    syncEnabled: bool = True,
    companionEnabled: bool = True,
    intervalSeconds: int = 60,
    triggerOn: list[str] | None = None,
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
                "enabled": syncEnabled,
                "intervalSeconds": intervalSeconds,
                "triggerOn": triggerOn or ["interval", "drive_end"],
            },
        },
        "server": {},
    }


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-wiring")


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    # simulate=True avoids any real OBD connection being attempted during
    # construction -- this test targets the sync plumbing, not the full
    # init chain, so we only exercise _initializeSyncClient directly.
    return ApplicationOrchestrator(config=config, simulate=True)


# ================================================================================
# 1. Lifecycle wiring
# ================================================================================


class TestInitializeSyncClient:
    def test_enabledConfig_createsSyncClient(self, stubApiKey) -> None:
        orch = _makeOrch(_baseConfig(syncEnabled=True))

        orch._initializeSyncClient()

        assert orch.syncClient is not None
        assert orch.syncClient.isEnabled is True

    def test_syncDisabled_leavesClientNone(self) -> None:
        orch = _makeOrch(_baseConfig(syncEnabled=False))

        orch._initializeSyncClient()

        assert orch.syncClient is None

    def test_missingApiKey_swallowedAsWarning(
        self, monkeypatch, caplog
    ) -> None:
        """With sync enabled but the API key env unset, boot must not crash."""
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        orch = _makeOrch(_baseConfig(syncEnabled=True))

        import logging
        with caplog.at_level(logging.WARNING):
            orch._initializeSyncClient()

        assert orch.syncClient is None
        assert any(
            "SyncClient initialization failed" in rec.getMessage()
            for rec in caplog.records
        )

    def test_companionDisabled_clientConstructedButInactive(
        self, monkeypatch
    ) -> None:
        """A disabled companion service is benign: client exists but isEnabled=False."""
        monkeypatch.delenv("COMPANION_API_KEY", raising=False)
        orch = _makeOrch(
            _baseConfig(syncEnabled=True, companionEnabled=False),
        )

        orch._initializeSyncClient()

        assert orch.syncClient is not None
        assert orch.syncClient.isEnabled is False


# ================================================================================
# 2. Interval cadence
# ================================================================================


class TestIntervalCadence:
    def test_firstCall_triggersFlush(self, stubApiKey) -> None:
        """Boot-time flush: first runLoop pass pushes any pending rows."""
        orch = _makeOrch(_baseConfig(intervalSeconds=60))
        orch._initializeSyncClient()
        # Swap the real client for a mock so we can assert without HTTP.
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True
        assert orch._syncClient.pushAllDeltas.call_count == 1

    def test_subInterval_doesNotTrigger(self, stubApiKey) -> None:
        """Second call within intervalSeconds is a no-op."""
        orch = _makeOrch(_baseConfig(intervalSeconds=60))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        orch._maybeTriggerIntervalSync()
        fired = orch._maybeTriggerIntervalSync()

        assert fired is False
        assert orch._syncClient.pushAllDeltas.call_count == 1

    def test_pastInterval_triggersAgain(self, stubApiKey) -> None:
        """Once intervalSeconds has elapsed, a tick fires again."""
        orch = _makeOrch(_baseConfig(intervalSeconds=60))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        orch._maybeTriggerIntervalSync()
        # Backdate the last attempt so the next call crosses the interval.
        orch._lastSyncAttemptTime = datetime.now() - timedelta(seconds=120)

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True
        assert orch._syncClient.pushAllDeltas.call_count == 2

    def test_noSyncClient_isNoOp(self) -> None:
        """A None syncClient gates the trigger cleanly -- no crash."""
        orch = _makeOrch(_baseConfig(syncEnabled=False))
        orch._syncClient = None

        fired = orch._maybeTriggerIntervalSync()

        assert fired is False

    def test_intervalMissingFromTriggerOn_isNoOp(self, stubApiKey) -> None:
        """With only drive_end configured, interval trigger never fires."""
        orch = _makeOrch(
            _baseConfig(triggerOn=["drive_end"]),
        )
        orch._syncClient = MagicMock()

        fired = orch._maybeTriggerIntervalSync()

        assert fired is False
        orch._syncClient.pushAllDeltas.assert_not_called()

    def test_pushCrash_swallowedCleanly(self, stubApiKey) -> None:
        """Transport error must not crash runLoop."""
        orch = _makeOrch(_baseConfig(intervalSeconds=60))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.side_effect = RuntimeError("boom")

        # Should not raise
        fired = orch._maybeTriggerIntervalSync()

        assert fired is False

    def test_intervalIndependentOfDriveEnd(self, stubApiKey) -> None:
        """Invariant: interval fires even when drive_end trigger not in list."""
        orch = _makeOrch(
            _baseConfig(triggerOn=["interval"]),
        )
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True


# ================================================================================
# 3. Drive-end trigger
# ================================================================================


class TestDriveEndTrigger:
    def test_driveEndInTriggerOn_fires(self, stubApiKey) -> None:
        orch = _makeOrch(_baseConfig(triggerOn=["drive_end"]))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        fired = orch.triggerDriveEndSync()

        assert fired is True
        orch._syncClient.pushAllDeltas.assert_called_once()

    def test_driveEndNotInTriggerOn_isNoOp(self, stubApiKey) -> None:
        orch = _makeOrch(_baseConfig(triggerOn=["interval"]))
        orch._syncClient = MagicMock()

        fired = orch.triggerDriveEndSync()

        assert fired is False
        orch._syncClient.pushAllDeltas.assert_not_called()

    def test_driveEndResetsIntervalCadence(self, stubApiKey) -> None:
        """After drive-end fires, the interval tick should wait intervalSeconds."""
        orch = _makeOrch(
            _baseConfig(triggerOn=["interval", "drive_end"], intervalSeconds=60),
        )
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        # Drive ends, fires the trigger -> _lastSyncAttemptTime is set.
        orch.triggerDriveEndSync()

        # Immediately after, interval tick should NOT double-fire.
        fired = orch._maybeTriggerIntervalSync()

        assert fired is False
        assert orch._syncClient.pushAllDeltas.call_count == 1

    def test_noSyncClient_isNoOp(self) -> None:
        orch = _makeOrch(_baseConfig(syncEnabled=False))
        orch._syncClient = None

        fired = orch.triggerDriveEndSync()

        assert fired is False

    def test_pushCrash_swallowedCleanly(self, stubApiKey) -> None:
        orch = _makeOrch(_baseConfig(triggerOn=["drive_end"]))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.side_effect = RuntimeError("boom")

        fired = orch.triggerDriveEndSync()

        assert fired is False


# ================================================================================
# 4. Row-count logging path (uses real PushResult objects)
# ================================================================================


class TestLoggingAggregation:
    def test_rowsPushedLogged_afterOkResults(self, stubApiKey, caplog) -> None:
        orch = _makeOrch(_baseConfig(intervalSeconds=60))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = [
            PushResult(
                tableName="realtime_data",
                rowsPushed=42,
                batchId="chi-eclipse-01-x",
                elapsed=0.1,
                status=PushStatus.OK,
            ),
            PushResult(
                tableName="statistics",
                rowsPushed=0,
                batchId="",
                elapsed=0.01,
                status=PushStatus.EMPTY,
            ),
        ]

        import logging
        with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
            orch._maybeTriggerIntervalSync()

        assert any(
            "rowsPushed=42" in rec.getMessage()
            for rec in caplog.records
        )
