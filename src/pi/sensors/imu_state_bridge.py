################################################################################
# File Name: imu_state_bridge.py
# Purpose/Description: US-478 IMU -> states/imu bridge (F-113). A PURE consumer of
#   the F-110 SampleBus that drains the additive raw.imu.accel / raw.imu.mag
#   channels (published by sensor_reader.ImuReader off the genuine Adafruit
#   ICM-20948 #4554 @0x69) and writes the DISPLAY-DERIVED view into states/imu --
#   the SSOT state file the US-497 live-instrument card polls. Mirrors the
#   states/light seam exactly (US-483-a): same atomic writer, same tmpfs dir, same
#   served-as-is-by-eclipse-states-http contract.
#
#   THE READER COMPUTES, THE DISPLAY CONSUMES (Atlas DELTA-2 / Q-A). The derived
#   contract published here is exactly:
#     gLat / gLon / gMag  -- horizontal g (units = g, 1 g = 9.80665 m/s^2)
#     headingDeg          -- 0..359, tilt-compensated magnetometer bearing
#     gradePct            -- tan(pitch) * 100, pitch from the gravity vector
#     altitude            -- typed NULL + reason "no_source" (no barometer)
#     available + ts      -- freshness; absent/stale -> US-497 idle-card fallback
#   RAW accel/gyro/mag stay on the bus + the versioned edr_imu_sample store (A-4);
#   this file is the DERIVED view and is deliberately a separate artifact.
#
#   Honest-instrument, per field: any value whose source cannot be read is JSON
#   null WITH a named reason in ``reasons`` -- never a fabricated 0.0. A zeroed
#   g-meter and a dead g-meter must not look alike, and a grade past
#   MAX_GRADE_PITCH_DEG (where tan explodes) is reported as unknown rather than as
#   a four-digit percentage the card would render as fact.
#
#   GRAVITY REFERENCE (why the filter exists): the accelerometer measures gravity
#   and vehicle acceleration summed into one vector. Publishing the raw horizontal
#   components would pin a permanent phantom 0.17 g on the g-meter for a board
#   bolted in at a 10-degree tilt. So a slow low-pass tracks the gravity vector
#   (mount tilt + road grade change over seconds), and the fast residual is the
#   vehicle acceleration the g-meter exists to show. The SAME estimate feeds the
#   grade and the heading tilt-compensation -- one gravity fact, three consumers.
#
#   This module opens no I2C device and starts no OBD connection -- bus subscriber
#   only, so it cannot re-introduce the A-17 second-connection race. Gated behind
#   pi.bus.enabled + pi.sensors.imu.enabled (built only by
#   createImuStateBridgeFromConfig when both are set).
# Author: Rex (US-478)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Rex (US-478) | Initial -- bus raw.imu.{accel,mag} -> states/imu
#               |              | derived bridge (gLat/gLon/gMag, headingDeg,
#               |              | gradePct, typed-NULL altitude), gravity low-pass,
#               |              | config mount frame, display-cadence decimation.
# ================================================================================
################################################################################

"""IMU-state bridge: derive the states/imu display view from the bus IMU burst."""

from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Callable
from typing import Any

from common.time.helper import utcIsoNow

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_GRAVITY_TAU_S",
    "DEFAULT_MOUNT",
    "DEFAULT_STATE_HZ",
    "IMU_STATE_FILENAME",
    "MAG_MAX_AGE_POLLS",
    "MAX_GRADE_PITCH_DEG",
    "REASON_NO_MAG",
    "REASON_NO_SOURCE",
    "REASON_PITCH_OUT_OF_RANGE",
    "REASON_SENSOR_ABSENT",
    "REASON_TILT_UNRESOLVED",
    "STANDARD_GRAVITY_MS2",
    "STATE_IMU_PRESENCE",
    "TOPIC_IMU_ACCEL",
    "TOPIC_IMU_MAG",
    "ImuStateBridge",
    "buildImuState",
    "computeGradePct",
    "computeHeadingDeg",
    "computeHorizontalG",
    "createImuStateBridgeFromConfig",
    "resolveMountFrame",
]

