################################################################################
# File Name: test_drive_phases.py
# Purpose/Description: ARCH-058 -- the four-phase drive schedule and the park
#                      detector that ends a session without the driver touching
#                      anything. Pure logic; no hardware, no HTTP, no clock.
# Author: Atlas (architect) -- CIO-directed build, override on ARCH-058
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial -- bracketed ORIGINAL->A->B->ORIGINAL
#               | (ARCH-058)     | schedule, transition edges, park auto-end.
# ================================================================================
################################################################################
"""The drive schedule, and why it is bracketed.

THE CIO'S CONSTRAINTS, which shape every decision here:
  * he is DRIVING -- no keyboard, no typing, no console, nothing to manipulate;
  * he is OFF WIFI for the whole session, so nothing can be driven over SSH;
  * the screen is 3.5 inches, so anything shown has to be readable at a glance;
  * therefore: ZERO interaction. The session starts before he leaves, advances on
    a clock, and ENDS ITSELF -- including restoring the collector.

🔴 WHY THE CONTROL RUNS AT BOTH ENDS (the CIO's own suggestion, and it is right).
The sequence is ORIGINAL -> A -> B -> ORIGINAL. If the closing control differs
from the opening one, something changed DURING the drive -- temperature, the
mount, the magnetic environment -- and without the bracket that drift would be
silently attributed to A or B. Bracketing turns four phases into a paired design.

🔴 WHY A PHASE CANNOT BE SHORT WITHOUT CIRCLES. MEASURED from the CIO's own
2026-09-15 GPX: worst-case coverage of 36 heading bins was 3% at a 2-minute
window and only 81% at 15 minutes. A hard-iron offset is the CENTRE OF A CIRCLE
and cannot be located from an arc -- so a phase that contains no continuous turn
cannot produce a fit however long it runs. A rectangular block has FOUR headings;
lapping it three times gives three times as many samples at the same four.
Hence the on-screen circle prompt at the head of each phase.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.imu.drive_phases import (  # noqa: E402
    CIRCLE_PROMPT_S,
    DEFAULT_PHASES,
    MECH_KEEPALIVE,
    MECH_KEEPALIVE_DRDY,
    MECH_ORIGINAL,
    ParkDetector,
    PhaseSchedule,
)

# --------------------------------------------------------------------------
# The schedule shape -- bracketed, and the CIO's 5 minutes first.
# --------------------------------------------------------------------------

def test_defaultScheduleIsBracketedByTheControl():
    """🔴 ORIGINAL at BOTH ends is the drift control, not redundancy."""
    mechs = [p.mechanism for p in DEFAULT_PHASES]
    assert mechs[0] == MECH_ORIGINAL
    assert mechs[-1] == MECH_ORIGINAL
    assert MECH_KEEPALIVE in mechs
    assert MECH_KEEPALIVE_DRDY in mechs


def test_openingPhaseIsFiveMinutes_asTheCIOSpecified():
    assert DEFAULT_PHASES[0].seconds == pytest.approx(5 * 60)


def test_theClosingPhaseIsOpenEnded():
    """He drives home on the closing control; it cannot have a fixed end."""
    assert DEFAULT_PHASES[-1].seconds is None
    assert all(p.seconds is not None for p in DEFAULT_PHASES[:-1])


def test_exactlyOnePhaseIsOpenEnded():
    """Two open-ended phases would make the schedule ambiguous and the second
    unreachable -- a silent loss of a whole mechanism."""
    assert sum(1 for p in DEFAULT_PHASES if p.seconds is None) == 1


# --------------------------------------------------------------------------
# Advancing on the clock
# --------------------------------------------------------------------------

def _schedule():
    return PhaseSchedule(DEFAULT_PHASES)


def test_startsInPhaseZeroAtTimeZero():
    s = _schedule()
    assert s.at(0.0).index == 0


def test_advancesAtTheBoundary_notBefore():
    s = _schedule()
    first = DEFAULT_PHASES[0].seconds
    assert s.at(first - 0.1).index == 0
    assert s.at(first + 0.1).index == 1


def test_remainingCountsDownWithinAPhase():
    s = _schedule()
    a = s.at(10.0)
    b = s.at(70.0)
    assert a.remainingS is not None and b.remainingS is not None
    assert b.remainingS < a.remainingS
    assert a.remainingS == pytest.approx(DEFAULT_PHASES[0].seconds - 10.0)


def test_theOpenEndedPhaseHasNoRemaining():
    """None, never a fabricated number. A countdown to an end that does not
    exist is the same class of lie as a zeroed sensor reading."""
    s = _schedule()
    total = sum(p.seconds for p in DEFAULT_PHASES[:-1])
    assert s.at(total + 60.0).remainingS is None


def test_neverAdvancesPastTheLastPhase():
    s = _schedule()
    huge = 10_000_000.0
    assert s.at(huge).index == len(DEFAULT_PHASES) - 1


def test_transitionIsDetectedExactlyOnce():
    """The banner must fire on the EDGE. Firing every poll would leave it on
    screen permanently and it would stop meaning 'something just changed'."""
    s = _schedule()
    first = DEFAULT_PHASES[0].seconds
    assert s.advanceTo(first - 1.0) is None            # still phase 0
    switched = s.advanceTo(first + 1.0)
    assert switched is not None and switched.index == 1
    assert s.advanceTo(first + 2.0) is None            # no repeat


def test_aBackwardsClockDoesNotRewindThePhase():
    """A monotonic clock should never go backwards, but if it does, replaying a
    phase would silently relabel rows already written under the next one."""
    s = _schedule()
    first = DEFAULT_PHASES[0].seconds
    s.advanceTo(first + 1.0)
    assert s.advanceTo(1.0) is None
    assert s.current.index == 1


# --------------------------------------------------------------------------
# The circle prompt
# --------------------------------------------------------------------------

def test_circlePromptShowsAtTheHeadOfAPhaseAndThenClears():
    s = _schedule()
    assert s.at(1.0).promptCircles is True
    assert s.at(CIRCLE_PROMPT_S + 1.0).promptCircles is False


def test_circlePromptReturnsAfterEachSwitch():
    s = _schedule()
    first = DEFAULT_PHASES[0].seconds
    assert s.at(first + 1.0).promptCircles is True


# --------------------------------------------------------------------------
# ParkDetector -- ends the session without the driver doing anything
# --------------------------------------------------------------------------

def test_sustainedStillnessReportsParked():
    d = ParkDetector(stillSeconds=60.0, minSessionSeconds=0.0)
    for t in range(0, 121, 5):
        d.note(magnitudeMs2=9.81, nowS=float(t), sessionElapsedS=float(t))
    assert d.parked is True


def test_motionResetsTheStillnessRun():
    d = ParkDetector(stillSeconds=60.0, minSessionSeconds=0.0)
    for t in range(0, 55, 5):
        d.note(magnitudeMs2=9.81, nowS=float(t), sessionElapsedS=float(t))
    d.note(magnitudeMs2=11.4, nowS=56.0, sessionElapsedS=56.0)   # a real bump
    d.note(magnitudeMs2=9.81, nowS=57.0, sessionElapsedS=57.0)
    assert d.parked is False


def test_parkIsSuppressedBeforeTheMinimumSessionLength():
    """🔴 Otherwise sitting at the first long red light ends the session and the
    drive is over before the second mechanism has ever run."""
    d = ParkDetector(stillSeconds=30.0, minSessionSeconds=600.0)
    for t in range(0, 121, 5):
        d.note(magnitudeMs2=9.81, nowS=float(t), sessionElapsedS=float(t))
    assert d.parked is False


def test_anAbsentReadingDoesNotCountAsStillness():
    """None is 'we do not know', not 'not moving'. Treating a dead accelerometer
    as a parked car would end the session on an instrument fault."""
    d = ParkDetector(stillSeconds=30.0, minSessionSeconds=0.0)
    for t in range(0, 121, 5):
        d.note(magnitudeMs2=None, nowS=float(t), sessionElapsedS=float(t))
    assert d.parked is False


def test_gravityOnlyIsStill_butVibrationIsNot():
    """The discriminator is deviation from 1 g, not the raw magnitude -- a parked
    car still reads ~9.81, and a driving one deviates around it."""
    d = ParkDetector(stillSeconds=20.0, minSessionSeconds=0.0)
    for t in range(0, 41, 5):
        d.note(magnitudeMs2=9.79, nowS=float(t), sessionElapsedS=float(t))
    assert d.parked is True

    d2 = ParkDetector(stillSeconds=20.0, minSessionSeconds=0.0)
    for i, t in enumerate(range(0, 41, 5)):
        d2.note(magnitudeMs2=9.81 + (0.6 if i % 2 else -0.6), nowS=float(t),
                sessionElapsedS=float(t))
    assert d2.parked is False
