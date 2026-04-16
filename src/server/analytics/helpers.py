################################################################################
# File Name: helpers.py
# Purpose/Description: Pure-math analytics helpers — statistics computation and
#                      deviation classification used by basic + advanced layers.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-158 — pure stats
#               |              | helpers and deviation classifier
# ================================================================================
################################################################################

"""
Pure-math helpers for the analytics engine.

No database or SQLAlchemy dependencies — these helpers accept plain Python
sequences and return plain dataclasses, so they are cheap to unit test and
reusable from any analytics layer (basic, advanced, reports).

Functions:
    * :func:`computeBasicStats` — min, max, avg, sample std dev, outlier bounds.
    * :func:`classifyDeviation` — map a sigma magnitude to a
      :class:`ComparisonStatus`.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from src.server.analytics.types import BasicStats, ComparisonStatus

# ---- Constants ---------------------------------------------------------------

# Boundaries for deviation severity, per server spec §1.7/§1.8.
#
# A deviation *magnitude* (absolute sigma) is compared inclusively against
# these bounds:
#
#   |σ| ≤ WATCH_THRESHOLD         → NORMAL
#   |σ| ≤ INVESTIGATE_THRESHOLD   → WATCH
#   |σ| >  INVESTIGATE_THRESHOLD  → INVESTIGATE
WATCH_THRESHOLD: float = 2.0
INVESTIGATE_THRESHOLD: float = 3.0


# ---- Stats -------------------------------------------------------------------


def computeBasicStats(values: Sequence[float]) -> BasicStats | None:
    """
    Compute min, max, avg, std dev, and 2σ outlier bounds for a sequence.

    Uses the **sample** standard deviation (``statistics.stdev``) when 2+
    values are present. For a single value, std_dev defaults to ``0.0`` and
    outlier bounds collapse to the value itself.

    Args:
        values: Numeric readings. Empty sequence returns ``None``.

    Returns:
        A :class:`BasicStats` instance, or ``None`` if ``values`` is empty.
    """
    if not values:
        return None

    minV = float(min(values))
    maxV = float(max(values))
    avg = float(statistics.fmean(values))
    std = float(statistics.stdev(values)) if len(values) >= 2 else 0.0
    return BasicStats(
        min_value=minV,
        max_value=maxV,
        avg_value=avg,
        std_dev=std,
        outlier_min=avg - 2.0 * std,
        outlier_max=avg + 2.0 * std,
        sample_count=len(values),
    )


# ---- Classification ----------------------------------------------------------


def classifyDeviation(sigma: float) -> ComparisonStatus:
    """
    Classify a deviation magnitude into NORMAL / WATCH / INVESTIGATE.

    The classifier uses the **absolute** sigma value, so a current drive
    sitting below historical norms is just as alert-worthy as one above.

    Args:
        sigma: Signed deviation in standard deviations from historical mean.

    Returns:
        :class:`ComparisonStatus` — one of NORMAL, WATCH, INVESTIGATE.
    """
    magnitude = abs(sigma)
    if magnitude <= WATCH_THRESHOLD:
        return ComparisonStatus.NORMAL
    if magnitude <= INVESTIGATE_THRESHOLD:
        return ComparisonStatus.WATCH
    return ComparisonStatus.INVESTIGATE


# ---- Public API --------------------------------------------------------------

__all__ = [
    "INVESTIGATE_THRESHOLD",
    "WATCH_THRESHOLD",
    "classifyDeviation",
    "computeBasicStats",
]
