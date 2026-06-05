################################################################################
# File Name: fit_reader.py
# Purpose/Description: Read a Strava/Garmin FIT file into alignment-ready GPS
#                      "source of truth" samples for SPEED-PID calibration. FIT
#                      record messages are heterogeneous -- the Strava dialect
#                      interleaves GPS-position records (lat/lon + ground speed +
#                      gps accuracy) with cumulative-distance records -- so the
#                      reader preserves every record with whatever fields it
#                      carries, converts int32 semicircles to degrees, stamps
#                      timestamps as UTC-aware, and exposes convenience accessors
#                      (gpsPoints, totalDistanceM, durationS) the OBD2 aligner
#                      consumes. Speed is m/s, distance metres (FIT native).
# Author: Atlas (Architect)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Read a Strava/Garmin FIT track into UTC-aware GPS calibration samples.

The GPS track is the calibration "source of truth" (external to the ECU's wrong
VSS constants).  This module only *extracts*; deriving the correction factor
(distance-ratio + speed-ratio estimators) is the aligner's job, so the reader
deliberately surfaces both the embedded ``speed`` and the raw ``lat``/``lon`` --
the aligner can trust the embedded speed or re-derive ground speed from the
positions it controls.

FIT specifics handled here:

* **Semicircles -> degrees.**  FIT stores ``position_lat``/``position_long`` as
  int32 semicircles; degrees = ``value * 180 / 2**31``.
* **Naive-UTC -> aware-UTC.**  The device writes naive UTC timestamps; we attach
  :data:`datetime.timezone.utc` so downstream clock-skew alignment is honest.
* **Heterogeneous records.**  Not every record carries every field; missing
  values are kept as ``None`` rather than dropped or defaulted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from fitparse import FitFile

# FIT encodes lat/long as int32 semicircles spanning +/- 2**31 == +/- 180 deg.
SEMICIRCLES_TO_DEGREES = 180.0 / 2**31


@dataclass(frozen=True)
class FitPoint:
    """One FIT ``record`` sample, with whatever fields it carried.

    Attributes:
        timestamp: UTC-aware sample time.
        latDeg: Latitude in degrees (None on distance-only records).
        lonDeg: Longitude in degrees (None on distance-only records).
        speedMps: Ground speed in metres/second (None when absent).
        distanceM: Cumulative distance in metres (None when absent).
        gpsAccuracyM: Reported GPS accuracy in metres (None when absent).
    """

    timestamp: datetime | None
    latDeg: float | None
    lonDeg: float | None
    speedMps: float | None
    distanceM: float | None
    gpsAccuracyM: float | None


@dataclass(frozen=True)
class FitTrack:
    """A parsed FIT track: every record plus calibration-ready accessors.

    Attributes:
        points: All records in non-decreasing timestamp order.
        sourcePath: The file the track was read from.
    """

    points: tuple[FitPoint, ...]
    sourcePath: str

    @property
    def gpsPoints(self) -> list[FitPoint]:
        """Records carrying a GPS fix (both lat and lon present)."""
        return [p for p in self.points if p.latDeg is not None and p.lonDeg is not None]

    @property
    def startTime(self) -> datetime | None:
        """First sample timestamp (None for an empty track)."""
        return self.points[0].timestamp if self.points else None

    @property
    def endTime(self) -> datetime | None:
        """Last sample timestamp (None for an empty track)."""
        return self.points[-1].timestamp if self.points else None

    @property
    def durationS(self) -> float:
        """Track span in seconds (0.0 when fewer than two timestamps)."""
        start, end = self.startTime, self.endTime
        if start is None or end is None:
            return 0.0
        return (end - start).total_seconds()

    @property
    def totalDistanceM(self) -> float:
        """Distance travelled: last minus first cumulative-distance reading.

        Returns 0.0 when no record carried a distance.
        """
        distances = [p.distanceM for p in self.points if p.distanceM is not None]
        if not distances:
            return 0.0
        return distances[-1] - distances[0]


def _toDegrees(semicircles: int | None) -> float | None:
    """Convert an int32 semicircle coordinate to degrees (None passes through)."""
    if semicircles is None:
        return None
    return semicircles * SEMICIRCLES_TO_DEGREES


def _toUtc(stamp: datetime | None) -> datetime | None:
    """Stamp a naive FIT timestamp as UTC-aware (already-aware passes through)."""
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC)


def readFit(path: str | os.PathLike[str]) -> FitTrack:
    """Read a FIT file into a :class:`FitTrack`.

    Args:
        path: Path to a ``.fit`` file (Strava/Garmin activity export).

    Returns:
        A :class:`FitTrack` with every ``record`` message in timestamp order.
    """
    fit = FitFile(os.fspath(path))
    points: list[FitPoint] = []
    for message in fit.get_messages("record"):
        fields = {field.name: field.value for field in message}
        points.append(
            FitPoint(
                timestamp=_toUtc(fields.get("timestamp")),
                latDeg=_toDegrees(fields.get("position_lat")),
                lonDeg=_toDegrees(fields.get("position_long")),
                speedMps=fields.get("speed"),
                distanceM=fields.get("distance"),
                gpsAccuracyM=fields.get("gps_accuracy"),
            )
        )
    points.sort(key=lambda p: (p.timestamp is None, p.timestamp))
    return FitTrack(points=tuple(points), sourcePath=os.fspath(path))
