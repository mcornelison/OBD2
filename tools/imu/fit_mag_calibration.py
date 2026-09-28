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
   at all, a sample is moving unless the MAGNETOMETER judges it stationary
   (Ruling 29a; until round 5 every such sample counted as moving, so
   movingSamples over-reported by the whole parked dwell).
3. A bin only counts occupied with at least ``MIN_SAMPLES_PER_BIN`` (3)
   samples in it -- a single noise-scattered outlier can no longer buy a bin.

The fit REFUSES when fewer than ``MIN_OCCUPIED_BINS`` (25) of 36 qualify.

Ruling 24: the gyro used for (2) is BIAS-CORRECTED, not raw. ``edr_imu_sample``
carries the RAW gyro (no bias removed upstream), and the A-34 faulted-offset
defect puts a constant ~0.5 rad/s offset on one axis -- well above
``MOVING_MIN_GYRO_RAD_S`` (0.05), which would mark every idle sample "moving"
on a faulted board and make this whole defence inert.

Ruling 25 (fit round 3 -- Ruling 24's fix round 2 approach was itself
defective). Ruling 24 subtracted the PER-AXIS MEDIAN gyro over the WHOLE
capture, reasoning that a capture is typically idle for much of its length.
MEASURED to fail on exactly the calibration procedure this tool asks the CIO
to drive: **steady circling with no idle dwell at all**. A whole-capture
median over a uniformly-circling signal (alternating, say, 0.3/0.7 rad/s)
converges toward the MOVING rate itself (its own median), so subtracting it
collapses every sample's debiased magnitude toward the noise floor --
misclassifying the ENTIRE capture as idle and refusing a perfectly good
capture with a message ("mostly idled") that is actively wrong: the car
never stopped turning. Worse, adding idle rows to that same circling capture
does not fix it -- it can INVERT the gate instead (idle rows biased toward
"moving", moving rows biased toward "idle"), refusing the combined capture
too. It failed closed both times (never a silent bad fit), but it rejected
the right procedure.

Fixed by estimating the bias from WHICH SAMPLES, not by aggregating ALL of
them: a sample's raw gyro reading IS the bias exactly when the car is not
turning, and "not turning" is answered independently of the (possibly
faulted) gyro by asking whether the horizontal MAGNETOMETER direction held
still over a short window (``_stationaryMask``).

Ruling 28 (fit round 4) -- round 3 measured that direction about the ORIGIN,
claiming this "needs no hard-iron centre". MEASURED wrong on this car: with
the hard-iron offset |h| comparable to or larger than the circle radius R,
the origin sits near or outside the circle, the apparent rotation seen from
it shrinks on the far side and is zero at the tangent points, and turning
rows were classed as parked -- gyro bias 0.80 against a true 0.50, and the
recommended parked-bookend procedure REFUSED. Now the direction is measured
about a PROVISIONAL CENTRE (``_provisionalCentre``: the bounding-box
midrange of the horizontal field, which parked rows cannot move because they
lie on the ellipse), against every row out to >= 2 s away. See
``STATIONARY_WINDOW_S`` / ``STATIONARY_HEADING_DELTA_DEG`` for the sizing
and its justification against the sample rate and noise. Too few stationary
samples (a capture that never held still, e.g. continuous circling with no
parked stretch) REFUSES with a distinct message naming that specifically.
Too few MOVING samples (Ruling 28 item 5) now asks the magnetometer which of
two causes it is: if the magnetometer shows the car turning, the message
blames the gyro (frozen/faulted, or a wrong bias estimate); only if the
magnetometer agrees nothing turned does it say the capture never turned.
Round 3 blamed the drive in both cases.

⚠️ ONLY DRIVES CAPTURED **AFTER** ARCH-064 DEPLOYS ARE VALID INPUT. Earlier
rows were recorded under the pre-ARCH-064 AK09916 axis map; feeding them here
would fit a calibration for an axis convention the sensor no longer uses.

QUALITY FLOOR (m7, noise-aware since Ruling 29a). Even a fit that passes
coverage can be untrustworthy -- a genuinely non-elliptical field, or a
capture that moved the sensor. The fit REFUSES when the corrected radius RMS
residual exceeds max(``maxRadiusSpreadPercent`` of R, 2 x sigmaHat), sigmaHat
being the magnetometer noise measured on the parked rows (1.0 uT when too few
were parked to measure it; reported as ``sigmaHatUt``). A fixed percentage of
R alone refused every honest weak circle -- its residual is noise, and noise
does not shrink with R (MEASURED: R 5.8 uT, sigma 0.3 -> 5.14 %, refused).
``--force`` / ``force=True`` accepts it anyway and marks ``qualityForced``.

