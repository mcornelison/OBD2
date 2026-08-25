################################################################################
# File Name: dtc_emitter.py
# Purpose/Description: F-111 `dtc` state emitter [US-404]. The schema + best-
#   effort writer for the `dtc` SSOT the carousel Alerts card (US-406) +
#   takeover/ribbon (US-405) consume. The DTC capture path OWNS this emitter:
#   after a KOEO (key-on) or drive Mode 03(+07) read it builds the enriched
#   state -- captured codes merged with Spool's static P1xxx severity table
#   (dtc_severity_table) -- and writes /run/eclipse-obd/states/dtc atomically.
#   Honest-instrument by contract: the Pi never decides severity (it merges
#   Spool's classification), never fabricates a description or fix (un-tabled
#   codes degrade to `unknown` with whatever python-obd supplied), never claims
#   a freeze-frame (Mode 02 confirmed unsupported on MD326328 -> freezeFrame
#   null, realtime fallback rendered by US-406), and a condition-dependent
#   caveat NEVER silently upgrades the tier (R-1). Mirrors the F-103 /
#   system-status / battery-health emitter seam; reuses ensureStatesDir +
#   writeStateAtomic so there is one provisioning + atomic-write impl (C-5).
#   Schema pinned in $FLEET_SHARE/knowledge/superpowers/specs/2026-06-05-pi-dtc-check-engine-
#   viewer-clear-design.md §8.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 `dtc` emitter (4th states-dir
#               |              | writer; KOEO + drive read publish path).
# ================================================================================
################################################################################

