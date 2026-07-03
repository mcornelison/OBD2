################################################################################
# File Name: compare_drives.py
# Purpose/Description: US-438 / F-069 server-side cross-drive comparison CLI.
#                      Reads obd2db and renders a side-by-side table of chosen
#                      metrics (peak RPM, LTFT/STFT, the US-436 derived signals,
#                      knock-retard) across N drives so Spool can eyeball tuning
#                      trends fast.  Read-only: it computes nothing and writes
#                      nothing -- it only SELECTs the already-computed analytics
#                      tables.  Honest about missing/foreign data: a drive with
#                      no computed row renders "--"; a foreign-vehicle drive
#                      (F-116, e.g. drive 33 the Ford Explorer) is EXCLUDED and
#                      shown as such, never silently counted.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-438) | Initial -- F-069 cross-drive comparison tool.
#               |              | Data-driven metric registry (statistic / derived
#               |              | / unavailable sources), F-116 foreign exclusion,
#               |              | pure table formatter.  Reads drive_summary +
#               |              | drive_statistics + drive_derived_signals.
# ================================================================================
################################################################################

"""US-438 / F-069 -- cross-drive metric comparison CLI (server-side, read-only).

Usage::

    python -m server.cli.compare_drives --drives 11,20,27
    python -m server.cli.compare_drives --drives 11-14,27 --metrics peak_rpm,ltft
    python -m server.cli.compare_drives --drives 27,33 --include-foreign
    python -m server.cli.compare_drives --list-metrics

The tool compares *chosen* metrics across *N* drives, side by side (metrics as
rows, drives as columns), so a Spool-style tuning read scans one metric across
several drives in a single glance.  It is deliberately read-only: analytics are
computed by ``recompute_drive_analytics``; this tool only SELECTs the results.

Architectural note (B-104): the server is the sole analytics authority, so a
comparison tool belongs here (not on the Pi).  Metrics live in three physical
shapes and the registry abstracts all three:

* ``statistic`` -- an EAV row in ``drive_statistics`` keyed by ``parameter_name``
  (peak RPM = RPM.max_value; LTFT = LONG_FUEL_TRIM_1.avg_value).
* ``derived`` -- a real column in ``drive_derived_signals`` (US-436): estimated
  distance, peak acceleration / deceleration.
* ``unavailable`` -- knock-retard: the stock 2G ECU exposes no knock PID over
  OBD, and the ECMLink knock-retard channel is USB-only, so there is no obd2db
  source.  The metric is offered for completeness but honestly renders "--" with
  a note rather than fabricating a value (grounding rule).

F-116 honesty: a drive stamped ``data_quality='foreign_vehicle'`` OR carrying a
``data_source`` other than 'real' (e.g. the Ford Explorer, drive 33) is excluded
from the comparison by default and shown with an EXCLUDED marker.  ``--include-
foreign`` overrides the exclusion when an operator explicitly wants to inspect
foreign data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.db.models import (
    DATA_QUALITY_FOREIGN_VEHICLE,
    DATA_SOURCE_DEFAULT,
    DriveDerivedSignal,
    DriveStatistic,
    DriveSummary,
)

logger = logging.getLogger(__name__)


# ---- Exit codes -------------------------------------------------------------

EXIT_OK: int = 0
EXIT_USAGE: int = 2

# ---- Rendering sentinels ----------------------------------------------------

# Rendered in a cell when a drive has no computed value for a metric (row not
# present, or the value is NULL) -- an honest "no data", distinct from a real 0.
NO_DATA_CELL: str = "--"


# ---- Metric registry --------------------------------------------------------

# Source discriminators for a MetricSpec.
SOURCE_STATISTIC: str = "statistic"
SOURCE_DERIVED: str = "derived"
SOURCE_UNAVAILABLE: str = "unavailable"

# drive_statistics aggregate columns a statistic metric may read.
_STATISTIC_AGGREGATE_COLUMNS: dict[str, str] = {
    "min": "min_value",
    "max": "max_value",
    "avg": "avg_value",
}


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """One comparable metric: where it lives and how to render it.

    Attributes:
        key: stable CLI selector (``--metrics <key>``).
        label: human column label for the table's metric column.
        unit: unit string appended to the label (honest-instrument).
        source: one of ``statistic`` / ``derived`` / ``unavailable``.
        precision: decimal places used to format the value.
        parameter: ``drive_statistics.parameter_name`` (statistic source only).
        aggregate: which aggregate column to read (``min``/``max``/``avg``;
            statistic source only).
        column: ``drive_derived_signals`` attribute name (derived source only).
        note: rationale rendered for an ``unavailable`` metric.
    """

    key: str
    label: str
    unit: str
    source: str
    precision: int = 2
    parameter: str | None = None
    aggregate: str | None = None
    column: str | None = None
    note: str | None = None


# Ordered so the default view matches the AC's named metrics: peak RPM,
# knock-retard, LTFT, then the US-436 derived signals.
METRIC_REGISTRY: dict[str, MetricSpec] = {
    "peak_rpm": MetricSpec(
        key="peak_rpm", label="Peak RPM", unit="rpm",
        source=SOURCE_STATISTIC, precision=0,
        parameter="RPM", aggregate="max",
    ),
    "knock_retard": MetricSpec(
        key="knock_retard", label="Knock retard", unit="deg",
        source=SOURCE_UNAVAILABLE, precision=1,
        note=(
            "no OBD knock PID on the stock 2G ECU; ECMLink knock-retard is "
            "USB-only -- not in obd2db"
        ),
    ),
    "ltft": MetricSpec(
        key="ltft", label="LTFT (avg)", unit="%",
        source=SOURCE_STATISTIC, precision=1,
        parameter="LONG_FUEL_TRIM_1", aggregate="avg",
    ),
    "stft": MetricSpec(
        key="stft", label="STFT (avg)", unit="%",
        source=SOURCE_STATISTIC, precision=1,
        parameter="SHORT_FUEL_TRIM_1", aggregate="avg",
    ),
    "peak_accel": MetricSpec(
        key="peak_accel", label="Peak accel", unit="m/s^2",
        source=SOURCE_DERIVED, precision=2,
        column="peak_acceleration_ms2",
    ),
    "peak_decel": MetricSpec(
        key="peak_decel", label="Peak decel", unit="m/s^2",
        source=SOURCE_DERIVED, precision=2,
        column="peak_deceleration_ms2",
    ),
    "distance": MetricSpec(
        key="distance", label="Est. distance", unit="km",
        source=SOURCE_DERIVED, precision=2,
        column="estimated_distance_km",
    ),
}

# The default metric set (all, in registry order) when --metrics is omitted.
DEFAULT_METRIC_KEYS: list[str] = list(METRIC_REGISTRY.keys())


# ---- Result shapes ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriveColumn:
    """One drive's resolved comparison column.

    Attributes:
        drive_id: the Pi-local drive_id requested.
        found: a ``drive_summary`` row exists for the drive_id.
        excluded: the drive is F-116 foreign/non-real and was excluded.
        exclude_reason: why the drive was excluded (``None`` when included).
        values: metric key -> resolved numeric value (``None`` = no data).
    """

    drive_id: int
    found: bool
    excluded: bool
    exclude_reason: str | None
    values: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """The full cross-drive comparison, ready to format.

    Attributes:
        metric_keys: metrics compared, in display order.
        drives: one column per requested drive, in request order.
    """

    metric_keys: list[str]
    drives: list[DriveColumn]


# ---- Parsing helpers --------------------------------------------------------


def parseDriveSpec(spec: str) -> list[int]:
    """Parse ``--drives`` into an ordered, de-duplicated drive_id list.

    Accepts a comma-separated mix of single ids and inclusive ranges::

        "11,20,27"      -> [11, 20, 27]
        "11-14"         -> [11, 12, 13, 14]
        "11-13,20"      -> [11, 12, 13, 20]

    First-occurrence order is preserved; duplicates are dropped.

    Raises:
        SystemExit: on an empty spec or a malformed token / inverted range.
    """
    ids: list[int] = []
    seen: set[int] = set()

    tokens = [tok.strip() for tok in spec.split(",") if tok.strip()]
    if not tokens:
        raise SystemExit("ERROR: --drives is empty; expected e.g. '11,20,27'.")

    for tok in tokens:
        if "-" in tok:
            for driveId in _parseRangeToken(tok):
                if driveId not in seen:
                    seen.add(driveId)
                    ids.append(driveId)
        else:
            driveId = _parseIntToken(tok)
            if driveId not in seen:
                seen.add(driveId)
                ids.append(driveId)

    return ids


def _parseIntToken(tok: str) -> int:
    try:
        return int(tok)
    except ValueError as exc:
        raise SystemExit(
            f"ERROR: --drives expects integer drive ids, got: {tok!r}",
        ) from exc


def _parseRangeToken(tok: str) -> Sequence[int]:
    try:
        loStr, hiStr = tok.split("-", 1)
        lo, hi = int(loStr), int(hiStr)
    except (ValueError, AttributeError) as exc:
        raise SystemExit(
            f"ERROR: --drives range expects 'A-B' format, got: {tok!r}",
        ) from exc
    if lo > hi:
        raise SystemExit(
            f"ERROR: --drives range low ({lo}) > high ({hi}) in {tok!r}",
        )
    return range(lo, hi + 1)


def resolveMetricKeys(spec: str | None) -> list[str]:
    """Resolve the requested ``--metrics`` selector into validated keys.

    ``None`` yields every registered metric in registry order.  An explicit
    comma-separated list is validated against the registry (order preserved,
    duplicates dropped).

    Raises:
        SystemExit: when a requested key is not in the registry.
    """
    if spec is None:
        return list(DEFAULT_METRIC_KEYS)

    keys: list[str] = []
    seen: set[str] = set()
    for raw in spec.split(","):
        key = raw.strip()
        if not key:
            continue
        if key not in METRIC_REGISTRY:
            valid = ", ".join(METRIC_REGISTRY.keys())
            raise SystemExit(
                f"ERROR: unknown metric {key!r}. Valid metrics: {valid}",
            )
        if key not in seen:
            seen.add(key)
            keys.append(key)

    if not keys:
        raise SystemExit("ERROR: --metrics resolved to no valid metrics.")
    return keys


# ---- Exclusion (F-116) ------------------------------------------------------


def driveExclusionReason(summary: DriveSummary) -> str | None:
    """Return an F-116 exclusion reason for a drive, or ``None`` if it is real.

    A drive is excluded when it is stamped as a foreign vehicle
    (``data_quality='foreign_vehicle'``) OR carries a ``data_source`` other than
    'real' (a NULL ``data_source`` is pre-US-195 and treated as real, matching
    the ``src/server/analytics/basic.py`` filter).
    """
    if summary.data_quality == DATA_QUALITY_FOREIGN_VEHICLE:
        return "foreign_vehicle"
    dataSource = summary.data_source
    if dataSource is not None and dataSource != DATA_SOURCE_DEFAULT:
        return f"data_source={dataSource}"
    return None


# ---- DB resolution ----------------------------------------------------------


def _findSummary(session: Session, driveId: int) -> DriveSummary | None:
    """Find the drive_summary row for a Pi-local drive_id (source_id|drive_id)."""
    return session.execute(
        select(DriveSummary)
        .where(
            (DriveSummary.source_id == driveId)
            | (DriveSummary.drive_id == driveId)
        )
        .order_by(DriveSummary.id.asc())
    ).scalars().first()


def _resolveDriveColumn(
    session: Session, driveId: int, metricKeys: list[str], includeForeign: bool,
) -> DriveColumn:
    """Resolve one drive's metric values (or its found/excluded state)."""
    summary = _findSummary(session, driveId)
    if summary is None:
        return DriveColumn(
            drive_id=driveId, found=False, excluded=False,
            exclude_reason=None, values={},
        )

    reason = driveExclusionReason(summary)
    if reason is not None and not includeForeign:
        return DriveColumn(
            drive_id=driveId, found=True, excluded=True,
            exclude_reason=reason, values={},
        )

    values = _resolveMetricValues(session, summary.id, metricKeys)
    return DriveColumn(
        drive_id=driveId, found=True, excluded=False,
        exclude_reason=None, values=values,
    )


