################################################################################
# File Name: system_status_emitter.py
# Purpose/Description: F-092 system-status emitter [Atlas A-3]. The schema +
#   best-effort writer for the `system-status` SSOT that the carousel dashboard
#   System Status card consumes. The orchestrator/sync tier OWNS this emitter
#   (it holds the live BT-link + sync-log + drive state, A-3); it calls the
#   injected `emit(...)` callable -- the dashboard renders what this file says,
#   it never decides or polls hardware (specs/ssot-design-pattern.md). Honest-
#   instrument by contract: a down/reconnecting link is reported verbatim, never
#   fabricated as `linked`, and the stale-while-driving policy (I-033 / I-4) is
#   computed here so a stale sync surfaces amber instead of green-when-broken.
#   Schema pinned in docs/superpowers/specs/2026-06-05-pi-touch-carousel-
#   dashboard-f092-f097-design.md §7 (state file shapes).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-400 system-status card)
# 2026-07-21    | Ralph (Rex)  | US-480-a: add the idle-SSOT `idle` boolean (Atlas
#               |              | ruling b) -- the emitter owns the idle decision.
# ================================================================================
################################################################################

"""System-status schema builder + the best-effort emit factory (Atlas A-3)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

# US-429 honest-availability: one source-availability truth per source (SSOT).
from pi.splash.source_availability import (
    REASON_OBD_OFF,
    SOURCE_OBD,
    buildSourceState,
)

logger = logging.getLogger(__name__)

# The single SSOT slot the carousel System Status card polls (4 Hz tmpfs read).
SYSTEM_STATUS_FILENAME = "system-status"

# OBD-link states (consumer-side view of the orchestrator's connection state).
#   linked       = an OBD read succeeded recently -> green.
#   reconnecting = the link dropped + the reconnect loop is retrying -> amber
#                  (I-033 visibility: the operator SEES the reconnect attempt).
#   down         = no link + not (yet) recovering -> red.
OBD_LINKED = "linked"
OBD_RECONNECTING = "reconnecting"
OBD_DOWN = "down"

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "OBD_DOWN",
    "OBD_LINKED",
    "OBD_RECONNECTING",
    "SYSTEM_STATUS_FILENAME",
    "buildSystemStatusState",
    "isSyncStaleWhileDriving",
    "makeSystemStatusEmitter",
]


def buildSystemStatusState(
    *,
    obdLinkState: str,
    obdRetries: int,
    obdLastSeenS: int | None,
    syncLastOkTs: str | None,
    syncRows: int,
    syncPending: int,
    syncStale: bool,
    powerMode: str,
    powerSource: str,
    driveState: str,
    driveId: int | None,
    nowIso: str,
    obdAvailable: bool = True,
    obdUnavailableReason: str | None = None,
    lastDrive: dict | None = None,
) -> dict:
    """Assemble the system-status payload (pure; spec §7 pinned A-3 schema).

    Args:
        obdLinkState: One of ``OBD_LINKED`` / ``OBD_RECONNECTING`` / ``OBD_DOWN``.
        obdRetries: Reconnect attempt count for the current drop (0 when linked).
        obdLastSeenS: Seconds since the last successful OBD read (None if never).
        syncLastOkTs: ISO-8601 instant of the last successful Pi->server sync.
        syncRows: Rows synced in the last successful batch.
        syncPending: Rows captured but not yet synced.
        syncStale: Whether the last sync is stale-while-driving (caller policy;
            see ``isSyncStaleWhileDriving``). The display renders amber when True.
        powerMode: ``car`` (in-car) or ``wall`` (bench/debug).
        powerSource: ``external`` (USB/car) or ``battery`` (running on the UPS).
        driveState: ``recording`` or ``idle``.
        driveId: Active drive ID when recording; None when idle.
        nowIso: ISO-8601 emission timestamp (freshness marker).
        obdAvailable: Whether the OBD source is present at all (US-429). False on
            wall power / car off -- the OBD-link tile then renders a typed NA, not
            a fabricated or stale link state. Defaults True (backward compatible).
        obdUnavailableReason: The typed-NA reason when ``obdAvailable`` is False
            (defaults to ``REASON_OBD_OFF``). Ignored when available.
        lastDrive: The US-505 last-COMPLETED-drive block
            (``{"driveId": int, "startedAtTs": str|None}``) from
            :func:`pi.obdii.last_drive_summary.readLastDriveSummary`, or None
            when no real drive is on record. A DIFFERENT fact from ``driveId``,
            which is the ACTIVE drive and stays null at idle -- merging the two
            would make a parked Pi read as recording. Transported verbatim: the
            emitter never reformats or re-derives the producer's fact.

    Returns:
        The system-status dict with exactly the spec §7 A-3 keys plus the US-429
        ``source`` block (one availability truth per source) and the US-480-a
        ``idle`` boolean (the idle-SSOT the display consumes, never re-derives).
    """
    # US-429 honest-availability: the OBD source owns the obdLink tile. When the
    # source is unavailable, its value is a fresh typed NULL (never the last real
    # state left stale) and the reason travels in `source.obd`.
    if obdAvailable:
        obdLink = {
            "state": obdLinkState,
            "retries": obdRetries,
            "lastSeenS": obdLastSeenS,
        }
    else:
        obdLink = {"state": None, "retries": 0, "lastSeenS": None}
    # US-480-a idle-SSOT (Atlas ruling b): the emitter OWNS the idle decision --
    # it holds BOTH inputs (obdAvailable + driveState), so the display renders
    # this flag and never re-derives idle from the drive-state string (the
    # replaced carousel.js:170 pattern). idle == the calm parked/asleep state:
    # the OBD source is ABSENT (no car) AND no drive is recording. It flips false
    # the moment the OBD source wakes OR a drive records (US-481 / Iris AC-4
    # auto-advance-off-idle).
    idle = (not obdAvailable) and (driveState != "recording")
    return {
        "obdLink": obdLink,
        "sync": {
            "lastOkTs": syncLastOkTs,
            "rows": syncRows,
            "pending": syncPending,
            "stale": syncStale,
        },
        "power": {"mode": powerMode, "source": powerSource},
        # `lastDrive` is ALWAYS present as a key (null when unknown) rather than
        # sometimes-absent: an intermittently-missing key is the shape that lets
        # a renderer quietly fall through to the wrong branch, and a stable
        # schema is what the display can actually be tested against.
        "drive": {
            "state": driveState,
            "driveId": driveId,
            "lastDrive": lastDrive,
        },
        "idle": idle,
        "source": {
            SOURCE_OBD: buildSourceState(
                obdAvailable, obdUnavailableReason or REASON_OBD_OFF
            )
        },
        "ts": nowIso,
    }


def isSyncStaleWhileDriving(
    driveState: str,
    syncLastOkTs: str | None,
    nowIso: str,
    *,
    thresholdS: float,
) -> bool:
    """Decide whether the last sync is stale *while a drive is recording*.

    The amber stale signal exists so the operator sees un-backed-up drive data
    (I-4 / the I-033 "did it capture my drive?" worry). It only applies while
    recording -- a parked Pi catches up on the next WiFi return, so idle is never
    flagged. When recording, an absent or unparseable last-sync is treated as
    stale (we never claim freshness we cannot prove -- no green-when-broken).

    Args:
        driveState: ``recording`` or ``idle``.
        syncLastOkTs: ISO-8601 instant of the last successful sync (or None).
        nowIso: ISO-8601 emission instant.
        thresholdS: Staleness threshold in seconds (Spool S-3 owns the value;
            supplied by config -- this module never hardcodes a tuning number).

    Returns:
        True if the sync should render amber, else False.
    """
    if driveState != "recording":
        return False
    if syncLastOkTs is None:
        return True
    try:
        lastOk = datetime.strptime(syncLastOkTs, _ISO_FMT).replace(tzinfo=UTC)
        now = datetime.strptime(nowIso, _ISO_FMT).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return True
    return (now - lastOk).total_seconds() > thresholdS


def makeSystemStatusEmitter(
    statesDir: str,
    *,
    syncStaleThresholdS: float,
    nowIsoFn: Callable[[], str] | None = None,
) -> Callable[..., None]:
    """Build the system-status emit callable owned by the orchestrator (A-3).

    The returned callable takes the live link / sync / power / drive readings,
    computes the stale-while-driving policy, and writes the system-status SSOT
    atomically. Best-effort by contract: a write failure is logged but NEVER
    raised, so the emit hook can never block the orchestrator's main loop.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        syncStaleThresholdS: Stale-while-driving threshold in seconds (Spool S-3;
            config-supplied -- no fabricated default).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        The emit callable.
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, SYSTEM_STATUS_FILENAME)

    def emit(
        *,
        obdLinkState: str,
        obdRetries: int,
        obdLastSeenS: int | None,
        syncLastOkTs: str | None,
        syncRows: int,
        syncPending: int,
        powerMode: str,
        powerSource: str,
        driveState: str,
        driveId: int | None,
        obdAvailable: bool = True,
        obdUnavailableReason: str | None = None,
        lastDrive: dict | None = None,
    ) -> None:
        try:
            nowIso = nowFn()
            syncStale = isSyncStaleWhileDriving(
                driveState, syncLastOkTs, nowIso, thresholdS=syncStaleThresholdS
            )
            payload = buildSystemStatusState(
                obdLinkState=obdLinkState,
                obdRetries=obdRetries,
                obdLastSeenS=obdLastSeenS,
                syncLastOkTs=syncLastOkTs,
                syncRows=syncRows,
                syncPending=syncPending,
                syncStale=syncStale,
                powerMode=powerMode,
                powerSource=powerSource,
                driveState=driveState,
                driveId=driveId,
                nowIso=nowIso,
                obdAvailable=obdAvailable,
                obdUnavailableReason=obdUnavailableReason,
                lastDrive=lastDrive,
            )
            ensureStatesDir(statesDir)
            writeStateAtomic(target, payload)
        except Exception as exc:  # noqa: BLE001 -- best-effort, never block the loop
            logger.error(
                "system-status emit failed (%s) -- ignored (the dashboard hook "
                "never blocks the orchestrator)",
                exc,
            )

    return emit
