################################################################################
# File Name: light_state_bridge.py
# Purpose/Description: US-483-a light -> states/light bridge (F-121). A PURE
#   consumer of the F-110 SampleBus that drains the additive raw.light.lux channel
#   (published by sensor_reader.LightReader off the TSL2591 @0x29) and mirrors the
#   latest reading into the dashboard states/light file -- the SSOT state file the
#   US-483-b display-brightness consumer reads (Atlas DELTA-2: the display never
#   touches the sensor, only this reader-owned state file). The file shape mirrors
#   the US-480-a states/ writers ({lux, ts}, plus the US-878-a raw counts, gain,
#   integration ms and channelAtLimit), written atomically via the shared
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
# 2026-10-13    | Rex (US-873) | Record the first sample ts and the newest
#               |              | sample capture for capture-health feeds.light.
# 2026-10-14    | Rex (US-878-a)| states/light carries the raw counts, gain label,
#               |              | integration ms and channelAtLimit. The bridge
#               |              | drains lux + raw + range, pairs them by Sample.seq
#               |              | and writes once per burst (on range, or when a
#               |              | newer seq shows the burst lost a sample). Topic
#               |              | copy deleted: imported from sensor_reader.
# ================================================================================
################################################################################

"""Light-state bridge: mirror one reader burst (lux, raw, range) into states/light."""

from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Callable
from typing import Any

from common.time.helper import utcIsoNow

# The producer-side SSOT for the topics, the ceilings and the gain codes
# (US-878-a): the bridge copies none of them.
from pi.sensors.sensor_reader import (
    TOPIC_LIGHT_LUX,
    TOPIC_LIGHT_RANGE,
    TOPIC_LIGHT_RAW,
    saturationCeilingForIntegrationMs,
    tslGainLabel,
)

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

__all__ = [
    "LIGHT_STATE_FILENAME",
    "LightStateBridge",
    "buildLightState",
    "createLightStateBridgeFromConfig",
]

# The single states/ slot the carousel brightness consumer polls (US-483-b).
LIGHT_STATE_FILENAME = "light"

# The three channels of one reader burst, published in this order under one seq.
_LIGHT_TOPICS = (TOPIC_LIGHT_LUX, TOPIC_LIGHT_RAW, TOPIC_LIGHT_RANGE)

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


