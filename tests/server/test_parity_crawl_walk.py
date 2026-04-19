################################################################################
# File Name: test_parity_crawl_walk.py
# Purpose/Description: Integration test proving analytics produce identical
#                      results regardless of whether data arrived via bulk
#                      import (crawl path) or HTTP sync (walk path).  Locks in
#                      the architectural invariant that analytics code does not
#                      depend on its data source.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-161 — parity
#               |              | validation between crawl and walk data paths
# ================================================================================
################################################################################

"""
Sync-to-analytics parity validation (Sprint 8 US-161).

Seeds one deterministic synthetic dataset (three drives — two normal, one
anomalous on RPM/SPEED) through two independent ingestion paths:

* **Crawl path** — ``scripts/load_data.loadData`` reads a Pi-schema SQLite
  file and upserts into a target server DB.
* **Walk path** — ``POST /api/v1/sync`` accepts a JSON payload carrying the
  exact same rows and upserts into a second target server DB.

Both paths converge on the same analytics functions
(``computeDriveStatistics`` / ``compareDriveToHistory`` / ``detectAnomalies``),
and every numeric and categorical output is asserted to match within the
server-spec §2.4 tolerance of 0.01% (exact on identical input; the tolerance
is a guardrail against any future floating-point dialect drift).

The ``drive_summary`` creation step is deliberately run from the *same*
helper (``load_data._createDriveSummaries``) on both DBs.  Sync.py does not
auto-create drive_summary rows by design (autoAnalysisTriggered=false — it's
US-CMP-006 / run-phase work).  Using one helper keeps the test's single
variable "how did the rows arrive?" instead of adding a second variable for
drive detection.

Test markers:
    * ``@pytest.mark.integration`` — crosses the HTTP stack + two DBs
    * ``@pytest.mark.parity`` — sprint-level invariant guard
"""

from __future__ import annotations

import asyncio
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("aiosqlite")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts import load_data  # noqa: E402
from src.server.analytics.advanced import detectAnomalies  # noqa: E402
from src.server.analytics.basic import (  # noqa: E402
    compareDriveToHistory,
    computeDriveStatistics,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveStatistic,
    DriveSummary,
)

# ==============================================================================
# Constants
# ==============================================================================

API_KEY = "parity-test-key"
DEVICE_ID = "parity-eclipse-gst"
PROFILE_ID = "daily"
BATCH_ID = "parity-batch"

# Server spec §2.4: per-drive statistics must match within 0.01% between the
# two ingestion paths.
TOLERANCE_PCT = 0.0001

# Parameters we'll emit each sample tick, and their units.
SAMPLED_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("RPM", "rpm"),
    ("SPEED", "km/h"),
    ("COOLANT_TEMP", "°C"),
)

# Three drives chosen so drive #3 breaks the 2σ envelope on RPM and SPEED
# (avg ~= 5000 vs historical mean ~= 2050, sigma > 3) and therefore produces
# non-empty flagged-parameter output from detectAnomalies.  An empty flagged
# set would technically satisfy parity but would not exercise the comparison.
_DRIVE_PROFILES: tuple[dict[str, float], ...] = (
    {"rpm": 2000.0, "speed": 30.0, "coolant": 90.0, "startHour": 8},
    {"rpm": 2100.0, "speed": 32.0, "coolant": 92.0, "startHour": 9},
    {"rpm": 5000.0, "speed": 90.0, "coolant": 95.0, "startHour": 10},
)

# Five evenly spaced samples per drive — enough for non-zero sample stdev.
_SAMPLES_PER_DRIVE = 5


# ==============================================================================
# Dataset builder (deterministic, pure)
# ==============================================================================


