################################################################################
# File Name: drive_phases.py
# Purpose/Description: ARCH-058 -- the four-phase drive schedule and park detector
#   for a ZERO-INTERACTION data-collection session. Pure logic: no hardware, no
#   HTTP, no clock of its own.
# Author: Atlas (architect) -- CIO-directed build; override on ARCH-058
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial -- bracketed schedule, edge-triggered
#               | (ARCH-058)     | transitions, park auto-end, circle prompt.
# ================================================================================
################################################################################
"""What mechanism is collecting right now, and when does the session end?

🔴 THE OPERATING CONSTRAINTS, which are safety constraints and not preferences.
The CIO is DRIVING. He has no keyboard in the car, he is off WiFi for the whole
session so nothing can be driven over SSH, the screen is 3.5 inches, and for
safety he should not be touching or manipulating anything. **So the session takes
ZERO interaction**: it is started before he leaves, it advances on a clock, and it
ENDS ITSELF -- including restarting the collector it stopped.

⇒ Every end path in this module funnels into one place, and the restore is in a
``finally``. A session that ended without restoring ``eclipse-obd`` would leave the
car recording nothing for the rest of the ignition cycle.

🔴 WHY THE CONTROL RUNS AT BOTH ENDS. The CIO proposed reverting to the original
algorithm for the drive home, and it is the right call for a reason worth naming:
it makes the run **bracketed** -- ORIGINAL -> A -> B -> ORIGINAL. If the closing
control disagrees with the opening one, something changed DURING the drive
(temperature, the mount, the magnetic environment), and without the bracket that
drift is silently attributed to A or B.

🔴 WHY THE SCREEN ASKS FOR CIRCLES. MEASURED from the CIO's own 2026-09-15 GPX:
worst-case coverage of 36 heading bins was **3% at a 2-minute window** and only
**81% at 15 minutes**. A hard-iron offset is the CENTRE OF A CIRCLE and cannot be
located from an arc, so angular SPREAD -- not distance and not lap count -- is what
gates a fit. Continuous slow circles reach it in well under a minute, which is why
the prompt leads each phase.

⚠️ CORRECTION TO MY OWN EARLIER CLAIM (Atlas, 2026-09-25). I told the CIO that a
rectangular block gives "FOUR headings, 4/36 = 11%, forever" and could never
calibrate a magnetometer. **That is WRONG, and the test that now guards it is
`test_aRectangularBlockDOESReachFittableCoverage` -- its first version asserted my
claim and FAILED.** A vehicle's heading is CONTINUOUS: it cannot teleport from
north to east, so every 90 deg corner sweeps through all the intermediate bearings
and four corners traverse the full circle. ⇒ **Three laps of a block ARE fittable
and no parking lot is required.** What circles buy is faster and more EVENLY
WEIGHTED coverage -- the fit is better conditioned -- not the difference between
possible and impossible.

⚠️ WHAT THIS MODULE DOES NOT DECIDE. It does not choose or configure the
acquisition mechanisms -- it only says which one should be running and for how
long. Binding a mechanism to hardware is the console's job.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "CIRCLE_PROMPT_S",
    "COVERAGE_BINS",
    "COVERAGE_FITTABLE",
    "COVERAGE_MAX_GAP_S",
    "TurnCoverage",
    "DEFAULT_PHASES",
    "MECH_KEEPALIVE",
    "MECH_KEEPALIVE_DRDY",
    "MECH_ORIGINAL",
    "ParkDetector",
    "Phase",
    "PhaseSchedule",
    "PhaseState",
]

#: The acquisition mechanisms, in the order they are exercised.
#:
#: ``MECH_ORIGINAL``  -- production's pre-ARCH-057 path (bypass, no keep-alive).
#:                       MEASURED 0/20 for liveness, so it is expected to FREEZE.
#:                       That is the point: it is the control.
#: ``MECH_KEEPALIVE``  -- master mode + the runtime keep-alive. MEASURED 20/20.
#: ``MECH_KEEPALIVE_DRDY`` -- as above, plus slave-0 reconfigured to start at ST1
#:                       so DRDY and HOFL are actually read. NEVER MEASURED on
#:                       this hardware, which is exactly why it belongs in a
#:                       harness and not in production.
MECH_ORIGINAL = "original"
MECH_KEEPALIVE = "keepalive"
MECH_KEEPALIVE_DRDY = "keepalive_drdy"

#: How long the "do slow circles" prompt stays up at the head of each phase.
#: Two circles at a walking-to-jogging pace take roughly 70 s; 120 s leaves room
#: to reach the open space without the prompt expiring on the way.
CIRCLE_PROMPT_S: float = 120.0

#: Sectors the compass is divided into for the coverage readout.
COVERAGE_BINS: int = 36

#: Coverage at which a phase is worth advancing from. Chosen from the CIO's
#: own 2026-09-15 GPX, where worst-case coverage was 3% at a 2-minute window
#: and 81% at 15 minutes: 0.70 is comfortably above what a block can ever
#: reach (4/36 = 0.11) and reachable by two slow circles in well under a
#: minute. ⚠️ It is ADVISORY on the screen and never disables the button --
#: see the UI comment for why.
COVERAGE_FITTABLE: float = 0.70

#: Longest sample gap the yaw integral will cross.
COVERAGE_MAX_GAP_S: float = 2.0


@dataclass(frozen=True)
class Phase:
    """One collection phase.

    Attributes:
        label: What the screen shows.
        mechanism: One of the ``MECH_*`` constants.
        seconds: Length, or None for the final open-ended phase.
    """

    label: str
    mechanism: str
    seconds: float | None


#: The shipped schedule. Phase 0 is five minutes at the CIO's request; the two
#: candidate phases are six minutes each (two minutes of circles plus a road
#: segment for GPS truth); the closing control runs until he parks.
DEFAULT_PHASES: tuple[Phase, ...] = (
    Phase("ORIGINAL (control)", MECH_ORIGINAL, 5 * 60.0),
    Phase("KEEP-ALIVE (master)", MECH_KEEPALIVE, 6 * 60.0),
    Phase("KEEP-ALIVE + DRDY", MECH_KEEPALIVE_DRDY, 6 * 60.0),
    Phase("ORIGINAL (drift check)", MECH_ORIGINAL, None),
)


@dataclass(frozen=True)
class PhaseState:
    """Where the session is right now.

    Attributes:
        index: Zero-based phase index.
        phase: The phase itself.
        elapsedInPhaseS: Seconds since this phase began.
        remainingS: Seconds until the next switch, or None when open-ended.
        promptCircles: Whether the screen should be asking for slow circles.
        total: How many phases there are, for the "n of N" display.
    """

    index: int
    phase: Phase
    elapsedInPhaseS: float
    remainingS: float | None
    promptCircles: bool
    total: int


class PhaseSchedule:
    """Maps session elapsed time onto a phase, and reports SWITCHES once.

    :meth:`at` is pure -- it may be called as often as the UI likes.
    :meth:`advanceTo` is stateful and edge-triggered: it returns the new state
    exactly once per transition, which is what drives the banner and the
    mechanism change.
    """

    def __init__(self, phases: Sequence[Phase] = DEFAULT_PHASES) -> None:
        if not phases:
            raise ValueError("a schedule needs at least one phase")
        openEnded = [i for i, p in enumerate(phases) if p.seconds is None]
        if len(openEnded) != 1 or openEnded[0] != len(phases) - 1:
            # Two open-ended phases make the schedule ambiguous and the second
            # unreachable -- a whole mechanism silently never running.
            raise ValueError("exactly the LAST phase may be open-ended")
        self._phases = tuple(phases)
        self._index = 0

    # -- pure ------------------------------------------------------------------
    def at(self, elapsedS: float) -> PhaseState:
        """The phase state at ``elapsedS`` seconds into the session."""
        remaining = float(elapsedS)
        for i, phase in enumerate(self._phases):
            if phase.seconds is None or remaining < phase.seconds:
                inPhase = max(0.0, remaining)
                left = None if phase.seconds is None else phase.seconds - inPhase
                return PhaseState(
                    index=i,
                    phase=phase,
                    elapsedInPhaseS=inPhase,
                    remainingS=left,
                    promptCircles=inPhase < CIRCLE_PROMPT_S,
                    total=len(self._phases),
                )
            remaining -= phase.seconds
        # Unreachable: the last phase is open-ended, so the loop always returns.
        last = len(self._phases) - 1
        return PhaseState(last, self._phases[last], remaining, None, False,
                          len(self._phases))

    # -- edge-triggered --------------------------------------------------------
    @property
    def current(self) -> PhaseState:
        """The last state :meth:`advanceTo` settled on."""
        phase = self._phases[self._index]
        return PhaseState(self._index, phase, 0.0, None,
                          False, len(self._phases))

    def advanceTo(self, elapsedS: float) -> PhaseState | None:
        """Move the schedule to ``elapsedS``; return the new state on a SWITCH.

        Returns:
            The new :class:`PhaseState` exactly once when the phase index has
            increased, else None.

        ⚠️ Never rewinds. A monotonic clock should not go backwards, but if one
        did, replaying a phase would relabel rows already written under the next
        one -- so the index only ever moves forward.
        """
        state = self.at(elapsedS)
        if state.index > self._index:
            self._index = state.index
            return state
        return None


class ParkDetector:
    """Has the vehicle been demonstrably still long enough to end the session?

    Uses the accelerometer's DEVIATION FROM 1 g rather than its raw magnitude: a
    parked car still reads ~9.81 m/s^2, and a moving one deviates around it. It
    deliberately does not use OBD speed -- the dongle can drop mid-drive, and an
    end condition that depends on the flakiest link in the system is an end
    condition that fails to fire.
    """

    #: Deviation from 1 g below which a sample counts as still. Road vibration and
    #: idle shake comfortably exceed this; sensor noise does not.
    STILL_BAND_MS2: float = 0.25

    def __init__(self, *, stillSeconds: float, minSessionSeconds: float) -> None:
        """
        Args:
            stillSeconds: How long stillness must persist.
            minSessionSeconds: 🔴 Session time before parking may end it at all.
                Without this, the first long red light ends the session and the
                later mechanisms never run.
        """
        self._stillSeconds = float(stillSeconds)
        self._minSession = float(minSessionSeconds)
        self._stillSince: float | None = None
        self._parked = False

    @property
    def parked(self) -> bool:
        """True once stillness has persisted past the threshold."""
        return self._parked

    def note(
        self,
        *,
        magnitudeMs2: float | None,
        nowS: float,
        sessionElapsedS: float,
    ) -> bool:
        """Fold in one accelerometer magnitude.

        Args:
            magnitudeMs2: ``|accel|``, or None when the reading is unavailable.
            nowS: A monotonic timestamp.
            sessionElapsedS: Seconds since the session began.

        Returns:
            :attr:`parked`.

        ⚠️ A ``None`` reading is NOT stillness. Treating an absent accelerometer as
        a parked car would end the session on an instrument fault -- reporting a
        conclusion on the strength of having failed to measure.
        """
        if magnitudeMs2 is None or not math.isfinite(magnitudeMs2):
            self._stillSince = None
            return self._parked
        still = abs(magnitudeMs2 - 9.80665) <= self.STILL_BAND_MS2
        if not still:
            self._stillSince = None
            return self._parked
        if self._stillSince is None:
            self._stillSince = nowS
        if (
            sessionElapsedS >= self._minSession
            and (nowS - self._stillSince) >= self._stillSeconds
        ):
            self._parked = True
        return self._parked


# ============================ BUTTON ADVANCE (CIO, 2026-09-25) ================
#
# 🔴 THE CIO CHOSE THE BUTTON OVER THE CLOCK, and he is right: *"I will be at a
# stop sign each lap so it will not be a big issue."* The button mechanism is also
# the one already BENCH-CHECKED on the Pi (2026-09-18, two rounds), and its label
# always says what pressing it does.
#
# ⚠️ BUT A BUTTON INTRODUCES A RISK A TIMER DID NOT: he can advance before the
# phase has collected enough to be FITTABLE. A timer at least guaranteed duration.
# So the screen has to tell him when it is safe to press -- which is what
# :class:`TurnCoverage` is for.
#
# 🔴 AND COVERAGE MUST BE MEASURED FROM THE GYRO, NOT THE MAGNETOMETER. Phase 0 is
# EXPECTED to freeze -- it is the control -- and a frozen magnetometer would report
# a confident, wrong coverage figure for the one phase whose job is to be broken.
# The gyro is independent of the channel under test, which is the whole point of
# choosing it: ask the instrument a question it can actually answer.


class TurnCoverage:
    """How much of the compass the vehicle has actually turned through.

    Integrates yaw RATE into a heading and bins it into
    :data:`COVERAGE_BINS` sectors. The absolute heading is meaningless (the
    integral starts wherever the phase started and drifts); what matters is the
    SPREAD of directions visited, which is exactly what a hard-iron fit needs.

    ⚠️ Drift is acceptable here and would not be for navigation: over a few
    minutes an in-spec gyro drifts by degrees, which moves a sample between
    adjacent bins and cannot manufacture coverage of a sector the car never faced.
    """

    def __init__(self, bins: int = 36) -> None:
        self._bins = max(4, int(bins))
        self._seen: set[int] = set()
        self._headingRad = 0.0

    @property
    def fraction(self) -> float:
        """Fraction of sectors visited, 0.0-1.0."""
        return len(self._seen) / self._bins

    @property
    def fittable(self) -> bool:
        """Whether there is enough angular spread to locate a circle's centre.

        🔴 The floor is :data:`COVERAGE_FITTABLE`. A rectangular block visits FOUR
        headings -- 4/36 = 11% -- however many times it is lapped, so this is the
        signal that separates "lapped a block" from "drove a circle".
        """
        return self.fraction >= COVERAGE_FITTABLE

    def reset(self) -> None:
        """Start a fresh phase. Coverage is PER PHASE: each mechanism needs its
        own fit, so inheriting the previous phase's spread would report a phase as
        ready when it had turned through nothing."""
        self._seen.clear()
        self._headingRad = 0.0

    def note(self, *, yawRateRadS: float | None, dtS: float) -> None:
        """Integrate one yaw-rate sample.

        Args:
            yawRateRadS: Rotation about the vertical axis, rad/s. None when
                unavailable -- which advances nothing rather than assuming zero.
            dtS: Interval since the previous sample.
        """
        if yawRateRadS is None or not math.isfinite(yawRateRadS):
            return
        if not math.isfinite(dtS) or dtS <= 0.0 or dtS > COVERAGE_MAX_GAP_S:
            # A gap this long makes the integral a guess about what happened in
            # between; skipping it loses a sample, inventing it loses the truth.
            return
        self._headingRad += yawRateRadS * dtS
        sector = int((math.degrees(self._headingRad) % 360.0) / (360.0 / self._bins))
        self._seen.add(sector)