def _coerceCount(value: Any) -> int | None:
    """A raw channel count as an int, else None (never a bool, never a float)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _tupleField(value: Any, index: int) -> Any:
    """``value[index]`` of a bus tuple, or None when the tuple is absent or short."""
    if not isinstance(value, (tuple, list)) or len(value) <= index:
        return None
    return value[index]


def _channelAtLimit(fullCount: int | None, irCount: int | None, ceiling: int | None) -> bool | None:
    """True when a channel reached the ceiling, False when both are below it.

    None when the ceiling is unknown, or when the only channel read is below it
    (the unread one could be at the limit, so "not at limit" is not known).
    """
    if ceiling is None:
        return None
    known = [c for c in (fullCount, irCount) if c is not None]
    if any(c >= ceiling for c in known):
        return True
    if len(known) < 2:
        return None
    return False


def buildLightState(
    *,
    lux: float | None,
    tsUtc: str,
    rawCounts: Any = None,
    rangeContext: Any = None,
) -> dict:
    """Assemble the states/light payload from one reader burst (pure).

    Args:
        lux: The burst's lux reading, or None when saturated/unreadable. A
            non-finite value is coerced to None (never inf/nan in the file).
        tsUtc: The reading's ISO-8601 EVENT instant (the freshness marker
            the US-483-b consumer compares against ``luxStaleSec``). Empty
            yields ``ts: null`` rather than a substituted clock reading,
            which would be permanently fresh (US-809-c).
        rawCounts: The raw.light.raw value ``(visible, infrared, full)``, or
            None when the burst lost it. ``visible`` is computed by the reader
            as full - infrared and goes negative on a failed read: a negative
            visible count is published as null.
        rangeContext: The raw.light.range value ``(gainCode, integrationMs)``,
            or None when the burst lost it.

    Returns:
        ``{lux, visibleCount, irCount, fullCount, gain, integrationMs,
        channelAtLimit, ts}``. ``gain`` is a label, never a register code;
        ``channelAtLimit`` is null when the saturation ceiling for the
        integration time is unknown; when it is true, ``lux`` is null.
    """
    visibleCount = _coerceCount(_tupleField(rawCounts, 0))
    if visibleCount is not None and visibleCount < 0:
        visibleCount = None
    irCount = _coerceCount(_tupleField(rawCounts, 1))
    fullCount = _coerceCount(_tupleField(rawCounts, 2))
    integrationMs = _coerceCount(_tupleField(rangeContext, 1))
    channelAtLimit = _channelAtLimit(
        fullCount, irCount, saturationCeilingForIntegrationMs(integrationMs)
    )
    return {
        "lux": None if channelAtLimit is True else _coerceLux(lux),
        "visibleCount": visibleCount,
        "irCount": irCount,
        "fullCount": fullCount,
        "gain": tslGainLabel(_tupleField(rangeContext, 0)),
        "integrationMs": integrationMs,
        "channelAtLimit": channelAtLimit,
        "ts": tsUtc or None,
    }


class _PendingBurst:
    """The samples of one reader burst seen so far, keyed by its Sample.seq."""

    def __init__(self, seq: int) -> None:
        self.seq = seq
        self.byTopic: dict[str, Any] = {}

    def tsUtc(self) -> str:
        """The lux sample's event ts; else the first sample's (never the clock)."""
        lux = self.byTopic.get(TOPIC_LIGHT_LUX)
        if lux is not None:
            return getattr(lux, "tsUtc", "")
        first = next(iter(self.byTopic.values()), None)
        return getattr(first, "tsUtc", "") if first is not None else ""

    def value(self, topic: str) -> Any:
        sample = self.byTopic.get(topic)
        return None if sample is None else sample.value


class LightStateBridge:
    """Drains one reader burst at a time off the bus into states/light.

    A pure bus consumer (Atlas DELTA-2): it opens no I2C device and starts no OBD
    connection. The reader publishes lux, raw and range in that order under ONE
    ``Sample.seq`` (a failed read publishes nothing), so the bridge pairs the
    three by seq and writes once per burst, when the burst's range sample lands.
    A sample of a different seq arriving first means the lossy queue dropped part
    of the pending burst: that burst is written with its missing fields null --
    another burst's counts are never borrowed (Atlas G3). The drain runs on its
    own daemon thread, mirroring the EdrPersistenceSubscriber lifecycle; a write
    fault is isolated (logged, never crashes the loop).
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
        # US-873: the light feed's capture-health facts for THIS process. Held
        # on the instance, so a restart re-arms them; None until a sample lands.
        self._firstSampleTs: str | None = None
        self._lastSampleCapture: float | None = None
        self._pending: _PendingBurst | None = None

    # -- capture-health feed (US-873) -----------------------------------------
    @property
    def firstSampleTs(self) -> str | None:
        """The ``tsUtc`` of the first lux sample drained in this process."""
        return self._firstSampleTs

    @property
    def lastSampleCapture(self) -> float | None:
        """The monotonic ``tsCapture`` of the newest lux sample, or None."""
        return self._lastSampleCapture

    def _recordFeedSample(self, sample: Any) -> None:
        """Note one live sample for the capture-health ``feeds.light`` entry.

        A saturated read (``lux`` None) still counts: the sensor answered. The
        first timestamp is first-write-wins and is never substituted by the
        clock -- a sample with no ``tsUtc`` leaves it unset.
        """
        tsUtc = getattr(sample, "tsUtc", "")
        if self._firstSampleTs is None and isinstance(tsUtc, str) and tsUtc:
            self._firstSampleTs = tsUtc
        capture = getattr(sample, "tsCapture", None)
        if isinstance(capture, (int, float)) and not isinstance(capture, bool):
            self._lastSampleCapture = float(capture)

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
        """Fold one light sample into its burst; write states/light when complete.

        Returns True when the sample is one of the burst's three topics (lux,
        raw, range); False for any other topic, which is ignored.
        """
        topic = getattr(sample, "topic", None)
        if topic not in _LIGHT_TOPICS:
            return False
        if topic == TOPIC_LIGHT_LUX:
            self._recordFeedSample(sample)
        seq = sample.seq
        if self._pending is not None and self._pending.seq != seq:
            # A newer burst began before this one's range arrived: the queue
            # dropped a sample. Write what this burst has; never mix bursts.
            self._flushPending()
        if self._pending is None:
            self._pending = _PendingBurst(seq)
        self._pending.byTopic[topic] = sample
        if topic == TOPIC_LIGHT_RANGE:
            self._flushPending()
        return True

    def _flushPending(self) -> None:
        """Write the pending burst to states/light and clear it."""
        burst = self._pending
        self._pending = None
        if burst is None:
            return
        # US-809-c: carry the absence rather than substituting the clock. A
        # fabricated ts is always fresh, so the US-483-b luxStaleSec check
        # would still be there and would have stopped being able to fire.
        self._writeState(
            buildLightState(
                lux=burst.value(TOPIC_LIGHT_LUX),
                tsUtc=burst.tsUtc(),
                rawCounts=burst.value(TOPIC_LIGHT_RAW),
                rangeContext=burst.value(TOPIC_LIGHT_RANGE),
            )
        )

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
        bus: The SampleBus to subscribe to (LOSSY on raw.light.lux, .raw and
            .range -- a display only needs the freshest reading, drop-oldest on
            overflow; a burst that loses a sample is written with it null).
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
    subscription = bus.subscribe(list(_LIGHT_TOPICS), QoS.LOSSY, _SUB_NAME)
    return LightStateBridge(subscription, statesDir, nowIsoFn=nowIsoFn)
