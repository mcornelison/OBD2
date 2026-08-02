################################################################################
# File Name: pitch_fusion.py
# Purpose/Description: US-521 (F-125) gyro-fused chassis pitch + ZUPT bias
#   update -- the honest pitch source behind states/imu gradePct and the
#   prerequisite the future interim altitude (US-519) integrates.
#
#   THE DEFECT THIS EXISTS TO DELETE (Spool, 2026-08-01): an accelerometer
#   cannot distinguish grade from acceleration -- they are the same measurement.
#   Specific force is ``a_vehicle - g_vector``, so a 0.3 g pull on FLAT ground
#   adds 0.3 g to the forward axis and any accel-derived tilt reads
#   ``atan(0.3)`` = 16.7 degrees of climb. US-478 low-passed the accel over 5 s,
#   which rejects a 1 s event but NOT a 10 s on-ramp (2 tau) -- that contamination
#   propagates almost fully into the "gravity" estimate the grade was read from.
#
#   THE FIX, exactly as Spool specified it:
#     1. GYRO INTEGRATION carries the short term. The gyro sees real chassis
#        rotation and is blind to linear acceleration.
#     2. THE ACCEL CORRECTS THE GYRO ONLY NEAR 1 g. Gyro alone drifts; accel
#        alone is contaminated; neither works standalone. The magnitude gate is
#        what rejects the 16.7-degree phantom: under 0.3 g the specific force is
#        1.044 g, comfortably outside DEFAULT_ACCEL_TRUST_BAND.
#     3. ZUPT at every confirmed stop (OBD speed 0 for > [EXACT: 3] s -- Spool,
#        load-bearing). At zero velocity the accel reads PURE GRAVITY, so the
#        measured tilt is the true chassis pitch: the one uncontaminated fix the
#        estimator ever gets. One stop cannot separate the mount tilt from the
#        slope you are parked on, but the mean over many stops converges on the
#        BIAS -- valid because Chicagoland is glacial-flat, so real road slopes
#        genuinely average ~0. City stoplights are the free calibration signal.
#
#   HONEST-INSTRUMENT, per branch: the pitch starts None and is NEVER a
#   fabricated 0.0 (a level board and an unknown attitude must not look alike);
#   it seeds only from an UNCONTAMINATED reading, because seeding mid-pull would
#   bake the phantom in as the origin the gyro then integrates from; no bias is
#   applied until enough stops have been seen to have actually measured one; and
#   an ABSENT or STALE OBD speed is never read as "stopped" -- that would
#   hard-correct the attitude to a contaminated accel while the car is moving,
#   which is strictly worse than the drift it would be trying to fix.
#
#   Pure and I/O-free by construction: no bus, no device, no clock. The caller
#   supplies vehicle-frame vectors and monotonic capture times, so the whole
#   estimator is deterministically testable and US-519 can reuse it unchanged.
# Author: Rex (US-521)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Rex (US-521) | Initial -- complementary gyro/accel pitch filter
#               |              | + ZUPT stop detector and rolling bias mean.
#               |              | Owns the gravity/tilt constants US-478 defined
#               |              | (imu_state_bridge re-exports them; ONE home).
# ================================================================================
################################################################################

"""Gyro-fused chassis pitch with a zero-velocity (ZUPT) bias update."""

from __future__ import annotations

import logging
import math
from collections import deque

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ACCEL_TRUST_BAND",
    "DEFAULT_PITCH_TAU_S",
    "DEFAULT_ZUPT_MIN_STOPS",
    "DEFAULT_ZUPT_SPEED_MAX_AGE_S",
    "DEFAULT_ZUPT_WINDOW_STOPS",
    "MAX_GRADE_PITCH_DEG",
    "MIN_GRAVITY_MS2",
    "STANDARD_GRAVITY_MS2",
    "ZUPT_MIN_STOP_S",
    "PitchFusion",
    "gradePctFromPitchRad",
    "pitchRadFromAccel",
]

