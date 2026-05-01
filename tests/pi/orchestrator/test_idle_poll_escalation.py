################################################################################
# File Name: test_idle_poll_escalation.py
# Purpose/Description: US-242 / B-049 escalation tests -- BATTERY_V sustained
#                      above engineOnVoltageThreshold for engineOnSampleCount
#                      consecutive samples fires the single-shot RPM probe and
#                      drive_detector observes the RPM value (drive_start
#                      eligible).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-242) | B-049 close: idle->active escalation tests.
# ================================================================================
################################################################################

"""US-242 / B-049 -- engine-on escalation acceptance tests.

Mocks BATTERY_V at sensor-read level (LoggedReading objects pumped through
:meth:`ApplicationOrchestrator._handleReading`) per
``feedback_runtime_validation_required.md``.  No orchestrator-state-machine
mocking; the escalation logic runs end-to-end against the real
ApplicationOrchestrator + a real :class:`DriveDetector` with shortened
debounce windows.

Trace from the 2026-04-29 inverted-power drill (Drive 5 baseline):

* engine off, battery rest:  12.7-12.8V
* cranking dip:              ~11.4V (single sample)
* engine on, alternator:     14.4V (bulk-charge)

13.8V threshold sustained 3 samples = unmistakable alternator-active
signature.  See ``offices/pm/backlog/B-049-drive-detect-idle-poll-gap.md``
and ``offices/tuner/knowledge.md`` for grounding.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.drive.detector import DriveDetector
from pi.obdii.drive.types import DriveState
from pi.obdii.orchestrator.core import ApplicationOrchestrator

# ================================================================================
# Helpers / fixtures
# ================================================================================


def _baseConfig() -> dict[str, Any]:
    """Minimal config exercising the new pi.obdii.orchestrator section."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "obdii": {
                "orchestrator": {
                    "engineOnVoltageThreshold": 13.8,
                    "engineOnSampleCount": 3,
                },
            },
            "analysis": {
                # Tight debounce + zero-duration so a single RPM probe value
                # above threshold is enough to drive the state machine
                # through STARTING -> RUNNING (drive_start fires on the
                # next processValue iteration).
                "driveStartRpmThreshold": 500,
                "driveStartDurationSeconds": 0.0,
                "driveEndRpmThreshold": 0,
                "driveEndDurationSeconds": 60,
                "triggerAfterDrive": False,
                "driveSummaryBackfillSeconds": 0,
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }


def _makeReading(parameterName: str, value: float) -> MagicMock:
    """Build a LoggedReading-shaped mock the EventRouterMixin can route."""
    reading = MagicMock(spec=["parameterName", "value", "unit"])
    reading.parameterName = parameterName
    reading.value = value
    reading.unit = "V" if parameterName == "BATTERY_V" else None
    return reading


@pytest.fixture()
def orchestrator() -> ApplicationOrchestrator:
    """ApplicationOrchestrator wired with a real DriveDetector.

    ``simulate=True`` short-circuits the OBD connection requirement at
    construction.  We attach a real :class:`DriveDetector` (in MONITORING
    state, primed STOPPED) and a mock dataLogger whose inner ``_dataLogger``
    exposes ``queryAndLogParameter`` -- the orchestrator's
    ``_injectRpmProbeForEscalation`` call site.
    """
    orch = ApplicationOrchestrator(config=_baseConfig(), simulate=True)

    detector = DriveDetector(config=_baseConfig())
    detector.start()
    # Skip the UNKNOWN -> STOPPED bootstrap so the first RPM > threshold
    # transitions directly into STARTING (and with duration=0, immediately
    # RUNNING, firing _startDrive).
    detector._driveState = DriveState.STOPPED
    orch._driveDetector = detector

    # Mock dataLogger composition (RealtimeDataLogger wraps an
    # ObdDataLogger at ``._dataLogger`` -- _injectRpmProbeForEscalation
    # walks that path).
    inner = MagicMock()
    inner.queryAndLogParameter = MagicMock(
        return_value=_makeReading("RPM", 800.0)
    )
    outer = MagicMock()
    outer._dataLogger = inner
    orch._dataLogger = outer

    return orch


# ================================================================================
# Acceptance #1: alternator-active BATTERY_V trace fires escalation by sample 6
# ================================================================================


