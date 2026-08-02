################################################################################
# File Name: test_sync_success_altitude_reanchor.py
# Purpose/Description: US-518 (WP-3, F-125) seam tests -- the derived-altitude
#   re-anchor fires on a SUCCESSFUL server sync and on nothing else.
#
#   A successful push to the companion service means the Pi reached the home
#   network, which means the car is home -- a verified "at home" reset. The
#   negative cases carry the weight here: a crashed push, a route-gated tick
#   that never left the Pi, and a gated-off trigger must all leave the
#   accumulator alone, because re-anchoring away from home is exactly the
#   fabricated altitude this whole work package exists to avoid.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-518 sync-success re-anchor seam.
# ================================================================================
################################################################################

"""US-518: the altitude re-anchor fires on sync-success, and only then."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.location.altitude_anchor import AltitudeAnchor
from pi.obdii.orchestrator.core import ApplicationOrchestrator

FAKE_HOME_ELEVATION_M = 137.5


def _baseConfig(
    *,
    triggerOn: list[str] | None = None,
    homeElevationM: Any = FAKE_HOME_ELEVATION_M,
) -> dict[str, Any]:
    """The sync-wiring config shape (tests/pi/orchestrator/test_sync_wiring.py)."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "location": {"home": {"elevationM": homeElevationM}},
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
                "triggerOn": triggerOn or ["interval", "drive_end"],
            },
        },
        "server": {},
    }


