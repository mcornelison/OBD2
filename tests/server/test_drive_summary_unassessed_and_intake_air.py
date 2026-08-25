################################################################################
# File Name: test_drive_summary_unassessed_and_intake_air.py
# Purpose/Description: US-563 (F-134) gate -- a drive_summary row that has NOT
#                      been assessed must not read as assessed, and the IAT
#                      column must not claim to be ambient.  Covers the ORM /
#                      behavioural half of the story:
#                        * data_quality defaults to the NON-verdict
#                          'unassessed' (was: 'full', the BEST verdict)
#                        * is_real defaults to NULL (was: 0, which read as a
#                          computed "not real" verdict)
#                        * ambient_temp_at_start_c -> intake_air_temp_at_start_c
#                      The APPLIED-schema default guard is a SEPARATE file with
#                      its own acceptance line (Atlas, explicit):
#                      tests/server/test_applied_schema_column_defaults.py.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-563) | Initial -- Sprint 75 F-134 pending-vs-assessed.
# ================================================================================
################################################################################

"""US-563 / F-134 -- pending must not read as assessed; IAT is not ambient.

Why this exists
---------------

On 2026-08-20 a drive that had ended but had not yet reached the nightly 03:30
analytics batch read back as ``data_quality='full', is_real=0`` -- a confident
full-quality verdict on a drive nobody had assessed.  It misled **both** Spool
and Atlas into filing a phantom "roll-up regression" story.  The roll-up is a
nightly batch and it runs correctly; the defect is entirely in the schema:

* ``data_quality`` is a quality VERDICT column whose DEFAULT was the BEST
  verdict, so an untouched row was indistinguishable from a clean one.
* ``is_real`` defaulted to ``0``, which reads as "analytics ran and said this
  drive is not real" -- the exact false-confidence ``_deriveIsReal`` is careful
  to avoid (it returns ``None`` for unknown).  Atlas CONFIRMED the observed
  ``is_real=0`` was the schema default, **not** a compute result.  There is no
  compute defect; do not go looking for one.

Separately, ``ambient_temp_at_start_c`` is fed from IAT (PID 0x0F) and is
therefore MISLABELED.  Drive 41 logged 47 C / 117 F as "ambient" while the real
ambient was 24-27 C; IAT ran 48.1 -> 40.6 C by speed band, cooling with airflow,
and never came near ambient.  No ambient source exists on this vehicle, so
inventing one would be fabrication -- the column is renamed to what it actually
is.

What each layer pins
--------------------

* :class:`TestUnassessedIsNotAVerdict` -- a freshly-inserted Pi-shape row (the
  pending window) does NOT present a confident verdict.
* :class:`TestAssessedStillWritesItsVerdict` -- the batch still stamps 'full'
  on a clean drive, so 'unassessed' is a starting state and not a sticky one.
* :class:`TestIntakeAirNotAmbient` -- the column carries the honest name, the
  mislabeled name is GONE, and the Pi wire key still lands (deploy-window
  compatibility).
* :class:`TestConstantNamesDistinguishDefaultFromVerdict` -- STRUCTURAL.  The
  single ambiguous name ``DRIVE_SUMMARY_DATA_QUALITY_DEFAULT`` doing duty as
  both "the column default" and "the clean verdict" IS the defect; behaviour
  alone cannot pin its removal, because a constant re-pointed at 'unassessed'
  would pass every behavioural test here while leaving the compute path writing
  a value named "DEFAULT".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from src.server.api.sync import runSyncUpsert
from src.server.db import models
from src.server.db.models import (
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
    DATA_QUALITY_UNASSESSED,
    DRIVE_SUMMARY_ASSESSED_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_COLUMN_DEFAULT,
    DRIVE_SUMMARY_DATA_QUALITY_FULL,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
    Base,
    DriveSummary,
)

DEVICE_ID = 'chi-eclipse-01'

# The renamed column + the name it retires.  Both spelled once here so a future
# rename edits one place and every assertion below moves with it.
INTAKE_AIR_COLUMN = 'intake_air_temp_at_start_c'
RETIRED_AMBIENT_COLUMN = 'ambient_temp_at_start_c'


# ================================================================================
# Fixtures -- hermetic ORM-shaped SQLite, the project's standard server harness
# ================================================================================


@pytest.fixture
def session() -> Session:
    """ORM-created schema on in-memory SQLite (fresh-deploy reference shape)."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    sess = Session(engine)
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()


