"""ARCH-027: GPS truth for scoring IMU estimators.

🔴 WHY THIS REPLACED THE OLD METRIC. The first fusion bench scored "phantom
coupling" by regressing estimated pitch against the accelerometer's own forward
axis. On a tilted stationary sensor that axis is dominated by the GRAVITY
component -- which IS pitch. So the metric regressed pitch against pitch, and
returned slopes of tens of degrees per g with signs that flipped between
estimators. Numbers, not evidence.

Truth has to come from outside the system under test:

* **grade** -- from GPS elevation over a distance window, against which the
  estimator's published grade is compared;
* **heading** -- from GPS course over ground;
* **longitudinal acceleration** -- from d(OBD SPEED)/dt, which no estimator
  consumes, so it cannot contain the answer.

The GPX parsing, haversine, clock alignment and circular statistics follow the
2026-09-15 test-ride analysis (`evidence/2026-09-15-test-ride-gps-truth/`),
which produced the 4.1°/6.8° out-of-sample heading result. Reproduced here as a
tested module rather than a scratch script, because a second implementation of
the same maths is how two different answers to one question appear.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

EARTH_RADIUS_M = 6371000.0

# Approximate magnetic declination, Chicago 2026 (degrees, west negative).
# magnetic = true - declination.
DEFAULT_DECLINATION_DEG = -3.5

# Course over ground is meaningless at a standstill: GPS noise spins the bearing
# freely. 4 m/s (~14 km/h) is the floor the test-ride analysis used.
MIN_SPEED_FOR_COURSE_MS = 4.0

_TRKPT = re.compile(
    r'<trkpt lat="([-\d.]+)" lon="([-\d.]+)">\s*<ele>([-\d.]+)</ele>\s*<time>([^<]+)</time>'
)


def parseIsoUtc(text: str) -> float:
    """ISO-8601 UTC -> epoch seconds. Accepts fractional seconds and 'Z'."""
    cleaned = text.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned).replace(tzinfo=UTC).timestamp()


@dataclass(frozen=True)
class GpsTrack:
    """A parsed GPX track, with derived speed, course and cumulative distance."""

    time: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    elevation: np.ndarray
    courseTime: np.ndarray
    speedMs: np.ndarray
    courseDeg: np.ndarray
    cumulativeM: np.ndarray

    @property
    def samples(self) -> int:
        return len(self.time)


def distanceAndBearing(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Great-circle distance (m) and initial bearing (deg, 0=N) between points."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    deltaLon = np.radians(lon2 - lon1)
    x = np.sin(deltaLon) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(deltaLon)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(deltaLon / 2) ** 2
    distance = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))
    bearing = (np.degrees(np.arctan2(x, y)) + 360) % 360
    return distance, bearing


def loadGpx(path: str) -> GpsTrack:
    """Parse a GPX track and derive speed, course over ground and distance.

    Speed and course use a CENTRED difference (point n-1 to n+1) rather than
    consecutive points: at 1 Hz the consecutive-point bearing is dominated by
    position noise, which is what makes a stationary GPS appear to spin.
    """
    with open(path, encoding="utf-8") as handle:
        points = _TRKPT.findall(handle.read())
    if len(points) < 3:
        raise ValueError(f"GPX has too few track points to derive course: {len(points)}")

    time = np.array([parseIsoUtc(p[3]) for p in points])
    lat = np.array([float(p[0]) for p in points])
    lon = np.array([float(p[1]) for p in points])
    elevation = np.array([float(p[2]) for p in points])

    span, bearing = distanceAndBearing(lat[:-2], lon[:-2], lat[2:], lon[2:])
    interval = time[2:] - time[:-2]
    speed = np.divide(span, interval, out=np.zeros_like(span), where=interval > 0)

    stepDistance = distanceAndBearing(lat[:-1], lon[:-1], lat[1:], lon[1:])[0]
    cumulative = np.concatenate([[0.0], np.cumsum(stepDistance)])

    return GpsTrack(
        time=time,
        lat=lat,
        lon=lon,
        elevation=elevation,
        courseTime=time[1:-1],
        speedMs=speed,
        courseDeg=bearing,
        cumulativeM=cumulative,
    )


def findClockOffset(
    track: GpsTrack,
    obdTime: np.ndarray,
    obdSpeedKph: np.ndarray,
    searchS: float = 20.0,
    stepS: float = 0.25,
) -> float:
    """Seconds to ADD to OBD time to land on GPS time, by matching speed.

    Speed is the right alignment signal because both instruments measure it
    independently and it changes fast enough to localise a lag. The test ride
    resolved to +1.25 s this way.
    """
    lags = np.arange(-searchS, searchS + stepS, stepS)
    errors = []
    gpsSpeedKph = track.speedMs * 3.6
    for lag in lags:
        interpolated = np.interp(
            obdTime + lag, track.courseTime, gpsSpeedKph, left=np.nan, right=np.nan
        )
        mask = np.isfinite(interpolated)
        errors.append(
            float(np.mean(np.abs(interpolated[mask] - obdSpeedKph[mask])))
            if mask.sum()
            else np.inf
        )
    return float(lags[int(np.argmin(errors))])


def circularErrorDeg(estimate: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """Signed smallest-angle difference, in (-180, 180]."""
    return (estimate - truth + 180.0) % 360.0 - 180.0


def gradeWindows(
    track: GpsTrack,
    sampleTime: np.ndarray,
    estimatedGradePct: np.ndarray,
    clockOffsetS: float,
    windowS: float = 30.0,
    minDistanceM: float = 100.0,
) -> list[tuple[float, float]]:
    """Pairs of (GPS grade %, mean estimated grade %) over moving windows.

    Windows shorter than `minDistanceM` of travel are DISCARDED: grade is rise
    over run, and over a few metres the run is too small for the ratio to mean
    anything -- GPS elevation noise then dominates and manufactures hills.
    """
    pairs: list[tuple[float, float]] = []
    if len(sampleTime) == 0:
        return pairs

    start = sampleTime[0]
    end = sampleTime[-1] - windowS
    for windowStart in np.arange(start, end, windowS):
        gpsStart = windowStart + clockOffsetS
        gpsEnd = windowStart + windowS + clockOffsetS
        run = float(
            np.interp(gpsEnd, track.time, track.cumulativeM)
            - np.interp(gpsStart, track.time, track.cumulativeM)
        )
        if run < minDistanceM:
            continue
        rise = float(
            np.interp(gpsEnd, track.time, track.elevation)
            - np.interp(gpsStart, track.time, track.elevation)
        )
        inWindow = (sampleTime >= windowStart) & (sampleTime < windowStart + windowS)
        estimated = estimatedGradePct[inWindow]
        if not np.any(np.isfinite(estimated)):
            continue
        pairs.append((rise / run * 100.0, float(np.nanmean(estimated))))
    return pairs


def scoreGrade(pairs: list[tuple[float, float]]) -> dict[str, float]:
    """Median absolute error in grade POINTS, plus correlation and range."""
    if len(pairs) < 3:
        return {"windows": len(pairs), "medianAbsErrorPoints": float("nan")}
    truth = np.array([p[0] for p in pairs])
    estimate = np.array([p[1] for p in pairs])
    correlation = (
        float(np.corrcoef(truth, estimate)[0, 1]) if len(pairs) > 3 else float("nan")
    )
    return {
        "windows": len(pairs),
        "medianAbsErrorPoints": float(np.median(np.abs(estimate - truth))),
        "meanAbsEstimatedPct": float(np.mean(np.abs(estimate))),
        "gpsGradeMinPct": float(truth.min()),
        "gpsGradeMaxPct": float(truth.max()),
        "correlation": correlation,
    }


def scoreHeading(
    track: GpsTrack,
    sampleTime: np.ndarray,
    estimatedHeadingDeg: np.ndarray,
    clockOffsetS: float,
    declinationDeg: float = DEFAULT_DECLINATION_DEG,
) -> dict[str, float]:
    """Heading error against GPS course over ground, above a speed floor.

    Also reports TURN SLOPE: regress the estimate's change against truth's
    change over 5 s. +1 means the heading turns with the car, -1 mirrored, 0 not
    at all. A heading can have a respectable median error while being completely
    uncorrelated with rotation -- that is exactly how A-30 hid.
    """
    if len(sampleTime) == 0:
        return {"seconds": 0, "medianAbsErrorDeg": float("nan")}

    seconds = np.unique(np.floor(sampleTime))
    perSecond = []
    for second in seconds:
        values = estimatedHeadingDeg[np.floor(sampleTime) == second]
        values = values[np.isfinite(values)]
        if len(values) == 0:
            perSecond.append(np.nan)
            continue
        # Circular mean: averaging 359 and 1 arithmetically gives 180.
        perSecond.append(
            math.degrees(math.atan2(
                float(np.mean(np.sin(np.radians(values)))),
                float(np.mean(np.cos(np.radians(values)))),
            )) % 360.0
        )
    estimate = np.array(perSecond)

    index = np.clip(
        np.searchsorted(track.courseTime, seconds + clockOffsetS), 0, len(track.courseTime) - 1
    )
    truth = (track.courseDeg[index] - declinationDeg) % 360.0
    speed = track.speedMs[index]

    usable = (speed > MIN_SPEED_FOR_COURSE_MS) & np.isfinite(estimate)
    if usable.sum() < 5:
        return {"seconds": int(usable.sum()), "medianAbsErrorDeg": float("nan")}

    error = circularErrorDeg(estimate[usable], truth[usable])
    unwrappedEstimate = np.degrees(np.unwrap(np.radians(estimate[usable])))
    unwrappedTruth = np.degrees(np.unwrap(np.radians(truth[usable])))
    deltaEstimate = unwrappedEstimate[5:] - unwrappedEstimate[:-5]
    deltaTruth = unwrappedTruth[5:] - unwrappedTruth[:-5]
    turning = np.abs(deltaTruth) > 20.0
    slope = (
        float(np.polyfit(deltaTruth[turning], deltaEstimate[turning], 1)[0])
        if turning.sum() > 5
        else float("nan")
    )

    return {
        "seconds": int(usable.sum()),
        "medianAbsErrorDeg": float(np.median(np.abs(error))),
        "p90AbsErrorDeg": float(np.percentile(np.abs(error), 90)),
        "within30DegPct": float((np.abs(error) <= 30).mean() * 100.0),
        "turnSlope": slope,
    }


def longitudinalAccelFromSpeed(
    speedTime: np.ndarray, speedKph: np.ndarray, sampleTime: np.ndarray
) -> np.ndarray:
    """d(SPEED)/dt in g, interpolated onto the IMU timebase.

    🔴 Derived from OBD SPEED on purpose. No estimator consumes it, so unlike the
    accelerometer's own forward axis it cannot contain the quantity being scored.
    """
    if len(speedTime) < 3:
        return np.full(len(sampleTime), np.nan)
    speedMs = speedKph / 3.6
    accel = np.gradient(speedMs, speedTime)
    return np.interp(sampleTime, speedTime, accel, left=np.nan, right=np.nan) / 9.80665
