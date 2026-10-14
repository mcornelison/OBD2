################################################################################
# File Name: test_trip_gap_crosses_tiers.py
# Purpose/Description: US-880-a -- ONE gap definition across tiers. The Pi's
#                      pi.trip.gapSec default equals the server's
#                      GAP_DETECTION_THRESHOLD_SECONDS, and the Pi's speed
#                      integrator and the server's derived-signals integral
#                      give the same distance for the same SPEED series --
#                      a segment with dt > gapSec excluded on both.
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
"""The trip gap rule crosses the tier boundary (US-880-a)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.common.config.validator import DEFAULTS
from src.pi.obdii.speed_integrator import SpeedIntegrator
from src.server.analytics.derived_signals_compute import computeDerivedSignals
from src.server.analytics.drive_summary_compute import GAP_DETECTION_THRESHOLD_SECONDS

_T0 = datetime(2026, 10, 14, 12, 0, 0)


def test_piGapSecDefault_equalsTheServerGapThreshold():
    """Atlas 2026-10-14: pi.trip.gapSec == GAP_DETECTION_THRESHOLD_SECONDS."""
    assert DEFAULTS["pi.trip.gapSec"] == GAP_DETECTION_THRESHOLD_SECONDS


def _piDistance(series: list[tuple[float, float]]) -> float:
    integ = SpeedIntegrator(DEFAULTS["pi.trip.gapSec"])
    km = 0.0
    for tS, speed in series:
        km = integ.update(speed, tS)
    return km


def _serverDistance(series: list[tuple[float, float]]) -> float:
    samples = [(_T0 + timedelta(seconds=tS), speed) for tS, speed in series]
    result = computeDerivedSignals(samples)
    assert result is not None
    return result.estimated_distance_km


@pytest.mark.parametrize(
    "series",
    [
        # Steady cruise, ~2.2 s per-PID cadence.
        [(i * 2.2, 60.0) for i in range(50)],
        # Accelerate and brake.
        [(0.0, 0.0), (2.0, 20.0), (4.0, 45.0), (6.0, 30.0), (8.0, 0.0)],
        # A 5-16 s bus stall mid-drive is still travel (not obdLiveSec).
        [(0.0, 50.0), (2.0, 50.0), (18.0, 50.0), (20.0, 50.0)],
        # A soak gap wider than gapSec: excluded on both tiers.
        [(0.0, 50.0), (10.0, 50.0), (311.0, 50.0), (321.0, 50.0)],
        # Exactly gapSec is still travel on both tiers.
        [(0.0, 36.0), (300.0, 36.0)],
    ],
)
def test_sameSpeedSeries_piAndServerAgree(series):
    assert _piDistance(series) == pytest.approx(_serverDistance(series), abs=1e-12)


def test_gapWiderThanGapSec_excludedFromDistance():
    """dt > gapSec adds nothing to distance on the Pi (and the server agrees)."""
    gap = DEFAULTS["pi.trip.gapSec"]
    series = [(0.0, 50.0), (gap + 1.0, 50.0)]

    assert _piDistance(series) == 0.0
    assert _serverDistance(series) == 0.0