"""`dtc` schema builder + the best-effort emit factory (F-111 / US-404)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic
from pi.splash.dtc_severity_table import (
    FIX_PROVENANCE_NONE,
    SEVERITY_MINOR,
    SEVERITY_NA,
    SEVERITY_UNKNOWN,
)

# US-429 honest-availability: one source-availability truth per source (SSOT).
from pi.splash.source_availability import (
    REASON_DTC_NOT_READ,
    SOURCE_DTC,
    buildSourceState,
)

logger = logging.getLogger(__name__)

# The single SSOT slot the carousel Alerts card / takeover / ribbon poll.
DTC_FILENAME = "dtc"

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# clearGate reasons (design-spec §8): a non-MINOR stored code blocks the clear,
# else an un-synced capture blocks it, else it is clearable. US-407 owns the
# authoritative gate (re-checked at the privileged action path); this is the
# honest UI-side computation from what the capture read knows.
_REASON_SEVERITY = "severity_present"
_REASON_SYNC = "sync_pending"
_REASON_OK = "ok"

__all__ = [
    "DTC_FILENAME",
    "buildDtcState",
    "enrichCode",
    "makeDtcEmitter",
]


def enrichCode(raw: dict, severityTable: dict[str, dict]) -> dict:
    """Merge one captured code with Spool's static severity table (pure).

    Args:
        raw: A captured-code dict with at least ``code`` / ``status`` /
            ``description`` / ``driveId`` / ``setAtTs`` / ``logged`` /
            ``syncAcked``. ``driveId`` is None for a KOEO read.
        severityTable: The ``{code -> enrichment}`` map from
            :func:`~src.pi.splash.dtc_severity_table.loadP1xxxSeverityTable`.

    Returns:
        The enriched code dict (design-spec §8 per-code shape). A code absent
        from the table degrades honestly to ``unknown`` severity, no fabricated
        fix, and whatever description python-obd supplied (empty -> the display
        shows "No description yet"). ``freezeFrame`` is always None on the
        current ECU (Mode 02 unsupported); US-406 renders the realtime fallback.
    """
    code = str(raw.get("code", "")).upper()
    entry = severityTable.get(code)
    rawDesc = (raw.get("description") or "").strip()

    if entry is not None:
        severity = entry["severity"]
        caveat = entry["severityCaveat"]
        short = entry["short"]
        long = entry["long"]
        suggestedFix = entry["suggestedFix"]
        fixProvenance = entry["fixProvenance"]
        clearEligible = entry["clearEligible"]
    else:
        # Un-tabled: never fabricate severity/fix. Use python-obd's text only.
        severity = SEVERITY_UNKNOWN
        caveat = None
        short = rawDesc
        long = rawDesc
        suggestedFix = None
        fixProvenance = FIX_PROVENANCE_NONE
        clearEligible = False

    return {
        "code": code,
        "status": raw.get("status"),
        "severity": severity,
        "severityCaveat": caveat,
        "short": short,
        "long": long,
        "setAtTs": raw.get("setAtTs"),
        "driveId": raw.get("driveId"),
        "freezeFrame": None,  # Mode 02 unsupported on MD326328 -> realtime fallback
        "suggestedFix": suggestedFix,
        "fixProvenance": fixProvenance,
        "logged": bool(raw.get("logged", False)),
        "syncAcked": bool(raw.get("syncAcked", False)),
        "clearEligible": clearEligible,
    }


def _computeClearGate(enrichedCodes: list[dict]) -> dict:
    """Derive the clear gate from the enriched stored codes (design-spec §8).

    Mode 04 is all-or-nothing, so the gate keys off ALL stored codes. ``na``
    codes (auto-trans on this manual car) are not real faults and never block.
    A non-MINOR stored fault -> ``severity_present``; an un-logged/un-synced
    MINOR capture -> ``sync_pending``; otherwise clearable. US-407 re-checks
    this authoritatively at the privileged action path -- the UI is never
    trusted to be the gate.
    """
    relevant = [
        c
        for c in enrichedCodes
        if c.get("status") == "stored" and c.get("severity") != SEVERITY_NA
    ]
    if not relevant:
        return {"enabled": False, "reason": _REASON_OK}
    if any(c.get("severity") != SEVERITY_MINOR for c in relevant):
        return {"enabled": False, "reason": _REASON_SEVERITY}
    if any(not (c.get("logged") and c.get("syncAcked")) for c in relevant):
        return {"enabled": False, "reason": _REASON_SYNC}
    return {"enabled": True, "reason": _REASON_OK}


def buildDtcState(
    *,
    codes: list[dict],
    severityTable: dict[str, dict],
    mil: bool,
    newSinceTs: str | None,
    sessionResetLock: list[str] | None,
    nowIso: str,
    dtcAvailable: bool = True,
    dtcUnavailableReason: str | None = None,
) -> dict:
    """Assemble the `dtc` payload (pure; design-spec §8 pinned schema).

    Args:
        codes: Captured-code dicts (see :func:`enrichCode`). KOEO reads pass
            ``driveId`` None on every code.
        severityTable: Spool's static P1xxx severity map (the loader output).
        mil: Whether the malfunction-indicator lamp is reported lit.
        newSinceTs: ISO-8601 instant a *new* code appeared (drives the US-405
            takeover); None when nothing is new.
        sessionResetLock: Codes that re-set this session -> US-407 refuses a
            2nd clear ("don't chase the light"). None -> empty list.
        nowIso: ISO-8601 emission timestamp (freshness marker).
        dtcAvailable: Whether a DTC read actually happened (US-429). False when
            the OBD source is down so no KOEO/drive read could run -- the display
            then reads the source as *unavailable* (NA), NOT "no codes -> all
            clear" and never a mis-fired takeover. An unavailable read writes a
            FRESH empty state (no stale codes, no takeover trigger). Defaults True.
        dtcUnavailableReason: The typed-NA reason when ``dtcAvailable`` is False
            (defaults to ``REASON_DTC_NOT_READ``). Ignored when available.

    Returns:
        The `dtc` dict with exactly the spec §8 keys plus the US-429 ``source``
        block (one availability truth per source).
    """
    # US-429 honest-availability: an unavailable DTC source (no read happened)
    # publishes a FRESH empty state -- never leave stale codes and never a
    # newSinceTs that would mis-fire the US-405 takeover (Bug-3b). The display
    # reads `source.dtc.available == false` and renders NA, not a false all-clear.
    if not dtcAvailable:
        codes = []
        newSinceTs = None
        mil = False
    enriched = [enrichCode(raw, severityTable) for raw in codes]
    return {
        "mil": bool(mil),
        "codes": enriched,
        "newSinceTs": newSinceTs,
        "clearGate": _computeClearGate(enriched),
        "sessionResetLock": list(sessionResetLock or []),
        "source": {
            SOURCE_DTC: buildSourceState(
                dtcAvailable, dtcUnavailableReason or REASON_DTC_NOT_READ
            )
        },
        "ts": nowIso,
    }


def makeDtcEmitter(
    statesDir: str,
    *,
    severityTable: dict[str, dict],
    nowIsoFn: Callable[[], str] | None = None,
) -> Callable[..., None]:
    """Build the `dtc` emit callable owned by the DTC capture path (US-404).

    The returned callable takes the just-captured codes (KOEO or drive read),
    merges Spool's severity table, and writes the `dtc` SSOT atomically.
    Best-effort by contract: a write failure is logged but NEVER raised, so the
    emit hook can never block the connection-edge DTC read.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        severityTable: Spool's static P1xxx severity map (loaded once at
            construction from the SSOT markdown).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        The emit callable.
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, DTC_FILENAME)

    def emit(
        *,
        codes: list[dict],
        mil: bool,
        newSinceTs: str | None = None,
        sessionResetLock: list[str] | None = None,
        dtcAvailable: bool = True,
        dtcUnavailableReason: str | None = None,
    ) -> None:
        try:
            payload = buildDtcState(
                codes=codes,
                severityTable=severityTable,
                mil=mil,
                newSinceTs=newSinceTs,
                sessionResetLock=sessionResetLock,
                nowIso=nowFn(),
                dtcAvailable=dtcAvailable,
                dtcUnavailableReason=dtcUnavailableReason,
            )
            ensureStatesDir(statesDir)
            writeStateAtomic(target, payload)
        except Exception as exc:  # noqa: BLE001 -- best-effort, never block capture
            logger.error(
                "dtc emit failed (%s) -- ignored (the dashboard hook never "
                "blocks the DTC capture path)",
                exc,
            )

    return emit
