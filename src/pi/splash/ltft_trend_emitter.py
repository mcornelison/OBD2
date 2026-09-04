################################################################################
# File Name: ltft_trend_emitter.py
# Purpose/Description: F-096 `ltft-trend` state emitter. The reader + schema +
#   best-effort writer for the `ltft-trend` SSOT the carousel Fuel Trim card
#   consumes.
#
#   US-661 REBUILT THIS AGAINST SPOOL'S TUNER-005 CONTRACT (specs/
#   grounded-knowledge.md, "LTFT trend contract (US-661)", added 2026-08-31),
#   which SUPERSEDES the offices/tuner/cards/safe-range-fuel-trims.md bands the
#   US-420 version was built on. The original was never wired to a producer, so
#   nothing it computed ever reached a panel -- which is fortunate, because it
#   was precisely the implementation Spool's contract opens by forbidding:
#
#       "A naive implementation (mean LTFT per drive, plot the points, join
#        them) draws a chart that wanders up to 3.72 pp between drives on the
#        same day with nothing wrong. Anyone reading that for drift finds
#        drift, every time."
#
#   Four things changed, each traceable to a measurement in that section:
#
#     1. A PER-SAMPLE GATE, all three ANDed: coolant >= 85 C AND fuel-system
#        status == 2 (closed loop) AND >= 20 qualifying samples in the drive.
#        Loop status ALONE is not a warm-up gate on this car -- the O2 sensor is
#        heated, so at 30-40 C coolant 65 of 68 buckets already report closed
#        loop. Coolant is the load-bearing condition.
#     2. THE HEADLINE IS A ROLLING 5-DRIVE MEDIAN, never the per-drive line. At
#        an SD of 1.43 pp between drives, a 5-drive median resolves to about
#        +/-0.6 pp and a single drive resolves to nothing.
#     3. THE VERDICT IS RELATIVE TO THE CURRENT EPOCH'S BASELINE, not to zero.
#        The prior ECU's grand mean was -2.311 % and the current one's is
#        +0.009 %; scoring absolute distance from zero spends an epoch's whole
#        noise budget on a difference that is not a fault.
#     4. EPOCH BOUNDARIES BREAK THE SERIES. An adaptive-memory reset is detected
#        by LTFT being BIT-IDENTICAL to exactly 0.000 for a whole drive -- NOT
#        by zero variance, which false-positives on drive 33 (zero variance at
#        -2.344, a short drive parked in one load cell).
#
#   THE ALIGNMENT IS AS-OF (SAMPLE-AND-HOLD), AND THAT IS LOAD-BEARING. The gate
#   is per-sample, but `realtime_data` is long/narrow and `data/logger.py` stamps
#   `utcIsoNow()` PER READING, at second resolution -- so the parameters in one
#   Bluetooth round-robin land on different timestamps whenever the cycle
#   crosses a second boundary. An exact-timestamp join does not fail cleanly; it
#   matches SOMETIMES, silently dropping most qualifying samples. Each LTFT
#   sample is therefore gated against the most recent coolant/status reading AT
#   OR BEFORE it, and the hold FAILS CLOSED past GATE_HOLD_MAX_SECONDS: an
#   unknown state never resolves to "warm".
#
#   Honest-instrument by contract (specs/ssot-design-pattern.md): this module is
#   the SINGLE authoritative provider of the LTFT verdict -- it classifies here
#   so the carousel card only maps verdict -> colour. While the gate is unmet it
#   publishes a TYPED ABSENCE with a reason and never a number that failed the
#   gate. Spool measured that resting state as permanent for roughly one drive
#   in four (5 of the 22 post-reset drives never reach 20 qualifying samples) --
#   an absent trend is not a failed producer.
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
# 2026-09-04    | Ralph (Rex)  | US-661 -- rebuilt against Spool's TUNER-005
#               |              | contract: per-sample as-of gate, 5-drive
#               |              | median, epoch boundaries, epoch-relative
#               |              | verdict, typed WARMING absence, total trim.
# ================================================================================
################################################################################

"""`ltft-trend` reader + schema builder + emit factory (F-096 / US-420 / US-661)."""

from __future__ import annotations