def _piShapeRow(driveId: int, *, ambientKey: str = INTAKE_AIR_COLUMN) -> dict:
    """The Pi-sync payload for one drive -- the row that lands in the pending window.

    The Pi sends drive-start metadata ONLY.  It has no source for the analytics
    columns (``row_count``, ``is_real``, ...) and never sends ``data_quality``.
    That omission is the whole point: those columns are what the nightly batch
    fills in, and until it runs they must not read as filled.
    """
    return {
        'id': driveId,
        'drive_start_timestamp': '2026-08-20T14:05:00Z',
        ambientKey: 47.0,
        'starting_battery_v': 12.7,
        'barometric_kpa_at_start': 99.0,
        'data_source': 'real',
    }


def _syncOneDrive(session: Session, driveId: int, **kwargs) -> DriveSummary:
    """Run the REAL sync upsert for one Pi drive row and return the landed row."""
    runSyncUpsert(
        session,
        deviceId=DEVICE_ID,
        batchId=f'batch-{driveId}',
        tables={'drive_summary': {'rows': [_piShapeRow(driveId, **kwargs)]}},
        syncHistoryId=1,
    )
    session.commit()
    row = session.query(DriveSummary).filter_by(
        source_device=DEVICE_ID, source_id=driveId,
    ).one()
    session.refresh(row)
    return row


# ================================================================================
# AC-1 / AC-2 / AC-3 -- the pending window must not present a verdict
# ================================================================================


class TestUnassessedIsNotAVerdict:
    """A drive that has ended but not been assessed reads as unassessed.

    This is the 2026-08-20 failure reproduced: read a drive_summary row between
    the drive ending and the 03:30 batch and it claimed ``data_quality='full',
    is_real=0``.
    """

    def test_pendingRow_dataQualityIsNotAnAssessedVerdict(
        self, session: Session,
    ) -> None:
        """The exact misleading read: a pending row must not say 'full'.

        Asserted against the ASSESSED set rather than against the literal
        'full', so re-defaulting the column to 'attribution_anomaly' (or any
        other verdict) fails here too.  A default that is *any* verdict is the
        defect; 'full' is merely the one that shipped.
        """
        row = _syncOneDrive(session, driveId=41)
        assert row.data_quality not in DRIVE_SUMMARY_ASSESSED_DATA_QUALITY_VALUES, (
            f'a drive that has not been assessed reads as '
            f'{row.data_quality!r} -- an assessed verdict.  This is the '
            f'2026-08-20 read that produced a phantom regression story.'
        )

    def test_pendingRow_dataQualityIsUnassessed(self, session: Session) -> None:
        # Positive half: not merely "not full" -- it says what it actually is,
        # so unassessed is DISTINGUISHABLE from assessed-good rather than just
        # absent (validationCriteria #3).
        row = _syncOneDrive(session, driveId=41)
        assert row.data_quality == DATA_QUALITY_UNASSESSED

    def test_pendingRow_isRealIsNullNotZero(self, session: Session) -> None:
        """``is_real`` must be NULL, never 0, before analytics runs.

        0 is a COMPUTED verdict ("tested, and this drive is not real").  NULL is
        "nobody has looked".  analysis.py already documents that distinction as
        load-bearing for Spool's grading queries -- the schema default was
        quietly overriding it on every Pi-sync row.
        """
        row = _syncOneDrive(session, driveId=41)
        assert row.is_real is None, (
            f'is_real={row.is_real!r} on an unassessed drive.  Atlas CONFIRMED '
            f'2026-08-20 this was the SCHEMA DEFAULT, not a compute result.'
        )

    def test_unassessedIsNotItselfInTheAssessedSet(self) -> None:
        # Guards the trivially-green failure mode: adding 'unassessed' to the
        # ASSESSED tuple would make every assertion above pass vacuously.
        assert DATA_QUALITY_UNASSESSED not in DRIVE_SUMMARY_ASSESSED_DATA_QUALITY_VALUES
        assert DATA_QUALITY_UNASSESSED in DRIVE_SUMMARY_DATA_QUALITY_VALUES

    def test_unassessedIsPermittedByTheDbLevelCheckConstraint(
        self, session: Session,
    ) -> None:
        # The enum is enforced by a CHECK on both SQLite and MariaDB.  If the
        # value were not added to the CHECK, the new default would make EVERY
        # Pi-sync INSERT fail -- a far louder bug, but pin it anyway so the
        # widen cannot be dropped from the migration.
        session.add(DriveSummary(
            source_device=DEVICE_ID, source_id=900, drive_id=900,
            data_quality=DATA_QUALITY_UNASSESSED,
        ))
        session.commit()

    def test_unassessedFitsTheColumnWidth(self) -> None:
        # US-377's lesson: SQLite never enforces VARCHAR width, so a too-long
        # value passes every bench test and raises DataError 1406 on MariaDB.
        assert len(DATA_QUALITY_UNASSESSED) <= models.DATA_QUALITY_COLUMN_LENGTH


