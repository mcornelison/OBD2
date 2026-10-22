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
# 2026-09-13    | Ralph (Rex)  | US-728: add the always-present `priorShutdown`
#               |              | block (startup_log verdict, transported verbatim).
# 2026-10-14    | Rex (US-901-b)| add the always-present `runMode` (live /
#               |              | simulate / replay) and its deriveRunMode rule.
# 2026-10-14    | Rex (US-880-a)| drive block gains the always-present
#               |              | distanceKm / distanceSinceTs (speed integrator).
# 2026-10-18    | Rex (US-896-b)| drive block gains the always-present elapsedSec
#               |              | (frozen at drive end) and distancePartial.
# 2026-10-22    | Rex (US-876-c)| the always-present link {bt, adapter, ecu}
#               |              | block (Atlas L6/X1) and the shared per-layer
#               |              | state function + tracker (Atlas L1/L5, G1).
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

# US-901-b run modes: is the panel showing the live car? Published as
# `runMode`, NOT `mode` -- `mode` collides with pi.power.mode, and US-668
# removed a `mode` field from this payload once already.
#   live     = the real car (production).
#   simulate = the run was started with --simulate.
#   replay   = pi.replay.active: a recorded drive is being replayed.
RUN_MODE_LIVE = "live"
RUN_MODE_SIMULATE = "simulate"
RUN_MODE_REPLAY = "replay"

# US-876-c link-chain layer states (Atlas L1, exact). A DIFFERENT vocabulary
# from obdLink's, which ships unchanged until S110 retires it with the page.
#   up         = the latest observation of the layer was positive.
#   connecting = not up, and never up this session (neutral, not counted).
#   retrying   = not up, but up earlier this session (counted).
#   down       = not up and NO retry authority exists (RE-HUNT C2).
#   null       = not read.
# "This session" is this process (L5): a restart is null until re-observed.
LINK_UP = "up"
LINK_CONNECTING = "connecting"
LINK_RETRYING = "retrying"
LINK_DOWN = "down"

# The three layers, chain order (L6), and every layer's keys (X1).
LINK_LAYERS: tuple[str, ...] = ("bt", "adapter", "ecu")
LINK_LAYER_KEYS: tuple[str, ...] = ("state", "ts", "lastOkTs")

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "LINK_CONNECTING",
    "LINK_DOWN",
    "LINK_LAYERS",
    "LINK_LAYER_KEYS",
    "LINK_RETRYING",
    "LINK_UP",
    "OBD_DOWN",
    "OBD_LINKED",
    "OBD_RECONNECTING",
    "RUN_MODE_LIVE",
    "RUN_MODE_REPLAY",
    "RUN_MODE_SIMULATE",
    "SYSTEM_STATUS_FILENAME",
    "LinkLayerTracker",
    "buildSystemStatusState",
    "deriveElapsedSec",
    "deriveLinkLayerState",
    "deriveRunMode",
    "unreadLinkLayer",
    "isSyncStaleWhileDriving",
    "makeSystemStatusEmitter",
]


def deriveRunMode(*, replayActive: bool, simulate: bool) -> str:
    """Resolve the US-901-b run mode from the replay and --simulate flags.

    Replay wins: US-857 replays through the --simulate seam, so a replay run
    usually has both flags set, and it must still read as a replay (Atlas
    ruling 2026-10-13 on Iris S-2).

    Args:
        replayActive: ``pi.replay.active`` as configured.
        simulate: Whether the orchestrator was started with --simulate.

    Returns:
        ``RUN_MODE_REPLAY``, else ``RUN_MODE_SIMULATE``, else ``RUN_MODE_LIVE``.
    """
    if replayActive:
        return RUN_MODE_REPLAY
    if simulate:
        return RUN_MODE_SIMULATE
    return RUN_MODE_LIVE


def deriveElapsedSec(
    sinceTs: str | None, endTs: str | None, nowIso: str
) -> int | None:
    """Resolve the US-896-b drive.elapsedSec (Atlas S105 Q2/G2), once, here.

    The window is the distance's own: it starts at ``distanceSinceTs``, so
    "12.4 mi over 0:23" is one window. It ends at the drive-end mark when the
    drive has ended (frozen: parked time is not drive time), else at the
    publish instant. The page formats it and does no time arithmetic.

    Args:
        sinceTs: ``drive.distanceSinceTs`` (canonical UTC), or None.
        endTs: The drive-end mark (canonical UTC), or None while the window is
            open.
        nowIso: The publish instant (the payload's ``ts``).

    Returns:
        Whole seconds, or None when there is no since-point, a timestamp does
        not parse, or the end precedes the since-point -- a negative span is
        two clocks disagreeing, not a duration.
    """
    if sinceTs is None:
        return None
    try:
        since = datetime.strptime(sinceTs, _ISO_FMT)
        until = datetime.strptime(endTs if endTs is not None else nowIso, _ISO_FMT)
    except (ValueError, TypeError):
        return None
    seconds = (until - since).total_seconds()
    return int(seconds) if seconds >= 0 else None


