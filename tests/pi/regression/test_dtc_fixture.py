################################################################################
# File Name: test_dtc_fixture.py
# Purpose/Description: Synthetic DTC fixture replay test -- verifies the Pi
#                      writes a P0171 dtc_log row, the row is delta-syncable,
#                      and the server upsert lands the right shape (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- synthetic DTC pipeline replay.
# ================================================================================
################################################################################

"""End-to-end replay test for a synthetic DTC pipeline (US-204).

Uses two synthetic DTCs (P0171 + P0420 per the Spool-supplied fixture
guidance) to walk the dtc_log row from Pi insert -> Pi delta-sync
extract -> server upsert.  Mirrors the pattern in
``tests/pi/regression/test_eclipse_idle_replay.py`` but for the DTC
table (which Spool's idle fixture cannot exercise -- the Eclipse
returned no DTCs in Session 23).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pi.data.sync_log import getDeltaRows, initDb
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.dtc_log_schema import DTC_LOG_TABLE
from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, DtcLog


def _seedSyntheticDtcs(db: ObdDatabase) -> list[tuple[str, str]]:
    """Insert P0171 + P0420 synthetic rows; return ((code, status), ...).

    Uses the Pi's INSERT shape (no source_id / source_device -- Pi
    rows are autoincrement-id-keyed).
    """
    seeded = [("P0171", "stored"), ("P0420", "pending")]
    with db.connect() as conn:
        for code, status in seeded:
            conn.execute(
                f"INSERT INTO {DTC_LOG_TABLE} "
                "(dtc_code, description, status, drive_id, data_source) "
                "VALUES (?, ?, ?, ?, ?)",
                (code, "synthetic", status, 1, "fixture"),
            )
    return seeded


def test_pipelineEndToEnd(tmp_path: Path) -> None:
    """Pi insert -> sync_log delta extract -> server upsert."""
    # 1. Pi side: initialize DB + seed two DTCs.
    piDb = ObdDatabase(str(tmp_path / "pi_dtc.db"), walMode=False)
    piDb.initialize()
    seeded = _seedSyntheticDtcs(piDb)

    # 2. sync_log delta extract picks up both rows.
    with piDb.connect() as piConn:
        initDb(piConn)
        deltaRows = getDeltaRows(piConn, 'dtc_log', lastId=0, limit=100)

    assert len(deltaRows) == len(seeded)
    assert {r['dtc_code'] for r in deltaRows} == {code for code, _ in seeded}
    # data_source preserved verbatim (no coercion in getDeltaRows).
    assert {r['data_source'] for r in deltaRows} == {'fixture'}

    # 3. Server side: in-memory MariaDB stand-in (sqlite); upsert delta.
    serverEngine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(serverEngine)
    with Session(serverEngine) as session:
        result = runSyncUpsert(
            session,
            deviceId="fixture-device",
            batchId="fixture-batch",
            tables={"dtc_log": {"rows": deltaRows}},
            syncHistoryId=1,
        )
        assert result["dtc_log"] == {
            "inserted": len(seeded), "updated": 0, "errors": 0,
        }

        # 4. Verify server-side state.
        rows = session.query(DtcLog).order_by(DtcLog.source_id).all()
        assert len(rows) == len(seeded)
        assert [r.dtc_code for r in rows] == [code for code, _ in seeded]
        assert [r.status for r in rows] == [status for _, status in seeded]
        # drive_id preserved across the boundary.
        assert {r.drive_id for r in rows} == {1}
        # data_source preserved (NOT coerced to 'real' -- the fixture
        # was tagged 'fixture' and the upsert passes it through).
        assert {r.data_source for r in rows} == {'fixture'}


def test_repeatedDeltaPushUpdatesNoNewRows(tmp_path: Path) -> None:
    """Re-running the sync with the same Pi rows -> updates, not new inserts."""
    piDb = ObdDatabase(str(tmp_path / "pi_repeat.db"), walMode=False)
    piDb.initialize()
    _seedSyntheticDtcs(piDb)

    with piDb.connect() as piConn:
        initDb(piConn)
        deltaRows = getDeltaRows(piConn, 'dtc_log', lastId=0, limit=100)

    serverEngine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(serverEngine)
    with Session(serverEngine) as session:
        firstResult = runSyncUpsert(
            session, deviceId="dev", batchId="b1",
            tables={"dtc_log": {"rows": deltaRows}}, syncHistoryId=1,
        )
        secondResult = runSyncUpsert(
            session, deviceId="dev", batchId="b2",
            tables={"dtc_log": {"rows": deltaRows}}, syncHistoryId=2,
        )

    assert firstResult["dtc_log"]["inserted"] == 2
    assert firstResult["dtc_log"]["updated"] == 0
    assert secondResult["dtc_log"]["inserted"] == 0
    assert secondResult["dtc_log"]["updated"] == 2
