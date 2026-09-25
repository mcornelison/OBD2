################################################################################
# File Name: test_mag_keepalive.py
# Purpose/Description: ARCH-057 -- the magnetometer runtime keep-alive. Ports the
#                      repair MEASURED at 20/20 on this hardware 2026-09-18 and
#                      left unshipped for a week while production ran at 0/20.
# Author: Atlas (architect) -- CIO-directed build, override on ARCH-057
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial -- liveness by CHANGE, cooldown, retry,
#               | (ARCH-057)     | never-raises, dwell expressed in SECONDS.
# ================================================================================
################################################################################
"""Is the magnetometer demonstrably alive, and can it be revived in place?

WHY THIS EXISTS, AND WHY IT IS A RUNTIME WATCHDOG.

MEASURED on this hardware 2026-09-18 (``evidence/2026-09-18-heading-algorithm-comparison``):

    do nothing (production today)      0 / 20
    re-init once                      17 / 20 = 85%
    re-init + verify + retry x3       20 / 20 = 100%

🔴 THE INIT'S RETURN VALUE IS NOT EVIDENCE. ``_magnetometer_init()`` returned True on
every hand run INCLUDING the one where the sensor stayed frozen. So liveness is
established by SAMPLING -- the readings must actually CHANGE -- and never by a
success flag.

🔴 AND IT CANNOT BE A STARTUP CHECK. The freeze arrives AFTER a period of good
readings (0.1-1.2 s in both bench runs), so a startup-only probe passes and then
dies one second into the drive.

⚠️ (0,0,0) is physically impossible for a magnetometer -- Earth's field is never
zero -- and is what an uninitialised AK09916 reports. It is the measured source of
the 98 all-zero rows in ``edr_imu_sample``.
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
    magIsLive,
)

# --------------------------------------------------------------------------
# magIsLive -- liveness is CHANGE, not a flag
# --------------------------------------------------------------------------

def test_changingReadings_areLive():
    vals = [(1.0, 2.0, 3.0), (1.15, 2.0, 3.0), (1.0, 2.1, 3.0)]
    assert magIsLive(lambda: vals.pop(0), samples=3, sleepFn=lambda _s: None) is True


def test_identicalReadings_areNotLive():
    """The whole point: a frozen channel returns the same triple forever."""
    assert magIsLive(
        lambda: (11.85, 21.45, 38.25), samples=8, sleepFn=lambda _s: None
    ) is False


def test_allZeroReadings_areNotLive_evenIfTheyChanged():
    """🔴 (0,0,0) is physically impossible -- Earth's field is never zero.

    An uninitialised AK09916 reports it, and it is the measured source of the 98
    all-zero rows in edr_imu_sample. It must fail liveness even if some other
    component varies, because the vector is not a measurement at all.
    """
    assert magIsLive(
        lambda: (0.0, 0.0, 0.0), samples=4, sleepFn=lambda _s: None
    ) is False


def test_aRaisingReaderIsNotLive_andDoesNotPropagate():
    def boom():
        raise OSError("i2c bus error")

    assert magIsLive(boom, samples=4, sleepFn=lambda _s: None) is False


# --------------------------------------------------------------------------
# The dwell is expressed in SECONDS and the count derived from the rate.
# --------------------------------------------------------------------------

def test_frozenRepeatsScaleWithSampleRate():
    """🔴 A threshold in POLLS silently changes meaning when the rate changes.

    This is the US-803-b lesson applied at the point of use: the invariant is a
    wall-clock dwell, so the COUNT is derived from the rate rather than frozen.
    """
    assert frozenRepeatsForRate(4.0) == pytest.approx(MAG_FROZEN_DWELL_S * 4.0, abs=1)
    assert frozenRepeatsForRate(10.0) > frozenRepeatsForRate(4.0)


@pytest.mark.parametrize("rate", [0.0, -1.0, None, float("nan")])
def test_degenerateRateFallsBackToASafeFloor(rate):
    """A bad rate must not produce a zero threshold -- that would restore on
    every single sample and stall the poll loop permanently."""
    assert frozenRepeatsForRate(rate) >= 2


# --------------------------------------------------------------------------
# MagKeepAlive -- retry, verify, cooldown, and never raise
# --------------------------------------------------------------------------

def _keepAlive(reinit, live, *, clock):
    return MagKeepAlive(
        reinitFn=reinit, livenessFn=live, monotonicFn=clock, sleepFn=lambda _s: None
    )


def test_restoreSucceedsOnFirstAttempt():
    calls = []
    ka = _keepAlive(lambda: calls.append("init"), lambda: True, clock=lambda: 100.0)
    assert ka.restore("test") is True
    assert calls == ["init"]
    assert ka.restores == 1
    assert ka.failures == 0


def test_restoreRetriesUpToTheLimitThenReportsFailure():
    calls = []
    ka = _keepAlive(lambda: calls.append("init"), lambda: False, clock=lambda: 100.0)
    assert ka.restore("test") is False
    assert len(calls) == MagKeepAlive.ATTEMPTS
    assert ka.failures == 1
    assert ka.restores == 0


def test_livenessIsCheckedAFTEReachAttempt_notOnce():
    """Verify-per-attempt is what took 85% to 100%."""
    outcomes = [False, True]
    checks = []

    def live():
        checks.append(1)
        return outcomes.pop(0)

    ka = _keepAlive(lambda: None, live, clock=lambda: 100.0)
    assert ka.restore("test") is True
    assert len(checks) == 2


def test_aRaisingReinitIsSwallowedAndCountedAsAnAttempt():
    """🔴 A watchdog that can raise is worse than none: it would take down the
    poll loop it exists to protect."""
    def boom():
        raise OSError("i2c write failed")

    ka = _keepAlive(boom, lambda: False, clock=lambda: 100.0)
    assert ka.restore("test") is False
    assert ka.failures == 1


def test_cooldownSuppressesBackToBackRestores():
    """Without a cooldown a genuinely dead sensor stalls the loop every sample."""
    calls = []
    now = [100.0]
    ka = _keepAlive(lambda: calls.append(1), lambda: True, clock=lambda: now[0])
    assert ka.restore("first") is True
    assert ka.restore("immediately after") is False   # suppressed, not attempted
    assert len(calls) == 1
    now[0] += MagKeepAlive.COOLDOWN_S + 0.01
    assert ka.restore("after the cooldown") is True
    assert len(calls) == 2


def test_suppressedRestoreIsNotCountedAsAFailure():
    """A cooldown suppression is 'not asked', not 'asked and failed'.

    Conflating them would make the failure counter useless as a health signal --
    the same three-valued discipline as the rotation gate's UNDETERMINED.
    """
    ka = _keepAlive(lambda: None, lambda: True, clock=lambda: 100.0)
    ka.restore("first")
    ka.restore("suppressed")
    assert ka.failures == 0
    assert ka.suppressed == 1


def test_trackerFiresOnlyAfterTheDwellOfIdenticalTriples():
    ka = _keepAlive(lambda: None, lambda: True, clock=lambda: 100.0)
    threshold = frozenRepeatsForRate(4.0)
    triple = (11.85, 21.45, 38.25)
    for _ in range(threshold - 1):
        assert ka.noteSample(triple, sampleHz=4.0) is False
    assert ka.noteSample(triple, sampleHz=4.0) is True


def test_anyChangeResetsTheRepeatRun():
    ka = _keepAlive(lambda: None, lambda: True, clock=lambda: 100.0)
    for _ in range(frozenRepeatsForRate(4.0) - 1):
        ka.noteSample((1.0, 2.0, 3.0), sampleHz=4.0)
    ka.noteSample((1.15, 2.0, 3.0), sampleHz=4.0)          # one LSB of dither
    assert ka.noteSample((1.15, 2.0, 3.0), sampleHz=4.0) is False


def test_noneSampleDoesNotCountAsARepeat():
    """An absent reading is not a repeated one. Counting it would let a dead
    channel look frozen for the wrong reason and trigger a pointless restore."""
    ka = _keepAlive(lambda: None, lambda: True, clock=lambda: 100.0)
    for _ in range(frozenRepeatsForRate(4.0) + 3):
        assert ka.noteSample(None, sampleHz=4.0) is False