class TestAlternatorActiveEscalation:
    """Sustained > threshold BATTERY_V samples trigger the single-shot RPM probe."""

    def test_alternatorActiveTrace_escalatesBySampleSix(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """The drill trace [12.7, 12.7, 11.4, 14.4, 14.4, 14.4] escalates on
        sample 6 -- 3 consecutive samples above 13.8V.
        """
        trace = [12.7, 12.7, 11.4, 14.4, 14.4, 14.4]
        escalationStates: list[bool] = []

        for voltage in trace:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))
            escalationStates.append(orchestrator._engineOnEscalated)

        assert escalationStates == [
            False, False, False, False, False, True,
        ], (
            "Escalation must NOT fire until 3 consecutive samples above "
            "13.8V are observed (cranking dip at sample 3 resets the "
            f"counter); got {escalationStates}"
        )

    def test_escalation_injectsSingleShotRpmProbe(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """The escalation path queries RPM exactly once via the data logger."""
        for voltage in [12.7, 12.7, 11.4, 14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        inner = orchestrator._dataLogger._dataLogger
        inner.queryAndLogParameter.assert_called_once_with("RPM")

    def test_escalation_feedsRpmIntoDriveDetector(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """Drive detector observes the probed RPM value -- drive_start eligible."""
        for voltage in [12.7, 12.7, 11.4, 14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        # First call: 800 > 500 threshold + duration=0 -> STARTING.  The
        # _processRpmValue path fires _startDrive on the same tick when
        # the elapsed time satisfies the (zero) debounce.
        detector = orchestrator._driveDetector
        assert detector._lastRpmValue == 800.0
        assert detector._driveState in {DriveState.STARTING, DriveState.RUNNING}, (
            f"After RPM=800 probe, detector should be STARTING or RUNNING; "
            f"got {detector._driveState}"
        )

    def test_escalation_isOneShotPerProcess(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """A second sustained burst does not re-trigger the probe."""
        # First burst escalates.
        for voltage in [14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))
        # Second burst (after a fictional drop-and-rise) must not re-probe.
        for voltage in [12.7, 12.7, 14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        inner = orchestrator._dataLogger._dataLogger
        assert inner.queryAndLogParameter.call_count == 1, (
            "Single-shot invariant: RPM probe must fire at most once per "
            f"process; saw {inner.queryAndLogParameter.call_count} calls"
        )


# ================================================================================
# Acceptance #1b: probe failure preserves escalation flag (single-shot invariant)
# ================================================================================


class TestEscalationFailureModes:
    """Probe failures are swallowed; the flag stays set so we never retry."""

    def test_probeRaises_swallowedAndFlagPersists(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        inner = orchestrator._dataLogger._dataLogger
        inner.queryAndLogParameter.side_effect = RuntimeError("ECU silent")

        for voltage in [14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        assert orchestrator._engineOnEscalated is True, (
            "Probe failure must not unset the escalation flag -- otherwise "
            "every subsequent BATTERY_V tick would re-attempt the probe."
        )

    def test_dataLoggerNone_isCleanNoOp(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        orchestrator._dataLogger = None

        for voltage in [14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        # Escalation flag flipped, but no probe was attempted -- runLoop
        # tolerates a missing dataLogger (e.g. early-boot pre-init).
        assert orchestrator._engineOnEscalated is True


# ================================================================================
# Acceptance: existing detector reading-routing still works
# (regression guard for the EventRouterMixin._handleReading tail addition)
# ================================================================================


class TestEventRouterRegression:
    """The escalation hook is additive; non-BATTERY_V routing is unchanged."""

    def test_rpmReading_stillRoutesToDriveDetector(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        orchestrator._handleReading(_makeReading("RPM", 1200.0))

        assert orchestrator._driveDetector._lastRpmValue == 1200.0

    def test_unrelatedReading_doesNotTriggerEscalation(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        # SPEED, COOLANT_TEMP, ... must not move the escalation counter.
        for paramName in ["RPM", "SPEED", "COOLANT_TEMP", "MAF"]:
            orchestrator._handleReading(_makeReading(paramName, 100.0))

        assert orchestrator._engineOnEscalated is False
        assert orchestrator._consecutiveAlternatorActiveSamples == 0