def unreadLinkLayer() -> dict[str, str | None]:
    """A link layer that was not read: every key present, every value null (X1)."""
    return dict.fromkeys(LINK_LAYER_KEYS)


def deriveLinkLayerState(
    *,
    observedUp: bool | None,
    upEarlierThisSession: bool,
    retryAuthority: bool,
) -> str | None:
    """Resolve ONE link layer's state (Atlas L1, exact; RE-HUNT C2).

    The shared rule every layer uses -- the ECU here (US-876-c), the adapter
    and BT layers through the same call (US-876-d/e). The page compares
    nothing; this is where the state is decided.

    Args:
        observedUp: The layer's latest observation -- True up, False not up,
            None not read (could not determine, or no source to read).
        upEarlierThisSession: Whether the layer was up earlier this process.
            For bt/adapter that means up WHILE the ECU was up (G1); the caller
            owns that flag (:class:`LinkLayerTracker`).
        retryAuthority: Whether anything exists that will try the layer again.

    Returns:
        ``LINK_UP`` / ``LINK_CONNECTING`` / ``LINK_RETRYING`` / ``LINK_DOWN``,
        or None when the layer is not read and was never up. A layer that was
        up and now cannot be read is retrying: it WAS there, and an unread
        instant is not evidence it is gone.
    """
    if observedUp is None:
        return LINK_RETRYING if upEarlierThisSession else None
    if observedUp:
        return LINK_UP
    if not retryAuthority:
        return LINK_DOWN
    return LINK_RETRYING if upEarlierThisSession else LINK_CONNECTING


class LinkLayerTracker:
    """One link layer's memory for THIS session (Atlas L1/L5, G1, X1, c-6).

    Holds what a single observation cannot carry: whether the layer was up
    earlier this session -- set on the first up and never cleared, because a
    reconnect resets the producer's observation (the ECU's generation bump
    returns reachability to NOT_YET_ATTEMPTED) -- plus the published state's
    transition time and the last time the layer was up. Owned by the
    orchestrator side, one per layer; US-876-d/e feed bt/adapter through the
    same class, which is their production caller.
    """

    def __init__(self) -> None:
        self._upEarlier = False
        self._state: str | None = None
        self._ts: str | None = None
        self._lastOkTs: str | None = None

    def observe(
        self,
        *,
        observedUp: bool | None,
        observedTs: str | None,
        nowTs: str,
        noAuthoritySinceTs: str | None = None,
        chainComplete: bool = True,
        lastOkTs: str | None = None,
    ) -> dict[str, str | None]:
        """Fold one observation in and return the layer's published block.

        Args:
            observedUp: True up / False not up / None not read.
            observedTs: Canonical-UTC event time of the observation's own last
                change (the producer's transition stamp), or None if it has
                none.
            nowTs: The publish instant (canonical UTC) -- used only where no
                event time exists.
            noAuthoritySinceTs: None while a retry authority exists; else the
                canonical-UTC instant since which none has (the layer may be
                down).
            chainComplete: Whether this up counts as "up this session". Always
                True for the ECU; for bt/adapter, whether link.ecu is up (G1).
            lastOkTs: The producer's own last-up instant, when it has one.

        Returns:
            ``{"state", "ts", "lastOkTs"}`` -- all three null when not read.
        """
        state = deriveLinkLayerState(
            observedUp=observedUp,
            upEarlierThisSession=self._upEarlier,
            retryAuthority=noAuthoritySinceTs is None,
        )
        if state == LINK_UP:
            if chainComplete:
                self._upEarlier = True
            self._lastOkTs = lastOkTs or nowTs
        if state != self._state:
            self._ts = self._transitionTs(state, observedTs, nowTs, noAuthoritySinceTs)
            self._state = state
        if state is None:
            return unreadLinkLayer()
        return {"state": state, "ts": self._ts, "lastOkTs": self._lastOkTs}

    def _transitionTs(
        self,
        state: str | None,
        observedTs: str | None,
        nowTs: str,
        noAuthoritySinceTs: str | None,
    ) -> str | None:
        """The event time of a change INTO ``state`` (c-6: never the tick if known).

        Down begins when its two conditions are both true: the later of the
        observation's change and the authority's departure. Otherwise an
        observation newer than the current state is the cause; an older one
        is not (the change came from the authority side, seen now).
        """
        if state is None:
            return None
        if state == LINK_DOWN:
            causes = [t for t in (observedTs, noAuthoritySinceTs) if t is not None]
            return max(causes) if causes else nowTs
        # Canonical UTC strings order as the instants they name.
        if observedTs is not None and (self._ts is None or observedTs > self._ts):
            return observedTs
        return nowTs


