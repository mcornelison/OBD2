################################################################################
# File Name: test_capture_health_wiring.py
# Purpose/Description: US-688 (F-138) -- the JOIN. `capture_health.py` decides
#                      correctly in isolation and that is worth nothing until
#                      the orchestrator actually CALLS it, with the real power
#                      fact and the real logger reading, on the real emit tick.
#
#                      🔴 WHY THIS FILE EXISTS SEPARATELY. Every emitter on this
#                      mixin is a CLASS default of None, so a `_maybeEmitCardStates`
#                      that never calls the capture emitter leaves EVERY OTHER
#                      TEST IN THIS SPRINT GREEN and the operator's alert
#                      permanently dark. That is the US-687-b `linkHealthy`
#                      failure exactly -- it defaulted False, and one wiring test
#                      was the single RED in a file of seven.
#
#                      Nothing here sets `powerSource` or the row age directly.
#                      Doing so would prove `buildCaptureHealthState` works,
#                      which the producer suite already proves, and would say
#                      NOTHING about whether the orchestrator ever computes
#                      them -- which is the only thing in doubt.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-08    | Rex (US-688) | Initial -- the emit-tick join, driven through
#               |              | a real provider and a real data logger.
# ================================================================================
################################################################################

"""US-688: the capture-health producer must actually run on the emit tick.

The two facts are acquired through the SAME methods production uses --
``_gatherPowerSource`` (the US-502 GPIO6 SSOT) and the US-302 data-logger
freshness read.  A test that injected either one would be green against an
orchestrator that never gathers it.
"""

from __future__ import annotations

import json

from pi.obdii.capture_health import (
    REASON_LOGGER_ABSENT,
    REASON_NEVER_WRITTEN,
    STATE_IDLE,
    STATE_OK,
    STATE_STALLED,
    STATE_UNKNOWN,
)
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.health_monitor import HealthMonitorMixin

_STALL_S = 60.0


class _FakePowerSourceProvider:
    """The two methods `_gatherPowerSource` actually calls on the provider.

    Models the REAL contract: `isAvailable` is a PROPERTY and gates the read,
    `isExternalPowerPresent()` is the reading. Nothing here shortcuts the
    mapping -- production code is what turns these into external/battery/unknown.
    """

    def __init__(self, *, available: bool, external: bool):
        self._available = available
        self._external = external

    @property
    def isAvailable(self) -> bool:
        return self._available

    def isExternalPowerPresent(self) -> bool:
        return self._external


class _FakeDataLogger:
    """A data logger exposing only US-302's freshness property.

    `lastRowWrittenSecondsAgo` is `None` when no row has ever been written --
    the literal shape the Pi held for two days on 2026-09-04.
    """

    def __init__(self, lastRowWrittenSecondsAgo):
        self.lastRowWrittenSecondsAgo = lastRowWrittenSecondsAgo


class _Orch(HealthMonitorMixin, CardStateEmitterMixin):
    """The real mixins, composed IN THE PRODUCTION ORDER.

    🔴 THE COMPOSITION IS PART OF WHAT THIS FILE PINS. The row-freshness read
    lives on ``HealthMonitorMixin`` and the emit tick on ``CardStateEmitterMixin``
    -- a CROSS-MIXIN call, and `ApplicationOrchestrator` lists them in exactly
    this order (core.py:127-136). US-630 lost a whole feature to this seam: a
    `def foo(): ...` stub declared for mypy SHADOWED the real implementation
    because of MRO order, and the producer logged "wired" while deriving
    nothing. Composing only `CardStateEmitterMixin` here would raise
    AttributeError inside the emit tick's own try/except and be swallowed --
    green init log, no file, no alert.
    """

    def __init__(self, statesDir, *, powerProvider, dataLogger, stallSeconds=_STALL_S):
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "captureHealth": {"enabled": True, "stallSeconds": stallSeconds},
            }
        }
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._dataLogger = dataLogger
        self._powerSourceProvider = powerProvider
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _runTick(tmp_path, *, available=True, external=True, lastRow=None,
             withLogger=True, stallSeconds=_STALL_S):
    """Drive the REAL emit path once; return the parsed states/capture-health.

    Everything between the fakes and the parsed JSON is production code: the
    emitter construction, the power gather, the logger read, the decision and
    the atomic write.
    """
    statesDir = str(tmp_path / "states")
    orch = _Orch(
        statesDir,
        powerProvider=_FakePowerSourceProvider(
            available=available, external=external
        ),
        dataLogger=_FakeDataLogger(lastRow) if withLogger else None,
        stallSeconds=stallSeconds,
    )
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()

    path = tmp_path / "states" / "capture-health"
    assert path.exists(), (
        "no states/capture-health was written -- the producer is not wired into "
        "the emit tick, which is the one failure every other test in this story "
        "stays green for"
    )
    return json.loads(path.read_text())