# The single states/ slot the US-497 live-instrument card polls.
IMU_STATE_FILENAME = "imu"

# The bus channels this bridge consumes. Kept in sync with sensor_reader (the
# producer-side SSOT) -- a test pins them equal so the seam cannot drift.
TOPIC_IMU_ACCEL = "raw.imu.accel"
TOPIC_IMU_MAG = "raw.imu.mag"
STATE_IMU_PRESENCE = "state.sensor.imu"

# Standard gravity (BIPM/CODATA g_n = 9.80665 m/s^2 exactly) -- the divisor that
# turns the reader's m/s^2 into the contract's g units (Atlas: 1 g = 9.81 m/s^2).
STANDARD_GRAVITY_MS2 = 9.80665

# Default tmpfs states dir (matches boot_state_emitter + the states-http unit).
_DEFAULT_STATES_DIR = "/run/eclipse-obd/states"

# Bus name for the bridge's subscription (appears in SubStats / gap markers).
_SUB_NAME = "imu-state"

# How long the drain loop blocks waiting for a sample before re-checking _stop.
_DRAIN_TIMEOUT_S = 0.5

# Default state-file write cadence. GROUNDED to the consumer, not the sensor:
# writing the file faster than the only consumer reads it is pure tmpfs churn
# with no observable effect. The IMU bursts at 50 Hz; this is the DISPLAY view.
#
# US-508 raised it 4 -> 10 Hz because the consumer got faster, not because the
# sensor did. The live instrument moved onto the carousel's HOME slot and polls
# states/imu on its own ~10 Hz loop (carousel.js IMU_POLL_MS = 100) -- a
# scrolling compass tape and a g-trail simply do not animate at 4 Hz. Per
# Atlas's transport ruling this stays latest-wins/lossy with no history on the
# display path; the durable EDR persist is a SEPARATE cadence (persistHz) off
# the same producer. Overridable via pi.sensors.imu.stateHz.
DEFAULT_STATE_HZ = 10

# Default gravity low-pass time constant, seconds. Chosen so the estimate tracks
# mount tilt / road grade (which change over tens of seconds) while rejecting
# vehicle acceleration events (0.2-3 s): a 1 s event is attenuated >90%, a grade
# change is tracked within ~3 tau. Rex-derived default, config-parameterized
# (pi.sensors.imu.gravityTauSec) and flagged to Atlas/Spool for SME confirmation
# against a real drive -- it is a filter constant, not a tuning value.
DEFAULT_GRAVITY_TAU_S = 5.0

# Default IMU burst rate (mirrors sensor_reader.DEFAULT_IMU_SAMPLE_HZ) -- used to
# derive the magnetometer freshness window below.
DEFAULT_IMU_SAMPLE_HZ = 50

# A magnetometer reading is paired with an accel reading only if it is within
# this many poll intervals. Derived from the configured sampleHz (not a second
# independent constant): the reader bursts accel+gyro+mag under ONE seq, so the
# freshest mag is at most one interval old; 5 is slack for scheduler jitter.
MAG_MAX_AGE_POLLS = 5

# Beyond this pitch, tan() runs away (tan(85 deg) = 1143%) and the reading is not
# a road grade by any reading -- report unknown rather than an absurd number.
MAX_GRADE_PITCH_DEG = 85.0

# A gravity vector shorter than this is not a usable level reference (free-fall,
# an unreadable burst, or garbage) -- every tilt-derived field grays.
_MIN_GRAVITY_MS2 = 0.5

# Display precision. The g fields are far coarser than the sensor (16-bit at
# +/-2 g is ~0.00006 g); this is a DISPLAY view, and trailing noise digits are
# not information the card can render.
_G_DECIMALS = 3
_HEADING_DECIMALS = 1
_GRADE_DECIMALS = 1