import logging
import os
import sqlite3
import statistics
from collections.abc import Callable
from datetime import UTC, datetime

# Reuse the boot-state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)

# The single SSOT slot the carousel Fuel Trim card polls (4 Hz tmpfs read).
LTFT_TREND_FILENAME = "ltft-trend"

# The 4G63 is a single-bank inline-4, so bank-1 LTFT is THE trim signal (bank 2
# is unlogged on this ECU). Pinned here so the source PID has one definition.
LTFT_PID = "LONG_FUEL_TRIM_1"
STFT_PID = "SHORT_FUEL_TRIM_1"

# The two gate parameters. `FUEL_SYSTEM_STATUS` stores the NUMERIC enum code in
# `realtime_data.value` (the text label -- 'CL', 'OL-drive' -- rides in `unit`),
# so the contract's `== 2` is a comparison on `value`. See obdii/decoders.py
# `_FUEL_STATUS_ENUM`.
COOLANT_PID = "COOLANT_TEMP"
FUEL_SYSTEM_PID = "FUEL_SYSTEM_STATUS"

# ---------------------------------------------------------------------------
# The gate. All three ANDed; a sample failing any of them is not eligible.
# Every value here is MEASURED -- specs/grounded-knowledge.md, "LTFT trend
# contract (US-661)". None of them is a tuning knob.
# ---------------------------------------------------------------------------

GATE_COOLANT_MIN_C = 85.0

# Fuel-system status 2 == closed loop. Deliberately NOT `!= 1`: status 3 is open
# loop under LOAD OR DECEL -- a WARM state (mean coolant 89.0 C, mean RPM 2515),
# not a temperature state -- and the enrichment trims it carries are not the
# closed-loop correction this card reports. A coolant-only gate would admit it.
FUEL_SYSTEM_CLOSED_LOOP = 2

# ~100 s of qualifying operation at the ~5 s LTFT cadence.
GATE_MIN_QUALIFYING_SAMPLES = 20

# How long a coolant / loop-status reading may be held forward over an LTFT
# sample before that sample becomes ineligible. FAIL CLOSED: holding a gate
# reading indefinitely is the latched-channel defect specs/ssot-design-pattern.md
# calls out, and "we have not measured coolant recently" must never resolve to
# "the engine is warm". Sized at 6 poll cycles against the ~5 s cadence implied
# by the contract's own "20 samples ~= 100 s"; generous enough to survive a
# dropped poll, far too short to carry a stale reading across a key cycle.
GATE_HOLD_MAX_SECONDS = 30.0

# ---------------------------------------------------------------------------
# Window, epoch and verdict bands.
# ---------------------------------------------------------------------------

# "Display a rolling 5-drive MEDIAN, never the raw per-drive line."
TREND_MEDIAN_WINDOW = 5

# The between-drive noise floor: drive means spread up to 3.72 pp on the SAME
# DAY on a healthy engine, between-drive SD 1.43 pp. A deviation smaller than
# this carries no information, so nothing below it may raise a verdict.
LTFT_NOISE_FLOOR_PP = 4.0

# The conventional fault line. Spool records it as a CONVENTION that has NEVER
# fired on this car and is UNTESTED here; it is retained because the faults it
# names (vacuum leak, failing injector, clogged filter, MAF drift) move LTFT by
# 10-25 pp, not 3. Absolute, not epoch-relative: at this magnitude the epoch
# baseline is no longer the interesting comparison.
LTFT_FAULT_ABS = 10.0

# An adaptive-memory reset reads BIT-IDENTICAL zero for a whole drive.
RESET_EXACT_VALUE = 0.0

# How many recent drives the reader spans. Wide enough to hold a whole epoch
# (Spool's post-reset epoch is 17 qualifying drives across 22) so the baseline
# is computed from the epoch rather than from a window that clips it.
DEFAULT_TREND_DRIVES = 20

# Migration is only "improving"/"worsening" past this dead-band (percent), so
# median-to-median float noise doesn't flip the verdict.
TREND_EPSILON_PCT = 0.5

# Headline verdict levels the card maps -> colour (it never classifies).
LEVEL_OK = "ok"
LEVEL_AMBER = "amber"
LEVEL_DOWN = "down"
LEVEL_INSUFFICIENT = "insufficient"

