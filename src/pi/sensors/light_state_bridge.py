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
# 2026-10-14    | Rex (US-878-b)| states/light gains brightnessLevel and
#               |              | brightnessMode: carousel.js's auto-dim curve
#               |              | ported unchanged (golden table in
#               |              | tests/pi/sensors/test_brightness_golden.py).
#               |              | pi.display.autoDim is re-read through the
#               |              | overlay seam when config.json or
#               |              | config.local.json mtime changes.
# 2026-10-19    | Rex (US-893-a)| The bridge is the ONE brightness applier:
#               |              | states/light gains lightBand, brightnessMode
#               |              | 'default', the curve points, reasons.lux and
#               |              | atLimit, all from one resolved autoDim. One lux
#               |              | predicate (_luxReading, Atlas A3): -1 publishes
#               |              | null.
# ================================================================================
################################################################################

"""Light-state bridge: mirror one reader burst (lux, raw, range) into states/light."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from common.config.overlay import (
    getDotPath,
    loadOverlay,
    overlayPathFor,
    resolveEffectiveConfig,
)
from common.config.validator import DEFAULTS
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
    "BRIGHTNESS_MODE_AUTO",
    "BRIGHTNESS_MODE_DEFAULT",
    "LIGHT_BAND_DAY",
    "LIGHT_BAND_DUSK",
    "LIGHT_BAND_NIGHT",
    "LIGHT_REASON_AT_LIMIT",
    "LIGHT_REASON_NO_READING",
    "LIGHT_STATE_FILENAME",
    "LightStateBridge",
    "brightnessCurve",
    "brightnessCurvePoints",
    "brightnessKnee",
    "brightnessLevel",
    "buildLightState",
    "createLightStateBridgeFromConfig",
    "lightBand",
    "resolveAutoDim",
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

# US-878-b: the level follows the curve. 'fixed' arrives with US-878-c.
BRIGHTNESS_MODE_AUTO = "auto"
# US-893-a (Atlas ruling 3): no lux reading, so the level is defaultLevel.
BRIGHTNESS_MODE_DEFAULT = "default"

# US-893-a: the ambient band the published lux falls in (the page names it).
LIGHT_BAND_NIGHT = "night"
LIGHT_BAND_DUSK = "dusk"
LIGHT_BAND_DAY = "day"

# US-893-a (Atlas L1): why the published lux is null. A code, never a sentence:
# the page maps it to words in LIGHT_REASON_TEXT, as it does for the IMU.
LIGHT_REASON_AT_LIMIT = "at_limit"
LIGHT_REASON_NO_READING = "no_reading"

# US-893-a (Atlas Q5/A4): the published curve's grid -- 10 log-spaced points per
# decade from 0.3 lux, i = 0..50, so it ends at 0.3 * 10**5 = 30000 lux.
_CURVE_GRID_START_LUX = 0.3
_CURVE_GRID_PER_DECADE = 10
_CURVE_GRID_COUNT = 51
# A grid point this close (relative) to a breakpoint is dropped and the exact
# breakpoint kept: the grid's 94.86832980505139 sits one ulp from the knee.
_CURVE_DEDUP_REL = 1e-9

# The auto-dim section. Its keys and fallback values come from the validator
# DEFAULTS. Since US-893-a the page holds only defaultLevel and luxStaleSec.
_AUTODIM_KEY = "pi.display.autoDim"
_AUTODIM_PREFIX = _AUTODIM_KEY + "."
_AUTODIM_DEFAULTS: dict[str, Any] = {
    key[len(_AUTODIM_PREFIX):]: value
    for key, value in DEFAULTS.items()
    if key.startswith(_AUTODIM_PREFIX)
}

# The curve value the page treats as linear; any other string is logarithmic.
_CURVE_LINEAR = "linear"

# US-878-b (Atlas ruled B): config.json and config.local.json mtimes are
# checked at most once per second while bursts arrive.
_CONFIG_RECHECK_S = 1.0


def resolveAutoDim(section: Any) -> dict[str, Any]:
    """Resolve an autoDim section over the validator defaults (pure).

    The port of carousel.js ``resolveAutoDimConfig``: each key starts at its
    default and only a well-typed value wins -- a finite number (never a bool)
    for the numeric keys, a string for ``curve``. Anything else, including a
    non-dict section, leaves the default in place.

    Args:
        section: The ``pi.display.autoDim`` mapping, or None.

    Returns:
        A complete autoDim dict.
    """
    out = dict(_AUTODIM_DEFAULTS)
    if not isinstance(section, dict):
        return out
    for key in _AUTODIM_DEFAULTS:
        if key not in section:
            continue
        value = section[key]
        if key == "curve":
            if isinstance(value, str):
                out[key] = value
        elif (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            out[key] = value
    return out


def brightnessCurve(lux: float, luxMin: float, luxFull: float, curve: str) -> float:
    """The perceptual lux -> 0..1 mapping, ported unchanged from carousel.js.

    0 at/below luxMin, 1 at/above luxFull. A degenerate range (luxFull <=
    luxMin) is full, and a non-positive luxMin or lux under the log curve falls
    back to linear, so it can never divide by zero or take a log of <= 0.

    Args:
        lux: A finite lux reading.
        luxMin: Lux at and below which the curve is 0.
        luxFull: Lux at and above which the curve is 1.
        curve: ``'linear'``, else logarithmic (as the page reads it).

    Returns:
        The curve value in [0, 1].
    """
    if not math.isfinite(lux):
        return 0.0
    if not luxFull > luxMin:
        return 1.0
    if lux <= luxMin:
        return 0.0
    if lux >= luxFull:
        return 1.0
    if curve != _CURVE_LINEAR and luxMin > 0 and lux > 0:
        return (math.log(lux) - math.log(luxMin)) / (math.log(luxFull) - math.log(luxMin))
    return (lux - luxMin) / (luxFull - luxMin)


def brightnessKnee(autoDim: dict[str, Any] | None) -> float | None:
    """The lux at which the curve rises off the minLevel clamp, or None.

    Mirrors brightnessCurve's branches (Atlas A5): no knee when minLevel <= 0
    (nothing is clamped), minLevel >= 1 (the clamp is 1 everywhere) or luxFull
    <= luxMin (the curve is 1 everywhere). Linear when curve is 'linear' or
    luxMin <= 0, else logarithmic.

    Args:
        autoDim: The autoDim section; resolved over the validator defaults.

    Returns:
        The knee lux, or None when the curve has none.
    """
    cfg = resolveAutoDim(autoDim)
    luxMin, luxFull, minLevel = cfg["luxMin"], cfg["luxFull"], cfg["minLevel"]
    if minLevel <= 0 or minLevel >= 1 or not luxFull > luxMin:
        return None
    if cfg["curve"] == _CURVE_LINEAR or luxMin <= 0:
        return float(luxMin + minLevel * (luxFull - luxMin))
    return float(luxMin * (luxFull / luxMin) ** minLevel)


def brightnessCurvePoints(autoDim: dict[str, Any] | None) -> dict[str, Any]:
    """The published curve: ``{points, luxMin, luxFull, minLevel}`` (Atlas Q5/A4).

    ``points`` is the log grid (0.3..30000 lux, 10 per decade) united with the
    breakpoints luxMin, luxFull and the knee -- each only when finite and > 0 --
    sorted ascending as ``[lux, level]`` lists. A grid point within a relative
    1e-9 of a breakpoint is dropped so the exact config value is published.
    Every level is ``brightnessLevel(lux, autoDim)``. Fresh lists every call, so
    no caller can mutate another write's curve.

    Args:
        autoDim: The autoDim section; resolved over the validator defaults.

    Returns:
        The curve dict.
    """
    cfg = resolveAutoDim(autoDim)
    breakpoints = [
        float(v)
        for v in (cfg["luxMin"], cfg["luxFull"], brightnessKnee(cfg))
        if v is not None and math.isfinite(v) and v > 0
    ]
    grid = [
        _CURVE_GRID_START_LUX * 10 ** (i / _CURVE_GRID_PER_DECADE)
        for i in range(_CURVE_GRID_COUNT)
    ]
    kept = [
        lux
        for lux in grid
        if not any(math.isclose(lux, bp, rel_tol=_CURVE_DEDUP_REL, abs_tol=0.0)
                   for bp in breakpoints)
    ]
    luxes = sorted(set(kept) | set(breakpoints))
    return {
        "points": [[lux, brightnessLevel(lux, cfg)] for lux in luxes],
        "luxMin": cfg["luxMin"],
        "luxFull": cfg["luxFull"],
        "minLevel": cfg["minLevel"],
    }


def brightnessLevel(lux: Any, autoDim: dict[str, Any] | None) -> float:
    """The 0..1 panel level for one lux reading -- the ONE brightness curve.

    The port of carousel.js ``brightnessLevel`` (US-878-b) WITHOUT the STOP
    override, which stays page-side; since US-893-a the page applies this
    level and holds no curve of its own. A lux that is not a reading (absent,
    saturated, failed, negative or non-finite: ``_luxReading``) gives
    defaultLevel UNCLAMPED to minLevel (US-627: the floor is enforced by
    validate_config, never hidden here); a curved value is clamped to
    [minLevel, 1.0]. Both are then bounded to [0, 1]. Staleness is the
    reader's concern: this is the level for the reading at its own event time.

    Args:
        lux: The published lux (float or None).
        autoDim: The autoDim section; resolved over the validator defaults.

    Returns:
        The brightness level in [0, 1].
    """
    cfg = resolveAutoDim(autoDim)
    luxF = _luxReading(lux)
    if luxF is None:
        level = cfg["defaultLevel"]
    else:
        curved = brightnessCurve(luxF, cfg["luxMin"], cfg["luxFull"], cfg["curve"])
        level = min(max(curved, cfg["minLevel"]), 1.0)
    return float(min(max(level, 0.0), 1.0))


def lightBand(lux: Any, autoDim: dict[str, Any] | None) -> str | None:
    """The ambient band a lux reading falls in, or None when it is not a reading.

    Tested DAY first (lux >= luxFull), then night (lux < luxMin), else dusk
    (Atlas A5): with luxFull <= luxMin dusk is unreachable and day agrees with
    the level 1.0; with luxMin <= 0 there is no night.

    Args:
        lux: The published lux (float or None).
        autoDim: The autoDim section; resolved over the validator defaults.

    Returns:
        ``'night'``, ``'dusk'``, ``'day'`` or None.
    """
    luxF = _luxReading(lux)
    if luxF is None:
        return None
    cfg = resolveAutoDim(autoDim)
    if luxF >= cfg["luxFull"]:
        return LIGHT_BAND_DAY
    if luxF < cfg["luxMin"]:
        return LIGHT_BAND_NIGHT
    return LIGHT_BAND_DUSK


def _luxReading(value: Any) -> float | None:
    """A lux that is a reading -- finite AND >= 0 -- as a float, else None.

    THE one predicate (Atlas A3): the published lux, the level's default
    branch, brightnessMode 'default', lightBand null and reasons.lux all key
    off it. The producer already publishes ``None`` on saturation and on a
    negative computed lux (sensor_reader._honestLux, ARCH-010); this is
    defense-in-depth at the seam so a non-finite, negative or non-numeric value
    can never land in the state file as a fabricated reading.
    """
    if value is None:
        return None
    try:
        luxF = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(luxF) or luxF < 0:
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


def _countAtLimit(count: int | None, ceiling: int | None) -> bool | None:
    """One channel against the ceiling: None when either is unknown (Atlas L2)."""
    if count is None or ceiling is None:
        return None
    return count >= ceiling


def buildLightState(
    *,
    lux: float | None,
    tsUtc: str,
    rawCounts: Any = None,
    rangeContext: Any = None,
    autoDim: dict[str, Any] | None = None,
) -> dict:
    """Assemble the states/light payload from one reader burst (pure).

    Args:
        lux: The burst's lux reading, or None when saturated/unreadable. A
            non-finite or negative value is published as None (never inf/nan,
            never a negative in the file; Atlas A3).
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
        autoDim: The ``pi.display.autoDim`` section the brightness level is
            computed under; None uses the validator defaults.

    Returns:
        ``{lux, visibleCount, irCount, fullCount, gain, integrationMs,
        channelAtLimit, atLimit, lightBand, brightnessLevel, brightnessMode,
        curve, reasons, ts}``. ``gain`` is a label, never a register code;
        ``channelAtLimit`` is null when the saturation ceiling for the
        integration time is unknown; when it is true, ``lux`` is null.
        ``atLimit`` holds the same test per channel. ``lightBand``,
        ``brightnessLevel`` (US-878-b), ``brightnessMode`` and ``curve`` all
        come from the published ``lux`` under ONE resolved autoDim (Atlas
        A6); ``reasons.lux`` is present only when ``lux`` is null.
    """
    visibleCount = _coerceCount(_tupleField(rawCounts, 0))
    if visibleCount is not None and visibleCount < 0:
        visibleCount = None
    irCount = _coerceCount(_tupleField(rawCounts, 1))
    fullCount = _coerceCount(_tupleField(rawCounts, 2))
    integrationMs = _coerceCount(_tupleField(rangeContext, 1))
    ceiling = saturationCeilingForIntegrationMs(integrationMs)
    channelAtLimit = _channelAtLimit(fullCount, irCount, ceiling)
    publishedLux = None if channelAtLimit is True else _luxReading(lux)
    cfg = resolveAutoDim(autoDim)
    reasons: dict[str, str] = {}
    if publishedLux is None:
        reasons["lux"] = (
            LIGHT_REASON_AT_LIMIT if channelAtLimit is True else LIGHT_REASON_NO_READING
        )
    return {
        "lux": publishedLux,
        "visibleCount": visibleCount,
        "irCount": irCount,
        "fullCount": fullCount,
        "gain": tslGainLabel(_tupleField(rangeContext, 0)),
        "integrationMs": integrationMs,
        "channelAtLimit": channelAtLimit,
        "atLimit": {
            "ir": _countAtLimit(irCount, ceiling),
            "full": _countAtLimit(fullCount, ceiling),
        },
        "lightBand": lightBand(publishedLux, cfg),
        "brightnessLevel": brightnessLevel(publishedLux, cfg),
        "brightnessMode": (
            BRIGHTNESS_MODE_DEFAULT if publishedLux is None else BRIGHTNESS_MODE_AUTO
        ),
        "curve": brightnessCurvePoints(cfg),
        "reasons": reasons,
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
        autoDim: dict[str, Any] | None = None,
        configPath: str | None = None,
        monotonicFn: Callable[[], float] | None = None,
    ) -> None:
        """Bind the bridge to its source subscription + states dir.

        Args:
            subscription: The bus Subscription (LOSSY on raw.light.lux) this
                consumer drains. May be None for direct-handleSample tests.
            statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
            nowIsoFn: Fallback clock for ``ts`` when a sample carries no tsUtc
                (default UTC now, canonical ISO). The sample's own tsUtc is used
                whenever present (honest read-time freshness).
            autoDim: The start ``pi.display.autoDim`` section (None -> the
                validator defaults).
            configPath: config.json path. When set, autoDim is re-read through
                the overlay seam once config.json or config.local.json changes
                mtime; None keeps the start config for the process lifetime.
            monotonicFn: Monotonic clock (seconds) pacing the mtime check
                (default ``time.monotonic``).
        """
        self._sub = subscription
        self._statesDir = statesDir
        self._target = os.path.join(statesDir, LIGHT_STATE_FILENAME)
        self._nowIsoFn = nowIsoFn if nowIsoFn is not None else utcIsoNow
        # US-878-b: the bridge's own autoDim -- never the HTTP server's
        # start-time cache (Atlas gap 5).
        self._autoDim = resolveAutoDim(autoDim)
        self._configPath = configPath
        self._monotonicFn = monotonicFn if monotonicFn is not None else time.monotonic
        self._lastConfigCheck = self._monotonicFn()
        self._configMtimes = (
            self._readConfigMtimes(configPath) if configPath is not None else None
        )
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

    # -- autoDim config (US-878-b) ---------------------------------------------
    @property
    def autoDim(self) -> dict[str, Any]:
        """The autoDim section the next brightnessLevel is computed under."""
        return dict(self._autoDim)

    @staticmethod
    def _readConfigMtimes(configPath: str) -> tuple[int | None, int | None]:
        """``st_mtime_ns`` of config.json and config.local.json; None if absent."""
        mtimes: list[int | None] = []
        for path in (configPath, overlayPathFor(configPath)):
            try:
                mtimes.append(os.stat(path).st_mtime_ns)
            except OSError:
                mtimes.append(None)
        return mtimes[0], mtimes[1]

    def _currentAutoDim(self) -> dict[str, Any]:
        """The autoDim to compute under, re-read when either file changed.

        The mtimes are checked at most once per ``_CONFIG_RECHECK_S`` of the
        monotonic clock. Without a configPath the start config stands.
        """
        configPath = self._configPath
        if configPath is None:
            return self._autoDim
        now = self._monotonicFn()
        if now - self._lastConfigCheck < _CONFIG_RECHECK_S:
            return self._autoDim
        self._lastConfigCheck = now
        mtimes = self._readConfigMtimes(configPath)
        if mtimes != self._configMtimes and self._reloadAutoDim(configPath):
            self._configMtimes = mtimes
        return self._autoDim

    def _reloadAutoDim(self, configPath: str) -> bool:
        """Re-read autoDim from config.json through the overlay seam.

        config.local.json is applied by ``resolveEffectiveConfig``, whose
        allow-list holds luxMin and luxFull (US-895-b: the CIO reversed Atlas
        ruling B 2026-10-19), so a saved lux end applies on the next burst after
        the mtime check; a pair that breaks ``luxFull > luxMin`` is dropped
        there. An unreadable or malformed config.json keeps the current autoDim
        and returns False, so the next check retries it.
        """
        try:
            with open(configPath, encoding="utf-8") as fh:
                base = json.load(fh)
        except (OSError, ValueError) as e:
            logger.warning("light-state autoDim re-read failed (%s) -- kept", e)
            return False
        if not isinstance(base, dict):
            logger.warning("light-state autoDim re-read: config is not an object -- kept")
            return False
        effective = resolveEffectiveConfig(base, loadOverlay(overlayPathFor(configPath)))
        _, section = getDotPath(effective, _AUTODIM_KEY)
        self._autoDim = resolveAutoDim(section)
        return True

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
                autoDim=self._currentAutoDim(),
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
    configPath: str | None = None,
    monotonicFn: Callable[[], float] | None = None,
) -> LightStateBridge | None:
    """Build the light-state bridge from validated config, or None when dark.

    Returns None unless ``pi.bus.enabled`` AND ``pi.sensors.light.enabled`` are
    both set -- so with the default flags off nothing is built (ships dark).

    Args:
        config: Validated tier-aware config (reads the ``pi`` section). Its
            ``pi.display.autoDim`` is the bridge's start config.
        bus: The SampleBus to subscribe to (LOSSY on raw.light.lux, .raw and
            .range -- a display only needs the freshest reading, drop-oldest on
            overflow; a burst that loses a sample is written with it null).
        nowIsoFn: Optional fallback clock for ``ts`` (see LightStateBridge).
        configPath: config.json path for the autoDim re-read (Atlas G5);
            None keeps the start config.
        monotonicFn: Optional monotonic clock pacing that re-read.

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
    _, autoDim = getDotPath(config, _AUTODIM_KEY)
    return LightStateBridge(
        subscription,
        statesDir,
        nowIsoFn=nowIsoFn,
        autoDim=autoDim,
        configPath=configPath,
        monotonicFn=monotonicFn,
    )
