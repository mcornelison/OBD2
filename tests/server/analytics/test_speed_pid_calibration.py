################################################################################
# File Name: test_speed_pid_calibration.py
# Purpose/Description: Sprint 43 V0.28.0 (US-370 / F-076) -- tests for the
#                      speed_pid_calibration ORM surface + the writer-path guard
#                      and analytics provenance-prefix gate in
#                      src/server/analytics/speed_pid_calibration.py.  The table
#                      is the SSOT for per-ECU multiplicative SPEED-PID correction
#                      (new modified-EPROM ECU reads ~2x actual ground speed).
#                      Per Atlas option-(c) ruling 2026-05-29: ecu_signature is a
#                      UNIQUE natural key (no FK to vehicle_info -- the factor is
#                      window-invariant).  Hermetic: real in-memory SQLite + real
#                      ORM + real INSERTs (post-I-040 no-seam-mocks discipline).
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
# ================================================================================
################################################################################

"""US-370 / F-076 tests for the speed_pid_calibration surface."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import String, Text, create_engine, inspect  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.speed_pid_calibration import (  # noqa: E402
    insert_speed_pid_calibration,
    select_empirical_calibrations,
)
from src.server.db.models import (  # noqa: E402
    SPEED_PID_CALIBRATION_ECU_SIGNATURE_LENGTH,
    SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
    Base,
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


# =========================================================================
# ORM shape
# =========================================================================


class TestSpeedPidCalibrationOrm:
    def test_tableName(self) -> None:
        assert SpeedPidCalibration.__tablename__ == "speed_pid_calibration"

    def test_hasExpectedColumns(self) -> None:
        cols = {c.name for c in SpeedPidCalibration.__table__.columns}
        for expected in (
            "id",
            "ecu_signature",
            "correction_factor",
            "capture_method",
            "captured_at_timestamp_utc",
            "captured_by",
            "provenance",
            "notes",
        ):
            assert expected in cols, f"missing column {expected!r}"

    def test_ecuSignatureIsVarchar32NotNull(self) -> None:
        col = SpeedPidCalibration.__table__.columns["ecu_signature"]
        assert isinstance(col.type, String)
        assert col.type.length == SPEED_PID_CALIBRATION_ECU_SIGNATURE_LENGTH == 32
        assert col.nullable is False

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

    def test_ecuSignatureHasUniqueConstraint(self) -> None:
        uniques = inspect(SpeedPidCalibration).local_table.constraints
        unique_cols = {
            tuple(c.name for c in con.columns)
            for con in uniques
            if con.__class__.__name__ == "UniqueConstraint"
        }
        assert ("ecu_signature",) in unique_cols


# =========================================================================
# DB-level invariants (VC#7 NOT NULL + UNIQUE natural key)
# =========================================================================


class TestSpeedPidCalibrationDbInvariants:
    def test_provenanceNotNullEnforced(self, session: Session) -> None:
        """VC#7: a row without provenance is rejected at the DB layer."""
        session.add(
            SpeedPidCalibration(
                ecu_signature="MD000001",
                correction_factor=1.0,
                provenance=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_ecuSignatureUniqueEnforced(self, session: Session) -> None:
        """option-(c): ecu_signature is a UNIQUE natural key (no duplicates)."""
        session.add(
            SpeedPidCalibration(
                ecu_signature="MD000002",
                correction_factor=1.0,
                provenance="empirical-test",
            )
        )
        session.flush()
        session.add(
            SpeedPidCalibration(
                ecu_signature="MD000002",
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
        insert_speed_pid_calibration(
            session,
            ecu_signature="MD123456",
            correction_factor=0.5,
            provenance="empirical-gps-2026-06-01",
            capture_method="gps_correlation",
            notes="GPS-correlated.",
        )
        session.flush()
        row = session.query(SpeedPidCalibration).filter_by(
            ecu_signature="MD123456",
        ).one()
        assert row.correction_factor == 0.5
        assert row.provenance == "empirical-gps-2026-06-01"

    def test_emptyProvenanceRaises(self, session: Session) -> None:
        """VC#8: provenance='' is forbidden by writer-path discipline."""
        with pytest.raises(ValueError, match="provenance"):
            insert_speed_pid_calibration(
                session,
                ecu_signature="MD123457",
                correction_factor=1.0,
                provenance="",
            )

    def test_whitespaceProvenanceRaises(self, session: Session) -> None:
        with pytest.raises(ValueError, match="provenance"):
            insert_speed_pid_calibration(
                session,
                ecu_signature="MD123458",
                correction_factor=1.0,
                provenance="   ",
            )

    def test_emptyEcuSignatureRaises(self, session: Session) -> None:
        with pytest.raises(ValueError, match="ecu_signature"):
            insert_speed_pid_calibration(
                session,
                ecu_signature="  ",
                correction_factor=1.0,
                provenance="empirical-x",
            )


# =========================================================================
# Analytics provenance-prefix gate (VC#9)
# =========================================================================


class TestEmpiricalProvenanceGate:
    def test_prefixGateExcludesRoughSeedRows(self, session: Session) -> None:
        """VC#9: only 'empirical-' provenance rows are returned; rough seeds out."""
        insert_speed_pid_calibration(
            session,
            ecu_signature="MD346675",
            correction_factor=1.0,
            provenance="gear-math-drive-18-3rd-gear-fit",
        )
        insert_speed_pid_calibration(
            session,
            ecu_signature="MD335287",
            correction_factor=0.5,
            provenance="rough-seed-drive-26-gear-math",
        )
        insert_speed_pid_calibration(
            session,
            ecu_signature="MD999999",
            correction_factor=0.97,
            provenance="empirical-gps-correlation-2026-06-15",
        )
        session.flush()

        rows = select_empirical_calibrations(session)
        sigs = {r.ecu_signature for r in rows}
        assert sigs == {"MD999999"}
        for r in rows:
            assert r.provenance.startswith(
                SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
            )

    def test_prefixGateEmptyWhenNoEmpiricalRows(self, session: Session) -> None:
        insert_speed_pid_calibration(
            session,
            ecu_signature="MD346675",
            correction_factor=1.0,
            provenance="gear-math-drive-18-3rd-gear-fit",
        )
        session.flush()
        assert select_empirical_calibrations(session) == []
