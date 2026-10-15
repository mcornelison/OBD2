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
        scale: ``{amberFrom, redFrom}`` for RPM's bar zones, else None.
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
                naive-local -> canonical-UTC conversion and the ``pi.bands.*``
                numbers for the band producer.
        """
        self._config = config
        self._latest: dict[str, ObdLiveObservation] = {}
        self._bands = BandProducer(BandSettings.fromConfig(config))
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
            self._latest[name] = ObdLiveObservation(
                value=value,
                unit=canonicalUnit(getattr(reading, "unit", None)),
                ts=toCanonicalIso(eventUtc),
            )

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
                    scale=self._bands.rpmScale if name == PID_RPM else None,
                )
            return snap


def _isStale(ts: str, nowUtc: datetime, staleSec: float) -> bool:
    """True when the reading at ``ts`` is more than ``staleSec`` old at ``nowUtc``."""
    readAt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (nowUtc - readAt).total_seconds() > staleSec


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
        ``{params: {<PID>: {value, unit, ts, stale, band, last}}, dataSource, ts}``.
        A null band adds ``noBandReason``; RPM adds ``scale``. While stale no
        band is evaluated: ``last.band`` is the band frozen at the last reading.
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
        "dataSource": dataSource,
        "ts": nowUtc.strftime(_ISO_FMT),
    }


def makeObdLiveEmitter(statesDir: str) -> Callable[..., None]:
    """Build the states/obd-live emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).

    Returns:
        ``emit(observations, *, nowUtc, staleSec, dataSource)`` writing the
        payload atomically. Best-effort by contract: write failures are logged,
        never raised.
    """
    from pi.splash import boot_state_emitter

    target = os.path.join(statesDir, OBD_LIVE_STATE_FILENAME)

    def emit(
        observations: Mapping[str, ObdLiveObservation],
        *,
        nowUtc: datetime,
        staleSec: float,
        dataSource: str | None,
    ) -> None:
        try:
            boot_state_emitter.ensureStatesDir(statesDir)
            boot_state_emitter.writeStateAtomic(
                target,
                buildObdLiveState(
                    observations,
                    nowUtc=nowUtc,
                    staleSec=staleSec,
                    dataSource=dataSource,
                ),
            )
        except Exception as e:  # noqa: BLE001 -- never crash the run loop
            logger.error("states/obd-live write failed (%s) -- ignored", e)

    return emit
