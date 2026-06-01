################################################################################
# File Name: test_sync_dtc_freeze_frame.py
# Purpose/Description: Sprint 43 V0.28.0 (US-369 / F-109) -- Pi->server sync of
#                      dtc_freeze_frame rows.  The Pi sends a cross-tier shape
#                      (vehicle_info_vin TEXT + Pi-local dtc_log_id + a JSON
#                      string pid_responses_json); the server sync path resolves
#                      vin -> integer vehicle_info_id at the ECU era active at
#                      capture time, resolves the Pi dtc_log_id -> server
#                      dtc_log.id, parses the JSON, and upserts a server row.
#                      Real in-memory SQLite + real ORM (post-I-040 discipline).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-369) | Initial -- dtc_freeze_frame Pi->server sync
#               |              | round-trip + cross-tier FK resolution.
# ================================================================================
################################################################################

"""US-369 / F-109 server-side sync tests for ``dtc_freeze_frame``.

The cross-tier wrinkle (US-368 design): the Pi ``vehicle_info`` PK is ``vin``
(TEXT) while the server PK is an integer ``id``.  The Pi freeze-frame row
carries ``vehicle_info_vin``; the server sync path resolves it to the integer
``vehicle_info_id`` of the ECU era active at ``captured_at`` (the Q4 temporal
join).  It also maps the Pi-local ``dtc_log_id`` to the server ``dtc_log.id``
and parses the JSON-string ``pid_responses_json`` into the JSON column.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import (  # noqa: E402
    Base,
    DtcFreezeFrame,
    DtcLog,
    VehicleInfo,
)

_DEVICE = "chi-eclipse-01"
_VIN = "4A3AK34T0XE000000"
_INSTALL = datetime(2026, 5, 22, 14, 0, 0)
_CAPTURE = datetime(2026, 5, 23, 9, 30, 0)
_PIDS = {f"PID_{i:02d}": float(i) for i in range(16)}


@pytest.fixture
def syncEngine():
    """Sync SQLAlchemy engine against a temp SQLite file with server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedActiveEcu(session: Session, *, source_id: int = 1,
                   removal: datetime | None = None) -> VehicleInfo:
    """Insert one vehicle_info ECU-lineage row (active when removal is None)."""
    row = VehicleInfo(
        source_id=source_id,
        source_device=_DEVICE,
        vin=_VIN,
        ecu_signature="MD335287-ecmlink-v3",
        ecu_install_timestamp_utc=_INSTALL,
        ecu_removal_timestamp_utc=removal,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _piFreezeFrameTables(*, pi_dtc_log_id: int | None = 1,
                         vin: str | None = _VIN,
                         pids: dict | None = None,
                         notes: str | None = None) -> dict:
    """Build a sync `tables` payload carrying one Pi-shaped freeze-frame row."""
    pidBlob = "{}" if pids is None else json.dumps(pids)
    return {
        "dtc_freeze_frame": {
            "lastSyncedId": 0,
            "rows": [
                {
                    "id": 1,
                    "dtc_log_id": pi_dtc_log_id,
                    "captured_at_timestamp_utc": _CAPTURE.isoformat(),
                    "pid_responses_json": pidBlob,
                    "vehicle_info_vin": vin,
                    "notes": notes,
                    "data_source": "real",
                },
            ],
        },
    }


def _seedPiDtcLog(session: Session, *, source_id: int = 1) -> DtcLog:
    """Insert a server dtc_log row as if the Pi row (source_id) already synced."""
    row = DtcLog(
        source_id=source_id,
        source_device=_DEVICE,
        dtc_code="P0300",
        status="stored",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ==============================================================================
# 1) Acceptance: dtc_freeze_frame is a synced table
# ==============================================================================


def test_dtcFreezeFrame_inAcceptedTables():
    """AC#1 / V-5: the table is in the sync-table list."""
    from src.server.api.sync import ACCEPTED_TABLES

    assert "dtc_freeze_frame" in ACCEPTED_TABLES


# ==============================================================================
# 2) Round-trip: 16 PIDs + FKs preserved (AC#1 / AC#4 / V-1)
# ==============================================================================


def test_sync_preserves16PidsAndResolvesFks(syncEngine):
    from src.server.api.sync import runSyncUpsert

    with Session(syncEngine) as session:
        ecu = _seedActiveEcu(session)
        dtc = _seedPiDtcLog(session, source_id=1)
        result = runSyncUpsert(
            session=session,
            deviceId=_DEVICE,
            batchId="batch-1",
            tables=_piFreezeFrameTables(pi_dtc_log_id=1, pids=_PIDS),
            syncHistoryId=7,
        )
        session.commit()
        ecuId, dtcId = ecu.id, dtc.id

    assert result["dtc_freeze_frame"]["inserted"] == 1

    with Session(syncEngine) as session:
        row = session.execute(select(DtcFreezeFrame)).scalar_one()
        # 16 PIDs intact (parsed from the JSON string into the JSON column).
        assert row.pid_responses_json == _PIDS
        assert len(row.pid_responses_json) == 16
        # FKs resolved cross-tier.
        assert row.vehicle_info_id == ecuId
        assert row.dtc_log_id == dtcId
        # Sync bookkeeping stamped.
        assert row.source_device == _DEVICE
        assert row.source_id == 1
        assert row.sync_batch_id == 7


# ==============================================================================
# 3) Q4 temporal join: bind to the ECU era active at capture time (V-3)
# ==============================================================================


def test_sync_bindsToEcuActiveAtCaptureTime_notLaterEra(syncEngine):
    """A capture binds to the era whose [install, removal] window contains it."""
    from src.server.api.sync import runSyncUpsert

    prior_removal = datetime(2026, 5, 22, 18, 0, 0)
    with Session(syncEngine) as session:
        # Prior ECU: installed before, removed BEFORE the capture.
        prior = VehicleInfo(
            source_id=1, source_device=_DEVICE, vin=_VIN,
            ecu_signature="prior-ecu",
            ecu_install_timestamp_utc=datetime(2026, 1, 1, 0, 0, 0),
            ecu_removal_timestamp_utc=prior_removal,
        )
        session.add(prior)
        session.commit()
        # Active ECU: installed before the capture, still open.
        active = _seedActiveEcu(session, source_id=2)
        activeId = active.id

        runSyncUpsert(
            session=session, deviceId=_DEVICE, batchId="b",
            tables=_piFreezeFrameTables(pi_dtc_log_id=None, pids=_PIDS),
            syncHistoryId=1,
        )
        session.commit()

    with Session(syncEngine) as session:
        row = session.execute(select(DtcFreezeFrame)).scalar_one()
        assert row.vehicle_info_id == activeId


# ==============================================================================
# 4) Fail loudly on an unresolvable vehicle_info FK (conditionalOutcome 1)
# ==============================================================================


def test_sync_unresolvableVin_failsLoudly(syncEngine):
    from src.server.api.sync import runSyncUpsert

    with Session(syncEngine) as session:
        # No vehicle_info row at all -> the vin cannot resolve.
        with pytest.raises(ValueError, match="vehicle_info"):
            runSyncUpsert(
                session=session, deviceId=_DEVICE, batchId="b",
                tables=_piFreezeFrameTables(pi_dtc_log_id=None, pids=_PIDS),
                syncHistoryId=1,
            )


def test_sync_captureOutsideEveryWindow_failsLoudly(syncEngine):
    """A capture predating the only ECU's install has no active era -> raise."""
    from src.server.api.sync import runSyncUpsert

    with Session(syncEngine) as session:
        _seedActiveEcu(session)  # installed 2026-05-22
        early = {
            "dtc_freeze_frame": {
                "lastSyncedId": 0,
                "rows": [{
                    "id": 1,
                    "dtc_log_id": None,
                    "captured_at_timestamp_utc": "2020-01-01T00:00:00",
                    "pid_responses_json": json.dumps(_PIDS),
                    "vehicle_info_vin": _VIN,
                    "notes": None,
                    "data_source": "real",
                }],
            },
        }
        with pytest.raises(ValueError, match="vehicle_info"):
            runSyncUpsert(
                session=session, deviceId=_DEVICE, batchId="b",
                tables=early, syncHistoryId=1,
            )


# ==============================================================================
# 5) Graceful degradation: empty PIDs + notes preserved (US-368 V-6 round-trip)
# ==============================================================================


def test_sync_emptyPids_storesEmptyDictAndNotes(syncEngine):
    from src.server.api.sync import runSyncUpsert

    with Session(syncEngine) as session:
        _seedActiveEcu(session)
        runSyncUpsert(
            session=session, deviceId=_DEVICE, batchId="b",
            tables=_piFreezeFrameTables(
                pi_dtc_log_id=None, pids=None,
                notes="Mode 02 unavailable on this ECU",
            ),
            syncHistoryId=1,
        )
        session.commit()

    with Session(syncEngine) as session:
        row = session.execute(select(DtcFreezeFrame)).scalar_one()
        assert row.pid_responses_json == {}
        assert row.notes == "Mode 02 unavailable on this ECU"


# ==============================================================================
# 6) Idempotency: re-sync of the same row updates, never duplicates
# ==============================================================================


def test_sync_idempotentReSync_noDuplicate(syncEngine):
    from src.server.api.sync import runSyncUpsert

    tables = _piFreezeFrameTables(pi_dtc_log_id=None, pids=_PIDS)
    with Session(syncEngine) as session:
        _seedActiveEcu(session)
        runSyncUpsert(session=session, deviceId=_DEVICE, batchId="b1",
                      tables=tables, syncHistoryId=1)
        session.commit()

    with Session(syncEngine) as session:
        result = runSyncUpsert(session=session, deviceId=_DEVICE, batchId="b2",
                               tables=tables, syncHistoryId=2)
        session.commit()
        assert result["dtc_freeze_frame"]["inserted"] == 0
        assert result["dtc_freeze_frame"]["updated"] == 1

    with Session(syncEngine) as session:
        rows = session.execute(select(DtcFreezeFrame)).scalars().all()
        assert len(rows) == 1
