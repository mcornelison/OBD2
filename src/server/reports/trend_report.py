################################################################################
# File Name: trend_report.py
# Purpose/Description: Trend report formatter and orchestrator — rolling trend
#                      direction arrows, delta over period, significance label,
#                      and detected correlations.  Matches spec §1.9 format.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-160 — CLI trend
#               |              | report per server spec §1.9
# ================================================================================
################################################################################

"""
Trend report formatting and assembly.

Public entry points:

* :func:`formatTrendReport` — pure formatter. Takes a list of
  :class:`~src.server.analytics.types.TrendResult` and a list of
  :class:`~src.server.analytics.types.CorrelationResult` and returns the
  formatted block.
* :func:`trendArrow` — pure mapping from direction + slope sign + drift
  magnitude to one of ``↑ ↗ → ↘ ↓`` (and a textual label).
* :func:`classifyTrendSignificance` — pure mapping from ``TrendResult`` to
  one of ``OK / WATCH / INVESTIGATE`` based on absolute drift percent.
* :func:`buildTrendReport` — orchestrator. Runs :func:`computeTrends` for a
  fixed set of parameters, then :func:`computeCorrelations`, then formats.

The "significance" column is a *display-layer* label, not a re-analysis
step.  It maps the drift magnitude (already computed by
:func:`computeTrends`) to a severity label so the CIO can glance at the
report and spot what to investigate.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.server.analytics.advanced import (
    DEFAULT_TREND_WINDOW,
    computeCorrelations,
    computeTrends,
)
from src.server.analytics.types import (
    ComparisonStatus,
    CorrelationResult,
    TrendDirection,
    TrendResult,
)

# ---- Presentation constants -------------------------------------------------

_BORDER_WIDTH: int = 64
_DOUBLE_BORDER: str = "═" * _BORDER_WIDTH
_SINGLE_BORDER: str = "─" * _BORDER_WIDTH

_PARAM_COL: int = 18
_DIRECTION_COL: int = 14
_DELTA_COL: int = 18
_SIGNIF_COL: int = 14

# Significance thresholds applied to abs(drift_pct). Kept permissive so that a
# sub-spec (5%) drift is OK, a mid-range drift flags WATCH, and a large drift
# escalates to INVESTIGATE.  Tune-able in the future without spec changes.
_SIGNIF_WATCH_PCT: float = 5.0
_SIGNIF_INVESTIGATE_PCT: float = 15.0

# Minimum slope magnitude (per-drive) to show a ↗/↘ arrow on an otherwise
# STABLE trend.  Below this we keep the flat → arrow.  Value is low so that
# even mild drift direction shows an angled arrow — matches the spec example
# where ``IAT Peak  ↗ Slight  +3°F`` is shown despite being under the 5%
# STABLE threshold.
_SLOPE_ANGLE_EPSILON: float = 0.05


# Default parameters to trend.  Covers the tuning-relevant vitals the CIO
# cares about during crawl phase.
DEFAULT_TREND_PARAMETERS: tuple[str, ...] = (
    "RPM",
    "CoolantTemp",
    "IAT",
    "STFT",
    "KnockCount",
    "Boost",
    "AFR",
)


# ==============================================================================
# Pure formatters
# ==============================================================================


def formatTrendReport(
    trends: list[TrendResult],
    correlations: list[CorrelationResult],
    windowSize: int = DEFAULT_TREND_WINDOW,
) -> str:
    """
    Format a trend report block per spec §1.9.

    Header shows the rolling window size.  Body is a table of parameters with
    direction arrow, delta over the period (numeric, unit-less), and a
    significance label.  A correlations section follows, listing any pair
    above :data:`CORRELATION_SIGNIFICANCE_THRESHOLD` with its Pearson r.

    Args:
        trends: One :class:`TrendResult` per parameter to include.
        correlations: All computed correlations. Only ``is_significant``
            entries are listed; callers can pass the full list from
            :func:`computeCorrelations`.
        windowSize: Shown in the header (e.g. "Last 10 Drives").

    Returns:
        Fully-formatted multi-line report block.
    """
    lines: list[str] = [
        _DOUBLE_BORDER,
        f"  Trend Report — Last {windowSize} Drives",
        _DOUBLE_BORDER,
        "",
        *_formatTrendTable(trends),
        "",
        *_formatCorrelationSection(correlations),
        _DOUBLE_BORDER,
    ]
    return "\n".join(lines)


def trendArrow(result: TrendResult) -> tuple[str, str]:
    """
    Map a :class:`TrendResult` to a ``(glyph, label)`` pair.

    Direction glyphs:

    * ``↑`` / ``Rising``   — RISING direction.
    * ``↗`` / ``Slight``   — STABLE with positive slope above epsilon.
    * ``→`` / ``Stable``   — STABLE with negligible slope.
    * ``↘`` / ``Slight``   — STABLE with negative slope above epsilon.
    * ``↓`` / ``Falling``  — FALLING direction.

    Args:
        result: Trend result to classify.

    Returns:
        ``(arrow_glyph, label)`` tuple.
    """
    if result.direction is TrendDirection.RISING:
        return ("↑", "Rising")
    if result.direction is TrendDirection.FALLING:
        return ("↓", "Falling")
    # STABLE: disambiguate with slope sign so the reader can see
    # whether the trend is drifting slightly up or down.
    if result.slope > _SLOPE_ANGLE_EPSILON:
        return ("↗", "Slight")
    if result.slope < -_SLOPE_ANGLE_EPSILON:
        return ("↘", "Slight")
    return ("→", "Stable")


def classifyTrendSignificance(result: TrendResult) -> ComparisonStatus:
    """
    Assign a severity label to a trend based on absolute drift percent.

    * ``|drift_pct| < 5``   → NORMAL
    * ``5 ≤ |drift_pct| < 15`` → WATCH
    * ``|drift_pct| ≥ 15``  → INVESTIGATE

    Args:
        result: Trend to classify.

    Returns:
        :class:`ComparisonStatus` — same enum as per-drive comparisons so the
        UI layer treats them uniformly.
    """
    magnitude = abs(result.drift_pct)
    if magnitude < _SIGNIF_WATCH_PCT:
        return ComparisonStatus.NORMAL
    if magnitude < _SIGNIF_INVESTIGATE_PCT:
        return ComparisonStatus.WATCH
    return ComparisonStatus.INVESTIGATE


# ---- Trend table helpers ----------------------------------------------------


def _formatTrendTable(trends: list[TrendResult]) -> list[str]:
    header = (
        f"  {'Parameter':<{_PARAM_COL}}"
        f"{'Direction':<{_DIRECTION_COL}}"
        f"{'Δ Over Period':<{_DELTA_COL}}"
        f"{'Significance':<{_SIGNIF_COL}}"
    )
    lines = [header, "  " + _SINGLE_BORDER]

    if not trends:
        lines.append("  (no trend data — need at least one drive per parameter)")
        return lines

    for result in trends:
        arrow, label = trendArrow(result)
        direction = f"{arrow} {label}"
        delta = _formatDriftDelta(result.drift_pct)
        signif = _decorateSignificance(classifyTrendSignificance(result))
        lines.append(
            f"  {result.parameter_name:<{_PARAM_COL}}"
            f"{direction:<{_DIRECTION_COL}}"
            f"{delta:<{_DELTA_COL}}"
            f"{signif:<{_SIGNIF_COL}}"
        )
    return lines


def _formatDriftDelta(driftPct: float) -> str:
    sign = "+" if driftPct >= 0 else ""
    return f"{sign}{driftPct:.1f}%"


def _decorateSignificance(status: ComparisonStatus) -> str:
    if status is ComparisonStatus.WATCH:
        return "WATCH"
    if status is ComparisonStatus.INVESTIGATE:
        return "⚠ INVESTIGATE"
    return "OK"


# ---- Correlation section helpers --------------------------------------------


def _formatCorrelationSection(
    correlations: list[CorrelationResult],
) -> list[str]:
    lines = [
        "  Correlations Detected:",
        "  " + _SINGLE_BORDER,
    ]

    significant = [c for c in correlations if c.is_significant]
    if not significant:
        lines.append("  No significant correlations detected.")
        return lines

    for corr in significant:
        lines.append(
            f"  {corr.parameter_a} correlates with {corr.parameter_b} "
            f"(r={corr.pearson_r:+.2f}, n={corr.sample_count})"
        )
    return lines


# ==============================================================================
# Orchestrator (DB-backed)
# ==============================================================================


def buildTrendReport(
    session: Session,
    windowSize: int = DEFAULT_TREND_WINDOW,
    parameters: tuple[str, ...] = DEFAULT_TREND_PARAMETERS,
) -> str:
    """
    Build a trend report by running analytics and formatting the result.

    Args:
        session: Open SQLAlchemy session.
        windowSize: How many most-recent drives to include in each trend
            snapshot.
        parameters: Which parameters to trend.  Pulled from
            :data:`DEFAULT_TREND_PARAMETERS` if omitted.  Parameters with no
            drive_statistics rows are silently skipped — the trend engine
            returns ``None`` for those.

    Returns:
        Fully-formatted report string.
    """
    trends: list[TrendResult] = []
    for name in parameters:
        result = computeTrends(session, name, windowSize=windowSize)
        if result is not None:
            trends.append(result)

    correlations = computeCorrelations(session)
    return formatTrendReport(trends, correlations, windowSize=windowSize)


# ---- Public API -------------------------------------------------------------

__all__ = [
    "DEFAULT_TREND_PARAMETERS",
    "buildTrendReport",
    "classifyTrendSignificance",
    "formatTrendReport",
    "trendArrow",
]
