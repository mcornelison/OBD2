################################################################################
# File Name: test_mag_keepalive.py
# Purpose/Description: The magnetometer frozen-dwell DETECTOR. The repair itself is
#   tested in test_mag_keepalive_nonblocking.py (ARCH-059).
# Author: Atlas (architect)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial (ARCH-057) -- dwell + blocking restore.
# 2026-09-25    | Atlas          | ARCH-059: the blocking-restore and magIsLive
#               |                | tests REMOVED with their API. See below.
# ================================================================================
################################################################################
"""The frozen-dwell detector: has this channel stopped changing?

⚠️ WHAT WAS REMOVED HERE, AND WHY, SO NOBODY RESTORES IT.
ARCH-057 tested ``magIsLive()`` -- an 8 x 30 ms blocking sample loop -- and a
synchronous ``restore()`` that retried it three times. Those tests passed and the
design they described **took 87% of a real drive**: three attempts x (adafruit's
~4 s reset-and-settle + 240 ms of sleep) stalled the IMU poll thread for ~12.4 s,
repeatedly, and the CIO's 82 s of calibration circles yielded 32 usable samples out
of 328.

🔴 The tests were green because they asked whether the repair WORKED. Nothing asked
what it COST. ARCH-059 moved the repair off the poll thread and made cost the
acceptance criterion; ``test_mag_keepalive_nonblocking.py`` is where that lives, and
its first test fails if the caller ever blocks again.

**Verification is now the poll loop itself** -- it already samples at 4 Hz, so it IS
a liveness test. A blocking check to build a second one was redundant and expensive.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pi.sensors.mag_keepalive import (  # noqa: E402
    MAG_FROZEN_DWELL_S,
    MagKeepAlive,
    frozenRepeatsForRate,
)

# --------------------------------------------------------------------------
# The dwell is a WALL-CLOCK quantity; the count is derived from the rate.
# --------------------------------------------------------------------------

def test_frozenRepeatsScaleWithSampleRate():
    """🔴 A threshold in POLLS silently changes meaning when the rate changes.

    The 2026-09-18 console used a bare count of 20, which was 2 s at its 10 Hz and
    would have become 5 s at production's 4 Hz. Same defect shape as US-803-b, so
    the invariant kept here is the wall clock.
    """
    assert frozenRepeatsForRate(4.0) == pytest.approx(MAG_FROZEN_DWELL_S * 4.0, abs=1)
    assert frozenRepeatsForRate(10.0) > frozenRepeatsForRate(4.0)


@pytest.mark.parametrize("rate", [0.0, -1.0, None, float("nan")])
def test_degenerateRateFallsBackToASafeFloor(rate):
    """A bad rate must not yield a zero threshold -- that would request a repair on
    every single poll and put the loop in a permanent repair cycle."""
    assert frozenRepeatsForRate(rate) >= 2


# --------------------------------------------------------------------------
# The detector itself
# --------------------------------------------------------------------------

def _ka():
    return MagKeepAlive(reinitFn=lambda: None, monotonicFn=lambda: 100.0)


def test_dwellFiresOnlyAfterEnoughIdenticalTriples():
    ka = _ka()
    triple = (11.85, 21.45, 38.25)
    for _ in range(frozenRepeatsForRate(4.0) - 1):
        assert ka.noteSample(triple, sampleHz=4.0) is False
    assert ka.noteSample(triple, sampleHz=4.0) is True


def test_oneLsbOfDitherResetsTheRun():
    """A real sensor dithers, which is exactly why bit-identity is the predicate."""
    ka = _ka()
    for _ in range(frozenRepeatsForRate(4.0) - 1):
        ka.noteSample((1.0, 2.0, 3.0), sampleHz=4.0)
    ka.noteSample((1.15, 2.0, 3.0), sampleHz=4.0)
    assert ka.noteSample((1.15, 2.0, 3.0), sampleHz=4.0) is False


def test_noneSampleIsNotARepeat():
    """An absent reading is not an unchanging one. Counting absence as repetition
    would schedule a repair for a channel that is missing, not frozen."""
    ka = _ka()
    for _ in range(frozenRepeatsForRate(4.0) + 3):
        assert ka.noteSample(None, sampleHz=4.0) is False


def test_forgetClearsTheRun():
    ka = _ka()
    triple = (1.0, 2.0, 3.0)
    for _ in range(frozenRepeatsForRate(4.0)):
        ka.noteSample(triple, sampleHz=4.0)
    ka.forget()
    assert ka.noteSample(triple, sampleHz=4.0) is False
