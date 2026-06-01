################################################################################
# File Name: test_drive_summary_drive_id_invariant.py
# Purpose/Description: Sprint 43 V0.28.0 (US-372 / F-076) -- tests for the
#                      drive_summary.drive_id <-> source_id invariant.  Q1 ruling
#                      2026-05-28: backfill + CHECK invariant (not the SSOT-purist
#                      column drop, which is deferred to a later V0.28+
#                      normalization).  Covers: the ORM CheckConstraint shape +
#                      SQLite enforcement (both-NULL allowed; equal allowed;
#                      asymmetric / divergent rejected); the v0010 migration
#                      substep (UPDATE-before-ALTER backfill in BOTH directions,
#                      then ADD CONSTRAINT; idempotent no-op when already present;
#                      hermetic FakeRunner, no MariaDB); and the writer-path
#                      discipline that keeps the invariant true going forward
#                      (server sync maps Pi id -> source_id AND mirrors it onto
#                      drive_id; compute_drive_summary heals a legacy NULL mirror).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-372) | Initial -- F-076 drive_summary drive_id/source_id
#               |              | backfill + CHECK invariant + writer-path tests.
# ================================================================================
################################################################################

"""TDD tests for the US-372 drive_summary.drive_id <-> source_id invariant.

Production smell (Q1): a Pi-sync ``drive_summary`` row arrives with the Pi
``drive_counter`` id mapped to ``source_id`` while the ``drive_id`` mirror
column is left NULL (the wire renames the Pi PK ``drive_id`` -> ``id`` ->
``source_id`` server-side; nothing populated the mirror).  Future readers that
join on ``drive_id`` were bitten by the NULL.  US-372 resolves it with a
backfill + a CHECK invariant: a row is either fully un-attributed (both NULL,
the legacy analytics path) or the two columns agree.

Test discipline (post-I-040): the enforcement + writer tests use a real
in-memory / temp-file SQLite engine + the real ORM + real INSERTs.  The
migration substep is tested hermetically with the FakeRunner pattern shared by
the other v0010 substep tests (no SSH, no MariaDB).
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts import apply_server_migrations as asm  # noqa: E402
from src.server.analytics.drive_summary_compute import (  # noqa: E402
    compute_drive_summary,
)
from src.server.api.sync import runSyncUpsert  # noqa: E402
from src.server.db import models as db_models  # noqa: E402
from src.server.db.models import (  # noqa: E402
    Base,
    DriveSummary,
    RealtimeData,
)
from src.server.migrations.runner import RunnerContext  # noqa: E402
from src.server.migrations.versions import (  # noqa: E402
    v0010_us363_attribution_anomaly_data_quality as m0010,
)

# ================================================================================
# Fixtures + helpers
# ================================================================================


@pytest.fixture
def engine():
    """Temp-file SQLite engine carrying the full server schema.

    Temp file (not ``:memory:``) so a second raw connection -- used by the
    heal test to seed the pre-migration smell row with the CHECK disabled --
    sees the same database.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedRealtime(session: Session, *, driveId: int, device: str = "chi-eclipse-01",
                  samples: int = 5) -> None:
    """Seed a few realtime_data rows for ``driveId`` so compute has data."""
    base = datetime(2026, 5, 1, 12, 0, 0)
    for i in range(samples):
        session.add(RealtimeData(
            source_id=driveId * 1000 + i,
            source_device=device,
            timestamp=base + timedelta(seconds=i),
            parameter_name="RPM",
            value=2000.0 + i,
            data_source="real",
            drive_id=driveId,
        ))
    session.commit()


# ---- FakeRunner (mirrors test_migration_0010_us371) -------------------------


@dataclass
class FakeRunner:
    handlers: list[tuple[str, Callable[[str], subprocess.CompletedProcess[str]]]] = (
        field(default_factory=list)
    )
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = input or ''
        self.calls.append({'argv': list(argv), 'input': sql, 'timeout': timeout})
        for needle, handler in self.handlers:
            if needle in sql:
                return handler(sql)
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout='', stderr='',
        )

    @property
    def emittedSqls(self) -> list[str]:
        return [c['input'] for c in self.calls if c['input']]


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _scriptInvariantSubstep(runner: FakeRunner, *, alreadyPresent: bool) -> None:
    """Script the probes the US-372 substep issues, in isolation.

    ``alreadyPresent`` False -> constraint absent on the first probe (ADD
    fires), present on the post-condition probe (success path).  True ->
    present on every probe (idempotent no-op path).
    """
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))
    chkCalls = {'n': 0}

    def chkProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        chkCalls['n'] += 1
        if alreadyPresent:
            return _ok(stdout='1\n')
        return _ok(stdout='0\n' if chkCalls['n'] == 1 else '1\n')

    runner.handlers.append((m0010.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME, chkProbe))


