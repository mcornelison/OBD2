################################################################################
# File Name: types.py
# Purpose/Description: Dataclasses and enums for the analytics engine. Pure
#                      stdlib (no project imports) so every analytics submodule
#                      can import from here safely.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-158 — basic
#               |              | analytics result types
# 2026-04-16    | Ralph Agent  | Added advanced analytics result types for
#               |              | US-159 — trends, correlations, anomalies
# ================================================================================
################################################################################

"""
Analytics result types.

Contains the immutable result shapes for :mod:`src.server.analytics.basic` and
:mod:`src.server.analytics.advanced`:

* :class:`BasicStats` — raw min/max/avg/std bundle produced by the pure
  :func:`helpers.computeBasicStats` helper.
* :class:`DriveStatistics` — per-drive per-parameter statistics with drive and
  parameter identifiers, matching the ``drive_statistics`` table schema.
* :class:`ParameterComparison` — result of comparing a drive's statistics
  against historical aggregates.
* :class:`ComparisonStatus` — enum mapping deviation magnitude to a severity
  label (NORMAL / WATCH / INVESTIGATE).
* :class:`TrendDirection` — enum for multi-drive trend direction.
* :class:`TrendResult` — rolling trend summary for a parameter across the last
  N drives, matching the ``trend_snapshots`` table schema.
* :class:`CorrelationResult` — Pearson correlation between two drive-level
  parameter aggregates.
* :class:`AnomalyResult` — flagged anomaly for one parameter on one drive,
  matching the ``anomaly_log`` table schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# ---- Enums -------------------------------------------------------------------


class ComparisonStatus(StrEnum):
    """Severity label assigned by :func:`helpers.classifyDeviation`.

    * ``NORMAL`` — deviation ≤ 2σ.
    * ``WATCH`` — deviation > 2σ and ≤ 3σ.
    * ``INVESTIGATE`` — deviation > 3σ.
    """

    NORMAL = "NORMAL"
    WATCH = "WATCH"
    INVESTIGATE = "INVESTIGATE"


class TrendDirection(StrEnum):
    """Direction of a parameter's rolling trend over the last N drives.

    * ``RISING`` — positive regression slope with absolute drift > 5%.
    * ``FALLING`` — negative regression slope with absolute drift > 5%.
    * ``STABLE`` — drift ≤ 5% or insufficient data to determine slope.
    """

    RISING = "RISING"
    FALLING = "FALLING"
    STABLE = "STABLE"


# ---- Dataclasses -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BasicStats:
    """Raw stats from a series of numeric values. No drive/parameter context."""

    min_value: float
    max_value: float
    avg_value: float
    std_dev: float
    outlier_min: float
    outlier_max: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class DriveStatistics:
    """Per-drive per-parameter statistics, matching ``drive_statistics`` rows."""

    drive_id: int
    parameter_name: str
    min_value: float
    max_value: float
    avg_value: float
    std_dev: float
    outlier_min: float
    outlier_max: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class ParameterComparison:
    """One parameter's comparison against historical aggregates."""

    parameter_name: str
    current_avg: float
    current_max: float
    historical_mean_avg: float
    historical_std_avg: float
    deviation_sigma: float
    status: ComparisonStatus


@dataclass(frozen=True, slots=True)
class TrendResult:
    """Rolling trend summary for one parameter across the last N drives.

    Mirrors the ``trend_snapshots`` table: a point-in-time snapshot that
    captures direction, slope, and drift of a parameter's averages.
    """

    parameter_name: str
    window_size: int
    direction: TrendDirection
    slope: float
    avg_peak: float
    avg_mean: float
    drift_pct: float


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    """Pearson correlation between drive-level aggregates of two parameters."""

    parameter_a: str
    parameter_b: str
    pearson_r: float
    is_significant: bool
    sample_count: int


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    """Flagged anomaly for one parameter on one drive.

    Written to ``anomaly_log``. Only deviations >= 2σ produce results — lower
    deviations are considered within the historical envelope.
    """

    drive_id: int
    parameter_name: str
    observed_value: float
    expected_min: float
    expected_max: float
    deviation_sigma: float
    severity: ComparisonStatus


# ---- Public API --------------------------------------------------------------

__all__ = [
    "AnomalyResult",
    "BasicStats",
    "ComparisonStatus",
    "CorrelationResult",
    "DriveStatistics",
    "ParameterComparison",
    "TrendDirection",
    "TrendResult",
]