# ================================================================================
# The counter-direction -- assessment still writes its verdict
# ================================================================================


class TestAssessedStillWritesItsVerdict:
    """'unassessed' is a STARTING state, not a sticky one.

    Without this direction the whole story is satisfiable by a column that never
    says anything -- honest, and useless.  Both directions or neither.
    """

    def test_computePathWritesFullOnACleanDrive(self, session: Session) -> None:
        row = _syncOneDrive(session, driveId=41)
        # Stand in for the nightly batch's write -- the verdict vocabulary is
        # unchanged by this story, only the pre-assessment state is.
        row.data_quality = DRIVE_SUMMARY_DATA_QUALITY_FULL
        row.is_real = True
        session.commit()
        session.refresh(row)
        assert row.data_quality == DRIVE_SUMMARY_DATA_QUALITY_FULL
        assert row.is_real is True

    def test_anomalyVerdictStillPermitted(self, session: Session) -> None:
        row = _syncOneDrive(session, driveId=42)
        row.data_quality = DATA_QUALITY_ATTRIBUTION_ANOMALY
        session.commit()
        session.refresh(row)
        assert row.data_quality == DATA_QUALITY_ATTRIBUTION_ANOMALY

    def test_explicitDataQualityOnInsertIsNotOverriddenByTheDefault(
        self, session: Session,
    ) -> None:
        # A default only applies when the column is OMITTED.  Pinned so a future
        # "always stamp unassessed on insert" implementation (which WOULD be a
        # regression -- it would erase an analytics-written value on re-sync)
        # goes red here.
        session.add(DriveSummary(
            source_device=DEVICE_ID, source_id=901, drive_id=901,
            data_quality=DRIVE_SUMMARY_DATA_QUALITY_FULL,
        ))
        session.commit()
        row = session.query(DriveSummary).filter_by(source_id=901).one()
        assert row.data_quality == DRIVE_SUMMARY_DATA_QUALITY_FULL


# ================================================================================
# AC-5 / AC-6 -- IAT is not ambient
# ================================================================================


class TestIntakeAirNotAmbient:
    """The column is named for what it measures: intake air, not ambient."""

    def test_ormDeclaresTheIntakeAirColumn(self) -> None:
        assert INTAKE_AIR_COLUMN in DriveSummary.__table__.columns

    def test_ormNoLongerDeclaresTheMislabeledAmbientColumn(self) -> None:
        """The mislabeled name is GONE, not aliased alongside the new one.

        Two live spellings of one fact is how the mislabel survives a rename:
        every consumer that was wrong stays wrong and nothing goes red.
        """
        assert RETIRED_AMBIENT_COLUMN not in DriveSummary.__table__.columns

    def test_appliedSqliteSchemaCarriesTheRenamedColumn(
        self, session: Session,
    ) -> None:
        # Asserted through the real created schema, not only the ORM object --
        # the ORM mapping and the emitted DDL are two different things.
        cols = {c['name'] for c in inspect(session.bind).get_columns('drive_summary')}
        assert INTAKE_AIR_COLUMN in cols
        assert RETIRED_AMBIENT_COLUMN not in cols

    def test_piWireKeyStillLandsInTheRenamedColumn(self, session: Session) -> None:
        """A Pi that still sends the OLD key must not silently drop its reading.

        Deploy is lockstep, but the Pi's own queue can hold rows captured before
        the deploy.  The sync registry's rename seam maps the legacy wire key
        onto the honest column -- landing what was read (SSOT rule A), rather
        than discarding it because the label changed.
        """
        row = _syncOneDrive(session, driveId=43, ambientKey=RETIRED_AMBIENT_COLUMN)
        assert getattr(row, INTAKE_AIR_COLUMN) == pytest.approx(47.0)

    def test_newPiWireKeyAlsoLands(self, session: Session) -> None:
        # The rename seam must not break the post-deploy Pi, which sends the new
        # key.  Both keys land in one column; neither is dropped.
        row = _syncOneDrive(session, driveId=44, ambientKey=INTAKE_AIR_COLUMN)
        assert getattr(row, INTAKE_AIR_COLUMN) == pytest.approx(47.0)

    def test_noSurfaceRendersThisColumnAsAmbient(self) -> None:
        """AC-6: any surface reading the column shows INTAKE AIR, not AMBIENT.

        Measured, not assumed: no dashboard / report surface reads this column
        today (the carousel's AMBIENT tile is the TSL2591 light feed, an
        unrelated fact).  This pins that a surface cannot start reading the
        renamed column back under the retired label -- the way the mislabel
        would return.
        """
        repoRoot = Path(__file__).resolve().parents[2]
        surfaces = [
            repoRoot / 'src' / 'pi' / 'ui' / 'dashboard' / 'carousel.js',
            repoRoot / 'src' / 'server' / 'reports' / 'drive_report.py',
        ]
        for surface in surfaces:
            if not surface.exists():
                continue
            text_ = surface.read_text(encoding='utf-8')
            assert RETIRED_AMBIENT_COLUMN not in text_, (
                f'{surface.name} references the retired {RETIRED_AMBIENT_COLUMN!r}'
            )


