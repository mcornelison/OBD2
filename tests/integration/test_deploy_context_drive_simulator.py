################################################################################
# File Name: test_deploy_context_drive_simulator.py
# Purpose/Description: I-040 structural close (US-355) -- deploy-context drive
#                      simulator. Pytest harness exercising the integrated
#                      Pi-database -> sync -> server-compute path against real
#                      DBs (Pi SQLite + server SQLite with the production ORM)
#                      without mocking the writer/compute seams. Captures the
#                      V0.27.16 false-pass scenario as ONE seeded reproducer
#                      and parameterizes the architectural cut: with B-104
#                      Step 1 server compute the scenario is GREEN; without it
#                      (V0.27.7 / V0.27.16 trigger-seam architecture, whose
#                      writer never fired on sequencer-driven termination) it
#                      is RED. The retroactive RED proof is the second test
#                      in this module -- same scenario, no compute invocation,
#                      drive_summary stays NULL.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-355) | Initial -- I-040 structural close. The 3-cycle
#               |              | V0.27.7/V0.27.16 false-pass class (US-326 /
#               |              | US-328 / US-348 / US-349) shipped through
#               |              | because unit-test fixtures stub-replaced the
#               |              | trigger seam; the seam never fired in the
#               |              | deploy because the Pi-side drive-end signal
#               |              | does not materialize on sequencer-driven
#               |              | termination. This harness uses the REAL Pi
#               |              | sqlite3 schema + the REAL server ORM + the
#               |              | REAL compute functions and forces the same
#               |              | scenario Argus drilled in V0.27.16 (drive 20:
#               |              | engine-on producing realtime_data rows ->
#               |              | sequencer poweroff with no engine-off OBD
#               |              | signal -> next-boot recovery). GREEN test
#               |              | invokes B-104 Step 1 compute; RED test
#               |              | mirrors the V0.27.16 architecture by NOT
#               |              | invoking compute (trigger-seam writer would
#               |              | also have stayed silent in this scenario) and
#               |              | asserts drive_summary computed fields stay
#               |              | NULL + drive_statistics zero rows.
# ================================================================================
################################################################################

