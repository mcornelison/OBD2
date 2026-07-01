################################################################################
# File Name: ltft_trend_emitter.py
# Purpose/Description: F-096 `ltft-trend` state emitter [US-420]. The reader +
#   schema + best-effort writer for the `ltft-trend` SSOT the carousel LTFT
#   Trend card (US-420) consumes. Long-Term Fuel Trim is a slow-moving multi-
#   drive signal (F-096: "multi-drive view, NOT per-drive"): a healthy tune
#   migrates the trim TOWARD 0, while a persistent drift beyond +/-10 % flags a
#   vacuum leak / failing sensor / fuel-delivery fault. The source is the Pi's
#   own `realtime_data` table (parameter_name='LONG_FUEL_TRIM_1', the single
#   4G63 bank), aggregated per drive; `drive_summary` supplies the drive start
#   time for the axis label. Honest-instrument by contract (specs/ssot-design-
#   pattern.md): this module is the SINGLE authoritative provider of the LTFT
#   verdict -- it CLASSIFIES the drift here (ok / amber / down) so the carousel
#   card only maps the verdict -> colour, never classifies. Two honesty traps
#   are locked at this data contract:
#     * insufficient data (< MIN_DRIVES_FOR_TREND real drives) NEVER renders a
#       confident GREEN -- the headline `level` is forced to `insufficient`, so
#       a single in-band reading can't masquerade as a healthy trend.
#     * only `data_source='real'` drives feed the trend (fixture / replay /
#       physics_sim -- and the US-424 foreign-vehicle marker -- are excluded), so
#       a bench-seeded or foreign drive can never pollute the tune signal.
#   Mirrors the F-103 / system-status / battery-health / dtc emitter seam;
#   reuses ensureStatesDir + writeStateAtomic so there is one provisioning +
#   atomic-write impl (C-5). Thresholds grounded in offices/tuner/cards/
#   safe-range-fuel-trims.md (normal +/-5 %, danger > +/-10 %).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Ralph (Rex)  | Initial -- US-420 `ltft-trend` emitter (multi-
#               |              | drive LTFT trend card, F-096).
# ================================================================================
################################################################################