# Standard gravity (BIPM/CODATA g_n = 9.80665 m/s^2 exactly). The divisor that
# turns the reader's m/s^2 into g units, and the reference the trust band is
# measured against. Defined HERE and re-exported by imu_state_bridge so the two
# modules cannot drift apart on the value (US-478 originally owned it).
STANDARD_GRAVITY_MS2 = 9.80665

# A specific-force vector shorter than this is not a usable level reference
# (free-fall, an unreadable burst, or garbage) -- every tilt-derived field grays.
MIN_GRAVITY_MS2 = 0.5

# Beyond this pitch, tan() runs away (tan(85 deg) = 1143%) and the reading is not
# a road grade by any reading -- report unknown rather than an absurd number.
MAX_GRADE_PITCH_DEG = 85.0

# Display precision for the published grade (a display view, not the estimate).
_GRADE_DECIMALS = 1

# SPOOL [EXACT: 3] -- the zero-velocity gate. A stop counts only once OBD speed
# has been OBSERVED at zero across a span longer than this. LOAD-BEARING SME
# value: flag Spool before any drift.
ZUPT_MIN_STOP_S = 3.0

# Complementary-filter time constant, seconds: how fast a TRUSTED accel reading
# pulls the gyro-integrated pitch back. Rex-derived (mirrors US-478's gravity
# low-pass, which was sized the same way and flagged the same way) and
# config-parameterized via pi.sensors.imu.pitchTauSec. Routed to Spool with the
# sample rates under the story's SPOOL SIZING acceptance criterion.
DEFAULT_PITCH_TAU_S = 5.0

# The "near 1 g" window, as a FRACTION of standard gravity, inside which the
# accelerometer is trusted to correct the gyro (Spool's condition).
#
# WHY 0.02 AND NOT MORE: the specific force under a longitudinal pull of a g is
# sqrt(1 + a^2), so the band admits accelerations up to ~sqrt(2 * band) g. At
# 0.02 that is ~0.2 g, and the 0.3 g case the story names (1.044 g, a 4.4%
# excess) is rejected outright. WHY NOT LESS: road vibration alone would then
# gate the accel off permanently, leaving pure gyro drift with nothing to
# correct it. The residual -- a sustained sub-0.2 g pull still leaks in -- is
# bounded by the tau blend above and erased by the next ZUPT, which is precisely
# why Spool specified both mechanisms rather than either alone. Rex-derived,
# config-parameterized (pi.sensors.imu.accelTrustBand), routed to Spool.
DEFAULT_ACCEL_TRUST_BAND = 0.02

# How stale an OBD speed reading may be and still count as evidence about the
# vehicle's motion. Sized just above the ~1 Hz SPEED poll to bridge scheduler
# jitter -- deliberately BELOW the ZUPT gate, so a link that drops mid-stop
# stops being treated as a stop quickly rather than pinning the estimator to a
# stale zero while the car drives away. Rex-derived; see the class docstring.
DEFAULT_ZUPT_SPEED_MAX_AGE_S = 2.0

# Minimum confirmed stops before ANY bias is applied. One stop cannot separate
# the mount tilt from the slope of the spot you parked on, so a bias claimed
# from it would be a calibration we have not measured. Rex-derived.
DEFAULT_ZUPT_MIN_STOPS = 5

# Rolling window of stop observations the bias mean is taken over. A cumulative
# mean over all history would freeze on an old calibration and never recover
# from a physical remount. Rex-derived.
DEFAULT_ZUPT_WINDOW_STOPS = 20

# The integrated pitch is clamped here: past vertical the attitude is not merely
# wrong, it makes every downstream tan() nonsense.
_MAX_PITCH_RAD = math.pi / 2.0


def _finiteVec3(value) -> tuple[float, float, float] | None:
    """Coerce a value to a finite float 3-tuple, else None.

    Args:
        value: Anything the caller believes is a 3-vector.

    Returns:
        The coerced ``(x, y, z)``, or None when it is malformed or carries a
        non-finite component. NaN is rejected explicitly: it propagates silently
        through every later sum and never compares unequal to itself, so nothing
        downstream would ever detect it.
    """
    if value is None:
        return None
    try:
        x, y, z = value
        out = (float(x), float(y), float(z))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(c) for c in out):
        return None
    return out


