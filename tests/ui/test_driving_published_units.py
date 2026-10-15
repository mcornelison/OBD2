################################################################################
# File Name: test_driving_published_units.py
# Purpose/Description: US-888-b (F-140, Iris G-1) -- the Driving card fed what
#   the Pi ACTUALLY publishes. The fixture driving-published-units.json is
#   proven to be the obd-live builder's output for readings carrying
#   python-obd's MEASURED unit names (degree_Celsius, kilometer_per_hour,
#   revolutions_per_minute, volt), then rendered through the Driving card's
#   view and the shipped DOM: coolant in deg F, speed in mph, RPM with no unit,
#   battery in V. Before US-888-b the card showed "degree_Celsius".
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-888-b) | Initial -- published units through the card.
# ================================================================================
################################################################################

"""US-888-b: the Driving card renders the provider's canonical units."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from pi.obdii import obd_live_emitter as ole
from tests.ui.test_driving_page import (
    _NODE_ONLY,
    _boot,
    _child,
    _fixture,
    _ms,
    _probe,
    _readingPath,
    _textOf,
)

FIXTURE = "driving-published-units"

# MEASURED python-obd unit per PID (obd2db realtime_data, Atlas 2026-10-15 s1).
PUBLISHED_UNITS = {
    "RPM": "revolutions_per_minute",
    "SPEED": "kilometer_per_hour",
    "COOLANT_TEMP": "degree_Celsius",
    "INTAKE_TEMP": "degree_Celsius",
    "BATTERY_V": "volt",
}

# pid -> (text, unit) on the Driving card.
EXPECTED = {
    "COOLANT_TEMP": ("190", "°F"),
    "INTAKE_TEMP": ("88", "°F"),
    "SPEED": ("40", "mph"),
    "RPM": ("2450", ""),
    "BATTERY_V": ("14.1", "V"),
}


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback (LoggedReading)."""

    def __init__(self, parameterName: str, value: Any, timestamp: datetime, unit: str) -> None:
        self.parameterName = parameterName
        self.value = value
        self.timestamp = timestamp
        self.unit = unit


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_fixture_isTheBuildersOutputForPythonObdUnits() -> None:
    """
    Given: the fixture's readings, re-fed with python-obd's measured unit names
    When: observed by a real ObdLiveTracker and built at the fixture's ts
    Then: the builder's output equals the fixture's obd-live exactly
    """
    payload = _fixture(FIXTURE)["obd-live"]
    tracker = ole.ObdLiveTracker({})
    for name, pid in payload["params"].items():
        tracker.observeReading(
            _Reading(name, pid["value"], _utc(pid["ts"]), PUBLISHED_UNITS[name])
        )

    built = ole.buildObdLiveState(
        tracker.snapshot(),
        nowUtc=_utc(payload["ts"]),
        staleSec=ole.DEFAULT_OBD_LIVE_STALE_S,
        dataSource=payload["dataSource"],
    )

    assert built == payload


@_NODE_ONLY
@pytest.mark.parametrize("pid", sorted(EXPECTED))
def test_drivingView_convertsThePublishedUnits(pid: str) -> None:
    """
    Given: the published-units fixture
    When: the Driving card's view is built from it
    Then: coolant/IAT in deg F, speed in mph, RPM with no unit, battery in V
    """
    fx = _fixture(FIXTURE)
    view = _probe("drivingView", fx["obd-live"], fx["gear"], _ms(fx["now"]))

    reading = view["readings"][pid]

    assert (reading["text"], reading["unit"]) == EXPECTED[pid]


@_NODE_ONLY
@pytest.mark.parametrize("pid", sorted(EXPECTED))
def test_shippedDom_paintsTheConvertedUnits(pid: str) -> None:
    """
    Given: the published-units fixture served as /obd-live
    When: the shipped dashboard renders the Driving card
    Then: each reading's value and unit text are the converted ones
    """
    path = _readingPath(_boot(FIXTURE), pid)

    shown = (_textOf(_child(path, "drv-value")[-1]), _textOf(_child(path, "drv-unit")[-1]))

    assert shown == EXPECTED[pid]
