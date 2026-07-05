################################################################################
# File Name: owned_tables.py
# Purpose/Description: US-449 / F-104 -- owned-table manifest for the server
#                      persisted-analytics tables.  Enumerates every persisted-
#                      analytics table with its ONE authoritative writer so
#                      "the harness is the sole writer / no dual-write" is a
#                      CHECKABLE contract, not a claim.  Companion test source-
#                      scans + behaviourally proves the /analyze flow writes
#                      NONE of these tables (pure consumer).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-449) | Initial -- F-104 sole-writer manifest.  BL-017
#               |              | (Atlas Option A): /analyze is a PURE CONSUMER;
#               |              | the B-104 harness is the sole writer of the
#               |              | tables it computes.  anomaly_log / trend_snapshots
#               |              | / statistics are honestly enumerated with their
#               |              | true current writer + a harness-owned target.
# ================================================================================
################################################################################

"""US-449 / F-104 -- owned-table manifest (sole-writer registry).

BL-017 taught us that a "sole writer" claim must be *checkable*: a second live
writer of ``drive_statistics`` (``analytics.basic.computeDriveStatistics`` via
``POST /api/v1/analyze``) went undetected until an audit.  This module makes the
writer of every persisted-analytics table explicit, so a test can assert:

1. every persisted-analytics table is enumerated with exactly ONE writer, and
2. the ``/analyze`` consumer flow (``src.server.services.analysis``) writes
   NONE of them -- it only READS harness-authoritative rows, or triggers the
   HARNESS compute on a miss.

**F-104 boundary rule.**  A fact is server-authoritative iff the server can
reproduce it from synced raw (``realtime_data`` / ``connection_log``).  The
authoritative writer is the **B-104 analytics harness**:

* ``drive_summary_compute.compute_drive_summary``
* ``drive_statistics_compute.compute_drive_statistics``
* ``derived_signals_compute.compute_drive_derived_signals``

invoked by the nightly ``server-analytics-batch.timer`` and the on-demand CLI
``src.server.cli.recompute_drive_analytics`` (one timer / one CLI tick fires all
three per drive).  The harness is idempotent (re-run over the same raw = 0 row
diffs; proven by ``tests/server/analytics/test_harness_idempotency.py``) and
keys its rows on ``drive_summary.id`` -- the canonical drive identity subsumed
into ``drives.drive_id`` by US-448.

**Honesty (F-104 is a half-landed spine).**  ``anomaly_log`` and
``trend_snapshots`` are *derived* from ``drive_statistics`` but the harness does
not yet compute them; ``statistics`` is a legacy rollup US-452 reconciles.  This
manifest records each table's TRUE current writer and flags the harness-owned
target as a follow-up rather than claiming a sole-writer state that does not yet
exist.  What US-449 *does* guarantee -- and the companion test enforces -- is
that ``/analyze`` writes none of these tables.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---- Writer identities ------------------------------------------------------

# The B-104 server-analytics harness (summary/statistics/derived compute,
# nightly timer + recompute CLI).
WRITER_HARNESS = "harness"

# The trend-report CLI path
# (reports.trend_report.buildTrendReport -> advanced.computeTrends), which
# intentionally accumulates a trend_snapshots row per call (spec §1.8).
WRITER_TREND_REPORT_CLI = "trend_report_cli"

# No live writer: the table is honest-empty in production and its designated
# owner (the harness) does not compute it yet.  Distinct from "unknown" -- it
# is a documented, intentional state pending a future F-104 follow-up.
WRITER_NONE = "none"


@dataclass(frozen=True, slots=True)
class OwnedTable:
    """One persisted-analytics table and its single authoritative writer.

    Attributes:
        table: SQL table name (``__tablename__``).
        writer: One of the ``WRITER_*`` identities above.
        writer_ref: Dotted reference to the concrete writer (or ``"(none)"``).
        harness_owned: ``True`` iff the harness is the live sole writer today.
        analyze_writes: ``True`` iff the ``/analyze`` flow persists this table.
            MUST be ``False`` for every table post-US-449 (the sole-writer
            contract the companion test enforces).
        notes: Grounding / status detail.
    """

    table: str
    writer: str
    writer_ref: str
    harness_owned: bool
    analyze_writes: bool
    notes: str


# ---- The manifest -----------------------------------------------------------

PERSISTED_ANALYTICS_TABLES: tuple[OwnedTable, ...] = (
    OwnedTable(
        table="drive_summary",
        writer=WRITER_HARNESS,
        writer_ref="src.server.analytics.drive_summary_compute.compute_drive_summary",
        harness_owned=True,
        analyze_writes=False,
        notes=(
            "Harness sole writer (US-350). /analyze reads the DriveSummary it "
            "is handed; the retired trigger-seam writer (_ensureDriveSummary) "
            "is unreachable behind the enqueueAutoAnalysisForSync "
            "NotImplementedError tripwire (B-076 owns residual-helper cleanup)."
        ),
    ),
    OwnedTable(
        table="drive_statistics",
        writer=WRITER_HARNESS,
        writer_ref="src.server.analytics.drive_statistics_compute.compute_drive_statistics",
        harness_owned=True,
        analyze_writes=False,
        notes=(
            "Harness sole writer (US-351). BL-017 FIX: /analyze retired its "
            "second writer (analytics.basic.computeDriveStatistics) -- it now "
            "READS harness rows and, on a miss, triggers the HARNESS compute "
            "(never basic.py). basic.computeDriveStatistics still exists for "
            "the crawl-phase report seeding + the retired-seam helpers, but is "
            "no longer on any /analyze path."
        ),
    ),
    OwnedTable(
        table="drive_derived_signals",
        writer=WRITER_HARNESS,
        writer_ref="src.server.analytics.derived_signals_compute.compute_drive_derived_signals",
        harness_owned=True,
        analyze_writes=False,
        notes="Harness sole writer (US-436 / F-106). /analyze does not touch it.",
    ),
    OwnedTable(
        table="anomaly_log",
        writer=WRITER_NONE,
        writer_ref="(none live) -- advanced.detectAnomalies persists but has no live caller post-US-449",
        harness_owned=False,
        analyze_writes=False,
        notes=(
            "US-449 retired the /analyze anomaly_log write: _buildAnalyticsContext "
            "now uses advanced.evaluateAnomalies (pure, in-memory) for the prompt "
            "context. advanced.detectAnomalies (the persisting wrapper) has no "
            "remaining live caller, so anomaly_log is honest-empty in production. "
            "TARGET: fold anomaly compute under the harness in a future F-104 "
            "follow-up so anomaly_log becomes harness_owned."
        ),
    ),
    OwnedTable(
        table="trend_snapshots",
        writer=WRITER_TREND_REPORT_CLI,
        writer_ref="src.server.reports.trend_report.buildTrendReport -> src.server.analytics.computeTrends",
        harness_owned=False,
        analyze_writes=False,
        notes=(
            "US-449 retired the /analyze trend_snapshots write: "
            "_buildAnalyticsContext now uses advanced.evaluateTrend (pure, "
            "in-memory). The only remaining writer is the trend-report CLI, "
            "which intentionally accumulates a snapshot per call (spec §1.8) -- "
            "a single, non-/analyze, non-harness writer (no dual-write). "
            "TARGET: fold trend compute under the harness in a future F-104 "
            "follow-up."
        ),
    ),
    OwnedTable(
        table="statistics",
        writer=WRITER_NONE,
        writer_ref="(none) -- legacy rollup; no code constructs a Statistic row",
        harness_owned=False,
        analyze_writes=False,
        notes=(
            "Legacy crawl-phase rollup table (models.Statistic). No live writer "
            "exists (grep: no `Statistic(` constructor in src/). US-452 "
            "reconciles statistics (rollup) vs drive_statistics (granular SSOT) "
            "as harness-derived with no dual-write."
        ),
    ),
)


# The tables the /analyze consumer path (src.server.services.analysis) must
# NEVER directly persist -- the BL-017 sole-writer contract.  It may only READ
# them or trigger the HARNESS compute on a miss.
ANALYZE_FORBIDDEN_WRITE_TABLES: tuple[str, ...] = tuple(
    t.table for t in PERSISTED_ANALYTICS_TABLES
)


def manifest_by_table() -> dict[str, OwnedTable]:
    """Return the manifest indexed by table name."""
    return {t.table: t for t in PERSISTED_ANALYTICS_TABLES}


def harness_owned_tables() -> tuple[str, ...]:
    """Return the tables the harness is the live sole writer of today."""
    return tuple(t.table for t in PERSISTED_ANALYTICS_TABLES if t.harness_owned)


__all__ = [
    "ANALYZE_FORBIDDEN_WRITE_TABLES",
    "PERSISTED_ANALYTICS_TABLES",
    "WRITER_HARNESS",
    "WRITER_NONE",
    "WRITER_TREND_REPORT_CLI",
    "OwnedTable",
    "harness_owned_tables",
    "manifest_by_table",
]
