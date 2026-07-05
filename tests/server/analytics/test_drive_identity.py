################################################################################
# File Name: test_drive_identity.py
# Purpose/Description: Tests for src/server/analytics/drive_identity.py --
#                      US-448 / F-104 canonical drive-identity mint + tripwire
#                      output resolver.  Covers: the Drive ORM model + natural-key
#                      UNIQUE constraint; upsert_drive idempotency (re-mint re-uses
#                      the drive_id, never renumbers); resolve_canonical_drive_id;
#                      and the load-bearing regression -- a RAW Pi dual-mint pair
#                      STILL trips detect_overlapping_drives against the new schema
#                      while its OUTPUT maps to the canonical drives identity.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-448) | Initial -- canonical drives mint + resolver +
#               |              | tripwire-not-blinded regression fixture.
# ================================================================================
################################################################################

"""US-448 / F-104 tests for canonical drive-identity mint + tripwire resolver."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.drive_identity import (  # noqa: E402
    map_overlap_to_canonical,
    resolve_canonical_drive_id,
    upsert_drive,
)
from src.server.analytics.overlap import detect_overlapping_drives  # noqa: E402
from src.server.db.models import Base, Drive, RealtimeData  # noqa: E402

_DEVICE = "chi-eclipse-01"


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


def _seedRawDrive(
    session: Session,
    *,
    driveId: int,
    startTime: datetime,
    endTime: datetime,
    device: str = _DEVICE,
) -> None:
    """Seed one-Hz RPM realtime_data rows so the drive's window == [start,end]."""
    lane = driveId * 1_000_000
    ts = startTime
    while ts <= endTime:
        session.add(
            RealtimeData(
                source_id=lane,
                source_device=device,
                timestamp=ts,
                parameter_name="RPM",
                value=2000.0,
                drive_id=driveId,
                data_source="real",
            )
        )
        lane += 1
        ts = ts + timedelta(seconds=1)
    session.commit()


# =========================================================================
# Drive ORM model + natural-key UNIQUE constraint
# =========================================================================


class TestDriveModel:
    def test_tablenameAndColumns(self, engine) -> None:
        cols = set(Drive.__table__.columns.keys())
        assert Drive.__tablename__ == "drives"
        assert cols == {
            "drive_id", "source_device", "source_drive_id",
            "start_time", "end_time", "data_source", "data_quality",
        }

    def test_driveIdIsAutoincrementPk(self, engine) -> None:
        pk = list(Drive.__table__.primary_key.columns)
        assert [c.name for c in pk] == ["drive_id"]

    def test_naturalKeyUniqueConstraintEnforced(self, engine) -> None:
        """Two rows with the same (device, source_drive_id) collide."""
        with Session(engine) as session:
            session.add(Drive(source_device=_DEVICE, source_drive_id=7))
            session.commit()
            session.add(Drive(source_device=_DEVICE, source_drive_id=7))
            with pytest.raises(IntegrityError):
                session.commit()


# =========================================================================
# upsert_drive -- natural-key mint, idempotent, never renumbers
# =========================================================================


class TestUpsertDrive:
    def test_freshMintReturnsDriveId(self, engine) -> None:
        with Session(engine) as session:
            driveId = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=27,
            )
            assert isinstance(driveId, int)
            row = session.get(Drive, driveId)
            assert row.source_drive_id == 27
            assert row.source_device == _DEVICE

    def test_reMintSameNaturalKeyReusesId_noRenumber(self, engine) -> None:
        """The load-bearing idempotency invariant: re-mint == same drive_id."""
        with Session(engine) as session:
            first = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=27,
            )
            second = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=27,
            )
            assert first == second
            # And exactly ONE row exists (no duplicate, no renumber).
            count = session.execute(
                select(Drive).where(Drive.source_drive_id == 27)
            ).scalars().all()
            assert len(count) == 1

    def test_distinctNaturalKeysGetDistinctIds(self, engine) -> None:
        with Session(engine) as session:
            a = upsert_drive(session, source_device=_DEVICE, source_drive_id=27)
            b = upsert_drive(session, source_device=_DEVICE, source_drive_id=28)
            assert a != b

    def test_reMintRefreshesMutableFields(self, engine) -> None:
        start = datetime(2026, 7, 4, 10, 0, 0)
        end = datetime(2026, 7, 4, 10, 15, 0)
        with Session(engine) as session:
            driveId = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=27,
            )
            upsert_drive(
                session, source_device=_DEVICE, source_drive_id=27,
                start_time=start, end_time=end, data_quality="full",
            )
            row = session.get(Drive, driveId)
            assert row.start_time == start
            assert row.end_time == end

    def test_emptyDeviceRaises(self, engine) -> None:
        with Session(engine) as session, pytest.raises(ValueError):
            upsert_drive(session, source_device="", source_drive_id=27)

    def test_noneSourceDriveIdRaises(self, engine) -> None:
        with Session(engine) as session, pytest.raises(ValueError):
            upsert_drive(
                session, source_device=_DEVICE, source_drive_id=None,  # type: ignore[arg-type]
            )


