################################################################################
# File Name: ahrs_fusion.py
# Purpose/Description: ARCH-064 -- the x-io Fusion AHRS (``imufusion``) behind
#   the PitchFusion surface, plus heading.
#
#   WHY THIS REPLACES PitchFusion (ARCH-064 RCA): the home-grown complementary
#   filter trusted the accelerometer only while |a| sat within +/-2 % of 1 g. On
#   a real drive 30 % of samples passed that gate, so ~70 % of the time pitch ran
#   on the gyro alone and drifted -- the parked grade crept 1 -> 12 % and
#   in-motion pitch read -9...-24 degrees on flat roads. Heading had no
#   calibration and no declination at all. The CIO directed: use a proven
#   library, not our own maths. Fusion rejects the accelerometer by the ANGLE it
#   disagrees with the estimated gravity (not by magnitude), recovers after a
#   bounded timeout instead of drifting forever, and learns the gyro bias
#   whenever the board is stationary (``imufusion.Bias``).
#
#   UNITS AND CONVENTIONS -- MEASURED against imufusion 1.3.3 (2026-09-28), the
#   installed wheel carries no docstrings, so each was probed, not recalled:
#     * gyroscope deg/s  (10 units about z for 1 s -> yaw +10.0 deg)
#     * accelerometer g  (Fusion documentation; attitude uses direction only)
#     * magnetometer: any unit (direction only) -- we pass calibrated uT
#     * ``rejection_timeout`` is SECONDS (5 at 50 Hz -> recovery at sample 250;
#       250 -> sample 12,500)
#     * ``quaternion_to_euler`` -> [roll, pitch, yaw] in DEGREES
#     * ``set_sample_period`` sets the dt of the NEXT update (10 x 0.1 s at
#       10 deg/s -> +10.0 deg), so the measured elapsed time is used per update
#   With CONVENTION_NWU and our body frame (x forward, y left, z up -- MEASURED
#   on the car) the body axes ARE the NWU axes of a car pointing north, so no
#   remap is needed. Fusion's NWU pitch is NEGATIVE for nose-up and its yaw is
#   counter-clockwise from north, so:  pitch = -eulerPitch  (nose-UP positive)
#   and  heading = (-eulerYaw + declination) mod 360  (clockwise from TRUE
#   north). Both are pinned by tests/pi/sensors/test_ahrs_fusion.py.
#
#   SPEED AIDING (ARCH-064 C2/C3, MEASURED): Fusion alone still absorbs the
#   car's own acceleration -- 0.15 g (8.5 deg, under the 10-deg rejection angle)
#   is never rejected and settles at 8.5 deg of phantom pitch; 0.3 g is rejected
#   for the 5 s timeout and then climbs to ~16.7 deg; sustained cornering puts
#   the same phantom into roll. That is inherent to gravity-from-accel with no
#   velocity aiding, so the standard vehicle-AHRS remedy is applied: subtract
#   the vehicle's own specific force before the update --
#       x -= a_long            (a_long = dv/dt from consecutive OBD SPEED samples)
#       y -= v * omega_z       (centripetal; left turn omega_z > 0 -> +y)
#   Skipped when speed is STALE (> 3 s since the last sample) or the sample has
#   no gyro. Signs are pinned by tests.
#
#   Pure and I/O-free: no bus, no device, no clock -- the caller supplies body-
#   frame vectors and monotonic capture times, as with PitchFusion.
# Author: Atlas (ARCH-064)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-28    | Atlas        | Initial -- imufusion Ahrs + Bias behind the
#               | (ARCH-064)   | PitchFusion surface; heading with hard/soft-iron
#               |              | calibration and declination.
# 2026-09-28    | Atlas        | Speed-aided acceleration compensation (C2/C3):
#               | (ARCH-064)   | OBD speed -> a_long = dv/dt (clamped 0.6 g) and
#               |              | centripetal v*omega_z are subtracted from the
#               |              | accel before the AHRS; off when speed is stale.
# 2026-09-28    | Atlas        | Review fix: heading coasts on the gyro for at
#               | (ARCH-064)   | most MAG_MAX_COAST_S after the last mag reading,
#               |              | then reads None until a fresh one.
# ================================================================================
################################################################################

"""x-io Fusion AHRS (imufusion) behind the PitchFusion surface, plus heading."""

from __future__ import annotations

import math
from collections.abc import Sequence

import imufusion
import numpy as np

