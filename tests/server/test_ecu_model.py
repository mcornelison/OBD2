################################################################################
# File Name: test_ecu_model.py
# Purpose/Description: Sprint 44 V0.28.1 (US-376 / B-076 first slice) -- ORM-shape
#                      + transitional-coherence tests for the normalized,
#                      immutable ``ecu`` identity dimension and the
#                      ``vehicle_info.ecu_id`` FK that references it.  The ecu
#                      table is pair-keyed on (ecu_signature, cal_signature) so a
#                      reflash is its own identity row; vehicle_info keeps its
#                      transitional TEXT signature columns but they must stay in
#                      lockstep with the joined ecu row (zero-drift guard).  Real
#                      in-memory SQLite + real ORM, no mocks.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-376) | Initial -- ecu identity model + vehicle_info.
#               |              | ecu_id FK + transitional-coherence guard tests.
# ================================================================================
################################################################################

"""US-376 / B-076: ecu identity dimension + vehicle_info.ecu_id coherence."""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import (  # noqa: E402
    ECU_PAIR_UNIQUE,
    ECU_SIGNATURE_LENGTH,
    ECU_TABLE,
    Base,
    Ecu,
    VehicleInfo,
)
from src.server.db.vehicle_info_coherence import (  # noqa: E402
    findEcuCoherenceViolations,
)

_INSTALL = datetime(2026, 5, 22, 14, 0, 0)


def _columns(model) -> dict:
    return {c.name: c for c in model.__table__.columns}


# ================================================================================
# ecu table shape
# ================================================================================


class TestEcuModelShape:
    def test_tableName(self) -> None:
        assert Ecu.__tablename__ == ECU_TABLE == "ecu"

    def test_hasOnlyIdentityColumns(self) -> None:
        cols = set(_columns(Ecu))
        assert cols == {"id", "ecu_signature", "cal_signature"}, (
            "ecu is a pure identity dimension -- no lineage/timestamp columns"
        )

    def test_signatureColumnsAreVarchar32NotNull(self) -> None:
        cols = _columns(Ecu)
        for name in ("ecu_signature", "cal_signature"):
            assert cols[name].nullable is False, f"{name} must be NOT NULL"
            assert cols[name].type.length == ECU_SIGNATURE_LENGTH == 32

    def test_pairUniqueConstraintPresent(self) -> None:
        names = {
            c.name
            for c in Ecu.__table__.constraints
            if c.name is not None
        }
        assert ECU_PAIR_UNIQUE == "uq_ecu_signature_cal_signature"
        assert ECU_PAIR_UNIQUE in names

    def test_immutabilityCarveOutInTableComment(self) -> None:
        comment = (Ecu.__table__.comment or "").lower()
        assert "immutable" in comment
        # The sanctioned UNKCAL -> real-CALID same-row resolution carve-out.
        assert "unkcal" in comment
        assert "reflash" in comment


# ================================================================================
# vehicle_info.ecu_id FK
# ================================================================================


class TestVehicleInfoEcuIdFk:
    def test_ecuIdColumnPresentAndNotNull(self) -> None:
        cols = _columns(VehicleInfo)
        assert "ecu_id" in cols, "vehicle_info must carry the ecu_id FK"
        assert cols["ecu_id"].nullable is False, "ecu_id is NOT NULL post-v0011"

    def test_ecuIdForeignKeyTargetsEcuId(self) -> None:
        fk = next(iter(_columns(VehicleInfo)["ecu_id"].foreign_keys))
        assert fk.column.table.name == "ecu"
        assert fk.column.name == "id"

    def test_transitionalTextColumnsKept(self) -> None:
        cols = _columns(VehicleInfo)
        assert "ecu_signature" in cols
        assert "cal_signature" in cols


# ================================================================================
# Transitional-coherence guard (zero drift between text columns + ecu row)
# ================================================================================


class TestVehicleInfoEcuCoherence:
    def _engine(self):
        eng = create_engine("sqlite://")
        Base.metadata.create_all(eng)
        return eng

    def test_coherentRowsHaveNoViolations(self) -> None:
        eng = self._engine()
        with Session(eng) as session:
            ecu = Ecu(ecu_signature="MD346675", cal_signature="6675")
            session.add(ecu)
            session.flush()
            session.add(
                VehicleInfo(
                    source_id=1,
                    source_device="chi-eclipse-01",
                    ecu_id=ecu.id,
                    ecu_signature="MD346675",
                    cal_signature="6675",
                    ecu_install_timestamp_utc=_INSTALL,
                    ecu_removal_timestamp_utc=None,
                )
            )
            session.commit()
            assert findEcuCoherenceViolations(session) == []

    def test_driftedSignatureIsAViolation(self) -> None:
        eng = self._engine()
        with Session(eng) as session:
            ecu = Ecu(ecu_signature="MD346675", cal_signature="6675")
            session.add(ecu)
            session.flush()
            session.add(
                VehicleInfo(
                    source_id=1,
                    source_device="chi-eclipse-01",
                    ecu_id=ecu.id,
                    # ecu_signature drifted from the joined ecu row.
                    ecu_signature="WRONG-SIG",
                    cal_signature="6675",
                    ecu_install_timestamp_utc=_INSTALL,
                    ecu_removal_timestamp_utc=None,
                )
            )
            session.commit()
            violations = findEcuCoherenceViolations(session)
            assert len(violations) == 1
            assert violations[0]["ecu_signature"] == "WRONG-SIG"

    def test_driftedCalSignatureIsAViolation(self) -> None:
        eng = self._engine()
        with Session(eng) as session:
            ecu = Ecu(ecu_signature="MD335287", cal_signature="UNKCAL")
            session.add(ecu)
            session.flush()
            session.add(
                VehicleInfo(
                    source_id=1,
                    source_device="chi-eclipse-01",
                    ecu_id=ecu.id,
                    ecu_signature="MD335287",
                    cal_signature="DRIFTED-CAL",
                    ecu_install_timestamp_utc=_INSTALL,
                    ecu_removal_timestamp_utc=None,
                )
            )
            session.commit()
            assert len(findEcuCoherenceViolations(session)) == 1
