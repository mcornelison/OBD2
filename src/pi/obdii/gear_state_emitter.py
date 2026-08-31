################################################################################
# File Name: gear_state_emitter.py
# Purpose/Description: US-630 (F-138) states/gear emitter -- the transport that
#                      puts the DERIVED gear on the panel. gear_derivation.py
#                      computes the gear; this writes it, once, to the tmpfs
#                      states dir the dashboard's states_http_server already
#                      serves. Pure transport: it decides nothing about gears
#                      and fabricates no reading -- a typed absence is written
#                      out exactly as the deriver reported it, reason and all.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex (US-630) | Initial -- states/gear payload + emit callable.
# ================================================================================
################################################################################

"""Publish the derived gear to ``states/gear`` (US-630).

Follows the F-092/097/111 card-emitter house shape exactly: a pure
``build...State`` that owns the payload contract, and a ``make...Emitter``
factory returning a best-effort emit callable that writes atomically and NEVER
raises -- the orchestrator's realtime poll is safety-adjacent, so a tmpfs hiccup
must not reach it.

The file is named ``gear`` with no extension, like ``imu`` and
``system-status``: ``states_http_server`` serves any file in the states dir by
name, so writing it is the whole of the transport work and ``GET /gear`` starts
answering the moment the first payload lands.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pi.obdii.gear_derivation import GearReading

__all__ = ["GEAR_STATE_FILENAME", "buildGearState", "makeGearStateEmitter"]

logger = logging.getLogger("pi.obdii.gear")

# The state name the carousel fetches: GET /gear.
GEAR_STATE_FILENAME = "gear"

# Matches the other card emitters' `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def buildGearState(reading: GearReading, *, nowIso: str) -> dict[str, Any]:
    """Build the states/gear payload from one derivation result.

    ``gear`` is written as an explicit ``null`` on every absence rather than
    omitted.  ``carousel.js`` reads ``gearData.gear``, where an absent key and a
    null are both ``undefined`` -- but only the null records that the producer
    ran and found nothing, which is the difference between "no gear right now"
    and "no producer".  The reason travels alongside it in both cases.

    Args:
        reading: What the deriver concluded this instant.
        nowIso: ISO-8601 emission timestamp (the freshness marker).

    Returns:
        ``{"available", "gear", "reason", "ts"}`` -- the three keys
        ``gearView()`` reads, plus the stamp every other state file carries.
    """
    payload: dict[str, Any] = dict(reading.toStateDict())
    payload["ts"] = nowIso
    return payload


def makeGearStateEmitter(
    statesDir: str,
    *,
    nowIsoFn: Callable[[], str] | None = None,
) -> Callable[[GearReading], None]:
    """Build the states/gear emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        A callable taking one :class:`GearReading` and writing it atomically.
        Best-effort by contract: write failures are logged, never raised.
    """
    from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, GEAR_STATE_FILENAME)

    def emit(reading: GearReading) -> None:
        try:
            ensureStatesDir(statesDir)
            writeStateAtomic(target, buildGearState(reading, nowIso=nowFn()))
        except Exception as e:  # noqa: BLE001 -- never crash the realtime poll
            logger.error("states/gear write failed (%s) -- ignored", e)

    return emit