# =========================================================================
# resolve_canonical_drive_id
# =========================================================================


class TestResolveCanonicalDriveId:
    def test_resolvesKnownPair(self, engine) -> None:
        with Session(engine) as session:
            driveId = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=27,
            )
            assert resolve_canonical_drive_id(session, _DEVICE, 27) == driveId

    def test_unknownPairIsNoneNotSentinel(self, engine) -> None:
        with Session(engine) as session:
            assert resolve_canonical_drive_id(session, _DEVICE, 999) is None

    def test_noneInputsAreNone(self, engine) -> None:
        with Session(engine) as session:
            assert resolve_canonical_drive_id(session, None, 27) is None
            assert resolve_canonical_drive_id(session, _DEVICE, None) is None


# =========================================================================
# Tripwire NOT blinded -- raw dual-mint still trips + output maps canonical
# (US-448 AC: the load-bearing regression)
# =========================================================================


class TestTripwireOutputRepoint:
    def test_rawDualMintStillTripsAgainstNewSchema(self, engine) -> None:
        """A raw Pi dual-mint pair (23/24) still trips against the new schema.

        detect_overlapping_drives keeps DETECTING on the RAW
        realtime_data.drive_id -- the drives table's presence must not blind
        the Pi-dual-mint backstop.
        """
        base = datetime(2026, 5, 22, 14, 43, 0)
        with Session(engine) as session:
            # One physical leg, two Pi drive_ids, overlapping windows.
            _seedRawDrive(
                session, driveId=23,
                startTime=base, endTime=base + timedelta(minutes=2),
            )
            _seedRawDrive(
                session, driveId=24,
                startTime=base + timedelta(minutes=1),
                endTime=base + timedelta(minutes=3),
            )
            # Mint the canonical identities (as the harness would).
            upsert_drive(session, source_device=_DEVICE, source_drive_id=23)
            upsert_drive(session, source_device=_DEVICE, source_drive_id=24)
            session.commit()

            # Detection is on RAW ids and STILL trips.
            assert detect_overlapping_drives(session, 23) == [24]

    def test_anomalyOutputMapsToCanonicalIdentity(self, engine) -> None:
        """The detected RAW overlap ids map to canonical drives.drive_id."""
        base = datetime(2026, 5, 22, 14, 43, 0)
        with Session(engine) as session:
            _seedRawDrive(
                session, driveId=23,
                startTime=base, endTime=base + timedelta(minutes=2),
            )
            _seedRawDrive(
                session, driveId=24,
                startTime=base + timedelta(minutes=1),
                endTime=base + timedelta(minutes=3),
            )
            canonical23 = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=23,
            )
            canonical24 = upsert_drive(
                session, source_device=_DEVICE, source_drive_id=24,
            )
            session.commit()

            rawOverlap = detect_overlapping_drives(session, 23)  # [24]
            mapped = map_overlap_to_canonical(session, _DEVICE, rawOverlap)
            assert mapped == {24: canonical24}
            # And the target itself resolves to its canonical identity.
            assert resolve_canonical_drive_id(session, _DEVICE, 23) == canonical23

    def test_unmintedRawOverlapMapsToNoneNotDropped(self, engine) -> None:
        """A raw overlap id with no canonical row yet -> None (never dropped)."""
        base = datetime(2026, 5, 22, 14, 43, 0)
        with Session(engine) as session:
            _seedRawDrive(
                session, driveId=23,
                startTime=base, endTime=base + timedelta(minutes=2),
            )
            _seedRawDrive(
                session, driveId=24,
                startTime=base + timedelta(minutes=1),
                endTime=base + timedelta(minutes=3),
            )
            # Only 23 is minted; 24 is not yet in drives.
            upsert_drive(session, source_device=_DEVICE, source_drive_id=23)
            session.commit()

            mapped = map_overlap_to_canonical(
                session, _DEVICE, detect_overlapping_drives(session, 23),
            )
            assert mapped == {24: None}  # surfaced honestly, not silently dropped
