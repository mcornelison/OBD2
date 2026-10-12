################################################################################
# File Name: test_mag_rotation_gate.py
# Purpose/Description: ARCH-056 -- the magnetometer ROTATION gate and the mag
#                      SOURCE provenance. Guards the frozen-channel failure
#                      that silently contaminated five of twelve drives.
# Author: Atlas (architect) -- CIO-directed build, override recorded on ARCH-056
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-24    | Atlas          | Initial -- three-valued rotation verdict,
#               | (ARCH-056)     | grounded thresholds, measured-corpus guards.
# ================================================================================
################################################################################
"""Does the mag channel actually turn when the car turns?

WHY THIS EXISTS. ``dev.magnetic`` (the Adafruit path) returns a FROZEN vector
unless the read extends through ST2 -- US-565 measured that directly. The
``ak09916_bypass`` module reads ST1..ST2 and is correct, but when it fails
``_attachDirectMagnetometer`` returns the BARE ICM, silently reinstating the
known-frozen path. The code defended that with "the US-564 gate will refuse it
as stale".

🔴 IT DID NOT, AND THE RECORD PROVES IT. MEASURED 2026-09-24 over
``edr_imu_sample``, per-axis excursion across a whole drive:

    drives 70 / 77 / 78 (healthy) : 12.45 -- 46.50 uT
    drives 69 / 72 / 74 / 75 / 76 : 5.25 -- 9.30 uT   <-- frozen, WRITTEN not refused

A turning car must sweep the horizontal field through ~2H ~ 40 uT. Those five
drives moved ~6 uT and every row was persisted, then calibrated against.

⚠️ THE OLD GATE TESTS THE WRONG PROPERTY. ``REASON_NO_MAG`` fires on AGE
(``MAG_MAX_AGE_POLLS / sampleHz`` = 1.25 s today). A frozen channel is FRESH --
new timestamps, unchanging content -- so an age gate cannot see it. The project's
bit-identity rule cannot either: the frozen readback dithers by a few LSB, so it
is not bit-identical. The discriminating property is ROTATION, and nothing tested
it.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pi.sensors.imu_state_bridge import (  # noqa: E402
    MAG_ROTATION_MIN_RATIO,
    MAG_ROTATION_MIN_YAW_RAD,
    MAG_SOURCE_BYPASS,
    MAG_SOURCE_ICM_SHADOW,
    MAG_SOURCE_NONE,
    REASON_MAG_FROZEN,
    MagRotation,
    assessMagRotation,
)

# --------------------------------------------------------------------------
# The three-valued verdict. UNDETERMINED is not a pass.
# --------------------------------------------------------------------------

def test_notEnoughYaw_isUNDETERMINED_neverHealthy():
    """A car driving straight cannot testify about its magnetometer.

    🔴 This is the case that makes the gate safe to ship: a bare excursion
    threshold would fire on every highway mile. No yaw means NO EXPECTATION, and
    the honest verdict is UNDETERMINED -- never HEALTHY, because nothing was
    demonstrated. A skip is not a pass.
    """
    verdict = assessMagRotation(yawRad=math.radians(5.0), magRotationRad=0.0)
    assert verdict is MagRotation.UNDETERMINED


def test_frozenChannel_underRealYaw_isFROZEN():
    """90 deg of measured yaw with a mag bearing that did not move."""
    verdict = assessMagRotation(yawRad=math.radians(90.0), magRotationRad=math.radians(1.0))
    assert verdict is MagRotation.FROZEN


def test_liveChannel_trackingYaw_isHEALTHY():
    """A correctly-read magnetometer rotates ~1:1 with vehicle yaw."""
    verdict = assessMagRotation(yawRad=math.radians(90.0), magRotationRad=math.radians(88.0))
    assert verdict is MagRotation.HEALTHY


# --------------------------------------------------------------------------
# The threshold is DERIVED, not chosen. This is the test that pins the basis.
# --------------------------------------------------------------------------

def test_uncorrectedHardIron_isNotMistakenForFrozen():
    """🔴 THE THRESHOLD'S WHOLE REASON, and it is measured.

    MEASURED drive 77: hard-iron |offset| = 17.59 uT against a rotating radius
    of 16.43 uT. Offset EXCEEDS radius, so the uncorrected horizontal locus does
    NOT enclose the origin and the raw bearing physically cannot sweep a full
    circle -- it is bounded to about +/- asin(R/|offset|) ~ +/- 69 deg, i.e. a
    ratio near 0.38 over a full vehicle rotation.

    US-695 is NOT shipped, so the live channel is uncorrected TODAY. A ratio
    threshold at or above 0.38 would therefore condemn a perfectly live channel.
    The threshold sits well below it, and a frozen channel scores ~0.
    """
    fullTurn = math.radians(360.0)
    uncorrectedSweep = 2.0 * math.asin(min(1.0, 16.43 / 17.59))  # ~138 deg
    ratio = uncorrectedSweep / fullTurn
    assert ratio == pytest.approx(0.38, abs=0.03), "the measured geometry moved"
    assert MAG_ROTATION_MIN_RATIO < ratio, (
        "the gate would refuse a LIVE but uncorrected channel -- "
        "that is the nuisance-fire trap this threshold exists to avoid"
    )
    assert assessMagRotation(yawRad=fullTurn, magRotationRad=uncorrectedSweep) is (
        MagRotation.HEALTHY
    )


def test_measuredFrozenDrives_scoreBelowTheThreshold():
    """Grounded in the corpus: ~6 uT of excursion on a 16.4 uT circle.

    A frozen axis wandering 6 uT peak-to-peak on a circle of radius 16.4 uT
    subtends at most 2*asin(3.0/16.4) ~ 21 deg of apparent bearing, whatever the
    car did. Against a full turn that is a ratio of ~0.06.
    """
    apparent = 2.0 * math.asin((9.30 / 2.0) / 16.43)  # widest frozen drive
    ratio = apparent / math.radians(360.0)
    assert ratio < MAG_ROTATION_MIN_RATIO, (
        "the widest frozen drive must still be caught"
    )
    assert assessMagRotation(
        yawRad=math.radians(360.0), magRotationRad=apparent
    ) is MagRotation.FROZEN


def test_thresholdsAreDeclaredOnce_andCarryTheirUnits():
    """The constants state their quantity, per the standing naming rule."""
    assert MAG_ROTATION_MIN_YAW_RAD > 0.0
    assert 0.0 < MAG_ROTATION_MIN_RATIO < 0.38


# --------------------------------------------------------------------------
# Degenerate inputs resolve to UNDETERMINED, never to a pass.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("yaw", [0.0, -1.0, float("nan")])
def test_degenerateYaw_isUNDETERMINED(yaw):
    assert assessMagRotation(yawRad=yaw, magRotationRad=0.5) is MagRotation.UNDETERMINED


def test_nonFiniteMagRotation_isUNDETERMINED_notFrozen():
    """An unreadable rotation is not evidence of freezing.

    Reporting FROZEN here would condemn the channel on the strength of having
    failed to measure it -- the same inversion as reporting a disk HEALTHY
    because the filesystem could not be read.
    """
    verdict = assessMagRotation(yawRad=math.radians(90.0), magRotationRad=float("nan"))
    assert verdict is MagRotation.UNDETERMINED


# --------------------------------------------------------------------------
# Provenance: which path produced the reading.
# --------------------------------------------------------------------------

def test_magSourceConstants_areDistinctAndTyped():
    """A disagreement between two observers is only visible if rows say who saw it."""
    sources = {MAG_SOURCE_BYPASS, MAG_SOURCE_ICM_SHADOW, MAG_SOURCE_NONE}
    assert len(sources) == 3
    assert MAG_SOURCE_ICM_SHADOW != MAG_SOURCE_BYPASS
    for s in sources:
        assert isinstance(s, str) and s


def test_frozenReasonIsTypedAndDistinctFromStale():
    """``mag_frozen`` is not ``no_mag_reading``.

    Collapsing them would re-create the defect: an age gate reporting a content
    failure means the operator reads "stale" and goes looking for a timing
    problem that is not there.
    """
    from pi.sensors.imu_state_bridge import REASON_NO_MAG

    assert REASON_MAG_FROZEN != REASON_NO_MAG
    assert REASON_MAG_FROZEN == "mag_frozen"
