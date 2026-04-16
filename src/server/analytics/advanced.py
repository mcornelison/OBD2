################################################################################
# File Name: advanced.py
# Purpose/Description: Advanced analytics engine — multi-drive trends,
#                      cross-parameter correlations, and anomaly detection.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-159 — advanced
#               |              | analytics (trends/correlations/anomaly) per
#               |              | server spec §1.8
# ================================================================================
################################################################################

"""
Advanced analytics engine.

Three entry points, all taking a sync :class:`sqlalchemy.orm.Session`:

* :func:`computeTrends` — rolling avg of peak and avg across the last N drives
  for one parameter, slope-based direction classification (rising/falling/
  stable) with a drift threshold, persisted as a snapshot in
  ``trend_snapshots``.
* :func:`computeCorrelations` — Pearson correlation between drive-level
  aggregates of parameter pairs. Pairs are configurable via the ``pairs``
  argument and default to :data:`DEFAULT_CORRELATION_PAIRS`.
* :func:`detectAnomalies` — flags per-parameter deviations > 2σ against the
  historical envelope (mean ± 2·std of prior drives' avg_value). Results are
  persisted to ``anomaly_log``; re-running replaces rather than duplicates.

Configuration constants at the top of the module can be overridden by callers
that want non-default thresholds (e.g. a shorter trend window).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from src.server.analytics.helpers import classifyDeviation
from src.server.analytics.types import (
    AnomalyResult,
    ComparisonStatus,
    CorrelationResult,
    TrendDirection,
    TrendResult,
)
from src.server.db.models import (
    AnomalyLog,
    DriveStatistic,
    DriveSummary,
    TrendSnapshot,
)

# ---- Configuration constants ------------------------------------------------

# Default window for trend computation (spec §Configuration TREND_WINDOW_DRIVES)
DEFAULT_TREND_WINDOW: int = 10

# Minimum absolute drift (percent) to classify a trend as RISING/FALLING.
# Below this, the trend is STABLE regardless of slope sign. Spec §1.8.
TREND_DRIFT_THRESHOLD_PCT: float = 5.0

# Absolute Pearson r above which a correlation is considered significant.
# Spec §1.8.
CORRELATION_SIGNIFICANCE_THRESHOLD: float = 0.7

# Known tuning-relevant parameter pairs. Callers can pass their own sequence
# to :func:`computeCorrelations` instead; this constant is module-level to
# keep the function body free of hardcoded pairs (invariant).
DEFAULT_CORRELATION_PAIRS: tuple[tuple[str, str], ...] = (
    ("IAT", "KnockCount"),
    ("IAT", "STFT"),
    ("RPM", "CoolantTemp"),
    ("Boost", "AFR"),
)


# ---- Trend analysis ---------------------------------------------------------


def computeTrends(
    session: Session,
    parameterName: str,
    windowSize: int = DEFAULT_TREND_WINDOW,
) -> TrendResult | None:
    """
    Compute a rolling trend snapshot for ``parameterName``.

    Pulls the last ``windowSize`` drives that have a ``drive_statistics`` row
    for the parameter (ordered by ``drive_summary.start_time``), computes the
    mean of ``avg_value`` and ``max_value`` across those drives, fits a
    least-squares line to the ``avg_value`` series, and classifies direction
    as follows:

    * ``STABLE`` if absolute drift (first→last avg_value) is ≤ 5 %.
    * ``RISING`` if drift is > +5 % and slope is non-negative.
    * ``FALLING`` if drift is < -5 % and slope is non-positive.

    A :class:`TrendSnapshot` row is inserted on every call — the table
    accumulates snapshots over time, which is intentional (see spec §1.8).

    Args:
        session: Open SQLAlchemy session bound to the server database.
        parameterName: Parameter to trend (e.g. ``"RPM"``).
        windowSize: Max number of most-recent drives to include.

    Returns:
        A :class:`TrendResult`, or ``None`` if no drive has stats for this
        parameter.
    """
    rows = _loadRecentAvgs(session, parameterName, windowSize)
    if not rows:
        return None

    avgs = [float(r.avg_value or 0.0) for r in rows]
    peaks = [float(r.max_value or 0.0) for r in rows]
    avgMean = float(statistics.fmean(avgs))
    avgPeak = float(statistics.fmean(peaks))

    slope = _safeSlope(avgs)
    driftPct = _computeDriftPct(avgs)
    direction = _classifyTrendDirection(driftPct, slope)

    session.add(
        TrendSnapshot(
            parameter_name=parameterName,
            window_size=windowSize,
            direction=direction.value,
            slope=slope,
            avg_peak=avgPeak,
            avg_mean=avgMean,
            drift_pct=driftPct,
        )
    )
    session.commit()

    return TrendResult(
        parameter_name=parameterName,
        window_size=windowSize,
        direction=direction,
        slope=slope,
        avg_peak=avgPeak,
        avg_mean=avgMean,
        drift_pct=driftPct,
    )


def _loadRecentAvgs(
    session: Session, parameterName: str, windowSize: int,
) -> list[DriveStatistic]:
    """Load up to ``windowSize`` most-recent drive_statistics rows for a param.

    Returned in chronological order (oldest first) so regression math reads
    naturally.
    """
    stmt = (
        select(DriveStatistic)
        .join(DriveSummary, DriveSummary.id == DriveStatistic.drive_id)
        .where(DriveStatistic.parameter_name == parameterName)
        .order_by(DriveSummary.start_time.desc())
        .limit(windowSize)
    )
    rows = list(session.execute(stmt).scalars().all())
    rows.reverse()  # oldest → newest
    return rows


def _safeSlope(series: Sequence[float]) -> float:
    """Least-squares slope of ``series`` over an integer index.

    Returns ``0.0`` when fewer than two points exist or the series is
    constant (``statistics.linear_regression`` raises in that case).
    """
    if len(series) < 2:
        return 0.0
    xs = list(range(len(series)))
    try:
        return float(statistics.linear_regression(xs, series).slope)
    except statistics.StatisticsError:
        return 0.0


def _computeDriftPct(series: Sequence[float]) -> float:
    """Percentage change from first to last element of ``series``.

    Returns ``0.0`` for single-element series or a zero baseline.
    """
    if len(series) < 2:
        return 0.0
    first = series[0]
    if first == 0.0:
        return 0.0
    return ((series[-1] - first) / first) * 100.0


def _classifyTrendDirection(
    driftPct: float, slope: float,
) -> TrendDirection:
    """Map drift magnitude + slope sign to a :class:`TrendDirection`."""
    if abs(driftPct) <= TREND_DRIFT_THRESHOLD_PCT:
        return TrendDirection.STABLE
    return TrendDirection.RISING if slope >= 0 else TrendDirection.FALLING


# ---- Cross-parameter correlation --------------------------------------------


def computeCorrelations(
    session: Session,
    pairs: Sequence[tuple[str, str]] = DEFAULT_CORRELATION_PAIRS,
) -> list[CorrelationResult]:
    """
    Compute Pearson r between drive-level aggregates of each parameter pair.

    For every ``(paramA, paramB)`` pair, pulls drives whose ``drive_statistics``
    has rows for both parameters, extracts paired ``avg_value`` series, and
    computes the correlation. Pairs with fewer than two overlapping drives,
    or where either series is constant, are skipped.

    Args:
        session: Open SQLAlchemy session bound to the server database.
        pairs: Parameter pairs to correlate. Defaults to
            :data:`DEFAULT_CORRELATION_PAIRS`; callers can override to test
            their own set.

    Returns:
        List of :class:`CorrelationResult`, one per pair that had enough data.
    """
    results: list[CorrelationResult] = []
    for paramA, paramB in pairs:
        xs, ys = _alignedAvgsByDrive(session, paramA, paramB)
        if len(xs) < 2:
            continue
        try:
            r = float(statistics.correlation(xs, ys))
        except statistics.StatisticsError:
            # Constant series — no meaningful correlation; skip.
            continue
        results.append(
            CorrelationResult(
                parameter_a=paramA,
                parameter_b=paramB,
                pearson_r=r,
                is_significant=abs(r) >= CORRELATION_SIGNIFICANCE_THRESHOLD,
                sample_count=len(xs),
            )
        )
    return results


def _alignedAvgsByDrive(
    session: Session, paramA: str, paramB: str,
) -> tuple[list[float], list[float]]:
    """Return the aligned avg_value series across drives with both params.

    A drive contributes exactly one ``(x, y)`` pair where ``x`` is the
    ``paramA`` avg_value and ``y`` is the ``paramB`` avg_value. Drives
    missing either parameter are dropped.
    """
    stmt = select(
        DriveStatistic.drive_id,
        DriveStatistic.parameter_name,
        DriveStatistic.avg_value,
    ).where(DriveStatistic.parameter_name.in_((paramA, paramB)))

    byDrive: dict[int, dict[str, float]] = {}
    for driveId, name, avg in session.execute(stmt).all():
        if avg is None:
            continue
        byDrive.setdefault(driveId, {})[name] = float(avg)

    xs: list[float] = []
    ys: list[float] = []
    for driveId in sorted(byDrive.keys()):
        values = byDrive[driveId]
        if paramA in values and paramB in values:
            xs.append(values[paramA])
            ys.append(values[paramB])
    return xs, ys


# ---- Anomaly detection ------------------------------------------------------


def detectAnomalies(session: Session, driveId: int) -> list[AnomalyResult]:
    """
    Flag parameters on ``driveId`` that fall outside the historical envelope.

    For each parameter the drive has stats for, compute the mean and sample
    standard deviation of ``avg_value`` across **other** drives. Deviations
    with ``|σ| > 2`` are classified :attr:`ComparisonStatus.WATCH` (≤3σ) or
    :attr:`ComparisonStatus.INVESTIGATE` (>3σ) and persisted to
    ``anomaly_log``.

    Prior ``anomaly_log`` rows for the same ``drive_id`` are deleted first,
    so re-running the function replaces rather than accumulates.

    Args:
        session: Open SQLAlchemy session bound to the server database.
        driveId: The drive to check.

    Returns:
        List of :class:`AnomalyResult` for every parameter that tripped the
        2σ gate. Empty when the drive is entirely within the envelope or when
        there is insufficient history to build one.
    """
    # Clear any previous anomalies for this drive to keep the call idempotent.
    session.execute(
        delete(AnomalyLog).where(AnomalyLog.drive_id == driveId)
    )

    currentStats = session.execute(
        select(DriveStatistic).where(DriveStatistic.drive_id == driveId)
    ).scalars().all()
    if not currentStats:
        session.commit()
        return []

    results: list[AnomalyResult] = []
    for current in currentStats:
        anomaly = _evaluateAnomaly(session, driveId, current)
        if anomaly is None:
            continue
        results.append(anomaly)
        session.add(
            AnomalyLog(
                drive_id=anomaly.drive_id,
                parameter_name=anomaly.parameter_name,
                observed_value=anomaly.observed_value,
                expected_min=anomaly.expected_min,
                expected_max=anomaly.expected_max,
                deviation_sigma=anomaly.deviation_sigma,
                severity=anomaly.severity.value,
            )
        )
    session.commit()
    return results


def _evaluateAnomaly(
    session: Session, driveId: int, current: DriveStatistic,
) -> AnomalyResult | None:
    """Return an :class:`AnomalyResult` if ``current`` breaches the envelope.

    Returns ``None`` when there is no usable historical distribution (fewer
    than two prior samples or zero variance) or when the deviation is within
    the NORMAL band.
    """
    historicalAvgs = [
        row.avg_value
        for row in session.execute(
            select(DriveStatistic).where(
                and_(
                    DriveStatistic.parameter_name == current.parameter_name,
                    DriveStatistic.drive_id != driveId,
                )
            )
        ).scalars().all()
        if row.avg_value is not None
    ]
    if len(historicalAvgs) < 2:
        return None

    histMean = float(statistics.fmean(historicalAvgs))
    histStd = float(statistics.stdev(historicalAvgs))
    if histStd <= 0.0:
        return None

    currentAvg = float(current.avg_value or 0.0)
    sigma = (currentAvg - histMean) / histStd
    severity = classifyDeviation(sigma)
    if severity is ComparisonStatus.NORMAL:
        return None

    return AnomalyResult(
        drive_id=driveId,
        parameter_name=current.parameter_name,
        observed_value=currentAvg,
        expected_min=histMean - 2.0 * histStd,
        expected_max=histMean + 2.0 * histStd,
        deviation_sigma=sigma,
        severity=severity,
    )


# ---- Public API -------------------------------------------------------------

__all__ = [
    "CORRELATION_SIGNIFICANCE_THRESHOLD",
    "DEFAULT_CORRELATION_PAIRS",
    "DEFAULT_TREND_WINDOW",
    "TREND_DRIFT_THRESHOLD_PCT",
    "computeCorrelations",
    "computeTrends",
    "detectAnomalies",
]