def pitchRadFromAccel(accel) -> float | None:
    """Chassis pitch in radians from one specific-force reading.

    This is the CONTAMINATED estimate -- correct only when the vehicle is not
    accelerating. It is the accel half of the complementary filter and the ZUPT
    measurement, never the published pitch on its own.

    Args:
        accel: Specific force in VEHICLE coordinates ``(forward, left, up)``,
            m/s^2.

    Returns:
        Pitch in radians, positive = nose up = climbing, or None when the vector
        is malformed or too short to be a level reference.
    """
    vec = _finiteVec3(accel)
    if vec is None:
        return None
    fwd, left, up = vec
    if math.sqrt(fwd * fwd + left * left + up * up) < MIN_GRAVITY_MS2:
        return None
    return math.atan2(fwd, math.hypot(left, up))


def gradePctFromPitchRad(pitchRad: float | None) -> float | None:
    """Road grade in percent from a chassis pitch (Atlas: tan(pitch) * 100).

    Args:
        pitchRad: The fused, bias-corrected pitch in radians, or None when the
            estimator has no attitude yet.

    Returns:
        Signed grade percent (positive = climbing), or None when the pitch is
        unknown or past MAX_GRADE_PITCH_DEG, where tan runs away and the number
        would be a lie dressed as precision.
    """
    if pitchRad is None or not math.isfinite(pitchRad):
        return None
    if abs(math.degrees(pitchRad)) > MAX_GRADE_PITCH_DEG:
        return None
    return round(math.tan(pitchRad) * 100.0, _GRADE_DECIMALS)


