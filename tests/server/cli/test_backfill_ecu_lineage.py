################################################################################
# File Name: test_backfill_ecu_lineage.py
# Purpose/Description: Sprint 47 V0.29.1 (US-367 / F-108) -- tests for the
#                      one-shot ECU-lineage bootstrap/backfill CLI.  The script
#                      SUPERSEDES the degenerate PRE_TRACKING_UNKNOWN placeholder
#                      (a failed bootstrap, not lineage -- Atlas 2026-06-28
#                      2-row ruling) and writes exactly TWO real ECU-era rows:
#                      prior (MD346675/6675, closed at the swap instant) + new
#                      (MD326328/UNKCAL, currently active).  Both rows resolve
#                      their ecu_id via resolveOrCreateEcu and DERIVE the TEXT
#                      ecu_signature/cal_signature snapshot columns from the
#                      resolved ecu row (so findEcuCoherenceViolations() == []).
#                      The swap instant is a SCRIPT PARAM, not a hardcoded
#                      literal.  Real temp-file SQLite + real ORM, no mocks
#                      (post-I-040 discipline); only the DB-URL resolver is
#                      redirected.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-367) | Initial -- one-shot ECU-lineage backfill CLI.
# ================================================================================
################################################################################

"""US-367 / F-108 tests: one-shot ECU-lineage bootstrap/backfill CLI."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import backfill_ecu_lineage as cli  # noqa: E402
from src.server.db.models import (  # noqa: E402
    ECU_CAL_SIGNATURE_UNKNOWN,
    VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
    Base,
    DriveSummary,
    Ecu,
    VehicleInfo,
)
from src.server.db.vehicle_info_coherence import (  # noqa: E402
    findEcuCoherenceViolations,
)

# Grounded, Spool-signed (2026-06-29) lineage facts the backfill writes.
_PRIOR_SIG = "MD346675"
_PRIOR_CAL = "6675"
_NEW_SIG = "MD326328"
_NEW_CAL = ECU_CAL_SIGNATURE_UNKNOWN  # "UNKCAL"
# Prior-ECU install = start-of-tracking (earliest realtime_data.timestamp); the
# concrete realization of Atlas's "gapless partition start (NULL)" -- the column
# is NOT NULL and the resolver compares install <= captured_at, so an unbounded
# lower bound is stored as the earliest tracked instant.
_START_OF_TRACKING = datetime(2026, 4, 23, 16, 36, 50)
# Swap instant (prior removal == new install), Spool-derived 2026-06-29.
_SWAP_INSTANT = datetime(2026, 5, 22, 18, 35, 26)
_VIN = "4A3AK34T0XE000000"
_DEVICE = "chi-eclipse-01"

_SWAP_ISO = "2026-05-22T18:35:26Z"
_START_ISO = "2026-04-23T16:36:50Z"


@pytest.fixture
def dbPath():
    """Temp-file SQLite path carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    eng.dispose()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


def _seedPlaceholder(dbPath: str) -> None:
    """Seed the degenerate PRE_TRACKING_UNKNOWN placeholder (v0010 + v0011 shape).

    One closed legacy row whose ecu_signature is the sentinel and whose window is
    zero-width (install == removal == created_at), referencing the sentinel ecu
    identity row -- exactly what the migrations leave behind for US-367 to
    supersede.
    """
    created = datetime(2026, 5, 1, 11, 53, 45)
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        ecu = Ecu(
            ecu_signature=VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
            cal_signature=VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
        )
        session.add(ecu)
        session.flush()
        session.add(
            VehicleInfo(
                source_id=1,
                source_device=_DEVICE,
                vin=_VIN,
                ecu_id=ecu.id,
                ecu_signature=VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
                cal_signature=None,
                ecu_install_timestamp_utc=created,
                ecu_removal_timestamp_utc=created,
            )
        )
        session.commit()
    eng.dispose()


def _seedDrive(dbPath: str, *, sourceId: int, startTime: datetime) -> None:
    """Seed one Pi-sync drive_summary row with a start_time for partition tests."""
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        session.add(
            DriveSummary(
                source_id=sourceId,
                source_device=_DEVICE,
                drive_id=sourceId,
                start_time=startTime,
            )
        )
        session.commit()
    eng.dispose()


def _runCli(monkeypatch, dbPath: str, argv: list[str]) -> int:
    monkeypatch.setattr(
        cli, "resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
    )
    return cli.main(argv)


