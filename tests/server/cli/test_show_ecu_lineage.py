################################################################################
# File Name: test_show_ecu_lineage.py
# Purpose/Description: Sprint 43 V0.28.0 (US-366 / F-108) -- tests for the
#                      show_ecu_lineage server CLI.  Lists every historical ECU
#                      stamp in install-timestamp order, marking the currently-
#                      active row (ecu_removal_timestamp_utc IS NULL).  Covers:
#                      populated lineage (closed + active rows, ordered, active
#                      flagged); empty table graceful message; pre-migration
#                      graceful error.  Real in-memory-file SQLite + real ORM.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- show_ecu_lineage reader CLI tests.
# ================================================================================
################################################################################

"""US-366 / F-108 tests: show_ecu_lineage reader CLI."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import show_ecu_lineage as cli  # noqa: E402
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


def _seed(dbPath: str, *, signature, install, removal=None, cal=None):
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        existing = session.query(VehicleInfo).count()
        session.add(
            VehicleInfo(
                source_id=existing + 1,
                source_device="chi-eclipse-01",
                vin="4A3AK34T0XE000000",
                ecu_id=1,  # US-376: ecu_id is NOT NULL (FK not enforced on SQLite)
                ecu_signature=signature,
                cal_signature=cal,
                ecu_install_timestamp_utc=install,
                ecu_removal_timestamp_utc=removal,
            )
        )
        session.commit()
    eng.dispose()


def _runCli(monkeypatch, dbPath: str, argv=None) -> int:
    monkeypatch.setattr(
        cli, "resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
    )
    return cli.main(argv or [])


# =========================================================================
# Populated lineage (AC#2, V-4, V-12)
# =========================================================================


def test_listsClosedAndActiveRows_inInstallOrder_activeFlagged(
    monkeypatch, dbPath, capsys,
):
    """V-4/V-12: both rows listed, ordered by install, active row flagged."""
    _seed(
        dbPath, signature="old-ECU",
        install=datetime(2026, 1, 1, 0, 0, 0),
        removal=datetime(2026, 5, 22, 14, 0, 0),
    )
    _seed(
        dbPath, signature="new-ECU",
        install=datetime(2026, 5, 22, 14, 0, 0),
        removal=None, cal="pump-93-v1",
    )

    rc = _runCli(monkeypatch, dbPath)

    assert rc == 0
    out = capsys.readouterr().out
    assert "old-ECU" in out
    assert "new-ECU" in out
    # Ordered by install: old before new.
    assert out.index("old-ECU") < out.index("new-ECU")
    # The currently-active row is highlighted with an ACTIVE marker.
    assert "ACTIVE" in out.upper()


# =========================================================================
# Empty lineage (AC graceful, V-6, conditionalOutcome 3)
# =========================================================================


def test_emptyVehicleInfo_gracefulMessage_exit0(monkeypatch, dbPath, capsys):
    """V-6: empty vehicle_info -> exit 0 with 'no ECU lineage recorded yet'."""
    rc = _runCli(monkeypatch, dbPath)

    assert rc == 0
    out = capsys.readouterr().out
    assert "no ECU lineage recorded yet" in out


# =========================================================================
# Pre-migration graceful error
# =========================================================================


def test_preMigration_noEcuColumns_gracefulError(monkeypatch, capsys, caplog):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicle_info ("
                "id INTEGER PRIMARY KEY, source_id INTEGER, vin TEXT)"
            )
        )
    eng.dispose()

    try:
        rc = _runCli(monkeypatch, tmp.name)
        assert rc != 0
        combined = (capsys.readouterr().out + caplog.text).lower()
        assert "migration" in combined
    finally:
        Path(tmp.name).unlink(missing_ok=True)
