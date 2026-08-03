################################################################################
# File Name: soc_calibration.py
# Purpose/Description: The cold-start-guarded MAX17048 register SoC%% reader --
#                      ONE definition shared by every drain-event writer.  Moved
#                      here from scripts/record_drain_test.py in US-526: the
#                      production drain writer (src/pi/power/drain_event_writer)
#                      must reuse the SAME guard the manual CLI uses, and a
#                      src/ module must never import from scripts/.  The CLI now
#                      imports these names, so there is one implementation with
#                      two callers (SSOT design directive), not a copy that can
#                      drift.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex (US-526) | Extracted verbatim from record_drain_test.py
#                               (US-427 / US-431 behaviour preserved) with ONE
#                               deliberate widening: the register read now
#                               catches Exception rather than UpsMonitorError
#                               alone.  Rationale is load-bearing, not tidiness
#                               -- UpsMonitor is imported BOTH as
#                               `pi.hardware.ups_monitor` (record_drain_test,
#                               orchestrator) and `src.pi.hardware.ups_monitor`
#                               (power_watch/__main__), so those are two
#                               distinct class objects and an
#                               `except UpsMonitorError` bound to one of them
#                               would NOT catch the other's instance.  On the
#                               shutdown path that miss would propagate out of
#                               a gauge read instead of recording NULL -- the
#                               cross-module identity trap that cost the
#                               9-drain saga.  Catching Exception is identity-
#                               independent and matches the honest-instrument
#                               contract (unreadable gauge -> NULL, never a
#                               guessed number, never a crash).
# ================================================================================
################################################################################

"""Cold-start-guarded MAX17048 State-of-Charge reads (US-427 / US-431 / US-234).

The MAX17048 ModelGauge SoC register mis-reads by 30-40 points for the first few
minutes after a cold power-up -- the reason the shutdown ladder moved OFF SoC
onto VCELL in US-234.  Every writer that records ``*_soc_pct`` therefore routes
its read through :func:`readCalibratedRegisterSocPct`, which returns ``None``
(record NULL) rather than a garbage percent whenever the gauge is -- or may be
-- still calibrating.

VCELL is NOT guarded here: cell voltage is trustworthy immediately at power-up.
Only the modelled SoC%% needs the window.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    'COLD_START_CALIBRATION_WINDOW_SECONDS',
    'readCalibratedRegisterSocPct',
    'readSystemUptimeSeconds',
    'resolveColdStartWindowSeconds',
]


# US-427 (BL-015 / US-234): a register read taken within this many seconds of
# power-up is treated as uncalibrated and recorded as NULL rather than a garbage
# percent (Atlas BL-015 cold-start ruling, CIO-ratified 2026-07-01; consistent
# with the US-264 SOC-uncalibrated rule).
#
# US-431 (F-048): this is the FALLBACK default only.  The live window is read
# from config (pi.hardware.upsMonitor.socColdStartWindowSeconds) via
# resolveColdStartWindowSeconds, so the value measured by
# scripts/calibrate_max17048.py on the rig feeds the guard directly -- real data
# replacing this guessed constant.
COLD_START_CALIBRATION_WINDOW_SECONDS: float = 180.0


def readSystemUptimeSeconds() -> float | None:
    """Return seconds since power-up from ``/proc/uptime``, or None.

    The MAX17048 fuel gauge starts calibrating when the rig powers up, so system
    uptime is the available proxy for "how long has the gauge had to settle."
    Returns ``None`` off-Linux or if the file is unreadable -- the caller treats
    an unknowable uptime as uncalibrated (no number).

    Returns:
        Seconds since boot, or ``None`` when it cannot be determined.
    """
    try:
        with open('/proc/uptime', encoding='utf-8') as fh:
            return float(fh.readline().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def resolveColdStartWindowSeconds(config: dict[str, Any]) -> float:
    """Return the cold-start guard window from config, or the fallback constant.

    US-431 (F-048): the window is measured on the UPS-drain rig by
    ``scripts/calibrate_max17048.py`` and written to
    ``pi.hardware.upsMonitor.socColdStartWindowSeconds``.  A missing or
    malformed key falls back to :data:`COLD_START_CALIBRATION_WINDOW_SECONDS`
    so an older config still guards conservatively rather than crashing.

    Args:
        config: A validated (or partial) config mapping.

    Returns:
        The window in seconds.
    """
    try:
        value = config['pi']['hardware']['upsMonitor']['socColdStartWindowSeconds']
    except (KeyError, TypeError):
        return COLD_START_CALIBRATION_WINDOW_SECONDS
    try:
        return float(value)
    except (TypeError, ValueError):
        return COLD_START_CALIBRATION_WINDOW_SECONDS


def readCalibratedRegisterSocPct(
    monitor: Any,
    *,
    uptimeSeconds: float | None,
    calibrationWindowSeconds: float = COLD_START_CALIBRATION_WINDOW_SECONDS,
) -> int | None:
    """Read the MAX17048 register SoC%%, guarded against the cold-start window.

    Honest-instrument (US-234 / BL-015): if the gauge is still inside its
    ~3-min calibration window -- or the uptime that would prove it is past the
    window cannot be determined -- the register value is garbage, so this
    returns ``None`` (records NULL) WITHOUT reading the register.  A read
    failure (hardware absent / I2C error) also yields ``None`` rather than
    propagating, so a drain recorded on a dev box (or with a dead gauge on the
    shutdown path) records NULL, not a crash.

    Args:
        monitor: A ``UpsMonitor``-like object exposing
            ``getBatteryPercentage() -> int``.
        uptimeSeconds: Seconds since power-up (see
            :func:`readSystemUptimeSeconds`), or ``None`` when unknowable.
        calibrationWindowSeconds: The cold-start window; reads inside it are
            suppressed.  Defaults to
            :data:`COLD_START_CALIBRATION_WINDOW_SECONDS`.

    Returns:
        The register State-of-Charge percent (0-100), or ``None`` when the gauge
        is (or may be) uncalibrated or the read fails.
    """
    if uptimeSeconds is None or uptimeSeconds < calibrationWindowSeconds:
        logger.warning(
            "register SoC%% suppressed -> NULL: fuel gauge within the "
            "~%.0fs cold-start calibration window (uptime=%s); "
            "honest-instrument, no garbage percent (US-234).",
            calibrationWindowSeconds, uptimeSeconds,
        )
        return None
    try:
        return int(monitor.getBatteryPercentage())
    except Exception as exc:  # noqa: BLE001 -- see header: identity-independent
        logger.warning(
            "register SoC%% read failed -> NULL: %s", exc,
        )
        return None