# Named absence reasons (the honest-availability vocabulary the card renders).
REASON_SENSOR_ABSENT = "sensor_absent"
REASON_NO_MAG = "no_mag_reading"
REASON_TILT_UNRESOLVED = "tilt_unresolved"
REASON_PITCH_OUT_OF_RANGE = "pitch_out_of_range"
REASON_NO_SOURCE = "no_source"

# The derived fields, in payload order (the reasons map is keyed by these).
_DERIVED_FIELDS = ("gLat", "gLon", "gMag", "headingDeg", "gradePct", "altitude")

# Default mount frame: the board's +x points at the vehicle nose, +y out the left
# flank, +z at the roof. A physical remount is a CONFIG edit (pi.sensors.imu.mount)
# -- never a code edit.
DEFAULT_MOUNT = {"forward": "+x", "left": "+y", "up": "+z"}

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _axisComponent(vec: tuple[float, float, float], spec: str) -> float:
    """Pick one signed axis component out of a device-frame vector.

    Args:
        vec: The raw device-frame 3-vector.
        spec: An axis spec such as ``"+x"`` / ``"-z"`` (a bare ``"x"`` is +x).

    Returns:
        The selected component with the spec's sign applied.

    Raises:
        ValueError: If the spec does not name one of x/y/z.
    """
    token = spec.strip().lower()
    sign = -1.0 if token.startswith("-") else 1.0
    axis = token.lstrip("+-")
    if axis not in _AXIS_INDEX:
        raise ValueError(f"invalid IMU mount axis spec: {spec!r}")
    return sign * float(vec[_AXIS_INDEX[axis]])


def resolveMountFrame(
    vec: tuple[float, float, float], mount: dict[str, str] | None = None
) -> tuple[float, float, float]:
    """Re-express a raw device-frame vector in the VEHICLE frame.

    Args:
        vec: The reader's raw 3-vector in the board's own axes.
        mount: Axis map ``{"forward": "+x", "left": "+y", "up": "+z"}``; the
            identity default matches the board mounted nose-forward, flat.

    Returns:
        ``(forward, left, up)`` -- the frame every derived field is computed in.
    """
    m = mount or DEFAULT_MOUNT
    return (
        _axisComponent(vec, m.get("forward", "+x")),
        _axisComponent(vec, m.get("left", "+y")),
        _axisComponent(vec, m.get("up", "+z")),
    )


