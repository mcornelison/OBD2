################################################################################
# File Name: test_recompute_attribution_anomaly_cli.py
# Purpose/Description: US-363 / F-107 AC#4-#5 -- the recompute_drive_analytics
#                      CLI is the representative downstream consumer of the
#                      data_quality tripwire.  These tests drive the CLI's
#                      main() against a real in-memory-file SQLite DB seeded
#                      with the Drive 23/24 overlap and assert it surfaces the
#                      'attribution_anomaly' flag visibly, exits 0, and never
#                      drops the row (graceful degradation = DoD per Atlas
#                      Refinements row 5).  A control drive with no overlap is
#                      rendered as 'full'.  Real ORM + real INSERTs, no compute-
#                      seam mocks (post-I-040 discipline); only the DB-URL
#                      resolver is redirected to the temp DB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-363) | Initial -- downstream-consumer graceful-render
#               |              | test for the attribution-anomaly tripwire.
# ================================================================================
################################################################################

"""US-363 CLI consumer tests: recompute surfaces attribution_anomaly gracefully."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import recompute_drive_analytics as cli  # noqa: E402
from src.server.db.models import (  # noqa: E402
    Base,
    DriveSummary,
    RealtimeData,
)


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


def _seedDriveSummary(session: Session, *, driveId: int) -> None:
    session.add(
        DriveSummary(
            source_device="chi-eclipse-01",
            source_id=driveId,
            drive_id=driveId,
            data_source="real",
        )
    )


def _seedRealtime(
    session: Session, *, driveId: int, startTime: datetime, samples: int,
) -> None:
    cursor = driveId * 100_000
    for i in range(samples):
        session.add(
            RealtimeData(
                source_id=cursor + i,
                source_device="chi-eclipse-01",
                timestamp=startTime + timedelta(seconds=i),
                parameter_name="RPM",
                value=float(800 + i),
                drive_id=driveId,
                data_source="real",
            )
        )


def _runCli(monkeypatch, dbPath: str, argv: list[str]) -> int:
    monkeypatch.setattr(
        cli, "_resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
    )
    return cli.main(argv)


def test_overlappingDrive_cliSurfacesAnomaly_exit0_rowNotDropped(
    monkeypatch, dbPath, caplog,
):
    """Drive 23 overlaps drive 24 -> CLI exits 0 and logs the anomaly flag."""
    start = datetime(2026, 5, 22, 14, 43, 0)
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        _seedDriveSummary(session, driveId=23)
        _seedRealtime(session, driveId=23, startTime=start, samples=120)
        # Drive 24 overlaps drive 23's window (one physical leg minted twice).
        _seedRealtime(
            session, driveId=24,
            startTime=start + timedelta(seconds=30), samples=120,
        )
        session.commit()
    eng.dispose()

    with caplog.at_level(logging.INFO):
        rc = _runCli(monkeypatch, dbPath, ["--drive-id", "23"])

    assert rc == 0
    text = caplog.text
    # Flag surfaced visibly (the [ATTRIBUTION_ANOMALY] marker + data_quality).
    assert "ATTRIBUTION_ANOMALY" in text
    assert "data_quality=attribution_anomaly" in text
    # Row was processed, not dropped: the OK line for drive 23 is present.
    assert "drive_id=23 | OK" in text

    # And the row is actually persisted with the anomaly flag (not refused).
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        row = session.execute(
            DriveSummary.__table__.select().where(
                DriveSummary.drive_id == 23,
            )
        ).first()
        assert row is not None
        assert row.data_quality == "attribution_anomaly"
    eng.dispose()


def test_nonOverlappingDrive_cliRendersFull_noAnomalyWarning(
    monkeypatch, dbPath, caplog,
):
    """Control: a clean drive renders data_quality=full, no anomaly marker."""
    start = datetime(2026, 5, 22, 16, 0, 0)
    eng = create_engine(f"sqlite:///{dbPath}")
    with Session(eng) as session:
        _seedDriveSummary(session, driveId=25)
        _seedRealtime(session, driveId=25, startTime=start, samples=60)
        # Neighbour 5 min later -- no shared second.
        _seedRealtime(
            session, driveId=26,
            startTime=start + timedelta(seconds=300), samples=60,
        )
        session.commit()
    eng.dispose()

    with caplog.at_level(logging.INFO):
        rc = _runCli(monkeypatch, dbPath, ["--drive-id", "25"])

    assert rc == 0
    text = caplog.text
    assert "data_quality=full" in text
    assert "ATTRIBUTION_ANOMALY" not in text
