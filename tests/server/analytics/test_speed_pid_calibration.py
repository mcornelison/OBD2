################################################################################
# File Name: test_speed_pid_calibration.py
# Purpose/Description: Sprint 44 V0.28.1 (US-374 / F-076) -- tests for the
#                      speed_pid_calibration ORM surface + the writer-path guard
#                      and analytics provenance-prefix gate in
#                      src/server/analytics/speed_pid_calibration.py.  US-374
#                      re-keys the table FORWARD from the v0010 option-(c)
#                      ``ecu_signature`` natural key to an ``ecu_id`` FK -> ecu.id
#                      (SSOT ecu identity; a reflash gets its own calibration row).
#                      Hermetic: real in-memory SQLite + real ORM + real INSERTs
#                      (post-I-040 no-seam-mocks discipline).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-29    | Rex (US-370) | Initial -- F-076 speed_pid_calibration ORM shape,
#               |              | UNIQUE natural key, provenance NOT NULL (VC#7),
#               |              | writer-path empty-provenance guard (VC#8), and
#               |              | analytics empirical-provenance-prefix gate (VC#9).
# 2026-06-01    | Rex (US-374) | Re-key FORWARD: ecu_signature natural key ->
#               |              | ecu_id FK -> ecu.id + UNIQUE(ecu_id) + relationship;
#               |              | writer takes ecu_id; gate works over the FK shape.
# ================================================================================
################################################################################

"""US-374 / F-076 tests for the re-keyed speed_pid_calibration surface."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import Integer, Text, create_engine, inspect  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.speed_pid_calibration import (  # noqa: E402
    insert_speed_pid_calibration,
    select_empirical_calibrations,
)
from src.server.db.models import (  # noqa: E402
    SPEED_PID_CALIBRATION_ECU_FK_NAME,
    SPEED_PID_CALIBRATION_ECU_ID_UNIQUE,
    SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
    Base,
    Ecu,
    SpeedPidCalibration,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """Temp-file SQLite engine carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def session(engine):
    with Session(engine) as sess:
        yield sess


def _seedEcu(session: Session, ecu_signature: str, cal_signature: str) -> Ecu:
    """Insert + flush a single ecu identity row and return it (FK target)."""
    row = Ecu(ecu_signature=ecu_signature, cal_signature=cal_signature)
    session.add(row)
    session.flush()
    return row


# =========================================================================
# ORM shape (re-keyed to ecu_id FK)
# =========================================================================


class TestSpeedPidCalibrationOrm:
    def test_tableName(self) -> None:
        assert SpeedPidCalibration.__tablename__ == "speed_pid_calibration"

    def test_hasExpectedColumns(self) -> None:
        cols = {c.name for c in SpeedPidCalibration.__table__.columns}
        for expected in (
            "id",
            "ecu_id",
            "correction_factor",
            "capture_method",
            "captured_at_timestamp_utc",
            "captured_by",
            "provenance",
            "notes",
        ):
            assert expected in cols, f"missing column {expected!r}"

    def test_ecuSignatureColumnRemoved(self) -> None:
        """Re-key: the transitional ecu_signature natural key is gone."""
        cols = {c.name for c in SpeedPidCalibration.__table__.columns}
        assert "ecu_signature" not in cols

    def test_ecuIdIsIntegerFkNotNull(self) -> None:
        col = SpeedPidCalibration.__table__.columns["ecu_id"]
        assert isinstance(col.type, Integer)
        assert col.nullable is False
        fk = next(iter(col.foreign_keys))
        assert fk.column.table.name == "ecu"
        assert fk.column.name == "id"

    def test_correctionFactorNotNull(self) -> None:
        col = SpeedPidCalibration.__table__.columns["correction_factor"]
        assert col.nullable is False

    def test_provenanceIsTextNotNull(self) -> None:
        col = SpeedPidCalibration.__table__.columns["provenance"]
        assert isinstance(col.type, Text)
        assert col.nullable is False

    def test_optionalColumnsAreNullable(self) -> None:
        table = SpeedPidCalibration.__table__
        for name in ("capture_method", "captured_at_timestamp_utc",
                     "captured_by", "notes"):
            assert table.columns[name].nullable is True, f"{name} should be nullable"

    def test_ecuIdHasUniqueConstraint(self) -> None:
        uniques = inspect(SpeedPidCalibration).local_table.constraints
        unique_cols = {
            tuple(c.name for c in con.columns)
            for con in uniques
            if con.__class__.__name__ == "UniqueConstraint"
        }
        assert ("ecu_id",) in unique_cols
        # ecu_signature is no longer a key on this table.
        assert ("ecu_signature",) not in unique_cols

    def test_uniqueConstraintNameMatchesSsot(self) -> None:
        names = {
            con.name
            for con in inspect(SpeedPidCalibration).local_table.constraints
            if con.__class__.__name__ == "UniqueConstraint"
        }
        assert SPEED_PID_CALIBRATION_ECU_ID_UNIQUE in names

    def test_fkConstraintNameMatchesSsot(self) -> None:
        col = SpeedPidCalibration.__table__.columns["ecu_id"]
        fk = next(iter(col.foreign_keys))
        assert fk.constraint.name == SPEED_PID_CALIBRATION_ECU_FK_NAME

    def test_hasEcuRelationship(self) -> None:
        rels = inspect(SpeedPidCalibration).relationships
        assert "ecu" in rels
        assert rels["ecu"].mapper.class_ is Ecu


