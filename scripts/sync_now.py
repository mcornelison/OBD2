################################################################################
# File Name: sync_now.py
# Purpose/Description: Manual sync CLI for the Walk-phase Pi -> Chi-Srv-01
#                      pipeline.  Invokes SyncClient.pushAllDeltas() and prints
#                      one human-readable line per in-scope table + a summary.
#                      The CIO runs this on the Pi (or via SSH) to trigger a
#                      sync when WiFi returns -- auto-scheduling is Run-phase
#                      scope.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-154 (Sprint 11)
# ================================================================================
################################################################################

"""
Walk-phase manual sync CLI.

Usage::

    # Normal run -- push all in-scope tables' delta rows to Chi-Srv-01
    python scripts/sync_now.py

    # Override config location
    python scripts/sync_now.py --config path/to/config.json

    # Query delta counts without pushing (cheap; no HTTP)
    python scripts/sync_now.py --dry-run

Output matches spec 2.2::

    Sync started: 2026-04-18 14:32:05
    Config: baseUrl=http://10.27.27.10:8000, batchSize=500

    realtime_data: 247 new rows -> pushed -> accepted (batch: chi-eclipse-01-...)
    statistics:     12 new rows -> pushed -> accepted (batch: chi-eclipse-01-...)
    alert_log:       0 new rows -> nothing to sync
    ...

    Total: 259 rows pushed across 2 tables
    Elapsed: 1.8s
    Status: OK

Exit codes:
    * 0 -- all pushes succeeded (including all-empty / all-disabled short-circuits)
    * 1 -- at least one table failed, OR config load failed
    * 2 -- invalid CLI arguments (argparse-reported)

Invariants (US-154):
    * No scheduling.  This CLI is the manual trigger.
    * No secrets in stdout.  The API key is never printed.
    * Runs offline -- if the server is unreachable, every table reports
      FAILED with its reason, the sync_log high-water marks stay put
      (US-149 invariant), and exit code is 1.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root is importable (matches scripts/report.py).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.config.secrets_loader import (  # noqa: E402
    loadConfigWithSecrets,
    loadEnvFile,
)
from src.common.config.validator import (  # noqa: E402
    ConfigValidationError,
    ConfigValidator,
)
from src.common.errors.handler import ConfigurationError  # noqa: E402
from src.pi.data import sync_log  # noqa: E402
from src.pi.sync import PushResult, PushStatus, SyncClient  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = ["main", "parseArguments"]


# ==============================================================================
# Types
# ==============================================================================


SyncClientFactory = Callable[[dict[str, Any]], Any]
"""Callable that takes a validated config dict and returns a SyncClient-like
object with a ``pushAllDeltas()`` method and ``baseUrl`` / ``batchSize``
properties.  Injected in tests so the CLI can be exercised without real
HTTP / SQLite; defaults to the real :class:`SyncClient`."""


# ==============================================================================
# CLI parsing
# ==============================================================================


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Populated ``argparse.Namespace`` with ``config`` and ``dry_run``.
    """
    parser = argparse.ArgumentParser(
        prog="sync_now.py",
        description=(
            "Manually push Pi delta rows to the Chi-Srv-01 companion "  # b044-exempt: argparse help prose
            "service.  Walk-phase Pi -> server sync trigger."
        ),
    )
    parser.add_argument(
        "--config", "-c",
        default="config.json",
        metavar="PATH",
        help="Path to config.json (default: ./config.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report pending delta counts per table without pushing.  No "
            "HTTP is made and the high-water marks are unchanged."
        ),
    )
    return parser.parse_args(argv)


# ==============================================================================
# Config loading
# ==============================================================================


def _loadConfig(configPath: str) -> dict[str, Any]:
    """Load + validate a Pi config, raising with a clear operator message.

    Raises:
        ConfigurationError: If the file is missing, invalid JSON, or fails
            ConfigValidator.  The message is operator-readable and does
            not leak secret values.
    """
    # Populate environment from .env if one exists alongside config.
    loadEnvFile(".env")

    if not Path(configPath).exists():
        raise ConfigurationError(
            f"config file not found: {configPath}",
            {"configPath": configPath},
        )

    try:
        raw = loadConfigWithSecrets(configPath)
        validated: dict[str, Any] = ConfigValidator().validate(raw)
    except ConfigValidationError as exc:
        raise ConfigurationError(
            f"config validation failed: {exc}",
            {"configPath": configPath},
        ) from exc
    return validated


# ==============================================================================
# Rendering
# ==============================================================================


# Column widths used for vertical alignment of the per-table line.  Long
# enough to accommodate every member of sync_log.IN_SCOPE_TABLES (the
# longest is "calibration_sessions" at 20 chars).
_TABLE_COL_WIDTH = 22
_ROWS_COL_WIDTH = 5


