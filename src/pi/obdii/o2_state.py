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
# 2026-10-26    | Rex (US-891-b) | frontVerdict/frontReason by Spool's
#                                distribution rule over per-sample-gated
#                                front samples (status 2, coolant >= 85 C).
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
* **The front verdict is the provider's** (US-891-b, spec s4.2): a front sample
  counts only when the FUEL_SYSTEM_STATUS and COOLANT_TEMP readings of its own
  poll cycle say code 2 and >= 85 C; with too few such samples the page gets
  the reason instead (``open_loop``, ``warming_up``, ...), never a guess.

The writer runs on EVERY card tick, never only on change, so ``stale`` flips
while the feed is quiet.
"""

from __future__ import annotations

import bisect
import logging
import math
import os
import statistics
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Spool S3 RULED 2026-10-26: ONLY code 2 counts -- the EXISTING code-2-only
# constant, imported, never a second literal (fuel_status's {2, 5} is another rule).
from pi.splash.ltft_trend_emitter import FUEL_SYSTEM_CLOSED_LOOP

__all__ = [
    "GateReading",
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
    "frontVerdict",
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

# ---------------------------------------------------------------------------
# US-891-b: the front verdict (spec v030-o2-page-design s4.2, Spool 2026-10-13).
# ---------------------------------------------------------------------------

# The gate inputs: FUEL_SYSTEM_STATUS carries its NUMERIC enum code (decoders
# _FUEL_STATUS_ENUM), COOLANT_TEMP degrees C.
PID_FUEL_SYSTEM_STATUS = "FUEL_SYSTEM_STATUS"
PID_COOLANT_TEMP = "COOLANT_TEMP"

# A sample counts only with coolant at or above this, degrees C (spec s4.2).
GATE_COOLANT_MIN_C = 85.0

# A gate reading pairs with a sample (or with the other gate reading) only from
# the same poll cycle: within half a ~2.2 s cycle (Spool 2026-10-26, S117 S2).
# Under pi.display.stale.obdLiveSec (5 s), so a paired reading is never stale.
GATE_PAIR_MAX_SEC = 1.1

# Fewer gated front samples in the window than this: not_enough_data (spec s4.2,
# ~2.2 min of closed loop at the measured ~2.2 s period).
VERDICT_MIN_GATED_SAMPLES = 60

# The distribution rule, fractions of the gated samples (spec s4.2, Spool
# 2026-10-13). SWITCHING: both bands strict, each side at least the fraction.
# STUCK: at least the fraction strictly on one side of MIDLINE_V. The STUCK
# thresholds are convention and have never been exercised on this car.
SWITCH_LOW_V = 0.30
SWITCH_HIGH_V = 0.60
SWITCH_MIN_FRACTION = 0.20
STUCK_MIN_FRACTION = 0.90

# FUEL_SYSTEM_STATUS codes that read open_loop when a verdict is withheld
# (Spool S1 + S3 RULED 2026-10-26). 5 (CL-fault) is closed loop and is NOT here;
# its samples simply do not count (only FUEL_SYSTEM_CLOSED_LOOP does).
OPEN_LOOP_STATUS_CODES = frozenset({1, 3, 4})

# frontVerdict tokens (snake_case; the page maps token -> words).
VERDICT_SWITCHING = "switching"
VERDICT_STUCK_LEAN = "stuck_lean"
VERDICT_STUCK_RICH = "stuck_rich"
VERDICT_UNCLEAR = "unclear"
VERDICT_NOT_ENOUGH_DATA = "not_enough_data"
VERDICT_OPEN_LOOP = "open_loop"
VERDICT_WARMING_UP = "warming_up"
VERDICT_NO_DATA = "no_data"

# The verdicts that rate the sensor; every other token is a withheld verdict
# and is published as frontReason too.
_LIVE_VERDICTS = frozenset({VERDICT_SWITCHING, VERDICT_STUCK_LEAN, VERDICT_STUCK_RICH})

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
            windowSec=float(DEFAULTS["pi.display.o2.windowSec"] if windowSec is None else windowSec)
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
class GateReading:
    """One verdict-gate reading (FUEL_SYSTEM_STATUS code or COOLANT_TEMP C)."""

    value: float
    atUtc: datetime


@dataclass(frozen=True)
class O2Snapshot:
    """Both sensors, the gate readings and the window, copied out of an :class:`O2History`."""

    front: O2Series
    rear: O2Series
    windowSec: float
    fuelStatus: tuple[GateReading, ...] = ()
    coolant: tuple[GateReading, ...] = ()


def _number(value: Any) -> float | None:
    """A reading's value as a finite float, or None when it is not a number (bool is not)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _bounded(readings: deque[Any], newest: datetime, keepSec: float) -> None:
    """Drop readings older than ``keepSec`` before ``newest`` (the newest stays)."""
    oldest = newest - timedelta(seconds=keepSec)
    while readings[0].atUtc < oldest:
        readings.popleft()