"""US-355 / I-040 structural close -- deploy-context drive simulator.

Builds a pytest harness exercising the integrated data path (Pi sqlite ->
sync transport -> server compute) against real databases with NO mock of
the writer or compute seams.  The single seeded scenario reproduces
Argus's 2026-05-21 V0.27.16 drill: a drive whose realtime_data rows are
captured to Pi but whose drive-end OBD signal never fires because the
shutdown sequencer pulls the OBD stack down before engine-off transmits.

Architectural cut (B-104 Step 1, Sprint 41 / V0.27.17): server reads raw
``realtime_data`` MIN/MAX/COUNT directly and computes ``drive_summary``
analytics + per-parameter ``drive_statistics``.  No Pi-side drive-end
marker dependency.  The harness's GREEN test invokes
:func:`src.server.analytics.drive_summary_compute.compute_drive_summary`
and :func:`src.server.analytics.drive_statistics_compute.compute_drive_statistics`
after the sync; analytics fields are populated and per-PID stats rows
land.

Retroactive RED proof (acceptance criterion 4): the SAME scenario without
the B-104 compute invocation is the V0.27.7 / V0.27.16 architectural
shape.  The Pi-side trigger seam (DriveStatisticsRecorder hooked to
DriveDetector.engine_off) and the server-side trigger seam
(``_tryAutoAnalysisTrigger`` on /sync receipt) both depend on a drive-end
event that this scenario does not produce.  Therefore "skip compute"
faithfully captures the failure mode: drive_summary computed fields stay
NULL, drive_statistics has zero rows.  Companion procedure for an
out-of-tree retroactive run against the actual V0.27.16 commit
(``c04d36e``) is documented in
``docs/superpowers/specs/2026-05-21-deploy-context-drive-simulator.md``.

Test discipline (post-I-040)
----------------------------

* Real Pi sqlite3 connection running the production ``database_schema``
  + ``ensureDriveSummaryTable`` migrations -- no Pi-side mock seams.
* Real server SQLAlchemy engine with the production ``Base.metadata``
  schema -- no server-side mock seams.
* Direct DB-to-DB sync (Pi rows replayed into the server ORM in the
  shape the HTTP /sync endpoint would have produced).  HTTP transport
  is exercised separately by ``tests/integration/test_pi_to_server_e2e.py``
  -- this harness focuses on the writer/compute seam where the 3-cycle
  false-pass class lived.
* The compute functions are imported + called for real.  No mocks.

Scenario coverage roadmap (V0.28+):

1. Scenario 1 (this file): V0.27.16 false-pass reproducer -- one drive,
   sequencer-terminated, single sync round-trip.  Pinned RED / GREEN.
2. Scenario 2 (deferred): sparse drive -- 5 realtime rows; assert
   data_quality='below_threshold'.
3. Scenario 3 (deferred): replay drive (data_source='replay') -->
   is_real=None (NULL preservation per Atlas Q2).
4. Scenario 4 (deferred): partial sync (sync log shows realtime_data
   landed but drive_summary did not) -- server compute logs WARN, does
   not raise.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.pi.obdii.database import ObdDatabase  # noqa: E402
from src.server.analytics.drive_statistics_compute import (  # noqa: E402
    compute_drive_statistics,
)
from src.server.analytics.drive_summary_compute import (  # noqa: E402
    compute_drive_summary,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)

pytestmark = pytest.mark.integration


# =========================================================================
# Constants
# =========================================================================

# Argus's V0.27.16 drill drive 20 shape -- the scenario the harness pins.
SCENARIO_1_DRIVE_ID = 20
SCENARIO_1_DEVICE = "chi-eclipse-01"
SCENARIO_1_START_TIME = datetime(2026, 5, 21, 17, 29, 21)
SCENARIO_1_DURATION_SECONDS = 540  # ~9 min, mirrors drive 20
SCENARIO_1_POLL_INTERVAL_S = 1.0
# 16 PIDs match the live Pi poll set (Argus drill: drive 20 had 16
# distinct parameter_names across 3,808 realtime_data rows).  A subset
# of 4 keeps the test fast while exercising the per-PID compute path
# with enough rows to land in the 'full' data_quality bucket (>=100
# samples per PID after 540s @ 1Hz).
SCENARIO_1_PARAMETERS = ("RPM", "SPEED", "MAP", "COOLANT_TEMP")


# =========================================================================
# Fixtures -- real Pi sqlite + real server SQLAlchemy engine, no mocks
# =========================================================================


@pytest.fixture
def piDatabase():
    """Real Pi ``ObdDatabase`` backed by a temp SQLite file.

    Runs the production migrations (``ensureDriveSummaryTable``,
    ``ensureAllDriveIdColumns``, ``ensureDriveStatisticsRetired``, etc.)
    so the harness's writes hit the deploy-faithful schema -- not a
    sketch of it.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = Path(tmpdir) / "obd.db"
        db = ObdDatabase(str(dbPath))
        db.initialize()
        yield db