# Trend directions (migration of the rolling median across the epoch).
TREND_IMPROVING = "improving"  # |median| shrinking toward the baseline
TREND_WORSENING = "worsening"  # |median| growing away from it
TREND_STABLE = "stable"

# Typed-absence reasons. Three DIFFERENT facts, deliberately distinguishable:
# "the engine has not warmed up" is not "we have not driven enough" and neither
# is "nothing has ever been recorded".
REASON_WARMING = "WARMING - NOT YET MEANINGFUL"
REASON_INSUFFICIENT_HISTORY = "not enough qualifying drives yet"
REASON_NO_DRIVES = "no real drives recorded"

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "COOLANT_PID",
    "DEFAULT_TREND_DRIVES",
    "FUEL_SYSTEM_CLOSED_LOOP",
    "FUEL_SYSTEM_PID",
    "GATE_COOLANT_MIN_C",
    "GATE_HOLD_MAX_SECONDS",
    "GATE_MIN_QUALIFYING_SAMPLES",
    "LEVEL_AMBER",
    "LEVEL_DOWN",
    "LEVEL_INSUFFICIENT",
    "LEVEL_OK",
    "LTFT_FAULT_ABS",
    "LTFT_NOISE_FLOOR_PP",
    "LTFT_PID",
    "LTFT_TREND_FILENAME",
    "REASON_INSUFFICIENT_HISTORY",
    "REASON_NO_DRIVES",
    "REASON_WARMING",
    "STFT_PID",
    "TREND_IMPROVING",
    "TREND_MEDIAN_WINDOW",
    "TREND_STABLE",
    "TREND_WORSENING",
    "buildDriveRecords",
    "buildLtftTrendState",
    "isAdaptiveResetDrive",
    "makeLtftTrendEmitter",
    "qualifyingLtftSamples",
    "qualifyingSamples",
    "readLtftDriveRows",
    "readLtftDriveRowsFrom",
    "rollingMedian",
]


def _round2(value: float | None) -> float | None:
    """Round to 2 decimals (a clean data-contract number), pass None through."""
    return None if value is None else round(float(value), 2)


def _epochSeconds(ts: str) -> float | None:
    """Parse a canonical ISO-8601 UTC stamp to epoch seconds, or None."""
    try:
        return datetime.strptime(ts, _ISO_FMT).replace(tzinfo=UTC).timestamp()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def qualifyingSamples(
    rows: list[tuple[str, str, float]],
    pid: str = LTFT_PID,
    *,
    coolantMinC: float = GATE_COOLANT_MIN_C,
    closedLoop: int = FUEL_SYSTEM_CLOSED_LOOP,
    holdMaxSeconds: float = GATE_HOLD_MAX_SECONDS,
) -> list[float]:
    """Select the samples of ``pid`` that pass Spool's warm closed-loop gate.

    Walks one drive's rows in time order carrying the most recent coolant and
    fuel-system-status reading forward (an AS-OF / sample-and-hold join). A
    sample of ``pid`` is eligible only when BOTH held readings exist, BOTH are
    no older than ``holdMaxSeconds``, coolant is at or above ``coolantMinC`` and
    the status is exactly ``closedLoop``.

    The as-of join is not a convenience: the three parameters are written on
    separate second-resolution timestamps, so an equality join silently drops
    most of the corpus. Unknown gate state FAILS CLOSED -- an LTFT sample with
    no recent coolant reading is ineligible, never assumed warm.

    Args:
        rows: One drive's ``(timestamp, parameter_name, value)`` rows. Sorted
            here defensively; ties keep their input order.
        pid: The parameter being gated (LTFT, or STFT for the total-trim value).
        coolantMinC: Minimum coolant temperature in Celsius (inclusive).
        closedLoop: The fuel-system-status enum code meaning closed loop.
        holdMaxSeconds: Maximum age of a held gate reading.

    Returns:
        The eligible values of ``pid``, oldest first. Empty when none qualify.
    """
    ordered = sorted(rows, key=lambda row: row[0])

    coolantValue: float | None = None
    coolantAt: float | None = None
    statusValue: float | None = None
    statusAt: float | None = None
    eligible: list[float] = []

    for ts, name, value in ordered:
        at = _epochSeconds(ts)
        if at is None:
            continue
        if name == COOLANT_PID:
            coolantValue, coolantAt = float(value), at
            continue
        if name == FUEL_SYSTEM_PID:
            statusValue, statusAt = float(value), at
            continue
        if name != pid:
            continue
        # Fail closed on every unknown: never seen, or seen too long ago.
        if coolantAt is None or statusAt is None:
            continue
        if (at - coolantAt) > holdMaxSeconds or (at - statusAt) > holdMaxSeconds:
            continue
        if coolantValue is None or coolantValue < coolantMinC:
            continue
        if statusValue is None or int(statusValue) != closedLoop:
            continue
        eligible.append(float(value))

    return eligible