class O2History:
    """The newest windowSec of front and rear O2 samples and of the gate readings.

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
        self._gates: dict[str, deque[GateReading]] = {
            PID_FUEL_SYSTEM_STATUS: deque(),
            PID_COOLANT_TEMP: deque(),
        }

    def observe(self, pid: str, value: Any, ts: datetime) -> None:
        """Fold one reading.

        Args:
            pid: The reading's PID; anything but the two sensors and the two
                verdict-gate PIDs is ignored.
            value: The reading's value; a non-number is dropped, never stored
                as 0, and changes neither the samples nor the latest reading.
            ts: The reading's aware UTC event time.
        """
        number = _number(value)
        if number is None:
            return
        samples = self._samples.get(pid)
        if samples is not None:
            samples.append(O2Sample(number, ts))
            # Bound the memory; the build trims again against the write time.
            _bounded(samples, ts, self._windowSec)
            return
        gate = self._gates.get(pid)
        if gate is not None:
            gate.append(GateReading(number, ts))
            # A sample on the window edge pairs with a gate read up to one
            # pairing span before it.
            _bounded(gate, ts, self._windowSec + GATE_PAIR_MAX_SEC)

    def snapshot(self) -> O2Snapshot:
        """An immutable copy of both sensors' samples and the gate readings."""
        return O2Snapshot(
            front=self._series(PID_O2_FRONT),
            rear=self._series(PID_O2_REAR),
            windowSec=self._windowSec,
            fuelStatus=tuple(self._gates[PID_FUEL_SYSTEM_STATUS]),
            coolant=tuple(self._gates[PID_COOLANT_TEMP]),
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


def _pairedAtOrBefore(
    readings: Sequence[GateReading], times: Sequence[datetime], atUtc: datetime
) -> GateReading | None:
    """The latest reading at or before ``atUtc``, if it is from the same poll cycle."""
    index = bisect.bisect_right(times, atUtc)
    if index == 0:
        return None
    reading = readings[index - 1]
    return reading if (atUtc - reading.atUtc).total_seconds() <= GATE_PAIR_MAX_SEC else None


def _statusCode(value: float) -> int | None:
    """A FUEL_SYSTEM_STATUS value as its integral code, None when it is not one."""
    return int(value) if value.is_integer() else None


def _gatedVolts(
    front: list[O2Sample], fuelStatus: Sequence[GateReading], coolant: Sequence[GateReading]
) -> list[float]:
    """The front volts whose paired status is closed loop and paired coolant warm."""
    statusTimes = [r.atUtc for r in fuelStatus]
    coolantTimes = [r.atUtc for r in coolant]
    gated: list[float] = []
    for sample in front:
        status = _pairedAtOrBefore(fuelStatus, statusTimes, sample.atUtc)
        temp = _pairedAtOrBefore(coolant, coolantTimes, sample.atUtc)
        if (
            status is not None
            and temp is not None
            and status.value == FUEL_SYSTEM_CLOSED_LOOP
            and temp.value >= GATE_COOLANT_MIN_C
        ):
            gated.append(sample.value)
    return gated


def _withheldReason(
    fuelStatus: Sequence[GateReading],
    coolant: Sequence[GateReading],
    nowUtc: datetime,
    staleSec: float,
) -> str:
    """Why there is no verdict, by the latest status and the coolant of its cycle.

    A status older than ``staleSec`` at this emit is absent, as obd-live
    publishes it (value always means CURRENT).
    """
    if not fuelStatus:
        return VERDICT_NO_DATA
    status = fuelStatus[-1]
    if (nowUtc - status.atUtc).total_seconds() > staleSec:
        return VERDICT_NO_DATA
    code = _statusCode(status.value)
    if code is None:
        return VERDICT_NO_DATA
    if code in OPEN_LOOP_STATUS_CODES:
        return VERDICT_OPEN_LOOP
    if code == FUEL_SYSTEM_CLOSED_LOOP:
        # Status and coolant are polled back to back: pair them either way round.
        for temp in reversed(coolant):
            if abs((temp.atUtc - status.atUtc).total_seconds()) <= GATE_PAIR_MAX_SEC:
                if temp.value < GATE_COOLANT_MIN_C:
                    return VERDICT_WARMING_UP
                break
    # Code 5 (closed loop, sensor fault), 0 (unknown) or warm closed loop.
    return VERDICT_NOT_ENOUGH_DATA


def frontVerdict(snapshot: O2Snapshot, *, nowUtc: datetime, staleSec: float) -> str:
    """The front sensor's verdict token (spec s4.2, Spool 2026-10-13).

    Args:
        snapshot: :meth:`O2History.snapshot` output.
        nowUtc: Aware UTC instant of this write; the window is judged against it.
        staleSec: ``pi.display.stale.obdLiveSec``; a latest status older than
            this reads as absent.

    Returns:
        ``switching`` / ``stuck_lean`` / ``stuck_rich`` / ``unclear`` from the
        gated front samples in the window when there are at least
        :data:`VERDICT_MIN_GATED_SAMPLES`; otherwise the withheld reason:
        ``no_data`` (no current status), ``open_loop`` (status 1/3/4),
        ``warming_up`` (status 2 with coolant of its cycle under 85 C) or
        ``not_enough_data``.
    """
    oldest = nowUtc - timedelta(seconds=snapshot.windowSec)
    front = [s for s in snapshot.front.samples if s.atUtc >= oldest]
    # Readings arrive in event order; sort anyway so the pairing never depends on it.
    fuelStatus = sorted(snapshot.fuelStatus, key=lambda r: r.atUtc)
    coolant = sorted(snapshot.coolant, key=lambda r: r.atUtc)
    volts = _gatedVolts(front, fuelStatus, coolant)
    total = len(volts)
    if total < VERDICT_MIN_GATED_SAMPLES:
        return _withheldReason(fuelStatus, coolant, nowUtc, staleSec)
    low = sum(1 for v in volts if v < SWITCH_LOW_V) / total
    high = sum(1 for v in volts if v > SWITCH_HIGH_V) / total
    if low >= SWITCH_MIN_FRACTION and high >= SWITCH_MIN_FRACTION:
        return VERDICT_SWITCHING
    if sum(1 for v in volts if v < MIDLINE_V) / total >= STUCK_MIN_FRACTION:
        return VERDICT_STUCK_LEAN
    if sum(1 for v in volts if v > MIDLINE_V) / total >= STUCK_MIN_FRACTION:
        return VERDICT_STUCK_RICH
    return VERDICT_UNCLEAR


def buildO2State(snapshot: O2Snapshot, *, nowUtc: datetime, staleSec: float) -> dict[str, Any]:
    """Build the states/o2 payload.

    Args:
        snapshot: :meth:`O2History.snapshot` output.
        nowUtc: Aware UTC instant of this write; the window and staleness are
            judged against it.
        staleSec: ``pi.display.stale.obdLiveSec`` (obd-live's one stale fact).

    Returns:
        ``{front: {value, ts, stale, reason, last, samples: [{v, ts}]}, rear:
        {...}, samplePeriodSec, windowSec, midlineV, frontVerdict,
        frontReason, rearVerdict, catalystVerdict, ts}``. ``last`` is
        ``{value}`` while stale, else None. ``frontReason`` is null when the
        verdict rates the sensor (switching / stuck_lean / stuck_rich), else
        the withheld token (the same as ``frontVerdict``).
    """
    oldest = nowUtc - timedelta(seconds=snapshot.windowSec)
    front = [s for s in snapshot.front.samples if s.atUtc >= oldest]
    rear = [s for s in snapshot.rear.samples if s.atUtc >= oldest]
    verdict = frontVerdict(snapshot, nowUtc=nowUtc, staleSec=staleSec)
    return {
        "front": _sensorState(snapshot.front, front, nowUtc, staleSec),
        "rear": _sensorState(snapshot.rear, rear, nowUtc, staleSec),
        "samplePeriodSec": _samplePeriodSec(front),
        "windowSec": snapshot.windowSec,
        "midlineV": MIDLINE_V,
        "frontVerdict": verdict,
        "frontReason": None if verdict in _LIVE_VERDICTS else verdict,
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