def _formatStartBanner(baseUrl: str, batchSize: int) -> str:
    """Build the two-line header printed before per-table output."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"Sync started: {now}\n"
        f"Config: baseUrl={baseUrl}, batchSize={batchSize}\n"
    )


def _formatResultLine(result: PushResult) -> str:
    """Format a single PushResult as a one-line CLI output row."""
    name = result.tableName.ljust(_TABLE_COL_WIDTH)
    rows = str(result.rowsPushed).rjust(_ROWS_COL_WIDTH)

    if result.status is PushStatus.OK:
        return (
            f"{name}{rows} new rows -> pushed -> accepted "
            f"(batch: {result.batchId})"
        )
    if result.status is PushStatus.EMPTY:
        return f"{name}{rows} new rows -> nothing to sync"
    if result.status is PushStatus.DISABLED:
        return f"{name}{'-'.rjust(_ROWS_COL_WIDTH)}       -> disabled"
    # FAILED (or unknown -- treat as failed defensively).
    reason = result.reason or "unknown error"
    return f"{name}{'?'.rjust(_ROWS_COL_WIDTH)}       -> failed -> {reason}"


def _overallStatus(results: list[PushResult]) -> str:
    """Decide the single-word summary status.

    * FAILED if any result is FAILED (exit 1).
    * DISABLED if every result is DISABLED.
    * OK otherwise (all-EMPTY and mixed OK/EMPTY both count as OK).
    """
    if any(r.status is PushStatus.FAILED for r in results):
        return "FAILED"
    if results and all(r.status is PushStatus.DISABLED for r in results):
        return "DISABLED"
    return "OK"


def _summaryLines(results: list[PushResult], elapsedSeconds: float) -> str:
    """Build the three-line footer: Total / Elapsed / Status."""
    totalRows = sum(
        r.rowsPushed for r in results if r.status is PushStatus.OK
    )
    tablesWithData = sum(
        1 for r in results if r.status is PushStatus.OK and r.rowsPushed > 0
    )
    status = _overallStatus(results)
    return (
        f"Total: {totalRows} rows pushed across {tablesWithData} tables\n"
        f"Elapsed: {elapsedSeconds:.1f}s\n"
        f"Status: {status}\n"
    )


def _renderDryRunReport(syncClient: Any) -> str:
    """Render a dry-run delta-count report without making any HTTP calls.

    Reads the sync_log high-water marks directly from the Pi SQLite and
    counts rows with id > HWM per in-scope table.
    """
    import sqlite3

    lines = ["Dry run: pending delta counts (no push)\n"]
    try:
        with sqlite3.connect(syncClient.dbPath) as conn:
            sync_log.initDb(conn)
            totalPending = 0
            for tableName in sorted(sync_log.IN_SCOPE_TABLES):
                # US-194: snapshot tables have TEXT natural PKs and are
                # not delta-syncable -- render a marker instead of trying
                # a COUNT against a non-existent id column.
                if tableName in sync_log.SNAPSHOT_TABLES:
                    name = tableName.ljust(_TABLE_COL_WIDTH)
                    lines.append(
                        f"{name}{'-'.rjust(_ROWS_COL_WIDTH)} "
                        f"pending (snapshot table, delta-sync N/A)"
                    )
                    continue
                pkColumn = sync_log.PK_COLUMN[tableName]
                lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
                try:
                    cursor = conn.execute(
                        f"SELECT COUNT(*) FROM {tableName} "  # noqa: S608
                        f"WHERE {pkColumn} > ?",
                        (lastId,),
                    )
                    pending = int(cursor.fetchone()[0])
                except sqlite3.OperationalError:
                    # Table may not exist yet on a fresh DB; treat as zero.
                    pending = 0
                totalPending += pending
                name = tableName.ljust(_TABLE_COL_WIDTH)
                rows = str(pending).rjust(_ROWS_COL_WIDTH)
                lines.append(
                    f"{name}{rows} pending (last_synced_id={lastId})"
                )
            lines.append("")
            lines.append(f"Total pending: {totalPending} rows")
    except sqlite3.Error as exc:
        lines.append(f"(unable to read sync_log: {exc})")
    return "\n".join(lines) + "\n"


# ==============================================================================
# Entry point
# ==============================================================================


def _defaultSyncClientFactory(config: dict[str, Any]) -> SyncClient:
    """Production factory -- constructs the real :class:`SyncClient`."""
    return SyncClient(config)


def main(
    argv: list[str] | None = None,
    *,
    syncClientFactory: SyncClientFactory | None = None,
) -> int:
    """CLI entry point.

    Args:
        argv: Optional argv slice; defaults to ``sys.argv[1:]``.
        syncClientFactory: Optional hook to inject a fake SyncClient in
            tests.  Must accept a validated config dict and return an
            object exposing ``pushAllDeltas()`` + ``baseUrl`` + ``batchSize``.

    Returns:
        Exit code (0 on success, 1 on failure).
    """
    args = parseArguments(argv)

    try:
        config = _loadConfig(args.config)
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    factory = syncClientFactory or _defaultSyncClientFactory
    try:
        client = factory(config)
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    baseUrl = getattr(client, "baseUrl", "unknown")
    batchSize = getattr(client, "batchSize", 0) or int(
        config.get("pi", {}).get("companionService", {}).get("batchSize", 0),
    )

    print(_formatStartBanner(baseUrl, batchSize))

    if args.dry_run:
        print(_renderDryRunReport(client))
        return 0

    start = time.monotonic()
    results: list[PushResult] = client.pushAllDeltas()
    elapsed = time.monotonic() - start

    for result in results:
        print(_formatResultLine(result))
    print()
    print(_summaryLines(results, elapsed))

    return 1 if _overallStatus(results) == "FAILED" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