class PitchFusion:
    """Complementary gyro/accel pitch filter with a ZUPT bias update.

    Owns exactly two running facts: the fused attitude and the rolling mean of
    the tilts measured at confirmed stops (the mount-tilt bias). The published
    pitch is ``fused - bias``, which is the road grade rather than the board's
    angle in its bracket.

    THE DANGEROUS CASE IS NOT A FAILED SPEED READ, IT IS A STALE ONE. If the OBD
    link drops while the car is stopped at a light and the last thing the
    estimator heard was "speed 0", then treating that reading as durable would
    keep hard-correcting the attitude to whatever the accelerometer says for the
    rest of the drive -- i.e. snapping the pitch to the 16.7-degree phantom on
    every on-ramp, with more confidence than the drift it was fixing. So a stop
    requires speed to have been OBSERVED at zero across the whole gate AND to
    still be fresh; absence resolves to "unknown motion", never to "stopped".

    Not thread-safe by design: the IMU bridge drains one bus subscription on one
    thread, and adding a lock would only hide a caller that had introduced a
    second one.
    """

    def __init__(
        self,
        *,
        pitchTauSec: float = DEFAULT_PITCH_TAU_S,
        accelTrustBand: float = DEFAULT_ACCEL_TRUST_BAND,
        zuptMinStopSec: float = ZUPT_MIN_STOP_S,
        zuptSpeedMaxAgeSec: float = DEFAULT_ZUPT_SPEED_MAX_AGE_S,
        zuptMinStops: int = DEFAULT_ZUPT_MIN_STOPS,
        zuptWindowStops: int = DEFAULT_ZUPT_WINDOW_STOPS,
    ) -> None:
        """Bind the estimator to its filter + ZUPT parameters.

        Args:
            pitchTauSec: Complementary blend time constant, seconds.
            accelTrustBand: Fractional deviation of |accel| from 1 g inside
                which the accelerometer may correct the gyro.
            zuptMinStopSec: Spool's [EXACT: 3] s zero-velocity gate.
            zuptSpeedMaxAgeSec: How stale a speed reading may be and still be
                evidence about motion.
            zuptMinStops: Confirmed stops required before any bias is applied.
            zuptWindowStops: Length of the rolling stop-observation window.
        """
        self._tauS = pitchTauSec if pitchTauSec > 0 else DEFAULT_PITCH_TAU_S
        self._trustBand = accelTrustBand if accelTrustBand > 0 else DEFAULT_ACCEL_TRUST_BAND
        self._minStopS = zuptMinStopSec if zuptMinStopSec > 0 else ZUPT_MIN_STOP_S
        self._speedMaxAgeS = (
            zuptSpeedMaxAgeSec if zuptSpeedMaxAgeSec > 0 else DEFAULT_ZUPT_SPEED_MAX_AGE_S
        )
        self._minStops = max(1, int(zuptMinStops))
        window = max(1, int(zuptWindowStops))
        # Attitude state.
        self._pitch: float | None = None
        self._lastCapture: float | None = None
        # ZUPT state.
        self._stopSince: float | None = None
        self._lastSpeedCapture: float | None = None
        self._stopSum = 0.0
        self._stopSamples = 0
        self._stopObs: deque[float] = deque(maxlen=window)

    # -- read side -------------------------------------------------------------
    @property
    def pitchRad(self) -> float | None:
        """The fused, bias-corrected chassis pitch, or None when unknown.

        None is the honest answer before the filter has seeded from an
        uncontaminated reading -- never a fabricated 0.0.
        """
        if self._pitch is None:
            return None
        return self._pitch - self.biasRad

    @property
    def rawPitchRad(self) -> float | None:
        """The fused pitch BEFORE bias removal (board angle, diagnostics only)."""
        return self._pitch

    @property
    def biasRad(self) -> float:
        """The mount-tilt bias: the mean tilt measured over recent stops.

        0.0 until ``zuptMinStops`` stops have been observed -- reporting a bias
        measured from one stop would be reporting the slope of a parking spot as
        a calibration constant.
        """
        if len(self._stopObs) < self._minStops:
            return 0.0
        return sum(self._stopObs) / len(self._stopObs)

    @property
    def stopCount(self) -> int:
        """Confirmed stops currently held in the rolling bias window."""
        return len(self._stopObs)

    @property
    def inConfirmedStop(self) -> bool:
        """Whether the last processed sample fell inside a confirmed stop."""
        return self._confirmedStopAt(self._lastCapture) if self._lastCapture is not None else False

    # -- ingest ----------------------------------------------------------------
    def observeSpeed(self, speed, capture: float) -> None:
        """Fold one OBD speed reading into the stop detector.

        Unit-agnostic ON PURPOSE. The gate is "speed is zero", which is the same
        fact in km/h or mph -- so this reader cannot repeat the km/h-read-as-mph
        mislabel that produced the phantom 2x SPEED drift, because it never
        depends on the magnitude at all.

        Args:
            speed: The reading's value; None or non-finite is treated as SILENCE
                (it neither starts a stop nor refreshes freshness), because an
                unreadable speed is not a zero speed.
            capture: The reading's monotonic capture time, seconds.
        """
        try:
            value = float(speed)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        self._lastSpeedCapture = capture
        if value <= 0.0:
            if self._stopSince is None:
                self._stopSince = capture
        else:
            self._endStop()

    def update(self, accel, gyro, capture: float) -> None:
        """Fold one IMU burst into the fused pitch.

        Args:
            accel: Specific force in VEHICLE coordinates (forward, left, up),
                m/s^2. A malformed or non-finite vector is ignored outright --
                it must never be able to poison the running estimate.
            gyro: Angular rate in VEHICLE coordinates, rad/s, or None when the
                burst carried no usable gyro. Without it the estimator holds its
                attitude and leans on the accel correction (the pre-US-521
                behaviour), rather than freezing or fabricating a rate.
            capture: The burst's monotonic capture time, seconds.
        """
        vec = _finiteVec3(accel)
        if vec is None:
            return

        self._expireStaleStop(capture)
        accelPitch = pitchRadFromAccel(vec)
        trusted = accelPitch is not None and self._accelIsNearOneG(vec)

        prev, last = self._pitch, self._lastCapture
        self._lastCapture = capture

        # Seed, or re-seed across a gap the gyro history cannot span. Only ever
        # from an uncontaminated reading: seeding mid-pull would bake the
        # acceleration phantom in as the origin the gyro integrates from.
        dt = capture - last if last is not None else None
        if prev is None or dt is None or dt <= 0.0 or dt > self._tauS:
            if trusted:
                self._pitch = accelPitch
            return

        # 1. Gyro integration -- the short-term truth, blind to linear g.
        predicted = prev
        rate = self._pitchRateFromGyro(gyro)
        if rate is not None:
            predicted = _clampPitch(prev + rate * dt)

        # 2. Accel correction -- ONLY near 1 g (Spool).
        if trusted:
            assert accelPitch is not None  # narrowed by `trusted`
            if self._confirmedStopAt(capture):
                # ZUPT: at zero velocity the accel is pure gravity, so this is a
                # measurement, not an estimate. Snap, do not blend -- a blend
                # would leave the gyro drift decaying over seconds when we have
                # the true value in hand right now.
                predicted = accelPitch
                self._stopSum += accelPitch
                self._stopSamples += 1
            else:
                alpha = dt / (self._tauS + dt)
                predicted = predicted + alpha * (accelPitch - predicted)

        self._pitch = _clampPitch(predicted)

    def reset(self) -> None:
        """Drop the attitude estimate (e.g. the sensor went absent).

        The ZUPT bias survives: it is a property of how the board is BOLTED IN,
        which an unplug does not change, and re-converging it costs another five
        stoplights.
        """
        self._pitch = None
        self._lastCapture = None
        self._endStop()
        self._stopSince = None
        self._lastSpeedCapture = None

    # -- internals -------------------------------------------------------------
    def _accelIsNearOneG(self, vec: tuple[float, float, float]) -> bool:
        """Whether |accel| sits inside the trust band around standard gravity."""
        magnitudeG = math.sqrt(sum(c * c for c in vec)) / STANDARD_GRAVITY_MS2
        return abs(magnitudeG - 1.0) <= self._trustBand

    @staticmethod
    def _pitchRateFromGyro(gyro) -> float | None:
        """Nose-up pitch rate, rad/s, from a vehicle-frame angular rate.

        SIGN, derived rather than guessed, because it must agree with the accel
        tilt convention or the two halves of the filter fight each other. The
        frame is right-handed (forward x left = up), so a point at the nose
        moves as ``omega x forward = omega_left * (left x forward) =
        -omega_left * up``: the nose rises when the LEFT-axis rate is NEGATIVE.

        NOTE on mounts: this assumes ``pi.sensors.imu.mount`` expresses a
        physical ROTATION (determinant +1), which every realizable remount is.
        An axis map that mirrors the board is not a mount, it is a config typo,
        and it already breaks the heading the same way.
        """
        vec = _finiteVec3(gyro)
        if vec is None:
            return None
        return -vec[1]

    def _confirmedStopAt(self, capture: float) -> bool:
        """Whether ``capture`` falls inside a confirmed zero-velocity window.

        Requires zero speed to have been OBSERVED across a span longer than the
        gate -- not merely that the gate's worth of time has ELAPSED since one
        zero reading. Elapsed time after a single sample is not evidence the car
        stayed still; it is evidence only that we stopped being told.
        """
        if self._stopSince is None or self._lastSpeedCapture is None:
            return False
        if capture - self._lastSpeedCapture > self._speedMaxAgeS:
            return False
        return (self._lastSpeedCapture - self._stopSince) > self._minStopS

    def _expireStaleStop(self, capture: float) -> None:
        """Retire a stop whose speed evidence has gone stale (link drop)."""
        if self._lastSpeedCapture is None:
            return
        if capture - self._lastSpeedCapture > self._speedMaxAgeS:
            self._endStop()
            self._lastSpeedCapture = None

    def _endStop(self) -> None:
        """Close the current stop, committing ONE averaged bias observation.

        One observation per STOP, not per sample: Spool's mean is over stops, and
        per-sample accumulation would let a single long red light outvote a whole
        drive's worth of stoplights.
        """
        self._stopSince = None
        if self._stopSamples > 0:
            self._stopObs.append(self._stopSum / self._stopSamples)
        self._stopSum = 0.0
        self._stopSamples = 0


def _clampPitch(pitchRad: float) -> float:
    """Hold the integrated attitude inside +/- vertical."""
    return max(-_MAX_PITCH_RAD, min(_MAX_PITCH_RAD, pitchRad))
