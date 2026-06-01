################################################################################
# File Name: test_add_ecu_note.py
# Purpose/Description: Sprint 43 V0.28.0 (US-366 / F-108) -- tests for the
#                      add_ecu_note server CLI.  Appends a timestamped line to a
#                      vehicle_info row's `notes` column (append-only; prior
#                      content preserved -- notes is a MUTABLE column, distinct
#                      from the immutable ECU-identity columns).  Covers: append
#                      to an empty notes; append again without overwriting; bogus
#                      vehicle_info id graceful error with no partial state.  Also
#                      unit-tests the pure appendNote() helper deterministically.
#                      Real in-memory-file SQLite + real ORM.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- add_ecu_note append-only notes CLI.
# ================================================================================
################################################################################

"""US-366 / F-108 tests: add_ecu_note append-only notes CLI."""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import add_ecu_note as cli  # noqa: E402
from src.server.cli._ecu_lineage_support import appendNote  # noqa: E402
from src.server.db.models import Base, VehicleInfo  # noqa: E402


@pytest.fixture
def dbPath():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    eng.dispose()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


def _seedActive(dbPath: str, *, signature="new-ECU") -> int:
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        row = VehicleInfo(
            source_id=1,
            source_device="chi-eclipse-01",
            vin="4A3AK34T0XE000000",
            ecu_id=1,  # US-376: ecu_id is NOT NULL (FK not enforced on SQLite)
            ecu_signature=signature,
            ecu_install_timestamp_utc=datetime(2026, 5, 22, 14, 0, 0),
            ecu_removal_timestamp_utc=None,
        )
        session.add(row)
        session.commit()
        rid = row.id
    eng.dispose()
    return rid


def _runCli(monkeypatch, dbPath: str, argv: list[str]) -> int:
    monkeypatch.setattr(
        cli, "resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
    )
    return cli.main(argv)


def _notes(dbPath: str, rid: int) -> str | None:
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        notes = session.get(VehicleInfo, rid).notes
    eng.dispose()
    return notes


# =========================================================================
# Pure helper -- deterministic append (no DB)
# =========================================================================


class TestAppendNoteHelper:
    def test_appendToEmpty_returnsSingleStampedLine(self):
        now = datetime(2026, 5, 22, 15, 30, 0, tzinfo=UTC)
        result = appendNote(None, "Mode 22 silent", now=now)
        assert "Mode 22 silent" in result
        assert "2026-05-22" in result
        assert result.count("\n") == 0

    def test_appendToExisting_preservesPriorLine(self):
        now = datetime(2026, 5, 23, 9, 0, 0, tzinfo=UTC)
        prior = "[2026-05-22T15:30:00Z] Mode 22 silent"
        result = appendNote(prior, "knock retard observed", now=now)
        assert prior in result
        assert "knock retard observed" in result
        assert result.count("\n") == 1


# =========================================================================
# CLI append (AC#7, V-10)
# =========================================================================


def test_appendNote_toEmptyNotes_thenAgain_preservesHistory(
    monkeypatch, dbPath,
):
    """V-10: two appends -> both lines present, neither overwritten."""
    rid = _seedActive(dbPath)

    rc1 = _runCli(
        monkeypatch, dbPath,
        ["--vehicle-info-id", str(rid), "--text", "Mode 22 silent 2026-05-22"],
    )
    assert rc1 == 0
    assert "Mode 22 silent 2026-05-22" in _notes(dbPath, rid)

    rc2 = _runCli(
        monkeypatch, dbPath,
        ["--vehicle-info-id", str(rid), "--text", "knock retard ~18deg"],
    )
    assert rc2 == 0
    notes = _notes(dbPath, rid)
    # Prior line preserved + new line appended (two lines).
    assert "Mode 22 silent 2026-05-22" in notes
    assert "knock retard ~18deg" in notes
    assert notes.count("\n") == 1


# =========================================================================
# Bogus id graceful error (V-11)
# =========================================================================


def test_bogusVehicleInfoId_gracefulError_noPartialState(
    monkeypatch, dbPath, caplog,
):
    """V-11: unknown id -> 'vehicle_info id not found'; nothing written."""
    _seedActive(dbPath)

    with caplog.at_level(logging.ERROR):
        rc = _runCli(
            monkeypatch, dbPath,
            ["--vehicle-info-id", "9999", "--text", "orphan note"],
        )

    assert rc != 0
    assert "not found" in caplog.text.lower()
    # The real row is untouched.
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        assert all(r.notes is None for r in session.query(VehicleInfo).all())
    eng.dispose()
