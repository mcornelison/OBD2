################################################################################
# File Name: test_idle_poll_no_false_escalation.py
# Purpose/Description: US-242 / B-049 false-positive guard tests -- a single
#                      noise spike or sub-threshold trace must NOT escalate.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-242) | B-049 close: no-false-escalation tests.
# ================================================================================
################################################################################

"""US-242 / B-049 -- engine-on no-false-escalation tests.

Verifies that:

* engine-off rest voltage (12.7-12.8V) never escalates;
* an isolated noise spike below or above the threshold resets the counter
  on the next sub-threshold sample (single-spike rejection);
* the counter requires consecutive samples (not cumulative) -- a 14.4V,
  12.7V, 14.4V pattern stays sub-count.

Mocks BATTERY_V at sensor-read level (LoggedReading objects pumped through
:meth:`ApplicationOrchestrator._handleReading`) per
``feedback_runtime_validation_required.md``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.orchestrator.core import ApplicationOrchestrator

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig() -> dict[str, Any]:
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
            "sync": {"enabled": False},
        },
        "server": {},
    }


def _makeReading(parameterName: str, value: float) -> MagicMock:
    reading = MagicMock(spec=["parameterName", "value", "unit"])
    reading.parameterName = parameterName
    reading.value = value
    reading.unit = "V" if parameterName == "BATTERY_V" else None
    return reading


@pytest.fixture()
def orchestrator() -> ApplicationOrchestrator:
    """Real orchestrator with a mock dataLogger -- no real probe needed."""
    orch = ApplicationOrchestrator(config=_baseConfig(), simulate=True)

    inner = MagicMock()
    inner.queryAndLogParameter = MagicMock()
    outer = MagicMock()
    outer._dataLogger = inner
    orch._dataLogger = outer

    return orch


# ================================================================================
# Acceptance #2: rest voltage with single sub-threshold spike does NOT escalate
# ================================================================================


class TestSubThresholdTraces:
    """Sub-threshold and isolated-spike traces never trigger escalation."""

    def test_engineOffRest_neverEscalates(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """Sustained 12.7V (battery rest) -- counter never increments."""
        for _ in range(10):
            orchestrator._handleReading(_makeReading("BATTERY_V", 12.7))

        assert orchestrator._engineOnEscalated is False
        assert orchestrator._consecutiveAlternatorActiveSamples == 0

        inner = orchestrator._dataLogger._dataLogger
        inner.queryAndLogParameter.assert_not_called()

    def test_singleSubThresholdSpike_doesNotEscalate(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """13.5V spike (still below 13.8) is invisible to the tracker."""
        trace = [12.7, 12.7, 13.5, 12.7, 12.7]

        for voltage in trace:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        assert orchestrator._engineOnEscalated is False
        # The 13.5V is BELOW threshold so the counter never moved.
        assert orchestrator._consecutiveAlternatorActiveSamples == 0

        inner = orchestrator._dataLogger._dataLogger
        inner.queryAndLogParameter.assert_not_called()

    def test_isolatedAboveThresholdSpike_resetsCounter(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """A 14.0V spike followed by 12.7V drops the counter back to zero."""
        # Two above-threshold samples build the counter to 2, but the next
        # 12.7V sample resets to 0 -- so the *third* 14.0V never reaches
        # the engineOnSampleCount threshold of 3.
        trace = [14.0, 14.0, 12.7, 14.0, 12.7]

        for voltage in trace:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        assert orchestrator._engineOnEscalated is False
        # After the final 12.7V, counter is 0.
        assert orchestrator._consecutiveAlternatorActiveSamples == 0

        inner = orchestrator._dataLogger._dataLogger
        inner.queryAndLogParameter.assert_not_called()

    def test_floatChargeStatic_doesNotEscalate(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """13.5-13.7V float-charge band stays below the 13.8V cutoff.

        Drive 5 baseline shows the alternator's float-charge mode hovers
        in 13.5-13.7V territory.  The threshold is intentionally above
        this so a fully-warmed-up alternator on a charged battery never
        false-escalates if the orchestrator picks the signal up
        mid-drive (where this story's escalation is moot anyway).
        """
        for voltage in [13.5, 13.6, 13.7, 13.6, 13.5, 13.7]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        assert orchestrator._engineOnEscalated is False
        assert orchestrator._consecutiveAlternatorActiveSamples == 0


# ================================================================================
# Acceptance: counter logic guards (consecutive-only, threshold-strict)
# ================================================================================


class TestCounterLogic:
    """Sample-count and threshold-comparison guards behave as documented."""

    def test_exactThreshold_doesNotCount(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """Comparison is strictly greater-than (13.8V exactly does NOT count).

        13.8V is the *cutoff* between alternator-active and engine-off
        states; treating it as inclusive would risk false-escalation
        on float-charge upticks that briefly hit the boundary.
        """
        for _ in range(5):
            orchestrator._handleReading(_makeReading("BATTERY_V", 13.8))

        assert orchestrator._engineOnEscalated is False
        assert orchestrator._consecutiveAlternatorActiveSamples == 0

    def test_twoAboveThenInterrupted_neverEscalates(
        self, orchestrator: ApplicationOrchestrator
    ) -> None:
        """N=2 consecutive samples is below count=3 -- no escalation."""
        # Build counter to 2, interrupt, build to 2 again.  Cumulative
        # above-threshold samples = 4, but counter never hits 3.
        for voltage in [14.4, 14.4, 12.7, 14.4, 14.4, 12.7]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        assert orchestrator._engineOnEscalated is False
