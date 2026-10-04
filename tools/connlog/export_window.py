################################################################################
# File Name: export_window.py
# Purpose/Description: US-808-d -- export every connection_log row older than a
#                      window end, from the Pi and the server, to CSV plus a
#                      manifest. Read-only by construction; every write is
#                      re-read and verified against the source's own count.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-808-d) | Rewrite of the lost Sprint 93 export tool,
#               |                | specified by its surviving manifest.
# ================================================================================
################################################################################
"""Export a historical connection_log window from both tiers, read-only.

This is the rewrite of ``tools/export_connection_log_window.py`` (US-808-a),
which sat directly under ``tools/`` where ``.gitignore``'s ``tools/*`` swallowed
it. Its output survived at ``data/us808-connection-log-export/`` and is the
specification: the manifest written here carries the same field set.

Two properties are the point of the tool:

1. **Read-only by construction.** Every statement goes through
   :func:`requireSelect`, which refuses anything but a single ``SELECT``. The Pi
   database is opened through a ``mode=ro`` URI. ``deletionPerformed`` is written
   ``false`` on every run because nothing here can remove a row.
2. **An export that cannot be re-read is a failed export.** The source's own
   ``COUNT(*)`` is recorded as ``rowsReported``; the rows re-read from the
   written CSV are ``rowsReadBack``. A truncated export shows as a difference
   between the two and a non-zero exit, never as silence.

Timestamps are compared as INSTANTS. The Pi stores both ``2026-04-23 03:14:40``
and ``2026-04-23T03:12:39Z``; a raw string minimum ranks every space-form value
ahead of every T-form value, which is how the preserved manifest came to record
the Pi's first row as 03:14:40 when its earliest instant is 03:12:39.

Usage::

    python -m tools.connlog.export_window --window-end 2026-06-01 --out <new dir>
    python -m tools.connlog.export_window --window-end 2026-06-01 --out <dir> --tier pi
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.sync.reconcile import _CONFIG_HOST_KEY, PI_DB, _configValue, _normaliseTs

TABLE = "connection_log"
TIMESTAMP_COLUMN = "timestamp"
EVENT_TYPE_COLUMN = "event_type"
ID_COLUMN = "id"
MANIFEST_NAME = "manifest.json"
TIERS = ("pi", "server")

#: The three types the connection manager emits on every retry. Recorded in the
#: manifest so the gap analysis reads them from the export, not from a guess.
RETRY_EVENT_TYPES = ("connect_attempt", "connect_failure", "disconnect")

#: How the Pi's sqlite3 renders NULL (empty) and how prod_db_query.sh renders it.
PI_NULL = ""
SERVER_NULL = "NULL"

_PI_QUERY_TIMEOUT_S = 300
_SERVER_QUERY_TIMEOUT_S = 300
_SERVER_QUERY_SCRIPT = "tools/pm/prod_db_query.sh"

#: A query runner returns ``(rows)`` where each row is a list of cell strings.
QueryRunner = Callable[[str], list[list[str]]]


class ExportError(Exception):
    """An export that must not be trusted: refused, unreadable or unverifiable."""


def requireSelect(sql: str) -> str:
    """Refuse every statement that is not one single SELECT.

    Args:
        sql: The statement about to be sent to a tier.

    Returns:
        ``sql`` unchanged when it is a single SELECT.

    Raises:
        ExportError: When the statement is anything else, or chains a second one.
    """
    body = sql.strip().rstrip(";").strip()
    if not body.upper().startswith("SELECT") or ";" in body:
        raise ExportError(f"read-only tool: refusing a non-SELECT statement: {sql!r}")
    return sql


# ---------------------------------------------------------------------------
# Tier sources
# ---------------------------------------------------------------------------


class TierSource:
    """One tier's connection_log, reached only through read-only SELECTs.

    Args:
        tier: ``"pi"`` or ``"server"``.
        runQuery: Executes one SELECT and returns its rows as cell strings.
        columnsSql: A SELECT returning the table's column names in order.
    """

    def __init__(self, tier: str, runQuery: QueryRunner, columnsSql: str) -> None:
        if tier not in TIERS:
            raise ExportError(f"unknown tier {tier!r}; expected one of {TIERS}")
        self.tier = tier
        self._runQuery = runQuery
        self._columnsSql = columnsSql

    def _select(self, sql: str) -> list[list[str]]:
        return self._runQuery(requireSelect(sql))

    def columns(self) -> list[str]:
        """Every column of the source table, in table order."""
        cols = [row[0] for row in self._select(self._columnsSql)]
        if not cols:
            raise ExportError(f"{self.tier}: {TABLE} has no columns -- wrong database?")
        return cols

    def countRows(self, windowEnd: str) -> int:
        """The source's own count of rows before ``windowEnd``."""
        rows = self._select(
            f"SELECT COUNT(*) FROM {TABLE} WHERE {TIMESTAMP_COLUMN} < '{windowEnd}'"
        )
        return int(rows[0][0])

    def fetchRows(self, columns: Sequence[str], windowEnd: str) -> list[list[str]]:
        """Every row before ``windowEnd``, in id order, as cell strings."""
        return self._select(
            f"SELECT {', '.join(columns)} FROM {TABLE} "
            f"WHERE {TIMESTAMP_COLUMN} < '{windowEnd}' ORDER BY {ID_COLUMN}"
        )


