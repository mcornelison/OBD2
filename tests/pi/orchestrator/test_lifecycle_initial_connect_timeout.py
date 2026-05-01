################################################################################
# File Name: test_lifecycle_initial_connect_timeout.py
# Purpose/Description: US-244 / TD-036 -- _initializeConnection wall-clock
#                      timeout + non-blocking runLoop entry on initial connect
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-244) | Initial: pin _initializeConnection wall-clock
#                              | bound + PENDING-state contract.  3 classes:
#                              | TestInitialConnectTimeout (4 tests),
#                              | TestRunLoopToleratesPendingConnection (2),
#                              | TestConstructionFailureStillFatal (1).
# ================================================================================
################################################################################

"""US-244 / TD-036: lifecycle wiring tests for non-blocking initial OBD connect.

Sprint 18 post-deploy 2026-04-27 surfaced a silent gap: when the Pi cold-booted
with the engine off (adapter responds, ECU silent), ``_initializeConnection``
blocked indefinitely in the connect retry loop, ``runLoop`` never entered, and
US-226 interval-based sync never fired.  US-244 caps the initial connect with
a wall-clock timeout (``pi.obdii.orchestrator.initialConnectTimeoutSec``,
default 30s) and converts connect-failure from a startup-fatal raise into a
warning + return.  ``runLoop`` then tolerates the not-yet-connected (PENDING)
state and the existing US-211 reconnect path picks up late-arriving readiness.

Tests pin three contracts:

1. ``TestInitialConnectTimeout`` -- wall-clock cap fires regardless of how
   ``connect()`` would otherwise behave (block, fail, or succeed).
2. ``TestRunLoopToleratesPendingConnection`` -- ``runLoop`` entry succeeds with
   an unconnected connection, and US-226 interval sync fires anyway.
3. ``TestConstructionFailureStillFatal`` -- module/factory-level failures
   (ImportError surrogate) are still loud at startup; only retry exhaustion is
   downgraded to WARN.

Mocks are at the ``createConnectionFromConfig`` factory boundary (the lifecycle
imports it lazily inside ``_initializeConnection``) so the real
``ApplicationOrchestrator`` class wiring is exercised end-to-end.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.obdii.orchestrator.types import ComponentInitializationError

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig(
    *,
    initialConnectTimeoutSec: float = 0.5,
) -> dict[str, Any]:
    """Tier-aware config that drives the live (simulate=False) connect path."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "bluetooth": {
                "macAddress": "00:04:3E:85:0D:FB",
                "retryDelays": [0],
                "maxRetries": 0,
            },
            "obdii": {
                "orchestrator": {
                    "initialConnectTimeoutSec": initialConnectTimeoutSec,
                },
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    # simulate=False so _initializeConnection takes the real ObdConnection
    # path (which is what the wall-clock cap is for).  The
    # createConnectionFromConfig import inside _initializeConnection is the
    # mock seam.
    return ApplicationOrchestrator(config=config, simulate=False)


# ================================================================================
# 1. Wall-clock cap on initial connect
# ================================================================================


class TestInitialConnectTimeout:
    """The wall-clock cap returns control regardless of connect() behavior."""

    def test_connectBlocksLongerThanTimeout_initializeConnectionReturnsByTimeout(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: connect() blocks until a Stop event is set
        When:  _initializeConnection is called with a 0.5s timeout
        Then:  the method returns within ~1.0s (well under the no-cap worst
               case) AND logs the WARN "Initial connect timed out" line.
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=0.5))
        stopEvent = threading.Event()
        connectCalled = threading.Event()

        fakeConnection = MagicMock()

        def _blockingConnect() -> bool:
            connectCalled.set()
            stopEvent.wait(timeout=10.0)  # safety: never hold the test forever
            return False

        fakeConnection.connect.side_effect = _blockingConnect
        fakeConnection.isConnected.return_value = False

        # The lazy import in _initializeConnection resolves to
        # pi.obdii.obd_connection.createConnectionFromConfig.
        with patch(
            "pi.obdii.obd_connection.createConnectionFromConfig",
            return_value=fakeConnection,
        ):
            with caplog.at_level("WARNING", logger="pi.obdii.orchestrator"):
                started = time.perf_counter()
                orch._initializeConnection()
                elapsed = time.perf_counter() - started

        # Cleanup: release the blocking thread
        stopEvent.set()

        # Wall-clock cap honored: 0.5s timeout + small overhead.  The 2.0s
        # ceiling tolerates GC pauses and Windows-flake jitter on CI.
        assert connectCalled.is_set(), "connect() was never invoked"
        assert elapsed < 2.0, (
            f"_initializeConnection blocked {elapsed:.2f}s -- wall-clock cap "
            "did not fire (expected <2.0s with 0.5s timeout)"
        )
        # Connection object was constructed (not None) even though connect
        # didn't complete -- this is what makes runLoop tolerable.
        assert orch._connection is fakeConnection
        # The WARN line names the timeout fact.
        assert any(
            "timed out" in r.getMessage().lower()
            and "pending" in r.getMessage().lower()
            for r in caplog.records
        ), (
            "Expected a WARN log naming 'timed out' + 'pending' after "
            f"timeout; got: {[r.getMessage() for r in caplog.records]}"
        )

    def test_connectFailsQuickly_initializeConnectionDoesNotRaise(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: connect() returns False fast (retries already exhausted)
        When:  _initializeConnection is called
        Then:  no ComponentInitializationError raised; method returns
               quickly; WARN log mentions "PENDING".

        Pre-US-244 this raised ComponentInitializationError and crashed
        the start() path -- TD-036's silent auto-sync gap.
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=2.0))

        fakeConnection = MagicMock()
        fakeConnection.connect.return_value = False
        fakeConnection.isConnected.return_value = False
        fakeConnection.maxRetries = 5

        with patch(
            "pi.obdii.obd_connection.createConnectionFromConfig",
            return_value=fakeConnection,
        ):
            with caplog.at_level("WARNING", logger="pi.obdii.orchestrator"):
                # Must NOT raise -- the whole point of US-244.
                orch._initializeConnection()

        # PENDING WARN was emitted.
        assert any(
            "pending" in r.getMessage().lower()
            and ("retries exhausted" in r.getMessage().lower()
                 or "returned false" in r.getMessage().lower())
            for r in caplog.records
        ), (
            "Expected a WARN log naming 'PENDING' + retry-exhaustion after "
            f"connect()->False; got: {[r.getMessage() for r in caplog.records]}"
        )
        assert orch._connection is fakeConnection

    def test_connectSucceedsQuickly_logsSuccessAndConnectionUsable(self) -> None:
        """
        Given: connect() returns True immediately (engine on)
        When:  _initializeConnection is called
        Then:  the method returns successfully, the connection is set,
               and isConnected() reports True (the happy-path contract
               the cap MUST NOT regress).
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=2.0))

        fakeConnection = MagicMock()
        fakeConnection.connect.return_value = True
        fakeConnection.isConnected.return_value = True

        with patch(
            "pi.obdii.obd_connection.createConnectionFromConfig",
            return_value=fakeConnection,
        ):
            orch._initializeConnection()

        assert orch._connection is fakeConnection
        assert orch._connection.isConnected() is True
        fakeConnection.connect.assert_called_once()

    def test_invalidTimeoutConfig_fallsBackTo30sDefault(self) -> None:
        """
        Given: pi.obdii.orchestrator.initialConnectTimeoutSec = "garbage"
        When:  _initialConnectTimeoutSec() is called
        Then:  returns 30.0 (default), does not raise.

        Defensive guard: validator DEFAULTS provide 30, but a stale
        config.json can still slip a bad string through.
        """
        config = _baseConfig()
        config["pi"]["obdii"]["orchestrator"]["initialConnectTimeoutSec"] = "not-a-number"
        orch = _makeOrch(config)

        assert orch._initialConnectTimeoutSec() == 30.0


# ================================================================================
# 2. runLoop tolerates a PENDING connection
# ================================================================================


class TestRunLoopToleratesPendingConnection:
    """A timed-out initial connect must NOT block the rest of runLoop."""

    def test_initialConnectTimeout_orchestrator_canStillRunInterval(
        self,
    ) -> None:
        """
        Given: _initializeConnection timed out (connection set, isConnected=False)
        When:  runLoop's interval-sync hook is invoked manually
        Then:  the orchestrator does not crash and the no-op return is
               clean (sync disabled in fixture config).

        Validates the runLoop-tolerance contract without taking the full
        runLoop spin: _maybeTriggerIntervalSync is the canonical example
        of a runLoop-resident behavior that MUST fire regardless of
        connection state (US-226 invariant).
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=0.2))

        fakeConnection = MagicMock()
        stopEvent = threading.Event()
        fakeConnection.connect.side_effect = lambda: stopEvent.wait(timeout=5.0)
        fakeConnection.isConnected.return_value = False

        with patch(
            "pi.obdii.obd_connection.createConnectionFromConfig",
            return_value=fakeConnection,
        ):
            orch._initializeConnection()

        try:
            # Per fixture, pi.sync.enabled=false so _syncClient is None.
            # _maybeTriggerIntervalSync MUST short-circuit cleanly without
            # touching the disconnected connection.
            assert orch._maybeTriggerIntervalSync() is False
        finally:
            stopEvent.set()

    def test_intervalSyncFires_evenWhenConnectionUnconnected(self) -> None:
        """
        Given: connection is unconnected (PENDING) AND a SyncClient exists
        When:  _maybeTriggerIntervalSync is invoked
        Then:  the SyncClient's pushAllDeltas is called -- sync is gated on
               sync-config, NOT on OBD connection state (US-226 invariant
               that US-244 explicitly preserves).
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=0.2))

        fakeConnection = MagicMock()
        stopEvent = threading.Event()
        fakeConnection.connect.side_effect = lambda: stopEvent.wait(timeout=5.0)
        fakeConnection.isConnected.return_value = False

        with patch(
            "pi.obdii.obd_connection.createConnectionFromConfig",
            return_value=fakeConnection,
        ):
            orch._initializeConnection()

        try:
            # Inject a fake SyncClient so the interval trigger hits push.
            fakeSync = MagicMock()
            fakeSync.pushAllDeltas.return_value = []
            orch._syncClient = fakeSync
            orch._syncTriggerOn = ['interval']
            orch._lastSyncAttemptTime = None  # next call must fire immediately

            fired = orch._maybeTriggerIntervalSync()

            assert fired is True, "Interval sync must fire on PENDING connection"
            fakeSync.pushAllDeltas.assert_called_once()
        finally:
            stopEvent.set()


# ================================================================================
# 3. Construction failures are still fatal
# ================================================================================


class TestConstructionFailureStillFatal:
    """Only retry exhaustion is downgraded.  Factory failures still raise."""

    def test_constructionRaises_propagatesAsComponentInitializationError(
        self,
    ) -> None:
        """
        Given: createConnectionFromConfig itself raises (e.g., bad config)
        When:  _initializeConnection is called
        Then:  ComponentInitializationError still propagates -- the cap
               only protects against retry-loop blocking, not against
               malformed config that prevents construction.
        """
        orch = _makeOrch(_baseConfig())

        with patch(
            "pi.obdii.obd_connection.createConnectionFromConfig",
            side_effect=KeyError("missing required config key"),
        ):
            with pytest.raises(ComponentInitializationError):
                orch._initializeConnection()