def _resolveMetricValues(
    session: Session, summaryId: int, metricKeys: list[str],
) -> dict[str, float | None]:
    """Read every requested metric for one drive_summary.id.

    Loads the drive's statistic rows (keyed by parameter_name) and its single
    derived-signals row ONCE, then resolves each metric from the in-memory maps
    so N metrics cost at most two queries.
    """
    statByParam: dict[str, DriveStatistic] = {
        row.parameter_name: row
        for row in session.execute(
            select(DriveStatistic).where(
                DriveStatistic.summary_id == summaryId
            )
        ).scalars().all()
    }
    derived = session.get(DriveDerivedSignal, summaryId)

    values: dict[str, float | None] = {}
    for key in metricKeys:
        spec = METRIC_REGISTRY[key]
        values[key] = _resolveOneMetric(spec, statByParam, derived)
    return values


def _resolveOneMetric(
    spec: MetricSpec,
    statByParam: dict[str, DriveStatistic],
    derived: DriveDerivedSignal | None,
) -> float | None:
    """Resolve a single metric's value from the pre-loaded per-drive maps."""
    if spec.source == SOURCE_STATISTIC:
        row = statByParam.get(spec.parameter or "")
        if row is None:
            return None
        aggregateColumn = _STATISTIC_AGGREGATE_COLUMNS[spec.aggregate or "avg"]
        value = getattr(row, aggregateColumn)
        return None if value is None else float(value)

    if spec.source == SOURCE_DERIVED:
        if derived is None:
            return None
        value = getattr(derived, spec.column or "")
        return None if value is None else float(value)

    # SOURCE_UNAVAILABLE: honest no-data, never fabricated.
    return None