UNOBSERVABLE: HORIZONTAL/VERTICAL GAIN (Ruling 26). A PLANAR capture -- one
level circle -- cannot tell a correctly-scaled sensor from one whose
horizontal gain differs from its vertical gain: the car body itself can
attenuate the horizontal field differently from the vertical one (steel
roof/floor sandwiching a horizontally-mounted board, say), and a level
capture's horizontal locus is still a circle either way -- gain only shows up
once the car TILTS and some of that unequal gain rotates into the plane the
ellipse fit is reading. WORKED EXAMPLE: horizontal gain a=0.3, vertical gain
k_v=1, 3 degrees of pitch, gives ~19 degrees of heading error at E/W headings
-- a defect this tool cannot see from a planar capture and therefore cannot
correct. So it does the honest thing instead: MEASURE and WARN, never
silently. ``horizontalGain`` (the fitted circle's radius divided by
``earthHorizontalUt``, ``DEFAULT_EARTH_HORIZONTAL_UT``'s DOCUMENTED WMM-2025
value unless overridden) is always reported; outside 0.8-1.2 it comes with a
WARNING (never a refusal -- there is nothing a planar fit can do about it
except say so) that heading on graded roads may be biased.

VERTICAL COMPANION (Ruling 28 item 4). ``verticalFieldRatio`` (the mean
body-up field of the moving rows divided by ``earthVerticalUt``) is always
reported; when the two differ by more than ``VERTICAL_FIELD_WARN_FRACTION``
(10 %) of ``|earthVerticalUt|`` it WARNS, never refuses: the car alters the
vertical field, or there is large z iron, or ``--earth-vertical-ut`` is
wrong for the capture location. Hard-iron z absorbs the difference in every
case; the warning makes it visible.

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

# Ruling 28 (fix round 4): stationary-window sizing for gyro bias estimation.
# Round 3 judged "not turning" by the change in the RAW (p, q) direction seen
# from the ORIGIN, against the immediate neighbours (~0.5 s), at 2 degrees.
# MEASURED wrong on this car's geometry: when the hard-iron offset |h| is
# comparable to or larger than the circle radius R (drive 77: 17.59 vs 16.43
# uT, RECALLED, pre-fix axis map), the origin sits near or outside the circle,
# so the apparent rotation seen from it shrinks on the far side and is ZERO at
# the tangent points -- turning rows read as parked, their gyro (bias + rate)
# enters the median, and the bias came out 0.80 instead of 0.50. Gentle turns
# failed the same way even with |h| < R: 0.1 rad/s moves only 2.9 degrees in
# 0.5 s, which the noise band swallows.
#
# STATIONARY_WINDOW_S -- each row is compared against rows at least this far
# away in ts_capture (rows arrive at the ~2 Hz EDR persistHz, so ~4 rows).
# Over 2 s a gentle 0.1 rad/s turn moves 11.5 degrees -- far clear of the
# per-comparison noise (0.3-0.6 uT on R ~16 uT: sqrt(2) * sigma / R = 1.5-3.0
# degrees, 1 sigma). A 0.5 s window would put that same turn at 2.9 degrees,
# inside the noise.
STATIONARY_WINDOW_S = 2.0
#
# The comparison row must lie within this span of the row being judged. A
# gap in ts_capture (a dropped burst, a paused capture) must not turn two
# rows a lap apart into a "held still" pair.
_STATIONARY_MAX_SPAN_S = 2.0 * STATIONARY_WINDOW_S
#
# STATIONARY_HEADING_DELTA_DEG -- chosen so the stationary test and the
# moving gate meet at the SAME rate: a row is "held still" only if its
# apparent rotation over the window is below MOVING_MIN_GYRO_RAD_S (0.05 rad/s
# x 2 s = 5.7 degrees). One threshold, two views of it -- the gyro's and the
# magnetometer's. Against the noise: 5.7 degrees is 1.9-3.8 sigma of a single
# comparison, and a row needs only ONE side (earlier or later) to hold. Against
# motion: a 0.1 rad/s turn reads 11.5 degrees over the window, still 9.2 after
# the worst apparent-rate shrink the brief's 20/16 ellipse imposes (x0.8), so
# every turn at or above 0.1 rad/s is excluded. Rows creeping below ~0.06
# rad/s can pass; their gyro then contaminates the median by at most that
# rate, and only in proportion to how many of them there are versus parked
# rows -- which is why the procedure asks for a parked stretch.
STATIONARY_HEADING_DELTA_DEG = math.degrees(MOVING_MIN_GYRO_RAD_S * STATIONARY_WINDOW_S)
#
# That 5.7 degrees is the FLOOR of the threshold, not the threshold (Ruling
# 29a): the threshold used is max(5.7 deg, degrees(3 * sigmaHat / R)), R the
# provisional radius. A fixed 5.7 deg assumes the noise is small against R;
# on a weak circle it is not -- MEASURED at R 5.8 uT, sigma 0.6 uT, only 15 of
# 120 parked rows qualified (one comparison's noise is sqrt(2) * 0.6 / 5.8 =
# 8.4 deg, so 5.7 deg rejects most of them). 3 sigma of a single row's angle
# is ~2.1 sigma of a comparison: most parked rows pass. The price: on a weak,
# noisy circle, slow turns (below 3 sigma / R / window rad/s) also pass, and
# contaminate the bias median by at most their rate.
_THRESHOLD_NOISE_SIGMAS = 3.0
#
# The threshold needs sigmaHat, and sigmaHat is measured on the rows the
# threshold selects. Bootstrap: start at the 5.7-degree floor, measure
# sigmaHat on the rows it selects, re-derive the threshold, re-select -- up
# to this many passes, stopping once the threshold moves by under 0.1 deg.
# The first pass UNDER-estimates sigma (a tight threshold keeps the rows that
# happen to scatter least), so the threshold climbs toward the fixed point
# from below; it never starts above the true noise. If a pass finds fewer
# than _MIN_STATIONARY_SAMPLES usable rows, the threshold stays where it is
# (the 1.0 uT fallback below is for the quality floor only -- widening the
# stationary test on a GUESSED noise would let gentle turns in).
_THRESHOLD_BOOTSTRAP_PASSES = 4
#
# Ruling 29a: when too few stationary rows exist to measure the noise,
# sigmaHat for the QUALITY FLOOR falls back to this (a typical AK09916 noise
# figure is 0.3-0.6 uT; 1.0 is deliberately generous, so a capture that gave
# us nothing to measure is judged by the 5 % floor or a 2 uT one).
_SIGMA_HAT_FALLBACK_UT = 1.0
#
# Ruling 29a: the quality floor is max(5 % of R, this many sigmaHat). A
# circle's radial RMS residual is ~sigma from noise alone, so a fixed 5 % of
# R refuses every honest weak circle (MEASURED: R 5.8, sigma 0.3 -> 5.14 %,
# REFUSED). 2 sigma leaves room for noise; a systematic misfit (a
# non-elliptical locus) still exceeds it.
_QUALITY_NOISE_SIGMAS = 2.0
#
# Ruling 29a: the provisional centre is a COUNT-TRIMMED midrange -- drop this
# many most extreme rows at each end, per axis. A COUNT, not a percentile: at
# 95-99 % parked dwell both percentiles of a (2, 98) midrange land INSIDE the
# parked cluster (MEASURED by the reviewer: 6.5 / 13.9 / 18.0 uT centre error),
# while a fixed count of 3 still reaches the circle's own extremes and
# survives up to three spikes per side (0.24-0.43 uT).
_CENTRE_TRIM_COUNT = 3
#
# Degenerate locus: the magnetometer saw no turn at all (an all-parked
# capture) and the provisional centre lands INSIDE the parked cluster, where
# angles about it are pure noise. Detected by CONTINUITY, not size (round 4's
# fixed 4 uT radius floor would refuse an honest R 3.9 uT circle) and not
# shape (a "rows near the centre" test was MEASURED to flag an honest
# 120-degree arc, whose box midpoint sits close to the arc): about a centre
# inside a noise cluster the direction jumps at random from one row to the
# next -- median jump 90 degrees -- while on any real locus, parked or
# turning, it moves smoothly (the fastest plausible turn, 1 rad/s at the
# ~2 Hz EDR rate, is 29 degrees per row). The line sits at 60 degrees.
_DEGENERATE_MEDIAN_STEP_DEG = 60.0
#
# A median needs enough points to be a robust centre, not a coincidence; 10
# is a practical floor, well under what even a few seconds of the brief's
# own "~30 s parked" bookend would provide, while still catching a capture
# that truly never held still (continuous circling with no parked stretch).
_MIN_STATIONARY_SAMPLES = 10

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

