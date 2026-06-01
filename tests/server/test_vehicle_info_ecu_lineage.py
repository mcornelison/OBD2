################################################################################
# File Name: test_vehicle_info_ecu_lineage.py
# Purpose/Description: Sprint 43 V0.28.0 (US-365 / F-108) -- ECU-lineage schema
#                      tests for the server-side vehicle_info table.  Validates
#                      the five new ECU columns (ecu_signature, cal_signature,
#                      ecu_install_timestamp_utc, ecu_removal_timestamp_utc,
#                      notes), the "exactly one currently-active ECU" constraint
#                      (enforced via a STORED generated marker column + UNIQUE
#                      index, since MariaDB has no partial unique index), and the
#                      ORM round-trip.  Real in-memory SQLite + real ORM, no
#                      mocks (post-I-040 discipline).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-365) | Initial -- F-108 vehicle_info ECU-lineage
#               |              | columns + single-active-row constraint.
# ================================================================================
################################################################################

"""US-365 / F-108 tests for the vehicle_info ECU-lineage schema.

The server-side ``vehicle_info`` table gains five ECU-lineage columns so
downstream analytics can join a drive to the ECU active at the drive's time
window (US-367 backfill, US-370 speed_pid_calibration FK, US-368 freeze-frame
FK).  Exactly one row may be "currently active" (``ecu_removal_timestamp_utc
IS NULL``).  MariaDB has no partial unique index and a plain UNIQUE on the
timestamp would allow many NULLs, so the invariant is enforced by a STORED
generated marker column (``1`` when active, ``NULL`` when closed) carrying a
UNIQUE index -- ``1`` must be unique, ``NULL`` repeats freely.

Pi-side schema is UNCHANGED (no ECU columns); see
``test_pi_vehicle_info_schema_unchanged`` for the lock.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import Base, VehicleInfo  # noqa: E402

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


def _vehicle(
    *,
    sourceId: int,
    signature: str,
    install: datetime = _INSTALL,
    removal: datetime | None = None,
    cal: str | None = None,
    device: str = "chi-eclipse-01",
) -> VehicleInfo:
    """Build a VehicleInfo row with the NOT NULL columns populated."""
    return VehicleInfo(
        source_id=sourceId,
        source_device=device,
        vin="4A3AK34T0XE000000",
        ecu_id=1,  # US-376: ecu_id is NOT NULL (FK not enforced on SQLite)
        ecu_signature=signature,
        cal_signature=cal,
        ecu_install_timestamp_utc=install,
        ecu_removal_timestamp_utc=removal,
    )


# =========================================================================
# Column shape (AC#1, AC#4)
# =========================================================================


class TestVehicleInfoEcuColumns:
    """The five ECU columns exist on the ORM with the right nullability."""

    def test_ecuColumnsPresent(self):
        cols = {c.name for c in VehicleInfo.__table__.columns}
        for name in (
            "ecu_signature",
            "cal_signature",
            "ecu_install_timestamp_utc",
            "ecu_removal_timestamp_utc",
            "notes",
        ):
            assert name in cols, f"{name} missing from vehicle_info ORM"

    def test_requiredColumnsAreNotNull(self):
        """ecu_signature + ecu_install_timestamp_utc are NOT NULL (AC#1)."""
        table = VehicleInfo.__table__
        assert table.columns["ecu_signature"].nullable is False
        assert table.columns["ecu_install_timestamp_utc"].nullable is False

    def test_optionalColumnsAreNullable(self):
        """cal_signature, removal timestamp, notes are NULLable (AC#1)."""
        table = VehicleInfo.__table__
        assert table.columns["cal_signature"].nullable is True
        assert table.columns["ecu_removal_timestamp_utc"].nullable is True
        assert table.columns["notes"].nullable is True

    def test_existingVinColumnsRetained(self):
        """The pre-existing VIN-decoded columns are untouched (additive)."""
        cols = {c.name for c in VehicleInfo.__table__.columns}
        for name in ("vin", "make", "model", "year", "engine"):
            assert name in cols


# =========================================================================
# Round-trip (AC#4 -- ORM smoke / serialize)
# =========================================================================


class TestEcuColumnsRoundTrip:
    """A vehicle_info row with ECU columns persists + reloads cleanly."""

    def test_insertAndReload(self, engine):
        with Session(engine) as session:
            session.add(
                _vehicle(
                    sourceId=1,
                    signature="MD335287-ECMLinkV3",
                    cal="pump-93-v1",
                )
            )
            session.commit()

        with Session(engine) as session:
            row = session.query(VehicleInfo).filter_by(source_id=1).one()
            assert row.ecu_signature == "MD335287-ECMLinkV3"
            assert row.cal_signature == "pump-93-v1"
            assert row.ecu_install_timestamp_utc == _INSTALL
            assert row.ecu_removal_timestamp_utc is None


# =========================================================================
# Exactly-one-active-ECU constraint (AC#2, validationCriteria V-2/V-3)
# =========================================================================


class TestSingleActiveEcuConstraint:
    """At most one row may have ecu_removal_timestamp_utc IS NULL."""

    def test_insertActiveWhenNoneActive_succeeds(self, engine):
        """V-2: insert with NULL removal when zero rows active -> succeeds."""
        with Session(engine) as session:
            session.add(_vehicle(sourceId=1, signature="ecu-A", removal=None))
            session.commit()
            active = (
                session.query(VehicleInfo)
                .filter(VehicleInfo.ecu_removal_timestamp_utc.is_(None))
                .count()
            )
            assert active == 1

    def test_insertSecondActive_failsConstraint(self, engine):
        """V-3: a second NULL-removal row is rejected by the unique marker."""
        with Session(engine) as session:
            session.add(_vehicle(sourceId=1, signature="ecu-A", removal=None))
            session.commit()
        with Session(engine) as session:
            session.add(_vehicle(sourceId=2, signature="ecu-B", removal=None))
            with pytest.raises(IntegrityError):
                session.commit()

    def test_closedRowsDoNotCountAsActive(self, engine):
        """Many closed rows (removal set) + one active row coexist."""
        with Session(engine) as session:
            session.add(
                _vehicle(
                    sourceId=1,
                    signature="ecu-A",
                    install=_INSTALL - timedelta(days=400),
                    removal=_INSTALL,
                )
            )
            session.add(
                _vehicle(
                    sourceId=2,
                    signature="ecu-B",
                    install=_INSTALL - timedelta(days=800),
                    removal=_INSTALL - timedelta(days=400),
                )
            )
            session.add(_vehicle(sourceId=3, signature="ecu-C", removal=None))
            session.commit()
            assert session.query(VehicleInfo).count() == 3

    def test_closeThenOpen_succeeds(self, engine):
        """The close-prior + open-new swap motion (US-366) is permitted."""
        with Session(engine) as session:
            session.add(_vehicle(sourceId=1, signature="ecu-A", removal=None))
            session.commit()
            # Close the active row.
            row = session.query(VehicleInfo).filter_by(source_id=1).one()
            row.ecu_removal_timestamp_utc = _INSTALL + timedelta(days=10)
            session.commit()
            # Now a new active row may open.
            session.add(
                _vehicle(
                    sourceId=2,
                    signature="ecu-B",
                    install=_INSTALL + timedelta(days=10),
                    removal=None,
                )
            )
            session.commit()
            active = (
                session.query(VehicleInfo)
                .filter(VehicleInfo.ecu_removal_timestamp_utc.is_(None))
                .count()
            )
            assert active == 1


# =========================================================================
# Pi-side schema is UNCHANGED (AC#7)
# =========================================================================


def test_pi_vehicle_info_schema_unchanged():
    """The Pi SQLite vehicle_info schema carries no ECU columns (AC#7).

    US-365 is a SERVER-only schema change.  The Pi keeps only VIN-decoded
    columns; no Pi migration runs for vehicle_info.  This lock-test fails if a
    future change leaks an ECU column into the Pi schema string.
    """
    from src.pi.obdii import database_schema as ds

    schema_text = "\n".join(
        v for v in vars(ds).values() if isinstance(v, str)
    ).lower()
    # Locate the vehicle_info CREATE TABLE block and assert no ECU columns.
    for ecu_col in (
        "ecu_signature",
        "cal_signature",
        "ecu_install_timestamp_utc",
        "ecu_removal_timestamp_utc",
    ):
        assert ecu_col not in schema_text, (
            f"Pi vehicle_info schema leaked ECU column {ecu_col!r}; "
            f"US-365 is server-only"
        )
