################################################################################
# File Name: obd_live_emitter.py
# Purpose/Description: US-874 (F-159) states/obd-live -- every PID read this
#                      process, with its latest value, unit, the EVENT time it
#                      was read (canonical UTC) and a band slot the band
#                      producer (US-875) fills. Observed at the orchestrator's
#                      _handleReading seam; this module opens no connection and
#                      reads no database.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Rex (US-874) | Initial -- tracker, pure builder, emit callable.
# 2026-10-14    | Rex (US-875) | The tracker feeds the band producer; every PID
#                                carries band or noBandReason; params.RPM.scale.
# 2026-10-14    | Rex (US-881-b) | engineRunningAt(reading): the band producer's
#                                engine gate, under the lock, same time domain.
# 2026-10-15    | Rex (US-888-b) | observeReading stores the canonical short unit
#                                (pi.obdii.units); obd.db keeps the captured one.
# 2026-10-15    | Rex (US-889-a) | The tracker owns the EngineHistory: each fresh
#                                reading feeds it with the band at that reading;
#                                resetEngineHistory / engineHistoryIfChanged.
# 2026-10-15    | Rex (US-890-b) | params.MAF.scale {max} from
#                                pi.display.scale.mafMaxGs (Atlas S104 ruling 2).
# 2026-10-15    | Rex (US-890-c) | Top-level fuel {loop, totalTrimNow} through the
#                                shared closed-loop code set (Atlas S104 (b)).
# 2026-10-20    | Rex (US-897-b2) | emit returns the payload it wrote (None when
#                                the write failed) for the alerts arbiter (Q18).
# ================================================================================
################################################################################