# Ruling 26: Earth's HORIZONTAL field magnitude, same computation/date/source
# as DEFAULT_EARTH_VERTICAL_UT above -- DOCUMENTED, computed 2026-09-28 for
# Chicago (lat 41.88, lon -87.63), decimal year 2026.6658 (2026-09-01):
# WMM-2025 horizontal intensity H = 19414.041 nT via the same `pygeomag`
# WMM-2025 run (the one cross-validated against NOAA/NCEI's live
# calculateDeclination API to 5 decimal places -- see above), i.e. 19.4 uT.
# Used only as the denominator of ``horizontalGain`` (see module docstring's
# Ruling 26 section) -- a planar fit cannot correct a horizontal/vertical
# gain mismatch, only flag one, so this constant never enters the emitted
# calibration itself.
DEFAULT_EARTH_HORIZONTAL_UT = 19.4

# Ruling 26: horizontalGain outside this band WARNS (never refuses). Module
# constants, not literals, so a test can prove it reads each edge.
HORIZONTAL_GAIN_WARN_LOW = 0.8
HORIZONTAL_GAIN_WARN_HIGH = 1.2

# Ruling 28 item 4, the vertical companion to horizontalGain: warn when the
# mean body-up field differs from earthVerticalUt by more than this fraction
# of |earthVerticalUt|. Either the car alters the vertical field, or there is
# large z iron, or --earth-vertical-ut is wrong for where the capture was
# made. h_z absorbs all three, so this is a WARNING, never a refusal.
VERTICAL_FIELD_WARN_FRACTION = 0.10


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
    # Ruling 26: fitted horizontal circle radius / earthHorizontalUt. Always
    # reported; horizontalGainWarning is set (never raised) outside 0.8-1.2 --
    # a planar capture cannot correct this, only flag it.
    horizontalGain: float = 1.0
    horizontalGainWarning: str | None = None
    # Ruling 28: mean body-up field / earthVerticalUt. Always reported;
    # verticalFieldWarning is set (never raised) when the two differ by more
    # than VERTICAL_FIELD_WARN_FRACTION of |earthVerticalUt|.
    verticalFieldRatio: float = 1.0
    verticalFieldWarning: str | None = None
    # Ruling 25/28: the per-axis gyro bias subtracted before the moving gate,
    # rad/s, raw DEVICE axes. None when the CSV carried no gyro columns.
    gyroBiasRadS: Vector3 | None = None
    # Ruling 29a: magnetometer noise measured from the parked rows (None when
    # too few; the quality floor then assumes _SIGMA_HAT_FALLBACK_UT), and
    # the RMS-residual floor it produced.
    sigmaHatUt: float | None = None
    qualityFloorUt: float = 0.0

    def toConfigBlock(self) -> dict[str, object]:
        """The ``pi.sensors.imu.magCalibration`` config block, verbatim shape."""
        return {
            "hardIronUt": [round(v, 4) for v in self.hardIronUt],
            "softIron": [[round(v, 6) for v in row] for row in self.softIron],
        }

    def describe(self) -> str:
        """One line for a log or a report."""
        forced = " (FORCED past the quality floor)" if self.qualityForced else ""
        warned = " [WARNING: unobserved horizontal/vertical gain]" if self.horizontalGainWarning else ""
        if self.verticalFieldWarning:
            warned += " [WARNING: vertical field differs from Earth's expected]"
        return (
            f"hard iron ({self.hardIronUt[0]:+.2f}, {self.hardIronUt[1]:+.2f}, "
            f"{self.hardIronUt[2]:+.2f}) uT, ellipse major/minor axes "
            f"({self.semiAxesUt[0]:.2f}, {self.semiAxesUt[1]:.2f}) uT, major axis "
            f"rotated {self.majorAxisRotationDeg:.1f} deg, {self.headingBinsOccupied}/"
            f"{self.headingBinsTotal} heading bins, corrected radius spread "
            f"{self.radiusSpreadPercent:.2f}% over {self.movingSamples}/"
            f"{self.totalSamples} moving samples, horizontal gain "
            f"{self.horizontalGain:.3f}{forced}{warned}"
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
    Ruling 25 stationary-window bias estimate needs the WHOLE loaded capture
    (and its ``ts_capture`` ordering) at once, so that step belongs to
    ``fitMagCalibration``, not this per-row loader; a mount conversion would
    not change anything the bias subtraction or the resulting magnitude
    cares about (magnitude is invariant under a signed axis permutation
    applied identically to both the reading and its bias), so it is skipped
    here rather than performed and then subtracted through.

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


def _trimmedMidrange(values: np.ndarray) -> tuple[float, float]:
    """(midpoint, half-extent) of ``values`` after dropping the
    ``_CENTRE_TRIM_COUNT`` most extreme rows at EACH end (Ruling 29a).

    Untrimmed when there are too few rows to spare them.
    """
    ordered = np.sort(values)
    trim = _CENTRE_TRIM_COUNT if len(ordered) > 2 * _CENTRE_TRIM_COUNT + 1 else 0
    low, high = float(ordered[trim]), float(ordered[len(ordered) - 1 - trim])
    return (high + low) / 2.0, (high - low) / 2.0


def _provisionalCentre(p: np.ndarray, q: np.ndarray) -> tuple[float, float]:
    """Rulings 28/29a: a first guess at the ellipse centre, BEFORE any fit.

    The COUNT-TRIMMED midrange per axis (``_trimmedMidrange``). A midrange
    rather than a first-pass conic fit because parked rows lie ON the
    ellipse, inside its bounding box, so dwell cannot move the box's middle;
    a conic fit weights every row, and 2000 parked rows at one point would
    drag it (the Ruling 23 exploit, again). A rotated ellipse's bounding box
    is centred on the ellipse centre, so with full heading coverage this IS
    the centre up to noise in the extreme rows. Trimmed by a fixed COUNT, not
    a percentile: round 4's plain midrange moved by half of any spike
    (one +40 uT row moved it 20 uT), and a percentile midrange lands inside
    the parked cluster once dwell is heavy -- see ``_CENTRE_TRIM_COUNT``.
    With partial coverage the midrange is off-centre, but such a capture is
    refused on coverage anyway.
    """
    return _trimmedMidrange(p)[0], _trimmedMidrange(q)[0]


def _provisionalRadius(p: np.ndarray, q: np.ndarray) -> float:
    """Mean trimmed half-extent of the horizontal field -- the R that the
    angle noise (sigma / R) is scaled by."""
    return (_trimmedMidrange(p)[1] + _trimmedMidrange(q)[1]) / 2.0


def _locusIsDegenerate(
    tsArray: np.ndarray, p: np.ndarray, q: np.ndarray, centreP: float, centreQ: float
) -> bool:
    """True when the provisional centre sits inside the data (the car never
    turned): the direction about it jumps at random between consecutive
    rows -- see ``_DEGENERATE_MEDIAN_STEP_DEG``."""
    if len(p) < 2:
        return True
    order = np.argsort(tsArray, kind="stable")
    phi = np.arctan2(q[order] - centreQ, p[order] - centreP)
    step = np.abs((np.diff(phi) + math.pi) % (2.0 * math.pi) - math.pi)
    return math.degrees(float(np.median(step))) > _DEGENERATE_MEDIAN_STEP_DEG


def _stationaryMask(
    tsArray: np.ndarray,
    p: np.ndarray,
    q: np.ndarray,
    centreP: float,
    centreQ: float,
    thresholdDeg: float = STATIONARY_HEADING_DELTA_DEG,
) -> np.ndarray:
    """Ruling 28: rows whose horizontal field direction, seen from the
    PROVISIONAL CENTRE, held still for ``STATIONARY_WINDOW_S`` -- a
    non-turning row's raw gyro reading IS the bias, whatever the gyro fault.

    Angles are measured about ``(centreP, centreQ)``, not the origin: about
    the centre, a real turn at rate w moves the direction at ~w on every
    side of the ellipse (between b/a and a/b of it), whereas about the
    origin it shrinks to zero at the tangent points once |h| ~ R (the
    round-3 defect).

    A row is stationary when, on EITHER side (earlier or later), every row
    out to the first one at least ``STATIONARY_WINDOW_S`` away stays within
    ``thresholdDeg`` of it. Checking every row in the window, not just the
    far end, stops a fast turn that happens to come full circle from reading
    as held still; allowing either side lets the first and last rows of a
    parked stretch qualify. A side whose far row is beyond
    ``_STATIONARY_MAX_SPAN_S`` (a gap in the capture) does not count.
    """
    order = np.argsort(tsArray, kind="stable")
    ts = tsArray[order]
    phi = np.arctan2(q[order] - centreQ, p[order] - centreP)
    n = len(ts)
    thresholdRad = math.radians(thresholdDeg)
    # First row at or after ts + window; last row at or before ts - window.
    forwardEnd = np.searchsorted(ts, ts + STATIONARY_WINDOW_S, side="left")
    backwardEnd = np.searchsorted(ts, ts - STATIONARY_WINDOW_S, side="right") - 1

    stationarySorted = np.zeros(n, dtype=bool)
    for k in range(n):
        sides = (
            (forwardEnd[k], slice(k + 1, forwardEnd[k] + 1)),
            (backwardEnd[k], slice(backwardEnd[k], k)),
        )
        for endIdx, window in sides:
            if endIdx < 0 or endIdx >= n:
                continue
            if abs(ts[endIdx] - ts[k]) > _STATIONARY_MAX_SPAN_S:
                continue
            delta = (phi[window] - phi[k] + math.pi) % (2.0 * math.pi) - math.pi
            if float(np.max(np.abs(delta))) <= thresholdRad:
                stationarySorted[k] = True
                break
    stationary = np.zeros(n, dtype=bool)
    stationary[order] = stationarySorted
    return stationary


def _sigmaHatUt(
    tsArray: np.ndarray, p: np.ndarray, q: np.ndarray, stationary: np.ndarray
) -> float | None:
    """Ruling 29a: per-axis magnetometer noise, uT, from the STATIONARY rows'
    scatter about their LOCAL mean. None when fewer than
    ``_MIN_STATIONARY_SAMPLES`` rows can be used.

    Local = the stationary rows of the same unbroken parked run (no turning
    row, no ts gap over ``_STATIONARY_MAX_SPAN_S`` between them) within
    ``STATIONARY_WINDOW_S`` of the row. A local mean, not a run-wide one, so
    slow drift over a long parked stretch is not read as noise. Each residual
    is scaled by sqrt(m / (m - 1)) for its window of m rows (a mean of m
    noisy rows absorbs 1/m of each one's variance); rows with m < 3 are
    skipped. The scale is 1.4826 x the median |residual| over both axes --
    the MAD, so a few turning rows that slipped into the mask do not inflate it.
    """
    order = np.argsort(tsArray, kind="stable")
    ts, pS, qS, mask = tsArray[order], p[order], q[order], stationary[order]
    gaps = np.concatenate([[False], np.diff(ts) > _STATIONARY_MAX_SPAN_S])
    runId = np.cumsum(~mask | gaps)
    low = np.searchsorted(ts, ts - STATIONARY_WINDOW_S, side="left")
    high = np.searchsorted(ts, ts + STATIONARY_WINDOW_S, side="right")

    residuals: list[float] = []
    usedRows = 0
    for k in np.flatnonzero(mask):
        window = slice(low[k], high[k])
        local = mask[window] & (runId[window] == runId[k])
        m = int(np.sum(local))
        if m < 3:
            continue
        scale = math.sqrt(m / (m - 1.0))
        residuals.append((pS[k] - float(np.mean(pS[window][local]))) * scale)
        residuals.append((qS[k] - float(np.mean(qS[window][local]))) * scale)
        usedRows += 1
    if usedRows < _MIN_STATIONARY_SAMPLES:
        return None
    return 1.4826 * float(np.median(np.abs(residuals)))


@dataclass(frozen=True)
class _StationaryAnalysis:
    mask: np.ndarray
    sigmaHatUt: float | None  # None: too few usable stationary rows
    thresholdDeg: float
    degenerate: bool


def _analyseStationarity(
    tsArray: np.ndarray, p: np.ndarray, q: np.ndarray
) -> _StationaryAnalysis:
    """Rulings 28/29a: the stationary mask about the provisional centre,
    with its noise-scaled threshold (bootstrapped -- see
    ``_THRESHOLD_BOOTSTRAP_PASSES``) and the noise it measured.

    Degenerate locus (``_locusIsDegenerate``, the car never turned): every
    row is stationary -- the magnetometer's answer is unambiguous -- and the
    fit refuses downstream saying the capture never turned. (MEASURED in
    round 4: without this, an all-parked capture found 0 stationary rows and
    was refused for having nothing parked.)
    """
    centreP, centreQ = _provisionalCentre(p, q)
    if _locusIsDegenerate(tsArray, p, q, centreP, centreQ):
        allRows = np.ones(len(p), dtype=bool)
        return _StationaryAnalysis(
            allRows, _sigmaHatUt(tsArray, p, q, allRows), STATIONARY_HEADING_DELTA_DEG, True
        )

    radius = _provisionalRadius(p, q)
    thresholdDeg = STATIONARY_HEADING_DELTA_DEG
    mask = _stationaryMask(tsArray, p, q, centreP, centreQ, thresholdDeg)
    sigmaHat = _sigmaHatUt(tsArray, p, q, mask)
    for _ in range(_THRESHOLD_BOOTSTRAP_PASSES):
        if sigmaHat is None or radius <= 0.0:
            break
        nextDeg = max(
            STATIONARY_HEADING_DELTA_DEG,
            math.degrees(_THRESHOLD_NOISE_SIGMAS * sigmaHat / radius),
        )
        if abs(nextDeg - thresholdDeg) < 0.1:
            break
        thresholdDeg = nextDeg
        mask = _stationaryMask(tsArray, p, q, centreP, centreQ, thresholdDeg)
        sigmaHat = _sigmaHatUt(tsArray, p, q, mask)
    return _StationaryAnalysis(mask, sigmaHat, thresholdDeg, False)


def _stationaryMaskAboutProvisionalCentre(
    tsArray: np.ndarray, p: np.ndarray, q: np.ndarray
) -> np.ndarray:
    """The stationary mask alone -- see ``_analyseStationarity``."""
    return _analyseStationarity(tsArray, p, q).mask


def _estimateGyroBias(
    tsArray: np.ndarray, p: np.ndarray, q: np.ndarray, gyroMatrix: np.ndarray
) -> np.ndarray:
    """Ruling 25/28: per-axis gyro bias, the median RAW reading over rows
    judged stationary by the magnetometer about the provisional centre --
    never the whole capture (Ruling 24's approach; see module docstring for
    why that measurably fails on steady circling).

    Kept as its own function, with this signature, so it is a clean, direct
    patch target: the tests prove each acceptance case goes RED when this is
    swapped for round 3's origin-based version, or for zero.

    Raises:
        ValueError: too few stationary samples to trust the median.
    """
    analysis = _analyseStationarity(tsArray, p, q)
    stationaryCount = int(np.sum(analysis.mask))
    if stationaryCount < _MIN_STATIONARY_SAMPLES:
        raise ValueError(
            f"too few parked, non-turning samples to estimate the gyro bias: "
            f"{stationaryCount} rows held their magnetometer heading within "
            f"{analysis.thresholdDeg:.1f} deg for {STATIONARY_WINDOW_S:.0f} s, "
            f"need at least {_MIN_STATIONARY_SAMPLES}. Start and end the "
            "capture with roughly 30 seconds parked, engine running."
        )
    return np.median(gyroMatrix[analysis.mask], axis=0)


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
    earthHorizontalUt: float = DEFAULT_EARTH_HORIZONTAL_UT,
    maxRadiusSpreadPercent: float = MAX_RADIUS_SPREAD_PERCENT_DEFAULT,
    force: bool = False,
) -> MagCalibrationFit:
    """Fit the planar hard/soft-iron calibration from BODY-frame capture rows.

    Args:
        rows: ``(tsCaptureS, accelBody, magBody, gyroRaw)`` as returned by
            ``loadRows``. ``gyroRaw`` may be None (no gyro columns in the
            source CSV) -- see Ruling 23's moving/idle fallback. When present
            it is RAW (bias not yet removed); the stationary-window bias
            estimate (Ruling 25) is computed and subtracted here before
            gating.
        earthVerticalUt: Earth's expected vertical field component, BODY-UP
            sign convention (Ruling 22). Defaults to the DOCUMENTED Chicago
            WMM-2025 value; override for a different location.
        earthHorizontalUt: Earth's expected horizontal field MAGNITUDE
            (Ruling 26). Defaults to the DOCUMENTED Chicago WMM-2025 value;
            only used as ``horizontalGain``'s denominator -- never affects
            the emitted calibration, which a planar capture cannot correct
            for a horizontal/vertical gain mismatch.
        maxRadiusSpreadPercent: m7 quality floor -- see module docstring.
        force: m7 -- accept a fit whose radius spread exceeds
            ``maxRadiusSpreadPercent`` anyway (``qualityForced=True`` on the
            result) instead of refusing.

    Raises:
        ValueError: too few total or moving samples, too few stationary
            samples to estimate a gyro bias (Ruling 25), insufficient heading
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
    tsArray = np.array([row[0] for row in rows])

    gravity = _meanGravity(accelBody)
    forward, left, up = _levelBasis(gravity)

    p = np.array([m[0] * forward[0] + m[1] * forward[1] + m[2] * forward[2] for m in magBody])
    q = np.array([m[0] * left[0] + m[1] * left[1] + m[2] * left[2] for m in magBody])
    r = np.array([m[0] * up[0] + m[1] * up[1] + m[2] * up[2] for m in magBody])

    # Ruling 23/25: idle dwell must not enter the fit or the coverage count.
    # The gyro is RAW (no bias removed upstream -- edr_imu_sample carries the
    # sensor's own reading, and the A-34 faulted-offset defect puts a
    # constant ~0.5 rad/s on one axis, well above MOVING_MIN_GYRO_RAD_S). The
    # bias is estimated from samples judged STATIONARY by mag-heading
    # stability about a provisional centre (Rulings 25, 28), NOT a
    # whole-capture median (Ruling 24's approach, which fails on steady
    # circling -- see module docstring).
    # Ruling 29a: the magnetometer's own stationarity analysis, once -- its
    # sigmaHat sets the quality floor below, and its mask is the no-gyro
    # path's only way to tell a parked row from a moving one.
    stationarity = _analyseStationarity(tsArray, p, q)
    gyroBiasPerAxis: np.ndarray | None = None
    if all(g is not None for g in gyroRaw):
        gyroMatrix = np.array(gyroRaw)  # shape (N, 3)
        gyroBiasPerAxis = _estimateGyroBias(tsArray, p, q, gyroMatrix)
        gyroMagRadS = np.linalg.norm(gyroMatrix - gyroBiasPerAxis, axis=1)
        movingMask = gyroMagRadS > MOVING_MIN_GYRO_RAD_S
    else:
        # No gyro columns (Ruling 23's fallback, tightened by Ruling 29a): a
        # row the magnetometer judges stationary is parked, not moving.
        # Round 4 counted every row as moving here, so movingSamples
        # over-reported by the whole parked dwell.
        movingMask = ~stationarity.mask
    movingCount = int(np.sum(movingMask))
    if movingCount < _MIN_SAMPLES:
        raise ValueError(_tooFewMovingMessage(tsArray, p, q, movingCount, total, gyroBiasPerAxis))
    pM, qM, rM = p[movingMask], q[movingMask], r[movingMask]

    # Ruling 22: subtract Earth's own vertical field before what remains is
    # called hard iron -- see module docstring and DEFAULT_EARTH_VERTICAL_UT.
    hz = float(np.mean(rM)) - earthVerticalUt

    pMean, qMean = float(np.mean(pM)), float(np.mean(qM))
    coeffs = _fitConic(pM - pMean, qM - qMean)
    try:
        x0c, y0c, r1, r2, eigvecs = _ellipseParams(*coeffs)
    except ValueError as exc:
        # Item 5: say what went INTO the fit, so a bad moving/idle split (a
        # wrong gyro bias letting parked rows in) is visible, not hidden
        # behind "too noisy".
        biasNote = (
            ""
            if gyroBiasPerAxis is None
            else f", gyro bias subtracted ({', '.join(f'{v:+.3f}' for v in gyroBiasPerAxis)}) rad/s"
        )
        raise ValueError(f"{exc} [{movingCount} of {total} rows judged moving{biasNote}]") from exc
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

    # m7, made noise-aware by Ruling 29a: refuse only when the residual
    # exceeds BOTH what the percentage allows AND what the measured noise
    # explains (_QUALITY_NOISE_SIGMAS x sigmaHat) -- a fixed percentage of R
    # refused every honest weak circle, whose residual is noise, not misfit.
    sigmaForFloorUt = (
        stationarity.sigmaHatUt
        if stationarity.sigmaHatUt is not None
        else _SIGMA_HAT_FALLBACK_UT
    )
    qualityFloorUt = max(
        maxRadiusSpreadPercent / 100.0 * radiusTarget,
        _QUALITY_NOISE_SIGMAS * sigmaForFloorUt,
    )
    qualityForced = False
    if residualRmsUt > qualityFloorUt:
        sigmaNote = (
            f"measured noise sigma {stationarity.sigmaHatUt:.2f} uT"
            if stationarity.sigmaHatUt is not None
            else f"noise not measurable (too few parked rows), assumed {_SIGMA_HAT_FALLBACK_UT} uT"
        )
        if not force:
            raise ValueError(
                f"corrected radius RMS residual {residualRmsUt:.2f} uT "
                f"({radiusSpreadPercent:.2f}% of R) exceeds the quality floor "
                f"{qualityFloorUt:.2f} uT (the larger of {maxRadiusSpreadPercent}% of "
                f"R and {_QUALITY_NOISE_SIGMAS:g} x sigma; {sigmaNote}) -- the locus "
                "is not the ellipse this fit assumes (a non-elliptical field, or "
                "a capture that moved the sensor). Pass --force / force=True to "
                "accept it anyway."
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

    # Ruling 26: MEASURE, never correct -- a planar (level) capture cannot
    # observe a horizontal/vertical gain mismatch (see module docstring's
    # worked example), so this is reported for every fit and warned on, not
    # gated on.
    horizontalGain = radiusTarget / earthHorizontalUt if earthHorizontalUt > 0 else float("inf")
    horizontalGainWarning = None
    if not (HORIZONTAL_GAIN_WARN_LOW <= horizontalGain <= HORIZONTAL_GAIN_WARN_HIGH):
        horizontalGainWarning = (
            f"horizontal:vertical gain ratio is unobserved from a planar capture "
            f"(fitted horizontal gain {horizontalGain:.2f}, outside "
            f"{HORIZONTAL_GAIN_WARN_LOW}-{HORIZONTAL_GAIN_WARN_HIGH}) -- "
            "heading on grades (nonzero pitch/roll) may be biased; this fit "
            "cannot correct for it, only flag it."
        )

    # Ruling 28 item 4: the vertical companion. Same contract -- reported for
    # every fit, warned on, never gated on.
    meanVerticalUt = float(np.mean(rM))
    verticalFieldRatio = (
        meanVerticalUt / earthVerticalUt if earthVerticalUt != 0 else float("inf")
    )
    verticalFieldWarning = None
    if abs(meanVerticalUt - earthVerticalUt) > VERTICAL_FIELD_WARN_FRACTION * abs(earthVerticalUt):
        verticalFieldWarning = (
            f"mean vertical field {meanVerticalUt:+.1f} uT differs from the "
            f"expected Earth vertical {earthVerticalUt:+.1f} uT by "
            f"{meanVerticalUt - earthVerticalUt:+.1f} uT (more than "
            f"{VERTICAL_FIELD_WARN_FRACTION:.0%} of it) -- the car is altering "
            "the vertical field, or there is large z hard iron, or "
            "--earth-vertical-ut is wrong for where this was captured. "
            "Hard-iron z absorbs it; if the car's own iron is the cause, "
            "heading on grades may be biased."
        )

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
        horizontalGain=horizontalGain,
        horizontalGainWarning=horizontalGainWarning,
        verticalFieldRatio=verticalFieldRatio,
        verticalFieldWarning=verticalFieldWarning,
        sigmaHatUt=stationarity.sigmaHatUt,
        qualityFloorUt=qualityFloorUt,
        gyroBiasRadS=(
            None if gyroBiasPerAxis is None else tuple(float(v) for v in gyroBiasPerAxis)
        ),
    )


def _tooFewMovingMessage(
    tsArray: np.ndarray,
    p: np.ndarray,
    q: np.ndarray,
    movingCount: int,
    total: int,
    gyroBiasPerAxis: np.ndarray | None,
) -> str:
    """Ruling 28 item 5: name the REAL cause of a too-few-moving refusal.

    Two very different captures end here. Either the car genuinely did not
    turn, or the magnetometer shows it turning and the bias-corrected gyro
    does not -- a frozen/latched gyro (A-34), or a bias estimate that is
    wrong. The magnetometer decides which, and the message says so; round 3
    blamed the drive in both cases.
    """
    head = (
        f"need at least {_MIN_SAMPLES} moving samples (bias-corrected gyro "
        f"magnitude > {MOVING_MIN_GYRO_RAD_S} rad/s), got {movingCount} of {total}"
    )
    if gyroBiasPerAxis is None:
        return f"{head} -- the capture never turned enough to trace a heading-dependent ellipse."
    turningByMag = total - int(np.sum(_stationaryMaskAboutProvisionalCentre(tsArray, p, q)))
    bias = ", ".join(f"{v:+.3f}" for v in gyroBiasPerAxis)
    if turningByMag >= _MIN_SAMPLES:
        return (
            f"{head}, but the magnetometer shows {turningByMag} rows turning -- "
            f"the gyro disagrees with the magnetometer. The gyro is frozen or "
            f"faulted, or its bias estimate ({bias}) rad/s is wrong; this is a "
            "gyro problem, not a drive that failed to turn."
        )
    return (
        f"{head}, and the magnetometer agrees (only {turningByMag} rows turning) "
        "-- the capture never turned enough to trace a heading-dependent ellipse."
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
        "--earth-horizontal-ut",
        type=float,
        default=DEFAULT_EARTH_HORIZONTAL_UT,
        help="Earth's expected horizontal field magnitude (Ruling 26)",
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
            rows,
            earthVerticalUt=args.earth_vertical_ut,
            earthHorizontalUt=args.earth_horizontal_ut,
            force=args.force,
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
            "horizontalGain": _finiteOrNone(fit.horizontalGain),
            "horizontalGainWarning": fit.horizontalGainWarning,
            "verticalFieldRatio": _finiteOrNone(fit.verticalFieldRatio),
            "verticalFieldWarning": fit.verticalFieldWarning,
            "sigmaHatUt": None if fit.sigmaHatUt is None else round(fit.sigmaHatUt, 4),
            "qualityFloorUt": round(fit.qualityFloorUt, 4),
            "gyroBiasRadS": (
                None if fit.gyroBiasRadS is None else [round(v, 5) for v in fit.gyroBiasRadS]
            ),
            "describe": fit.describe(),
        },
    }
    print(json.dumps(result, indent=2))
    # Rulings 26/28: WARNING lines, not refusals -- printed separately
    # (stderr) so they are visible even when stdout is redirected to save
    # the JSON.
    for warning in (fit.horizontalGainWarning, fit.verticalFieldWarning):
        if warning is not None:
            print(f"WARNING: {warning}", file=sys.stderr)
    return 0


def _finiteOrNone(value: float) -> float | None:
    """Round for JSON; a non-finite ratio (zero denominator) becomes null,
    because ``json.dumps`` would otherwise emit the non-standard ``Infinity``."""
    return round(value, 3) if math.isfinite(value) else None


if __name__ == "__main__":
    sys.exit(main())
