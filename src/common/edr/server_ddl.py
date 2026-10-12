################################################################################
# File Name: server_ddl.py
# Purpose/Description: MariaDB DDL for the server EDR raw tables, GENERATED from
#                      sensor_schema.EDR_COLUMNS so the server cannot drift from
#                      the Pi (the A-4 anti-divergence promise). Natural primary
#                      key containing the partition column, monthly RANGE
#                      COLUMNS partitions on ts_utc plus pmax, PAGE_COMPRESSED,
#                      no inline CHECK and no surrogate id. Also generates the
#                      add-partition (REORGANIZE pmax) and drop-partition SQL.
# Author: Rex (US-764)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-764) | Initial -- raw-table DDL generator + partition
#               |              | maintenance SQL (US-734 spec section 6 + 9a).
# ================================================================================
################################################################################
"""Server-side EDR raw-table DDL, generated from the shared contract.

Usage::

    python -m src.common.edr.server_ddl create --first-month 2026-09 --months 3
    python -m src.common.edr.server_ddl add-partition --table edr_imu_sample --month 2026-12
    python -m src.common.edr.server_ddl drop-partition --table edr_imu_sample --month 2024-09

Nothing here connects to a database; it prints SQL for a migration or an
operator to run. The partition window is always supplied by the caller.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from .sensor_schema import EDR_COLUMNS
from .sync_contract import EDR_SYNC_TABLES

# The ruled kind -> MariaDB type map (US-734 spec section 6, D8). REAL->FLOAT and
# ISO-text->DATETIME are deliberate casts, not drift.
KIND_TYPES: dict[str, str] = {
    "iso_ts": "DATETIME",
    "monotonic_s": "DOUBLE",
    "int": "INT",
    "float": "FLOAT",
    "label": "VARCHAR(16)",
}

# Server-only columns: where the row came from, and when/which batch landed it.
SOURCE_COLUMNS: tuple[str, ...] = (
    "source_device VARCHAR(64) NOT NULL",
    "source_id BIGINT NOT NULL",
)
SYNC_COLUMNS: tuple[str, ...] = (
    "synced_at DATETIME",
    "sync_batch_id INT",
)

PRIMARY_KEY_COLUMNS: tuple[str, ...] = ("source_device", "source_id", "ts_utc")
DEVICE_TS_KEY_COLUMNS: tuple[str, ...] = ("source_device", "ts_utc")
PARTITION_COLUMN = "ts_utc"
MAX_PARTITION = "pmax"


def partitionName(month: date) -> str:
    """Return the partition identifier for the month containing ``month``.

    Args:
        month: Any date in the month.

    Returns:
        ``p<YYYY><MM>``, e.g. ``p202609``.
    """
    return f"p{month.year:04d}{month.month:02d}"


def _nextMonth(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def monthStarts(firstMonth: date, count: int) -> list[date]:
    """Return ``count`` consecutive first-of-month dates from ``firstMonth``'s month.

    Args:
        firstMonth: Any date in the first month.
        count: How many months; zero yields an empty list.

    Returns:
        First-of-month dates in ascending order.

    Raises:
        ValueError: If ``count`` is negative.
    """
    if count < 0:
        raise ValueError(f"month count must not be negative, got {count}")
    current = date(firstMonth.year, firstMonth.month, 1)
    starts: list[date] = []
    for _ in range(count):
        starts.append(current)
        current = _nextMonth(current)
    return starts


def _partitionClause(month: date) -> str:
    return (
        f"PARTITION {partitionName(month)} VALUES LESS THAN "
        f"('{_nextMonth(month).isoformat()}')"
    )


def _maxPartitionClause() -> str:
    return f"PARTITION {MAX_PARTITION} VALUES LESS THAN (MAXVALUE)"


def _requireTable(tableName: str) -> None:
    if tableName not in EDR_COLUMNS:
        raise ValueError(f"{tableName!r} is not an EDR contract table")


def _columnLine(tableName: str, name: str, kind: str, nullable: bool) -> str:
    if kind not in KIND_TYPES:
        raise ValueError(f"{tableName}.{name} has kind {kind!r}, outside the ruled map")
    return f"{name} {KIND_TYPES[kind]}{'' if nullable else ' NOT NULL'}"


def buildRawTableDdl(tableName: str, *, firstMonth: date, months: int) -> str:
    """Build ``CREATE TABLE IF NOT EXISTS`` for one EDR raw table.

    Args:
        tableName: An EDR contract table (a key of ``EDR_COLUMNS``).
        firstMonth: Any date in the first partitioned month.
        months: How many monthly partitions precede ``pmax``.

    Returns:
        The MariaDB DDL statement.

    Raises:
        ValueError: If the table is not in the contract, a column kind is outside
            the ruled map, or ``months`` is negative.
    """
    _requireTable(tableName)
    columns = [
        *SOURCE_COLUMNS,
        *(_columnLine(tableName, n, k, nl) for n, k, nl in EDR_COLUMNS[tableName]),
        *SYNC_COLUMNS,
    ]
    body = [
        *columns,
        f"PRIMARY KEY ({', '.join(PRIMARY_KEY_COLUMNS)})",
        f"KEY ix_{tableName}_device_ts ({', '.join(DEVICE_TS_KEY_COLUMNS)})",
    ]
    partitions = [_partitionClause(m) for m in monthStarts(firstMonth, months)]
    partitions.append(_maxPartitionClause())
    return (
        f"CREATE TABLE IF NOT EXISTS {tableName} (\n  "
        + ",\n  ".join(body)
        + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci "
        "PAGE_COMPRESSED=1\n"
        f"PARTITION BY RANGE COLUMNS({PARTITION_COLUMN}) (\n  "
        + ",\n  ".join(partitions)
        + "\n);"
    )


def buildAllRawTableDdl(*, firstMonth: date, months: int) -> list[str]:
    """Build the raw-table DDL for every table in EDR sync scope, in scope order.

    Args:
        firstMonth: Any date in the first partitioned month.
        months: How many monthly partitions precede ``pmax``.

    Returns:
        One DDL statement per ``EDR_SYNC_TABLES`` entry.
    """
    return [buildRawTableDdl(t, firstMonth=firstMonth, months=months) for t in EDR_SYNC_TABLES]


def buildAddPartitionSql(tableName: str, month: date) -> str:
    """Build the statement that splits ``pmax`` to add ``month``'s partition.

    Args:
        tableName: An EDR contract table.
        month: Any date in the month to add.

    Returns:
        ``ALTER TABLE ... REORGANIZE PARTITION pmax INTO (...)``.

    Raises:
        ValueError: If the table is not in the contract.
    """
    _requireTable(tableName)
    return (
        f"ALTER TABLE {tableName} REORGANIZE PARTITION {MAX_PARTITION} INTO ("
        f"{_partitionClause(month)}, {_maxPartitionClause()});"
    )


def buildDropPartitionSql(tableName: str, month: date) -> str:
    """Build the statement that drops ``month``'s partition.

    Args:
        tableName: An EDR contract table.
        month: Any date in the month to drop.

    Returns:
        ``ALTER TABLE ... DROP PARTITION p<YYYY><MM>;``.

    Raises:
        ValueError: If the table is not in the contract.
    """
    _requireTable(tableName)
    return f"ALTER TABLE {tableName} DROP PARTITION {partitionName(month)};"


def _parseMonth(text: str) -> date:
    try:
        return date.fromisoformat(f"{text}-01")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {text!r}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Print generated EDR server SQL.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code: 0 on success, 2 on an invalid table or count.
    """
    parser = argparse.ArgumentParser(description="Generate EDR server raw-table SQL.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="CREATE TABLE for every EDR sync table")
    create.add_argument("--first-month", type=_parseMonth, required=True)
    create.add_argument("--months", type=int, required=True)

    for command in ("add-partition", "drop-partition"):
        maintenance = sub.add_parser(command)
        maintenance.add_argument("--table", required=True)
        maintenance.add_argument("--month", type=_parseMonth, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            statements = buildAllRawTableDdl(firstMonth=args.first_month, months=args.months)
        elif args.command == "add-partition":
            statements = [buildAddPartitionSql(args.table, args.month)]
        else:
            statements = [buildDropPartitionSql(args.table, args.month)]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("\n\n".join(statements))
    return 0


__all__ = [
    "KIND_TYPES",
    "buildAddPartitionSql",
    "buildAllRawTableDdl",
    "buildDropPartitionSql",
    "buildRawTableDdl",
    "main",
    "monthStarts",
    "partitionName",
]


if __name__ == "__main__":
    sys.exit(main())