def qualifyingLtftSamples(
    rows: list[tuple[str, str, float]],
    **kwargs: object,
) -> list[float]:
    """The warm closed-loop LTFT samples of one drive (see :func:`qualifyingSamples`)."""
    return qualifyingSamples(rows, LTFT_PID, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Epoch detection
# ---------------------------------------------------------------------------


def isAdaptiveResetDrive(ltftValues: list[float]) -> bool:
    """True when a drive's LTFT is bit-identical to exactly 0.000 throughout.

    THE TEST IS BIT-IDENTITY TO ZERO, NOT ZERO VARIANCE, and the difference is
    measured rather than stylistic: drive 33 has zero variance at -2.344 (a
    short drive parked in one load cell) and is NOT a reset, while drives 35/36
    are bit-identical 0.000 and ARE. Bit-identity needs no tuned threshold and
    cannot false-positive.

    Args:
        ltftValues: EVERY LTFT sample in the drive -- not only the qualifying
            ones. A reset zeroes the trim in all conditions, and the drives that
            prove it (35/36, flat battery) are exactly the sort that may not
            reach the qualifying floor.

    Returns:
        True when the drive has samples and all of them are exactly zero. An
        empty drive is False -- an absence is not a measurement of zero.
    """
    if not ltftValues:
        return False
    return all(float(value) == RESET_EXACT_VALUE for value in ltftValues)


def rollingMedian(values: list[float], window: int) -> list[float]:
    """Every full-window median across ``values``, oldest window first.

    Args:
        values: The per-drive points, oldest -> newest.
        window: Window width in drives.

    Returns:
        One median per complete window; empty when there are fewer than
        ``window`` values (a partial window is not reported as a median).
    """
    if window <= 0 or len(values) < window:
        return []
    return [
        float(statistics.median(values[i : i + window]))
        for i in range(len(values) - window + 1)
    ]


# ---------------------------------------------------------------------------
# Per-drive records
# ---------------------------------------------------------------------------


def buildDriveRecords(
    perDrive: dict[int, tuple[str | None, list[tuple[str, str, float]]]],
    *,
    minSamples: int = GATE_MIN_QUALIFYING_SAMPLES,
) -> list[dict]:
    """Reduce each drive's raw rows to one gated record (pure).

    Args:
        perDrive: ``{driveId: (driveStartTimestamp | None, rows)}``.
        minSamples: The qualifying-sample floor below which a drive yields NO
            point (``ltftMean`` is None -- never a mean of too few samples).

    Returns:
        Records ordered by drive id ascending, each
        ``{driveId, ts, sampleCount, qualifyingCount, ltftMean, stftMean,
        isReset}``.
    """
    records: list[dict] = []
    for driveId in sorted(perDrive):
        ts, rows = perDrive[driveId]
        allLtft = [float(v) for _t, name, v in rows if name == LTFT_PID]
        ltftEligible = qualifyingSamples(rows, LTFT_PID)
        stftEligible = qualifyingSamples(rows, STFT_PID)
        records.append(
            {
                "driveId": int(driveId),
                "ts": ts,
                "sampleCount": len(allLtft),
                "qualifyingCount": len(ltftEligible),
                "ltftMean": (
                    _round2(statistics.fmean(ltftEligible))
                    if len(ltftEligible) >= minSamples
                    else None
                ),
                "stftMean": (
                    _round2(statistics.fmean(stftEligible))
                    if len(stftEligible) >= minSamples
                    else None
                ),
                "isReset": isAdaptiveResetDrive(allLtft),
            }
        )
    return records


def _currentEpoch(records: list[dict]) -> tuple[list[dict], bool, int | None]:
    """Split off the drives since the most recent epoch boundary.

    Returns:
        ``(epochRecords, epochBreak, epochStartDriveId)``. The reset drive
        itself is the BOUNDARY and belongs to neither side, so it is excluded.
    """
    lastResetIndex: int | None = None
    for index, record in enumerate(records):
        if record["isReset"]:
            lastResetIndex = index
    if lastResetIndex is None:
        epoch = list(records)
        return (epoch, False, epoch[0]["driveId"] if epoch else None)
    epoch = records[lastResetIndex + 1 :]
    return (epoch, True, epoch[0]["driveId"] if epoch else None)


def _trendDirection(medians: list[float]) -> str | None:
    """Classify the migration of the rolling median, as distance from ZERO.

    DELIBERATELY NOT MEASURED AGAINST THE EPOCH BASELINE, and the two references
    answer different questions. The VERDICT asks "is this engine off its own
    normal?", which is only meaningful relative to the epoch baseline. The TREND
    asks "is the ECU having to apply more correction or less?", which is
    magnitude from zero -- that is what "migrating toward 0" means on the card
    and it is the physically meaningful reading.

    Measuring the trend against the baseline as well would also be arithmetically
    self-defeating: the baseline is the epoch's own MEAN, so any monotonic series
    necessarily ends FURTHER from it than it began, and a steadily improving
    engine would report "worsening".
    """
    if len(medians) < 2:
        return None
    firstAbs = abs(medians[0])
    lastAbs = abs(medians[-1])
    if lastAbs < firstAbs - TREND_EPSILON_PCT:
        return TREND_IMPROVING
    if lastAbs > firstAbs + TREND_EPSILON_PCT:
        return TREND_WORSENING
    return TREND_STABLE


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------


def buildLtftTrendState(
    *,
    driveRecords: list[dict],
    nowIso: str,
    pid: str = LTFT_PID,
    medianWindow: int = TREND_MEDIAN_WINDOW,
) -> dict:
    """Assemble the `ltft-trend` payload (pure; the card's pinned schema).

    Everything the card renders is decided HERE (the SSOT): the epoch, the
    rolling median, the epoch baseline, the deviation and the verdict. The
    carousel maps level -> colour and never classifies.

    Args:
        driveRecords: Per-drive records from :func:`buildDriveRecords`.
        nowIso: ISO-8601 emission timestamp (freshness marker).
        pid: The source PID, carried into the payload for provenance.
        medianWindow: Width of the rolling median, in drives.

    Returns:
        The `ltft-trend` dict. When the gate or the history is unmet, a TYPED
        ABSENCE: ``median``/``baseline``/``deviationPp``/``current`` are None,
        ``points`` is empty or short, ``level`` is ``insufficient`` and
        ``reason`` says WHICH absence it is.
    """
    epoch, epochBreak, epochStartDriveId = _currentEpoch(driveRecords)
    points = [
        {
            "driveId": record["driveId"],
            "ts": record["ts"],
            "ltftAvg": record["ltftMean"],
            "sampleCount": record["qualifyingCount"],
        }
        for record in epoch
        if record["ltftMean"] is not None
    ]

    state: dict = {
        "pid": pid,
        "sufficient": False,
        "level": LEVEL_INSUFFICIENT,
        "reason": None,
        "median": None,
        "medianWindow": medianWindow,
        "baseline": None,
        "deviationPp": None,
        "sustained": False,
        "totalTrim": None,
        "trend": None,
        "current": None,
        "points": points,
        "driveCount": len(points),
        "minDrives": medianWindow,
        "epochBreak": epochBreak,
        "epochStartDriveId": epochStartDriveId,
        "epochDriveCount": len(epoch),
        "noiseFloorPp": LTFT_NOISE_FLOOR_PP,
        "faultAbs": LTFT_FAULT_ABS,
        "gate": {
            "coolantMinC": GATE_COOLANT_MIN_C,
            "closedLoopCode": FUEL_SYSTEM_CLOSED_LOOP,
            "minQualifyingSamples": GATE_MIN_QUALIFYING_SAMPLES,
        },
        "ts": nowIso,
    }

    if not driveRecords:
        state["reason"] = REASON_NO_DRIVES
        return state
    if not points:
        # Drives exist but none cleared the warm closed-loop gate. Spool measured
        # this as PERMANENT for roughly one drive in four -- not a defect, and
        # not a temporary condition pending the producer.
        state["reason"] = REASON_WARMING
        return state

    values = [float(point["ltftAvg"]) for point in points]
    medians = rollingMedian(values, medianWindow)
    if not medians:
        state["reason"] = REASON_INSUFFICIENT_HISTORY
        return state

    # The baseline is the epoch's own grand mean; the headline is the MOST
    # RECENT full window. A short epoch therefore reports a deviation near zero
    # -- which is honest: with five drives you cannot separate drift from the
    # baseline it would be measured against.
    baseline = float(statistics.fmean(values))
    median = medians[-1]
    deviation = median - baseline

    if abs(median) >= LTFT_FAULT_ABS:
        level = LEVEL_DOWN
    elif abs(deviation) >= LTFT_NOISE_FLOOR_PP:
        level = LEVEL_AMBER
    else:
        level = LEVEL_OK

    current = points[-1]
    # THE STFT HALF MUST COME FROM THE SAME DRIVE AS THE LTFT HALF. `current` is
    # the newest drive WITH A QUALIFYING LTFT POINT, which is not necessarily the
    # newest drive in the epoch: the gate is per-sample and each parameter is
    # counted separately, so a drive can clear the 20-sample floor for STFT and
    # miss it for LTFT. Reading `epoch[-1]` here summed two DIFFERENT drives into
    # a value the contract defines as "the total correction being applied now" --
    # a number no drive ever measured, and one that can land outside the healthy
    # -1.37..+4.05 range on entirely healthy data.
    currentRecord = next(
        (record for record in epoch if record["driveId"] == current["driveId"]),
        None,
    )
    stftMean = currentRecord["stftMean"] if currentRecord is not None else None
    totalTrim = (
        _round2(float(current["ltftAvg"]) + float(stftMean))
        if stftMean is not None and current["ltftAvg"] is not None
        else None
    )

    state.update(
        {
            "sufficient": True,
            "level": level,
            "median": _round2(median),
            "baseline": _round2(baseline),
            "deviationPp": _round2(deviation),
            # Spool's warn is "sustained >= 3 qualifying drives". Carried as
            # DATA beside the verdict rather than gating it: a verdict that
            # stayed `ok` for two more drives while the median sat outside the
            # noise floor would be the cheap wrong answer in the other
            # direction.
            "sustained": all(
                abs(value - baseline) >= LTFT_NOISE_FLOOR_PP
                for value in medians[-3:]
            )
            and len(medians) >= 3,
            "totalTrim": totalTrim,
            "trend": _trendDirection(medians),
            "current": current,
        }
    )
    return state


# ---------------------------------------------------------------------------
# The DB seam
# ---------------------------------------------------------------------------


def readLtftDriveRows(
    conn: sqlite3.Connection,
    *,
    driveLimit: int = DEFAULT_TREND_DRIVES,
) -> dict[int, tuple[str | None, list[tuple[str, str, float]]]]:
    """Read the gate + trim rows for the last N real drives.

    Only ``data_source='real'`` rows with a non-NULL ``drive_id`` count --
    fixture/replay/physics_sim (and the US-424 foreign marker) are excluded so a
    bench or foreign drive can never enter the tune signal. ``drive_summary`` is
    LEFT-joined for the drive-start axis label, carried as None when absent
    rather than fabricated.

    Args:
        conn: An open SQLite connection to the Pi database.
        driveLimit: How many most-recent drives to include (>=1).

    Returns:
        ``{driveId: (driveStartTimestamp | None, rows)}`` where rows are
        ``(timestamp, parameter_name, value)`` in time order.
    """
    limit = max(1, int(driveLimit))
    rows = conn.execute(
        """
        SELECT rd.drive_id, ds.drive_start_timestamp, rd.timestamp,
               rd.parameter_name, rd.value
          FROM realtime_data rd
          LEFT JOIN drive_summary ds ON ds.drive_id = rd.drive_id
         WHERE rd.parameter_name IN (?, ?, ?, ?)
           AND rd.data_source = 'real'
           AND rd.drive_id IS NOT NULL
           AND rd.drive_id IN (
                 SELECT drive_id
                   FROM realtime_data
                  WHERE parameter_name = ?
                    AND data_source = 'real'
                    AND drive_id IS NOT NULL
                  GROUP BY drive_id
                  ORDER BY drive_id DESC
                  LIMIT ?
               )
         ORDER BY rd.drive_id ASC, rd.timestamp ASC, rd.id ASC
        """,
        (LTFT_PID, STFT_PID, COOLANT_PID, FUEL_SYSTEM_PID, LTFT_PID, limit),
    ).fetchall()

    perDrive: dict[int, tuple[str | None, list[tuple[str, str, float]]]] = {}
    for driveId, driveTs, ts, name, value in rows:
        entry = perDrive.setdefault(int(driveId), (driveTs, []))
        entry[1].append((ts, name, float(value)))
    return perDrive


def readLtftDriveRowsFrom(
    database: object | None,
    *,
    driveLimit: int = DEFAULT_TREND_DRIVES,
) -> dict[int, tuple[str | None, list[tuple[str, str, float]]]]:
    """Read the drive rows through a Pi ``database`` handle.

    The handle seam lives HERE rather than in the orchestrator mixin for the
    same reason ``readLastDriveSummary`` does: Atlas's A-17 guard
    (``test_cardStateEmitter_opensNoSecondObdConnection``) statically forbids
    ``.connect(`` anywhere in ``card_state_emitter.py``, because a second OBD
    connection there re-introduces the two-owner race. That guard is a text
    sweep and cannot tell a DATABASE connect from an OBD one -- which is a
    feature, not a gap: keeping every handle-opening call in a reader module is
    exactly the discipline that makes such a cheap guard sound.

    Args:
        database: An object exposing ``connect()`` as a context manager yielding
            a DB-API connection, or None (bench / not yet built in boot order).
        driveLimit: How many most-recent drives to include.

    Returns:
        The per-drive rows, or ``{}`` when there is no handle. Read failures
        PROPAGATE -- the emit factory logs them; swallowing them here would make
        an unreadable log indistinguishable from an empty one.
    """
    if database is None:
        return {}
    with database.connect() as conn:  # type: ignore[attr-defined]
        return readLtftDriveRows(conn, driveLimit=driveLimit)


# ---------------------------------------------------------------------------
# The emit factory
# ---------------------------------------------------------------------------


def makeLtftTrendEmitter(
    statesDir: str,
    *,
    driveRowsReader: Callable[
        [], dict[int, tuple[str | None, list[tuple[str, str, float]]]]
    ],
    nowIsoFn: Callable[[], str] | None = None,
    pid: str = LTFT_PID,
    medianWindow: int = TREND_MEDIAN_WINDOW,
) -> Callable[[], None]:
    """Build the `ltft-trend` emit callable (F-096 / US-420 / US-661).

    The returned zero-arg callable reads one drive-rows batch via the injected
    ``driveRowsReader`` (the DB seam -- kept out of this module so the builders
    stay pure and node-parallel testable), gates + classifies it, and writes the
    `ltft-trend` SSOT atomically. Best-effort by contract: a read/write failure
    is logged but NEVER raised, so the emit hook can never block its owning tier.

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        driveRowsReader: A zero-arg callable returning the per-drive rows
            (typically ``lambda: readLtftDriveRows(conn)``).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).
        pid: The source PID carried into the payload.
        medianWindow: Width of the rolling median, in drives.

    Returns:
        The emit callable.
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, LTFT_TREND_FILENAME)

    def emit() -> None:
        try:
            payload = buildLtftTrendState(
                driveRecords=buildDriveRecords(driveRowsReader()),
                nowIso=nowFn(),
                pid=pid,
                medianWindow=medianWindow,
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
