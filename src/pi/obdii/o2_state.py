################################################################################
# File Name: o2_state.py
# Purpose/Description: US-891-a (F-127) states/o2 -- the last windowSec of front
#                      (O2_B1S1) and rear (O2_B1S2) O2 samples at their own
#                      event times, each sensor's staleness by obd-live's
#                      contract, and the MEASURED sample period. Fed at the
#                      obd-live reading seam (ObdLiveTracker.observeReading);
#                      opens no connection, reads no database.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-891-a) | Initial -- O2History, pure builder, emitter.
# ================================================================================
################################################################################

"""Publish the recent O2 samples to ``states/o2`` (US-891-a, Atlas A1 RULED).

Three facts are load-bearing:

* **ts is the event time.** Every sample ``ts`` and each sensor's ``ts`` is the
  reading's own capture time as aware UTC (the obd-live format); only the
  top-level ``ts`` is the write time (the engine-history precedent).
* **value always means CURRENT**, exactly as states/obd-live: a sensor whose
  latest reading is older than ``pi.display.stale.obdLiveSec`` publishes
  ``value: null``, ``stale: true``, reason ``stale`` and its old reading under
  ``last``. The samples are history and stay in the list while stale.
* **samplePeriodSec is measured, never configured**: the median of consecutive
  front-sample deltas inside the window, so one dropped poll does not move it.

The writer runs on EVERY card tick, never only on change, so ``stale`` flips
while the feed is quiet.
"""

from __future__ import annotations

import logging
import math
import os
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

__all__ = [
    "MIDLINE_V",
    "O2_STATE_FILENAME",
    "O2History",
    "O2Sample",
    "O2Series",
    "O2Settings",
    "O2Snapshot",
    "PID_O2_FRONT",
    "PID_O2_REAR",
    "buildO2State",
    "makeO2Emitter",
]

logger = logging.getLogger("pi.obdii.o2_state")

# The state name a page fetches: GET /o2.
O2_STATE_FILENAME = "o2"

# The two sensors of the one bank (spec v030-o2-page-design s5).
PID_O2_FRONT = "O2_B1S1"
PID_O2_REAR = "O2_B1S2"

# The narrowband mid-line, volts: spec s4.2 (Spool 2026-10-13). ONE home (Atlas
# A1 (a)3): the page draws its dashed mid-line from the published midlineV.
MIDLINE_V = 0.45

# Rear and catalyst are held (CIO 2026-10-13, spec s4.3): always this token.
VERDICT_NOT_RATED = "not_rated"

# Per-sensor reason when value is null (Atlas A1 (a)1); null when current.
REASON_NOT_READ = "not_read"
REASON_STALE = "stale"

# Matches the other card emitters' `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# samplePeriodSec is rounded to this many decimals (0.1 s, Atlas A1 (c)).
_SAMPLE_PERIOD_DECIMALS = 1


@dataclass(frozen=True)
class O2Settings:
    """``pi.display.o2.*``: the sample window, seconds."""

    windowSec: float

    @classmethod
    def fromConfig(cls, config: dict[str, Any]) -> O2Settings:
        """Read the settings, falling back to the validator default.

        Args:
            config: Configuration mapping (validated or raw).

        Returns:
            The resolved settings.
        """
        from common.config.validator import DEFAULTS

        windowSec = config.get("pi", {}).get("display", {}).get("o2", {}).get("windowSec")
        return cls(
            windowSec=float(
                DEFAULTS["pi.display.o2.windowSec"] if windowSec is None else windowSec
            )
        )


@dataclass(frozen=True)
class O2Sample:
    """One O2 reading: volts at its aware-UTC event time."""

    value: float
    atUtc: datetime


@dataclass(frozen=True)
class O2Series:
    """One sensor: its latest reading (None when never read) and its samples."""

    latest: O2Sample | None
    samples: tuple[O2Sample, ...]


@dataclass(frozen=True)
class O2Snapshot:
    """Both sensors and the window, copied out of an :class:`O2History`."""

    front: O2Series
    rear: O2Series
    windowSec: float


