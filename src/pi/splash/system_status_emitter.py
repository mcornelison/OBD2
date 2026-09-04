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
#   Schema pinned in $FLEET_SHARE/knowledge/superpowers/specs/2026-06-05-pi-touch-carousel-
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
# 2026-09-03    | Ralph (Rex)  | US-672: drop the invisible `or REASON_OBD_OFF`
#               |              | default -- an unexplained absence must not have
#               |              | a claim about the CAR filled in for it.
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
    SOURCE_OBD,
    SOURCE_WIFI,
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


# ARCH-007 -- WiFi band thresholds. Defaults MIRROR pi.network.wifi.* in
# config.json (the tuning SSOT); they are parameters, never magic numbers, per
# the Atlas ruling 2026-08-20 section 2.2.
DEFAULT_WEAK_RSSI_DBM: int = -70
DEFAULT_DOWN_RSSI_DBM: int = -90

REASON_WIFI_UNKNOWN = "wifi: not read"

# US-628 -- the two `power.source` readings that are MEASUREMENTS. Anything
# else is an absence, and an absence is what may carry a reason. Stated as the
# resolved set rather than as `== "unknown"` so a future source value cannot
# quietly acquire a reason by not being spelled `unknown`.
RESOLVED_POWER_SOURCES = frozenset({"external", "battery"})


def deriveWifiState(
    *,
    associated: bool | None,
    rssiDbm: int | None,
    weakRssiDbm: int = DEFAULT_WEAK_RSSI_DBM,
    downRssiDbm: int = DEFAULT_DOWN_RSSI_DBM,
) -> str | None:
    """Derive the WiFi band ONCE, here (Atlas ruling 2026-08-20 section 2.1).

    The glyph renders this verdict and applies no threshold of its own. Two
    rules for one fact disagree the first time either moves.

    Returns ``"up"`` / ``"weak"`` / ``"down"``, or ``None`` when the link cannot
    be READ.

    That last distinction is the whole point of the ruling (section 2.3):
    **``down`` is a MEASUREMENT** -- we looked, and there is no usable link.
    An unreadable interface is ``None``, never ``down``. Painting "no signal"
    when the truth is "we could not look" is a fabricated reading, and it is the
    exact defect class this project keeps finding.
    """
    if associated is None:
        return None            # could not read the interface at all
    if not associated:
        return "down"          # we looked: there is no link. A real measurement.
    if rssiDbm is None:
        return None            # associated, but ungradeable -- not "down"
    if rssiDbm <= downRssiDbm:
        return "down"
    if rssiDbm <= weakRssiDbm:
        return "weak"
    return "up"


