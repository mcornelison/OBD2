################################################################################
# File Name: capture_health.py
# Purpose/Description: US-688 (F-138) -- the CONSUMER for the capture-health
#                      signal US-302 has been logging since 2026-05-08 and
#                      which nothing has ever read. Decides whether the data
#                      logger has gone silent while the car is powered, and
#                      publishes that verdict to `states/capture-health` for the
#                      dashboard's System Status card.
#
#                      Follows the F-092/097/111 card-emitter house shape: a
#                      pure `build...State` that owns the payload contract, and
#                      a `make...Emitter` factory returning a best-effort emit
#                      callable that writes atomically and NEVER raises.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-08    | Rex (US-688) | Initial -- capture-health decision + emitter.
# ================================================================================
################################################################################

"""Publish whether data capture has gone silent (US-688).

THE INCIDENT.  On 2026-09-04 a dongle worked loose after a shop visit.  Drive 68
ended abruptly, 41 reconnect attempts failed, and the Pi wrote zero rows.  It
logged ``data_logger_last_row_seconds_ago=never_written`` every 60 seconds for
TWO DAYS and no surface consumed it; the outage was found by a human looking at
a dongle, and the second code was found a day later by a database query.  The
signal existed.  The consumer did not.  That is what this module is.

🔴 WHY THE GATE IS THE POWER SOURCE AND NOT THE ENGINE.

The obvious gate is "only alert while the engine is running", and every
engine-running signal this system owns arrives over the OBDLink Bluetooth
transport: RPM (PID ``0x0C``), the alternator-voltage escalation
(``engineOnVoltageThreshold``, PID ``0x42``), and drive detection, which is
derived from both.  THAT IS THE TRANSPORT WHOSE FAILURE IS THE INCIDENT.  Gated
on any of them, this alert goes quiet at precisely the instant capture dies --
a dead branch, and the second time this sprint the natural phrasing of a gate
would have shipped one (US-687-a: ``RPM >= 900`` and ``speed missing``).

So the gate is ``powerSource``, sensed on the X1209 GPIO6 PLD line by
``PowerSourceProvider`` -- a DIFFERENT transport, which a loose dongle does not
touch.  ``external`` means the Pi is drawing from the car's fuse box, which is
live only with the key on; ``battery`` means that supply is gone and the UPS is
running the Pi down toward a graceful poweroff.

WHAT ``stalled`` THEREFORE CLAIMS, stated honestly: *the Pi is on the car's
power and no row has been written for longer than the stall window*.  It does
NOT claim the engine is turning.  Key-on-engine-off is inside the alerting
state, and that is a deliberate over-claim in the SAFE direction -- rows ought
to be landing there too, so an alert is not a false one.  A bench Pi on wall
power also reads ``external``; see ``DEFAULT_STALL_SECONDS`` for why that is
bounded rather than free.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "CAPTURE_HEALTH_FILENAME",
    "DEFAULT_STALL_SECONDS",
    "REASON_LOGGER_ABSENT",
    "REASON_NEVER_WRITTEN",
    "REASON_STALLED",
    "REASON_UNREADABLE",
    "STATE_IDLE",
    "STATE_OK",
    "STATE_STALLED",
    "STATE_UNKNOWN",
    "buildCaptureHealthState",
    "makeCaptureHealthEmitter",
]

logger = logging.getLogger("pi.obdii.capture_health")

# The state name the carousel fetches: GET /capture-health.
CAPTURE_HEALTH_FILENAME = "capture-health"

# Matches every other card emitter's `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# ---------------------------------------------------------------- vocabulary

#: Rows are landing inside the stall window, on car power.
STATE_OK = "ok"
#: THE ALERT. On car power, and nothing has been written for too long.
STATE_STALLED = "stalled"
#: The car's power is gone (key off). Absence of data here is EXPECTED, not a
#: fault -- an alert that fired on every key-off would be ignored within a week.
STATE_IDLE = "idle"
#: We cannot tell. Blocks a green all-clear WITHOUT raising an alarm -- the
#: dashboard's existing word for a known-unknown.
STATE_UNKNOWN = "unknown"

#: The logger exists and has written no row since the process started. This is a
#: MEASUREMENT, and it is the literal state the Pi logged for two days.
REASON_NEVER_WRITTEN = "never_written"
#: No data logger is wired into this orchestrator at all. An ABSENCE, and a
#: DIFFERENT fact from ``never_written`` -- US-302's reader returns ``None`` for
#: both, which is why the reason has to travel separately from the value.
REASON_LOGGER_ABSENT = "logger_absent"
#: The freshness property could not be read. A fault in the Pi, not a claim
#: about capture, and the two have different fixes.
REASON_UNREADABLE = "unreadable"
#: Rows were written once, and the newest is older than the stall window.
REASON_STALLED = "stalled"

#: The two power readings that are MEASUREMENTS. Anything else is an absence.
#: Stated as the resolved set rather than as ``!= "unknown"`` so a future source
#: value cannot quietly acquire a verdict by not being spelled ``unknown``
#: (the idiom ``system_status_emitter.RESOLVED_POWER_SOURCES`` already uses).
_POWER_EXTERNAL = "external"
_POWER_BATTERY = "battery"
_RESOLVED_POWER_SOURCES = frozenset({_POWER_EXTERNAL, _POWER_BATTERY})

# ⚠️ TUNING VALUE -- NOT RATIFIED BY SPOOL. Spool owns every tuning number on
# this project (PM Rule 7); this default is DERIVED, not invented, and the
# derivation is written down here so it can be checked rather than re-guessed.
# It is filed for ratification in offices/pm/inbox/.
#
# FLOOR, from two independent measurements, both already on file:
#   * 13 s -- the worst in-drive RPM inter-sample gap across drives 64-68
#     (2,141 samples, US-687-b). Capture legitimately goes quiet for that long
#     while the car is moving, so anything at or under it nuisance-fires.
#   * 30 s -- `pi.obdii.orchestrator.initialConnectTimeoutSec`. A Pi that has
#     just booted has legitimately written nothing while it connects, and an
#     alert during every startup is an alert nobody reads.
# 60 s clears the larger floor by 2x and the smaller by ~4.6x.
#
# CEILING: soft, and generous. The outage this story reports lasted TWO DAYS,
# so any value in minutes still catches it. The cost of a larger value is only
# how long the operator drives uninformed; the cost of a smaller one is a false
# alarm, which is permanent (an alert that has cried wolf is off forever).
# 60 s is therefore biased toward the recoverable error.
DEFAULT_STALL_SECONDS = 60.0


def buildCaptureHealthState(
    *,
    lastRowSecondsAgo: float | None,
    freshnessReason: str | None,
    powerSource: str,
    stallSeconds: float,
    nowIso: str,
) -> dict[str, Any]:
    """Decide capture health (pure).

    🔴 THE PARAMETER LIST IS PART OF THE SPECIFICATION. There is deliberately no
    ``rpm``, ``linkState``, ``driveState`` or ``engineRunning`` argument here.
    Every one of those arrives over the OBD transport whose failure this alert
    exists to report, so consulting one would make the alert unable to fire in
    its own motivating incident. ``tests/pi/obdii/test_capture_health.py``
    asserts on this signature for exactly that reason.

    Args:
        lastRowSecondsAgo: Seconds since the data logger last wrote a row, or
            ``None`` when there is no such reading. ``None`` is NEVER coerced to
            ``0`` on the way out -- "a row landed just now" is the most
            reassuring value this field can take and the exact opposite of the
            truth it would be standing in for.
        freshnessReason: Why ``lastRowSecondsAgo`` is ``None`` -- one of
            :data:`REASON_NEVER_WRITTEN` / :data:`REASON_LOGGER_ABSENT` /
            :data:`REASON_UNREADABLE`. Carried separately from the value because
            US-302's reader collapses a MEASUREMENT (the logger has written
            nothing) and an ABSENCE (there is no logger) into the same ``None``,
            and only the first is a capture fault.
        powerSource: ``external`` / ``battery`` / ``unknown`` from
            ``card_state_emitter._gatherPowerSource`` -- the ONE authoritative
            acquisition for the AC-vs-battery fact (US-502). Never re-read here:
            a second path could disagree with GPIO6.
        stallSeconds: The stall window. A parameter, never a module constant
            read from inside -- see :data:`DEFAULT_STALL_SECONDS`.
        nowIso: ISO-8601 emission timestamp (the freshness marker).

    Returns:
        ``{"state", "lastRowSecondsAgo", "stallSeconds", "reason", "ts"}``.
    """
    state, reason = _decide(
        lastRowSecondsAgo=lastRowSecondsAgo,
        freshnessReason=freshnessReason,
        powerSource=powerSource,
        stallSeconds=stallSeconds,
    )
    return {
        "state": state,
        "lastRowSecondsAgo": lastRowSecondsAgo,
        "stallSeconds": stallSeconds,
        "reason": reason,
        "ts": nowIso,
    }


def _decide(
    *,
    lastRowSecondsAgo: float | None,
    freshnessReason: str | None,
    powerSource: str,
    stallSeconds: float,
) -> tuple[str, str | None]:
    """The decision, in the order the guards must run.

    GUARD ORDER IS THE SPECIFICATION here exactly as it is in
    ``gear_derivation.update()``. The power gate runs FIRST because it decides
    whether a silence is a fault at all; running it after the freshness checks
    would report a stall on a Pi that is simply switched off.
    """
    # 1. UNRESOLVED POWER -> we cannot say. Before everything, because an
    #    unreadable gate must yield neither an alarm nor an all-clear.
    if powerSource not in _RESOLVED_POWER_SOURCES:
        return (STATE_UNKNOWN, freshnessReason)

    # 2. THE KEY IS OFF. Expected absence, never a fault. The story's stated
    #    negative case, and the one that keeps this alert worth listening to.
    if powerSource == _POWER_BATTERY:
        return (STATE_IDLE, None)

    # --- on car power from here: rows OUGHT to be landing -------------------

    # 3. NO READING, and the reason decides whether that is a fault. Only
    #    `never_written` is a measurement of capture; the other two are facts
    #    about the instrument and must not raise a capture alarm.
    if lastRowSecondsAgo is None:
        if freshnessReason == REASON_NEVER_WRITTEN:
            return (STATE_STALLED, REASON_NEVER_WRITTEN)
        return (STATE_UNKNOWN, freshnessReason)

    # 4. A real age, judged against the window.
    if lastRowSecondsAgo > stallSeconds:
        return (STATE_STALLED, REASON_STALLED)
    return (STATE_OK, None)


def makeCaptureHealthEmitter(
    statesDir: str,
    *,
    nowIsoFn: Callable[[], str] | None = None,
) -> Callable[..., None]:
    """Build the ``states/capture-health`` emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        The emit callable. Best-effort by contract: a write failure is logged
        but NEVER raised, so the dashboard hook can never block the
        orchestrator's poll loop.
    """
    from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, CAPTURE_HEALTH_FILENAME)

    def emit(
        *,
        lastRowSecondsAgo: float | None,
        freshnessReason: str | None,
        powerSource: str,
        stallSeconds: float,
    ) -> None:
        try:
            payload = buildCaptureHealthState(
                lastRowSecondsAgo=lastRowSecondsAgo,
                freshnessReason=freshnessReason,
                powerSource=powerSource,
                stallSeconds=stallSeconds,
                nowIso=nowFn(),
            )
            ensureStatesDir(statesDir)
            writeStateAtomic(target, payload)
        except Exception as exc:  # noqa: BLE001 -- best-effort, never block
            logger.error(
                "states/capture-health write failed (%s) -- ignored", exc
            )

    return emit