__all__ = [
    "AHRS_GAIN",
    "ACCELERATION_REJECTION_DEG",
    "AhrsFusion",
    "BIAS_STATIONARY_PERIOD_S",
    "BIAS_STATIONARY_THRESHOLD_DPS",
    "FUSION_VERSION_AHRS",
    "MAGNETIC_REJECTION_DEG",
    "MAG_MAX_COAST_S",
    "MAX_LONGITUDINAL_ACCEL_G",
    "MAX_SAMPLE_PERIOD_S",
    "SPEED_STALE_S",
    "REJECTION_TIMEOUT_S",
]

# US-805 algorithm stamp for derived rows. PitchFusion is version 1; this is a
# different filter, so every row it produces must say so.
FUSION_VERSION_AHRS: int = 2

STANDARD_GRAVITY_MS2 = 9.80665

# ARCH-064 ruling (settings exactly as ruled -- do not tune blindly).
AHRS_GAIN = 0.5
# 7, not the ruled 10 -- tuned with a stated reason (controller permission,
# ARCH-064 C2): speed aiding cannot see an acceleration ONSET until the next OBD
# SPEED sample, up to ~2.3 s later, so the rejection angle is what must hold the
# attitude through that blind window. At 10 deg a 0.15 g pull (atan = 8.5 deg)
# is never rejected and leaks ~5 deg of phantom pitch before the first dv/dt
# arrives (MEASURED: 2.76 deg still present 4 s in). 7 deg rejects any pull
# >= tan(7) = 0.123 g at onset with 1.5 deg margin on the 0.15 g case; smaller
# pulls still leak, bounded (0.12 g: 4.2 deg peak). A lower angle ignores the
# accel more often under road vibration -- unmeasured on the car; revisit with
# drive data.
ACCELERATION_REJECTION_DEG = 7.0
MAGNETIC_REJECTION_DEG = 10.0
# MEASURED: imufusion 1.3.3 takes rejection_timeout in SECONDS (see header).
REJECTION_TIMEOUT_S = 5.0
BIAS_STATIONARY_THRESHOLD_DPS = 3.0
BIAS_STATIONARY_PERIOD_S = 3.0

# A capture gap longer than this is not a sample period -- integrating the
# current rate across it would invent rotation nobody measured. Such an update
# falls back to the nominal period (1 / sampleHz).
MAX_SAMPLE_PERIOD_S = 0.5

# Speed aiding. OBD SPEED arrives only ~every 2.3 s; a sample older than this is
# no evidence about what the car is doing now, so compensation switches OFF.
SPEED_STALE_S = 3.0
# Sanity bound on dv/dt: a road car does not exceed ~0.6 g longitudinally, so a
# larger derivative is a quantised/glitched speed pair, not a measurement.
MAX_LONGITUDINAL_ACCEL_G = 0.6
_KMH_PER_MS = 3.6

# Heading may COAST on the gyro for at most this long after the last valid
# magnetometer reading, then reads None. Coasting across a short mag gap is
# intended AHRS behaviour; past this, an unaided integrated yaw drifts without
# bound (review probe: 0.05 rad/s over 10 s moved 90.0 -> 73.7 deg) and is not
# a measured heading. A fresh mag reading restores it.
MAG_MAX_COAST_S = 5.0

_IDENTITY_3X3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_ZERO_3 = (0.0, 0.0, 0.0)


def _finiteVec3(value) -> tuple[float, float, float] | None:
    """Coerce a value to a finite float 3-tuple, else None (NaN rejected)."""
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


