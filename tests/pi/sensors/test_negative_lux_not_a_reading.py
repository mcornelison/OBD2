################################################################################
# File Name: test_negative_lux_not_a_reading.py
# Purpose/Description: ARCH-010 -- a negative computed lux is not a measurement.
#   Publish it as None (honest unavailable), never as a number, and never
#   clamped to 0.
# Author: Atlas (Architect)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-29    | Atlas   | ARCH-010: negative lux dims the display in sun
# ================================================================================
################################################################################

"""A negative lux is a computation failure, not a dark reading.

**Measured, not theorised.** 452 samples in `edr_light_sample` on 2026-08-28
carried a negative lux, worst **-721.4**, during a drive. The raw channels on
that sample:

    visible 5884   infrared 29230   full_spectrum 35114     -> 83% INFRARED

The TSL2591 lux equation subtracts a multiple of the IR channel, so an
IR-dominated reading computes negative. 16:45 CDT -- low afternoon sun straight
through the windscreen.

**Why it mattered.** `freshLux` rejected non-finite values but not negatives, and
a negative IS finite, so it passed every type check downstream, reached
``if (lux <= luxMin) return 0`` and drove the display to ``minLevel``.
**The sunnier it got, the dimmer the screen went.**

**Why None and not 0.** Clamping to 0 would be the convenient choice and it is
the wrong one: 0 lux looks like darkness, so the display would still dim. `None`
routes to `defaultLevel`, which is full brightness -- so the honest answer and
the correct behaviour turn out to be the same answer. That is not a coincidence;
it is what honest-availability buys.

**Zero is NOT rejected.** A photon-counting sensor in real darkness can return a
bit-exact zero legitimately -- US-564 says so explicitly about this very device.
Rejecting 0 would delete a real reading.
"""

import pytest

from src.pi.sensors.sensor_reader import _readLux


class _Dev:
    def __init__(self, lux):
        self._lux = lux

    @property
    def lux(self):
        return self._lux


class TestANegativeLuxIsNotAReading:
    def test_theRealMinus721SampleIsRejected(self):
        """The worst sample actually recorded on 2026-08-28."""
        assert _readLux(_Dev(-721.4)) is None

    @pytest.mark.parametrize("lux", [-0.001, -1.0, -721.4, -14577.0])
    def test_anyNegativeIsRejected(self, lux):
        assert _readLux(_Dev(lux)) is None

    def test_itIsNotClampedToZero(self):
        """Clamping is the convenient answer and the wrong one: 0 lux reads as
        darkness and would still dim the panel. None routes to defaultLevel."""
        assert _readLux(_Dev(-721.4)) is not 0  # noqa: F632 -- identity is the point
        assert _readLux(_Dev(-721.4)) != 0


class TestValidReadingsSurvive:
    def test_zeroIsAValidReading(self):
        """Real darkness. US-564 records that this sensor can legitimately
        return a bit-exact zero; rejecting it would delete a real measurement."""
        assert _readLux(_Dev(0.0)) == 0.0

    @pytest.mark.parametrize("lux", [0.0, 0.4, 23.0, 209.0, 3196.5])
    def test_realWorldValuesPassThrough(self, lux):
        """23 = unmounted sensor, 209 = overcast in the window, 3196 = sun."""
        assert _readLux(_Dev(lux)) == pytest.approx(lux)


class TestExistingGuardsStillHold:
    def test_noneStaysNone(self):
        assert _readLux(_Dev(None)) is None

    def test_nonFiniteStillRejected(self):
        assert _readLux(_Dev(float("inf"))) is None
        assert _readLux(_Dev(float("nan"))) is None
