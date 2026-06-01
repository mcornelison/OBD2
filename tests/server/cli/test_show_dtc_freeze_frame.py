################################################################################
# File Name: test_show_dtc_freeze_frame.py
# Purpose/Description: Sprint 43 V0.28.0 (US-369 / F-109) -- tests for the
#                      show_dtc_freeze_frame server CLI.  Given a server
#                      dtc_log.id, prints the DTC row, the freeze-frame's
#                      captured_at + 16-PID dict, and the vehicle_info row joined
#                      through the stored FK (the ECU active at capture time --
#                      Q4 round-trip, unchanged by later stamp_ecu_swap rows).
#                      Real in-memory-file SQLite + real ORM.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-369) | Initial -- show_dtc_freeze_frame reader CLI.
# ================================================================================
################################################################################

"""US-369 / F-109 tests: show_dtc_freeze_frame reader CLI."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import show_dtc_freeze_frame as cli  # noqa: E402
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
def dbPath():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    eng.dispose()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


def _runCli(monkeypatch, dbPath: str, argv) -> int:
    monkeypatch.setattr(
        cli, "resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
    )
    return cli.main(argv)


def _seed(dbPath, *, pids=_PIDS, notes=None, removal=None, add_later_ecu=False):
    """Seed one ECU + DTC + freeze-frame; return the server dtc_log.id."""
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        ecu = VehicleInfo(
            source_id=1, source_device=_DEVICE, vin=_VIN,
            ecu_signature="orig-ECU", cal_signature="pump-93-v1",
            ecu_install_timestamp_utc=_INSTALL,
            ecu_removal_timestamp_utc=removal,
        )
        session.add(ecu)
        dtc = DtcLog(source_id=1, source_device=_DEVICE,
                     dtc_code="P0300", status="stored")
        session.add(dtc)
        session.commit()
        session.refresh(ecu)
        session.refresh(dtc)
        frame = DtcFreezeFrame(
            source_id=1, source_device=_DEVICE,
            dtc_log_id=dtc.id, vehicle_info_id=ecu.id,
            captured_at_timestamp_utc=_CAPTURE,
            pid_responses_json=pids, notes=notes,
        )
        session.add(frame)
        if add_later_ecu:
            # A subsequent ECU swap: close the orig + open a new active row.
            ecu.ecu_removal_timestamp_utc = datetime(2026, 6, 1, 0, 0, 0)
            session.add(VehicleInfo(
                source_id=2, source_device=_DEVICE, vin=_VIN,
                ecu_signature="new-ECU",
                ecu_install_timestamp_utc=datetime(2026, 6, 1, 0, 0, 0),
            ))
        session.commit()
        dtcId = dtc.id
    eng.dispose()
    return dtcId


# ==============================================================================
# 1) Happy path: DTC + 16 PIDs + vehicle_info ecu_signature (AC#2 / V-2)
# ==============================================================================


def test_printsDtc16PidsAndEcuSignature(monkeypatch, dbPath, capsys):
    dtcId = _seed(dbPath)
    rc = _runCli(monkeypatch, dbPath, ["--dtc-log-id", str(dtcId)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "P0300" in out
    assert "orig-ECU" in out
    # All 16 PID names rendered.
    for name in _PIDS:
        assert name in out


# ==============================================================================
# 2) Q4 round-trip: joins to the ORIGINAL ECU row, not the later one (V-3)
# ==============================================================================


def test_joinsToCaptureTimeEcu_notLaterSwap(monkeypatch, dbPath, capsys):
    dtcId = _seed(dbPath, add_later_ecu=True)
    rc = _runCli(monkeypatch, dbPath, ["--dtc-log-id", str(dtcId)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "orig-ECU" in out
    assert "new-ECU" not in out


# ==============================================================================
# 3) Missing freeze-frame: exit 0 + graceful message (AC#5 / V-4)
# ==============================================================================


def test_noFreezeFrame_exit0_gracefulMessage(monkeypatch, dbPath, capsys):
    # Seed a DTC with no freeze-frame.
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        dtc = DtcLog(source_id=9, source_device=_DEVICE,
                     dtc_code="P0420", status="stored")
        session.add(dtc)
        session.commit()
        dtcId = dtc.id
    eng.dispose()

    rc = _runCli(monkeypatch, dbPath, ["--dtc-log-id", str(dtcId)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "no freeze-frame recorded for this DTC" in out


# ==============================================================================
# 4) Empty PIDs: graceful "Mode 02 unavailable" + notes (conditionalOutcome 2)
# ==============================================================================


def test_emptyPids_showsUnavailableMessageAndNotes(monkeypatch, dbPath, capsys):
    dtcId = _seed(dbPath, pids={}, notes="Mode 02 dropped by ECU")
    rc = _runCli(monkeypatch, dbPath, ["--dtc-log-id", str(dtcId)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "unavailable" in out.lower()
    assert "Mode 02 dropped by ECU" in out


# ==============================================================================
# 5) Multiple freeze-frames for one DTC: most recent + WARN (conditionalOutcome 3)
# ==============================================================================


def test_multipleFreezeFrames_showsMostRecent_warns(monkeypatch, dbPath, caplog):
    dtcId = _seed(dbPath)
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        ecuId = session.query(VehicleInfo).first().id
        # A newer freeze-frame for the same DTC.
        session.add(DtcFreezeFrame(
            source_id=2, source_device=_DEVICE,
            dtc_log_id=dtcId, vehicle_info_id=ecuId,
            captured_at_timestamp_utc=datetime(2026, 5, 23, 10, 0, 0),
            pid_responses_json={"PID_NEWER": 99.0},
        ))
        session.commit()
    eng.dispose()

    import logging
    with caplog.at_level(logging.WARNING):
        rc = _runCli(monkeypatch, dbPath, ["--dtc-log-id", str(dtcId)])

    assert rc == 0
    assert "multiple" in caplog.text.lower()