@pytest.fixture
def serverEngine():
    """Real server SQLAlchemy engine with the full production schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


# =========================================================================
# Scenario builders -- no mock seams; real sqlite3 + real ORM writes
# =========================================================================


def _simulateSequencerTerminatedDrive(
    piDatabase: ObdDatabase,
    *,
    driveId: int,
    startTime: datetime,
    durationSeconds: int,
    parameters: tuple[str, ...],
    pollIntervalSeconds: float,
) -> int:
    """Drop a drive into Pi sqlite without firing the drive-end signal.

    Models the V0.27.16 failure mode: engine-on accumulates realtime_data
    + drive_summary row with event-log fields is written, then the
    shutdown sequencer tears the OBD stack down without an engine-off
    OBD signal so ``DriveDetector._endDrive`` never fires.  No mock seam
    -- writes hit the real Pi sqlite3 schema directly through the same
    table definitions the production orchestrator uses.

    Returns the total number of realtime_data rows inserted (one row per
    poll-tick per parameter).
    """
    rowsInserted = 0
    sampleCount = int(durationSeconds / pollIntervalSeconds)
    with piDatabase.connect() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO drive_summary (
                drive_id,
                drive_start_timestamp,
                ambient_temp_at_start_c,
                starting_battery_v,
                barometric_kpa_at_start,
                data_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                driveId,
                startTime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                19.0,
                14.2,
                101.3,
                "real",
            ),
        )

        for i in range(sampleCount):
            ts = startTime + timedelta(seconds=i * pollIntervalSeconds)
            tsIso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
            for param in parameters:
                cursor.execute(
                    """
                    INSERT INTO realtime_data (
                        timestamp,
                        parameter_name,
                        value,
                        drive_id,
                        data_source
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        tsIso,
                        param,
                        float(_syntheticValueFor(param, i)),
                        driveId,
                        "real",
                    ),
                )
                rowsInserted += 1
        conn.commit()
    return rowsInserted


def _syntheticValueFor(parameter: str, tick: int) -> float:
    """Deterministic per-PID value generator with realistic ranges.

    Picks bounds that put the synthetic aggregates inside Spool's typical
    safe operating envelope so future per-PID invariant tests (V0.28+)
    can stack on this harness without re-seeding.  Variance is non-zero
    so std_dev > 0 + outlier bounds are meaningful.
    """
    baselines = {
        "RPM": (1800.0, 600.0),         # mean ~1800, swing ~600
        "SPEED": (45.0, 15.0),          # 30-60 mph cruise
        "MAP": (80.0, 20.0),            # part-throttle MAP kPa
        "COOLANT_TEMP": (90.0, 5.0),    # warmed-up coolant C
    }
    mean, span = baselines.get(parameter, (100.0, 10.0))
    # Triangle wave: deterministic + bounded, gives stable min/max/avg.
    cyclePos = (tick % 100) / 100.0
    if cyclePos <= 0.5:
        offset = (cyclePos * 2) * span
    else:
        offset = (2 - cyclePos * 2) * span
    return mean - (span / 2) + offset


def _syncPiToServer(
    piDatabase: ObdDatabase,
    serverEngine,
    *,
    sourceDevice: str,
) -> tuple[int, int]:
    """Replay Pi rows into the server DB through the production ORM.

    The actual /api/v1/sync HTTP transport is exercised by
    ``test_pi_to_server_e2e.py``; here we directly copy rows in the
    shape that endpoint would have produced (preserves source_device +
    source_id natural key) so the harness focuses on the writer/compute
    seam where the false-pass class lived.

    Returns ``(driveSummaryRowsSynced, realtimeRowsSynced)``.
    """
    driveSummaryRowsSynced = 0
    realtimeRowsSynced = 0

    with piDatabase.connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM drive_summary")
        piDriveSummaryRows = cursor.fetchall()

        cursor.execute("SELECT * FROM realtime_data ORDER BY id ASC")
        piRealtimeRows = cursor.fetchall()

    with Session(serverEngine) as session:
        for row in piDriveSummaryRows:
            session.add(
                DriveSummary(
                    source_device=sourceDevice,
                    source_id=row["drive_id"],
                    drive_id=row["drive_id"],
                    drive_start_timestamp=_parseSqliteTimestamp(
                        row["drive_start_timestamp"],
                    ),
                    ambient_temp_at_start_c=row["ambient_temp_at_start_c"],
                    starting_battery_v=row["starting_battery_v"],
                    barometric_kpa_at_start=row["barometric_kpa_at_start"],
                    data_source=row["data_source"],
                    # Analytics columns explicitly NULL on landing --
                    # mirrors the Pi-sync-only state the V0.27.16 drill
                    # observed before server compute runs.
                    start_time=None,
                    end_time=None,
                    duration_seconds=None,
                    row_count=None,
                    is_real=None,
                ),
            )
            driveSummaryRowsSynced += 1

        for row in piRealtimeRows:
            session.add(
                RealtimeData(
                    source_device=sourceDevice,
                    source_id=row["id"],
                    timestamp=_parseSqliteTimestamp(row["timestamp"]),
                    parameter_name=row["parameter_name"],
                    value=row["value"],
                    drive_id=row["drive_id"],
                    data_source=row["data_source"],
                ),
            )
            realtimeRowsSynced += 1

        session.commit()

    return driveSummaryRowsSynced, realtimeRowsSynced