class AhrsFusion:
    """imufusion ``Ahrs`` + ``Bias`` exposing the PitchFusion surface and heading.

    ``pitchRad`` is nose-UP positive; ``rollRad`` is Fusion's NWU roll (left side
    UP positive); ``headingDeg`` is 0-360 clockwise from TRUE north. All are None
    until the filter has finished Fusion's startup (gain ramp, ~3 s of samples)
    -- a converging attitude is not reported as a confident one -- and heading is
    also None until a magnetometer reading has been supplied since the last
    reset.
    """

    def __init__(
        self,
        sampleHz: float,
        declinationDeg: float = 0.0,
        hardIronUt: Sequence[float] = _ZERO_3,
        softIron: Sequence[Sequence[float]] = _IDENTITY_3X3,
        gyroRangeDps: float = 500.0,
    ) -> None:
        """Build the filter.

        Args:
            sampleHz: Nominal IMU sample rate (production 50 Hz). Used by the
                Bias estimator (which has no per-update dt) and as the fallback
                period when a capture gap is not a usable dt.
            declinationDeg: Magnetic declination, degrees, EAST positive
                (true = magnetic + declination).
            hardIronUt: Hard-iron offset ``h``, uT, body frame.
            softIron: Soft-iron matrix ``S`` (3x3); ``m_c = S . (m_u - h)``.
            gyroRangeDps: Gyro full-scale range, deg/s (Fusion's overrange
                detection).
        """
        if not (sampleHz > 0.0 and math.isfinite(sampleHz)):
            raise ValueError(f"sampleHz must be a positive finite number, got {sampleHz!r}")
        self._sampleHz = float(sampleHz)
        self._nominalPeriod = 1.0 / self._sampleHz
        self._declinationDeg = float(declinationDeg)
        self._hardIron = np.asarray(hardIronUt, dtype=float).reshape(3)
        self._softIron = np.asarray(softIron, dtype=float).reshape(3, 3)
        self._gyroRangeDps = float(gyroRangeDps)
        self._headingCalibrated = bool(
            np.any(self._hardIron != 0.0) or np.any(self._softIron != np.eye(3))
        )
        self._ahrs = imufusion.Ahrs()
        self._bias = imufusion.Bias()
        self.reset()

    # -- PitchFusion surface ---------------------------------------------------
    @property
    def pitchRad(self) -> float | None:
        """Chassis pitch, radians, nose-UP positive; None until initialised."""
        if not self._initialised():
            return None
        return self._pitchRad

    @property
    def rawPitchRad(self) -> float | None:
        """Same as ``pitchRad`` -- Fusion has no separate mount-tilt bias."""
        return self.pitchRad

    @property
    def stopCount(self) -> int:
        """Always 0: there is no ZUPT stop detector (kept for surface parity)."""
        return 0

    @property
    def biasRad(self) -> float:
        """Always 0.0: no mount-tilt bias is subtracted (surface parity)."""
        return 0.0

    @property
    def gyroImplausible(self) -> bool:
        """Always False: superseded by Fusion's rejection/recovery ``flags``."""
        return False

    def observeSpeed(self, speed, capture: float) -> None:
        """Record one OBD SPEED sample for acceleration compensation.

        Args:
            speed: OBD SPEED, km/h, or None/non-finite (ignored).
            capture: Monotonic capture time, seconds (same clock as ``update``).

        a_long = dv/dt between this sample and the previous one, clamped to
        +/- MAX_LONGITUDINAL_ACCEL_G, and HELD until the next sample. A pair
        more than SPEED_STALE_S apart yields no derivative (a_long unknown).
        """
        try:
            kmh = float(speed)
        except (TypeError, ValueError):
            return
        if not math.isfinite(kmh):
            return
        speedMs = kmh / _KMH_PER_MS
        prev = self._lastSpeed
        if prev is not None:
            prevCapture, prevSpeedMs = prev
            dt = capture - prevCapture
            if dt <= 0.0:
                return  # a duplicate or out-of-order sample carries no derivative
            if dt <= SPEED_STALE_S:
                limit = MAX_LONGITUDINAL_ACCEL_G * STANDARD_GRAVITY_MS2
                self._aLongMs2 = max(-limit, min(limit, (speedMs - prevSpeedMs) / dt))
            else:
                self._aLongMs2 = None
        self._lastSpeed = (capture, speedMs)

    @property
    def longitudinalAccelMs2(self) -> float | None:
        """The held dv/dt from OBD speed, m/s^2 (None until two usable samples)."""
        return self._aLongMs2

    def update(self, accel, gyro, capture: float, mag_ut=None) -> None:
        """Fold one IMU sample into the attitude.

        Args:
            accel: Specific force, body frame (forward, left, up), m/s^2. A
                malformed or non-finite vector is ignored outright.
            gyro: Angular rate, body frame, rad/s, or None when the burst carried
                no fresh gyro -- then zero rate is integrated (attitude held,
                accel/mag still correct it) and the Bias estimator is NOT fed a
                fabricated zero.
            capture: Monotonic capture time, seconds.
            mag_ut: Magnetic field, body frame, uT, or None. Calibrated as
                ``S . (m_u - h)`` before the update.
        """
        accelVec = _finiteVec3(accel)
        if accelVec is None:
            return
        accelG = np.asarray(accelVec, dtype=float) / STANDARD_GRAVITY_MS2

        gyroVec = _finiteVec3(gyro)
        accelG = self._compensate(accelG, gyroVec, capture)
        if gyroVec is None:
            gyroDps = np.zeros(3)
        else:
            gyroDps = self._bias.update(np.degrees(np.asarray(gyroVec, dtype=float)))

        # Real elapsed time where it is a plausible sample period; otherwise the
        # nominal one (first sample, a clock step backwards, or a gap).
        period = self._nominalPeriod
        if self._lastCapture is not None:
            dt = capture - self._lastCapture
            if 0.0 < dt <= MAX_SAMPLE_PERIOD_S:
                period = dt
        self._lastCapture = capture
        self._ahrs.set_sample_period(period)

        magVec = _finiteVec3(mag_ut)
        if magVec is None:
            self._ahrs.update_no_magnetometer(gyroDps, accelG)
        else:
            magCal = self._softIron @ (np.asarray(magVec, dtype=float) - self._hardIron)
            self._ahrs.update(gyroDps, accelG, magCal)
            self._lastMagCapture = capture
        self._updated = True

        roll, pitch, yaw = imufusion.quaternion_to_euler(self._ahrs.get_quaternion())
        self._rollRad = math.radians(float(roll))
        self._pitchRad = math.radians(-float(pitch))
        self._headingDeg = (-float(yaw) + self._declinationDeg) % 360.0

    def reset(self) -> None:
        """Drop the attitude and the learned gyro bias (re-powered die, new bias)."""
        self._ahrs.set_settings(
            imufusion.AhrsSettings(
                sample_rate=self._sampleHz,
                convention=imufusion.CONVENTION_NWU,
                gain=AHRS_GAIN,
                gyroscope_range=self._gyroRangeDps,
                acceleration_rejection=ACCELERATION_REJECTION_DEG,
                magnetic_rejection=MAGNETIC_REJECTION_DEG,
                rejection_timeout=REJECTION_TIMEOUT_S,
            )
        )
        self._ahrs.restart()
        self._bias.set_settings(
            imufusion.BiasSettings(
                sample_rate=self._sampleHz,
                stationary_threshold=BIAS_STATIONARY_THRESHOLD_DPS,
                stationary_period=BIAS_STATIONARY_PERIOD_S,
            )
        )
        self._bias.set_offset(np.zeros(3))
        self._lastCapture: float | None = None
        self._updated = False
        self._lastMagCapture: float | None = None
        self._pitchRad = 0.0
        self._rollRad = 0.0
        self._headingDeg = 0.0
        self._lastSpeed: tuple[float, float] | None = None
        self._aLongMs2: float | None = None
        self._speedCompensated = False

    # -- new surface -----------------------------------------------------------
    @property
    def rollRad(self) -> float | None:
        """Roll, radians, Fusion NWU sign (left side UP positive); None until initialised."""
        if not self._initialised():
            return None
        return self._rollRad

    @property
    def headingDeg(self) -> float | None:
        """Heading, degrees 0-360 clockwise from TRUE north, or None.

        None until initialised and until a magnetometer reading has been supplied
        since the last reset -- a gyro-only yaw has no north to be measured from
        -- and None again once the last valid mag reading is more than
        MAG_MAX_COAST_S older than the last update (bounded gyro coasting).
        """
        if not self._initialised() or self._lastMagCapture is None:
            return None
        assert self._lastCapture is not None  # set by the update that set the mag
        if self._lastCapture - self._lastMagCapture > MAG_MAX_COAST_S:
            return None
        return self._headingDeg

    @property
    def headingCalibrated(self) -> bool:
        """True only when a non-default hard- or soft-iron calibration was supplied."""
        return self._headingCalibrated

    @property
    def flags(self) -> dict:
        """Fusion's rejection/recovery flags and internal states, for diagnostics."""
        f = self._ahrs.get_flags()
        s = self._ahrs.get_internal_states()
        return {
            "startup": bool(f.startup),
            "accelerationRecovery": bool(f.acceleration_recovery),
            "magneticRecovery": bool(f.magnetic_recovery),
            "overrangeRecovery": bool(f.overrange_recovery),
            "accelerometerIgnored": bool(s.accelerometer_ignored),
            "magnetometerIgnored": bool(s.magnetometer_ignored),
            "accelerationErrorDeg": float(s.acceleration_error),
            "magneticErrorDeg": float(s.magnetic_error),
            "speedCompensated": self._speedCompensated,
        }

    # -- internals -------------------------------------------------------------
    def _compensate(self, accelG: np.ndarray, gyroVec, capture: float) -> np.ndarray:
        """Remove the vehicle's own specific force (g units) when speed is fresh.

        Off (accel returned unchanged) when there is no speed, the latest is
        stale, or this sample has no gyro -- never compensate on old data or a
        fabricated rate. With one sample only, the lateral term applies and the
        longitudinal one (no derivative yet) does not.
        """
        self._speedCompensated = False
        if self._lastSpeed is None or gyroVec is None:
            return accelG
        speedCapture, speedMs = self._lastSpeed
        if capture - speedCapture > SPEED_STALE_S:
            return accelG
        out = accelG.copy()
        if self._aLongMs2 is not None:
            out[0] -= self._aLongMs2 / STANDARD_GRAVITY_MS2
        out[1] -= speedMs * gyroVec[2] / STANDARD_GRAVITY_MS2
        self._speedCompensated = True
        return out

    def _initialised(self) -> bool:
        return self._updated and not self._ahrs.get_flags().startup