def _buildDatasetRows() -> tuple[list[dict], list[dict]]:
    """
    Build the canonical 3-drive dataset as two lists of row dicts.

    Each row carries an integer ``id`` matching its 1-based position in its
    list, so the SQLite ``rowid`` on the crawl side and the HTTP ``id`` field
    on the walk side both map to the same ``source_id`` in the server schema.

    Returns:
        (connectionLogRows, realtimeDataRows) in chronological order.
    """
    baseDate = datetime(2026, 4, 16, 0, 0, 0)
    connectionRows: list[dict] = []
    realtimeRows: list[dict] = []

    clId = 1
    rtId = 1
    for drive in _DRIVE_PROFILES:
        startTs = baseDate.replace(hour=int(drive["startHour"]))
        endTs = startTs + timedelta(minutes=10)

        connectionRows.append({
            "id": clId,
            "timestamp": startTs.isoformat(sep=" "),
            "event_type": "drive_start",
            "success": 1,
        })
        clId += 1

        for i in range(_SAMPLES_PER_DRIVE):
            sampleTs = startTs + timedelta(minutes=1 + i)
            tsStr = sampleTs.isoformat(sep=" ")
            # Small deterministic variation (0.5 per tick) seeds a non-zero
            # sample std dev per parameter without breaking the anomaly test.
            variation = i * 0.5
            for paramName, unit in SAMPLED_PARAMETERS:
                baseValue = drive[_paramKey(paramName)]
                realtimeRows.append({
                    "id": rtId,
                    "timestamp": tsStr,
                    "parameter_name": paramName,
                    "value": float(baseValue + variation),
                    "unit": unit,
                    "profile_id": PROFILE_ID,
                })
                rtId += 1

        connectionRows.append({
            "id": clId,
            "timestamp": endTs.isoformat(sep=" "),
            "event_type": "drive_end",
            "success": 1,
        })
        clId += 1

    return connectionRows, realtimeRows


def _paramKey(paramName: str) -> str:
    """Map OBD parameter name to the _DRIVE_PROFILES dict key."""
    return {
        "RPM": "rpm",
        "SPEED": "speed",
        "COOLANT_TEMP": "coolant",
    }[paramName]


# ==============================================================================
# Path-specific seeders
# ==============================================================================


def _seedCrawlDb(
    piDbPath: Path,
    serverDbPath: Path,
    connectionRows: list[dict],
    realtimeRows: list[dict],
) -> None:
    """
    Populate a server DB via the crawl path.

    Creates a Pi-schema SQLite file containing the canonical dataset, then
    runs ``load_data.loadData`` to upsert into the target server DB.
    """
    from src.pi.obdii.database_schema import (
        SCHEMA_CONNECTION_LOG,
        SCHEMA_PROFILES,
        SCHEMA_REALTIME_DATA,
    )

    piConn = sqlite3.connect(str(piDbPath))
    try:
        piConn.execute("PRAGMA foreign_keys=OFF")
        piConn.execute(SCHEMA_PROFILES)
        piConn.execute(SCHEMA_REALTIME_DATA)
        piConn.execute(SCHEMA_CONNECTION_LOG)

        # Profile row so profile_id FK references resolve on the server side.
        piConn.execute(
            "INSERT INTO profiles (id, name, description, polling_interval_ms) "
            "VALUES (?, ?, ?, ?)",
            (PROFILE_ID, "Daily", "Parity test profile", 1000),
        )

        for row in connectionRows:
            piConn.execute(
                "INSERT INTO connection_log "
                "(id, timestamp, event_type, success) VALUES (?, ?, ?, ?)",
                (row["id"], row["timestamp"], row["event_type"], row["success"]),
            )
        for row in realtimeRows:
            piConn.execute(
                "INSERT INTO realtime_data "
                "(id, timestamp, parameter_name, value, unit, profile_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"], row["timestamp"], row["parameter_name"],
                    row["value"], row["unit"], row["profile_id"],
                ),
            )
        piConn.commit()
    finally:
        piConn.close()

    # Pre-create the server schema, then run loadData.
    serverEngine = create_engine(f"sqlite:///{serverDbPath}")
    try:
        Base.metadata.create_all(serverEngine)
        load_data.loadData(
            dbFile=str(piDbPath),
            deviceId=DEVICE_ID,
            engine=serverEngine,
        )
    finally:
        serverEngine.dispose()


