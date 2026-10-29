################################################################################
# File Name: alerts_arbiter.py
# Purpose/Description: US-897-b2 (F-127) states/alerts -- the one provider of
#                      the warnings page: what was assessed (sources), the icon,
#                      the ordered entries and the non-dismissable PULL OVER
#                      takeover. Fed the obd-live payload the card tick just
#                      published; its entries are the live coolant STOP, the
#                      battery WATCH and the over-rev WATCH (whose peak is fed
#                      per reading); the stored/pending codes come from the dtc
#                      payload the router hands in. Each STOP episode edge is
#                      INSERTed into alert_log.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-b2) | Initial -- arbiter, pure builder, emitter,
#                                coolant STOP episode, alert_log record, seed.
# 2026-10-20    | Rex (US-897-b3) | Battery WATCH: side words, value rounded
#                                toward the breach, ends after a 10 s green
#                                hold by reading time; seeded like coolant.
# 2026-10-20    | Rex (US-897-b4) | Over-rev WATCH: peak from EVERY RPM reading
#                                on the reading seam (own lock), '(sampled)'
#                                sentence, value/unit null; ends at drive end or
#                                after a no-drive green hold; drive start resets
#                                the peak; seeded like coolant.
# 2026-10-20    | Rex (US-897-b5) | CODE source: one entry per alertable code of
#                                the in-process dtc payload (never stop, UNRATED
#                                words, pending labelled), sources.code from
#                                checkedAtTs, codeAlert; removal only on a NEWER
#                                read (G1).
# 2026-10-20    | Rex (US-897-c) | buildAlertsState + the emit take acknowledgedIds
#                                (default empty: output unchanged): acknowledged
#                                true, an acked cleared entry removed (Q15), no
#                                pulse, codeAlert null once all its ids are acked.
# 2026-10-21    | Rex (US-897-d) | Battery value/last.value are the RAW reading;
#                                every entry carries `round` (the battery
#                                episode's side: 'floor' low / 'ceil' high, else
#                                null) and the page rounds last. _towardBreach
#                                deleted (Atlas RULED 2026-10-20/21).
# 2026-10-22    | Rex (US-877-c) | SYSTEM source: observeSystemStatus (in-process,
#                                from the system-status emit) makes one WATCH per
#                                verdict member (Iris titles, the member's reason
#                                verbatim), removed when it clears; systemSource()
#                                and buildAlertsState(systemSource=) -- not_read
#                                until a verdict was read; system ranks with engine.
# 2026-10-24    | Rex (US-869-c) | SYSTEM_TITLES gains 'sensor': 'SENSOR FAULT'.
# 2026-10-27    | Rex (US-917-c) | SYSTEM_TITLES gains 'sync': 'SYNC NOT COMPLETE'.
# 2026-10-28    | Rex (US-897-f) | sources.system carries the verdict's issueCount
#                                as published (null unless an int >= 0); an
#                                untitled member is a WATCH titled
#                                SYSTEM_TITLE_FALLBACK, no longer skipped (Atlas F2).
# ================================================================================
################################################################################