def _piCell(value: Any) -> str:
    return PI_NULL if value is None else str(value)


def sqliteReadOnlyRunner(dbPath: Path) -> QueryRunner:
    """Run SELECTs against a local SQLite file opened through a ``mode=ro`` URI."""

    def run(sql: str) -> list[list[str]]:
        conn = sqlite3.connect(f"{dbPath.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return [[_piCell(v) for v in row] for row in conn.execute(sql)]
        finally:
            conn.close()

    return run


def sshPiRunner(piHost: str, dbPath: str = PI_DB) -> QueryRunner:
    """Run SELECTs on the Pi over ssh, database opened ``mode=ro``.

    ``eclipse-obd`` keeps writing while this reads; ``mode=ro`` means the export
    never takes a write lock on the collector's database.
    """

    def run(sql: str) -> list[list[str]]:
        remote = f"sqlite3 -json 'file:{dbPath}?mode=ro' \"{sql}\""
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", piHost, remote],
            capture_output=True, text=True, encoding="utf-8", timeout=_PI_QUERY_TIMEOUT_S,
        )
        if result.returncode != 0:
            raise ExportError(f"Pi query failed: {result.stderr[-400:]}")
        # sqlite3 -json prints nothing at all for an empty result.
        records = json.loads(result.stdout or "[]")
        return [[_piCell(v) for v in rec.values()] for rec in records]

    return run


def serverRunner(repoRoot: Path) -> QueryRunner:
    """Run SELECTs on the server through ``tools/pm/prod_db_query.sh``.

    That script prints one tab-separated line per row and renders NULL as
    ``NULL``; both are kept verbatim.
    """

    def run(sql: str) -> list[list[str]]:
        result = subprocess.run(
            ["bash", _SERVER_QUERY_SCRIPT, sql],
            capture_output=True, text=True, encoding="utf-8",
            timeout=_SERVER_QUERY_TIMEOUT_S, cwd=repoRoot,
        )
        if result.returncode != 0:
            raise ExportError(f"server query failed: {result.stderr[-500:]}")
        return [line.split("\t") for line in result.stdout.splitlines() if line]

    return run


PI_COLUMNS_SQL = f"SELECT name FROM pragma_table_info('{TABLE}') ORDER BY cid"
SERVER_COLUMNS_SQL = (
    "SELECT column_name FROM information_schema.columns "
    f"WHERE table_schema = DATABASE() AND table_name = '{TABLE}' ORDER BY ordinal_position"
)


def piSource(runQuery: QueryRunner) -> TierSource:
    """The Pi tier over any runner (ssh, or a local read-only copy)."""
    return TierSource("pi", runQuery, PI_COLUMNS_SQL)


def serverSource(runQuery: QueryRunner) -> TierSource:
    """The server tier over any runner."""
    return TierSource("server", runQuery, SERVER_COLUMNS_SQL)


# ---------------------------------------------------------------------------
# Export and read-back
# ---------------------------------------------------------------------------


def csvName(tier: str, windowEnd: str) -> str:
    """The file name the preserved export used: ``<tier>_connection_log_before_<end>.csv``."""
    return f"{tier}_{TABLE}_before_{windowEnd}.csv"