async def _seedWalkDb(
    serverDbPath: Path,
    connectionRows: list[dict],
    realtimeRows: list[dict],
) -> None:
    """
    Populate a server DB via the walk path — HTTP POST ``/api/v1/sync``.

    Builds a FastAPI app with an aiosqlite async engine pointing at
    ``serverDbPath`` and fires one sync request carrying the canonical
    dataset.  Disposes the engine before returning so the SQLite file is
    free for subsequent sync-engine access.
    """
    import httpx
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.server.api.app import createApp
    from src.server.config import Settings

    # Pre-create the server schema with a sync engine so aiosqlite doesn't
    # have to issue DDL — mirrors test_sync.py's asyncAppAndEngine fixture.
    syncEng = create_engine(f"sqlite:///{serverDbPath}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    asyncEngine = create_async_engine(f"sqlite+aiosqlite:///{serverDbPath}")
    settings = Settings(
        DATABASE_URL=f"sqlite+aiosqlite:///{serverDbPath}",
        API_KEY=API_KEY,
        MAX_SYNC_PAYLOAD_MB=10,
    )
    app = createApp(settings=settings)
    app.state.engine = asyncEngine

    payload = {
        "deviceId": DEVICE_ID,
        "batchId": BATCH_ID,
        "tables": {
            "connection_log": {
                "lastSyncedId": 0,
                "rows": connectionRows,
            },
            "realtime_data": {
                "lastSyncedId": 0,
                "rows": realtimeRows,
            },
        },
    }

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": API_KEY},
            )
        assert response.status_code == 200, (
            f"walk-path sync failed: {response.status_code} {response.text}"
        )
        body = response.json()
        assert body["status"] == "ok"
        assert body["driveDataReceived"] is True
    finally:
        await asyncEngine.dispose()


def _finaliseWalkDb(serverDbPath: Path) -> None:
    """
    Create ``drive_summary`` rows on the walk DB using the same helper the
    crawl path invokes.  Sync.py does not auto-create these rows — by design
    (autoAnalysisTriggered=false, US-CMP-006 run-phase story).  Re-using
    ``load_data._createDriveSummaries`` keeps the only variable between the
    two DBs the ingestion path itself.
    """
    engine = create_engine(f"sqlite:///{serverDbPath}")
    try:
        with Session(engine) as session:
            load_data._createDriveSummaries(session, DEVICE_ID)
            session.commit()
    finally:
        engine.dispose()


# ==============================================================================
# Analytics runner (identical on both sides)
# ==============================================================================


def _runAnalytics(serverDbPath: Path) -> dict:
    """
    Run the full analytics pipeline against a populated server DB.

    Returns a comparable snapshot keyed by driveId containing:
        * summary   — DriveSummary attrs (minus id/created_at)
        * stats     — {parameterName: DriveStatistic attrs (minus id)}
        * anomalies — sorted tuple of flagged parameter names
    """
    engine = create_engine(f"sqlite:///{serverDbPath}")
    try:
        with Session(engine) as session:
            drives = session.execute(
                select(DriveSummary)
                .where(DriveSummary.device_id == DEVICE_ID)
                .order_by(DriveSummary.start_time),
            ).scalars().all()
            driveIds = [d.id for d in drives]

            # First: compute stats for every drive so historical aggregates
            # exist by the time we call compareDriveToHistory / detectAnomalies.
            for driveId in driveIds:
                computeDriveStatistics(session, driveId)

            snapshot: dict = {}
            for driveId in driveIds:
                drive = session.get(DriveSummary, driveId)
                stats = session.execute(
                    select(DriveStatistic)
                    .where(DriveStatistic.drive_id == driveId)
                    .order_by(DriveStatistic.parameter_name),
                ).scalars().all()
                anomalies = detectAnomalies(session, driveId)

                snapshot[driveId] = {
                    "summary": {
                        "device_id": drive.device_id,
                        "start_time": drive.start_time,
                        "end_time": drive.end_time,
                        "duration_seconds": drive.duration_seconds,
                        "profile_id": drive.profile_id,
                        "row_count": drive.row_count,
                    },
                    "stats": {
                        s.parameter_name: {
                            "min_value": s.min_value,
                            "max_value": s.max_value,
                            "avg_value": s.avg_value,
                            "std_dev": s.std_dev,
                            "outlier_min": s.outlier_min,
                            "outlier_max": s.outlier_max,
                            "sample_count": s.sample_count,
                        }
                        for s in stats
                    },
                    "anomalies": tuple(
                        sorted(a.parameter_name for a in anomalies)
                    ),
                    "comparison": tuple(
                        sorted(
                            c.parameter_name
                            for c in compareDriveToHistory(session, driveId)
                        )
                    ),
                }
            return snapshot
    finally:
        engine.dispose()