def buildComparison(
    session: Session,
    driveIds: list[int],
    metricKeys: list[str],
    *,
    includeForeign: bool = False,
) -> ComparisonResult:
    """Build the cross-drive comparison for the requested drives + metrics."""
    columns = [
        _resolveDriveColumn(session, driveId, metricKeys, includeForeign)
        for driveId in driveIds
    ]
    return ComparisonResult(metric_keys=list(metricKeys), drives=columns)


# ---- Formatting -------------------------------------------------------------


def _formatValue(value: float | None, precision: int) -> str:
    """Render a numeric cell, or the no-data sentinel when the value is None."""
    if value is None:
        return NO_DATA_CELL
    return f"{value:.{precision}f}"


def _driveHeader(column: DriveColumn) -> str:
    """Column header for a drive: id plus a state marker when not comparable."""
    if not column.found:
        return f"drive {column.drive_id} (NOT FOUND)"
    if column.excluded:
        return f"drive {column.drive_id} (EXCLUDED)"
    return f"drive {column.drive_id}"


def formatComparisonTable(result: ComparisonResult) -> str:
    """Render the comparison as an aligned, monospaced side-by-side table.

    Metrics are rows and drives are columns.  Missing values render as ``--``;
    a drive that was not found or was F-116-excluded is labelled in its header
    and its cells render ``--`` (it contributes no numbers).  A footnote lists
    any excluded drives and any unavailable metrics so the output is honest
    about what it did and did not count.
    """
    metricLabels = [
        f"{METRIC_REGISTRY[key].label} ({METRIC_REGISTRY[key].unit})"
        for key in result.metric_keys
    ]
    headers = [_driveHeader(col) for col in result.drives]

    # Column 0 = metric labels; one column per drive.
    metricColWidth = max((len(lbl) for lbl in metricLabels), default=0)
    metricColWidth = max(metricColWidth, len("Metric"))

    # Pre-render every data cell so column widths account for content.
    cellRows: list[list[str]] = []
    for key in result.metric_keys:
        spec = METRIC_REGISTRY[key]
        rowCells: list[str] = []
        for col in result.drives:
            if not col.found or col.excluded:
                rowCells.append(NO_DATA_CELL)
            else:
                rowCells.append(
                    _formatValue(col.values.get(key), spec.precision)
                )
        cellRows.append(rowCells)

    driveColWidths: list[int] = []
    for i in range(len(result.drives)):
        widest = len(headers[i])
        for r in range(len(cellRows)):
            widest = max(widest, len(cellRows[r][i]))
        driveColWidths.append(widest)

    lines: list[str] = []

    # Header row.
    headerCells = ["Metric".ljust(metricColWidth)]
    for i, hdr in enumerate(headers):
        headerCells.append(hdr.rjust(driveColWidths[i]))
    lines.append("  ".join(headerCells))

    # Separator.
    sepCells = ["-" * metricColWidth]
    sepCells.extend("-" * driveColWidths[i] for i in range(len(headers)))
    lines.append("  ".join(sepCells))

    # Data rows.
    for r, label in enumerate(metricLabels):
        rowCells = [label.ljust(metricColWidth)]
        for i in range(len(result.drives)):
            rowCells.append(cellRows[r][i].rjust(driveColWidths[i]))
        lines.append("  ".join(rowCells))

    # Footnotes -- honest about exclusions + unavailable metrics.
    footnotes = _buildFootnotes(result)
    if footnotes:
        lines.append("")
        lines.extend(footnotes)

    return "\n".join(lines)


