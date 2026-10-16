################################################################################
# File Name: test_units.py
# Purpose/Description: US-888-b (F-140) -- the provider's canonical short units.
#   Feeds the unit strings python-obd ACTUALLY returns (MEASURED in obd2db
#   realtime_data since 2026-10-12, cited in Atlas's 2026-10-15 units ruling
#   s1) and pins the canonical output; an unknown string (the status PIDs'
#   labels) passes through unchanged and warns once per distinct string.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-888-b) | Initial -- canonicalUnit and its WARN-once rule.
# ================================================================================
################################################################################

"""US-888-b: python-obd unit names -> the states/ contract's short units."""

from __future__ import annotations

import logging

import pytest

from pi.obdii import units

# MEASURED: realtime_data.unit on the Pi's obd.db (pulled 2026-10-15 09:50),
# per Atlas 2026-10-15 "RULED-units-normalise-in-the-provider" s1.
MEASURED_TO_CANONICAL = [
    ("degree_Celsius", "C"),
    ("kilometer_per_hour", "km/h"),
    ("volt", "V"),
    ("revolutions_per_minute", "rpm"),
    ("percent", "%"),
    ("degree", "deg"),
    ("gps", "g/s"),
    ("count", "count"),
]

# MEASURED in the same column: the status PIDs carry a LABEL, not a unit.
MEASURED_STATUS_LABELS = ["CL", "OL", "OL-drive", "ON", "OFF"]


@pytest.fixture(autouse=True)
def _freshWarnMemory() -> None:
    units._warnedUnits.clear()


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(("raw", "canonical"), MEASURED_TO_CANONICAL)
def test_canonicalUnit_measuredPythonObdName_isTheShortUnit(raw: str, canonical: str) -> None:
    """
    Given: a unit string python-obd returned on the car
    When: canonicalised
    Then: the states/ contract's short unit
    """
    assert units.canonicalUnit(raw) == canonical


def test_canonicalUnits_isExactlyTheRuledMap() -> None:
    """
    Given: Atlas's ruled map (2026-10-15 s2)
    When: compared
    Then: CANONICAL_UNITS holds exactly those eight entries
    """
    assert units.CANONICAL_UNITS == dict(MEASURED_TO_CANONICAL)


@pytest.mark.parametrize("canonical", sorted(set(dict(MEASURED_TO_CANONICAL).values())))
def test_canonicalUnit_alreadyCanonical_passesSilently(
    canonical: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Given: a string that is already a canonical unit
    When: canonicalised
    Then: it is returned unchanged and nothing is logged
    """
    with caplog.at_level(logging.DEBUG, logger=units.logger.name):
        assert units.canonicalUnit(canonical) == canonical
    assert _warnings(caplog) == []


@pytest.mark.parametrize("label", MEASURED_STATUS_LABELS)
def test_canonicalUnit_statusLabel_passesThroughUnchanged(label: str) -> None:
    """
    Given: a status PID's label in the unit column (FUEL_SYSTEM_STATUS, MIL_ON)
    When: canonicalised
    Then: it is returned UNCHANGED -- status PIDs are read by value, never unit
    """
    assert units.canonicalUnit(label) == label


def test_canonicalUnit_unknownString_warnsOncePerDistinctString(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: 'OL-drive' three times and 'ON' twice
    When: canonicalised
    Then: exactly two WARNs -- one per distinct string, not one per reading
    """
    with caplog.at_level(logging.WARNING, logger=units.logger.name):
        for raw in ["OL-drive", "ON", "OL-drive", "ON", "OL-drive"]:
            units.canonicalUnit(raw)

    warned = _warnings(caplog)
    assert len(warned) == 2
    assert "'OL-drive'" in warned[0].getMessage()
    assert "'ON'" in warned[1].getMessage()


def test_canonicalUnit_knownName_neverWarns(caplog: pytest.LogCaptureFixture) -> None:
    """
    Given: every measured python-obd name
    When: canonicalised
    Then: no WARN
    """
    with caplog.at_level(logging.WARNING, logger=units.logger.name):
        for raw, _ in MEASURED_TO_CANONICAL:
            units.canonicalUnit(raw)
    assert _warnings(caplog) == []


def test_canonicalUnit_none_isNone(caplog: pytest.LogCaptureFixture) -> None:
    """
    Given: a reading that carried no unit
    When: canonicalised
    Then: None, silently -- no unit is not an unknown unit
    """
    with caplog.at_level(logging.WARNING, logger=units.logger.name):
        assert units.canonicalUnit(None) is None
    assert _warnings(caplog) == []
