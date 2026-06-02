################################################################################
# File Name: test_dtc_freeze_frame_model.py
# Purpose/Description: Sprint 43 V0.28.0 (US-368 / F-109) -- ORM shape tests for
#                      the server-side dtc_freeze_frame table.  Validates the
#                      columns enumerated in US-368 AC#1 (id PK; dtc_log_id FK ->
#                      dtc_log.id; captured_at_timestamp_utc; pid_responses_json
#                      JSON; vehicle_info_id FK -> vehicle_info.id), the JSON
#                      round-trip, the FK targets, and the vehicle_info append-only
#                      table comment (AC#2 / V-4).  Real in-memory SQLite + real
#                      ORM, no mocks (post-I-040 discipline).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 dtc_freeze_frame ORM shape +
#               |              | JSON round-trip + vehicle_info append-only
#               |              | table-comment lock.
# ================================================================================
################################################################################

"""US-368 / F-109 ORM-shape tests for ``dtc_freeze_frame``.

A Mode 02 freeze-frame is the 16-PID snapshot of "what the engine was doing"
when a DTC tripped.  The server table carries the synced Pi capture: the 16-PID
JSON payload, the capture timestamp, an FK to the DTC it belongs to, and an FK
to the ``vehicle_info`` row (the ECU active at capture time -- resolved by the
server writer-path, see ``insertDtcFreezeFrame``).  Append-only invariant on
``vehicle_info`` keeps the FK honest: an identity column is never UPDATEd in
place (corrections go through ``stamp_ecu_swap`` close+open).
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import (  # noqa: E402
    Base,
    DtcFreezeFrame,
    DtcLog,
    VehicleInfo,
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


_INSTALL = datetime(2026, 5, 22, 14, 0, 0)
_CAPTURE = datetime(2026, 5, 23, 9, 30, 0)


def _activeVehicle(session: Session) -> VehicleInfo:
    """Insert + return one currently-active vehicle_info row."""
    row = VehicleInfo(
        source_id=1,
        source_device="chi-eclipse-01",
        vin="4A3AK34T0XE000000",
        ecu_id=1,  # US-376: ecu_id is NOT NULL (FK not enforced on SQLite)
        ecu_signature="MD326328-ecmlink-v3",
        ecu_install_timestamp_utc=_INSTALL,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _dtc(session: Session) -> DtcLog:
    row = DtcLog(
        source_id=1,
        source_device="chi-eclipse-01",
        dtc_code="P0300",
        status="stored",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# =========================================================================
# Tests
# =========================================================================


def test_dtcFreezeFrame_tableShape_hasAc1Columns(engine):
    """AC#1 / V-1: table exposes the five enumerated columns + FK targets."""
    columns = {c["name"]: c for c in inspect(engine).get_columns("dtc_freeze_frame")}

    # The five AC#1-enumerated columns.
    for required in (
        "id",
        "dtc_log_id",
        "captured_at_timestamp_utc",
        "pid_responses_json",
        "vehicle_info_id",
    ):
        assert required in columns, f"dtc_freeze_frame missing column {required!r}"

    fks = {
        fk["constrained_columns"][0]: fk["referred_table"]
        for fk in inspect(engine).get_foreign_keys("dtc_freeze_frame")
    }
    assert fks.get("dtc_log_id") == "dtc_log"
    assert fks.get("vehicle_info_id") == "vehicle_info"


def test_dtcFreezeFrame_jsonRoundTrip_preserves16Pids(engine):
    """pid_responses_json round-trips a 16-key dict losslessly (V-2 substrate)."""
    pids = {f"PID_{i:02d}": float(i) for i in range(16)}
    with Session(engine) as session:
        vehicle = _activeVehicle(session)
        dtc = _dtc(session)
        session.add(
            DtcFreezeFrame(
                source_id=1,
                source_device="chi-eclipse-01",
                dtc_log_id=dtc.id,
                vehicle_info_id=vehicle.id,
                captured_at_timestamp_utc=_CAPTURE,
                pid_responses_json=pids,
            )
        )
        session.commit()

    with Session(engine) as session:
        row = session.query(DtcFreezeFrame).one()
        assert row.pid_responses_json == pids
        assert len(row.pid_responses_json) == 16
        assert row.captured_at_timestamp_utc == _CAPTURE


def test_dtcFreezeFrame_emptyPidJson_allowed(engine):
    """V-6 graceful degradation: pid_responses_json={} is a legal stored value."""
    with Session(engine) as session:
        vehicle = _activeVehicle(session)
        session.add(
            DtcFreezeFrame(
                source_id=2,
                source_device="chi-eclipse-01",
                vehicle_info_id=vehicle.id,
                captured_at_timestamp_utc=_CAPTURE,
                pid_responses_json={},
            )
        )
        session.commit()
        row = session.query(DtcFreezeFrame).one()
        assert row.pid_responses_json == {}


def test_vehicleInfo_tableComment_documentsAppendOnlyInvariant():
    """AC#2 / V-4: vehicle_info table comment documents the append-only rule.

    Asserted against the ORM ``Table.comment`` (dialect-independent; the SQLite
    test dialect does not implement comment reflection, but the declared comment
    is what lands as the MariaDB SQL table comment in production).
    """
    comment = VehicleInfo.__table__.comment or ""
    lowered = comment.lower()
    assert "append-only" in lowered
    # The comment must tie the invariant to the freeze-frame FK + close+open.
    assert "freeze" in lowered
    assert "close" in lowered and "open" in lowered
