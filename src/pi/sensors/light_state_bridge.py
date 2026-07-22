################################################################################
# File Name: light_state_bridge.py
# Purpose/Description: US-483-a light -> states/light bridge (F-121). A PURE
#   consumer of the F-110 SampleBus that drains the additive raw.light.lux channel
#   (published by sensor_reader.LightReader off the TSL2591 @0x29) and mirrors the
#   latest reading into the dashboard states/light file -- the SSOT state file the
#   US-483-b display-brightness consumer reads (Atlas DELTA-2: the display never
#   touches the sensor, only this reader-owned state file). The file shape mirrors
#   the US-480-a states/ writers: {lux, ts}, written atomically via the shared
#   boot_state_emitter primitives, and served as-is by eclipse-states-http.
#
#   Honest-instrument (carries the sensor_reader contract through the seam): a
#   saturated read is lux=None -> JSON null (never inf, never a fabricated 0.0),
#   and the freshness `ts` is the SAMPLE's own read-time (not write-time) so a
#   stalled feed goes honestly stale and the consumer falls back to its fixed
#   default rather than trusting a frozen value. This module opens no I2C device
#   and starts no OBD connection -- it is a bus subscriber only, so it does not
#   re-introduce the A-17 second-connection race.
#
#   Gated behind pi.bus.enabled + pi.sensors.light.enabled (ships dark, built only
#   by createLightStateBridgeFromConfig when both are set).
# Author: Rex (US-483-a)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-22    | Rex (US-483-a)| Initial -- bus raw.light.lux -> states/light
#               |              | bridge, atomic write, honest null/stale, config
#               |              | factory (ships dark behind bus + light gates).
# ================================================================================
################################################################################

"""Light-state bridge: mirror the bus raw.light.lux channel into states/light."""

from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Callable
from typing import Any

from common.time.helper import utcIsoNow

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

__all__ = [
    "LIGHT_STATE_FILENAME",
    "TOPIC_LIGHT_LUX",
    "LightStateBridge",
    "buildLightState",
    "createLightStateBridgeFromConfig",
]

# The single states/ slot the carousel brightness consumer polls (US-483-b).
LIGHT_STATE_FILENAME = "light"

# The bus channel this bridge consumes (exact topic -- never raw.light.raw). Kept
# in sync with sensor_reader.TOPIC_LIGHT_LUX (the producer-side SSOT).
TOPIC_LIGHT_LUX = "raw.light.lux"

# Default tmpfs states dir (matches boot_state_emitter + the states-http unit).
_DEFAULT_STATES_DIR = "/run/eclipse-obd/states"

# Bus name for the bridge's subscription (appears in SubStats / gap markers).
_SUB_NAME = "light-state"

# How long the drain loop blocks waiting for a sample before re-checking _stop.
_DRAIN_TIMEOUT_S = 0.5


def _coerceLux(value: Any) -> float | None:
    """Coerce a lux reading to a finite float, else None (honest NULL).

    The producer already publishes ``None`` on saturation and guards against
    inf/nan (sensor_reader._readLux); this is defense-in-depth at the seam so a
    non-finite or non-numeric value can never land in the state file as a
    fabricated reading.
    """
    if value is None:
        return None
    try:
        luxF = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(luxF):
        return None
    return luxF


def buildLightState(*, lux: float | None, tsUtc: str) -> dict:
    """Assemble the states/light payload (pure).

    Args:
        lux: The latest lux reading, or None when saturated/unreadable. A
            non-finite value is coerced to None (never inf/nan in the file).
        tsUtc: The reading's ISO-8601 read-time (the freshness marker the
            US-483-b consumer compares against ``luxStaleSec``).

    Returns:
        ``{"lux": <float|None>, "ts": <tsUtc>}`` -- the exact shape mirroring the
        US-480-a states/ writers.
    """
    return {"lux": _coerceLux(lux), "ts": tsUtc}