class TestTheJoin:
    """The emit tick must reach the producer at all."""

    def test_maybeEmitCardStates_writesCaptureHealth(self, tmp_path) -> None:
        """
        Given: a wired orchestrator on car power with rows landing
        When: one emit tick runs
        Then: states/capture-health exists and is a real verdict

        The bare existence assertion. It is in its own test because every other
        test in this file depends on it, and a shared helper that silently
        returned None would make them all pass vacuously.
        """
        state = _runTick(tmp_path, lastRow=1.0)

        assert state["state"] == STATE_OK
        assert state["stallSeconds"] == _STALL_S


class TestTheIncidentThroughTheRealPath:
    """The 2026-09-04 outage, driven end-to-end."""

    def test_maybeEmitCardStates_neverWrittenOnCarPower_publishesStalled(
        self, tmp_path
    ) -> None:
        """
        Given: the Pi is on car power and the logger has never written a row
        When: one emit tick runs
        Then: states/capture-health says `stalled` with the never_written reason

        This is the alert the operator did not get for two days, produced by the
        real path rather than by a hand-built payload.
        """
        state = _runTick(tmp_path, lastRow=None)

        assert state["state"] == STATE_STALLED
        assert state["reason"] == REASON_NEVER_WRITTEN
        assert state["lastRowSecondsAgo"] is None

    def test_maybeEmitCardStates_stalledWithNoConnectionAtAll(self, tmp_path) -> None:
        """
        Given: `_connection` is None -- no dongle, no link, nothing on OBD
        When: one emit tick runs on car power with no rows written
        Then: `stalled` still publishes

        🔴 THE DEAD-BRANCH GUARD AT THE WIRING LEVEL. The producer's own suite
        proves the DECISION ignores OBD; this proves the WIRING does too. An
        orchestrator that gathered an OBD fact and passed it in would have to
        cope with a None connection here, and the natural implementation of
        "engine running" would go false and take the alert with it.
        """
        state = _runTick(tmp_path, lastRow=None)

        assert state["state"] == STATE_STALLED