"""Publish ``states/alerts`` (US-897-b2, Atlas 2026-10-14 s2).

The F-092 card-emitter house shape, plus one stateful piece:

* :class:`AlertsArbiter` holds the episodes in memory for this boot. Each card
  tick it is shown the obd-live payload the tick just published and moves the
  episodes on; a STOP episode's open and clear are each INSERTed into the
  existing, already-synced ``alert_log`` (Atlas Q15 option C).
* :func:`buildAlertsState` is pure over (episodes, obd-live payload, now): it
  computes everything the page shows -- the icon, the order, the takeover. The
  page compares nothing (rule 0).
* :func:`makeAlertsEmitter` writes ``<statesDir>/alerts`` atomically and never
  raises.

Three rules are load-bearing:

* **Stale never clears** (Spool). Only a FRESH reading whose band has left red
  ends a STOP -- and only a fresh GREEN held 10 s ends the battery WATCH; while
  the reading is stale or absent the entry stays active with ``value: null``
  and ``last`` carrying the last red reading (Atlas Q10).
* **A cleared STOP stays listed** ``active: false`` until it is acknowledged,
  bounded by the boot; it never drops by time (Atlas Q15). A restart inside the
  boot re-reads it from the tmpfs ``states/alerts`` (Atlas G3). The
  acknowledgements themselves are the host's ack store's (US-897-c), handed to
  :func:`buildAlertsState` as ids: the arbiter never writes.
* **ids are deterministic**: ``<source>:<key>:<tier>``, never a counter, so an
  escalation is a new id.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from pi.obdii.band_producer import BAND_GREEN, BAND_RED, PID_BATTERY, PID_COOLANT, PID_RPM
from pi.splash.dtc_severity_table import (
    SEVERITY_MINOR,
    SEVERITY_STOP,
    SEVERITY_UNKNOWN,
    SEVERITY_WATCH,
)

__all__ = [
    "ALERTS_STATE_FILENAME",
    "ALERT_TYPE_COOLANT_STOP",
    "ALERT_TYPE_COOLANT_STOP_CLEAR",
    "AlertEpisode",
    "AlertsArbiter",
    "buildAlertsState",
    "makeAlertsEmitter",
    "readAlertsSeed",
]

logger = logging.getLogger("pi.obdii.alerts_arbiter")

# The state name a page fetches: GET /alerts.
ALERTS_STATE_FILENAME = "alerts"

# alert_log.alert_type for a coolant STOP episode's two edges (Atlas Q15 design
# 5): new strings in the existing column; the legacy AlertManager's are untouched.
ALERT_TYPE_COOLANT_STOP = "coolant_stop"
ALERT_TYPE_COOLANT_STOP_CLEAR = "coolant_stop_clear"

SOURCE_ENGINE = "engine"
SOURCE_CODE = "code"
SOURCE_SYSTEM = "system"

TIER_STOP = "stop"
TIER_WATCH = "watch"
TIER_MINOR = "minor"
TIER_UNRATED = "unrated"

ICON_STOP = "stop"
ICON_WATCH = "watch"
ICON_NOT_CHECKED = "not_checked"
ICON_NONE = "none"

# B5 order: tier first, then live (engine, system) before stored (code). System
# ties engine (Atlas RULED 2026-10-22 A1): newest firstSeenTs, then id, decide.
_TIER_RANK = {TIER_STOP: 0, TIER_WATCH: 1, TIER_MINOR: 2, TIER_UNRATED: 3}
_SOURCE_RANK = {SOURCE_ENGINE: 0, SOURCE_SYSTEM: 0, SOURCE_CODE: 1}

# R28: the server rejects rows from these sources, so the Pi never writes them.
_NO_RECORD_SOURCES = frozenset({"replay", "physics_sim"})

# The coolant STOP's words, Spool 2026-10-14 WARNINGS rulings s3 (verbatim).
COOLANT_STOP_DIRECTIVE = "PULL OVER"
COOLANT_STOP_TITLE = "ENGINE OVERHEATING"
COOLANT_STOP_SENTENCE = "Stop safely, engine off. Do not open the radiator cap hot."
COOLANT_UNIT = "C"

_REDTIER_KEY = "pi.warnings.engine.COOLANT_TEMP.redTier"
_RED_C_KEY = "pi.bands.coolant.redC"
_RED_CLEAR_BELOW_C_KEY = "pi.bands.coolant.redClearBelowC"

# The battery WATCH's words by side, Spool 2026-10-14 WARNINGS rulings (verbatim).
BATTERY_LOW_TITLE = "CHARGING FAULT"
BATTERY_LOW_SENTENCE = "Head somewhere safe. Turn off accessories."
BATTERY_HIGH_TITLE = "OVERCHARGING"
BATTERY_HIGH_SENTENCE = "Head somewhere safe, then engine off."
BATTERY_UNIT = "V"

_SIDE_LOW = "low"
_SIDE_HIGH = "high"
_BATTERY_WORDS = {
    _SIDE_LOW: (BATTERY_LOW_TITLE, BATTERY_LOW_SENTENCE),
    _SIDE_HIGH: (BATTERY_HIGH_TITLE, BATTERY_HIGH_SENTENCE),
}
# The entry's `round` by the episode's side: the page rounds TOWARD the breach
# as its last step, after unit conversion (Spool 2026-10-19; Atlas RULED
# 2026-10-20 -- the provider publishes the raw value, never a pre-rounded one).
ROUND_FLOOR = "floor"
ROUND_CEIL = "ceil"
_ROUND_OF_SIDE = {_SIDE_LOW: ROUND_FLOOR, _SIDE_HIGH: ROUND_CEIL}

_BATTERY_REDTIER_KEY = "pi.warnings.engine.BATTERY_V.redTier"
_BATTERY_RED_ABOVE_V_KEY = "pi.bands.battery.redAboveV"
_BATTERY_CLEAR_GREEN_HOLD_KEY = "pi.warnings.battery.clearGreenHoldSec"

# The over-rev WATCH (Spool 2026-10-14/10-18 + Atlas G3): the sentence carries
# the SAMPLED peak -- '(sampled)' is mandatory, the poll can miss the true one.
RPM_OVER_REV_TITLE = "OVER-REV"
_RPM_SENTENCE_FMT = "peak {peak:,} rpm (sampled)"
_RPM_SENTENCE_PEAK = re.compile(r"^peak ([0-9][0-9,]*) rpm \(sampled\)$")

_RPM_REDTIER_KEY = "pi.warnings.engine.RPM.redTier"
_RPM_CLEAR_GREEN_HOLD_KEY = "pi.warnings.rpm.clearGreenHoldSec"

# Code entries (US-897-b5). The table tier -> the alerts tier: a code is NEVER
# stop (Spool s4, R31 -- only a live coolant red takes over), so a stop-tier row
# publishes as watch; unknown (no row) is UNRATED, never a guessed tier. 'na' is
# absent on purpose: an auto-trans code on this manual car is not a fault. The
# clear gate keeps reading the dtc payload's own table tier, never this one.
_CODE_TIER_OF_SEVERITY = {
    SEVERITY_STOP: TIER_WATCH,
    SEVERITY_WATCH: TIER_WATCH,
    SEVERITY_MINOR: TIER_MINOR,
    SEVERITY_UNKNOWN: TIER_UNRATED,
}
# Spool 2026-10-19 (S106 Q1), verbatim: every code with no table row.
CODE_UNRATED_SENTENCE = "Severity unknown. Get it diagnosed."
# Spool 2026-10-19 (b5): a pending code is labelled; same tier, same sentence.
CODE_PENDING_TITLE_SUFFIX = " · pending"
CODE_STATUS_STORED = "stored"
CODE_STATUS_PENDING = "pending"

# SYSTEM entries (US-877-c): one WATCH per member of the system-status verdict,
# never stop. Titles by member key, Iris 2026-10-19 (verbatim, <= 21 chars); the
# sentence is the member's own reason, copied -- the page composes nothing. A key
# not in this table gets SYSTEM_TITLE_FALLBACK and one WARNING (Atlas F2 RULED
# 2026-10-28, superseding the 10-22 A5 skip): every counted member yields exactly
# one entry, so the icon, the list and System's count agree by construction.
SYSTEM_TITLES = {
    "bt": "BLUETOOTH NOT LINKED",
    "adapter": "ADAPTER NOT ANSWERING",
    "capture": "DATA FEED STALLED",
    # US-869-c (Iris C-Iris-1): one title whatever the member's `feeds`.
    "sensor": "SENSOR FAULT",
    "wifi": "WIFI NOT READ",
    "pi": "PI OVER LIMIT",
    # US-917-c (Iris 2026-10-27): <THING> <STATE>; true for S1, S2 and S3.
    "sync": "SYNC NOT COMPLETE",
}
# Its own constant, never a SYSTEM_TITLES key: that table stays set-equal to the
# verdict's member keys (Iris owns the words).
SYSTEM_TITLE_FALLBACK = "SYSTEM ISSUE"
SYSTEM_REASON_NOT_READ = "not_read"
DATA_REASON_NOT_BUILT = "not_built"

# Matches the other card emitters' `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _configValue(config: Mapping[str, Any], key: str) -> Any:
    """``key`` (dot notation) from config, else the validator default."""
    from common.config.validator import DEFAULTS

    node: Any = config
    for part in key.split("."):
        if not isinstance(node, Mapping) or node.get(part) is None:
            return DEFAULTS[key]
        node = node[part]
    return node


def _entryId(source: str, key: str, tier: str) -> str:
    return f"{source}:{key}:{tier}"


@dataclass(frozen=True)
class AlertEpisode:
    """One condition's episode, as the arbiter holds it for this boot.

    Attributes:
        source: ``engine`` (live) or ``code`` (stored).
        key: The PID or code.
        tier: ``stop`` / ``watch`` / ``minor`` / ``unrated``.
        title: Spool's title, verbatim.
        sentence: Spool's sentence, verbatim.
        directive: The instruction a takeover shows (a STOP's), else None.
        unit: The reading's own unit, or None.
        firstSeenTs: Event time of the episode's first observation (ISO UTC).
        lastSeenTs: Event time of its last observation (ISO UTC).
        active: False once the condition cleared; it stays listed.
        stale: True while the active condition has no fresh reading.
        value: The CURRENT reading, None while stale or cleared.
        last: ``{value, band, ts}`` of the last red reading while ``value`` is
            None, else None.
        acknowledged: False as held; :func:`buildAlertsState` publishes True
            for the ids the host's ack store matches this boot (US-897-c).
        peak: Highest reading of the episode (the clear row's value).
        recorded: True once THIS process wrote the episode's open row.
        codeStatus: ``stored`` / ``pending`` for a code entry, else None.
        round: The page's rounding direction for ``value`` and ``last.value``:
            ``floor`` / ``ceil`` for the battery episode (its side), else None.
    """

    source: str
    key: str
    tier: str
    title: str
    sentence: str
    directive: str | None
    unit: str | None
    firstSeenTs: str | None
    lastSeenTs: str | None
    active: bool
    stale: bool = False
    value: Any = None
    last: dict[str, Any] | None = None
    acknowledged: bool = False
    peak: float | None = None
    recorded: bool = False
    codeStatus: str | None = None
    round: str | None = None

    @property
    def id(self) -> str:
        return _entryId(self.source, self.key, self.tier)


def _isNumber(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _param(obdLive: Mapping[str, Any] | None, pid: str) -> Mapping[str, Any] | None:
    """The obd-live ``params[pid]`` entry, or None when absent."""
    if not isinstance(obdLive, Mapping):
        return None
    params = obdLive.get("params")
    if not isinstance(params, Mapping):
        return None
    param = params.get(pid)
    return param if isinstance(param, Mapping) else None


def _freshParam(obdLive: Mapping[str, Any] | None, pid: str) -> Mapping[str, Any] | None:
    """The ``params[pid]`` entry when it is a FRESH reading, else None (Q14)."""
    param = _param(obdLive, pid)
    if param is None or param.get("stale") is not False or not _isNumber(param.get("value")):
        return None
    return param


def _freshCoolant(obdLive: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The COOLANT_TEMP entry when it is a FRESH reading, else None (Q14)."""
    return _freshParam(obdLive, PID_COOLANT)


def _rpmSentence(peak: float) -> str:
    """'peak 7,150 rpm (sampled)': floor of the peak, ',' thousands (Spool 2026-10-19)."""
    return _RPM_SENTENCE_FMT.format(peak=math.floor(peak))


def _rpmPeakOf(sentence: Any) -> float | None:
    """The peak a published over-rev sentence carries, or None."""
    match = _RPM_SENTENCE_PEAK.match(sentence) if isinstance(sentence, str) else None
    return None if match is None else float(match.group(1).replace(",", ""))


def _alertableCodes(codes: Iterable[Any]) -> dict[str, Mapping[str, Any]]:
    """``{code: enriched code}`` for every stored/pending code with an alert tier.

    ``na`` and any severity outside the table vocabulary are excluded. A code
    listed both stored and pending in one read is ONE entry, stored.
    """
    alertable: dict[str, Mapping[str, Any]] = {}
    for raw in codes:
        if not isinstance(raw, Mapping):
            continue
        code = str(raw.get("code") or "").upper()
        status = raw.get("status")
        if (
            not code
            or status not in (CODE_STATUS_STORED, CODE_STATUS_PENDING)
            or raw.get("severity") not in _CODE_TIER_OF_SEVERITY
        ):
            continue
        prior = alertable.get(code)
        if prior is None or prior.get("status") != CODE_STATUS_STORED:
            alertable[code] = raw
    return alertable


def _parseTs(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bandName(param: Mapping[str, Any]) -> str | None:
    band = param.get("band")
    if isinstance(band, Mapping) and isinstance(band.get("band"), str):
        return str(band["band"])
    return None


class AlertsArbiter:
    """The episodes of this boot; moved on once per card tick.

    In memory and boot-bounded: a service restart inside a boot forgets them
    unless they are seeded from the tmpfs ``states/alerts`` (Atlas G3); the
    alert_log rows survive regardless.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        driveIdProvider: Callable[[], int | None] | None = None,
        seedEntries: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        """
        Args:
            config: The FULL resolved config (``pi.bands.*``, ``pi.warnings.*``).
            driveIdProvider: Returns the current drive id for an alert_log row;
                defaults to ``pi.obdii.drive_id.getCurrentDriveId``.
            seedEntries: Entries of this boot's prior ``states/alerts``
                (:func:`readAlertsSeed`); unknown ids are ignored.
        """
        self._config = config
        self._coolantTier = str(_configValue(config, _REDTIER_KEY))
        self._redC = float(_configValue(config, _RED_C_KEY))
        self._redClearBelowC = float(_configValue(config, _RED_CLEAR_BELOW_C_KEY))
        if driveIdProvider is None:
            from pi.obdii.drive_id import getCurrentDriveId

            driveIdProvider = getCurrentDriveId
        self._driveIdProvider = driveIdProvider
        self._noDatabaseWarned = False
        self._coolant: AlertEpisode | None = None
        # {value, band, ts} of the coolant episode's last red reading.
        self._coolantLastReading: dict[str, Any] | None = None
        self._batteryTier = str(_configValue(config, _BATTERY_REDTIER_KEY))
        self._batteryRedAboveV = float(_configValue(config, _BATTERY_RED_ABOVE_V_KEY))
        self._batteryClearGreenHoldSec = float(_configValue(config, _BATTERY_CLEAR_GREEN_HOLD_KEY))
        self._battery: AlertEpisode | None = None
        # The side ('low'/'high') of the battery episode's last red reading.
        self._batterySide = _SIDE_LOW
        # {value, band, ts} of the battery episode's last red reading (raw).
        self._batteryLastReading: dict[str, Any] | None = None
        # Event time of the first reading of the current unbroken green run.
        self._batteryGreenSince: datetime | None = None
        self._rpmTier = str(_configValue(config, _RPM_REDTIER_KEY))
        self._rpmClearGreenHoldSec = float(_configValue(config, _RPM_CLEAR_GREEN_HOLD_KEY))
        # The over-rev episode and its green run are written on the realtime
        # thread (observeRpmReading) and read on the run loop: one lock, the
        # _fuelLock precedent.
        self._rpmLock = threading.Lock()
        self._rpm: AlertEpisode | None = None
        # Event times of the first and newest reading of the current unbroken
        # green run (per reading, not per snapshot).
        self._rpmGreenSince: datetime | None = None
        self._rpmGreenLatest: datetime | None = None
        # US-897-b5: the code entries, keyed by code. observeDtc is called off
        # the run loop (key-on, the MIL edge on the reading thread), so they
        # move under their own lock, the _rpmLock precedent.
        self._codeLock = threading.Lock()
        self._codes: dict[str, AlertEpisode] = {}
        self._codeSource: dict[str, Any] = {"assessed": False, "checkedAtTs": None}
        # checkedAtTs of the newest dtc payload whose codes were applied (G1).
        self._codeAppliedAt: datetime | None = None
        # US-877-c: the system entries, keyed by verdict member, from the last
        # system-status payload handed in. Written on the run loop, read by the
        # ack route too: their own lock, the _codeLock precedent.
        self._systemLock = threading.Lock()
        self._system: dict[str, AlertEpisode] = {}
        self._systemRead = False
        # US-897-f: the verdict's issueCount AS PUBLISHED (System's 'n ISSUES'),
        # None when it was not an int >= 0. Never counted here (Atlas F9).
        self._systemIssueCount: int | None = None
        self._systemUnknownWarned: set[str] = set()
        for entry in seedEntries:
            self._seed(entry)

    # ------------------------------------------------------------- reading

    def episodes(self) -> list[AlertEpisode]:
        """Every episode of this boot, active or cleared (unordered)."""
        with self._rpmLock:
            rpm = self._rpm
        with self._codeLock:
            codes = list(self._codes.values())
        with self._systemLock:
            system = list(self._system.values())
        return [e for e in (self._coolant, self._battery, rpm) if e is not None] + codes + system

    def codeSource(self) -> dict[str, Any]:
        """``sources.code`` -- ``{assessed, checkedAtTs}`` of the last dtc payload."""
        with self._codeLock:
            return dict(self._codeSource)

    def systemSource(self) -> dict[str, Any]:
        """``sources.system`` -- assessed once a verdict was read this boot,
        with that verdict's ``issueCount`` (int >= 0, else None; US-897-f)."""
        with self._systemLock:
            if self._systemRead:
                return {"assessed": True, "issueCount": self._systemIssueCount}
        return {"assessed": False, "reason": SYSTEM_REASON_NOT_READ}

    # -------------------------------------------------------------- system

    def observeSystemStatus(self, payload: Mapping[str, Any] | None) -> None:
        """Take the system-status payload its emit just wrote (US-877-c).

        Handed IN-PROCESS by ``_emitSystemStatusState`` only -- never by
        ``emitNow``, which stays a pure rebuild. Each verdict member is one
        active WATCH, id ``system:<key>:watch``; a member that left the verdict
        is REMOVED (a watch is never 'listed until acked'). ``firstSeenTs`` is
        the payload ``ts`` of the episode's first verdict and stays put while
        the member's reason changes; ``lastSeenTs`` advances to each payload's
        ``ts`` (Atlas A2). A None or verdict-less payload (a failed write) keeps
        what is held, still assessed (A3). No alert_log row (A6).

        The verdict's ``issueCount`` is held AS PUBLISHED for ``sources.system``
        (US-897-f): a bool, a non-int or a negative is held as None. A member
        whose key has no title becomes a WATCH titled ``SYSTEM_TITLE_FALLBACK``
        (Atlas F2); only a malformed member (non-str key or reason) is skipped.

        Args:
            payload: The system-status payload written, or None when none was.
        """
        if not isinstance(payload, Mapping):
            return
        verdict = payload.get("verdict")
        members = verdict.get("members") if isinstance(verdict, Mapping) else None
        if not isinstance(members, list):
            return
        issueCount = verdict.get("issueCount") if isinstance(verdict, Mapping) else None
        if type(issueCount) is not int or issueCount < 0:
            issueCount = None
        ts = payload.get("ts")
        ts = ts if isinstance(ts, str) and ts else None
        with self._systemLock:
            updated: dict[str, AlertEpisode] = {}
            for member in members:
                if not isinstance(member, Mapping):
                    continue
                key = member.get("key")
                reason = member.get("reason")
                if not isinstance(key, str) or not isinstance(reason, str):
                    continue
                title = SYSTEM_TITLES.get(key)
                if title is None:
                    title = SYSTEM_TITLE_FALLBACK
                    if key not in self._systemUnknownWarned:
                        self._systemUnknownWarned.add(key)
                        logger.warning(
                            "states/alerts: system verdict member %r has no title -- listed as %r",
                            key,
                            SYSTEM_TITLE_FALLBACK,
                        )
                previous = self._system.get(key)
                updated[key] = AlertEpisode(
                    source=SOURCE_SYSTEM,
                    key=key,
                    tier=TIER_WATCH,
                    title=title,
                    sentence=reason,
                    directive=None,
                    unit=None,
                    firstSeenTs=ts if previous is None else previous.firstSeenTs,
                    lastSeenTs=ts,
                    active=True,
                )
            self._system = updated
            self._systemIssueCount = issueCount
            self._systemRead = True

    # --------------------------------------------------------------- codes

    def observeDtc(self, payload: Mapping[str, Any] | None) -> None:
        """Take the dtc payload the router just wrote (US-897-b5, Atlas Q6).

        Handed IN-PROCESS by ``_emitDtcState`` / ``_emitInitialDtcState``, never
        a file read-back. ``sources.code`` is assessed only when the read was
        available AND carries a ``checkedAtTs``. ``codes`` null (unavailable,
        the boot state with its ``lastKnown`` included) creates and removes no
        entry: unknown is neither present nor cleared. A code absent from a read
        is REMOVED only when that read's ``checkedAtTs`` is newer than the last
        one applied (G1); a payload older than that changes nothing.

        Args:
            payload: The states/dtc payload written, or None when none was.
        """
        if not isinstance(payload, Mapping):
            return
        checkedAtTs = payload.get("checkedAtTs")
        if not isinstance(checkedAtTs, str) or not checkedAtTs:
            checkedAtTs = None
        at = _parseTs(checkedAtTs)
        source = payload.get("source")
        dtcSource = source.get("dtc") if isinstance(source, Mapping) else None
        available = isinstance(dtcSource, Mapping) and dtcSource.get("available") is True
        codes = payload.get("codes")
        listed = codes if isinstance(codes, list) else None
        with self._codeLock:
            applied = self._codeAppliedAt
            if at is not None and applied is not None and at < applied:
                return
            self._codeSource = {
                "assessed": available and checkedAtTs is not None and listed is not None,
                "checkedAtTs": checkedAtTs,
            }
            if listed is None:
                return
            newer = at is not None and (applied is None or at > applied)
            # A newer read is the whole truth; an unchanged one only adds.
            updated = {} if newer else dict(self._codes)
            for code, raw in _alertableCodes(listed).items():
                updated[code] = self._codeEpisode(code, raw, checkedAtTs)
            self._codes = updated
            if newer:
                self._codeAppliedAt = at

    def _codeEpisode(
        self, code: str, raw: Mapping[str, Any], checkedAtTs: str | None
    ) -> AlertEpisode:
        """One code's entry: the table's own words, or UNRATED's when untabled.

        Called under ``_codeLock``. The id carries no status, so a pending code
        that later stores stays ONE entry and only ``codeStatus`` flips.
        """
        tier = _CODE_TIER_OF_SEVERITY[raw["severity"]]
        status = raw["status"]
        title = raw.get("title")
        if not isinstance(title, str) or not title:
            title = code
        if status == CODE_STATUS_PENDING:
            title += CODE_PENDING_TITLE_SUFFIX
        sentence = raw.get("sentence")
        if not isinstance(sentence, str) or not sentence:
            sentence = CODE_UNRATED_SENTENCE if tier == TIER_UNRATED else ""
        firstSeenTs = raw.get("firstSeenTs")
        previous = self._codes.get(code)
        if not isinstance(firstSeenTs, str) and previous is not None:
            firstSeenTs = previous.firstSeenTs
        return AlertEpisode(
            source=SOURCE_CODE,
            key=code,
            tier=tier,
            title=title,
            sentence=sentence,
            directive=None,
            unit=None,
            firstSeenTs=firstSeenTs if isinstance(firstSeenTs, str) else None,
            lastSeenTs=checkedAtTs,
            active=True,
            codeStatus=status,
        )

    # ------------------------------------------------------------- the tick

    def observe(
        self,
        obdLive: Mapping[str, Any] | None,
        *,
        dataSource: str | None,
        database: Any,
        driveRecording: bool = False,
        driveEnded: bool = False,
    ) -> None:
        """Move the episodes on from the obd-live payload the tick published.

        Args:
            obdLive: The states/obd-live payload just written, or None when
                nothing was published (no tracker, or the write failed).
            dataSource: The data_source tag of the readings; replay and
                physics_sim write no alert_log row.
            database: An ``ObdDatabase``-like object (``connect()``), or None.
            driveRecording: A drive is recording now (``_gatherDriveState``).
            driveEnded: The recording -> idle edge happened since the last tick.
        """
        self._observeCoolant(obdLive, dataSource=dataSource, database=database)
        self._observeBattery(obdLive)
        self._observeRpmEnd(obdLive, driveRecording=driveRecording, driveEnded=driveEnded)

    # ------------------------------------------------------------ over-rev

    def observeRpmReading(self, value: Any, eventUtc: datetime, band: Any) -> None:
        """Feed ONE RPM reading from the reading seam (US-897-b4).

        Every reading, not the ~2 s snapshot, so the peak is the highest SAMPLED
        value. ``band`` is the band producer's result for THIS reading -- the
        producer is the one judge of red; nothing is compared here.

        Args:
            value: The RPM reading; None (or non-numeric) breaks the green run.
            eventUtc: Aware UTC event time of the reading.
            band: ``{band, since, reason}`` at this reading, or None.
        """
        bandName = band.get("band") if isinstance(band, Mapping) else None
        with self._rpmLock:
            if not _isNumber(value):
                self._rpmGreenSince = None
                self._rpmGreenLatest = None
                return
            rpm = float(value)
            if bandName == BAND_RED:
                self._rpmGreenSince = None
                self._rpmGreenLatest = None
                from common.time.helper import toCanonicalIso

                ts = toCanonicalIso(eventUtc)
                episode = self._rpm
                if episode is None or not episode.active:
                    episode = self._newRpmEpisode(ts)
                peak = rpm if episode.peak is None else max(episode.peak, rpm)
                self._rpm = replace(
                    episode, lastSeenTs=ts, peak=peak, sentence=_rpmSentence(peak)
                )
                return
            if bandName == BAND_GREEN:
                if self._rpmGreenSince is None:
                    self._rpmGreenSince = eventUtc
                self._rpmGreenLatest = eventUtc
                return
            # Amber or unbanded: not green, so the green run starts over.
            self._rpmGreenSince = None
            self._rpmGreenLatest = None

    def resetRpmPeak(self) -> None:
        """Drive start: the peak counts from this drive's readings only.

        A cleared episode stays listed; the next red reading opens a new one.
        An episode still active at the drive start keeps its entry, and its
        peak restarts from the next red reading.
        """
        with self._rpmLock:
            if self._rpm is not None and self._rpm.active:
                self._rpm = replace(self._rpm, peak=None)

    def _observeRpmEnd(
        self, obdLive: Mapping[str, Any] | None, *, driveRecording: bool, driveEnded: bool
    ) -> None:
        """End the over-rev at drive end, or -- no drive recording -- after the
        band has been green for clearGreenHoldSec by reading time (Atlas Q13).
        The green end also needs the tick's RPM to be a FRESH green reading:
        stale never clears."""
        param = _freshParam(obdLive, PID_RPM)
        freshGreen = param is not None and _bandName(param) == BAND_GREEN
        with self._rpmLock:
            episode = self._rpm
            if episode is None or not episode.active:
                return
            if driveEnded:
                self._endRpm(episode)
                return
            if driveRecording or not freshGreen:
                return
            since, latest = self._rpmGreenSince, self._rpmGreenLatest
            if (
                since is not None
                and latest is not None
                and (latest - since).total_seconds() >= self._rpmClearGreenHoldSec
            ):
                self._endRpm(episode)

    def _endRpm(self, episode: AlertEpisode) -> None:
        """Mark the over-rev ended; it stays listed until acked (Q15)."""
        self._rpm = replace(episode, active=False)
        self._rpmGreenSince = None
        self._rpmGreenLatest = None

    def _newRpmEpisode(self, firstSeenTs: Any) -> AlertEpisode:
        """A fresh over-rev episode: value and unit stay null (Atlas G3)."""
        return AlertEpisode(
            source=SOURCE_ENGINE,
            key=PID_RPM,
            tier=self._rpmTier,
            title=RPM_OVER_REV_TITLE,
            sentence="",
            directive=None,
            unit=None,
            firstSeenTs=firstSeenTs,
            lastSeenTs=firstSeenTs,
            active=True,
        )

    def _observeBattery(self, obdLive: Mapping[str, Any] | None) -> None:
        """Move the battery WATCH on (US-897-b3, Spool 2026-10-14 + Atlas Q12).

        Red (low or high) opens or continues the one ``engine:BATTERY_V`` episode;
        it ends only after the band has been GREEN for clearGreenHoldSec by the
        READINGS' event time. A null band (engine_not_running, amber_not_shipped),
        a stale or absent reading never ends it and breaks the green run.
        """
        episode = self._battery
        active = episode is not None and episode.active
        param = _freshParam(obdLive, PID_BATTERY)
        band = None if param is None else _bandName(param)
        if param is None or band not in (BAND_RED, BAND_GREEN):
            self._batteryGreenSince = None
            if episode is not None and active and not episode.stale:
                self._battery = replace(
                    episode, stale=True, value=None, last=self._batteryLast(episode)
                )
            return
        value = float(param["value"])
        ts = param.get("ts")
        if band == BAND_RED:
            self._batteryGreenSince = None
            # Side from the VALUE against the configured edge; the band is red,
            # so a value not above redAboveV is below redBelowV.
            side = _SIDE_HIGH if value > self._batteryRedAboveV else _SIDE_LOW
            if episode is None or not active:
                episode = self._newBatteryEpisode(ts, side)
            title, sentence = _BATTERY_WORDS[side]
            self._batterySide = side
            self._batteryLastReading = {"value": value, "band": dict(param["band"]), "ts": ts}
            self._battery = replace(
                episode,
                title=title,
                sentence=sentence,
                lastSeenTs=ts,
                stale=False,
                value=value,
                last=None,
                round=_ROUND_OF_SIDE[side],
            )
            return
        if episode is None or not active:
            return
        # Green while active: hold, then end.
        at = _parseTs(ts)
        if self._batteryGreenSince is None:
            self._batteryGreenSince = at
        held = (
            at is not None
            and self._batteryGreenSince is not None
            and (at - self._batteryGreenSince).total_seconds() >= self._batteryClearGreenHoldSec
        )
        if held:
            self._batteryGreenSince = None
            self._battery = replace(
                episode, active=False, stale=False, value=None, last=self._batteryLast(episode)
            )
            return
        # The green hold keeps the EPISODE's side for its round (Atlas RULED
        # 2026-10-21, reading 3): no band fired on this reading.
        self._battery = replace(
            episode, stale=False, value=value, last=None,
            round=_ROUND_OF_SIDE[self._batterySide],
        )

    def _batteryLast(self, episode: AlertEpisode) -> dict[str, Any] | None:
        """``{value, band, ts}`` of the battery episode's last red reading."""
        if self._batteryLastReading is not None:
            return dict(self._batteryLastReading)
        return episode.last

    def _newBatteryEpisode(self, firstSeenTs: Any, side: str) -> AlertEpisode:
        self._batteryLastReading = None
        self._batteryGreenSince = None
        title, sentence = _BATTERY_WORDS[side]
        return AlertEpisode(
            source=SOURCE_ENGINE,
            key=PID_BATTERY,
            tier=self._batteryTier,
            title=title,
            sentence=sentence,
            directive=None,
            unit=BATTERY_UNIT,
            firstSeenTs=firstSeenTs,
            lastSeenTs=firstSeenTs,
            active=True,
            round=_ROUND_OF_SIDE[side],
        )

    def _observeCoolant(
        self, obdLive: Mapping[str, Any] | None, *, dataSource: str | None, database: Any
    ) -> None:
        episode = self._coolant
        param = _freshCoolant(obdLive)
        band = None if param is None else _bandName(param)
        if param is None or band is None:
            # Undecided (absent / stale / not read / unbanded): stale never clears.
            if episode is not None and episode.active and not episode.stale:
                self._coolant = replace(episode, stale=True, value=None, last=self._lastOf(episode))
            return
        value = param["value"]
        ts = param.get("ts")
        if band == BAND_RED:
            reading = {"value": value, "band": dict(param["band"]), "ts": ts}
            if episode is None or not episode.active:
                episode = self._newCoolantEpisode(ts)
            episode = replace(
                episode,
                lastSeenTs=ts,
                stale=False,
                value=value,
                last=None,
                peak=value if episode.peak is None else max(episode.peak, value),
            )
            self._coolantLastReading = reading
            if not episode.recorded:
                self._record(
                    ALERT_TYPE_COOLANT_STOP, value, self._redC, ts,
                    dataSource=dataSource, database=database,
                )
                episode = replace(episode, recorded=True)
            self._coolant = episode
            return
        if episode is not None and episode.active:
            # The band left red (red's own clear is the band producer's).
            self._coolant = replace(
                episode, active=False, stale=False, value=None, last=self._lastOf(episode)
            )
            if episode.peak is not None:
                self._record(
                    ALERT_TYPE_COOLANT_STOP_CLEAR, episode.peak, self._redClearBelowC, ts,
                    dataSource=dataSource, database=database,
                )

    def _lastOf(self, episode: AlertEpisode) -> dict[str, Any] | None:
        """``{value, band, ts}`` of the episode's last red reading."""
        if self._coolantLastReading is not None:
            return dict(self._coolantLastReading)
        return episode.last

    def _newCoolantEpisode(self, firstSeenTs: Any) -> AlertEpisode:
        self._coolantLastReading = None
        return AlertEpisode(
            source=SOURCE_ENGINE,
            key=PID_COOLANT,
            tier=self._coolantTier,
            title=COOLANT_STOP_TITLE,
            sentence=COOLANT_STOP_SENTENCE,
            directive=COOLANT_STOP_DIRECTIVE,
            unit=COOLANT_UNIT,
            firstSeenTs=firstSeenTs,
            lastSeenTs=firstSeenTs,
            active=True,
        )

    # ------------------------------------------------------------ the seed

    def _seed(self, entry: Mapping[str, Any]) -> None:
        """Take one prior-state entry back (Atlas G3); unknown ids are ignored.

        A seeded ACTIVE entry is stale until a fresh reading decides it, and
        has no open row from THIS process: if it is still red, a second
        'coolant_stop' row is written (the stated, honest cost).
        """
        if not isinstance(entry, Mapping):
            return
        if entry.get("id") == _entryId(SOURCE_ENGINE, PID_BATTERY, self._batteryTier):
            self._seedBattery(entry)
            return
        if entry.get("id") == _entryId(SOURCE_ENGINE, PID_RPM, self._rpmTier):
            self._seedRpm(entry)
            return
        if entry.get("id") != _entryId(SOURCE_ENGINE, PID_COOLANT, self._coolantTier):
            return
        active = entry.get("active") is True
        last = entry.get("last") if isinstance(entry.get("last"), Mapping) else None
        lastValue = entry.get("value")
        if not _isNumber(lastValue) and last is not None:
            lastValue = last.get("value")
        if last is None and _isNumber(lastValue):
            last = {"value": lastValue, "band": None, "ts": entry.get("lastSeenTs")}
        episode = replace(
            self._newCoolantEpisode(entry.get("firstSeenTs")),
            lastSeenTs=entry.get("lastSeenTs"),
            active=active,
            stale=active,
            value=None,
            last=None if last is None else dict(last),
            peak=float(lastValue) if isinstance(lastValue, (int, float)) and _isNumber(lastValue) else None,
        )
        self._coolantLastReading = None if last is None else dict(last)
        self._coolant = episode

    def _seedBattery(self, entry: Mapping[str, Any]) -> None:
        """Take a prior battery WATCH back: its side from its title, its last red
        reading from ``last`` (else ``value``); an ACTIVE one is stale until a
        fresh reading decides it, and its green run starts over."""
        side = _SIDE_HIGH if entry.get("title") == BATTERY_HIGH_TITLE else _SIDE_LOW
        active = entry.get("active") is True
        last = entry.get("last") if isinstance(entry.get("last"), Mapping) else None
        if last is None and _isNumber(entry.get("value")):
            last = {"value": entry.get("value"), "band": None, "ts": entry.get("lastSeenTs")}
        self._battery = replace(
            self._newBatteryEpisode(entry.get("firstSeenTs"), side),
            lastSeenTs=entry.get("lastSeenTs"),
            active=active,
            stale=active,
            last=None if last is None else dict(last),
        )
        self._batterySide = side
        self._batteryLastReading = None if last is None else dict(last)

    def _seedRpm(self, entry: Mapping[str, Any]) -> None:
        """Take a prior over-rev back with its peak, read from its sentence
        (Atlas G3); the green run starts over, so an ACTIVE one ends only on a
        fresh green hold or the next drive end."""
        sentence = entry.get("sentence")
        peak = _rpmPeakOf(sentence)
        episode = replace(
            self._newRpmEpisode(entry.get("firstSeenTs")),
            lastSeenTs=entry.get("lastSeenTs"),
            active=entry.get("active") is True,
            peak=peak,
            sentence=sentence if isinstance(sentence, str) else "",
        )
        with self._rpmLock:
            self._rpm = episode

    # ---------------------------------------------------------- the record

    def _record(
        self,
        alertType: str,
        value: float,
        threshold: float,
        ts: Any,
        *,
        dataSource: str | None,
        database: Any,
    ) -> None:
        """INSERT one alert_log row; never UPDATE, never raise (Atlas Q15).

        The page fact comes first and the record second: a failure logs ERROR
        and the live STOP is published regardless.
        """
        if dataSource in _NO_RECORD_SOURCES:
            return
        if database is None:
            if not self._noDatabaseWarned:
                logger.warning("alert_log: no database -- %s row not written", alertType)
                self._noDatabaseWarned = True
            return
        try:
            from common.time.helper import utcIsoNow

            # The reading's event time; the write time only when it carries none.
            timestamp = ts if isinstance(ts, str) and ts else utcIsoNow()
            driveId = self._driveIdProvider()
            with database.connect() as conn:
                conn.execute(
                    "INSERT INTO alert_log "
                    "(timestamp, alert_type, parameter_name, value, threshold, drive_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (timestamp, alertType, PID_COOLANT, float(value), float(threshold), driveId),
                )
        except Exception as e:  # noqa: BLE001 -- never block the live STOP
            logger.error("alert_log INSERT of %s failed (%s) -- STOP still published", alertType, e)


def _sortKey(episode: AlertEpisode) -> tuple[int, int, float, str]:
    """B5: tier, then live (engine, system) before stored, then NEWEST firstSeenTs, then id."""
    newest = float("inf")
    if isinstance(episode.firstSeenTs, str):
        try:
            newest = -datetime.fromisoformat(episode.firstSeenTs.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return (
        _TIER_RANK.get(episode.tier, len(_TIER_RANK)),
        _SOURCE_RANK.get(episode.source, len(_SOURCE_RANK)),
        newest,
        episode.id,
    )


def _entryOf(episode: AlertEpisode) -> dict[str, Any]:
    return {
        "id": episode.id,
        "source": episode.source,
        "key": episode.key,
        "tier": episode.tier,
        "title": episode.title,
        "sentence": episode.sentence,
        "directive": episode.directive,
        "value": episode.value,
        "unit": episode.unit,
        "last": None if episode.last is None else dict(episode.last),
        "stale": episode.stale,
        "firstSeenTs": episode.firstSeenTs,
        "lastSeenTs": episode.lastSeenTs,
        "active": episode.active,
        "acknowledged": episode.acknowledged,
        "codeStatus": episode.codeStatus,
        "round": episode.round,
    }


def _takeoverOf(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "title": entry["title"],
        "sentence": entry["sentence"],
        "directive": entry["directive"],
        "value": entry["value"],
        "unit": entry["unit"],
        "last": entry["last"],
        "stale": entry["stale"],
        "firstSeenTs": entry["firstSeenTs"],
        "dismissable": False,
    }


def _icon(active: list[AlertEpisode], codeAssessed: bool) -> dict[str, Any]:
    """B6/G7: an active stop/watch outranks not_checked; minor/unrated are watch."""
    tiers = {e.tier for e in active}
    if TIER_STOP in tiers:
        state = ICON_STOP
    elif tiers & {TIER_WATCH, TIER_MINOR, TIER_UNRATED}:
        state = ICON_WATCH
    elif not codeAssessed:
        state = ICON_NOT_CHECKED
    else:
        state = ICON_NONE
    pulse = any(
        e.source == SOURCE_ENGINE and not e.acknowledged and e.tier in (TIER_STOP, TIER_WATCH)
        for e in active
    )
    return {"state": state, "count": len(active), "pulse": pulse}


def buildAlertsState(
    episodes: Iterable[AlertEpisode],
    obdLive: Mapping[str, Any] | None,
    nowUtc: datetime,
    *,
    dataSource: str | None,
    bootId: str,
    codeSource: Mapping[str, Any] | None = None,
    acknowledgedIds: Iterable[str] = (),
    systemSource: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the states/alerts payload (Atlas s2 shape; pure).

    Args:
        episodes: The arbiter's episodes of this boot.
        obdLive: The obd-live payload the tick published, or None.
        nowUtc: Aware UTC instant of this emit.
        dataSource: The obd-live data_source tag, or None.
        bootId: ``readBootId()`` ('unknown' when unreadable).
        codeSource: ``AlertsArbiter.codeSource()``; None -> unassessed.
        acknowledgedIds: The ids the ack store matches for this boot and this
            episode (US-897-c). Empty (the default) publishes nothing acked.
        systemSource: ``AlertsArbiter.systemSource()`` (US-877-c); None ->
            ``{assessed: false, reason: 'not_read'}``; assessed publishes
            ``{assessed: true, issueCount}`` (US-897-f).

    Returns:
        ``{ts, dataSource, bootId, sources, codesCheckedThisSession,
        checkedAtTs, icon, takeover, codeAlert, entries}`` -- every key present.
        ``entries`` is already ordered; ``takeover`` is set while the top
        ACTIVE entry is a stop (acked or not: the takeover is not dismissable);
        ``codeAlert`` while any code entry is active and not every one of its
        ids is acknowledged. An acknowledged entry that is no longer active is
        not listed (Atlas Q15: acking removes it), and an acknowledged entry
        never pulses.
    """
    acked = frozenset(acknowledgedIds)
    ordered = sorted(
        (replace(e, acknowledged=True) if e.id in acked else e for e in episodes),
        key=_sortKey,
    )
    ordered = [e for e in ordered if e.active or not e.acknowledged]
    entries = [_entryOf(e) for e in ordered]
    active = [e for e in ordered if e.active]
    code: dict[str, Any] = {"assessed": False, "checkedAtTs": None}
    if isinstance(codeSource, Mapping):
        code = {
            "assessed": codeSource.get("assessed") is True,
            "checkedAtTs": codeSource.get("checkedAtTs"),
        }
    system: dict[str, Any] = {"assessed": False, "reason": SYSTEM_REASON_NOT_READ}
    if isinstance(systemSource, Mapping) and systemSource.get("assessed") is True:
        # US-897-f: System's own count, null unless an int >= 0 (fails closed).
        issueCount = systemSource.get("issueCount")
        if type(issueCount) is not int or issueCount < 0:
            issueCount = None
        system = {"assessed": True, "issueCount": issueCount}
    takeover = None
    firstActive = next((entry for entry in entries if entry["active"]), None)
    if firstActive is not None and firstActive["tier"] == TIER_STOP:
        takeover = _takeoverOf(firstActive)
    # Atlas Q32: the provider computes the tier; the page decides moving/parked.
    codeIds = [e["id"] for e in entries if e["active"] and e["source"] == SOURCE_CODE]
    codeAlert = None
    if codeIds and not all(e["acknowledged"] for e in entries if e["id"] in codeIds):
        firstTier = next(e["tier"] for e in entries if e["id"] == codeIds[0])
        codeAlert = {"ids": codeIds, "tier": firstTier, "dismissable": True}
    return {
        "ts": nowUtc.strftime(_ISO_FMT),
        "dataSource": dataSource,
        "bootId": bootId,
        "sources": {
            "code": dict(code),
            "engine": {"assessed": _freshCoolant(obdLive) is not None},
            "system": system,
            "data": {"assessed": False, "reason": DATA_REASON_NOT_BUILT},
        },
        "codesCheckedThisSession": code["assessed"],
        "checkedAtTs": code["checkedAtTs"],
        "icon": _icon(active, code["assessed"]),
        "takeover": takeover,
        "codeAlert": codeAlert,
        "entries": entries,
    }


def readAlertsSeed(statesDir: str) -> list[dict[str, Any]]:
    """The entries of this boot's existing ``states/alerts`` (Atlas G3).

    The states dir is tmpfs, so a file there was written THIS boot by a prior
    orchestrator. A missing or unparseable file seeds nothing.

    Args:
        statesDir: tmpfs states directory.

    Returns:
        The prior entries (dicts only); empty when there is nothing usable.
    """
    try:
        with open(os.path.join(statesDir, ALERTS_STATE_FILENAME), encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def makeAlertsEmitter(statesDir: str) -> Callable[..., dict[str, Any] | None]:
    """Build the states/alerts emit callable.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).

    Returns:
        ``emit(episodes, obdLive, *, nowUtc, dataSource, bootId, codeSource,
        acknowledgedIds, systemSource)`` writing the payload atomically and
        returning it.
        Best-effort by contract: a failure is logged, never raised, and
        returns None.
    """
    from pi.splash import boot_state_emitter

    target = os.path.join(statesDir, ALERTS_STATE_FILENAME)

    def emit(
        episodes: Iterable[AlertEpisode],
        obdLive: Mapping[str, Any] | None,
        *,
        nowUtc: datetime,
        dataSource: str | None,
        bootId: str,
        codeSource: Mapping[str, Any] | None = None,
        acknowledgedIds: Iterable[str] = (),
        systemSource: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            payload = buildAlertsState(
                episodes, obdLive, nowUtc, dataSource=dataSource, bootId=bootId,
                codeSource=codeSource, acknowledgedIds=acknowledgedIds,
                systemSource=systemSource,
            )
            boot_state_emitter.ensureStatesDir(statesDir)
            boot_state_emitter.writeStateAtomic(target, payload)
        except Exception as e:  # noqa: BLE001 -- never crash the run loop
            logger.error("states/alerts write failed (%s) -- ignored", e)
            return None
        return payload

    return emit