def _buildFootnotes(result: ComparisonResult) -> list[str]:
    """Build the honesty footnotes (excluded drives + unavailable metrics)."""
    notes: list[str] = []

    excluded = [c for c in result.drives if c.excluded]
    for col in excluded:
        notes.append(
            f"NOTE: drive {col.drive_id} EXCLUDED ({col.exclude_reason}) "
            "-- foreign/non-real data is not counted (F-116). "
            "Use --include-foreign to override."
        )

    notFound = [c for c in result.drives if not c.found]
    for col in notFound:
        notes.append(
            f"NOTE: drive {col.drive_id} NOT FOUND -- no drive_summary row "
            "(Pi-sync may not have landed, or the id is wrong)."
        )

    for key in result.metric_keys:
        spec = METRIC_REGISTRY[key]
        if spec.source == SOURCE_UNAVAILABLE and spec.note:
            notes.append(
                f"NOTE: '{spec.label}' is unavailable -- {spec.note}."
            )

    return notes


# ---- CLI --------------------------------------------------------------------


def _resolveSyncDatabaseUrl() -> str:
    """Resolve a SYNC SQLAlchemy URL from the server config.

    The production server uses an async URL (``mysql+aiomysql://``); this CLI
    runs synchronously, so the async driver is swapped for its sync twin.
    """
    from src.server.config import Settings

    settings = Settings()
    url = settings.DATABASE_URL
    if "+aiomysql" in url:
        return url.replace("+aiomysql", "+pymysql")
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    return url


