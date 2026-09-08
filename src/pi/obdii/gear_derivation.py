################################################################################
# File Name: gear_derivation.py
# Purpose/Description: US-630 (F-138) GEAR derivation. The 4G63 exposes no gear
#                      PID, so the GEAR glyph has been permanently blank. Gear is
#                      DERIVED here, ONCE, from the realtime SPEED and RPM SSOT --
#                      never recomputed per consumer (ssot-design-pattern rule B).
#                      Pure: no bus, no I2C, no state file, no clock of its own.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex (US-630) | Initial -- ratio->band derivation with typed
#               |              | absence for every non-resolving branch, Spool's
#               |              | thresholds + debounce, and the grounded F5M33
#               |              | band formula. Ships DARK (pi.gear.enabled).
# 2026-09-07    | Rex (US-687-a) | NEUTRAL. RPM > 0 with SPEED == 0 is a
#               |              | determinate state, not an absence -- the tile
#               |              | showed `below_threshold` at every stoplight.
# 2026-09-07    | Rex (US-687-b) | PARK. A HEALTHY link that has stopped
#               |              | reporting RPM for longer than parkDwellSec is
#               |              | the engine switched off. Keyed on UNUSABLE
#               |              | (missing OR stale), because readings age out
#               |              | rather than disappear.
# ================================================================================
################################################################################