class LightStateBridge:
    """Drains raw.light.lux off the bus and mirrors it into states/light.

    A pure bus consumer (Atlas DELTA-2): it opens no I2C device and starts no OBD
    connection. Each ``raw.light.lux`` sample is written to the states/light file
    atomically as ``{lux, ts}`` (``lux`` may be None on saturation -> JSON null).
    The drain runs on its own daemon thread, mirroring the EdrPersistenceSubscriber
    lifecycle; a write fault is isolated (logged, never crashes the loop).
    """

    def __init__(
        self,
        subscription: Any,
        statesDir: str,
        *,
        nowIsoFn: Callable[[], str] | None = None,
    ) -> None:
        """Bind the bridge to its source subscription + states dir.

        Args:
            subscription: The bus Subscription (LOSSY on raw.light.lux) this
                consumer drains. May be None for direct-handleSample tests.
            statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
            nowIsoFn: Fallback clock for ``ts`` when a sample carries no tsUtc
                (default UTC now, canonical ISO). The sample's own tsUtc is used
                whenever present (honest read-time freshness).
        """
        self._sub = subscription
        self._statesDir = statesDir
        self._target = os.path.join(statesDir, LIGHT_STATE_FILENAME)
        self._nowIsoFn = nowIsoFn if nowIsoFn is not None else utcIsoNow
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Start the background drain thread."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="LightStateBridge", daemon=True
        )
        self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        """Signal the drain loop to exit and join the thread.

        Args:
            timeoutS: Maximum seconds to wait for the drain thread to finish.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)
            self._thread = None

    def _loop(self) -> None:
        """Drain samples until stopped (consumer isolation -- never crashes)."""
        if self._sub is None:
            return
        while not self._stop.is_set():
            sample = self._sub.get(timeoutS=_DRAIN_TIMEOUT_S)
            if sample is not None:
                try:
                    self.handleSample(sample)
                except Exception as e:  # noqa: BLE001 -- never crash the loop
                    logger.warning("light-state handleSample failed: %s", e)

    # -- ingest ----------------------------------------------------------------
    def handleSample(self, sample: Any) -> bool:
        """Mirror one raw.light.lux sample into states/light.

        Returns True if the sample was a lux reading and was written; False when
        it is any other topic (raw.light.raw / raw.obd.*), which is ignored.
        """
        if getattr(sample, "topic", None) != TOPIC_LIGHT_LUX:
            return False
        tsUtc = getattr(sample, "tsUtc", "") or self._nowIsoFn()
        self._writeState(buildLightState(lux=sample.value, tsUtc=tsUtc))
        return True

    def _writeState(self, payload: dict) -> None:
        """Write the states/light payload atomically (best-effort, never raises).

        A write failure is logged but never raised: the bridge is a dashboard
        hook and must never crash the bus drain (mirrors the emitters' contract).
        """
        try:
            ensureStatesDir(self._statesDir)
            writeStateAtomic(self._target, payload)
        except Exception as e:  # noqa: BLE001 -- best-effort, never crash the drain
            logger.error("states/light write failed (%s) -- ignored", e)


def createLightStateBridgeFromConfig(
    config: dict[str, Any],
    bus: Any,
    *,
    nowIsoFn: Callable[[], str] | None = None,
) -> LightStateBridge | None:
    """Build the light-state bridge from validated config, or None when dark.

    Returns None unless ``pi.bus.enabled`` AND ``pi.sensors.light.enabled`` are
    both set -- so with the default flags off nothing is built (ships dark).

    Args:
        config: Validated tier-aware config (reads the ``pi`` section).
        bus: The SampleBus to subscribe to (LOSSY on raw.light.lux -- a display
            only needs the freshest reading, drop-oldest on overflow).
        nowIsoFn: Optional fallback clock for ``ts`` (see LightStateBridge).

    Returns:
        A ready-to-start LightStateBridge, or None when disabled.
    """
    # Local import: keep the module import graph free of a hard bus dependency
    # for the pure-function (buildLightState) consumers.
    from pi.bus.sample import QoS

    pi = config.get("pi", {})
    if not pi.get("bus", {}).get("enabled", False):
        return None
    light = pi.get("sensors", {}).get("light", {})
    if not light.get("enabled", False):
        return None

    statesDir = pi.get("splash", {}).get("statesDir", _DEFAULT_STATES_DIR)
    subscription = bus.subscribe([TOPIC_LIGHT_LUX], QoS.LOSSY, _SUB_NAME)
    return LightStateBridge(subscription, statesDir, nowIsoFn=nowIsoFn)