def _norm(v: tuple[float, float, float]) -> float:
    """Euclidean length of a 3-vector."""
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Dot product of two 3-vectors."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _levelFrame(
    gravity: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Build the horizontal (earth-level) forward/left unit vectors.

    The gravity vector defines earth-UP in vehicle coordinates; projecting the
    vehicle's forward and left axes onto the plane perpendicular to it gives the
    frame every horizontal quantity (heading, gLat/gLon) is measured in -- that
    projection IS the tilt compensation.

    Args:
        gravity: The (slow) gravity estimate in vehicle coordinates, m/s^2.

    Returns:
        ``(forwardHorizontal, leftHorizontal)`` unit vectors, or None when the
        board is tilted so far that one of them collapses (no level frame).
    """
    gLen = _norm(gravity)
    if gLen < _MIN_GRAVITY_MS2:
        return None
    up = (gravity[0] / gLen, gravity[1] / gLen, gravity[2] / gLen)
    horizontals = []
    for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)):
        d = _dot(axis, up)
        proj = (axis[0] - d * up[0], axis[1] - d * up[1], axis[2] - d * up[2])
        length = _norm(proj)
        if length < 1e-6:  # the axis points straight up/down -- no bearing
            return None
        horizontals.append((proj[0] / length, proj[1] / length, proj[2] / length))
    return horizontals[0], horizontals[1]


def computeGradePct(gravity: tuple[float, float, float]) -> float | None:
    """Road grade in percent from the gravity vector (Atlas: tan(pitch) * 100).

    Args:
        gravity: The gravity estimate in vehicle coordinates (forward, left, up).

    Returns:
        Signed grade percent (positive = climbing), or None when there is no
        usable gravity reference or the pitch is past MAX_GRADE_PITCH_DEG (where
        tan runs away and the number would be a lie dressed as precision).
    """
    if _norm(gravity) < _MIN_GRAVITY_MS2:
        return None
    fwd, left, up = gravity
    pitchRad = math.atan2(fwd, math.hypot(left, up))
    if abs(math.degrees(pitchRad)) > MAX_GRADE_PITCH_DEG:
        return None
    return round(math.tan(pitchRad) * 100.0, _GRADE_DECIMALS)


def computeHeadingDeg(
    gravity: tuple[float, float, float], mag: tuple[float, float, float]
) -> float | None:
    """Tilt-compensated magnetic heading in degrees (0..359).

    The field's vertical component is projected out using the gravity estimate,
    so the bearing is invariant to how the board is tilted -- an uncompensated
    ``atan2(my, mx)`` swings by tens of degrees on a rolled mount.

    Args:
        gravity: The gravity estimate in vehicle coordinates.
        mag: The magnetometer reading in vehicle coordinates (uT).

    Returns:
        The vehicle nose's magnetic bearing, or None when there is no usable
        gravity reference or the field reading is degenerate. NOTE: magnetic,
        not true -- declination correction is not in the Q-A contract.
    """
    frame = _levelFrame(gravity)
    if frame is None or _norm(mag) < 1e-9:
        return None
    fwdH, leftH = frame
    bearing = math.degrees(math.atan2(_dot(mag, leftH), _dot(mag, fwdH)))
    return round(bearing % 360.0, _HEADING_DECIMALS)


def computeHorizontalG(
    linear: tuple[float, float, float], gravity: tuple[float, float, float]
) -> tuple[float, float] | None:
    """Horizontal acceleration in g, projected onto the level frame.

    Args:
        linear: The gravity-removed acceleration in vehicle coordinates (m/s^2).
        gravity: The gravity estimate defining the level frame.

    Returns:
        ``(gLon, gLat)`` in g, or None when there is no usable level frame.
        SIGN CONTRACT (the card maps these, it never re-derives them):
        gLon positive = accelerating, negative = braking; gLat positive = to the
        RIGHT (automotive convention), i.e. positive in a right-hand turn.
    """
    frame = _levelFrame(gravity)
    if frame is None:
        return None
    fwdH, leftH = frame
    gLon = _dot(linear, fwdH) / STANDARD_GRAVITY_MS2
    gLat = -_dot(linear, leftH) / STANDARD_GRAVITY_MS2
    return (round(gLon, _G_DECIMALS), round(gLat, _G_DECIMALS))


def buildImuState(
    *,
    tsUtc: str,
    gravity: tuple[float, float, float] | None = None,
    linear: tuple[float, float, float] | None = None,
    mag: tuple[float, float, float] | None = None,
    unavailableReason: str | None = None,
) -> dict:
    """Assemble the states/imu payload (pure -- the Atlas Q-A contract).

    Args:
        tsUtc: The reading's ISO-8601 read-time (the freshness marker US-497
            compares against before falling back to the idle card).
        gravity: The gravity estimate in vehicle coordinates, or None.
        linear: The gravity-removed acceleration in vehicle coordinates, or None.
        mag: The magnetometer reading in vehicle coordinates, or None when no
            fresh reading is paired with this burst.
        unavailableReason: When set, the whole instrument is reported absent with
            this reason (e.g. the sensor is not wired) and every derived field is
            null -- silence reported as silence.

    Returns:
        ``{available, ts, gLat, gLon, gMag, headingDeg, gradePct, altitude,
        reasons}``. ``altitude`` is ALWAYS null with reason ``"no_source"``: the
        ICM-20948 has no barometer, and a zeroed altitude would render as sea
        level -- a confident lie (a future BMP280/GPS fills it, not this bridge).
    """
    reasons: dict[str, str] = {"altitude": REASON_NO_SOURCE}
    state: dict[str, Any] = {
        "available": False,
        "ts": tsUtc,
        "gLat": None,
        "gLon": None,
        "gMag": None,
        "headingDeg": None,
        "gradePct": None,
        "altitude": None,
        "reasons": reasons,
    }

    blanketReason = unavailableReason
    if blanketReason is None and (gravity is None or _norm(gravity) < _MIN_GRAVITY_MS2):
        blanketReason = REASON_TILT_UNRESOLVED
    if blanketReason is not None:
        for field in _DERIVED_FIELDS:
            reasons.setdefault(field, blanketReason)
        reasons["altitude"] = REASON_NO_SOURCE
        return state

    assert gravity is not None  # narrowed by the blanket check above
    state["available"] = True

    horizontal = computeHorizontalG(linear or (0.0, 0.0, 0.0), gravity)
    if horizontal is None:
        for field in ("gLat", "gLon", "gMag"):
            reasons[field] = REASON_TILT_UNRESOLVED
    else:
        gLon, gLat = horizontal
        state["gLon"] = gLon
        state["gLat"] = gLat
        state["gMag"] = round(math.hypot(gLon, gLat), _G_DECIMALS)

    grade = computeGradePct(gravity)
    if grade is None:
        reasons["gradePct"] = REASON_PITCH_OUT_OF_RANGE
    else:
        state["gradePct"] = grade

    heading = computeHeadingDeg(gravity, mag) if mag is not None else None
    if heading is None:
        reasons["headingDeg"] = REASON_NO_MAG
    else:
        state["headingDeg"] = heading
    return state


def _vec3(value: Any) -> tuple[float, float, float] | None:
    """Coerce a bus sample value to a finite float 3-tuple, else None.

    Defense-in-depth at the seam: a non-finite or malformed vector can never
    reach the state file as a fabricated reading (the writer serializes with
    allow_nan=False, so an inf would otherwise blow up the write).
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


