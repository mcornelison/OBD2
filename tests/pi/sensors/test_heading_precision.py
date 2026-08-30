################################################################################
# File Name: test_heading_precision.py
# Purpose/Description: ARCH-012 -- the published heading must not claim more
#   precision than the magnetometer delivers.
# Author: Atlas (Architect)
# Creation Date: 2026-08-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-30    | Atlas   | ARCH-012: heading to whole degrees
# ================================================================================
################################################################################

"""The heading is published in whole degrees, not tenths.

**Measured on the live Pi**, 10 samples over 20 s from a sensor that never moved
(car parked, engine off):

    77.4 .. 89.2 deg   ->   range 11.8 deg, sigma 3.33

That independently reproduces Spool's ±3.2° scatter finding. Publishing 0.1°
resolved the bearing **118× finer than the sensor moves while standing still** --
not precision, but a claim about the measurement that the measurement does not
make.

**This test exists because the defect is a CONSTANT.** A one-token change with no
guard is exactly what drifts back the next time someone wants a smoother-looking
number.

**What this does NOT assert**, deliberately -- see the module comment in
`imu_state_bridge.py`: whole degrees is still ~12× finer than the observed
scatter. Rounding hides jitter; it does not reduce it. And TD-087 (uncalibrated
hard/soft iron) is a *systematic* offset that no precision choice corrects. This
removes a false claim; it does not make the heading trustworthy.
"""

import pytest

from src.pi.sensors.imu_state_bridge import _HEADING_DECIMALS, computeHeadingDeg

# A level frame: gravity straight down, so the horizontal projection is clean.
_LEVEL_GRAVITY = (0.0, 0.0, 9.80665)


class TestPublishedPrecision:
    def test_headingDecimalsIsZero(self):
        """The constant itself is the contract. Pinned so it cannot drift back."""
        assert _HEADING_DECIMALS == 0

    @pytest.mark.parametrize("mag", [
        (1.0, 0.0, 0.0),
        (0.7071, 0.7071, 0.0),
        (0.0, 1.0, 0.0),
        (-0.3, 0.9, 0.0),
        (0.42, -0.91, 0.0),
    ])
    def test_aPublishedHeadingCarriesNoFractionalPart(self, mag):
        h = computeHeadingDeg(_LEVEL_GRAVITY, mag)
        assert h is not None
        assert h == int(h), f"heading {h} claims sub-degree precision the sensor does not have"

    def test_theBearingIsStillInRange(self):
        """Rounding must not push a value outside 0..360."""
        for mag in [(1.0, -1e-9, 0.0), (1.0, 1e-9, 0.0), (-1.0, -1e-9, 0.0)]:
            h = computeHeadingDeg(_LEVEL_GRAVITY, mag)
            assert h is not None and 0.0 <= h < 360.0


class TestHonestAbsenceStillHolds:
    """Rounding must not turn an unavailable heading into a number."""

    def test_noMagReadingIsStillNone(self):
        assert computeHeadingDeg(_LEVEL_GRAVITY, (0.0, 0.0, 0.0)) is None

    def test_unresolvableTiltIsStillNone(self):
        assert computeHeadingDeg((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) is None
