################################################################################
# File Name: drive_report.py
# Purpose/Description: Drive report formatter and orchestrator — single-drive
#                      parameter table + historical comparison section, plus an
#                      all-drives summary table.  Matches spec §1.9 format.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-160 — CLI drive
#               |              | report per server spec §1.9
# ================================================================================
################################################################################

"""
Drive report formatting and assembly.

Public entry points:

* :func:`formatDriveReport` — pure formatter. Takes a
  :class:`~src.server.db.models.DriveSummary`, a list of
  :class:`~src.server.analytics.types.DriveStatistics`, a list of
  :class:`~src.server.analytics.types.ParameterComparison`, and the count of
  prior drives.  Returns the fully formatted block.
* :func:`formatAllDrivesTable` — pure formatter. Takes a list of
  ``DriveSummary`` rows and returns a table of (date, duration, device,
  profile, row count).
* :func:`buildDriveReport` — orchestrator. Takes a session + drive reference
  (``"latest"``, a ``YYYY-MM-DD`` date, or an integer id), runs
  :func:`~src.server.analytics.basic.compareDriveToHistory`, and returns the
  assembled string.
* :func:`buildAllDrivesReport` — orchestrator. Queries all drives ordered by
  ``start_time`` and formats them.

The pure formatters do *not* touch the database — they are unit-tested by
feeding them fixture dataclasses directly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.server.analytics.basic import compareDriveToHistory
from src.server.analytics.types import (
    ComparisonStatus,
    DriveStatistics,
    ParameterComparison,
)
from src.server.db.models import DriveStatistic, DriveSummary

# ---- Presentation constants --------------------------------------------------

_BORDER_WIDTH: int = 60
_DOUBLE_BORDER: str = "═" * _BORDER_WIDTH
_SINGLE_BORDER: str = "─" * _BORDER_WIDTH

# Column widths for the per-parameter stats table.
_PARAM_COL: int = 16
_NUM_COL: int = 9
_STATUS_COL: int = 14

# Column widths for the all-drives summary table.
_DATE_COL: int = 19
_DURATION_COL: int = 10
_DEVICE_COL: int = 22
_PROFILE_COL: int = 14
_ROWS_COL: int = 8


# ==============================================================================
# Pure formatters
# ==============================================================================


def formatDriveReport(
    drive: DriveSummary,
    stats: list[DriveStatistics],
    comparisons: list[ParameterComparison],
    historicalDriveCount: int,
) -> str:
    """
    Format a single-drive report per spec §1.9.

    The header shows date/time, duration in minutes, device id, and profile.
    The body is a parameter table (Min/Max/Avg/Std/Status) followed by a
    comparison-to-historical section.  If ``comparisons`` is empty (first-ever
    drive) the section degrades gracefully to a single note.

    Args:
        drive: The ``DriveSummary`` ORM row being reported on.
        stats: Per-parameter statistics for this drive.
        comparisons: Historical comparison rows for each parameter — can be
            empty when no prior drives exist.
        historicalDriveCount: How many *other* drives contribute to the
            historical envelope (shown in the comparison section header).

    Returns:
        A fully-formatted multi-line report block.
    """
    lines: list[str] = [
        _DOUBLE_BORDER,
        _formatHeaderLine(drive),
        _formatDeviceLine(drive),
        _DOUBLE_BORDER,
        "",
        *_formatStatsTable(stats, comparisons),
        "",
        *_formatComparisonSection(comparisons, historicalDriveCount),
        _DOUBLE_BORDER,
    ]
    return "\n".join(lines)


def formatAllDrivesTable(drives: list[DriveSummary]) -> str:
    """
    Format a summary table of every drive.

    Columns: date (YYYY-MM-DD HH:MM), duration (min), device, profile, rows.

    Args:
        drives: ``DriveSummary`` rows in chronological order (oldest → newest).

    Returns:
        Multi-line table string, or a friendly "no drives" notice.
    """
    lines: list[str] = [
        _DOUBLE_BORDER,
        "  All Drives Summary",
        _DOUBLE_BORDER,
        "",
    ]

    if not drives:
        lines.append("  No drives found.")
        lines.append(_DOUBLE_BORDER)
        return "\n".join(lines)

    header = (
        f"  {'Date':<{_DATE_COL}}"
        f"{'Duration':<{_DURATION_COL}}"
        f"{'Device':<{_DEVICE_COL}}"
        f"{'Profile':<{_PROFILE_COL}}"
        f"{'Rows':>{_ROWS_COL}}"
    )
    lines.append(header)
    lines.append("  " + _SINGLE_BORDER)

    for drive in drives:
        dateStr = _formatDateTime(drive.start_time)
        duration = _formatDurationMinutes(drive.duration_seconds)
        device = (drive.device_id or "")[:_DEVICE_COL - 1]
        profile = (drive.profile_id or "—")[:_PROFILE_COL - 1]
        rowCount = drive.row_count if drive.row_count is not None else 0
        lines.append(
            f"  {dateStr:<{_DATE_COL}}"
            f"{duration:<{_DURATION_COL}}"
            f"{device:<{_DEVICE_COL}}"
            f"{profile:<{_PROFILE_COL}}"
            f"{rowCount:>{_ROWS_COL}}"
        )

    lines.append("")
    lines.append(_DOUBLE_BORDER)
    return "\n".join(lines)


# ---- Header helpers ---------------------------------------------------------


def _formatHeaderLine(drive: DriveSummary) -> str:
    dateStr = _formatDateTime(drive.start_time)
    duration = _formatDurationMinutes(drive.duration_seconds).strip()
    return f"  Drive Report — {dateStr} ({duration})"


def _formatDeviceLine(drive: DriveSummary) -> str:
    device = drive.device_id or "unknown"
    profile = drive.profile_id or "—"
    return f"  Device: {device} | Profile: {profile}"


def _formatDateTime(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def _formatDurationMinutes(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    minutes = int(seconds // 60)
    return f"{minutes} min"


# ---- Stats table helpers ----------------------------------------------------


def _formatStatsTable(
    stats: list[DriveStatistics],
    comparisons: list[ParameterComparison],
) -> list[str]:
    statusByParam = {c.parameter_name: c.status for c in comparisons}
    header = (
        f"  {'Parameter':<{_PARAM_COL}}"
        f"{'Min':>{_NUM_COL}}"
        f"{'Max':>{_NUM_COL}}"
        f"{'Avg':>{_NUM_COL}}"
        f"{'Std':>{_NUM_COL}}"
        f"  {'Status':<{_STATUS_COL}}"
    )
    lines = [header, "  " + _SINGLE_BORDER]

    if not stats:
        lines.append("  (no statistics available for this drive)")
        return lines

    for row in stats:
        status = statusByParam.get(row.parameter_name, ComparisonStatus.NORMAL)
        lines.append(
            f"  {row.parameter_name:<{_PARAM_COL}}"
            f"{_formatNumber(row.min_value):>{_NUM_COL}}"
            f"{_formatNumber(row.max_value):>{_NUM_COL}}"
            f"{_formatNumber(row.avg_value):>{_NUM_COL}}"
            f"{_formatNumber(row.std_dev):>{_NUM_COL}}"
            f"  {_decorateStatus(status):<{_STATUS_COL}}"
        )
    return lines


def _formatNumber(value: float) -> str:
    """Format a float in at most 4 significant chars + optional decimal."""
    if value == 0:
        return "0"
    absValue = abs(value)
    if absValue >= 1000:
        return f"{value:.0f}"
    if absValue >= 100:
        return f"{value:.0f}"
    if absValue >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def _decorateStatus(status: ComparisonStatus) -> str:
    if status is ComparisonStatus.WATCH:
        return "⚠ WATCH"
    if status is ComparisonStatus.INVESTIGATE:
        return "⚠ INVESTIGATE"
    return "NORMAL"


# ---- Comparison section helpers ---------------------------------------------


def _formatComparisonSection(
    comparisons: list[ParameterComparison],
    historicalDriveCount: int,
) -> list[str]:
    headerCount = max(0, historicalDriveCount)
    lines = [
        f"  Comparison to Historical ({headerCount} prior drives):",
        "  " + _SINGLE_BORDER,
    ]

    if headerCount == 0 or not comparisons:
        lines.append("  No prior drives available for comparison.")
        return lines

    flagged = [
        c for c in comparisons
        if c.status is not ComparisonStatus.NORMAL
    ]

    if not flagged:
        lines.append("  All parameters within normal envelope.")
        return lines

    for comp in flagged:
        direction = "above" if comp.deviation_sigma >= 0 else "below"
        lines.append(
            f"  {comp.parameter_name} avg {_formatNumber(comp.current_avg)} is "
            f"{abs(comp.deviation_sigma):.1f}σ {direction} historical avg "
            f"{_formatNumber(comp.historical_mean_avg)} "
            f"[{_decorateStatus(comp.status)}]"
        )
    return lines


# ==============================================================================
# Orchestrators (DB-backed)
# ==============================================================================


def buildDriveReport(session: Session, driveRef: str) -> str:
    """
    Build a drive report by reference.

    Args:
        session: Open SQLAlchemy session.
        driveRef: One of:

            * ``"latest"`` — the most recent drive by ``start_time``.
            * A ``YYYY-MM-DD`` date — the first drive whose ``start_time``
              falls on that date (UTC-naive comparison).
            * An integer string — treated as the drive's primary key.

    Returns:
        The assembled report string, or an error message string when no drive
        is found (callers that need a hard failure should pre-validate).
    """
    drive = _resolveDrive(session, driveRef)
    if drive is None:
        return f"No drive found for reference '{driveRef}'."

    stats = _loadDriveStats(session, drive.id)
    comparisons = compareDriveToHistory(session, drive.id)

    historicalDriveCount = session.execute(
        select(DriveSummary.id).where(DriveSummary.id != drive.id),
    ).all()

    return formatDriveReport(
        drive=drive,
        stats=stats,
        comparisons=comparisons,
        historicalDriveCount=len(historicalDriveCount),
    )


def buildAllDrivesReport(session: Session) -> str:
    """Format an all-drives summary table, chronological order."""
    drives = list(
        session.execute(
            select(DriveSummary).order_by(DriveSummary.start_time.asc()),
        ).scalars().all(),
    )
    return formatAllDrivesTable(drives)


# ---- Resolution + loading helpers -------------------------------------------


def _resolveDrive(session: Session, driveRef: str) -> DriveSummary | None:
    ref = driveRef.strip()
    if ref == "latest":
        return session.execute(
            select(DriveSummary).order_by(DriveSummary.start_time.desc()).limit(1),
        ).scalar_one_or_none()

    if ref.isdigit():
        return session.get(DriveSummary, int(ref))

    try:
        dayStart = datetime.strptime(ref, "%Y-%m-%d")
    except ValueError:
        return None

    dayEnd = dayStart.replace(hour=23, minute=59, second=59)
    return session.execute(
        select(DriveSummary)
        .where(DriveSummary.start_time >= dayStart)
        .where(DriveSummary.start_time <= dayEnd)
        .order_by(DriveSummary.start_time.asc())
        .limit(1),
    ).scalar_one_or_none()


def _loadDriveStats(session: Session, driveId: int) -> list[DriveStatistics]:
    rows = session.execute(
        select(DriveStatistic)
        .where(DriveStatistic.drive_id == driveId)
        .order_by(DriveStatistic.parameter_name.asc()),
    ).scalars().all()

    return [
        DriveStatistics(
            drive_id=row.drive_id,
            parameter_name=row.parameter_name,
            min_value=float(row.min_value or 0.0),
            max_value=float(row.max_value or 0.0),
            avg_value=float(row.avg_value or 0.0),
            std_dev=float(row.std_dev or 0.0),
            outlier_min=float(row.outlier_min or 0.0),
            outlier_max=float(row.outlier_max or 0.0),
            sample_count=int(row.sample_count or 0),
        )
        for row in rows
    ]


# ---- Public API -------------------------------------------------------------

__all__ = [
    "buildAllDrivesReport",
    "buildDriveReport",
    "formatAllDrivesTable",
    "formatDriveReport",
]