"""Publish every live PID to ``states/obd-live`` (US-874).

The F-092 card-emitter house shape: a pure ``buildObdLiveState`` that owns the
payload contract, and a ``makeObdLiveEmitter`` factory returning a best-effort
emit callable that writes atomically and never raises.

Three facts are load-bearing:

* **ts is the event time.** ``reading.timestamp`` is a NAIVE LOCAL datetime; it
  is converted with ``localNaiveToCanonicalIso`` -- the converter the bus and
  the row writer already use -- and never replaced by the write time. A reading
  without a timestamp is not recorded at all.
* **value always means CURRENT** (Atlas ruling 2026-10-13 on Iris B-3). Staleness
  is decided at each emit against ``pi.display.stale.obdLiveSec``; a stale PID
  publishes ``value: null`` and carries its old reading under ``last``.
* **A PID never read this process is absent** from ``params`` -- not 0, not null.

The band of each PID comes from ``pi.obdii.band_producer`` (US-875), fed every
reading with its full-precision event time. ``band`` is null whenever ``value``
is, and a null band always carries a ``noBandReason`` code.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from pi.obdii.band_producer import (
    NO_BAND_NO_BAND_DEFINED,
    NO_BAND_NOT_READ,
    NO_BAND_STALE,
    PID_RPM,
    BandProducer,
    BandSettings,
)
from pi.obdii.engine_history import EngineHistory, EngineHistorySettings
from pi.obdii.fuel_status import FUEL_LOOP_OPEN, fuelLoopState
from pi.obdii.units import canonicalUnit

__all__ = [
    "DEFAULT_OBD_LIVE_STALE_S",
    "OBD_LIVE_STATE_FILENAME",
    "ObdLiveObservation",
    "ObdLiveTracker",
    "buildObdLiveState",
    "makeObdLiveEmitter",
]

logger = logging.getLogger("pi.obdii.obd_live")

# The state name a page fetches: GET /obd-live.
OBD_LIVE_STATE_FILENAME = "obd-live"

# Mirrors the validator default for pi.display.stale.obdLiveSec; the basis is
# recorded there (Atlas 2026-10-13, measured on obd2db).
DEFAULT_OBD_LIVE_STALE_S = 5.0

# Matches the other card emitters' `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# US-890-b: the PID whose airflow bar runs 0..pi.display.scale.mafMaxGs.
PID_MAF = "MAF"
_MAF_MAX_KEY = "pi.display.scale.mafMaxGs"

# US-890-c (Atlas S104 total-trim ruling (b)): the inputs of the fuel block.
PID_FUEL_SYSTEM_STATUS = "FUEL_SYSTEM_STATUS"
PID_LTFT = "LONG_FUEL_TRIM_1"
PID_STFT = "SHORT_FUEL_TRIM_1"
TOTAL_TRIM_UNIT = "%"

# totalTrimNow.reason, in PRECEDENCE order: the first that applies is published.
TRIM_NOT_READ = "not_read"
TRIM_STALE = "stale"
TRIM_LOOP_UNKNOWN = "loop_unknown"
TRIM_OPEN_LOOP = "open_loop"


def _mafScale(config: dict[str, Any]) -> dict[str, float]:
    """``{max}`` for params.MAF.scale, from config or the validator default.

    Args:
        config: Configuration mapping (validated or raw).

    Returns:
        ``{"max": pi.display.scale.mafMaxGs}`` as a float.
    """
    from common.config.validator import DEFAULTS

    node: Any = config
    for part in _MAF_MAX_KEY.split("."):
        if not isinstance(node, dict) or part not in node:
            return {"max": float(DEFAULTS[_MAF_MAX_KEY])}
        node = node[part]
    return {"max": float(DEFAULTS[_MAF_MAX_KEY] if node is None else node)}


@dataclass(frozen=True)
class ObdLiveObservation:
    """The latest reading of one PID.

    Attributes:
        value: The reading's value, as realtime_data stores it.
        unit: Its canonical short unit (``pi.obdii.units``, US-888-b); a
            string with no canonical form is kept as the reading carried it.
        ts: Canonical UTC event time of the reading.
        band: ``{band, since, reason}`` at this reading, or None.
        noBandReason: The band producer's code when ``band`` is None.
        scale: ``{amberFrom, redFrom}`` for RPM's bar zones, ``{max}`` for
            MAF's airflow bar (US-890-b), else None.
    """

    value: Any
    unit: str | None
    ts: str
    band: dict[str, str] | None = None
    noBandReason: str | None = None
    scale: dict[str, float] | None = None


class ObdLiveTracker:
    """Every PID observed this process, newest reading per PID.

    Written from the polling thread (``_handleReading``) and read from the run
    loop (the emit tick), so both sides take the lock.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Args:
            config: Validated config; supplies ``pi.time.localZone`` for the
                naive-local -> canonical-UTC conversion, the ``pi.bands.*``
                numbers for the band producer and ``pi.display.scale.mafMaxGs``.
        """
        self._config = config
        self._latest: dict[str, ObdLiveObservation] = {}
        self._bands = BandProducer(BandSettings.fromConfig(config))
        self._engineHistory = EngineHistory(EngineHistorySettings.fromConfig(config))
        self._mafScale = _mafScale(config)
        self._lock = threading.Lock()

    def observeReading(self, reading: Any) -> None:
        """Record one reading as its PID's latest.

        A reading with no name, no value or no capture timestamp is not a
        reading of anything and is not recorded -- the write time is never
        substituted for a missing event time. A null value still reaches the
        band producer, because a null gap resets a dwell.

        Args:
            reading: A ``LoggedReading`` (parameterName, value, unit, timestamp).

        Raises:
            ValueError: If no usable local zone is declared (the converter
                refuses rather than guess the host zone).
        """
        from common.time.helper import toCanonicalIso

        name = getattr(reading, "parameterName", None)
        value = getattr(reading, "value", None)
        timestamp = getattr(reading, "timestamp", None)
        if name is None or not isinstance(timestamp, datetime):
            return
        eventUtc = self._eventUtc(timestamp)
        with self._lock:
            self._bands.observe(name, value, eventUtc)
            if value is None:
                return
            unit = canonicalUnit(getattr(reading, "unit", None))
            # US-889-a (Atlas G2): the history copies the band AT this reading.
            band = self._bands.resultFor(name).band
            self._engineHistory.observe(
                name, value, eventUtc, None if band is None else band["band"], unit
            )
            self._latest[name] = ObdLiveObservation(
                value=value,
                unit=unit,
                ts=toCanonicalIso(eventUtc),
            )

    def resetEngineHistory(self, driveId: int | None, driveStart: Any) -> None:
        """Open a new drive's engine-history window (US-889-a).

        Args:
            driveId: The new drive's id.
            driveStart: The drive start's capture time (naive means the
                declared zone, as for a reading); not a datetime -> unknown.

        Raises:
            ValueError: If no usable local zone is declared.
        """
        startUtc = self._eventUtc(driveStart) if isinstance(driveStart, datetime) else None
        with self._lock:
            self._engineHistory.reset(driveId, startUtc)

    def engineHistoryIfChanged(self) -> dict[str, Any] | None:
        """The engine-history snapshot when a bucket closed or it was reset."""
        with self._lock:
            history: dict[str, Any] | None = self._engineHistory.snapshotIfChanged()
        return history

    def _eventUtc(self, timestamp: datetime) -> datetime:
        """A reading's capture time as aware UTC (naive means the declared zone)."""
        from common.time.helper import resolveLocalZone

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=resolveLocalZone(self._config))
        return timestamp.astimezone(UTC)

    def engineRunningAt(self, reading: Any) -> bool | None:
        """Was the engine running at this reading's capture time? (US-881-b)

        Asks the band producer's engine-running gate under this tracker's lock
        -- the polling thread appends RPM samples while the run loop reads --
        with the time converted exactly as :meth:`observeReading` converts it,
        so both answers are taken in one time domain.

        Args:
            reading: Any reading with a capture ``timestamp``.

        Returns:
            The gate's answer, or None when the reading has no capture time.

        Raises:
            ValueError: If no usable local zone is declared.
        """
        timestamp = getattr(reading, "timestamp", None)
        if not isinstance(timestamp, datetime):
            return None
        eventUtc = self._eventUtc(timestamp)
        with self._lock:
            running: bool = self._bands.engineRunningAt(eventUtc)
        return running

    def snapshot(self) -> dict[str, ObdLiveObservation]:
        """A copy of the latest observation per PID, with its band."""
        with self._lock:
            snap: dict[str, ObdLiveObservation] = {}
            for name, obs in self._latest.items():
                result = self._bands.resultFor(name)
                snap[name] = replace(
                    obs,
                    band=None if result.band is None else dict(result.band),
                    noBandReason=result.noBandReason,
                    scale=self._scaleFor(name),
                )
            return snap

    def _scaleFor(self, name: str) -> dict[str, float] | None:
        """RPM's bar zones, MAF's bar max (US-890-b), else None."""
        if name == PID_RPM:
            return self._bands.rpmScale
        if name == PID_MAF:
            return dict(self._mafScale)
        return None