# ================================================================================
# ORM constants + CheckConstraint shape
# ================================================================================


class TestOrmCheckConstraint:
    def test_checkNameConstant(self) -> None:
        assert db_models.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME == 'chk_drive_id_source_id'

    def test_checkClauseMentionsBothBranches(self) -> None:
        clause = db_models.DRIVE_SUMMARY_DRIVE_ID_CHECK_CLAUSE
        assert 'drive_id IS NULL AND source_id IS NULL' in clause
        assert 'drive_id = source_id' in clause

    def test_driveSummaryCarriesNamedCheckConstraint(self) -> None:
        names = {c.name for c in DriveSummary.__table__.constraints}
        assert 'chk_drive_id_source_id' in names


# ================================================================================
# SQLite enforcement (the CHECK at the DB layer)
# ================================================================================


class TestCheckEnforcement:
    def test_bothNullRowAllowed(self, engine) -> None:
        # Legacy analytics path: no Pi origin, both columns NULL.
        with Session(engine) as session:
            session.add(DriveSummary(
                device_id="chi-eclipse-01",
                start_time=datetime(2026, 5, 1, 12, 0, 0),
                drive_id=None,
                source_id=None,
            ))
            session.commit()
            assert session.query(DriveSummary).count() == 1

    def test_equalValuesAllowed(self, engine) -> None:
        with Session(engine) as session:
            session.add(DriveSummary(
                source_device="chi-eclipse-01", source_id=5, drive_id=5,
            ))
            session.commit()
            assert session.query(DriveSummary).one().drive_id == 5

    def test_driveIdNullWithSourceIdSetRejected(self, engine) -> None:
        # The exact production smell -- now structurally impossible.
        with Session(engine) as session, pytest.raises(IntegrityError):
            session.add(DriveSummary(
                source_device="chi-eclipse-01", source_id=99, drive_id=None,
            ))
            session.commit()

    def test_divergentValuesRejected(self, engine) -> None:
        with Session(engine) as session, pytest.raises(IntegrityError):
            session.add(DriveSummary(
                source_device="chi-eclipse-01", source_id=2, drive_id=1,
            ))
            session.commit()


# ================================================================================
# Migration DDL shapes + exports
# ================================================================================


class TestMigrationDdl:
    def test_forwardBackfillShape(self) -> None:
        ddl = m0010.BACKFILL_DRIVE_SUMMARY_DRIVE_ID_FROM_SOURCE_DDL
        assert ddl.startswith('UPDATE drive_summary SET')
        assert 'drive_id = source_id' in ddl
        assert 'WHERE drive_id IS NULL AND source_id IS NOT NULL' in ddl

    def test_reverseBackfillShape(self) -> None:
        ddl = m0010.BACKFILL_DRIVE_SUMMARY_SOURCE_ID_FROM_DRIVE_DDL
        assert ddl.startswith('UPDATE drive_summary SET')
        assert 'source_id = drive_id' in ddl
        assert 'WHERE source_id IS NULL AND drive_id IS NOT NULL' in ddl

    def test_addCheckDdlShape(self) -> None:
        ddl = m0010.ADD_DRIVE_SUMMARY_DRIVE_ID_CHECK_DDL
        assert ddl.startswith('ALTER TABLE drive_summary ADD CONSTRAINT')
        assert m0010.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME in ddl
        assert 'CHECK' in ddl

    def test_constantsMatchOrm(self) -> None:
        assert (
            m0010.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME
            == db_models.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME
        )

    def test_ddlsInExports(self) -> None:
        for name in (
            'BACKFILL_DRIVE_SUMMARY_DRIVE_ID_FROM_SOURCE_DDL',
            'BACKFILL_DRIVE_SUMMARY_SOURCE_ID_FROM_DRIVE_DDL',
            'ADD_DRIVE_SUMMARY_DRIVE_ID_CHECK_DDL',
            'DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME',
        ):
            assert name in m0010.__all__, name


# ================================================================================
# Migration substep behaviour (hermetic FakeRunner)
# ================================================================================