# ==============================================================================
# Fixture — build both DBs once per test session (or per test run)
# ==============================================================================


@pytest.fixture(scope="module")
def parityDbs(tmp_path_factory):
    """
    Seed both server DBs with the canonical dataset and return their paths.

    Scope is ``module`` so the expensive HTTP + dual-load sequence runs
    exactly once for all parity assertions.
    """
    connectionRows, realtimeRows = _buildDatasetRows()

    moduleTmp = tmp_path_factory.mktemp("parity_crawl_walk")
    piDbPath = moduleTmp / "pi_source.db"
    crawlDbPath = moduleTmp / "server_crawl.db"
    walkDbPath = moduleTmp / "server_walk.db"

    # --- Crawl path (sync) ---
    _seedCrawlDb(piDbPath, crawlDbPath, connectionRows, realtimeRows)

    # --- Walk path (async HTTP + aiosqlite), all inside one fresh loop ---
    asyncio.run(
        _seedWalkDb(walkDbPath, connectionRows, realtimeRows),
    )
    _finaliseWalkDb(walkDbPath)

    return crawlDbPath, walkDbPath


@pytest.fixture(scope="module")
def paritySnapshots(parityDbs):
    """Run the full analytics pipeline on both DBs once and cache the results."""
    crawlPath, walkPath = parityDbs
    return _runAnalytics(crawlPath), _runAnalytics(walkPath)


# ==============================================================================
# Assertion helpers
# ==============================================================================