def _publishLinkChain(link: dict | None) -> dict[str, dict[str, str | None]]:
    """Normalise a caller's chain to the L6 shape: every layer, every key.

    A missing layer is not read; a layer whose state is null is not read in
    all three keys, whatever was passed beside it (available = state != null).
    """
    chain = link or {}
    published: dict[str, dict[str, str | None]] = {}
    for layer in LINK_LAYERS:
        block = chain.get(layer) or {}
        if block.get("state") is None:
            published[layer] = unreadLinkLayer()
        else:
            published[layer] = {key: block.get(key) for key in LINK_LAYER_KEYS}
    return published


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
    priorShutdown: dict | None = None,
    runMode: str = RUN_MODE_LIVE,
    distanceKm: float | None = None,
    distanceSinceTs: str | None = None,
    distanceEndTs: str | None = None,
    distancePartial: bool | None = None,
    link: dict | None = None,
) -> dict:
    """Assemble the system-status payload (pure; spec §7 pinned A-3 schema).

    Args:
        obdLinkState: One of ``OBD_LINKED`` / ``OBD_RECONNECTING`` / ``OBD_DOWN``.
        obdRetries: Reconnect attempt count for the current drop (0 when linked).
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
        priorShutdown: The US-728 prior-shutdown block from
            :meth:`pi.diagnostics.prior_shutdown_summary.PriorShutdownSummary.toStatePayload`,
            or None when ``startup_log`` could not be read. Transported verbatim.
        runMode: The US-901-b run mode from :func:`deriveRunMode`. Defaults to
            ``RUN_MODE_LIVE``, which is what the production orchestrator
            resolves to with every replay/simulate flag at its default.
        distanceKm: US-880-a: this drive's distance from the ONE speed
            integrator, unrounded (the page formats), or None when nothing was
            integrated this process. Transported verbatim.
        distanceSinceTs: US-880-a: the event ts the distance counts from -- the
            drive start's, or the first integrated SPEED reading's after a
            mid-drive process start -- or None. Transported verbatim.
        distanceEndTs: US-896-b: the drive-end mark (canonical UTC) that
            freezes ``elapsedSec``, or None while the window is open. Not
            published itself; see :func:`deriveElapsedSec`.
        distancePartial: US-896-b (Atlas B-1(b)): True when the window starts
            at the first SPEED reading after a mid-drive restart, False when it
            starts at a drive start. Published only beside a non-null
            ``distanceSinceTs``; null otherwise (nothing to qualify).
        link: US-876-c: the link chain ``{bt, adapter, ecu}``, each
            ``{state, ts, lastOkTs}`` as :class:`LinkLayerTracker` publishes
            it. Normalised to every layer and key; a missing layer or a null
            state is all three null. NEVER blanked by ``obdAvailable`` -- that
            blanking is the ARCH-061 grey this block replaces.

    Returns:
        The system-status dict with exactly the spec §7 A-3 keys plus the US-429
        ``source`` block (one availability truth per source) and the US-480-a
        ``idle`` boolean (the idle-SSOT the display consumes, never re-derives).
    """
    # US-429 honest-availability: the OBD source owns the obdLink tile. When the
    # source is unavailable, its value is a fresh typed NULL (never the last real
    # state left stale) and the reason travels in `source.obd`.
    if obdAvailable:
        obdLink = {"state": obdLinkState, "retries": obdRetries}
    else:
        obdLink = {"state": None, "retries": 0}
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
        # US-876-c (Atlas L6): always a key, every layer always present, and
        # deliberately NOT gated on obdAvailable like obdLink above.
        "link": _publishLinkChain(link),
        # `lastDrive` is ALWAYS present as a key (null when unknown) rather than
        # sometimes-absent: an intermittently-missing key is the shape that lets
        # a renderer quietly fall through to the wrong branch, and a stable
        # schema is what the display can actually be tested against.
        "drive": {
            "state": driveState,
            "driveId": driveId,
            "lastDrive": lastDrive,
            # US-880-a: always keys (null = nothing integrated this process),
            # for the same reason as `lastDrive`.
            "distanceKm": distanceKm,
            "distanceSinceTs": distanceSinceTs,
            # US-896-b: always keys, null with no distanceSinceTs. Same name
            # and polarity as states/engine-history.partial.
            "elapsedSec": deriveElapsedSec(distanceSinceTs, distanceEndTs, nowIso),
            "distancePartial": distancePartial if distanceSinceTs is not None else None,
        },
        "idle": idle,
        # US-728: always a key (null = not read), same reason as `lastDrive`.
        # A different fact from NO RECORD, which arrives as a block.
        "priorShutdown": priorShutdown,
        # US-901-b: always a key. The dashboard raises its not-live marker on
        # any value other than `live`.
        "runMode": runMode,
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
        priorShutdown: dict | None = None,
        runMode: str = RUN_MODE_LIVE,
        distanceKm: float | None = None,
        distanceSinceTs: str | None = None,
        distanceEndTs: str | None = None,
        distancePartial: bool | None = None,
        link: dict | None = None,
    ) -> None:
        try:
            nowIso = nowFn()
            syncStale = isSyncStaleWhileDriving(
                driveState, syncLastOkTs, nowIso, thresholdS=syncStaleThresholdS
            )
            payload = buildSystemStatusState(
                obdLinkState=obdLinkState,
                obdRetries=obdRetries,
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
                priorShutdown=priorShutdown,
                runMode=runMode,
                distanceKm=distanceKm,
                distanceSinceTs=distanceSinceTs,
                distanceEndTs=distanceEndTs,
                distancePartial=distancePartial,
                link=link,
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