def _cleanArgv() -> list[str]:
    return [
        "--prior-signature", _PRIOR_SIG,
        "--prior-cal-signature", _PRIOR_CAL,
        "--new-signature", _NEW_SIG,
        "--new-cal-signature", _NEW_CAL,
        "--start-of-tracking", _START_ISO,
        "--swap-instant", _SWAP_ISO,
    ]


def _rows(dbPath: str) -> list[VehicleInfo]:
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        rows = (
            session.query(VehicleInfo)
            .order_by(VehicleInfo.ecu_install_timestamp_utc)
            .all()
        )
        session.expunge_all()
    eng.dispose()
    return rows


def _count(dbPath: str, whereClause) -> int:
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        stmt = select(func.count()).select_from(VehicleInfo)
        if whereClause is not None:
            stmt = stmt.where(whereClause)
        n = session.execute(stmt).scalar_one()
    eng.dispose()
    return n


# =========================================================================
# Clean bootstrap: supersede placeholder -> exactly 2 real eras (V-1..V-5)
# =========================================================================


def test_backfill_supersedesPlaceholder_writesTwoRealEras(monkeypatch, dbPath):
    """A clean bootstrap supersedes the placeholder and writes 2 real eras."""
    _seedPlaceholder(dbPath)

    rc = _runCli(monkeypatch, dbPath, _cleanArgv())

    assert rc == cli.EXIT_OK
    # V-1: exactly 2 rows post-backfill.
    assert _count(dbPath, None) == 2
    # V-2: zero PRE_TRACKING_UNKNOWN rows (placeholder superseded).
    assert _count(
        dbPath, VehicleInfo.ecu_signature == VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
    ) == 0
    # V-3: exactly one currently-active row (new ECU, removal NULL).
    assert _count(dbPath, VehicleInfo.ecu_removal_timestamp_utc.is_(None)) == 1
    # V-4: both rows carry a resolved ecu_id FK.
    assert _count(dbPath, VehicleInfo.ecu_id.is_(None)) == 0


def test_backfill_priorAndNewEraBoundaries(monkeypatch, dbPath):
    """Prior era: [start-of-tracking, swap); new era: [swap, NULL)."""
    _seedPlaceholder(dbPath)

    _runCli(monkeypatch, dbPath, _cleanArgv())

    prior, new = _rows(dbPath)
    assert prior.ecu_signature == _PRIOR_SIG
    assert prior.cal_signature == _PRIOR_CAL
    assert prior.ecu_install_timestamp_utc == _START_OF_TRACKING
    assert prior.ecu_removal_timestamp_utc == _SWAP_INSTANT
    assert new.ecu_signature == _NEW_SIG
    assert new.cal_signature == _NEW_CAL
    assert new.ecu_install_timestamp_utc == _SWAP_INSTANT
    assert new.ecu_removal_timestamp_utc is None
    # VIN is inherited from the superseded placeholder (resolver joins on vin).
    assert prior.vin == _VIN
    assert new.vin == _VIN


def test_backfill_resolvesEcuIdAndDerivesTextSnapshots(monkeypatch, dbPath):
    """Both eras key a real ecu_id; TEXT snapshots agree -> no coherence drift."""
    _seedPlaceholder(dbPath)

    _runCli(monkeypatch, dbPath, _cleanArgv())

    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        # V-5: coherence checker returns empty (derived snapshots == ecu rows).
        assert findEcuCoherenceViolations(session) == []
        # Each era references the distinct (sig, cal) ecu identity row.
        priorEcu = session.execute(
            select(Ecu).where(Ecu.ecu_signature == _PRIOR_SIG),
        ).scalar_one()
        newEcu = session.execute(
            select(Ecu).where(Ecu.ecu_signature == _NEW_SIG),
        ).scalar_one()
        assert priorEcu.cal_signature == _PRIOR_CAL
        assert newEcu.cal_signature == _NEW_CAL
    eng.dispose()


# =========================================================================
# Join / partition verification (V-6, V-7) + no resolver overlap
# =========================================================================


def test_verifyDrivePartition_partitionsDrivesByEra(monkeypatch, dbPath):
    """Drives before the swap -> prior ECU; drives at/after -> new ECU."""
    _seedPlaceholder(dbPath)
    # Drive 1 (just after start-of-tracking) + drive 24 (pre-swap) -> prior.
    _seedDrive(dbPath, sourceId=1, startTime=datetime(2026, 4, 23, 16, 40, 0))
    _seedDrive(dbPath, sourceId=24, startTime=datetime(2026, 5, 22, 14, 43, 0))
    # Drive 25 (post-swap) + drive 30 -> new.
    _seedDrive(dbPath, sourceId=25, startTime=datetime(2026, 5, 22, 18, 35, 38))
    _seedDrive(dbPath, sourceId=30, startTime=datetime(2026, 6, 10, 12, 0, 0))

    _runCli(monkeypatch, dbPath, _cleanArgv())

    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        report = cli.verifyDrivePartition(session)
    eng.dispose()

    # V-6: drives 1-24 -> prior; V-7: drives 25+ -> new.
    assert report["priorSignature"] == _PRIOR_SIG
    assert report["newSignature"] == _NEW_SIG
    assert report["priorDriveCount"] == 2
    assert report["newDriveCount"] == 2
    # No drive resolves to 0 or >1 ECU era (resolver never raises).
    assert report["unresolved"] == []
    assert report["overlapping"] == []