class ImuStateBridge:
    """Drains the bus IMU burst and mirrors the derived view into states/imu.

    A pure bus consumer (Atlas DELTA-2): it opens no I2C device and starts no OBD
    connection. Owns exactly one piece of running state -- the low-pass gravity
    estimate -- because gLat/gLon, gradePct and the heading tilt-compensation all
    need the SAME gravity fact, and deriving it three times is three chances to
    disagree. The drain runs on its own daemon thread, mirroring the
    LightStateBridge lifecycle; a write fault is isolated (logged, never crashes
    the loop).
    """

    def __init__(
        self,
        subscription: Any,
        statesDir: str,
        *,
        mount: dict[str, str] | None = None,
        stateHz: float = DEFAULT_STATE_HZ,
        gravityTauSec: float = DEFAULT_GRAVITY_TAU_S,
        sampleHz: int = DEFAULT_IMU_SAMPLE_HZ,
        nowIsoFn: Callable[[], str] | None = None,
    ) -> None:
        """Bind the bridge to its source subscription + states dir.

        Args:
            subscription: The bus Subscription (LOSSY on the IMU topics) this
                consumer drains. May be None for direct-handleSample tests.
            statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
            mount: Axis map placing the board in the vehicle (see DEFAULT_MOUNT).
            stateHz: State-file write cadence -- the DISPLAY's poll rate, not the
                sensor's burst rate.
            gravityTauSec: Gravity low-pass time constant, seconds.
            sampleHz: The reader's burst rate; the magnetometer pairing window is
                derived from it (MAG_MAX_AGE_POLLS intervals).
            nowIsoFn: Fallback clock for ``ts`` when a sample carries no tsUtc.
        """
        self._sub = subscription
        self._statesDir = statesDir
        self._target = os.path.join(statesDir, IMU_STATE_FILENAME)
        self._mount = mount or DEFAULT_MOUNT
        self._writeIntervalS = 1.0 / stateHz if stateHz and stateHz > 0 else 1.0 / DEFAULT_STATE_HZ
        self._tauS = gravityTauSec if gravityTauSec and gravityTauSec > 0 else DEFAULT_GRAVITY_TAU_S
        rate = sampleHz if sampleHz and sampleHz > 0 else DEFAULT_IMU_SAMPLE_HZ
        self._magMaxAgeS = MAG_MAX_AGE_POLLS / float(rate)
        self._nowIsoFn = nowIsoFn if nowIsoFn is not None else utcIsoNow
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Running state (single-threaded: only the drain thread touches these).
        self._gravity: tuple[float, float, float] | None = None
        self._lastAccelCapture: float | None = None
        self._mag: tuple[float, float, float] | None = None
        self._magCapture: float | None = None
        self._lastWriteCapture: float | None = None

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Start the background drain thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ImuStateBridge", daemon=True)
        self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        """Signal the drain loop to exit and join the thread.

        Args:
            timeoutS: Maximum seconds to wait for the drain thread to finish.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)
            self._thread = None

    def _loop(self) -> None:
        """Drain samples until stopped (consumer isolation -- never crashes)."""
        if self._sub is None:
            return
        while not self._stop.is_set():
            sample = self._sub.get(timeoutS=_DRAIN_TIMEOUT_S)
            if sample is not None:
                try:
                    self.handleSample(sample)
                except Exception as e:  # noqa: BLE001 -- never crash the loop
                    logger.warning("imu-state handleSample failed: %s", e)

    # -- ingest ----------------------------------------------------------------
    def handleSample(self, sample: Any) -> bool:
        """Fold one bus sample into the states/imu view.

        Returns True if the sample was one of this bridge's topics (accel, mag,
        or the retained presence STATE); False for anything else, which is
        ignored without a write.
        """
        topic = getattr(sample, "topic", None)
        if topic == STATE_IMU_PRESENCE:
            self._handlePresence(sample)
            return True
        if topic == TOPIC_IMU_MAG:
            self._mag = _vec3(getattr(sample, "value", None))
            self._magCapture = float(getattr(sample, "tsCapture", 0.0))
            return True
        if topic != TOPIC_IMU_ACCEL:
            return False
        self._handleAccel(sample)
        return True

    def _handlePresence(self, sample: Any) -> None:
        """Report an absent sensor explicitly (never leave stale values live).

        The write bypasses the decimation window: a state CHANGE is not
        rate-limited behind a display-cadence budget, and leaving the last live
        g reading on the card after an unplug would be a frozen instrument
        presenting itself as a live one (US-478 AC-3).
        """
        if bool(getattr(sample, "value", 0.0)):
            return
        self._gravity = None
        self._lastAccelCapture = None
        self._mag = None
        self._magCapture = None
        tsUtc = getattr(sample, "tsUtc", "") or self._nowIsoFn()
        self._writeState(buildImuState(tsUtc=tsUtc, unavailableReason=REASON_SENSOR_ABSENT))
        self._lastWriteCapture = None

    def _handleAccel(self, sample: Any) -> None:
        """Update the gravity estimate and (at the display cadence) write."""
        raw = _vec3(getattr(sample, "value", None))
        if raw is None:
            return  # an unreadable burst publishes nothing -- silence, not a zero
        accel = resolveMountFrame(raw, self._mount)
        capture = float(getattr(sample, "tsCapture", 0.0))
        self._updateGravity(accel, capture)
        if not self._shouldWrite(capture):
            return
        gravity = self._gravity
        assert gravity is not None  # set by _updateGravity
        linear = (accel[0] - gravity[0], accel[1] - gravity[1], accel[2] - gravity[2])
        tsUtc = getattr(sample, "tsUtc", "") or self._nowIsoFn()
        self._writeState(
            buildImuState(
                tsUtc=tsUtc, gravity=gravity, linear=linear, mag=self._freshMag(capture)
            )
        )
        self._lastWriteCapture = capture

    def _updateGravity(self, accel: tuple[float, float, float], capture: float) -> None:
        """Fold one accel reading into the low-pass gravity estimate.

        The first reading (and any reading after a gap longer than the time
        constant, where the filter's memory is worthless anyway) SEEDS the
        estimate outright, so a bench start or a resumed drive shows an honest
        zero-g immediately instead of settling in from a fabricated origin.
        """
        prev, last = self._gravity, self._lastAccelCapture
        self._lastAccelCapture = capture
        if prev is None or last is None:
            self._gravity = accel
            return
        dt = capture - last
        if dt <= 0.0 or dt > self._tauS:
            self._gravity = accel
            return
        alpha = dt / (self._tauS + dt)
        self._gravity = (
            prev[0] + alpha * (accel[0] - prev[0]),
            prev[1] + alpha * (accel[1] - prev[1]),
            prev[2] + alpha * (accel[2] - prev[2]),
        )

    def _freshMag(self, capture: float) -> tuple[float, float, float] | None:
        """The magnetometer reading paired with this burst, or None if stale.

        A frozen compass needle is worse than an absent one: past the pairing
        window the heading grays with REASON_NO_MAG rather than carrying an old
        bearing forward as though it were current.
        """
        if self._mag is None or self._magCapture is None:
            return None
        age = capture - self._magCapture
        if age < 0.0 or age > self._magMaxAgeS:
            return None
        return resolveMountFrame(self._mag, self._mount)

    def _shouldWrite(self, capture: float) -> bool:
        """True when the display-cadence window has opened (or on first sample)."""
        if self._lastWriteCapture is None:
            return True
        return (capture - self._lastWriteCapture) >= self._writeIntervalS

    # -- output ----------------------------------------------------------------
    def _ensureDir(self, statesDir: str) -> None:
        """Provision the tmpfs states dir (seam kept overridable for tests)."""
        ensureStatesDir(statesDir)

    def _writeState(self, payload: dict) -> None:
        """Write the states/imu payload atomically (best-effort, never raises).

        A write failure is logged but never raised: the bridge is a dashboard
        hook and must never crash the bus drain (mirrors the emitters' contract).
        """
        try:
            self._ensureDir(self._statesDir)
            writeStateAtomic(self._target, payload)
        except Exception as e:  # noqa: BLE001 -- best-effort, never crash the drain
            logger.error("states/imu write failed (%s) -- ignored", e)


def createImuStateBridgeFromConfig(
    config: dict[str, Any],
    bus: Any,
    *,
    nowIsoFn: Callable[[], str] | None = None,
) -> ImuStateBridge | None:
    """Build the IMU-state bridge from validated config, or None when dark.

    Returns None unless ``pi.bus.enabled`` AND ``pi.sensors.imu.enabled`` are both
    set -- so with the flags off nothing is built (connect-when-wired).

    Args:
        config: Validated tier-aware config (reads the ``pi`` section).
        bus: The SampleBus to subscribe to (LOSSY -- a live instrument only needs
            the freshest burst; drop-oldest on overflow is the honest policy).
        nowIsoFn: Optional fallback clock for ``ts`` (see ImuStateBridge).

    Returns:
        A ready-to-start ImuStateBridge, or None when disabled.
    """
    # Local import: keep the module import graph free of a hard bus dependency
    # for the pure-function (buildImuState) consumers.
    from pi.bus.sample import QoS

    pi = config.get("pi", {})
    if not pi.get("bus", {}).get("enabled", False):
        return None
    imu = pi.get("sensors", {}).get("imu", {})
    if not imu.get("enabled", False):
        return None

    statesDir = pi.get("splash", {}).get("statesDir", _DEFAULT_STATES_DIR)
    subscription = bus.subscribe(
        [TOPIC_IMU_ACCEL, TOPIC_IMU_MAG, STATE_IMU_PRESENCE], QoS.LOSSY, _SUB_NAME
    )
    return ImuStateBridge(
        subscription,
        statesDir,
        mount=imu.get("mount", DEFAULT_MOUNT),
        stateHz=imu.get("stateHz", DEFAULT_STATE_HZ),
        gravityTauSec=imu.get("gravityTauSec", DEFAULT_GRAVITY_TAU_S),
        sampleHz=imu.get("sampleHz", DEFAULT_IMU_SAMPLE_HZ),
        nowIsoFn=nowIsoFn,
    )
