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
    "F5M33_FINAL_DRIVE",
    "F5M33_GEAR_RATIOS",
    "GearBand",
    "GearDeriver",
    "GearReading",
    "MPH_PER_KPH",
    "REASON_AMBIGUOUS",
    "REASON_BELOW_THRESHOLD",
    "REASON_ENGAGED",
    "REASON_NOT_CALIBRATED",
    "REASON_NO_BAND",
    "REASON_NO_DATA",
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

# Freshness window for a SPEED/RPM sample, seconds. GROUNDED TO THE PIPE, not
# picked for feel: the OBD link sustains ~4-5 PIDs/sec over Bluetooth
# (specs/obd2-research.md), so a reading older than 2 s means several polls have
# been missed and the pipe is not keeping up -- not that the car is holding
# still. Rex-derived from the documented poll rate, config-parameterised
# (pi.gear.maxAgeSec) and flagged to Spool/Atlas for confirmation against a real
# drive, following the DEFAULT_GRAVITY_TAU_S precedent (US-478).
DEFAULT_MAX_AGE_S = 2.0

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
    """

    available: bool
    gear: int | None
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
        """
        self._bands = tuple(bands)
        self._minSpeedKph = minSpeedKph
        self._minRpm = minRpm
        self._debounceS = debounceS
        self._maxAgeS = maxAgeS
        self._candidateGear: int | None = None
        self._candidateSinceS: float = 0.0

    def update(
        self,
        *,
        speed: Reading | None,
        rpm: Reading | None,
        nowS: float,
    ) -> GearReading:
        """Feed one aligned SPEED/RPM pair and get the current opinion.

        Args:
            speed: Latest vehicle speed in km/h, or None if never seen.
            rpm: Latest engine speed in rpm, or None if never seen.
            nowS: Monotonic seconds now, for freshness and debounce.

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
        if speedKph is _MISSING or rpmValue is _MISSING:
            return self._absent(REASON_NO_DATA)
        if speedKph is _STALE or rpmValue is _STALE:
            return self._absent(REASON_STALE)

        # mypy: both are real floats past the sentinel checks above.
        assert isinstance(speedKph, float) and isinstance(rpmValue, float)

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

    def _debounced(self, gear: int, nowS: float) -> GearReading:
        """Publish ``gear`` only once it has held for the debounce window."""
        if gear != self._candidateGear:
            self._candidateGear = gear
            self._candidateSinceS = nowS
            return GearReading(available=False, gear=None, reason=REASON_SETTLING)
        if nowS - self._candidateSinceS < self._debounceS:
            return GearReading(available=False, gear=None, reason=REASON_SETTLING)
        return GearReading(available=True, gear=gear, reason=REASON_ENGAGED)

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
    )
