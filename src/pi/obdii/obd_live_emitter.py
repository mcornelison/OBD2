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
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
        unit: Its unit, as the reading carried it.
        ts: Canonical UTC event time of the reading.
        band: The band at this reading; None until US-875 classifies it.
    """

    value: Any
    unit: str | None
    ts: str
    band: Any = None


class ObdLiveTracker:
    """Every PID observed this process, newest reading per PID.

    Written from the polling thread (``_handleReading``) and read from the run
    loop (the emit tick), so both sides take the lock.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Args:
            config: Validated config; supplies ``pi.time.localZone`` for the
                naive-local -> canonical-UTC conversion.
        """
        self._config = config
        self._latest: dict[str, ObdLiveObservation] = {}
        self._lock = threading.Lock()

    def observeReading(self, reading: Any) -> None:
        """Record one reading as its PID's latest.

        A reading with no name, no value or no capture timestamp is not a
        reading of anything and is ignored -- the write time is never
        substituted for a missing event time.

        Args:
            reading: A ``LoggedReading`` (parameterName, value, unit, timestamp).

        Raises:
            ValueError: If no usable local zone is declared (the converter
                refuses rather than guess the host zone).
        """
        from common.time.helper import localNaiveToCanonicalIso

        name = getattr(reading, "parameterName", None)
        value = getattr(reading, "value", None)
        timestamp = getattr(reading, "timestamp", None)
        if name is None or value is None or not isinstance(timestamp, datetime):
            return
        observation = ObdLiveObservation(
            value=value,
            unit=getattr(reading, "unit", None),
            ts=localNaiveToCanonicalIso(timestamp, self._config),
        )
        with self._lock:
            self._latest[name] = observation

    def snapshot(self) -> dict[str, ObdLiveObservation]:
        """A copy of the latest observation per PID."""
        with self._lock:
            return dict(self._latest)


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
    """
    params: dict[str, Any] = {}
    for name, obs in observations.items():
        if _isStale(obs.ts, nowUtc, staleSec):
            params[name] = {
                "value": None,
                "unit": obs.unit,
                "ts": obs.ts,
                "stale": True,
                "band": None,
                "last": {"value": obs.value, "band": obs.band},
            }
        else:
            params[name] = {
                "value": obs.value,
                "unit": obs.unit,
                "ts": obs.ts,
                "stale": False,
                "band": obs.band,
                "last": None,
            }
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