# =========================================================================
# DB-level invariants (VC#7 NOT NULL + UNIQUE ecu_id FK)
# =========================================================================


class TestSpeedPidCalibrationDbInvariants:
    def test_provenanceNotNullEnforced(self, session: Session) -> None:
        """VC#7: a row without provenance is rejected at the DB layer."""
        ecu = _seedEcu(session, "MD000001", "CAL01")
        session.add(
            SpeedPidCalibration(
                ecu_id=ecu.id,
                correction_factor=1.0,
                provenance=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_ecuIdUniqueEnforced(self, session: Session) -> None:
        """Re-key: ecu_id is a UNIQUE FK -- one calibration row per ecu identity."""
        ecu = _seedEcu(session, "MD000002", "CAL02")
        session.add(
            SpeedPidCalibration(
                ecu_id=ecu.id,
                correction_factor=1.0,
                provenance="empirical-test",
            )
        )
        session.flush()
        session.add(
            SpeedPidCalibration(
                ecu_id=ecu.id,
                correction_factor=0.5,
                provenance="empirical-test-2",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


# =========================================================================
# Writer-path guard (VC#8: empty-string provenance forbidden)
# =========================================================================


class TestInsertWriterGuard:
    def test_validInsertPersistsRow(self, session: Session) -> None:
        ecu = _seedEcu(session, "MD123456", "CAL56")
        insert_speed_pid_calibration(
            session,
            ecu_id=ecu.id,
            correction_factor=0.5,
            provenance="empirical-gps-2026-06-01",
            capture_method="gps_correlation",
            notes="GPS-correlated.",
        )
        session.flush()
        row = session.query(SpeedPidCalibration).filter_by(ecu_id=ecu.id).one()
        assert row.correction_factor == 0.5
        assert row.provenance == "empirical-gps-2026-06-01"
        assert row.ecu.ecu_signature == "MD123456"

    def test_emptyProvenanceRaises(self, session: Session) -> None:
        """VC#8: provenance='' is forbidden by writer-path discipline."""
        ecu = _seedEcu(session, "MD123457", "CAL57")
        with pytest.raises(ValueError, match="provenance"):
            insert_speed_pid_calibration(
                session,
                ecu_id=ecu.id,
                correction_factor=1.0,
                provenance="",
            )

    def test_whitespaceProvenanceRaises(self, session: Session) -> None:
        ecu = _seedEcu(session, "MD123458", "CAL58")
        with pytest.raises(ValueError, match="provenance"):
            insert_speed_pid_calibration(
                session,
                ecu_id=ecu.id,
                correction_factor=1.0,
                provenance="   ",
            )


# =========================================================================
# Analytics provenance-prefix gate (VC#6 -- works over the FK shape)
# =========================================================================


class TestEmpiricalProvenanceGate:
    def test_prefixGateExcludesRoughSeedRows(self, session: Session) -> None:
        """VC#6: only 'empirical-' provenance rows are returned; rough seeds out."""
        prior = _seedEcu(session, "MD346675", "6675")
        new = _seedEcu(session, "MD326328", "UNKCAL")
        gps = _seedEcu(session, "MD999999", "CAL99")
        insert_speed_pid_calibration(
            session,
            ecu_id=prior.id,
            correction_factor=1.0,
            provenance="empirical-Drive-18-gear-math-fit",
        )
        insert_speed_pid_calibration(
            session,
            ecu_id=new.id,
            correction_factor=0.5,
            provenance="gear-math-sanity-check-Drive-26-CIO-corrected",
        )
        insert_speed_pid_calibration(
            session,
            ecu_id=gps.id,
            correction_factor=0.97,
            provenance="empirical-gps-correlation-2026-06-15",
        )
        session.flush()

        rows = select_empirical_calibrations(session)
        sigs = {r.ecu.ecu_signature for r in rows}
        assert sigs == {"MD346675", "MD999999"}
        for r in rows:
            assert r.provenance.startswith(
                SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
            )

    def test_prefixGateEmptyWhenNoEmpiricalRows(self, session: Session) -> None:
        new = _seedEcu(session, "MD326328", "UNKCAL")
        insert_speed_pid_calibration(
            session,
            ecu_id=new.id,
            correction_factor=0.5,
            provenance="gear-math-sanity-check-Drive-26-CIO-corrected",
        )
        session.flush()
        assert select_empirical_calibrations(session) == []