# ================================================================================
# STRUCTURAL -- the ambiguous constant name IS the defect
# ================================================================================


class TestConstantNamesDistinguishDefaultFromVerdict:
    """One name cannot mean both "the column default" and "the clean verdict".

    Behaviour cannot pin this: a constant re-pointed at 'unassessed' passes every
    behavioural test in this file while the compute path still writes something
    called ``..._DEFAULT`` as its verdict.  The conflation is what made the
    schema-level defect unsayable in code, so it is asserted on the SHAPE.
    """

    def test_theAmbiguousNameIsRetired(self) -> None:
        assert not hasattr(models, 'DRIVE_SUMMARY_DATA_QUALITY_DEFAULT'), (
            'DRIVE_SUMMARY_DATA_QUALITY_DEFAULT served as BOTH the column '
            'default and the clean verdict.  Splitting the two is the '
            'deliverable; a surviving alias re-opens the conflation.'
        )

    def test_theColumnDefaultIsTheNonVerdict(self) -> None:
        assert DRIVE_SUMMARY_DATA_QUALITY_COLUMN_DEFAULT == DATA_QUALITY_UNASSESSED

    def test_theCleanVerdictIsStillFull(self) -> None:
        # The verdict vocabulary is UNCHANGED -- this story does not re-label
        # assessed drives, and every historical 'full' row keeps its meaning.
        assert DRIVE_SUMMARY_DATA_QUALITY_FULL == 'full'

    def test_ormServerDefaultIsTheNonVerdict(self) -> None:
        # Read the mapped column's server_default rather than re-inserting a
        # row: this is the value that becomes the DDL DEFAULT clause.
        col = DriveSummary.__table__.columns['data_quality']
        assert col.server_default is not None
        rendered = str(col.server_default.arg)
        assert DATA_QUALITY_UNASSESSED in rendered

    def test_ormIsRealHasNoServerDefault(self) -> None:
        # DEFAULT NULL is spelled as "no server_default" in SQLAlchemy; a
        # server_default of any kind here re-creates the false-verdict.
        assert DriveSummary.__table__.columns['is_real'].server_default is None

    def test_computePathWritesTheVerdictConstantNotTheDefaultConstant(self) -> None:
        """The clean-drive branch must name the VERDICT, not the DEFAULT.

        Source-level because the two constants hold different strings now: a
        compute path still reaching for the column default would stamp
        'unassessed' onto an ASSESSED clean drive -- silently converting the
        whole story into a permanent "nothing was ever assessed".
        """
        computeSrc = (
            Path(__file__).resolve().parents[2]
            / 'src' / 'server' / 'analytics' / 'drive_summary_compute.py'
        ).read_text(encoding='utf-8')
        assert 'DRIVE_SUMMARY_DATA_QUALITY_FULL' in computeSrc
        assert 'DRIVE_SUMMARY_DATA_QUALITY_COLUMN_DEFAULT' not in computeSrc


def test_sqliteAppliedDefaultMatchesTheOrm() -> None:
    """The emitted DDL carries the non-verdict DEFAULT.

    ``create_all`` is the fresh-deploy path; the MIGRATION path (existing prod
    rows) is gated separately by v0024's tests + the applied-schema guard.  Both
    must agree, which is what this asserts on the SQLite side.
    """
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        ddl = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='drive_summary'",
        )).scalar_one()
    assert f"DEFAULT '{DATA_QUALITY_UNASSESSED}'" in ddl
    assert INTAKE_AIR_COLUMN in ddl
    assert RETIRED_AMBIENT_COLUMN not in ddl
