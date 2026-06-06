################################################################################
# File Name: test_dtc_freeze_frame_writer.py
# Purpose/Description: Sprint 43 V0.28.0 (US-368 / F-109) -- the five temporal-
#                      invariant tests for the server-side insertDtcFreezeFrame
#                      writer-path (AC#8 / V-7..V-11).  A freeze-frame's
#                      vehicle_info FK may only bind to the ECU era that was
#                      actually installed at capture time: captured_at must fall
#                      within [ecu_install, ecu_removal] (removal NULL = open).
#                      A bogus vehicle_info_id raises BEFORE any partial insert.
#                      Real in-memory SQLite + real ORM, no mocks (post-I-040).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 insertDtcFreezeFrame temporal-
#               |              | invariant + bogus-FK writer-path tests.
# ================================================================================
################################################################################

"""US-368 / F-109 temporal-invariant tests for ``insertDtcFreezeFrame``.

The Pi cannot enforce this invariant -- its ``vehicle_info`` schema carries no
ECU lineage (server-only per US-365) -- so the server writer-path is the SSOT
gate that keeps a freeze-frame FK honest.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.api.dtc_freeze_frame import insertDtcFreezeFrame  # noqa: E402
from src.server.db.models import Base, DtcFreezeFrame, VehicleInfo  # noqa: E402

_INSTALL = datetime(2026, 5, 22, 14, 0, 0)
_REMOVAL = datetime(2026, 6, 30, 12, 0, 0)


@pytest.fixture
def session():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _vehicle(
    session: Session,
    *,
    sourceId: int = 1,
    install: datetime = _INSTALL,
    removal: datetime | None = None,
) -> VehicleInfo:
    row = VehicleInfo(
        source_id=sourceId,
        source_device="chi-eclipse-01",
        vin="4A3AK34T0XE000000",
        ecu_id=1,  # US-376: ecu_id is NOT NULL (FK not enforced on SQLite)
        ecu_signature=f"sig-{sourceId}",
        ecu_install_timestamp_utc=install,
        ecu_removal_timestamp_utc=removal,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _insert(session: Session, vehicleId: int, capturedAt: datetime, **kw):
    return insertDtcFreezeFrame(
        session,
        vehicle_info_id=vehicleId,
        captured_at=capturedAt,
        pid_responses=kw.get("pid_responses", {"RPM": 850.0}),
        dtc_log_id=kw.get("dtc_log_id"),
        source_id=kw.get("source_id", 100),
        source_device=kw.get("source_device", "chi-eclipse-01"),
    )


# =========================================================================
# V-11: bogus FK
# =========================================================================


def test_bogusVehicleInfoId_raisesBeforeInsert(session):
    """V-11: unknown vehicle_info_id -> ValueError 'not found'; no partial row."""
    with pytest.raises(ValueError, match="vehicle_info id.*not found"):
        _insert(session, 999, _INSTALL + timedelta(days=1))
    assert session.query(DtcFreezeFrame).count() == 0


# =========================================================================
# V-7 / V-8: out-of-window captures rejected
# =========================================================================


def test_capturePredatingInstall_raises(session):
    """V-7: captured_at before ecu_install -> ValueError; row not inserted."""
    vehicle = _vehicle(session, removal=_REMOVAL)
    with pytest.raises(ValueError, match="predates"):
        _insert(session, vehicle.id, _INSTALL - timedelta(seconds=1))
    assert session.query(DtcFreezeFrame).count() == 0


def test_capturePostdatingRemoval_raises(session):
    """V-8: captured_at after a CLOSED ecu_removal -> ValueError; not inserted."""
    vehicle = _vehicle(session, removal=_REMOVAL)
    with pytest.raises(ValueError, match="postdates"):
        _insert(session, vehicle.id, _REMOVAL + timedelta(seconds=1))
    assert session.query(DtcFreezeFrame).count() == 0


# =========================================================================
# V-9 / V-10: in-window captures succeed
# =========================================================================


def test_captureInOpenWindow_succeeds(session):
    """V-9: removal IS NULL (active ECU) + capture >= install -> row inserted."""
    vehicle = _vehicle(session, removal=None)
    frame = _insert(session, vehicle.id, _INSTALL + timedelta(days=5))
    assert frame.id is not None
    assert frame.vehicle_info_id == vehicle.id
    assert session.query(DtcFreezeFrame).count() == 1


def test_captureInClosedWindow_succeeds(session):
    """V-10: install <= capture <= removal -> row inserted with FK intact."""
    vehicle = _vehicle(session, removal=_REMOVAL)
    frame = _insert(session, vehicle.id, _INSTALL + timedelta(days=10))
    assert frame.id is not None
    assert frame.vehicle_info_id == vehicle.id
    assert session.query(DtcFreezeFrame).count() == 1


def test_captureOnInstallBoundary_succeeds(session):
    """Inclusive lower bound: captured_at == install is in-window."""
    vehicle = _vehicle(session, removal=_REMOVAL)
    frame = _insert(session, vehicle.id, _INSTALL)
    assert frame.id is not None


def test_captureOnRemovalBoundary_succeeds(session):
    """Inclusive upper bound: captured_at == removal is in-window."""
    vehicle = _vehicle(session, removal=_REMOVAL)
    frame = _insert(session, vehicle.id, _REMOVAL)
    assert frame.id is not None


def test_emptyPidResponses_storedGracefully(session):
    """V-6 substrate: pid_responses={} is a valid stored payload."""
    vehicle = _vehicle(session, removal=None)
    frame = _insert(
        session, vehicle.id, _INSTALL + timedelta(days=1), pid_responses={},
    )
    assert frame.pid_responses_json == {}