class TestInvariantSubstep:
    def test_productionEmitsBackfillsBeforeAddConstraint(self) -> None:
        runner = FakeRunner()
        _scriptInvariantSubstep(runner, alreadyPresent=False)
        m0010._applyDriveSummaryDriveIdSourceIdInvariant(_ctx(runner))

        sqls = runner.emittedSqls
        forwardIdx = next(
            i for i, s in enumerate(sqls)
            if 'drive_id = source_id' in s and s.startswith('UPDATE')
        )
        reverseIdx = next(
            i for i, s in enumerate(sqls)
            if 'source_id = drive_id' in s and s.startswith('UPDATE')
        )
        addIdx = next(
            i for i, s in enumerate(sqls)
            if s.startswith('ALTER TABLE drive_summary ADD CONSTRAINT '
                            f'{m0010.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME}')
        )
        # UPDATE-before-ALTER (both directions before the constraint lands).
        assert forwardIdx < addIdx
        assert reverseIdx < addIdx

    def test_alreadyConstrainedIsNoOp(self) -> None:
        runner = FakeRunner()
        _scriptInvariantSubstep(runner, alreadyPresent=True)
        m0010._applyDriveSummaryDriveIdSourceIdInvariant(_ctx(runner))
        # No backfill UPDATEs and no ADD CONSTRAINT on an already-enforced DB.
        assert not [s for s in runner.emittedSqls if s.startswith('UPDATE drive_summary')]
        assert not [s for s in runner.emittedSqls if 'ADD CONSTRAINT' in s]

    def test_tableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_summary'):
            m0010._applyDriveSummaryDriveIdSourceIdInvariant(_ctx(runner))

    def test_postProbeMissingConstraintRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        # Constraint never appears (count stays 0) -> post-condition trips.
        runner.handlers.append((
            m0010.DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME,
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.SchemaProbeError, match='chk_drive_id_source_id'):
            m0010._applyDriveSummaryDriveIdSourceIdInvariant(_ctx(runner))

    def test_addConstraintFailureRaises(self) -> None:
        runner = FakeRunner()
        _scriptInvariantSubstep(runner, alreadyPresent=False)
        runner.handlers.insert(0, (
            'ADD CONSTRAINT chk_drive_id_source_id',
            lambda _sql: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='chk_drive_id_source_id'):
            m0010._applyDriveSummaryDriveIdSourceIdInvariant(_ctx(runner))

    def test_substepDocstringDocumentsUpdateBeforeAlter(self) -> None:
        doc = m0010._applyDriveSummaryDriveIdSourceIdInvariant.__doc__ or ''
        assert 'UPDATE' in doc and 'ALTER' in doc


# ================================================================================
# Writer-path discipline: invariant stays true going forward
# ================================================================================


class TestSyncWriterPath:
    def test_syncMirrorsSourceIdOntoDriveId(self, engine) -> None:
        # V-5: a Pi drive_summary row (id -> source_id) must land with
        # drive_id == source_id, else the new CHECK rejects the INSERT.
        with Session(engine) as session:
            runSyncUpsert(
                session,
                deviceId="chi-eclipse-01",
                batchId="b1",
                tables={"drive_summary": {"rows": [{
                    "id": 7,
                    "drive_start_timestamp": "2026-05-01T12:00:00Z",
                    "ambient_temp_at_start_c": 18.5,
                    "starting_battery_v": 12.4,
                    "barometric_kpa_at_start": 101.2,
                    "data_source": "real",
                }]}},
                syncHistoryId=1,
            )
            row = session.query(DriveSummary).one()
            assert row.source_id == 7
            assert row.drive_id == 7


class TestComputeWriterPath:
    def test_computePreservesInvariant(self, engine) -> None:
        # V-4: a valid Pi-sync row through compute keeps drive_id == source_id.
        with Session(engine) as session:
            session.add(DriveSummary(
                source_device="chi-eclipse-01", source_id=11, drive_id=11,
                data_source="real",
            ))
            session.commit()
            _seedRealtime(session, driveId=11)

            compute_drive_summary(session, 11)
            session.commit()

            row = session.query(DriveSummary).filter_by(source_id=11).one()
            assert row.drive_id == 11
            assert row.source_id == 11

    def test_computeHealsLegacyNullMirror(self, engine) -> None:
        # A pre-migration legacy row (source_id set, drive_id NULL) is seeded
        # with the CHECK disabled, then compute must heal the mirror so the
        # row satisfies the invariant.
        with engine.connect() as conn:
            conn.execute(text("PRAGMA ignore_check_constraints=ON"))
            conn.execute(text(
                "INSERT INTO drive_summary "
                "(source_device, source_id, drive_id, data_source) "
                "VALUES ('chi-eclipse-01', 11, NULL, 'real')"
            ))
            conn.commit()

        with Session(engine) as session:
            _seedRealtime(session, driveId=11)
            compute_drive_summary(session, 11)
            session.commit()

            row = session.query(DriveSummary).filter_by(source_id=11).one()
            assert row.drive_id == 11