def _isStale(ts: str, nowUtc: datetime, staleSec: float) -> bool:
    """True when the reading at ``ts`` is more than ``staleSec`` old at ``nowUtc``."""
    return (nowUtc - _parseTs(ts)).total_seconds() > staleSec


def _parseTs(ts: str) -> datetime:
    """A canonical ``...Z`` timestamp as an aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _isTrimValue(value: Any) -> bool:
    """True for a finite number a trim can be summed from (a bool is not one)."""
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    )


def _buildFuelBlock(
    observations: Mapping[str, ObdLiveObservation], nowUtc: datetime, staleSec: float
) -> dict[str, Any]:
    """The ``fuel`` block: ``{loop, totalTrimNow}`` (US-890-c).

    ``loop`` maps FUEL_SYSTEM_STATUS through the ONE closed-loop code set
    (``pi.obdii.fuel_status``); it is null when the status was never read, is
    stale (the params window), or is not a code. ``totalTrimNow`` is LTFT + STFT,
    unrounded and unbanded, at the OLDER input's ts -- null with the first
    reason that applies: not_read > stale > loop_unknown > open_loop.

    Args:
        observations: The SAME latest-per-PID observations as ``params``.
        nowUtc: Aware UTC instant of this emit.
        staleSec: ``pi.display.stale.obdLiveSec``.

    Returns:
        ``{"loop": "closed"|"open"|None, "totalTrimNow": {value, unit, ts, reason}}``.
    """
    status = observations.get(PID_FUEL_SYSTEM_STATUS)
    loop = None
    if status is not None and not _isStale(status.ts, nowUtc, staleSec):
        loop = fuelLoopState(status.value)

    ltft = observations.get(PID_LTFT)
    stft = observations.get(PID_STFT)
    ts: str | None = None
    reason: str | None
    if ltft is None or stft is None or not (_isTrimValue(ltft.value) and _isTrimValue(stft.value)):
        reason = TRIM_NOT_READ
    else:
        ts = min(ltft.ts, stft.ts, key=_parseTs)
        if _isStale(ltft.ts, nowUtc, staleSec) or _isStale(stft.ts, nowUtc, staleSec):
            reason = TRIM_STALE
        elif loop is None:
            reason = TRIM_LOOP_UNKNOWN
        elif loop == FUEL_LOOP_OPEN:
            reason = TRIM_OPEN_LOOP
        else:
            reason = None
    value = None
    if reason is None and ltft is not None and stft is not None:
        value = ltft.value + stft.value
    return {
        "loop": loop,
        "totalTrimNow": {"value": value, "unit": TOTAL_TRIM_UNIT, "ts": ts, "reason": reason},
    }


def buildObdLiveState(
    observations: Mapping[str, ObdLiveObservation],
    *,
    nowUtc: datetime,
    staleSec: float,
    dataSource: str | None,
) -> dict[str, Any]:
    """Build the states/obd-live payload.

    Args:
        observations: The latest observation per PID read this process.
        nowUtc: Aware UTC instant of this emit; staleness is judged against it.
        staleSec: ``pi.display.stale.obdLiveSec``.
        dataSource: The data_source tag of the rows these values came from, or
            None when no logger has resolved one.

    Returns:
        ``{params: {<PID>: {value, unit, ts, stale, band, last}}, fuel, dataSource,
        ts}``. A null band adds ``noBandReason``; RPM and MAF add ``scale``. While
        stale no band is evaluated: ``last.band`` is the band frozen at the last
        reading. ``fuel`` is ``{loop, totalTrimNow}`` from the same observations
        (US-890-c, :func:`_buildFuelBlock`).
    """
    params: dict[str, Any] = {}
    for name, obs in observations.items():
        entry: dict[str, Any]
        if _isStale(obs.ts, nowUtc, staleSec):
            entry = {
                "value": None,
                "unit": obs.unit,
                "ts": obs.ts,
                "stale": True,
                "band": None,
                "noBandReason": NO_BAND_STALE,
                "last": {"value": obs.value, "band": obs.band},
            }
        else:
            band = None if obs.value is None else obs.band
            entry = {
                "value": obs.value,
                "unit": obs.unit,
                "ts": obs.ts,
                "stale": False,
                "band": band,
                "last": None,
            }
            if band is None:
                if obs.value is None:
                    entry["noBandReason"] = NO_BAND_NOT_READ
                else:
                    entry["noBandReason"] = obs.noBandReason or NO_BAND_NO_BAND_DEFINED
        if obs.scale is not None:
            entry["scale"] = dict(obs.scale)
        params[name] = entry
    return {
        "params": params,
        "fuel": _buildFuelBlock(observations, nowUtc, staleSec),
        "dataSource": dataSource,
        "ts": nowUtc.strftime(_ISO_FMT),
    }


def makeObdLiveEmitter(statesDir: str) -> Callable[..., dict[str, Any] | None]:
    """Build the states/obd-live emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).

    Returns:
        ``emit(observations, *, nowUtc, staleSec, dataSource)`` writing the
        payload atomically and returning it (US-897-b2, Atlas Q18: the alerts
        arbiter reads the payload that was published, never a file read-back).
        Best-effort by contract: a write failure is logged, never raised, and
        returns None -- nothing was published.
    """
    from pi.splash import boot_state_emitter

    target = os.path.join(statesDir, OBD_LIVE_STATE_FILENAME)

    def emit(
        observations: Mapping[str, ObdLiveObservation],
        *,
        nowUtc: datetime,
        staleSec: float,
        dataSource: str | None,
    ) -> dict[str, Any] | None:
        try:
            payload = buildObdLiveState(
                observations,
                nowUtc=nowUtc,
                staleSec=staleSec,
                dataSource=dataSource,
            )
            boot_state_emitter.ensureStatesDir(statesDir)
            boot_state_emitter.writeStateAtomic(target, payload)
        except Exception as e:  # noqa: BLE001 -- never crash the run loop
            logger.error("states/obd-live write failed (%s) -- ignored", e)
            return None
        return payload

    return emit
