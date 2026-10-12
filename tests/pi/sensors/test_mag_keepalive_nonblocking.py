################################################################################
# File Name: test_mag_keepalive_nonblocking.py
# Purpose/Description: ARCH-059 -- the keep-alive must never block the IMU poll
#   loop. ARCH-057 did, for up to 12.4 s, and it cost 87% of a real drive.
# Author: Atlas (architect) -- CIO-directed
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial -- the acceptance criterion is CADENCE,
#               | (ARCH-059)     | not liveness. That is the whole point.
# ================================================================================
################################################################################
"""🔴 THE ACCEPTANCE CRITERION IS CADENCE, AND THAT IS THE LESSON.

ARCH-057's acceptance was LIVENESS -- does the repair work? It does: 84 restores,
0 failures, measured on the car. **I never measured what it COST**, and the cost
was that it ran on the IMU poll thread:

  MEASURED on drive 84 (2026-09-25, 20 minutes):
    * 154 of 654 sample intervals exceeded 0.6 s -- 23.5%
    * max gap 17.5 s, with a tight cluster at ~12.4 s
    * 639 rows where ~4,800 were due -- 13%
    * the CIO's 82 s of deliberate calibration circles yielded 32 usable
      magnetometer samples out of 328

The 12.4 s cluster is 3 attempts x (adafruit's ~4 s reset-and-settle + a 240 ms
blocking liveness sample loop). At 4 Hz that is ~50 missed polls, repeatedly.

⚠️ AND THE COST WAS WRITTEN DOWN A WEEK EARLIER, IN MY OWN INSTALL NOTES:
*"The cost, stated plainly: the sample rate drops from 10 Hz to ~1.5 Hz."*
I read that, called it acceptable for a 10 Hz harness, and shipped it into a 4 Hz
production loop without re-pricing it. Losing 85% of 10 Hz leaves 1.5 Hz; losing
the same from 4 Hz leaves 0.5 Hz, and the losses CLUSTER.

⇒ So every test here is about the CALLER, not the sensor. A repair that works and
destroys the data it was protecting is not a fix.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pi.sensors.mag_keepalive import (  # noqa: E402
    MAG_PLAUSIBLE_MAX_UT,
    MagKeepAlive,
    RestoreOutcome,
    frozenRepeatsForRate,
)
from pi.sensors.plausibility_gate import magnitudeAtMost  # noqa: E402

#: One definition of the rule, enforced where the mechanism lives.
magnitudeIsPlausible = magnitudeAtMost(MAG_PLAUSIBLE_MAX_UT)

#: The caller is a 4 Hz poll loop, so one interval is 250 ms. The keep-alive must
#: return in a small fraction of that -- it is bookkeeping, not work.
CALLER_BUDGET_S = 0.02


def _ka(reinit, *, clock=None, cooldown=None):
    ka = MagKeepAlive(reinitFn=reinit, monotonicFn=clock or time.monotonic)
    if cooldown is not None:
        ka.COOLDOWN_S = cooldown
    return ka


# --------------------------------------------------------------------------
# 🔴 THE TEST THAT WOULD HAVE CAUGHT ARCH-057
# --------------------------------------------------------------------------

def test_requestRestoreDoesNOTBlockTheCaller_evenWhenTheRepairIsSlow():
    """🔴 THE REGRESSION GUARD. A 4 s re-init must cost the poll loop nothing.

    ARCH-057 called a ~4 s init synchronously, three times. This asserts the
    caller returns in under one-tenth of a 4 Hz poll interval regardless.
    """
    started = threading.Event()
    release = threading.Event()

    def slowReinit():
        started.set()
        release.wait(5.0)          # stands in for adafruit's reset-and-settle

    ka = _ka(slowReinit)
    t0 = time.monotonic()
    outcome = ka.requestRestore("test")
    elapsed = time.monotonic() - t0

    assert outcome is RestoreOutcome.STARTED
    assert elapsed < CALLER_BUDGET_S, (
        f"the caller blocked for {elapsed*1000:.0f} ms -- ARCH-057 blocked for "
        f"12,400 ms and that is what this test exists to prevent"
    )
    assert started.wait(2.0), "the repair never ran off-thread"
    release.set()
    ka.join(timeout=5.0)
    assert ka.repairsIssued == 1


def test_noteSampleIsAlsoCheap():
    """The detector runs on every poll, so it must be bookkeeping only."""
    ka = _ka(lambda: None)
    triple = (11.85, 21.45, 38.25)
    t0 = time.monotonic()
    for _ in range(1000):
        ka.noteSample(triple, sampleHz=4.0)
    assert (time.monotonic() - t0) < 0.05


def test_aSecondRequestWhileRepairingIsBUSY_notAQueue():
    """Queueing repairs would let a frozen sensor schedule dozens of re-inits."""
    release = threading.Event()
    ka = _ka(lambda: release.wait(5.0), cooldown=0.0)
    assert ka.requestRestore("first") is RestoreOutcome.STARTED
    assert ka.requestRestore("second") is RestoreOutcome.BUSY
    release.set()
    ka.join(timeout=5.0)
    assert ka.repairsIssued == 1


def test_cooldownSuppressesWithoutStartingAWorker():
    now = [100.0]
    ka = _ka(lambda: None, clock=lambda: now[0])
    assert ka.requestRestore("a") is RestoreOutcome.STARTED
    ka.join(timeout=2.0)
    assert ka.requestRestore("b") is RestoreOutcome.SUPPRESSED
    now[0] += ka.COOLDOWN_S + 0.01
    assert ka.requestRestore("c") is RestoreOutcome.STARTED
    ka.join(timeout=2.0)
    assert ka.repairsIssued == 2


def test_aRaisingReinitIsCountedAndNeverPropagates():
    def boom():
        raise OSError("i2c write failed")

    ka = _ka(boom)
    assert ka.requestRestore("test") is RestoreOutcome.STARTED
    ka.join(timeout=2.0)
    assert ka.failures == 1
    assert ka.repairsIssued == 0


def test_theDwellIsClearedAfterARepair_soVerificationIsThePollLoop():
    """🔴 NO BLOCKING LIVENESS CHECK. ARCH-057 slept 8 x 30 ms to verify.

    The poll loop already samples at 4 Hz -- it IS a liveness test. So the repair
    clears the dwell and the NEXT window decides. Verification that costs nothing
    beats verification that costs 240 ms.
    """
    ka = _ka(lambda: None)
    triple = (1.0, 2.0, 3.0)
    for _ in range(frozenRepeatsForRate(4.0)):
        ka.noteSample(triple, sampleHz=4.0)
    ka.requestRestore("dwell")
    ka.join(timeout=2.0)
    # The run was reset, so the very next identical sample cannot re-fire.
    assert ka.noteSample(triple, sampleHz=4.0) is False


def test_repairsIssuedIsNamedHonestly():
    """It counts re-inits ISSUED, not repairs CONFIRMED.

    Nothing here proves the sensor came back -- the dwell recurring is what says
    that. Calling the counter 'restores' implied a confirmation it never had.
    """
    ka = _ka(lambda: None)
    ka.requestRestore("x")
    ka.join(timeout=2.0)
    assert hasattr(ka, "repairsIssued")
    assert not hasattr(ka, "restores"), (
        "'restores' implied confirmed liveness that this design does not measure"
    )


# --------------------------------------------------------------------------
# The overflow bound -- master mode never decodes ST2, so |B| is the only guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mag", [(11.85, 21.45, 38.25), (0.0, 0.0, 50.0), (30.0, 30.0, 30.0)])
def test_earthFieldIsPlausible(mag):
    assert magnitudeIsPlausible(mag) is True


@pytest.mark.parametrize("mag", [
    (4895.85, 4915.05, -4895.85),    # MEASURED on drive 84 -- 18 rows like this
    (4895.85, -0.15, -4895.85),      # MEASURED on drive 84
])
def test_measuredOverflowRowsAreRefused(mag):
    """🔴 REAL ROWS from drive 84, published as data because master mode reads ST2
    but never DECODES it. The bypass path raised on HOFL; switching the default to
    master silently dropped that check, and |B| is what is left to catch it."""
    assert magnitudeIsPlausible(mag) is False


def test_allZeroPassesTheCEILING_becauseInvarianceOwnsIt():
    """⚠️ DELIBERATE, and worth stating so nobody "fixes" it.

    (0,0,0) is physically impossible and is the measured source of the 98 all-zero
    rows in edr_imu_sample -- but it is caught by INVARIANCE (bit-identity), which
    the mag channel is enrolled in. Adding a floor here would be a second guard on
    one fact, and the pinned enrolment test records that a magnetometer field floor
    is invented physics. A ceiling asserts only saturation.
    """
    assert magnitudeIsPlausible((0.0, 0.0, 0.0)) is True


def test_theCeilingIsWellAboveEarthAndWellBelowFullScale():
    """Basis: Earth's field is 25-65 uT globally; the AK09916's full scale is
    +/-4912 uT. The ceiling must reject saturation without clipping real field."""
    assert 80.0 < MAG_PLAUSIBLE_MAX_UT < 4000.0


def test_thereIsExactlyONEDefinitionOfTheCeilingRule():
    """🔴 mag_keepalive DECLARES the number; plausibility_gate ENFORCES it.

    A private predicate in mag_keepalive with no production caller is the A-28 /
    A-16 shape -- a complete, correct implementation nothing calls -- which this
    project has paid for three times. This asserts the duplicate stayed deleted.
    """
    import pi.sensors.mag_keepalive as ka

    assert not hasattr(ka, "magnitudeIsPlausible")
    assert not hasattr(ka, "MAG_PLAUSIBLE_MIN_UT")


def test_nonFiniteIsRefused():
    assert magnitudeIsPlausible((float("nan"), 0.0, 0.0)) is False