"""Derive the engaged gear from vehicle SPEED and engine RPM (US-630).

WHY THIS EXISTS: punch-list item 1.4 -- the GEAR tile reads ``-- / no source``
because this car has no gear PID.  The renderer half has existed since US-508
(``carousel.js`` ``gearView``); the producer never did.  This module is that
producer's computation.

THE ONE RULE, and every guard below serves it: **a wrong gear is worse than no
gear.**  The engine speed / road speed ratio identifies a gear only while the
clutch is engaged and both readings are live.  Clutch-in, coasting, creeping
below walking pace and a shift in progress all LEGITIMATELY match no gear, and
each resolves to a typed absence carrying its own reason -- so the card can
distinguish "no producer" from "the producer is honestly refusing to guess".

WHAT IS GROUNDED AND WHAT IS NOT (PM Rule 7):

* The transmission ratios, final drive and tyre circumference in this module are
  transcribed from ``specs/grounded-knowledge.md`` (Road Race Engineering,
  factory Shop Manual CD, plus Spool's cross-check).  :func:`rpmPerKph`
  reproduces BOTH figures Spool published from them -- ~24 mph/1000 rpm in 5th,
  and drive 18's 57.6 mph computed in 3rd -- and tests pin both.
* The BANDS the derivation actually matches against are **injected**, not
  invented here.  With none configured the derivation reports
  ``not_calibrated`` and no gear, which is the shipped default.  See
  ``offices/pm/blockers/BL-us630-measured-gear-bands-were-never-recorded.md``.

Consumers get :class:`GearReading`; ``toStateDict()`` emits exactly the
``{available, gear, reason}`` shape ``carousel.js`` already reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

__all__ = [
    "DEFAULT_DEBOUNCE_S",
    "DEFAULT_MAX_AGE_S",
    "DEFAULT_MIN_RPM",
    "DEFAULT_MIN_SPEED_KPH",
    "DEFAULT_PARK_DWELL_S",
    "F5M33_FINAL_DRIVE",
    "F5M33_GEAR_RATIOS",
    "GEAR_NEUTRAL",
    "GEAR_PARK",
    "GearBand",
    "GearDeriver",
    "GearReading",
    "MPH_PER_KPH",
    "REASON_AMBIGUOUS",
    "REASON_BELOW_THRESHOLD",
    "REASON_ENGAGED",
    "REASON_NEUTRAL",
    "REASON_NOT_CALIBRATED",
    "REASON_NO_BAND",
    "REASON_NO_DATA",
    "REASON_PARK",
    "REASON_SETTLING",
    "REASON_STALE",
    "Reading",
    "TIRE_CIRCUMFERENCE_M",
    "bandsFromGearRatios",
    "createGearDeriverFromConfig",
    "rpmPerKph",
]

# --------------------------------------------------------------------------
# Reasons. Every non-resolving branch names ITSELF, because the operator needs
# to tell a dead pipe from an uncalibrated one from a clutch pedal.
# --------------------------------------------------------------------------
REASON_ENGAGED = "engaged"
REASON_NEUTRAL = "neutral"
REASON_PARK = "park"
REASON_NO_DATA = "no_data"
REASON_STALE = "stale"
REASON_NOT_CALIBRATED = "not_calibrated"
REASON_BELOW_THRESHOLD = "below_threshold"
REASON_NO_BAND = "no_band_match"
REASON_AMBIGUOUS = "ambiguous"
REASON_SETTLING = "settling"

# --------------------------------------------------------------------------
# Spool's semantics, transcribed from the US-508 contract already recorded in
# carousel.js: "-- when ambiguous (speed < 5 km/h, rpm < 900, ratio > 15% off
# the nearest gear), N rolling neutral, >= 2 s debounce. NEVER a wrong number."
# --------------------------------------------------------------------------
DEFAULT_MIN_SPEED_KPH = 5.0
DEFAULT_MIN_RPM = 900.0
DEFAULT_DEBOUNCE_S = 2.0

# US-687-a: the glyph the NEUTRAL state publishes. A STRING among otherwise
# integer gears, because `carousel.js` gearView has branched on the literal
# `gear === "N"` since US-508 -- this producer is meeting a renderer contract
# that already existed, not inventing one.
GEAR_NEUTRAL = "N"

# US-687-b: the glyph the PARK state publishes. Also a string, and unlike "N"
# this contract is NEW ON BOTH SIDES -- `carousel.js` handled "P" NOWHERE before
# this story, so a producer emitting it without the renderer change would have
# rendered as `--`. That is the renderer-with-no-producer defect wearing the
# other shoe, and it is why this story ships both halves together.
GEAR_PARK = "P"

# How long RPM must stay UNUSABLE, with a healthy link, before the tile says the
# car is parked. Seconds. Spool ratified 20.0 on 2026-09-07, and the value sits
# in the middle of a window with a measured bound on EACH side:
#
# * FLOOR ~13 s. Across drives 64-68 (2,141 RPM samples) the worst in-drive
#   inter-sample gap was 13 s, with 4 gaps >= 10 s and 31 >= 4 s -- independently
#   consistent with Spool's 11-12 s gaps on drive 66. Below the floor an ordinary
#   bus stall paints Park at 60 mph. 20.0 is 1.5x the measured worst case.
#
# * CEILING ~45 s, AND IT IS NOT DRIVER PERCEPTION. At key-off the Pi loses
#   fuse-box power and runs a bounded pre-shutdown pipeline (perTask=20s
#   totalCap=45s, from powerwatch's own startup line), so the Pi has roughly 45 s
#   of life after the event that stops the RPM data -- and this dwell counts down
#   INSIDE that budget. At 20 s, P appears with ~25 s of panel left; at 30 s,
#   ~15 s; at 45 s or more it NEVER RENDERS AT ALL. The next person to "harden"
#   this will reach for a bigger number: the floor is the only half that is
#   obvious, which is exactly why the ceiling is written here.
#
# THE CEILING IS SOFT AND THE COUPLING IS DELIBERATE, NOT INCIDENTAL: it depends
# on the pre-shutdown budget, which is under active work. IF `totalCap` IS EVER
# SHORTENED, THIS VALUE MUST BE RE-CHECKED AGAINST IT.
#
# NOT `DEFAULT_DEBOUNCE_S`. That is 2.0 and is sized for gear-to-gear
# transitions; Park is a persistent state. One number answers one question.
DEFAULT_PARK_DWELL_S = 20.0

# Freshness window for a SPEED/RPM sample, seconds. Spool ruled 3.0 on
# 2026-09-06 (US-686), and the number is the smaller half of the story.
#
# 🔴 THE CADENCE ANY RATIONALE FOR THIS VALUE MUST CITE IS THE **MEASURED
# PER-PID PERIOD**: 2.206-2.249 s for SPEED (Atlas, 2026-09-06, 3,494 paired
# SPEED/RPM samples across drives 64-67). NOT an aggregate bus rate, and NOT
# `pi.pollingTiers` -- that block has ZERO importers in `src/`, the live poll
# list is a flat `pi.realtimeData.parameters`, and it describes a system this
# project does not have. It has now misled two builds (A-28).
#
# WHY 2.0 WAS A UNIT ERROR AND NOT AGGRESSIVE CALIBRATION. This constant answers
# *how long may I still believe this reading?*; the period above answers *how
# often am I told?* No value of the first can be shorter than the second. At 2.0
# a sample aged out BEFORE ITS SUCCESSOR COULD ARRIVE, every cycle, by
# construction -- so `stale` fired in each cycle and cleared the debounce
# candidate, and the tile could never latch. Drive 64's census is exactly that
# prediction: below_threshold 776 / stale 722 / settling 409 / **engaged 0**.
#
# WHY 3.0 AND NOT MORE. This is also THE MAXIMUM TIME THE TILE CAN DISPLAY A
# GEAR THE CAR HAS ALREADY LEFT, so the window is bounded above by the error it
# permits. A 4G63 shift completes well inside 1 s; at 3.0 (1.33x the period) a
# stale glyph self-corrects within roughly the duration of the shift that
# invalidated it, and a reading that has missed TWO polls is still rejected. 2.5
# is only 1.11x, and 11-12 s inter-sample gaps were measured on drive 66 -- it
# passes a replay and fails the road. 4.0 buys nothing measurable and doubles
# the wrong-answer window.
#
# Config-parameterised as `pi.gear.maxAgeSec`. The value ALSO lives in
# `src/common/config/validator.py` DEFAULTS and in `config.json`;
# `tests/pi/obdii/test_gear_max_age_grounding.py` is the lint that keeps all
# three equal and keeps every one of them above the measured period.
DEFAULT_MAX_AGE_S = 3.0

# --------------------------------------------------------------------------
# Grounded vehicle facts -- specs/grounded-knowledge.md. Transcribed, not
# derived here. If these ever disagree with that table, that table wins.
# --------------------------------------------------------------------------
# Stock F5M33 5-speed (2G FWD turbo). CIO-confirmed stock and unmodified.
F5M33_GEAR_RATIOS: dict[int, float] = {
    1: 3.090,
    2: 1.833,
    3: 1.217,
    4: 0.888,
    5: 0.741,
}
F5M33_FINAL_DRIVE = 4.153

# Potenza 205/55R16 rolling circumference (Spool, 2026-06-01 tyre spec).
TIRE_CIRCUMFERENCE_M = 1.985

# Exact statute-mile conversion, for the cross-check tests that reproduce
# Spool's published mph figures.
MPH_PER_KPH = 0.621371

# km/h -> metres travelled per minute.
_METRES_PER_MINUTE_PER_KPH = 1000.0 / 60.0


@dataclass(frozen=True)
class Reading:
    """One timestamped scalar off the realtime SSOT.

    Args:
        value: The reading itself (km/h for SPEED, rpm for RPM).
        tsS: Monotonic seconds at which the reading was taken -- compared
            against ``nowS`` to decide freshness, never used as wall clock.
    """

    value: float | None
    tsS: float


@dataclass(frozen=True)
class GearBand:
    """One measured engine-speed / road-speed band that identifies a gear.

    HALF-OPEN, ``[ratioMin, ratioMax)``, as Atlas published the measured table:
    "low INCLUSIVE, high EXCLUSIVE".  This is not a taste: the measured bands
    are CONTIGUOUS -- 5th ends at 29.5 and 4th begins at 29.5 -- so an inclusive
    upper bound makes all four shared edges match TWO bands, and the derivation
    correctly reports ``ambiguous`` at exactly the ratios a shift passes
    through.  Left-open rather than right-open so 5th keeps its own 0.0 and no
    hole opens at the bottom of the table.

    Args:
        gear: The gear this band identifies (1-5).
        ratioMin: Inclusive lower bound, rpm per km/h.
        ratioMax: EXCLUSIVE upper bound, rpm per km/h.
    """

    gear: int
    ratioMin: float
    ratioMax: float

    def contains(self, ratio: float) -> bool:
        """Whether ``ratio`` (rpm per km/h) falls inside this half-open band."""
        return self.ratioMin <= ratio < self.ratioMax


@dataclass(frozen=True)
class GearReading:
    """The derivation's published opinion at one instant.

    ``gear`` is None whenever ``available`` is False -- there is no
    last-known-good and no partial state.  ``reason`` is populated in BOTH
    cases so a consumer never has to infer why a gear is missing.

    ``gear`` is an ``int`` for a derived gear, and one of TWO strings for the
    determinate non-gear states: :data:`GEAR_NEUTRAL` (``"N"``, US-687-a) and
    :data:`GEAR_PARK` (``"P"``, US-687-b).  ``gearView`` tests both with ``===``
    before it tests for a number, so every consumer must branch on the strings
    BEFORE assuming arithmetic -- a consumer that does `gear > 0` on this field
    is one string away from a TypeError.
    """

    available: bool
    gear: int | str | None
    reason: str

    def toStateDict(self) -> dict[str, Any]:
        """Serialise to the states/gear shape carousel.js gearView() reads.

        Returns:
            ``{"available": bool, "gear": int | None, "reason": str}``.
        """
        return {"available": self.available, "gear": self.gear, "reason": self.reason}


def rpmPerKph(
    *,
    gearRatio: float,
    finalDrive: float,
    tireCircumferenceM: float,
) -> float:
    """Engine rpm per km/h of road speed, in one gear.

    The closed form behind every band: road speed -> wheel revolutions ->
    engine revolutions through the gearbox and final drive.

    Args:
        gearRatio: Transmission ratio for the gear (e.g. 1.217 for 3rd).
        finalDrive: Final-drive ratio (4.153 on this car).
        tireCircumferenceM: Rolling circumference in metres.

    Returns:
        Engine rpm per km/h.

    Raises:
        ValueError: If the tyre circumference is not positive (the division
            would be meaningless, and a silent inf would poison every band).
    """
    if tireCircumferenceM <= 0.0:
        raise ValueError("tireCircumferenceM must be positive")
    wheelRevPerMinutePerKph = _METRES_PER_MINUTE_PER_KPH / tireCircumferenceM
    return wheelRevPerMinutePerKph * finalDrive * gearRatio


def bandsFromGearRatios(
    *,
    gearRatios: dict[int, float],
    finalDrive: float,
    tireCircumferenceM: float,
    tolerancePct: float,
) -> tuple[GearBand, ...]:
    """Build theoretical bands around each gear's closed-form ratio.

    NOTE: ``tolerancePct`` is deliberately REQUIRED. It is a calibration
    input with a real consequence -- at Spool's +/-15% the 4th and 5th bands
    OVERLAP between ~26.3 and ~29.7 rpm/kph (ordinary highway cruising), and
    the derivation reports ``ambiguous`` throughout that overlap. A test pins
    that overlap so the consequence stays visible. This function will not pick
    a tolerance on the caller's behalf.

    Args:
        gearRatios: Gear number -> transmission ratio.
        finalDrive: Final-drive ratio.
        tireCircumferenceM: Rolling circumference in metres.
        tolerancePct: Half-width of each band, as a percentage of its centre.

    Returns:
        One band per supplied gear, ordered by gear number.

    Raises:
        ValueError: If ``tolerancePct`` is negative.
    """
    if tolerancePct < 0.0:
        raise ValueError("tolerancePct must not be negative")
    bands: list[GearBand] = []
    for gear in sorted(gearRatios):
        centre = rpmPerKph(
            gearRatio=gearRatios[gear],
            finalDrive=finalDrive,
            tireCircumferenceM=tireCircumferenceM,
        )
        halfWidth = centre * (tolerancePct / 100.0)
        bands.append(
            GearBand(gear=gear, ratioMin=centre - halfWidth, ratioMax=centre + halfWidth)
        )
    return tuple(bands)


class GearDeriver:
    """Stateful gear derivation over a stream of SPEED/RPM readings.

    The only state held is the debounce candidate.  There is deliberately NO
    last-published-gear fallback: when the inputs stop resolving, the output
    drops to a typed absence on the very next update.  A held gear would be a
    fabricated reading of a pipe that has gone quiet, which is exactly the
    class of defect the V0.29 sweep exists to remove.
    """

    def __init__(
        self,
        *,
        bands: tuple[GearBand, ...] = (),
        minSpeedKph: float = DEFAULT_MIN_SPEED_KPH,
        minRpm: float = DEFAULT_MIN_RPM,
        debounceS: float = DEFAULT_DEBOUNCE_S,
        maxAgeS: float = DEFAULT_MAX_AGE_S,
        parkDwellS: float = DEFAULT_PARK_DWELL_S,
    ) -> None:
        """Build a deriver.

        Args:
            bands: Measured bands to match against. EMPTY BY DEFAULT -- an
                unconfigured deriver reports ``not_calibrated`` rather than
                falling back to a theoretical table.
            minSpeedKph: Road-speed floor below which no gear is reported.
            minRpm: Engine-speed floor below which no gear is reported.
            debounceS: How long a candidate gear must hold before publishing.
            maxAgeS: Freshness window for each input reading.
            parkDwellS: How long RPM must stay unusable before reporting P.
        """
        self._bands = tuple(bands)
        self._minSpeedKph = minSpeedKph
        self._minRpm = minRpm
        self._debounceS = debounceS
        self._maxAgeS = maxAgeS
        self._parkDwellS = parkDwellS
        self._candidateGear: int | None = None
        self._candidateSinceS: float = 0.0
        # When the CURRENT RPM outage began, or None while RPM is usable. None
        # rather than 0.0 on purpose: "nobody has looked yet" and "unusable since
        # the epoch" are different facts, and conflating them paints Park on the
        # first tick of every boot.
        self._rpmUnusableSinceS: float | None = None

    def update(
        self,
        *,
        speed: Reading | None,
        rpm: Reading | None,
        nowS: float,
        linkHealthy: bool = False,
    ) -> GearReading:
        """Feed one aligned SPEED/RPM pair and get the current opinion.

        Args:
            speed: Latest vehicle speed in km/h, or None if never seen.
            rpm: Latest engine speed in rpm, or None if never seen.
            nowS: Monotonic seconds now, for freshness and debounce.
            linkHealthy: Whether the OBD link is up AND linked (US-687-b).
                DEFAULTS FALSE, which is the fail-safe direction: a caller that
                has not considered the question gets no Park rather than a
                confident claim that the car is switched off. The orchestrator
                supplies the real value from ``_gatherObdLinkState``.

        Returns:
            The gear, or a typed absence naming why there is none.
        """
        # Configuration dominates: with no band table this can NEVER resolve,
        # so say so plainly rather than reporting whichever input happens to be
        # missing this instant (5-tier classification: config errors fail fast
        # with a clear message).
        if not self._bands:
            return self._absent(REASON_NOT_CALIBRATED)

        speedKph = self._liveValue(speed, nowS)
        rpmValue = self._liveValue(rpm, nowS)

        # US-687-b: PARK, and it sits HERE -- BEFORE the no_data and stale
        # guards -- because both of those already catch the input shape Park is
        # made of. Copying US-687-a's placement (after the guards) would put the
        # branch somewhere control flow never reaches.
        #
        # THE TRIGGER IS "UNUSABLE", NOT "MISSING", and that distinction is the
        # whole story. The orchestrator NEVER CLEARS `_lastRpmReading` -- it ages
        # out, so `_liveValue` returns _STALE and not _MISSING. A branch written
        # against the missing sentinel alone would fire only on a cold boot
        # before any reading was taken, which is not when anybody is looking at
        # this tile: after a real drive the reading is STALE, and that is the
        # normal parked state.
        parked = self._parkOpinion(rpmValue, nowS, linkHealthy)
        if parked is not None:
            return parked

        if speedKph is _MISSING or rpmValue is _MISSING:
            return self._absent(REASON_NO_DATA)
        if speedKph is _STALE or rpmValue is _STALE:
            return self._absent(REASON_STALE)

        # mypy: both are real floats past the sentinel checks above.
        assert isinstance(speedKph, float) and isinstance(rpmValue, float)

        # US-687-a: NEUTRAL. An engine that is turning while the car is
        # stationary is transmitting NO DRIVE RATIO -- a determinate state, and
        # the state this car spends most of a drive in (63 % of drive 64's SPEED
        # rows read zero). It sits HERE, deliberately, between two guards:
        #
        # * AFTER freshness, because a zero that arrived a minute ago is not
        #   evidence the car is stopped NOW.
        # * BEFORE the floors, because SPEED == 0 is below every speed floor
        #   there could be -- and `below_threshold` is what the tile has been
        #   showing at every stoplight, which is a machine token standing in
        #   for a fact the car states plainly.
        #
        # THE TRIGGER IS `rpmValue > 0`, NOT `rpmValue >= self._minRpm` (Spool,
        # ratified). The 900 rpm floor exists to make the RATIO trustworthy;
        # in neutral no ratio is being computed, so the floor answers a question
        # nobody asked. Measured idle on this car is 800 rpm average / 684 min,
        # with 91.6 % of stationary samples below 900 -- gate on the floor and
        # the branch is dead at exactly the stoplight it exists for.
        #
        # SPEED is compared to zero EXACTLY, not to a small epsilon: PID 0x0D
        # decodes to whole km/h, so a stopped car reports a clean 0. A creeping
        # 0.1 km/h is a car that IS transmitting a ratio, just not a trustworthy
        # one -- which is what `below_threshold` below already says correctly.
        if rpmValue > 0.0 and speedKph == 0.0:
            return self._neutral()

        # Below either floor the ratio is noise-dominated and the clutch is
        # commonly slipping -- there is no gear FACT here to report. This also
        # makes the ratio division below safe.
        if speedKph < self._minSpeedKph or rpmValue < self._minRpm:
            return self._absent(REASON_BELOW_THRESHOLD)

        ratio = rpmValue / speedKph
        matches = [band.gear for band in self._bands if band.contains(ratio)]
        if not matches:
            # Clutch in, coasting, or mid-shift. A real operating state.
            return self._absent(REASON_NO_BAND)
        if len(matches) > 1:
            # Atlas's conditionalOutcome: ambiguous means NA. Proximity to one
            # band's centre is NOT a tie-breaker -- that is guessing with extra
            # steps.
            return self._absent(REASON_AMBIGUOUS)

        return self._debounced(matches[0], nowS)

    def _liveValue(self, reading: Reading | None, nowS: float) -> Any:
        """Resolve a reading to a float, or a _MISSING / _STALE sentinel."""
        if reading is None or reading.value is None:
            return _MISSING
        value = float(reading.value)
        if not isfinite(value):
            return _MISSING
        if nowS - reading.tsS > self._maxAgeS:
            return _STALE
        return value

    def _parkOpinion(
        self, rpmValue: Any, nowS: float, linkHealthy: bool
    ) -> GearReading | None:
        """Advance the park dwell and return P, or None to keep deciding.

        TWO WAYS INTO PARK, and they are deliberately not the same shape,
        because the evidence behind them is not the same evidence:

        * **RPM UNUSABLE** (missing or stale) plus a healthy link, held for
          ``parkDwellS``.  Absence is ambiguous -- it is *engine off OR link
          down OR bus stall* -- so it needs BOTH corroborations: the link
          condition rules out the dead dongle, and the dwell rules out the
          stall.  Neither alone is sufficient and the story's "the trap" clause
          is about exactly that.
        * **RPM PRESENT, FRESH AND ZERO.**  Immediate, and NOT gated on
          ``linkHealthy``.  A fresh reading of 0 is the ECU affirmatively
          reporting a stopped engine -- it is a MEASUREMENT, not an absence, so
          there is nothing for a dwell to disambiguate.  Nor is a separate
          health flag consulted: the reading itself is proof the link
          delivered, and asking a second source whether the link is alive when
          the link just answered would be a second acquisition path for one
          fact.  A dead dongle cannot reach this branch, because a dead dongle
          produces no reading to be zero.

        Args:
            rpmValue: The resolved RPM -- a float, or a _MISSING/_STALE
                sentinel.
            nowS: Monotonic seconds now.
            linkHealthy: Whether the OBD link is up AND linked.

        Returns:
            A Park reading, or None if this tick is not Park.
        """
        if rpmValue is _MISSING or rpmValue is _STALE:
            if self._rpmUnusableSinceS is None:
                self._rpmUnusableSinceS = nowS
            heldS = nowS - self._rpmUnusableSinceS
            if linkHealthy and heldS >= self._parkDwellS:
                return self._park()
            return None

        # RPM is usable again: the CURRENT outage is over. Cleared rather than
        # accumulated, because two 18 s stalls on a flaky link are not one 36 s
        # parking event -- the dwell times the outage in progress, nothing else.
        self._rpmUnusableSinceS = None
        if isinstance(rpmValue, float) and rpmValue == 0.0:
            return self._park()
        return None

    def _park(self) -> GearReading:
        """Publish PARK, dropping any debounce candidate (US-687-b).

        NOT debounced. ``parkDwellS`` IS the wait, and it was sized against a
        45 s pre-shutdown budget -- stacking ``debounceS`` on top would silently
        add another ``debounceS`` to the delay and put that argument out by that
        much of the budget it was measured against.

        THE REAL KEY-OFF-TO-GLYPH DELAY IS ``parkDwellS + maxAgeS``, not
        ``parkDwellS`` alone: the dwell clock starts when RPM becomes UNUSABLE,
        and a PRESENT reading does not become unusable until it ages out, so one
        whole freshness window elapses before the dwell begins. US-686 raised
        ``maxAgeS`` 2.0 -> 3.0 and therefore moved that sum as well. It is
        deliberately NOT written down as a figure here -- it is arithmetic on two
        tunable constants, and the last two stories each invalidated whichever
        figure the one before had recorded. Recompute it; do not quote it.
        ``test_gear_park.py`` pins it as that arithmetic.

        The candidate IS cleared, for the reason US-687-a's ``_neutral`` records:
        without it, switching off in 2nd and restarting would republish the
        pre-park 2 on the first moving sample, a gear the car is not yet in.

        WHAT P CLAIMS: the link is up and the engine is not reporting a speed.
        NOT that a lever is in Park -- this car is a manual and has no Park
        detent at all. The CIO ruled the glyph on the record ("we're not doing
        anything with that information other than displaying it"), and that
        ruling holds only while gear stays DISPLAY-ONLY: no column, no sync, no
        analysis. US-693 is the lint that keeps that true, and if gear ever does
        become persisted this branch must be re-opened, not quietly kept.
        """
        self._candidateGear = None
        self._candidateSinceS = 0.0
        return GearReading(available=True, gear=GEAR_PARK, reason=REASON_PARK)

    def _debounced(self, gear: int, nowS: float) -> GearReading:
        """Publish ``gear`` only once it has held for the debounce window."""
        if gear != self._candidateGear:
            self._candidateGear = gear
            self._candidateSinceS = nowS
            return GearReading(available=False, gear=None, reason=REASON_SETTLING)
        if nowS - self._candidateSinceS < self._debounceS:
            return GearReading(available=False, gear=None, reason=REASON_SETTLING)
        return GearReading(available=True, gear=gear, reason=REASON_ENGAGED)

    def _neutral(self) -> GearReading:
        """Publish NEUTRAL, dropping any debounce candidate (US-687-a).

        NOT debounced. The debounce exists to stop the glyph flickering between
        NUMBERED gears while a ratio settles; ``SPEED == 0`` is exact and has
        nothing to settle, and a debounced N would leave the tile dark for the
        first two seconds of every stop.

        The candidate IS cleared, exactly as a typed absence clears it: without
        that, rolling to a stop in 2nd and pulling away again would republish
        the pre-stop 2 on the first moving sample -- a gear the car is not yet
        in, which is the one thing this producer must never print.

        WHAT N CLAIMS: the engine is running and no drive ratio is being
        transmitted. NOT that the lever is in neutral -- on a manual gearbox
        this state is bit-for-bit identical to first-with-the-clutch-down.
        There is no torque path either way, so the glyph is honest; anyone
        analysing N-time must not read it as lever position.
        """
        self._candidateGear = None
        self._candidateSinceS = 0.0
        return GearReading(available=True, gear=GEAR_NEUTRAL, reason=REASON_NEUTRAL)

    def _absent(self, reason: str) -> GearReading:
        """Drop any candidate and report a typed absence with ``reason``."""
        self._candidateGear = None
        self._candidateSinceS = 0.0
        return GearReading(available=False, gear=None, reason=reason)


# Sentinels for _liveValue. Module-private; never published.
_MISSING = object()
_STALE = object()


def createGearDeriverFromConfig(config: dict[str, Any]) -> GearDeriver | None:
    """Build the gear deriver from validated config, or None when dark.

    Ships DARK (connect-when-wired, the pi.bus.enabled precedent): returns None
    unless ``pi.gear.enabled`` is set.  Enabled but with no ``pi.gear.bands``
    yields a deriver that honestly reports ``not_calibrated`` -- which is the
    correct state until the measured bands are recorded (BL-us630).

    Args:
        config: Validated tier-aware config (reads the ``pi`` section).

    Returns:
        A ready GearDeriver, or None when disabled.
    """
    gear = config.get("pi", {}).get("gear", {})
    if not gear.get("enabled", False):
        return None

    bands = tuple(
        GearBand(
            gear=int(entry["gear"]),
            ratioMin=float(entry["ratioMin"]),
            ratioMax=float(entry["ratioMax"]),
        )
        for entry in gear.get("bands", [])
    )
    return GearDeriver(
        bands=bands,
        minSpeedKph=float(gear.get("minSpeedKph", DEFAULT_MIN_SPEED_KPH)),
        minRpm=float(gear.get("minRpm", DEFAULT_MIN_RPM)),
        debounceS=float(gear.get("debounceSec", DEFAULT_DEBOUNCE_S)),
        maxAgeS=float(gear.get("maxAgeSec", DEFAULT_MAX_AGE_S)),
        parkDwellS=float(gear.get("parkDwellSec", DEFAULT_PARK_DWELL_S)),
    )