class TestThePowerGateIsGathered:
    """`powerSource` must come from the provider, not from a default."""

    def test_maybeEmitCardStates_onBattery_publishesIdleNotStalled(
        self, tmp_path
    ) -> None:
        """
        Given: the provider reports the car's power is GONE (key off)
        When: one emit tick runs with no rows ever written
        Then: `idle` -- the story's negative case, through the real gather

        Paired with the incident test above on the SAME row-age fixture: the
        only thing that differs is the GPIO reading. An orchestrator that
        hardcoded `external` passes the incident test and fails this one.
        """
        state = _runTick(tmp_path, external=False, lastRow=None)

        assert state["state"] == STATE_IDLE
        assert state["state"] != STATE_STALLED

    def test_maybeEmitCardStates_unreadablePowerLine_publishesUnknown(
        self, tmp_path
    ) -> None:
        """
        Given: the power provider cannot be read
        When: one emit tick runs with no rows ever written
        Then: `unknown` -- neither a confident alarm nor a confident all-clear
        """
        state = _runTick(tmp_path, available=False, lastRow=None)

        assert state["state"] == STATE_UNKNOWN

    def test_maybeEmitCardStates_noProviderWired_publishesUnknownNotStalled(
        self, tmp_path
    ) -> None:
        """
        Given: no power provider exists on this orchestrator at all
        When: one emit tick runs with no rows ever written
        Then: `unknown`, never `stalled`

        The bench/boot-order case. `_gatherPowerSource` is LAZY precisely
        because the provider lands after the emitters are built, so an early
        tick genuinely has no provider -- and must not alert on that.
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(
            statesDir, powerProvider=None, dataLogger=_FakeDataLogger(None)
        )
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

        state = json.loads((tmp_path / "states" / "capture-health").read_text())
        assert state["state"] == STATE_UNKNOWN
        assert state["state"] != STATE_STALLED


class TestTheLoggerReadIsGathered:
    """The row age must come from the real US-302 property read."""

    def test_maybeEmitCardStates_freshRow_publishesTheRealAge(self, tmp_path) -> None:
        """
        Given: the logger reports a row written 5 s ago
        When: one emit tick runs
        Then: that exact age reaches the state file

        Pins the value as TRANSPORTED rather than re-derived. A wiring that
        passed a constant would pass every state-name assertion in this file.
        """
        state = _runTick(tmp_path, lastRow=5.0)

        assert state["lastRowSecondsAgo"] == 5.0
        assert state["state"] == STATE_OK

    def test_maybeEmitCardStates_agedRow_publishesStalled(self, tmp_path) -> None:
        """
        Given: the logger's newest row is older than the stall window
        When: one emit tick runs on car power
        Then: `stalled`

        The second route into the alert. `never_written` is a cold Pi that never
        captured; THIS is a Pi that was capturing and stopped -- the shape a
        mid-drive dongle drop actually produces.
        """
        state = _runTick(tmp_path, lastRow=_STALL_S + 30.0)

        assert state["state"] == STATE_STALLED
        assert state["lastRowSecondsAgo"] == _STALL_S + 30.0

    def test_maybeEmitCardStates_noDataLogger_publishesUnknownNotStalled(
        self, tmp_path
    ) -> None:
        """
        Given: no data logger is wired at all
        When: one emit tick runs on car power
        Then: `unknown` with the logger_absent reason, NEVER `stalled`

        🔴 THE DISTINCTION US-302's READER LOSES, asserted through the wiring.
        `_readDataLoggerLastRowSecondsAgo` returns None for BOTH this and the
        incident. If the orchestrator passes only that None through, this test
        goes RED as `stalled` -- and every bench run without a logger would
        have raised a capture alarm.
        """
        state = _runTick(tmp_path, withLogger=False)

        assert state["state"] == STATE_UNKNOWN
        assert state["reason"] == REASON_LOGGER_ABSENT
        assert state["state"] != STATE_STALLED


class TestTheWindowIsConfigured:
    """The stall window is a config value, not a constant in the wiring."""

    def test_maybeEmitCardStates_configuredWindowReachesTheDecision(
        self, tmp_path
    ) -> None:
        """
        Given: the same row age judged against two configured windows
        When: each emit tick runs
        Then: the verdict follows the CONFIG, not a hardcoded number

        US-686 closed this sprint on a value that lived in three files with no
        lint over them. This asserts the config value is the one that decides,
        so a wiring that fell back to the module default would be caught here.
        """
        aged = 120.0

        assert _runTick(tmp_path / "a", lastRow=aged, stallSeconds=60.0)[
            "state"
        ] == STATE_STALLED
        assert _runTick(tmp_path / "b", lastRow=aged, stallSeconds=600.0)[
            "state"
        ] == STATE_OK


class TestItStaysDarkWhenDisabled:
    """A disabled producer writes NO file -- it does not write a false all-clear."""

    def test_maybeEmitCardStates_disabled_writesNoFile(self, tmp_path) -> None:
        """
        Given: pi.captureHealth.enabled is false
        When: one emit tick runs
        Then: no states/capture-health exists

        An absent file is what the carousel renders as an honest absence. A file
        saying `ok` would be a producer claiming to have looked when it never
        ran -- the same reason gear writes nothing when its derivation is dark.
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(
            statesDir,
            powerProvider=_FakePowerSourceProvider(available=True, external=True),
            dataLogger=_FakeDataLogger(None),
        )
        orch._config["pi"]["captureHealth"]["enabled"] = False
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

        assert not (tmp_path / "states" / "capture-health").exists()