def _formatMetricCatalogue() -> str:
    """Render the metric registry for ``--list-metrics``."""
    lines = ["Available metrics:"]
    for spec in METRIC_REGISTRY.values():
        suffix = ""
        if spec.source == SOURCE_UNAVAILABLE:
            suffix = f"  [unavailable: {spec.note}]"
        lines.append(
            f"  {spec.key:<14} {spec.label} ({spec.unit}){suffix}"
        )
    return "\n".join(lines)


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.compare_drives",
        description=(
            "F-069: compare chosen metrics across N drives side-by-side "
            "(read-only; foreign/F-116 data excluded by default)."
        ),
    )
    parser.add_argument(
        "--drives",
        type=str,
        metavar="LIST",
        help="Comma-separated drive ids and/or ranges, e.g. '11,20,27' or "
             "'11-14,27'.",
    )
    parser.add_argument(
        "--metrics",
        type=str,
        default=None,
        metavar="LIST",
        help="Comma-separated metric keys (default: all). "
             "See --list-metrics.",
    )
    parser.add_argument(
        "--include-foreign",
        action="store_true",
        help="Include F-116 foreign-vehicle drives (excluded by default).",
    )
    parser.add_argument(
        "--list-metrics",
        action="store_true",
        help="Print the available metrics and exit.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.compare_drives``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    if args.list_metrics:
        print(_formatMetricCatalogue())
        return EXIT_OK

    if not args.drives:
        parser.error("--drives is required (or use --list-metrics).")

    driveIds = parseDriveSpec(args.drives)
    metricKeys = resolveMetricKeys(args.metrics)

    databaseUrl = _resolveSyncDatabaseUrl()
    engine = create_engine(databaseUrl, future=True)
    try:
        with Session(engine) as session:
            result = buildComparison(
                session, driveIds, metricKeys,
                includeForeign=args.include_foreign,
            )
    finally:
        engine.dispose()

    print(formatComparisonTable(result))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