def buildSystemStatusState(
    *,
    obdLinkState: str,
    obdRetries: int,
    obdLastSeenS: int | None,
    syncLastOkTs: str | None,
    syncRows: int,
    syncPending: int | None,
    syncStale: bool,
    powerSource: str,
    driveState: str,
    driveId: int | None,
    nowIso: str,
    powerSourceReason: str | None = None,
    obdAvailable: bool = True,
    obdUnavailableReason: str | None = None,
    lastDrive: dict | None = None,
    wifiAvailable: bool = False,
    wifiUnavailableReason: str | None = None,
    wifiSsid: str | None = None,
    wifiRssiDbm: int | None = None,
    wifiWeakRssiDbm: int = DEFAULT_WEAK_RSSI_DBM,
    wifiDownRssiDbm: int = DEFAULT_DOWN_RSSI_DBM,
) -> dict:
    """Assemble the system-status payload (pure; spec §7 pinned A-3 schema).

    Args:
        obdLinkState: One of ``OBD_LINKED`` / ``OBD_RECONNECTING`` / ``OBD_DOWN``.
        obdRetries: Reconnect attempt count for the current drop (0 when linked).
        obdLastSeenS: Seconds since the last successful OBD read (None if never).
        syncLastOkTs: ISO-8601 instant of the last successful Pi->server sync.
        syncRows: Rows synced in the last successful batch.
        syncPending: Rows captured but not yet synced, or None when no caller
            actually measures it (US-564). None is carried through to the display
            as a typed NA -- it must never be coerced to 0 here or below, because
            "0 pending" is an all-clear on data safety and an unmeasured
            all-clear is the exact defect class this project keeps finding.
        syncStale: Whether the last sync is stale-while-driving (caller policy;
            see ``isSyncStaleWhileDriving``). The display renders amber when True.
        powerSource: ``external`` (USB/car) or ``battery`` (running on the UPS),
            or ``unknown`` when the line could not be resolved.
        powerSourceReason: The US-628 typed reason for an UNRESOLVED source
            (``provider_absent`` / ``source_unreadable`` / ``read_failed`` --
            the vocabulary lives with the acquisition, in
            ``pi.obdii.orchestrator.card_state_emitter``). Published in
            ``power.reasons`` following the ``reasons.altitude: no_source``
            idiom. IGNORED beside a resolved source: a reason explains an
            absence, and one standing next to a real measurement would be a
            second, contradictory account of the same fact. None -- no reason
            offered -- publishes an empty map rather than a filled-in guess.
        driveState: ``recording`` or ``idle``.
        driveId: Active drive ID when recording; None when idle.
        nowIso: ISO-8601 emission timestamp (freshness marker).
        obdAvailable: Whether the OBD source is present at all (US-429). False on
            wall power / car off -- the OBD-link tile then renders a typed NA, not
            a fabricated or stale link state. Defaults True (backward compatible).
        obdUnavailableReason: The typed-NA reason when ``obdAvailable`` is False.
            Ignored when available. NO DEFAULT (US-672): an unsupplied reason
            falls through to ``buildSourceState``'s bare ``"unavailable"``, never
            to a claim about the car.
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
    # US-628 honest absence. `reasons` is ALWAYS present -- empty when the
    # source resolved -- for the reason stated below for `lastDrive`: a
    # sometimes-missing key is the shape a consumer falls quietly through.
    # Keyed by FIELD NAME so a second unresolvable power fact can be added
    # without a second container (imu_state_bridge's `reasons` map, same idea).
    powerReasons: dict[str, str] = {}
    if powerSource not in RESOLVED_POWER_SOURCES and powerSourceReason:
        powerReasons["source"] = powerSourceReason
    return {
        "obdLink": obdLink,
        "sync": {
            "lastOkTs": syncLastOkTs,
            "rows": syncRows,
            "pending": syncPending,
            "stale": syncStale,
        },
        # US-668 (CIO 2026-09-02): the operator-declared `mode` (car/wall) is
        # GONE. It was a fact the operator typed in so the screen could show it
        # back to them, and nothing else read it. `source` stays because it is
        # SENSED and answers the one power question the display cannot answer by
        # existing: am I on external power, or on the UPS battery?
        "power": {
            "source": powerSource,
            "reasons": powerReasons,
        },
        # ARCH-007 (Atlas ruling 2026-08-20). Defaults to UNAVAILABLE, not to a
        # cheerful "up": a caller that has not wired the provider must not
        # publish a link it never observed. And when unavailable, ssid/rssi are
        # forced null -- carrying the last-seen SSID would be a fabricated fact
        # about a link we cannot currently read.
        "wifi": {
            # DERIVED HERE, never passed in (ruling s2.1): one rule for one
            # fact. Association is inferred from the SSID -- if we have a
            # network name we are on a network.
            "state": deriveWifiState(
                associated=(wifiSsid is not None) if wifiAvailable else None,
                rssiDbm=wifiRssiDbm,
                weakRssiDbm=wifiWeakRssiDbm,
                downRssiDbm=wifiDownRssiDbm,
            ) if wifiAvailable else None,
            "ssid": wifiSsid if wifiAvailable else None,
            "rssiDbm": wifiRssiDbm if wifiAvailable else None,
        },
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
            # US-672: NO car-off fallback. This used to read
            # `obdUnavailableReason or REASON_OBD_OFF`, so a caller that
            # published an absence without saying why had "OBD: off" -- a claim
            # about the CAR -- filled in on its behalf, invisibly. The producer
            # supplies a real reason on every branch it can reach (pinned in
            # tests/ui/test_carousel_obd_link_typed_unknown.py); a caller that
            # does not now gets `buildSourceState`'s honest bare "unavailable"
            # instead of a guess about a car nobody asked about.
            SOURCE_OBD: buildSourceState(obdAvailable, obdUnavailableReason),
            SOURCE_WIFI: buildSourceState(
                wifiAvailable, wifiUnavailableReason or REASON_WIFI_UNKNOWN
            ),
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
        syncPending: int | None,
        powerSource: str,
        driveState: str,
        driveId: int | None,
        powerSourceReason: str | None = None,
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
                powerSource=powerSource,
                powerSourceReason=powerSourceReason,
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
