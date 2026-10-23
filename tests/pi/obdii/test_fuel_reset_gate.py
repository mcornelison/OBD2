################################################################################
# File Name: test_fuel_reset_gate.py
# Purpose/Description: US-923 (F-159) -- the ONE MPG-reset predicate
#                      fuel_reset_gate.resetAllowed (Atlas C1-C5): parked (raw
#                      gear P/N, no hold) OR fresh SPEED <= pi.fuel.
#                      resetMaxSpeedKph; reasons driving / speed_unknown.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-923) | Initial.
# ================================================================================
################################################################################

"""US-923: the MPG reset is allowed parked or rolling <= 5 mph, one predicate."""

from __future__ import annotations

import pytest

from pi.obdii.fuel_reset_gate import (
    REASON_DRIVING,
    REASON_SPEED_UNKNOWN,
    resetAllowed,
)
from pi.obdii.gear_derivation import (
    DEFAULT_MAX_AGE_S,
    GearDeriver,
    GearReading,
    Reading,
)

_NOW = 1000.0
_MAX_KPH = 8.0
_ALLOWED = {"value": True, "reason": None}
_DRIVING = {"value": False, "reason": REASON_DRIVING}
_UNKNOWN = {"value": False, "reason": REASON_SPEED_UNKNOWN}


def _gear(gear, *, available: bool = True, atS: float = _NOW):
    return (GearReading(available=available, gear=gear, reason="x"), atS)


def _speed(kph, *, ageS: float = 0.0) -> Reading:
    return Reading(value=kph, tsS=_NOW - ageS)


def _gate(gear, speed) -> dict:
    return resetAllowed(gear, speed, _NOW, DEFAULT_MAX_AGE_S, _MAX_KPH)


# ======================================================= validation criteria


def test_vc_gearP_allowed_evenWithNoSpeed():
    assert _gate(_gear("P"), None) == _ALLOWED


def test_vc_gearN_speedZero_allowed():
    assert _gate(_gear("N"), _speed(0.0)) == _ALLOWED


@pytest.mark.parametrize("kph", [0.0, 5.0, 8.0])
def test_vc_gear3_freshSpeedAtOrUnderEight_allowed(kph):
    assert _gate(_gear(3), _speed(kph)) == _ALLOWED


def test_vc_gear3_freshSpeedNine_refusedDriving():
    """9 km/h = 5.59 mph (Atlas 2026-10-22): one whole km/h past the limit."""
    assert _gate(_gear(3), _speed(9.0)) == _DRIVING


def test_vc_notParked_speedStale_refusedSpeedUnknown():
    assert _gate(_gear(3), _speed(0.0, ageS=DEFAULT_MAX_AGE_S + 0.1)) == _UNKNOWN


def test_vc_cachedPOlderThanMaxAge_freshSpeed40_refusedDriving():
    """GAP 1: a stale cached P must never allow a reset at speed."""
    stale = _gear("P", atS=_NOW - DEFAULT_MAX_AGE_S - 0.5)
    assert _gate(stale, _speed(40.0)) == _DRIVING


def test_vc_speedTwoSecondsOld_isFresh():
    assert _gate(_gear(3), _speed(8.0, ageS=2.0)) == _ALLOWED


# ================================================================ the rule


@pytest.mark.parametrize(
    "gear",
    [None, _gear("P", available=False), _gear(None, available=False), _gear("R"),
     _gear("p"), _gear(2)],
    ids=["no-gear", "P-unavailable", "absent", "R", "lowercase-p", "gear-2"],
)
def test_notParked_fallsToTheSpeedClause(gear):
    assert _gate(gear, _speed(20.0)) == _DRIVING
    assert _gate(gear, _speed(4.0)) == _ALLOWED
    assert _gate(gear, None) == _UNKNOWN


@pytest.mark.parametrize(
    "speed",
    [None, Reading(value=None, tsS=_NOW), Reading(value=float("nan"), tsS=_NOW),
     Reading(value=float("inf"), tsS=_NOW)],
    ids=["none", "value-none", "nan", "inf"],
)
def test_missingOrNonFiniteSpeed_isSpeedUnknown(speed):
    assert _gate(_gear(3), speed) == _UNKNOWN


def test_parkedWins_overAFastStaleOrMissingSpeed():
    """Raw P/N, no hold (Atlas C2): the speed clause is not consulted."""
    assert _gate(_gear("N"), _speed(40.0, ageS=10.0)) == _ALLOWED
    assert _gate(_gear("P"), _speed(40.0)) == _ALLOWED


def test_freshnessBoundary_isTheDeriversOwn():
    """One freshness rule with _parkOpinion: exactly maxAgeS old is still fresh
    for the deriver's _liveValue, and so it is here."""
    deriver = GearDeriver(maxAgeS=DEFAULT_MAX_AGE_S)
    edge = _speed(0.0, ageS=DEFAULT_MAX_AGE_S)
    past = _speed(0.0, ageS=DEFAULT_MAX_AGE_S + 0.01)
    assert deriver._liveValue(edge, _NOW) == 0.0
    assert _gate(_gear(3), edge) == _ALLOWED
    assert deriver._liveValue(past, _NOW) != 0.0
    assert _gate(_gear(3), past) == _UNKNOWN


def test_gearExactlyMaxAgeOld_isStillParked():
    assert _gate(_gear("P", atS=_NOW - DEFAULT_MAX_AGE_S), None) == _ALLOWED


def test_theResultIsANewDictEachCall():
    a = _gate(_gear("P"), None)
    a["value"] = False
    assert _gate(_gear("P"), None) == _ALLOWED