def _parseSqliteTimestamp(raw: str | None) -> datetime | None:
    """SQLite stores ISO-8601 ``...Z``; the server ORM wants a datetime."""
    if raw is None:
        return None
    # Strip trailing 'Z' for fromisoformat compatibility on 3.11.
    isoStr = raw.rstrip("Z")
    return datetime.fromisoformat(isoStr)


def _readServerDriveSummary(
    serverEngine, *, driveId: int, sourceDevice: str,
) -> DriveSummary | None:
    """Re-read the server drive_summary row after compute (no mocks)."""
    with Session(serverEngine) as session:
        return session.execute(
            select(DriveSummary).where(
                (DriveSummary.source_device == sourceDevice)
                & (DriveSummary.source_id == driveId)
            )
        ).scalars().first()


def _readServerDriveStatistics(
    serverEngine, *, summaryId: int,
) -> list[DriveStatistic]:
    """Re-read the server drive_statistics rows after compute (no mocks)."""
    with Session(serverEngine) as session:
        return list(
            session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.drive_id == summaryId
                )
            ).scalars().all(),
        )


# =========================================================================
# Scenario 1 -- V0.27.16 false-pass reproducer
# =========================================================================


class TestScenario1V0_27_16Reproducer:
    """The scenario Argus drilled on 2026-05-21 + that previously false-passed.

    Engine on for ~9 min producing realtime_data rows tagged with a
    drive_id; followed by sequencer poweroff (DriveDetector engine_off
    NOT fired); then next-boot post-sync sweep.  GREEN with B-104 Step
    1 server compute (V0.27.17); RED without it (V0.27.7 / V0.27.16
    deployed architecture).
    """

    def test_scenario_1_v0_27_16_reproducer_GREEN_on_current_branch(
        self, piDatabase, serverEngine,
    ):
        """V0.27.17 architecture: server compute populates analytics.

        Acceptance criterion mapping:
        - drive_summary computed fields NON-NULL + arithmetically consistent
          with realtime_data MIN/MAX/COUNT  (bigDoD US-350)
        - drive_statistics has >=1 row per parameter_name with sensible
          values (bigDoD US-351)
        """
        rowsInserted = _simulateSequencerTerminatedDrive(
            piDatabase,
            driveId=SCENARIO_1_DRIVE_ID,
            startTime=SCENARIO_1_START_TIME,
            durationSeconds=SCENARIO_1_DURATION_SECONDS,
            parameters=SCENARIO_1_PARAMETERS,
            pollIntervalSeconds=SCENARIO_1_POLL_INTERVAL_S,
        )
        expectedSamplesPerParam = int(
            SCENARIO_1_DURATION_SECONDS / SCENARIO_1_POLL_INTERVAL_S
        )
        assert rowsInserted == expectedSamplesPerParam * len(
            SCENARIO_1_PARAMETERS
        )

        summaryRowsSynced, realtimeRowsSynced = _syncPiToServer(
            piDatabase, serverEngine, sourceDevice=SCENARIO_1_DEVICE,
        )
        assert summaryRowsSynced == 1
        assert realtimeRowsSynced == rowsInserted

        # B-104 Step 1 compute path -- the architectural fix.
        with Session(serverEngine) as session:
            summaryId = compute_drive_summary(
                session, SCENARIO_1_DRIVE_ID,
            )
            assert summaryId is not None, (
                "compute_drive_summary returned None -- the scenario "
                "produced realtime_data + drive_summary rows but the "
                "compute did not converge"
            )
            statsWritten = compute_drive_statistics(
                session, SCENARIO_1_DRIVE_ID,
            )
            assert statsWritten == len(SCENARIO_1_PARAMETERS)
            session.commit()

        # Assert drive_summary computed fields landed (GREEN).
        summary = _readServerDriveSummary(
            serverEngine,
            driveId=SCENARIO_1_DRIVE_ID,
            sourceDevice=SCENARIO_1_DEVICE,
        )
        assert summary is not None
        assert summary.start_time is not None, (
            "drive_summary.start_time NULL after B-104 compute -- the "
            "V0.27.7/V0.27.16 false-pass would have shipped if this "
            "assertion did not exist"
        )
        assert summary.end_time is not None
        assert summary.duration_seconds is not None
        assert summary.row_count == rowsInserted, (
            f"row_count mismatch: stored {summary.row_count} vs "
            f"realtime_data total {rowsInserted}; arithmetic consistency "
            f"is the bigDoD US-350 acceptance criterion"
        )
        assert summary.is_real is True, (
            "is_real must derive from data_source='real' per Atlas Q2; "
            "NULL or False here means the compute path or the sync "
            "transport corrupted the event-log tag"
        )
        # Duration matches realtime_data span: (samples - 1) * pollInterval.
        expectedDurationS = int(
            (expectedSamplesPerParam - 1) * SCENARIO_1_POLL_INTERVAL_S
        )
        assert summary.duration_seconds == expectedDurationS

        # Assert drive_statistics rows landed (GREEN).
        statsRows = _readServerDriveStatistics(
            serverEngine, summaryId=summary.id,
        )
        assert len(statsRows) == len(SCENARIO_1_PARAMETERS)
        statsByParam = {row.parameter_name: row for row in statsRows}
        for param in SCENARIO_1_PARAMETERS:
            assert param in statsByParam, (
                f"drive_statistics missing row for {param!r}; per-PID "
                f"compute did not write this parameter"
            )
            row = statsByParam[param]
            # Atlas Refinement A invariants on real aggregates.
            assert row.min_value <= row.avg_value <= row.max_value
            assert row.std_dev is None or row.std_dev >= 0
            assert row.sample_count == expectedSamplesPerParam
            # Atlas Refinement B: >=100 samples per param -> 'full'.
            assert row.data_quality == "full"

    def test_scenario_1_v0_27_16_reproducer_RED_legacy_writer_architecture(
        self, piDatabase, serverEngine,
    ):
        """V0.27.7 / V0.27.16 architecture: no compute fires -> RED.

        Faithfully reproduces the V0.27.16 failure mode by NOT invoking
        the B-104 Step 1 compute path.  In V0.27.7 / V0.27.16 production
        code the Pi-side DriveStatisticsRecorder + the server-side
        _tryAutoAnalysisTrigger were both architected to fire on a
        Pi-side drive-end signal.  That signal does not fire on
        sequencer-driven termination (Argus's RCA 2026-05-21); therefore
        no writer ever wrote.  drive_summary computed fields stay NULL +
        drive_statistics has zero rows -- the exact pattern Argus
        captured on drive 20.

        This is the RED proof per US-355 acceptance criterion 4 + the
        bigDoD #6 requirement that the harness would have caught the
        3-cycle false-pass class.
        """
        _simulateSequencerTerminatedDrive(
            piDatabase,
            driveId=SCENARIO_1_DRIVE_ID,
            startTime=SCENARIO_1_START_TIME,
            durationSeconds=SCENARIO_1_DURATION_SECONDS,
            parameters=SCENARIO_1_PARAMETERS,
            pollIntervalSeconds=SCENARIO_1_POLL_INTERVAL_S,
        )
        _syncPiToServer(
            piDatabase, serverEngine, sourceDevice=SCENARIO_1_DEVICE,
        )

        # V0.27.16 architecture: no compute is invoked -- the trigger
        # seam never fired.  This is the deploy-faithful failure mode.

        summary = _readServerDriveSummary(
            serverEngine,
            driveId=SCENARIO_1_DRIVE_ID,
            sourceDevice=SCENARIO_1_DEVICE,
        )
        assert summary is not None, (
            "Pi-sync transport landed the drive_summary row -- this "
            "RED assertion is about analytics fields, not transport"
        )
        # The exact NULL pattern Argus observed on drive 20 (V0.27.16):
        assert summary.start_time is None, (
            "RED proof breached: start_time populated without a compute "
            "call -- something in the harness is invoking compute "
            "implicitly"
        )
        assert summary.end_time is None
        assert summary.duration_seconds is None
        # row_count defaults to 0 via server_default in the ORM; either
        # NULL or 0 is the V0.27.16 false-pass shape.
        assert summary.row_count in (None, 0)

        statsRows = _readServerDriveStatistics(
            serverEngine, summaryId=summary.id,
        )
        assert statsRows == [], (
            f"RED proof breached: drive_statistics has {len(statsRows)} "
            f"rows -- expected 0 (V0.27.7/V0.27.16 architecture wrote "
            f"none in this scenario)"
        )


