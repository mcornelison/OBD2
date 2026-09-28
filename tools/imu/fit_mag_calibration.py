"""ARCH-064 Task 6: planar hard/soft-iron magnetometer calibration fitter.

THE DEFECT THIS FITS AWAY. ``AhrsFusion`` (``pi.sensors.ahrs_fusion``) applies
``m_c = S . (m_u - h)`` to every magnetometer reading before it feeds the
heading estimate, but ships with ``h = 0`` and ``S = I`` -- a no-op. Nearby
steel (hard iron) adds a fixed offset to every reading regardless of heading,
and magnetically soft material (soft iron) distorts the field directionally,
so the raw horizontal locus is an OFF-CENTRE ELLIPSE rather than a circle
centred on the origin. Left uncorrected, the published heading carries a
heading-dependent error of tens of degrees (A-46, drive 77: hard-iron
|offset| 17.59 uT against a 16.43 uT rotating radius -- the offset EXCEEDS the
radius, so the raw bearing cannot even complete a circle).

THE METHOD. Earth's field, in vehicle coordinates, has a HORIZONTAL component
that rotates with the car's heading and a VERTICAL component that does not (it
only moves with pitch/roll, and a car is ~level). So:

* **Hard-iron x/y and soft-iron** come from a 2-D ellipse fit on the
  horizontal field: as heading sweeps 360 degrees, the (uncorrected)
  horizontal vector traces an ellipse whose CENTRE is the horizontal hard-iron
  offset and whose ECCENTRICITY/ROTATION is the soft-iron distortion. Fitting
  a scale+rotation that maps that ellipse onto a circle IS the soft-iron
  correction.
* **Hard-iron z** is the mean VERTICAL component across the capture, MINUS
  Earth's own expected vertical field (Ruling 22 -- see ``DEFAULT_EARTH_
  VERTICAL_UT`` below). Earth's vertical field does not depend on heading, so
  averaging over many headings cancels horizontal leakage and leaves Earth's
  (roughly constant) vertical field plus the z hard-iron offset SUMMED
  together; subtracting the expected Earth component is what isolates the
  hard-iron term alone. Skipping that subtraction (fit round 1's bug) makes
  z hard-iron absorb almost all of Earth's field instead -- MEASURED: fitted
  h_z = -49 uT against a true +3 uT, because Earth's vertical field here is
  ~-49 uT and dwarfs the real hard-iron term by more than an order of
  magnitude. That corrupted h_z then leaks into HEADING the moment the car's
  pitch is nonzero (mount tilt, a hill, braking dive): MEASURED heading error
  8.6 degrees at 3 degrees of pitch, 17.6 degrees at 6 degrees -- a wrong
  z-offset rotates partway into the horizontal plane precisely in proportion
  to how far from level the car sits.

LEVEL PROJECTION -- CHOICE MADE, AND WHY. The brief allows either gyro-gated
quasi-static rows (as ``pi.sensors.accel_cal.quasiStaticSamples`` selects for
the accelerometer fit) or a single robust mean-gravity vector. **This tool
uses the mean of ALL body-frame accel samples across the capture as the
gravity/up reference, not gyro-gated quasi-static filtering.** Reason: the
useful samples for THIS fit are exactly the ones where the car is TURNING (its
heading is changing), which is precisely when gyro magnitude is large --
gating on small gyro the way the accelerometer fit does would throw away most
of the heading diversity the ellipse needs. Averaging over the whole capture
instead relies on cornering/braking acceleration events summing toward zero
over a long, varied drive, leaving a residual dominated by the vehicle's fixed
mount tilt (measured ~2.5 degrees nose-up -- see ``imu_state_bridge``'s
IMU_BODY_FRAME_C commentary) -- the brief calls that residual "acceptable".

FRAME (Ruling 18, binding). ``edr_imu_sample`` rows hold the raw DEVICE frame.
Every accel and mag row is converted with the PRODUCTION
``pi.sensors.imu_state_bridge.resolveMountFrame`` (default mount) before
anything else runs, so the fit -- and the calibration it emits -- lives in the
same BODY/VEHICLE frame ``AhrsFusion`` applies it in.

COVERAGE REFUSAL (Ruling 23). Fit round 1 binned heading coverage around the
RAW CENTROID of every sample, moving or not. MEASURED EXPLOIT: 2000 idle
samples (parked, small noise) plus a real 90-degree sweep of 300 moving
samples were ACCEPTED at 32/36 bins with the hard-iron offset off by 12 uT.
The idle cluster sat off the true ellipse centre, so the naive centroid was
pulled toward it; angles measured FROM a reference point close to a dense
cluster are numerically unstable (dividing by a near-zero radius vector), and
noise alone scattered the idle cluster across many spurious bins even though
it carries almost no real heading information. Fixed three ways together:

1. Bins are centred on the FITTED ellipse centre, not the raw centroid.
2. Only samples judged MOVING count toward coverage: gyro magnitude above
   ``MOVING_MIN_GYRO_RAD_S`` (reused from ``pi.sensors.accel_cal.
   DEFAULT_MAX_GYRO_RAD_S`` -- its own documented meaning, "gyro magnitude
   below which a sample counts as not being moved", is exactly this
   boundary, used from the other side). When the CSV carries no gyro columns
   at all, every sample is treated as moving (a documented, weaker fallback --
   there is no signal to filter on, so refusing to fit at all would be worse
   than fitting without this particular defence).
3. A bin only counts occupied with at least ``MIN_SAMPLES_PER_BIN`` (3)
   samples in it -- a single noise-scattered outlier can no longer buy a bin.

The fit REFUSES when fewer than ``MIN_OCCUPIED_BINS`` (25) of 36 qualify.

Ruling 24: the gyro used for (2) is BIAS-CORRECTED, not raw. ``edr_imu_sample``
carries the RAW gyro (no bias removed upstream), and the A-34 faulted-offset
defect puts a constant ~0.5 rad/s offset on one axis -- well above
``MOVING_MIN_GYRO_RAD_S`` (0.05), which would mark every idle sample "moving"
on a faulted board and make this whole defence inert. The PER-AXIS MEDIAN
gyro reading across the capture is subtracted before the magnitude/threshold
test: a capture is typically idle or near-idle for much of its length, so the
median survives a genuinely-moving minority and estimates the constant bias
(faulted or not) without needing a separate calibration step.

⚠️ ONLY DRIVES CAPTURED **AFTER** ARCH-064 DEPLOYS ARE VALID INPUT. Earlier
rows were recorded under the pre-ARCH-064 AK09916 axis map; feeding them here
would fit a calibration for an axis convention the sensor no longer uses.

QUALITY FLOOR (m7). Even a fit that passes coverage can be untrustworthy --
noisy, or a genuinely non-elliptical field. The fit REFUSES when the corrected
horizontal radius spread exceeds ``maxRadiusSpreadPercent`` (``--force`` /
``force=True`` accepts it anyway and the result is marked ``qualityForced``).

Input: a CSV exported from ``edr_imu_sample`` (see
``src/common/edr/sensor_schema.py``), e.g.::

    sqlite3 -csv -header obd.db "select * from edr_imu_sample where drive_id=N"

Ruling 20 (fit round 1 bug): that export's REAL column names --
``ts_capture``, ``accel_x``/``accel_y``/``accel_z``, ``gyro_x``/``gyro_y``/
``gyro_z``, ``mag_x``/``mag_y``/``mag_z``, ``drive_id`` -- are the PRIMARY
names this loader looks for. The unit-suffixed spelling
(``accel_x_ms2``/etc, ``mag_x_ut``/etc, as ``tools/imu/accel_cal_cli.py`` and
``tools/imu/fit_csv.py`` use) is accepted as an ALIAS. Extra columns in the
export (``id``, ``ts_utc``, ``seq``, ``temp_c``, ``data_source``,
``schema_version``, ...) are ignored. Gyro columns are OPTIONAL (see the
coverage-refusal fallback above); accel, mag and ``ts_capture`` are required,
and a header matching NEITHER naming scheme for a required group raises
immediately, naming what is missing -- fit round 1's bug was that a header
match failure silently produced zero rows, surfacing only as a generic
too-few-samples error with no indication the columns were ever wrong.

Usage:
    python -m tools.imu.fit_mag_calibration capture.csv [--drive-id 42]
        [--earth-vertical-ut -49.0] [--force]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass

import numpy as np

from pi.sensors.accel_cal import DEFAULT_MAX_GYRO_RAD_S
from pi.sensors.imu_state_bridge import resolveMountFrame

Vector3 = tuple[float, float, float]

# --- CSV column names (Ruling 20) ---------------------------------------------
# PRIMARY = the real edr_imu_sample columns (src/common/edr/sensor_schema.py).
# ALIAS = the unit-suffixed spelling tools/imu/accel_cal_cli.py and
# tools/imu/fit_csv.py already use for a hand-shaped export. Either is
# accepted; ts_capture and drive_id have only ever had the one spelling.
TS_COLUMN = "ts_capture"
DRIVE_ID_COLUMN = "drive_id"
ACCEL_COLUMNS_PRIMARY = ("accel_x", "accel_y", "accel_z")
ACCEL_COLUMNS_ALIAS = ("accel_x_ms2", "accel_y_ms2", "accel_z_ms2")
MAG_COLUMNS_PRIMARY = ("mag_x", "mag_y", "mag_z")
MAG_COLUMNS_ALIAS = ("mag_x_ut", "mag_y_ut", "mag_z_ut")
GYRO_COLUMNS_PRIMARY = ("gyro_x", "gyro_y", "gyro_z")
GYRO_COLUMNS_ALIAS = ("gyro_x_rads", "gyro_y_rads", "gyro_z_rads")

# 36 buckets of 10 degrees span the compass. Fewer than 25 occupied means more
# than a third of the compass was never sampled -- the ellipse the ordinate
# axes least-squares would return is an interpolation over headings never
# driven, not a fit.
HEADING_BINS = 36
BIN_WIDTH_DEG = 360.0 / HEADING_BINS
MIN_OCCUPIED_BINS = 25

# Ruling 23: a bin only counts as occupied with at least this many MOVING
# samples in it -- a single noise-scattered point (see the module docstring's
# dense-idle exploit) can no longer buy a bin on its own.
MIN_SAMPLES_PER_BIN = 3

# A conic has 6 coefficients (5 degrees of freedom); well under this many
# points the "fit" is closer to an exact interpolation than a measurement.
# In practice MIN_OCCUPIED_BINS is the binding constraint -- occupying 25 of
# 36 bins already requires at least 25 samples -- this is only a defensive
# floor against a pathological CSV with heavy duplication. Applied to BOTH the
# total sample count and (separately) the moving-sample count.
_MIN_SAMPLES = HEADING_BINS

# Ruling 23: the moving/idle boundary. Reused, not reinvented -- see the
# module docstring's coverage-refusal section for why this exact constant.
MOVING_MIN_GYRO_RAD_S = DEFAULT_MAX_GYRO_RAD_S

# m7: refuse a fit whose corrected radius disagrees with itself by more than
# this many percent, unless the caller explicitly overrides it.
MAX_RADIUS_SPREAD_PERCENT_DEFAULT = 5.0

# Below this, a would-be unit vector (gravity, or a horizontal-plane basis
# vector) is numerically indistinguishable from zero.
_MIN_VECTOR_NORM = 1e-6

# Ruling 22: Earth's own vertical field component, BODY-UP sign convention
# (positive = pointing away from Earth, i.e. toward the sky; Earth's real
# field points mostly DOWN in the northern hemisphere, so this is negative).
#
# DOCUMENTED, computed 2026-09-28 for Chicago (lat 41.88, lon -87.63), decimal
# year 2026.6658 (2026-09-01): WMM-2025 vertical intensity Z = 49002.75 nT in
# the standard geomagnetic convention (X=north, Y=east, Z=DOWN-positive), so
# in THIS module's body-up convention the expected reading is -49.0 uT.
#
# Computed via `pygeomag` (PyPI; a tested Python port of NOAA's own WMM/IGRF
# reference C code, using the bundled official WMM.COF WMM-2025 coefficients)
# rather than NOAA/NCEI's live `calculateIgrfwmm` API -- that endpoint (the one
# that reports vertical intensity) requires its OWN registered API key;
# CONFIRMED via curl that NOAA's demo keys are scoped per-calculator (the
# `calculateDeclination` demo key `zNEw7` and the `calculateUshistoric` demo
# key `yKc9F` are both rejected by `calculateIgrfwmm` with "key ... is wrong").
# CROSS-VALIDATED instead: pygeomag's declination for this exact lat/lon/date
# is -4.18228 deg, matching NOAA/NCEI's live `calculateDeclination` API to 5
# decimal places --
#   https://www.ngdc.noaa.gov/geomag-web/calculators/calculateDeclination?lat1=41.88&lon1=-87.63&resultFormat=json&key=zNEw7&startYear=2026&startMonth=9&startDay=1
#   fetched 2026-09-28, model WMM-2025 v1.2.1, declination -4.18228 -- so both
# tools read the same WMM-2025 coefficient set, and the vertical-intensity
# figure is trusted on that basis rather than on a self-implemented
# calculation alone. (pygeomag is not a project dependency; this constant is
# the only artefact of using it.)
DEFAULT_EARTH_VERTICAL_UT = -49.0


@dataclass(frozen=True)
class MagCalibrationFit:
    """Result of the planar hard/soft-iron fit, in BODY-frame coordinates."""

    hardIronUt: Vector3
    softIron: tuple[Vector3, Vector3, Vector3]
    totalSamples: int
    movingSamples: int
    headingBinsOccupied: int
    headingBinsTotal: int
    semiAxesUt: tuple[float, float]  # (major, minor)
    majorAxisRotationDeg: float  # m8: the LARGER semi-axis's angle, degrees
    # from the level-frame forward axis (counter-clockwise, standard math sign)
    radiusTargetUt: float
    radiusSpreadPercent: float
    residualRmsUt: float
    qualityForced: bool = False

    def toConfigBlock(self) -> dict[str, object]:
        """The ``pi.sensors.imu.magCalibration`` config block, verbatim shape."""
        return {
            "hardIronUt": [round(v, 4) for v in self.hardIronUt],
            "softIron": [[round(v, 6) for v in row] for row in self.softIron],
        }

    def describe(self) -> str:
        """One line for a log or a report."""
        forced = " (FORCED past the quality floor)" if self.qualityForced else ""
        return (
            f"hard iron ({self.hardIronUt[0]:+.2f}, {self.hardIronUt[1]:+.2f}, "
            f"{self.hardIronUt[2]:+.2f}) uT, ellipse major/minor axes "
            f"({self.semiAxesUt[0]:.2f}, {self.semiAxesUt[1]:.2f}) uT, major axis "
            f"rotated {self.majorAxisRotationDeg:.1f} deg, {self.headingBinsOccupied}/"
            f"{self.headingBinsTotal} heading bins, corrected radius spread "
            f"{self.radiusSpreadPercent:.2f}% over {self.movingSamples}/"
            f"{self.totalSamples} moving samples{forced}"
        )


def _resolveColumnSet(
    fieldnames: set[str],
    label: str,
    primary: tuple[str, ...],
    alias: tuple[str, ...],
    *,
    required: bool = True,
) -> tuple[str, ...] | None:
    """Pick whichever of ``primary``/``alias`` the CSV header actually has.

    Ruling 20: never silently return an empty result set because a header
    matched neither spelling -- raise immediately, naming what is missing, so
    a real export with the wrong assumed column names fails LOUDLY here
    rather than surfacing as an opaque "0 rows loaded" downstream.
    """
    if all(c in fieldnames for c in primary):
        return primary
    if all(c in fieldnames for c in alias):
        return alias
    if not required:
        return None
    raise ValueError(
        f"CSV is missing {label} columns: need either {primary} (the real "
        f"edr_imu_sample names, src/common/edr/sensor_schema.py) or {alias} "
        f"(the unit-suffixed export alias). Header has: {sorted(fieldnames)}"
    )


def loadRows(
    path: str, driveId: int | None = None
) -> list[tuple[float, Vector3, Vector3, Vector3 | None]]:
    """Load ``(tsCaptureS, accelBody, magBody, gyroRaw)`` from an ``edr_imu_sample`` CSV.

    Every accel and mag vector passes through ``resolveMountFrame`` (default
    mount) exactly once, here, so every consumer downstream is already in the
    BODY frame ``AhrsFusion`` applies the calibration in -- Ruling 18. Gyro is
    returned RAW (DEVICE-frame, no mount conversion, no bias correction): the
    per-capture bias median (Ruling 24) needs the WHOLE loaded set at once, so
    that step belongs to ``fitMagCalibration``, not this per-row loader; a
    mount conversion would not change anything the bias subtraction or the
    resulting magnitude cares about (magnitude is invariant under a signed
    axis permutation applied identically to both the reading and its bias),
    so it is skipped here rather than performed and then subtracted through.

    Args:
        path: CSV path. Accepts either the real ``edr_imu_sample`` column
            names or the unit-suffixed alias -- see the module docstring.
        driveId: When given, only rows whose ``drive_id`` column matches are
            kept. A row with an unparseable or missing ``drive_id`` is
            dropped rather than assumed to match -- an ambiguous drive
            membership must not silently enter the fit.

    Raises:
        ValueError: the CSV has no header, or is missing both the primary and
            alias spelling of a REQUIRED column group (``ts_capture``, accel,
            mag). Gyro columns are optional -- see ``GYRO_COLUMNS_PRIMARY``.
    """
    rows: list[tuple[float, Vector3, Vector3, Vector3 | None]] = []
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or ())
        if not fieldnames:
            raise ValueError(f"CSV has no header row: {path}")
        if TS_COLUMN not in fieldnames:
            raise ValueError(
                f"CSV is missing the required '{TS_COLUMN}' column. "
                f"Header has: {sorted(fieldnames)}"
            )
        accelCols = _resolveColumnSet(fieldnames, "accel", ACCEL_COLUMNS_PRIMARY, ACCEL_COLUMNS_ALIAS)
        magCols = _resolveColumnSet(fieldnames, "mag", MAG_COLUMNS_PRIMARY, MAG_COLUMNS_ALIAS)
        gyroCols = _resolveColumnSet(
            fieldnames, "gyro", GYRO_COLUMNS_PRIMARY, GYRO_COLUMNS_ALIAS, required=False
        )

        for row in reader:
            if driveId is not None:
                try:
                    rowDriveId = int(row[DRIVE_ID_COLUMN])
                except (KeyError, TypeError, ValueError):
                    continue
                if rowDriveId != driveId:
                    continue
            try:
                tsCaptureS = float(row[TS_COLUMN])
                ax, ay, az = (float(row[c]) for c in accelCols)
                mx, my, mz = (float(row[c]) for c in magCols)
                gyroRaw: Vector3 | None = None
                if gyroCols is not None:
                    gx, gy, gz = (float(row[c]) for c in gyroCols)
                    gyroRaw = (gx, gy, gz)
            except (KeyError, TypeError, ValueError):
                # A row with a missing or unparseable field is skipped rather
                # than defaulted: a fabricated zero would enter the fit as data.
                continue
            rows.append(
                (
                    tsCaptureS,
                    resolveMountFrame((ax, ay, az)),
                    resolveMountFrame((mx, my, mz)),
                    gyroRaw,
                )
            )
    return rows


def _meanGravity(accelBody: list[Vector3]) -> Vector3:
    """Average body-frame accel across the whole capture (see module docstring)."""
    n = len(accelBody)
    mean = (
        sum(v[0] for v in accelBody) / n,
        sum(v[1] for v in accelBody) / n,
        sum(v[2] for v in accelBody) / n,
    )
    if math.sqrt(sum(c * c for c in mean)) < _MIN_VECTOR_NORM:
        raise ValueError(
            "mean accel across the capture is ~zero -- no usable gravity reference "
            "(accel channel absent, or the capture never included any driving)"
        )
    return mean


def _levelBasis(gravity: Vector3) -> tuple[Vector3, Vector3, Vector3]:
    """Build an orthonormal (forwardHorizontal, leftHorizontal, up) body-frame basis.

    ``up`` is the gravity direction; ``forwardHorizontal`` is body +x projected
    onto the plane perpendicular to it (removing the mount-tilt component);
    ``leftHorizontal`` completes a right-handed set with a cross product, which
    -- unlike projecting +y independently -- guarantees the two horizontal axes
    are exactly orthogonal (needed for the basis-change matrix below to be its
    own inverse transpose).
    """
    gLen = math.sqrt(sum(c * c for c in gravity))
    up = (gravity[0] / gLen, gravity[1] / gLen, gravity[2] / gLen)
    fwdRaw = (1.0, 0.0, 0.0)
    dot = fwdRaw[0] * up[0] + fwdRaw[1] * up[1] + fwdRaw[2] * up[2]
    fwdProj = (fwdRaw[0] - dot * up[0], fwdRaw[1] - dot * up[1], fwdRaw[2] - dot * up[2])
    fwdLen = math.sqrt(sum(c * c for c in fwdProj))
    if fwdLen < _MIN_VECTOR_NORM:
        raise ValueError(
            "mount is tilted ~90 degrees from level (forward axis is parallel to "
            "gravity) -- no horizontal plane to project the magnetometer onto"
        )
    forward = (fwdProj[0] / fwdLen, fwdProj[1] / fwdLen, fwdProj[2] / fwdLen)
    # left = up x forward, matching the body convention (forward x left = up,
    # e.g. IMU_BODY_FRAME_C: +x forward, +y left, +z up is right-handed).
    left = (
        up[1] * forward[2] - up[2] * forward[1],
        up[2] * forward[0] - up[0] * forward[2],
        up[0] * forward[1] - up[1] * forward[0],
    )
    return forward, left, up


def _headingBinCoverage(
    p: np.ndarray, q: np.ndarray, centerP: float, centerQ: float, minPerBin: int
) -> int:
    """Count 10-degree heading bins with at least ``minPerBin`` samples (Ruling 23).

    Centred on the caller-supplied (FITTED) centre, not a raw centroid -- see
    the module docstring's dense-idle exploit for why that distinction matters.
    """
    angleDeg = np.degrees(np.arctan2(q - centerQ, p - centerP)) % 360.0
    binIdx = (angleDeg // BIN_WIDTH_DEG).astype(int) % HEADING_BINS
    counts = np.bincount(binIdx, minlength=HEADING_BINS)
    return int(np.sum(counts >= minPerBin))


def _fitConic(p: np.ndarray, q: np.ndarray) -> tuple[float, float, float, float, float, float]:
    """General conic least-squares fit: a.x^2 + b.xy + c.y^2 + d.x + e.y + f = 0.

    Points are centred first, purely for the numerical conditioning of the
    SVD (the [x^2, xy, y^2] columns otherwise dwarf [x, y, 1] once the ellipse
    sits far from the origin); the centring is undone by the caller.
    """
    design = np.column_stack([p * p, p * q, q * q, p, q, np.ones_like(p)])
    _, _, vt = np.linalg.svd(design)
    a, b, c, d, e, f = vt[-1]
    return float(a), float(b), float(c), float(d), float(e), float(f)


def _ellipseParams(
    a: float, b: float, c: float, d: float, e: float, f: float
) -> tuple[float, float, float, float, np.ndarray]:
    """Centre, semi-axis lengths and eigenvectors of a general conic.

    Raises:
        ValueError: the conic is degenerate (singular centre system) or is not
            an ellipse (non-positive axis-squared) -- both mean the data does
            not determine an ellipse, most likely too little heading coverage
            or too much noise relative to the field's horizontal swing.
    """
    lhs = np.array([[2.0 * a, b], [b, 2.0 * c]])
    rhs = np.array([-d, -e])
    try:
        x0, y0 = np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "ellipse fit is singular -- the horizontal magnetometer samples do "
            "not determine a centre (collinear or too little heading spread)"
        ) from exc
    f0 = a * x0 * x0 + b * x0 * y0 + c * y0 * y0 + d * x0 + e * y0 + f
    quadForm = np.array([[a, b / 2.0], [b / 2.0, c]])
    eigvals, eigvecs = np.linalg.eigh(quadForm)
    axesSquared = -f0 / eigvals
    if not np.all(np.isfinite(axesSquared)) or np.any(axesSquared <= 0):
        raise ValueError(
            "conic fit is not an ellipse (non-positive axis) -- the horizontal "
            "magnetometer samples are too noisy or too collinear to fit"
        )
    axes = np.sqrt(axesSquared)
    return float(x0), float(y0), float(axes[0]), float(axes[1]), eigvecs


def fitMagCalibration(
    rows: list[tuple[float, Vector3, Vector3, Vector3 | None]],
    *,
    earthVerticalUt: float = DEFAULT_EARTH_VERTICAL_UT,
    maxRadiusSpreadPercent: float = MAX_RADIUS_SPREAD_PERCENT_DEFAULT,
    force: bool = False,
) -> MagCalibrationFit:
    """Fit the planar hard/soft-iron calibration from BODY-frame capture rows.

    Args:
        rows: ``(tsCaptureS, accelBody, magBody, gyroRaw)`` as returned by
            ``loadRows``. ``gyroRaw`` may be None (no gyro columns in the
            source CSV) -- see Ruling 23's moving/idle fallback. When present
            it is RAW (bias not yet removed); the per-axis median bias is
            estimated and subtracted here (Ruling 24) before gating.
        earthVerticalUt: Earth's expected vertical field component, BODY-UP
            sign convention (Ruling 22). Defaults to the DOCUMENTED Chicago
            WMM-2025 value; override for a different location.
        maxRadiusSpreadPercent: m7 quality floor -- see module docstring.
        force: m7 -- accept a fit whose radius spread exceeds
            ``maxRadiusSpreadPercent`` anyway (``qualityForced=True`` on the
            result) instead of refusing.

    Raises:
        ValueError: too few total or moving samples, insufficient heading
            coverage (Ruling 23), no usable gravity reference, a degenerate/
            non-ellipse fit, or (unless ``force``) a radius spread over the
            quality floor.
    """
    total = len(rows)
    if total < _MIN_SAMPLES:
        raise ValueError(f"need at least {_MIN_SAMPLES} samples, got {total}")

    accelBody = [r[1] for r in rows]
    magBody = [r[2] for r in rows]
    gyroRaw = [r[3] for r in rows]

    gravity = _meanGravity(accelBody)
    forward, left, up = _levelBasis(gravity)

    p = np.array([m[0] * forward[0] + m[1] * forward[1] + m[2] * forward[2] for m in magBody])
    q = np.array([m[0] * left[0] + m[1] * left[1] + m[2] * left[2] for m in magBody])
    r = np.array([m[0] * up[0] + m[1] * up[1] + m[2] * up[2] for m in magBody])

    # Ruling 23/24: idle dwell must not enter the fit or the coverage count.
    # The gyro is RAW (no bias removed upstream -- edr_imu_sample carries the
    # sensor's own reading, and the A-34 faulted-offset defect puts a
    # constant ~0.5 rad/s on one axis, well above MOVING_MIN_GYRO_RAD_S). The
    # per-axis MEDIAN over the whole capture is a robust bias estimate (a
    # capture is typically idle/near-idle for much of its length) and is
    # subtracted before the magnitude/threshold test -- see module docstring.
    if all(g is not None for g in gyroRaw):
        gyroMatrix = np.array(gyroRaw)  # shape (N, 3)
        gyroBiasPerAxis = np.median(gyroMatrix, axis=0)
        gyroMagRadS = np.linalg.norm(gyroMatrix - gyroBiasPerAxis, axis=1)
        movingMask = gyroMagRadS > MOVING_MIN_GYRO_RAD_S
    else:
        # Ruling 23's documented fallback: no gyro signal to filter on.
        movingMask = np.ones(len(rows), dtype=bool)
    movingCount = int(np.sum(movingMask))
    if movingCount < _MIN_SAMPLES:
        raise ValueError(
            f"need at least {_MIN_SAMPLES} moving samples (gyro magnitude > "
            f"{MOVING_MIN_GYRO_RAD_S} rad/s), got {movingCount} moving out of "
            f"{total} total -- a capture that mostly idled cannot fit a "
            "heading-dependent ellipse from its idle dwell."
        )
    pM, qM, rM = p[movingMask], q[movingMask], r[movingMask]

    # Ruling 22: subtract Earth's own vertical field before what remains is
    # called hard iron -- see module docstring and DEFAULT_EARTH_VERTICAL_UT.
    hz = float(np.mean(rM)) - earthVerticalUt

    pMean, qMean = float(np.mean(pM)), float(np.mean(qM))
    coeffs = _fitConic(pM - pMean, qM - qMean)
    x0c, y0c, r1, r2, eigvecs = _ellipseParams(*coeffs)
    x0, y0 = x0c + pMean, y0c + qMean

    # Ruling 23: bins centred on the FITTED centre, moving samples only.
    occupied = _headingBinCoverage(pM, qM, x0, y0, MIN_SAMPLES_PER_BIN)
    if occupied < MIN_OCCUPIED_BINS:
        raise ValueError(
            f"heading coverage insufficient: {occupied}/{HEADING_BINS} 10-degree "
            f"bins occupied (>= {MIN_SAMPLES_PER_BIN} moving samples each, "
            "centred on the fitted ellipse centre), need at least "
            f"{MIN_OCCUPIED_BINS}. Drive through more headings -- a capture "
            "that only ever turned through part of the compass cannot "
            "determine an ellipse for the rest of it."
        )

    # Map the fitted ellipse onto a circle of the geometric-mean radius: this
    # preserves the field's total horizontal magnitude (r1 * r2 == target^2)
    # rather than favouring either axis.
    radiusTarget = math.sqrt(r1 * r2)
    rotationMatrix = eigvecs  # columns are the (orthonormal) ellipse axes
    scaleDiag = np.diag([radiusTarget / r1, radiusTarget / r2])
    softIron2D = rotationMatrix @ scaleDiag @ rotationMatrix.T

    centred = np.column_stack([pM - x0, qM - y0])
    corrected = centred @ softIron2D.T
    correctedRadii = np.hypot(corrected[:, 0], corrected[:, 1])
    residualRmsUt = float(np.sqrt(np.mean((correctedRadii - radiusTarget) ** 2)))
    # RMS residual as a percentage of the target radius, not (max-min)/mean:
    # with hundreds of samples a couple of noise-tail points can double a
    # max-min spread without the fit itself being any worse, exactly the way
    # SphereFit/AccelCalibration elsewhere in this codebase score a fit by its
    # RMS residual rather than by its widest single outlier.
    radiusSpreadPercent = (
        residualRmsUt / radiusTarget * 100.0 if radiusTarget > 0 else float("inf")
    )

    # m7: a fit that passed coverage can still be untrustworthy.
    qualityForced = False
    if radiusSpreadPercent > maxRadiusSpreadPercent:
        if not force:
            raise ValueError(
                f"corrected radius spread {radiusSpreadPercent:.2f}% exceeds the "
                f"{maxRadiusSpreadPercent}% quality floor -- this fit is not "
                "trustworthy (noisy capture, or a genuinely non-elliptical "
                "field). Pass --force / force=True to accept it anyway."
            )
        qualityForced = True

    # m8: report the MAJOR (larger) axis's rotation, not an arbitrary one --
    # eigh's ascending eigenvalue order does not correspond to "major first".
    axes = (r1, r2)
    majorIdx = 0 if r1 >= r2 else 1
    minorIdx = 1 - majorIdx
    majorAxisRotationDeg = math.degrees(math.atan2(eigvecs[1, majorIdx], eigvecs[0, majorIdx]))

    # Embed: B's rows are (forward, left, up) -- body vector v -> level coords
    # is B @ v. The 2-D soft-iron correction (plus an identity z row/col) is
    # applied in level coords, then B^T (== B^-1, B orthonormal) maps back to
    # the body frame AhrsFusion actually applies the calibration in.
    basis = np.array([forward, left, up])
    correction3D = np.eye(3)
    correction3D[:2, :2] = softIron2D
    softIronBody = basis.T @ correction3D @ basis
    hardIronBody = basis.T @ np.array([x0, y0, hz])

    return MagCalibrationFit(
        hardIronUt=tuple(float(v) for v in hardIronBody),
        softIron=tuple(tuple(float(v) for v in row) for row in softIronBody),
        totalSamples=total,
        movingSamples=movingCount,
        headingBinsOccupied=occupied,
        headingBinsTotal=HEADING_BINS,
        semiAxesUt=(axes[majorIdx], axes[minorIdx]),
        majorAxisRotationDeg=majorAxisRotationDeg,
        radiusTargetUt=radiusTarget,
        radiusSpreadPercent=radiusSpreadPercent,
        residualRmsUt=residualRmsUt,
        qualityForced=qualityForced,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Planar hard/soft-iron magnetometer calibration fit (ARCH-064)"
    )
    parser.add_argument("csv")
    parser.add_argument("--drive-id", type=int, default=None)
    parser.add_argument(
        "--earth-vertical-ut",
        type=float,
        default=DEFAULT_EARTH_VERTICAL_UT,
        help="Earth's expected vertical field, body-up sign convention (Ruling 22)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="accept a fit whose radius spread exceeds the quality floor (m7)",
    )
    args = parser.parse_args(argv)

    # Ruling 24: loadRows raising (e.g. the wrong CSV columns, C1) is a
    # refusal like any other -- it must come out as this CLI's {"refused":
    # ...} JSON, not an uncaught traceback, so it is inside the same try.
    rows: list[tuple[float, Vector3, Vector3, Vector3 | None]] = []
    try:
        rows = loadRows(args.csv, driveId=args.drive_id)
        fit = fitMagCalibration(
            rows, earthVerticalUt=args.earth_vertical_ut, force=args.force
        )
    except ValueError as exc:
        print(json.dumps({"refused": str(exc), "samples": len(rows)}, indent=2))
        return 1

    result = {
        "magCalibration": fit.toConfigBlock(),
        "fitQuality": {
            "totalSamples": fit.totalSamples,
            "movingSamples": fit.movingSamples,
            "headingBinsOccupied": fit.headingBinsOccupied,
            "headingBinsTotal": fit.headingBinsTotal,
            "semiAxesUt": [round(v, 3) for v in fit.semiAxesUt],
            "majorAxisRotationDeg": round(fit.majorAxisRotationDeg, 2),
            "radiusTargetUt": round(fit.radiusTargetUt, 3),
            "radiusSpreadPercent": round(fit.radiusSpreadPercent, 3),
            "residualRmsUt": round(fit.residualRmsUt, 3),
            "qualityForced": fit.qualityForced,
            "describe": fit.describe(),
        },
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
