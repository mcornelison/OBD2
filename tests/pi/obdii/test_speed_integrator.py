################################################################################
# File Name: test_speed_integrator.py
# Purpose/Description: US-880-a -- the pure SpeedIntegrator: trapezoid distance
#                      between consecutive SPEED readings with the server's gap
#                      rule, None ignored, reset forgets the interval start.
# Author: Rex (US-880-a)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-880-a) | Initial.
# ================================================================================
################################################################################

"""US-880-a: one speed integrator for this drive's distance."""

from __future__ import annotations

import pytest

from pi.obdii.speed_integrator import SpeedIntegrator

_GAP_S = 300.0


def test_update_firstReading_onlySetsTheStart():
    integ = SpeedIntegrator(_GAP_S)

    assert integ.update(60.0, 0.0) == 0.0


def test_update_zeroThenSixty_overSixtySeconds_isHalfAKilometre():
    """Given update(0, 0); update(60, 60)
    Then the trapezoid (0 + 60) / 2 * 60 / 3600 = 0.5 km."""
    integ = SpeedIntegrator(_GAP_S)

    integ.update(0.0, 0.0)

    assert integ.update(60.0, 60.0) == pytest.approx(0.5)


def test_update_storyExample_accumulates():
    integ = SpeedIntegrator(300.0)

    assert integ.update(0.0, 100.0) == 0.0
    assert integ.update(36.0, 110.0) == pytest.approx(0.05)
    assert integ.update(36.0, 120.0) == pytest.approx(0.15)


def test_update_intervalWiderThanGap_contributesNothing_andRestartsTheInterval():
    """update(50, 0); update(50, 301) with gap 300 -> 0.0; update(50, 311)
    then adds 50 * 10 / 3600 (the gap reading became the next start)."""
    integ = SpeedIntegrator(_GAP_S)

    integ.update(50.0, 0.0)
    assert integ.update(50.0, 301.0) == 0.0

    assert integ.update(50.0, 311.0) == pytest.approx(50.0 * 10.0 / 3600.0)


def test_update_intervalExactlyTheGap_isStillTravel():
    """dt == gapSec is not > gapSec, so it integrates (the server's rule)."""
    integ = SpeedIntegrator(_GAP_S)

    integ.update(36.0, 0.0)

    assert integ.update(36.0, 300.0) == pytest.approx(3.0)


def test_update_zeroDt_contributesNothing():
    integ = SpeedIntegrator(_GAP_S)

    integ.update(50.0, 10.0)

    assert integ.update(50.0, 10.0) == 0.0


def test_update_negativeDt_contributesNothing_andBecomesTheStart():
    integ = SpeedIntegrator(_GAP_S)

    integ.update(50.0, 10.0)
    assert integ.update(50.0, 5.0) == 0.0

    assert integ.update(50.0, 15.0) == pytest.approx(50.0 * 10.0 / 3600.0)


def test_update_noneSpeed_isIgnoredEntirely():
    """update(40, 0); update(None, 5); update(40, 10) -> 40 * 10 / 3600:
    the None neither contributes nor becomes the interval start."""
    integ = SpeedIntegrator(_GAP_S)

    integ.update(40.0, 0.0)
    assert integ.update(None, 5.0) == 0.0

    assert integ.update(40.0, 10.0) == pytest.approx(40.0 * 10.0 / 3600.0)


def test_update_noneFirst_doesNotStartTheInterval():
    integ = SpeedIntegrator(_GAP_S)

    integ.update(None, 0.0)

    assert integ.update(40.0, 10.0) == 0.0


def test_reset_afterTwoKilometres_zeroes_andForgetsTheStart():
    """reset() after 2 km -> 0.0, and the next update contributes nothing."""
    integ = SpeedIntegrator(_GAP_S)
    integ.update(72.0, 0.0)
    assert integ.update(72.0, 100.0) == pytest.approx(2.0)

    integ.reset()

    assert integ.distanceKm == 0.0
    assert integ.update(72.0, 110.0) == 0.0
    assert integ.update(72.0, 160.0) == pytest.approx(1.0)


def test_distanceKm_isTheCumulativeTotal():
    integ = SpeedIntegrator(_GAP_S)
    integ.update(36.0, 0.0)
    integ.update(36.0, 100.0)

    assert integ.distanceKm == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [0, -1.0, float("inf"), float("nan")])
def test_init_nonPositiveOrNonFiniteGap_rejected(bad):
    with pytest.raises(ValueError):
        SpeedIntegrator(bad)