def test_backfill_noOverlappingWindows_resolverSafe(monkeypatch, dbPath):
    """Boundary instant equals no sample -> no drive double-matches both eras."""
    _seedPlaceholder(dbPath)
    # Last prior sample (14:50:14) and first new sample (18:35:27) straddle the
    # swap instant (18:35:26) with no sample exactly on it.
    _seedDrive(dbPath, sourceId=24, startTime=datetime(2026, 5, 22, 14, 50, 14))
    _seedDrive(dbPath, sourceId=25, startTime=datetime(2026, 5, 22, 18, 35, 27))

    _runCli(monkeypatch, dbPath, _cleanArgv())

    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        report = cli.verifyDrivePartition(session)
    eng.dispose()

    assert report["overlapping"] == []
    assert report["unresolved"] == []


# =========================================================================
# Swap instant is a script PARAM, not hardcoded (V-8)
# =========================================================================


def test_swapInstantIsParam_distinctValueShiftsBoundary(monkeypatch, dbPath):
    """A different --swap-instant produces a different era boundary (param-driven)."""
    _seedPlaceholder(dbPath)
    altArgv = _cleanArgv()
    swapIdx = altArgv.index("--swap-instant") + 1
    altArgv[swapIdx] = "2026-05-22T20:00:00Z"

    _runCli(monkeypatch, dbPath, altArgv)

    prior, new = _rows(dbPath)
    assert prior.ecu_removal_timestamp_utc == datetime(2026, 5, 22, 20, 0, 0)
    assert new.ecu_install_timestamp_utc == datetime(2026, 5, 22, 20, 0, 0)


# =========================================================================
# Idempotency + safety
# =========================================================================


def test_backfill_idempotentRerun_noDuplication(monkeypatch, dbPath):
    """Re-running the same backfill is a safe no-op (still exactly 2 eras)."""
    _seedPlaceholder(dbPath)

    rc1 = _runCli(monkeypatch, dbPath, _cleanArgv())
    rc2 = _runCli(monkeypatch, dbPath, _cleanArgv())

    assert rc1 == cli.EXIT_OK
    assert rc2 == cli.EXIT_OK
    assert _count(dbPath, None) == 2
    assert _count(dbPath, VehicleInfo.ecu_removal_timestamp_utc.is_(None)) == 1


def test_backfill_refusesWhenRealLineageExists(monkeypatch, dbPath):
    """Refuse loudly if non-placeholder lineage already exists (not a bootstrap)."""
    # Seed a real, unexpected active era (no placeholder) -> the backfill must
    # NOT overwrite real lineage.
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        ecu = Ecu(ecu_signature="MD999999", cal_signature="real")
        session.add(ecu)
        session.flush()
        session.add(
            VehicleInfo(
                source_id=1,
                source_device=_DEVICE,
                vin=_VIN,
                ecu_id=ecu.id,
                ecu_signature="MD999999",
                cal_signature="real",
                ecu_install_timestamp_utc=datetime(2026, 1, 1, 0, 0, 0),
                ecu_removal_timestamp_utc=None,
            )
        )
        session.commit()
    eng.dispose()

    rc = _runCli(monkeypatch, dbPath, _cleanArgv())

    assert rc == cli.EXIT_RUNTIME
    # The real lineage row is untouched.
    assert _count(dbPath, VehicleInfo.ecu_signature == "MD999999") == 1
    assert _count(dbPath, None) == 1


def test_backfill_freshDbNoPlaceholder_requiresVinAndDevice(monkeypatch, dbPath):
    """With no placeholder to inherit from, vin/source-device come from params."""
    rc = _runCli(
        monkeypatch,
        dbPath,
        [*_cleanArgv(), "--vin", _VIN, "--source-device", _DEVICE],
    )

    assert rc == cli.EXIT_OK
    assert _count(dbPath, None) == 2
    prior, new = _rows(dbPath)
    assert prior.vin == _VIN
    assert new.vin == _VIN
