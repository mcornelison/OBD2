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
# ================================================================================
################################################################################

"""
Analytics result types.

Contains the immutable result shapes for :mod:`src.server.analytics.basic`:

* :class:`BasicStats` — raw min/max/avg/std bundle produced by the pure
  :func:`helpers.computeBasicStats` helper.
* :class:`DriveStatistics` — per-drive per-parameter statistics with drive and
  parameter identifiers, matching the ``drive_statistics`` table schema.
* :class:`ParameterComparison` — result of comparing a drive's statistics
  against historical aggregates.
* :class:`ComparisonStatus` — enum mapping deviation magnitude to a severity
  label (NORMAL / WATCH / INVESTIGATE).
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


# ---- Public API --------------------------------------------------------------

__all__ = [
    "BasicStats",
    "ComparisonStatus",
    "DriveStatistics",
    "ParameterComparison",
]
