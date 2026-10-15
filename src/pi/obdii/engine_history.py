################################################################################
# File Name: engine_history.py
# Purpose/Description: US-889-a (F-127) states/engine-history -- this drive's
#                      COOLANT_TEMP, INTAKE_TEMP and BATTERY_V as worst-band
#                      buckets on the epoch grid, fed at the obd-live reading
#                      seam with the band producer's verdict at each reading
#                      (Atlas S104 ruling 1, G2). Opens no connection, reads no
#                      database, judges nothing.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-889-a) | Initial -- EngineHistory, pure builder, emitter.
# ================================================================================
################################################################################

"""Publish this drive's engine history to ``states/engine-history`` (US-889-a).

The bucket pattern is ``GradeHistory``'s (imu_state_bridge.py): buckets on the
epoch grid ``floor(ts / intervalSec)``, a point's ``ts`` is its bucket's END,
and a bucket closes on the next fresh sample past it. Per bucket:

* ``value`` is the LAST fresh sample -- the line steps, never averages.
* ``band`` is the WORST band held (red > amber > green > null), copied from the
  band producer at each reading. Bucketing never hides a fired span, and the
  history never re-judges a number (dwell stays the producer's alone).
* A bucket with no fresh sample is omitted: a gap is a gap, never a null point.

The window is THIS DRIVE: :meth:`EngineHistory.reset` at drive start clears
every series. ``partial`` says the series does not cover the whole drive -- an
orchestrator restart mid-drive (no drive start seen), or buckets trimmed past
``maxPoints`` -- and ``sinceTs`` always names where coverage begins.
"""

from __future__ import annotations

import logging
import math
import os
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "ENGINE_HISTORY_PIDS",
    "ENGINE_HISTORY_STATE_FILENAME",
    "EngineHistory",
    "EngineHistorySettings",
    "buildEngineHistoryState",
    "makeEngineHistoryEmitter",
]

logger = logging.getLogger("pi.obdii.engine_history")

# The state name a page fetches: GET /engine-history.
ENGINE_HISTORY_STATE_FILENAME = "engine-history"

# The three series the Engine page draws (Atlas S104 ruling 1).
ENGINE_HISTORY_PIDS = ("COOLANT_TEMP", "INTAKE_TEMP", "BATTERY_V")

# Worst-band order: a bucket keeps the highest rank it held.
_BAND_RANK = {None: 0, "green": 1, "amber": 2, "red": 3}

# Matches the other card emitters' `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class EngineHistorySettings:
    """``pi.display.engineHistory.*``: bucket width and the points kept per PID."""

    intervalSec: float
    maxPoints: int

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> EngineHistorySettings:
        """Read the settings, falling back to the validator defaults.

        Args:
            config: Configuration mapping (validated or raw).

        Returns:
            The resolved settings.
        """
        from common.config.validator import DEFAULTS

        node = config.get("pi", {}).get("display", {}).get("engineHistory", {})
        interval = node.get("intervalSec")
        maxPoints = node.get("maxPoints")
        return cls(
            intervalSec=float(
                DEFAULTS["pi.display.engineHistory.intervalSec"]
                if interval is None else interval
            ),
            maxPoints=int(
                DEFAULTS["pi.display.engineHistory.maxPoints"]
                if maxPoints is None else maxPoints
            ),
        )


def _formatInstant(epochS: float) -> str:
    """An epoch instant as ISO UTC: whole seconds canonical, else to the ms."""
    instant = datetime.fromtimestamp(epochS, UTC)
    if float(epochS).is_integer():
        return instant.strftime(_ISO_FMT)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _freshValue(value: Any) -> float | None:
    """A reading's value as a float, or None when it is not a fresh sample."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class _Bucket:
    """One PID's bucket: its grid index, last fresh value and worst band."""

    def __init__(self, idx: int, value: float, band: str | None) -> None:
        self.idx = idx
        self.value = value
        self.band = band

    def fold(self, value: float, band: str | None) -> None:
        self.value = value
        if _BAND_RANK.get(band, 0) > _BAND_RANK.get(self.band, 0):
            self.band = band