def readBack(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Re-read a written export: its header and every row."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def timestampSpan(rows: Sequence[dict[str, str]]) -> tuple[str | None, str | None]:
    """Earliest and latest INSTANT, whichever of the two renderings each row uses."""
    instants = [_normaliseTs(r[TIMESTAMP_COLUMN]) for r in rows if r[TIMESTAMP_COLUMN]]
    if not instants:
        return None, None
    return min(instants), max(instants)


def exportTier(
    source: TierSource, outDir: Path, windowEnd: str
) -> tuple[dict[str, Any], list[str]]:
    """Export one tier's window to CSV, re-read it, and describe it.

    Args:
        source: The tier to read.
        outDir: Directory to write into. An existing export is never overwritten.
        windowEnd: Rows with a timestamp before this are exported (``YYYY-MM-DD``).

    Returns:
        The tier's manifest entry, and every reason it cannot be trusted.

    Raises:
        ExportError: When the target file already exists.
    """
    path = outDir / csvName(source.tier, windowEnd)
    if path.exists():
        raise ExportError(f"{path} already exists -- an export never overwrites evidence")

    columns = source.columns()
    rowsReported = source.countRows(windowEnd)
    rows = source.fetchRows(columns, windowEnd)

    outDir.mkdir(parents=True, exist_ok=True)
    with open(path, "x", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)

    header, readRows = readBack(path)
    first, last = timestampSpan(readRows)
    entry = {
        "columns": header,
        "firstTimestamp": first,
        "lastTimestamp": last,
        "path": str(path),
        "perEventType": dict(sorted(Counter(r[EVENT_TYPE_COLUMN] for r in readRows).items())),
        "rowsReadBack": len(readRows),
        "rowsReported": rowsReported,
        "sampled": False,
        "sizeBytes": path.stat().st_size,
        "tier": source.tier,
    }
    return entry, verifyEntry(entry, columns)


def verifyEntry(entry: dict[str, Any], expectedColumns: Sequence[str]) -> list[str]:
    """Every reason this export cannot be trusted; empty when it can."""
    problems = []
    if entry["rowsReadBack"] != entry["rowsReported"]:
        problems.append(
            f"{entry['tier']}: source reported {entry['rowsReported']} rows, "
            f"file re-reads {entry['rowsReadBack']}"
        )
    if list(entry["columns"]) != list(expectedColumns):
        problems.append(f"{entry['tier']}: written header differs from the source's columns")
    return problems


def exportWindow(
    sources: Sequence[TierSource], outDir: Path, windowEnd: str
) -> tuple[dict[str, Any], list[str]]:
    """Export every tier, write the manifest, and return it with any problems.

    The manifest is written even when a problem is found, so a failed export is
    on disk beside the files it describes.
    """
    entries, problems = [], []
    for source in sources:
        entry, entryProblems = exportTier(source, outDir, windowEnd)
        entries.append(entry)
        problems.extend(entryProblems)

    manifest = {
        "deletionPerformed": False,
        "exportedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exports": entries,
        "liveCountsAtExport": {e["tier"]: e["rowsReported"] for e in entries},
        "retryEventTypes": list(RETRY_EVENT_TYPES),
        "windowEnd": windowEnd,
    }
    with open(outDir / MANIFEST_NAME, "x", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return manifest, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export a connection_log window, read-only.")
    ap.add_argument("--window-end", dest="windowEnd", required=True,
                    help="export rows with a timestamp before this date (YYYY-MM-DD)")
    ap.add_argument("--out", required=True, type=Path,
                    help="directory to write into; existing exports are never overwritten")
    ap.add_argument("--tier", choices=(*TIERS, "both"), default="both")
    ap.add_argument("--pi-host", dest="piHost", default=None,
                    help="overrides pi.network.piHost from config.json")
    ap.add_argument("--pi-db", dest="piDb", default=PI_DB)
    ap.add_argument("--repo-root", dest="repoRoot", type=Path, default=Path("."))
    a = ap.parse_args(argv)
    try:
        datetime.strptime(a.windowEnd, "%Y-%m-%d")
    except ValueError:
        ap.error(f"--window-end must be YYYY-MM-DD, got {a.windowEnd!r}")

    sources = []
    if a.tier in ("pi", "both"):
        piHost = a.piHost or _configValue(_CONFIG_HOST_KEY)
        if not piHost:
            ap.error("no Pi host: config.json was unreadable and no --pi-host given")
        sources.append(piSource(sshPiRunner(piHost, a.piDb)))
    if a.tier in ("server", "both"):
        sources.append(serverSource(serverRunner(a.repoRoot)))

    manifest, problems = exportWindow(sources, a.out, a.windowEnd)
    for e in manifest["exports"]:
        print(f"  {e['tier']:6} reported {e['rowsReported']:>8,}  read back "
              f"{e['rowsReadBack']:>8,}  {e['firstTimestamp']} .. {e['lastTimestamp']}")
    print(f"  deletionPerformed: {str(manifest['deletionPerformed']).lower()}")
    for p in problems:
        print(f"  FAILED EXPORT: {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