"""`ltft-trend` reader + schema builder + best-effort emit factory (F-096 / US-420)."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

# The single SSOT slot the carousel LTFT Trend card polls (4 Hz tmpfs read).
LTFT_TREND_FILENAME = "ltft-trend"

# The 4G63 is a single-bank inline-4, so bank-1 LTFT is THE trim signal (bank 2
# is unlogged on this ECU). Pinned here so the source PID has one definition.
LTFT_PID = "LONG_FUEL_TRIM_1"

# Drift bands (percent, absolute). Grounded in offices/tuner/cards/
# safe-range-fuel-trims.md + the US-420 acceptance criteria:
#   |LTFT| <= 5   -> ok    (normal band; a healthy tune sits here / migrates here)
#   5 < |LTFT| <=10 -> amber (attention -- watch the migration direction)
#   |LTFT| > 10   -> down  (drift; vacuum leak / failing sensor / fuel delivery)
LTFT_OK_ABS = 5.0
LTFT_DRIFT_ABS = 10.0

# A "trend" is multi-drive by definition (F-096) -- one drive is not a trend, so
# below this the card renders the honest insufficient-data state (never green).
MIN_DRIVES_FOR_TREND = 2

# How many recent drives the trend spans by default (the card shows the last N).
DEFAULT_TREND_DRIVES = 10

# Migration is only "improving"/"worsening" past this dead-band (percent), so
# drive-to-drive float noise doesn't flip the verdict.
TREND_EPSILON_PCT = 0.5

# Headline verdict levels the card maps -> colour (it never classifies).
LEVEL_OK = "ok"
LEVEL_AMBER = "amber"
LEVEL_DOWN = "down"
LEVEL_INSUFFICIENT = "insufficient"

# Trend directions (migration of |LTFT| across the window).
TREND_IMPROVING = "improving"  # |LTFT| shrinking toward 0 -- the healthy direction
TREND_WORSENING = "worsening"  # |LTFT| growing away from 0
TREND_STABLE = "stable"

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "DEFAULT_TREND_DRIVES",
    "LEVEL_AMBER",
    "LEVEL_DOWN",
    "LEVEL_INSUFFICIENT",
    "LEVEL_OK",
    "LTFT_DRIFT_ABS",
    "LTFT_OK_ABS",
    "LTFT_PID",
    "LTFT_TREND_FILENAME",
    "MIN_DRIVES_FOR_TREND",
    "TREND_IMPROVING",
    "TREND_STABLE",
    "TREND_WORSENING",
    "buildLtftTrendState",
    "classifyLtftDrift",
    "makeLtftTrendEmitter",
    "readLtftTrend",
]


def _round2(value: float | None) -> float | None:
    """Round to 2 decimals (a clean data-contract number), pass None through."""
    return None if value is None else round(float(value), 2)


def classifyLtftDrift(ltftAbs: float) -> str:
    """Classify one absolute LTFT magnitude into a honest drift level (pure).

    Args:
        ltftAbs: The ABSOLUTE fuel-trim magnitude in percent (sign already
            dropped -- a -8 % trim and a +8 % trim are equally far from 0).

    Returns:
        ``LEVEL_OK`` when within the normal +/-5 % band, ``LEVEL_AMBER`` in the
        5-10 % attention band, ``LEVEL_DOWN`` beyond +/-10 % (drift). Boundaries
        are inclusive on the healthy side (exactly 5 % is still ok, exactly 10 %
        is still amber) so a code-defined threshold is never a magic literal.
    """
    magnitude = abs(ltftAbs)
    if magnitude <= LTFT_OK_ABS:
        return LEVEL_OK
    if magnitude <= LTFT_DRIFT_ABS:
        return LEVEL_AMBER
    return LEVEL_DOWN


def readLtftTrend(
    conn: sqlite3.Connection,
    *,
    pid: str = LTFT_PID,
    driveLimit: int = DEFAULT_TREND_DRIVES,
) -> list[dict]:
    """Aggregate per-drive LTFT for the last N real drives (oldest -> newest).

    Reads the Pi-local ``realtime_data`` (the SSOT for captured trims), grouping
    the LTFT PID by drive. Only ``data_source='real'`` rows with a non-NULL
    ``drive_id`` count -- fixture/replay/sim (and the US-424 foreign marker) are
    excluded so a bench or foreign drive can never enter the tune trend.
    ``drive_summary`` is LEFT-joined for the drive-start axis label (NULL when a
    drive has trims but no summary row -- carried honestly, never fabricated).

    Args:
        conn: An open SQLite connection to the Pi database.
        pid: The LTFT parameter name (defaults to the bank-1 SSOT ``LTFT_PID``).
        driveLimit: How many most-recent drives to include (>=1).

    Returns:
        A list of per-drive dicts ordered OLDEST -> NEWEST (the natural trend
        axis): ``{driveId, ts, ltftAvg, ltftMin, ltftMax, sampleCount}``. Empty
        when no real LTFT rows exist. ``ts`` is None for a drive with no summary.
    """
    limit = max(1, int(driveLimit))
    # Recency by drive_id (monotone, minted by drive_counter, and always present
    # on the row) -- robust even when a drive lacks a drive_summary timestamp.
    rows = conn.execute(
        """
        SELECT rd.drive_id                AS drive_id,
               ds.drive_start_timestamp   AS ts,
               AVG(rd.value)              AS ltft_avg,
               MIN(rd.value)              AS ltft_min,
               MAX(rd.value)              AS ltft_max,
               COUNT(*)                   AS sample_count
          FROM realtime_data rd
          LEFT JOIN drive_summary ds ON ds.drive_id = rd.drive_id
         WHERE rd.parameter_name = ?
           AND rd.data_source = 'real'
           AND rd.drive_id IS NOT NULL
         GROUP BY rd.drive_id
         ORDER BY rd.drive_id DESC
         LIMIT ?
        """,
        (pid, limit),
    ).fetchall()

    # The query returns newest-first (for the LIMIT); reverse to oldest-first so
    # the trend reads left-to-right in chronological order.
    drives: list[dict] = []
    for driveId, ts, ltftAvg, ltftMin, ltftMax, sampleCount in reversed(rows):
        drives.append(
            {
                "driveId": int(driveId),
                "ts": ts,
                "ltftAvg": _round2(ltftAvg),
                "ltftMin": _round2(ltftMin),
                "ltftMax": _round2(ltftMax),
                "sampleCount": int(sampleCount),
            }
        )
    return drives


def _trendDirection(drives: list[dict]) -> str | None:
    """Classify the migration of |LTFT| across the window (pure).

    Compares the newest drive's absolute trim to the oldest's: shrinking toward
    0 past the epsilon dead-band is ``TREND_IMPROVING`` (the healthy direction),
    growing is ``TREND_WORSENING``, otherwise ``TREND_STABLE``. None when there
    are fewer than two points (a single drive has no direction).
    """
    if len(drives) < 2:
        return None
    firstAbs = abs(drives[0]["ltftAvg"])
    lastAbs = abs(drives[-1]["ltftAvg"])
    if lastAbs < firstAbs - TREND_EPSILON_PCT:
        return TREND_IMPROVING
    if lastAbs > firstAbs + TREND_EPSILON_PCT:
        return TREND_WORSENING
    return TREND_STABLE


def buildLtftTrendState(
    *,
    drives: list[dict],
    nowIso: str,
    pid: str = LTFT_PID,
    minDrives: int = MIN_DRIVES_FOR_TREND,
) -> dict:
    """Assemble the `ltft-trend` payload (pure; the card's pinned schema).

    Classifies each drive's average trim + the headline verdict here (the SSOT),
    so the carousel card only maps the level -> colour. The insufficient-data
    guard is locked in this builder: below ``minDrives`` real drives the headline
    ``level`` is ``LEVEL_INSUFFICIENT`` regardless of any single in-band reading,
    so the card can never render a confident GREEN off too little data.

    Args:
        drives: Per-drive aggregates OLDEST -> NEWEST (see :func:`readLtftTrend`).
        nowIso: ISO-8601 emission timestamp (freshness marker).
        pid: The source PID (carried into the payload for provenance).
        minDrives: Fewest real drives that count as a multi-drive trend.

    Returns:
        The `ltft-trend` dict: ``pid`` / ``sufficient`` / ``level`` /
        ``driveCount`` / ``minDrives`` / ``okAbs`` / ``driftAbs`` / ``trend`` /
        ``current`` / ``points`` / ``ts``. ``points`` are oldest->newest, each
        carrying its own drift ``level``; ``current`` is the newest point (or
        None when there are no drives).
    """
    points: list[dict] = []
    for d in drives:
        avg = d["ltftAvg"]
        points.append(
            {
                "driveId": d["driveId"],
                "ts": d.get("ts"),
                "ltftAvg": avg,
                "level": classifyLtftDrift(avg),
                "sampleCount": d.get("sampleCount"),
            }
        )

    current = points[-1] if points else None
    sufficient = len(points) >= minDrives
    # Honest-instrument: an insufficient trend NEVER inherits a green/ok verdict.
    if not sufficient:
        headlineLevel = LEVEL_INSUFFICIENT
    else:
        headlineLevel = current["level"]

    return {
        "pid": pid,
        "sufficient": sufficient,
        "level": headlineLevel,
        "driveCount": len(points),
        "minDrives": minDrives,
        "okAbs": LTFT_OK_ABS,
        "driftAbs": LTFT_DRIFT_ABS,
        "trend": _trendDirection(points) if sufficient else None,
        "current": current,
        "points": points,
        "ts": nowIso,
    }


def makeLtftTrendEmitter(
    statesDir: str,
    *,
    trendReader: Callable[[], list[dict]],
    nowIsoFn: Callable[[], str] | None = None,
    pid: str = LTFT_PID,
    minDrives: int = MIN_DRIVES_FOR_TREND,
) -> Callable[[], None]:
    """Build the `ltft-trend` emit callable (F-096 / US-420).

    The returned zero-arg callable reads the per-drive aggregates via the
    injected ``trendReader`` (the DB seam -- kept out of this module so the
    builder stays pure + node-parallel testable), classifies them, and writes
    the `ltft-trend` SSOT atomically. Best-effort by contract: a read/write
    failure is logged but NEVER raised, so the emit hook can never block its
    owning tier.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        trendReader: A zero-arg callable returning the per-drive aggregates
            (typically ``lambda: readLtftTrend(openDb(), ...)``).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).
        pid: The source PID carried into the payload.
        minDrives: Fewest real drives that count as a trend.

    Returns:
        The emit callable.
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, LTFT_TREND_FILENAME)

    def emit() -> None:
        try:
            drives = trendReader()
            payload = buildLtftTrendState(
                drives=drives,
                nowIso=nowFn(),
                pid=pid,
                minDrives=minDrives,
            )
            ensureStatesDir(statesDir)
            writeStateAtomic(target, payload)
        except Exception as exc:  # noqa: BLE001 -- best-effort, never block the owner
            logger.error(
                "ltft-trend emit failed (%s) -- ignored (the dashboard hook never "
                "blocks its owning tier)",
                exc,
            )

    return emit
