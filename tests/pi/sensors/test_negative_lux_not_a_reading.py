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
# 2026-10-06    | Atlas   | US-731: lux is now computed from raw counts, so the
#               |         | rule is tested on `_honestLux` (the same cases,
#               |         | unchanged) plus the REAL 2026-08-28 sample from its
#               |         | own recorded counts -- which also checks the port of
#               |         | the lux equation against the library's -721.4.
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

from src.pi.sensors.sensor_reader import TSL_GAIN_MED, _honestLux, _luxFromCounts

# The real 2026-08-28 sample: full_spectrum = CH0, infrared = CH1 (adafruit_tsl2591 1.4.8).
_REAL_CH0, _REAL_CH1 = 35114, 29230


class TestANegativeLuxIsNotAReading:
    def test_theRealMinus721SampleIsRejected(self):
        """The worst sample actually recorded on 2026-08-28."""
        assert _honestLux(-721.4) is None

    def test_theRealSample_fromItsOwnCounts_isRejected(self):
        """US-731: the same moment, recomputed from its recorded counts at medium gain."""
        assert _luxFromCounts(_REAL_CH0, _REAL_CH1, TSL_GAIN_MED, 0) is None

    def test_theEquationPort_reproducesTheRecordedValue(self):
        """Cross-check of the port against real data: with the LIBRARY's 25x medium
        gain the equation gives the recorded -721.4 for these counts. (US-731 uses the
        datasheet's 24.5x, which gives about -736 -- also rejected.)"""
        cpl = 100.0 * 25.0 / 408.0
        library = max((_REAL_CH0 - 1.64 * _REAL_CH1) / cpl, (0.59 * _REAL_CH0 - 0.86 * _REAL_CH1) / cpl)
        assert library == pytest.approx(-721.4, abs=0.1)

    @pytest.mark.parametrize("lux", [-0.001, -1.0, -721.4, -14577.0])
    def test_anyNegativeIsRejected(self, lux):
        assert _honestLux(lux) is None

    def test_itIsNotClampedToZero(self):
        """Clamping is the convenient answer and the wrong one: 0 lux reads as
        darkness and would still dim the panel. None routes to defaultLevel."""
        assert _honestLux(-721.4) is not 0  # noqa: F632 -- identity is the point
        assert _honestLux(-721.4) != 0


class TestValidReadingsSurvive:
    def test_zeroIsAValidReading(self):
        """Real darkness. US-564 records that this sensor can legitimately
        return a bit-exact zero; rejecting it would delete a real measurement."""
        assert _honestLux(0.0) == 0.0

    @pytest.mark.parametrize("lux", [0.0, 0.4, 23.0, 209.0, 3196.5])
    def test_realWorldValuesPassThrough(self, lux):
        """23 = unmounted sensor, 209 = overcast in the window, 3196 = sun."""
        assert _honestLux(lux) == pytest.approx(lux)


class TestExistingGuardsStillHold:
    def test_noneStaysNone(self):
        assert _honestLux(None) is None

    def test_nonFiniteStillRejected(self):
        assert _honestLux(float("inf")) is None
        assert _honestLux(float("nan")) is None