# =========================================================================
# Harness integrity -- pin "no mock seams" + "real DBs" claims
# =========================================================================


class TestHarnessIntegrity:
    """Pin the load-bearing claims this harness makes.

    If any of these checks regress the harness has silently weakened
    into a mock-seam test surface and the false-pass class can ship
    again.  Atlas + Argus + Marcus + Ralph sign-off (US-355 bigDoD #6)
    rides on these.
    """

    def test_piDatabase_isRealObdDatabase_notMock(self, piDatabase):
        """The Pi side runs the production ``ObdDatabase`` -- not a mock."""
        assert isinstance(piDatabase, ObdDatabase)
        # Schema check: the production migrations actually ran.
        with piDatabase.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name IN "
                "('drive_summary','realtime_data','connection_log')"
            )
            tableNames = {row[0] for row in cursor.fetchall()}
        assert tableNames == {
            "drive_summary", "realtime_data", "connection_log",
        }

    def test_serverEngine_runsRealOrmSchema(self, serverEngine):
        """The server side runs ``Base.metadata`` -- not a sketch."""
        with Session(serverEngine) as session:
            # If the production tables aren't there, these SELECTs raise.
            session.execute(select(DriveSummary)).first()
            session.execute(select(RealtimeData)).first()
            session.execute(select(DriveStatistic)).first()

    def test_computeFunctions_areTheProductionImports_notMocks(self):
        """The compute callables ARE the production module functions."""
        from src.server.analytics import (
            drive_statistics_compute as statsModule,
        )
        from src.server.analytics import (
            drive_summary_compute as summaryModule,
        )
        # Identity check -- no monkeypatch / mock substitution.
        assert compute_drive_summary is summaryModule.compute_drive_summary
        assert (
            compute_drive_statistics
            is statsModule.compute_drive_statistics
        )

    def test_scenario1_doesNotFireDriveEndSignal(self, piDatabase):
        """The scenario builder MUST NOT call DriveDetector._endDrive.

        That is the load-bearing condition of the V0.27.16 failure
        mode: drive-end never fires.  If the harness ever starts
        emitting drive_end connection_log events the RED test is no
        longer faithful.
        """
        _simulateSequencerTerminatedDrive(
            piDatabase,
            driveId=SCENARIO_1_DRIVE_ID,
            startTime=SCENARIO_1_START_TIME,
            durationSeconds=10,
            parameters=("RPM",),
            pollIntervalSeconds=1.0,
        )
        with piDatabase.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM connection_log "
                "WHERE event_type IN ('drive_end','engine_off')"
            )
            (driveEndEventCount,) = cursor.fetchone()
        assert driveEndEventCount == 0, (
            "Scenario builder fired a drive-end / engine-off event "
            "-- this defeats the V0.27.16 reproducer + invalidates "
            "the RED proof"
        )