def _volts(value: Any) -> float | None:
    """A reading's value as volts, or None when it is not a number (bool is not)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class O2History:
    """The newest windowSec of front and rear O2 samples.

    Not thread-safe: the caller (``ObdLiveTracker``) holds its own lock.
    """

    def __init__(self, settings: O2Settings) -> None:
        """
        Args:
            settings: The resolved ``pi.display.o2.*`` values.
        """
        self._windowSec = settings.windowSec
        self._samples: dict[str, deque[O2Sample]] = {
            PID_O2_FRONT: deque(),
            PID_O2_REAR: deque(),
        }

    def observe(self, pid: str, value: Any, ts: datetime) -> None:
        """Fold one reading.

        Args:
            pid: The reading's PID; anything but the two sensors is ignored.
            value: The reading's value; a non-number is dropped, never stored
                as 0, and changes neither the samples nor the latest reading.
            ts: The reading's aware UTC event time.
        """
        samples = self._samples.get(pid)
        if samples is None:
            return
        volts = _volts(value)
        if volts is None:
            return
        samples.append(O2Sample(volts, ts))
        # Bound the memory; the build trims again against the write time.
        oldest = ts - timedelta(seconds=self._windowSec)
        while samples[0].atUtc < oldest:
            samples.popleft()

    def snapshot(self) -> O2Snapshot:
        """An immutable copy of both sensors' samples."""
        return O2Snapshot(
            front=self._series(PID_O2_FRONT),
            rear=self._series(PID_O2_REAR),
            windowSec=self._windowSec,
        )

    def _series(self, pid: str) -> O2Series:
        samples = tuple(self._samples[pid])
        return O2Series(latest=samples[-1] if samples else None, samples=samples)


def _formatTs(atUtc: datetime) -> str:
    """An event time in the obd-live ``ts`` format (canonical UTC, seconds)."""
    from common.time.helper import toCanonicalIso

    return toCanonicalIso(atUtc)


def _sensorState(
    series: O2Series, inWindow: list[O2Sample], nowUtc: datetime, staleSec: float
) -> dict[str, Any]:
    """One sensor's ``{value, ts, stale, reason, last, samples}``."""
    samples = [{"v": s.value, "ts": _formatTs(s.atUtc)} for s in inWindow]
    latest = series.latest
    if latest is None:
        return {
            "value": None,
            "ts": None,
            "stale": False,
            "reason": REASON_NOT_READ,
            "last": None,
            "samples": samples,
        }
    # obd-live's _isStale: older than staleSec at this emit.
    if (nowUtc - latest.atUtc).total_seconds() > staleSec:
        return {
            "value": None,
            "ts": _formatTs(latest.atUtc),
            "stale": True,
            "reason": REASON_STALE,
            "last": {"value": latest.value},
            "samples": samples,
        }
    return {
        "value": latest.value,
        "ts": _formatTs(latest.atUtc),
        "stale": False,
        "reason": None,
        "last": None,
        "samples": samples,
    }


def _samplePeriodSec(front: list[O2Sample]) -> float | None:
    """Median of consecutive front deltas, to 0.1 s; None under 2 samples."""
    if len(front) < 2:
        return None
    deltas = [
        (later.atUtc - earlier.atUtc).total_seconds()
        for earlier, later in zip(front, front[1:], strict=False)
    ]
    return round(statistics.median(deltas), _SAMPLE_PERIOD_DECIMALS)


def buildO2State(snapshot: O2Snapshot, *, nowUtc: datetime, staleSec: float) -> dict[str, Any]:
    """Build the states/o2 payload.

    Args:
        snapshot: :meth:`O2History.snapshot` output.
        nowUtc: Aware UTC instant of this write; the window and staleness are
            judged against it.
        staleSec: ``pi.display.stale.obdLiveSec`` (obd-live's one stale fact).

    Returns:
        ``{front: {value, ts, stale, reason, last, samples: [{v, ts}]}, rear:
        {...}, samplePeriodSec, windowSec, midlineV, rearVerdict,
        catalystVerdict, ts}``. ``last`` is ``{value}`` while stale, else None.
    """
    oldest = nowUtc - timedelta(seconds=snapshot.windowSec)
    front = [s for s in snapshot.front.samples if s.atUtc >= oldest]
    rear = [s for s in snapshot.rear.samples if s.atUtc >= oldest]
    return {
        "front": _sensorState(snapshot.front, front, nowUtc, staleSec),
        "rear": _sensorState(snapshot.rear, rear, nowUtc, staleSec),
        "samplePeriodSec": _samplePeriodSec(front),
        "windowSec": snapshot.windowSec,
        "midlineV": MIDLINE_V,
        "rearVerdict": VERDICT_NOT_RATED,
        "catalystVerdict": VERDICT_NOT_RATED,
        "ts": nowUtc.strftime(_ISO_FMT),
    }


def makeO2Emitter(statesDir: str) -> Callable[..., None]:
    """Build the states/o2 emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).

    Returns:
        ``emit(snapshot, *, nowUtc, staleSec)`` writing the payload atomically.
        Best-effort by contract: a write failure is logged, never raised.
    """
    from pi.splash import boot_state_emitter

    target = os.path.join(statesDir, O2_STATE_FILENAME)

    def emit(snapshot: O2Snapshot, *, nowUtc: datetime, staleSec: float) -> None:
        try:
            payload = buildO2State(snapshot, nowUtc=nowUtc, staleSec=staleSec)
            boot_state_emitter.ensureStatesDir(statesDir)
            boot_state_emitter.writeStateAtomic(target, payload)
        except Exception as e:  # noqa: BLE001 -- never crash the run loop
            logger.error("states/o2 write failed (%s) -- ignored", e)

    return emit