class EngineHistory:
    """This drive's worst-band buckets for the three engine-history PIDs.

    Not thread-safe: the caller (``ObdLiveTracker``) holds its own lock. A new
    instance -- an orchestrator restart -- starts empty and ``partial``, because
    it has not seen this drive's start.
    """

    def __init__(self, settings: EngineHistorySettings) -> None:
        """
        Args:
            settings: The resolved ``pi.display.engineHistory.*`` values.
        """
        self._intervalS = settings.intervalSec
        self._maxPoints = settings.maxPoints
        self._series: dict[str, deque[_Bucket]] = {
            pid: deque() for pid in ENGINE_HISTORY_PIDS
        }
        self._open: dict[str, _Bucket] = {}
        self._unit: dict[str, str] = {}
        self._driveId: int | None = None
        self._sinceEpochS: float | None = None
        self._partial = True
        # True until the published file matches these series. Starts True so
        # the first tick replaces a previous process's file with the honest
        # empty-after-restart state.
        self._changed = True

    def reset(self, driveId: int | None, startUtc: datetime | None) -> None:
        """Open a new drive's window: every series cleared, ``partial`` false.

        Args:
            driveId: The new drive's id.
            startUtc: The drive start's aware UTC event time; when unknown, the
                window begins at the first folded bucket instead.
        """
        for points in self._series.values():
            points.clear()
        self._open.clear()
        self._driveId = driveId
        self._sinceEpochS = None if startUtc is None else startUtc.timestamp()
        self._partial = False
        self._changed = True

    def observe(
        self,
        pid: str,
        value: Any,
        ts: datetime,
        band: str | None,
        unit: str | None = None,
    ) -> None:
        """Fold one reading.

        Args:
            pid: The reading's PID; anything outside :data:`ENGINE_HISTORY_PIDS`
                is ignored.
            value: The reading's value. A null or non-finite value is not a
                fresh sample: it opens no bucket and changes none.
            ts: The reading's aware UTC event time.
            band: The band producer's band AT this reading (``green``,
                ``amber``, ``red`` or None), copied as given.
            unit: The reading's canonical unit (``pi.obdii.units``).
        """
        if pid not in self._series:
            return
        fresh = _freshValue(value)
        if fresh is None:
            return
        if unit is not None:
            self._unit[pid] = unit
        idx = math.floor(ts.timestamp() / self._intervalS)
        if self._sinceEpochS is None:
            # No drive start seen (restart mid-drive): coverage begins here.
            self._sinceEpochS = idx * self._intervalS
        bucket = self._open.get(pid)
        if bucket is None:
            self._open[pid] = _Bucket(idx, fresh, band)
            return
        if idx == bucket.idx:
            bucket.fold(fresh, band)
            return
        if idx < bucket.idx:
            self._clockSteppedBack(pid, ts, bucket.idx)
            self._sinceEpochS = idx * self._intervalS
        else:
            self._close(pid, bucket)
        self._open[pid] = _Bucket(idx, fresh, band)

    def _clockSteppedBack(self, pid: str, ts: datetime, openIdx: int) -> None:
        """A sample before its PID's open bucket: the old timeline is dropped.

        Points from two timelines would interleave, so every series restarts
        here, and the window says it is partial.
        """
        logger.warning(
            "engine-history: %s reading at %s is before its open bucket "
            "(starts %s) -- clock stepped back; history reset",
            pid,
            ts.isoformat(),
            _formatInstant(openIdx * self._intervalS),
        )
        for points in self._series.values():
            points.clear()
        self._open.clear()
        self._partial = True
        self._changed = True

    def _close(self, pid: str, bucket: _Bucket) -> None:
        points = self._series[pid]
        points.append(bucket)
        if len(points) > self._maxPoints:
            points.popleft()
            # The label must not claim coverage the series no longer holds.
            oldestStart = points[0].idx * self._intervalS
            if self._sinceEpochS is None or oldestStart > self._sinceEpochS:
                self._sinceEpochS = oldestStart
            self._partial = True
        self._changed = True

    def snapshotIfChanged(self) -> dict[str, Any] | None:
        """The snapshot when it changed since the last call, else None.

        Changes are a bucket closing, a reset, or the very first call.
        """
        if not self._changed:
            return None
        self._changed = False
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        """The payload's history part (fresh dicts every call)."""
        return {
            "driveId": self._driveId,
            "sinceTs": (
                None if self._sinceEpochS is None else _formatInstant(self._sinceEpochS)
            ),
            "partial": self._partial,
            "intervalSec": self._intervalS,
            "series": {
                pid: [
                    {
                        "ts": _formatInstant((b.idx + 1) * self._intervalS),
                        "value": b.value,
                        "band": b.band,
                    }
                    for b in points
                ]
                for pid, points in self._series.items()
            },
            "unit": dict(self._unit),
        }


def buildEngineHistoryState(history: dict[str, Any], *, nowUtc: datetime) -> dict[str, Any]:
    """Build the states/engine-history payload.

    Args:
        history: :meth:`EngineHistory.snapshot` output.
        nowUtc: Aware UTC instant of this write.

    Returns:
        ``{ts, driveId, sinceTs, partial, intervalSec, series: {pid: [{ts,
        value, band}]}, unit: {pid: unit}}``.
    """
    return {
        "ts": nowUtc.strftime(_ISO_FMT),
        "driveId": history["driveId"],
        "sinceTs": history["sinceTs"],
        "partial": history["partial"],
        "intervalSec": history["intervalSec"],
        "series": {pid: [dict(p) for p in pts] for pid, pts in history["series"].items()},
        "unit": dict(history["unit"]),
    }


def makeEngineHistoryEmitter(statesDir: str) -> Callable[..., None]:
    """Build the states/engine-history emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).

    Returns:
        ``emit(history, *, nowUtc)`` writing the payload atomically.
        Best-effort by contract: write failures are logged, never raised.
    """
    from pi.splash import boot_state_emitter

    target = os.path.join(statesDir, ENGINE_HISTORY_STATE_FILENAME)

    def emit(history: dict[str, Any], *, nowUtc: datetime) -> None:
        try:
            boot_state_emitter.ensureStatesDir(statesDir)
            boot_state_emitter.writeStateAtomic(
                target, buildEngineHistoryState(history, nowUtc=nowUtc)
            )
        except Exception as e:  # noqa: BLE001 -- never crash the run loop
            logger.error("states/engine-history write failed (%s) -- ignored", e)

    return emit