def _floatMatches(a: float | None, b: float | None, tolerance: float) -> bool:
    """True when two floats are equal within ``tolerance`` (relative, fractional)."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0.0:
        return math.isclose(a, b, abs_tol=1e-12)
    return abs(a - b) / denom <= tolerance


# ==============================================================================
# Parity assertions
# ==============================================================================


@pytest.mark.integration
@pytest.mark.parity
class TestCrawlWalkParity:
    """
    One instance of each assertion per sprint acceptance criterion.

    Every test reads both cached snapshots (``paritySnapshots`` module-scoped
    fixture) and asserts identical output from the analytics layer.
    """

    def test_sameDriveCount_bothPaths(self, paritySnapshots):
        """Sanity — both DBs saw the same three drives."""
        crawl, walk = paritySnapshots
        assert set(crawl.keys()) == set(walk.keys())
        assert len(crawl) == len(_DRIVE_PROFILES)

    def test_driveSummaryRows_matchBetweenPaths(self, paritySnapshots):
        """
        Acceptance: drive_summary rows match between crawl and walk paths.

        start_time, end_time, duration_seconds, row_count, and profile_id are
        derived from the inputs deterministically — byte-equal on both sides.
        """
        crawl, walk = paritySnapshots
        for driveId, crawlData in crawl.items():
            walkData = walk[driveId]
            cs = crawlData["summary"]
            ws = walkData["summary"]
            assert cs["device_id"] == ws["device_id"]
            assert cs["start_time"] == ws["start_time"]
            assert cs["end_time"] == ws["end_time"]
            assert cs["duration_seconds"] == ws["duration_seconds"]
            assert cs["row_count"] == ws["row_count"]
            assert cs["profile_id"] == ws["profile_id"]

    def test_driveStatistics_matchBetweenPaths_within0_01pct(
        self, paritySnapshots,
    ):
        """
        Acceptance: per-drive statistics (min, max, avg, std) match within
        0.01% tolerance.  sample_count is an integer and must match exactly.
        """
        crawl, walk = paritySnapshots
        for driveId, crawlData in crawl.items():
            cStats = crawlData["stats"]
            wStats = walk[driveId]["stats"]
            assert set(cStats.keys()) == set(wStats.keys()), (
                f"drive {driveId}: parameter set differs — "
                f"crawl={sorted(cStats)} walk={sorted(wStats)}"
            )
            for paramName in cStats:
                c = cStats[paramName]
                w = wStats[paramName]
                assert c["sample_count"] == w["sample_count"], (
                    f"drive {driveId} param {paramName}: "
                    f"sample_count differs ({c['sample_count']} vs "
                    f"{w['sample_count']})"
                )
                for field in ("min_value", "max_value", "avg_value", "std_dev",
                              "outlier_min", "outlier_max"):
                    assert _floatMatches(c[field], w[field], TOLERANCE_PCT), (
                        f"drive {driveId} param {paramName}: {field} "
                        f"mismatch — crawl={c[field]} walk={w[field]}"
                    )

    def test_anomalyDetection_flagsSameParameters(self, paritySnapshots):
        """
        Acceptance: anomaly detection produces the same flagged parameters.

        The fixture dataset is constructed so drive 3 (5000 RPM, 90 SPEED) is
        a clear 2σ outlier vs drives 1 and 2, guaranteeing a non-empty
        flagged-parameter set on both sides.
        """
        crawl, walk = paritySnapshots
        for driveId, crawlData in crawl.items():
            assert crawlData["anomalies"] == walk[driveId]["anomalies"], (
                f"drive {driveId}: anomaly sets differ — "
                f"crawl={crawlData['anomalies']} walk={walk[driveId]['anomalies']}"
            )

        # Drive 3 must flag RPM and SPEED (synthetic outlier design) — catch
        # a regression where the dataset or envelope rule silently weakens.
        thirdDriveId = sorted(crawl.keys())[-1]
        assert "RPM" in crawl[thirdDriveId]["anomalies"]
        assert "SPEED" in crawl[thirdDriveId]["anomalies"]

    def test_historicalComparison_coversSameParameters(self, paritySnapshots):
        """
        ``compareDriveToHistory`` output must cover the same parameter set.

        (Bonus guard — the story lists only anomaly parity explicitly, but a
        mismatch here would indicate diverging drive_statistics shape and is
        a cheap cross-check.)
        """
        crawl, walk = paritySnapshots
        for driveId, crawlData in crawl.items():
            assert crawlData["comparison"] == walk[driveId]["comparison"]

    def test_noAnalyticsImportFromDataPath(self):
        """
        Invariant: analytics code must not import from crawl/walk ingestion
        modules.  The parity proof is only meaningful if the analytics
        layer is genuinely source-agnostic.
        """
        analyticsSrc = (
            Path("src/server/analytics/basic.py").read_text(encoding="utf-8")
            + Path("src/server/analytics/advanced.py").read_text(encoding="utf-8")
            + Path("src/server/analytics/helpers.py").read_text(encoding="utf-8")
        )
        forbiddenImports = (
            "src.server.api.sync",
            "scripts.load_data",
            "src.server.api.analyze",
        )
        for bad in forbiddenImports:
            assert bad not in analyticsSrc, (
                f"analytics layer imports {bad!r} — violates source-agnostic "
                f"invariant that US-161 proves via runtime parity"
            )


# ==============================================================================
# Exports (mostly for ad-hoc REPL use / future reuse)
# ==============================================================================


__all__ = [
    "API_KEY",
    "DEVICE_ID",
    "TOLERANCE_PCT",
]