class _SpyAnchor:
    """Counts re-anchor calls without touching config."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls = 0
        self.raises = raises

    def onSyncSuccess(self) -> bool:
        self.calls += 1
        if self.raises:
            raise RuntimeError("anchor exploded")
        return True


@pytest.fixture
def stubApiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-us518")


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    return ApplicationOrchestrator(config=config, simulate=True)


def _orchWithSpy(
    config: dict[str, Any], *, raises: bool = False
) -> tuple[ApplicationOrchestrator, _SpyAnchor]:
    orch = _makeOrch(config)
    spy = _SpyAnchor(raises=raises)
    orch._altitudeAnchor = spy
    orch._syncClient = MagicMock()
    orch._syncClient.pushAllDeltas.return_value = []
    return orch, spy


# ================================================================================
# 1. Fires on a successful sync -- both trigger paths
# ================================================================================


class TestFiresOnSyncSuccess:
    def test_intervalSyncSuccess_reanchors(self, stubApiKey) -> None:
        """
        Given: an interval sync that completes past the route gate
        When:  the tick fires
        Then:  the derived altitude is re-anchored
        """
        orch, spy = _orchWithSpy(_baseConfig())

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True
        assert spy.calls == 1

    def test_driveEndSyncSuccess_reanchors(self, stubApiKey) -> None:
        """The drive-end flush is the sync most likely to happen in the driveway."""
        orch, spy = _orchWithSpy(_baseConfig(triggerOn=["drive_end"]))

        fired = orch.triggerDriveEndSync()

        assert fired is True
        assert spy.calls == 1

    def test_emptyPush_stillReanchors(self, stubApiKey) -> None:
        """
        Zero rows pushed is still a REACHED SERVER, which is the fact the
        re-anchor keys on -- "we are home", not "we had data".
        """
        orch, spy = _orchWithSpy(_baseConfig())
        orch._syncClient.pushAllDeltas.return_value = []

        orch._maybeTriggerIntervalSync()

        assert spy.calls == 1


# ================================================================================
# 2. Does NOT fire otherwise (AC2)
# ================================================================================


class TestDoesNotFireOtherwise:
    def test_intervalPushCrash_doesNotReanchor(self, stubApiKey) -> None:
        """A transport failure is not evidence the car is home."""
        orch, spy = _orchWithSpy(_baseConfig())
        orch._syncClient.pushAllDeltas.side_effect = RuntimeError("boom")

        fired = orch._maybeTriggerIntervalSync()

        assert fired is False
        assert spy.calls == 0

    def test_driveEndPushCrash_doesNotReanchor(self, stubApiKey) -> None:
        orch, spy = _orchWithSpy(_baseConfig(triggerOn=["drive_end"]))
        orch._syncClient.pushAllDeltas.side_effect = RuntimeError("boom")

        fired = orch.triggerDriveEndSync()

        assert fired is False
        assert spy.calls == 0

    def test_noRouteToServer_doesNotReanchor(self, stubApiKey) -> None:
        """
        THE ONE THAT MATTERS: the US-340 offline gate. Mid-drive, away from
        home, the tick bails before pushing. Re-anchoring there would reset the
        altitude to home elevation while the car is miles away -- the exact
        confident-wrong-number failure the honest-instrument rule forbids.
        """
        orch, spy = _orchWithSpy(_baseConfig())
        orch._syncClient.hasRouteToServer.return_value = False

        fired = orch._maybeTriggerIntervalSync()

        assert fired is False
        assert spy.calls == 0
        orch._syncClient.pushAllDeltas.assert_not_called()

    def test_subIntervalTick_doesNotReanchor(self, stubApiKey) -> None:
        """A gated no-op tick never reached the server."""
        orch, spy = _orchWithSpy(_baseConfig())

        orch._maybeTriggerIntervalSync()
        orch._maybeTriggerIntervalSync()

        assert spy.calls == 1

    def test_driveEndNotInTriggerOn_doesNotReanchor(self, stubApiKey) -> None:
        orch, spy = _orchWithSpy(_baseConfig(triggerOn=["interval"]))

        fired = orch.triggerDriveEndSync()

        assert fired is False
        assert spy.calls == 0

    def test_noSyncClient_doesNotReanchor(self) -> None:
        orch = _makeOrch(_baseConfig())
        spy = _SpyAnchor()
        orch._altitudeAnchor = spy
        orch._syncClient = None

        orch._maybeTriggerIntervalSync()
        orch.triggerDriveEndSync()

        assert spy.calls == 0


# ================================================================================
# 3. The re-anchor can never break capture (I-038 lesson)
# ================================================================================


class TestNeverBreaksSync:
    def test_anchorRaising_doesNotFailTheSync(self, stubApiKey) -> None:
        """
        Drift control is cosmetic; the sync is not. An exception out of the
        anchor must never turn a successful push into a reported failure.
        """
        orch, spy = _orchWithSpy(_baseConfig(), raises=True)

        fired = orch._maybeTriggerIntervalSync()

        assert fired is True
        assert spy.calls == 1

    def test_anchorRaisingOnDriveEnd_doesNotFailTheSync(self, stubApiKey) -> None:
        orch, spy = _orchWithSpy(
            _baseConfig(triggerOn=["drive_end"]), raises=True
        )

        fired = orch.triggerDriveEndSync()

        assert fired is True
        assert spy.calls == 1

    def test_syncOutcomeTileStillStamped(self, stubApiKey) -> None:
        """The US-480-a sync tile must not regress behind the new hook."""
        orch, _spy = _orchWithSpy(_baseConfig(), raises=True)

        orch._maybeTriggerIntervalSync()

        assert orch._lastSyncOkTsIso is not None


# ================================================================================
# 4. End-to-end -- the REAL anchor over the REAL config (two-correct-halves guard)
# ================================================================================


class TestRealAnchorEndToEnd:
    def test_realChain_syncSuccessResetsDriftedAltitude(self, stubApiKey) -> None:
        """
        Drives the REAL orchestrator seam -> REAL AltitudeAnchor -> REAL
        HomeLocationProvider over a REAL config shape. Both halves being
        individually correct while nothing connects them is the recurring
        failure this sprint (US-494/499/502/503/505/513), so the chain is
        pinned end-to-end rather than per-half.
        """
        orch = _makeOrch(_baseConfig())
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        anchor = orch._getAltitudeAnchor()
        assert isinstance(anchor, AltitudeAnchor)
        anchor.setDerivedAltitudeM(512.0)  # a drive's worth of drift

        orch._maybeTriggerIntervalSync()

        assert anchor.getAltitudeM() == pytest.approx(FAKE_HOME_ELEVATION_M)

    def test_realChain_unconfiguredHome_leavesAltitudeAlone(
        self, stubApiKey
    ) -> None:
        """
        The Pi's ACTUAL state today: deploy-pi.sh excludes .env, so
        PI_HOME_ELEVATION_M is unresolved on the box and the placeholder
        survives into the config. The re-anchor must degrade to a no-op, NOT
        reset the accumulator to zero.
        """
        orch = _makeOrch(_baseConfig(homeElevationM="${PI_HOME_ELEVATION_M}"))
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        anchor = orch._getAltitudeAnchor()
        anchor.setDerivedAltitudeM(512.0)

        orch._maybeTriggerIntervalSync()

        assert anchor.getAltitudeM() == pytest.approx(512.0)

    def test_anchorIsCachedAcrossSyncs(self, stubApiKey) -> None:
        """One accumulator per process -- a fresh one each tick would forget."""
        orch = _makeOrch(_baseConfig())
        orch._syncClient = MagicMock()
        orch._syncClient.pushAllDeltas.return_value = []

        first = orch._getAltitudeAnchor()
        orch._maybeTriggerIntervalSync()
        second = orch._getAltitudeAnchor()

        assert first is second
