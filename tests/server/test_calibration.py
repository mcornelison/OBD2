################################################################################
# File Name: test_calibration.py
# Purpose/Description: TDD tests for src/server/analytics/calibration.py and
#                      the --calibrate / --apply CLI path in scripts/report.py
#                      (US-162 baseline calibration tooling).
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-162 (Sprint 9) —
#               |              | baselines table, proposeCalibration pure
#               |              | math, applyCalibration writer, CLI wiring.
# ================================================================================
################################################################################

"""
Tests for the baseline calibration analytics + CLI.

Coverage:
    * ``Baseline`` ORM model — columns, unique constraint, tablename.
    * ``DriveSummary.is_real`` — new flag column, default False.
    * Pure math: ``proposeCalibration`` averages avg_value per parameter across
      real-flagged drives, emits BaselineProposal rows for deltas exceeding the
      threshold, returns the real-drive count separately so callers can render
      the insufficient-data banner.
    * Insufficient-data path (fewer than 5 real drives) — empty proposals.
    * ``applyCalibration`` — pure writer, upserts by ``(device_id, name)``,
      idempotent (second call produces identical table state).
    * CLI: ``--calibrate`` (pure read), ``--calibrate --apply`` (compute +
      write atomically), ``--apply`` without ``--calibrate`` rejected.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts import report as report_cli  # noqa: E402
from src.server.analytics import calibration as calib  # noqa: E402
from src.server.db.models import (  # noqa: E402
    Base,
    Baseline,
    DriveStatistic,
    DriveSummary,
)

_DEVICE = "chi-eclipse-01"


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """File-backed SQLite engine with the full server schema."""
    with tempfile.TemporaryDirectory() as tmp:
        dbPath = Path(tmp) / "calib.db"
        eng = create_engine(f"sqlite:///{dbPath}", future=True)
        Base.metadata.create_all(eng)
        try:
            yield eng
        finally:
            eng.dispose()


def _seedDrive(
    session: Session,
    *,
    driveId: int,
    isReal: bool,
    stats: dict[str, float],
    device: str = _DEVICE,
) -> None:
    """Insert one drive_summary row plus one drive_statistic row per parameter."""
    start = datetime(2026, 4, 10, 8, 0) + timedelta(hours=driveId)
    session.add(
        DriveSummary(
            id=driveId,
            device_id=device,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            duration_seconds=1800,
            profile_id="Daily",
            row_count=100,
            is_real=isReal,
        )
    )
    for paramName, avgValue in stats.items():
        session.add(
            DriveStatistic(
                drive_id=driveId,
                parameter_name=paramName,
                min_value=avgValue - 10,
                max_value=avgValue + 10,
                avg_value=avgValue,
                std_dev=5.0,
                outlier_min=avgValue - 20,
                outlier_max=avgValue + 20,
                sample_count=100,
            )
        )


# =========================================================================
# Schema tests
# =========================================================================


class TestDriveSummaryIsRealFlag:
    """DriveSummary must carry an ``is_real`` boolean for calibration filtering."""

    def test_hasIsRealColumn(self):
        cols = {c.name for c in DriveSummary.__table__.columns}
        assert "is_real" in cols

    def test_defaultsToFalseOnInsert(self, engine):
        with Session(engine) as session:
            drive = DriveSummary(
                device_id=_DEVICE,
                start_time=datetime(2026, 4, 10, 8, 0),
                end_time=datetime(2026, 4, 10, 8, 30),
            )
            session.add(drive)
            session.commit()
            session.refresh(drive)
            assert drive.is_real is False


class TestBaselineModel:
    """New ``baselines`` table stores approved real-drive baselines."""

    def test_tablename(self):
        assert Baseline.__tablename__ == "baselines"

    def test_hasExpectedColumns(self):
        cols = {c.name for c in Baseline.__table__.columns}
        for expected in [
            "id",
            "device_id",
            "parameter_name",
            "avg_value",
            "min_value",
            "max_value",
            "std_dev",
            "sample_count",
            "established_at",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_uniqueDeviceParameter(self, engine):
        """(device_id, parameter_name) must be unique — one baseline per pair."""
        with Session(engine) as session:
            session.add(Baseline(
                device_id=_DEVICE,
                parameter_name="RPM",
                avg_value=900,
                sample_count=5,
            ))
            session.commit()
            session.add(Baseline(
                device_id=_DEVICE,
                parameter_name="RPM",
                avg_value=950,
                sample_count=5,
            ))
            with pytest.raises(Exception):  # IntegrityError across dialects
                session.commit()


# =========================================================================
# proposeCalibration — pure math
# =========================================================================


class TestProposeCalibrationInsufficientData:
    """<5 real drives → no proposals, count reflects what was found."""

    def test_noRealDrives(self, engine):
        with Session(engine) as session:
            for i in range(1, 4):
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"RPM": 900.0},
                )
            session.commit()

            result = calib.proposeCalibration(session, deviceId=_DEVICE)
            assert result.realDriveCount == 0
            assert result.proposals == []

    def test_fewerThanFiveRealDrives(self, engine):
        with Session(engine) as session:
            for i in range(1, 5):  # 4 real drives
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 860.0},
                )
            for i in range(5, 8):  # 3 sim drives
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"RPM": 900.0},
                )
            session.commit()

            result = calib.proposeCalibration(session, deviceId=_DEVICE)
            assert result.realDriveCount == 4
            assert result.proposals == []

    def test_minDrivesOverride(self, engine):
        """Override ``minDrives`` to lower the threshold for smaller corpora."""
        with Session(engine) as session:
            for i in range(1, 3):
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 860.0},
                )
            for i in range(3, 6):
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"RPM": 900.0},
                )
            session.commit()

            result = calib.proposeCalibration(
                session, deviceId=_DEVICE, minDrives=2,
            )
            assert result.realDriveCount == 2
            assert len(result.proposals) == 1


class TestProposeCalibrationProposalMath:
    """Proposal = avg of real avg_value, sim baseline = avg of sim avg_value."""

    def test_proposesUpdateWhenDeltaExceedsThreshold(self, engine):
        with Session(engine) as session:
            for i in range(1, 6):  # 5 real drives @ 860 RPM idle
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 860.0},
                )
            for i in range(6, 9):  # 3 sim drives @ 900 RPM idle
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"RPM": 900.0},
                )
            session.commit()

            result = calib.proposeCalibration(session, deviceId=_DEVICE)
            assert result.realDriveCount == 5
            assert len(result.proposals) == 1
            prop = result.proposals[0]
            assert prop.parameter_name == "RPM"
            assert prop.sim_value == pytest.approx(900.0)
            assert prop.real_value == pytest.approx(860.0)
            assert prop.delta == pytest.approx(-40.0)
            # 40/900 ≈ 4.44% > 2% default threshold → UPDATE
            assert prop.action == "UPDATE"

    def test_skipsWhenDeltaUnderThreshold(self, engine):
        """|delta / sim_value| <= 2% → action KEEP, proposal omitted."""
        with Session(engine) as session:
            for i in range(1, 6):
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"Coolant": 186.0},  # sim 185, delta 1F = 0.54%
                )
            for i in range(6, 9):
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"Coolant": 185.0},
                )
            session.commit()

            result = calib.proposeCalibration(
                session, deviceId=_DEVICE, deltaThreshold=0.02,
            )
            # delta below threshold — no proposal row
            assert result.proposals == []
            assert result.realDriveCount == 5

    def test_multipleParameters(self, engine):
        """Each parameter evaluated independently; only divergent ones emitted."""
        with Session(engine) as session:
            realStats = {"RPM": 860.0, "Coolant": 192.0, "IAT": 78.0}
            simStats = {"RPM": 900.0, "Coolant": 185.0, "IAT": 78.2}  # IAT close
            for i in range(1, 6):
                _seedDrive(
                    session, driveId=i, isReal=True, stats=realStats,
                )
            for i in range(6, 9):
                _seedDrive(
                    session, driveId=i, isReal=False, stats=simStats,
                )
            session.commit()

            result = calib.proposeCalibration(session, deviceId=_DEVICE)
            names = {p.parameter_name for p in result.proposals}
            assert "RPM" in names
            assert "Coolant" in names
            assert "IAT" not in names  # 0.26% delta — below threshold

    def test_filtersByDevice(self, engine):
        """Real drives from other devices are ignored."""
        with Session(engine) as session:
            # Target device — 5 real @ 860 + 3 sim @ 900 RPM.
            for i in range(1, 6):
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 860.0},
                )
            for i in range(6, 9):
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"RPM": 900.0},
                )
            # Other device — different real values, must not influence.
            for i in range(9, 14):
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 700.0},
                    device="another-pi",
                )
            session.commit()

            result = calib.proposeCalibration(session, deviceId=_DEVICE)
            assert result.realDriveCount == 5
            # Real avg must be 860, not influenced by the other device
            rpm = next(p for p in result.proposals if p.parameter_name == "RPM")
            assert rpm.real_value == pytest.approx(860.0)


class TestProposeCalibrationReadOnly:
    """--calibrate must be a pure read — nothing ever written to baselines."""

    def test_doesNotWriteBaselines(self, engine):
        with Session(engine) as session:
            for i in range(1, 6):
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 860.0},
                )
            for i in range(6, 9):
                _seedDrive(
                    session, driveId=i, isReal=False,
                    stats={"RPM": 900.0},
                )
            session.commit()

            calib.proposeCalibration(session, deviceId=_DEVICE)

            count = session.execute(
                select(Baseline),
            ).scalars().all()
            assert count == []


# =========================================================================
# applyCalibration — writer
# =========================================================================


class TestApplyCalibration:
    """--apply persists proposals to baselines table atomically."""

    def test_writesOneRowPerProposal(self, engine):
        with Session(engine) as session:
            proposals = [
                calib.BaselineProposal(
                    parameter_name="RPM",
                    sim_value=900.0,
                    real_value=860.0,
                    delta=-40.0,
                    action="UPDATE",
                    min_value=850.0,
                    max_value=880.0,
                    std_dev=10.0,
                    sample_count=5,
                ),
                calib.BaselineProposal(
                    parameter_name="Coolant",
                    sim_value=185.0,
                    real_value=192.0,
                    delta=7.0,
                    action="UPDATE",
                    min_value=180.0,
                    max_value=200.0,
                    std_dev=4.0,
                    sample_count=5,
                ),
            ]

            written = calib.applyCalibration(
                session, proposals, deviceId=_DEVICE,
            )
            session.commit()
            assert written == 2

            rows = session.execute(select(Baseline)).scalars().all()
            assert len(rows) == 2
            names = {r.parameter_name for r in rows}
            assert names == {"RPM", "Coolant"}
            rpm = next(r for r in rows if r.parameter_name == "RPM")
            assert rpm.avg_value == pytest.approx(860.0)
            assert rpm.device_id == _DEVICE

    def test_idempotentReapply(self, engine):
        """Running apply twice with same proposals produces the same state."""
        proposals = [
            calib.BaselineProposal(
                parameter_name="RPM",
                sim_value=900.0,
                real_value=860.0,
                delta=-40.0,
                action="UPDATE",
                min_value=850.0,
                max_value=880.0,
                std_dev=10.0,
                sample_count=5,
            ),
        ]

        with Session(engine) as session:
            calib.applyCalibration(session, proposals, deviceId=_DEVICE)
            session.commit()

        with Session(engine) as session:
            calib.applyCalibration(session, proposals, deviceId=_DEVICE)
            session.commit()

        with Session(engine) as session:
            rows = session.execute(select(Baseline)).scalars().all()
            assert len(rows) == 1
            assert rows[0].avg_value == pytest.approx(860.0)

    def test_updatesExistingRow(self, engine):
        """Apply with a revised real_value overwrites the prior baseline."""
        with Session(engine) as session:
            first = [calib.BaselineProposal(
                parameter_name="RPM",
                sim_value=900.0, real_value=860.0, delta=-40.0,
                action="UPDATE",
                min_value=850.0, max_value=880.0,
                std_dev=10.0, sample_count=5,
            )]
            calib.applyCalibration(session, first, deviceId=_DEVICE)
            session.commit()

            second = [calib.BaselineProposal(
                parameter_name="RPM",
                sim_value=900.0, real_value=875.0, delta=-25.0,
                action="UPDATE",
                min_value=865.0, max_value=890.0,
                std_dev=8.0, sample_count=8,
            )]
            calib.applyCalibration(session, second, deviceId=_DEVICE)
            session.commit()

            rows = session.execute(select(Baseline)).scalars().all()
            assert len(rows) == 1
            assert rows[0].avg_value == pytest.approx(875.0)
            assert rows[0].sample_count == 8


# =========================================================================
# countRealDrives helper
# =========================================================================


class TestCountRealDrives:
    """Simple filtered count — keeps CLI banner cheap to compute."""

    def test_onlyRealFlaggedDrivesCount(self, engine):
        with Session(engine) as session:
            for i in range(1, 4):
                _seedDrive(session, driveId=i, isReal=True, stats={"RPM": 1.0})
            for i in range(4, 7):
                _seedDrive(session, driveId=i, isReal=False, stats={"RPM": 1.0})
            session.commit()

            assert calib.countRealDrives(session, deviceId=_DEVICE) == 3

    def test_filtersByDevice(self, engine):
        with Session(engine) as session:
            for i in range(1, 4):
                _seedDrive(session, driveId=i, isReal=True, stats={"RPM": 1.0})
            for i in range(4, 7):
                _seedDrive(
                    session, driveId=i, isReal=True,
                    stats={"RPM": 1.0}, device="other-pi",
                )
            session.commit()

            assert calib.countRealDrives(session, deviceId=_DEVICE) == 3
            assert calib.countRealDrives(session, deviceId="other-pi") == 3


# =========================================================================
# CLI integration
# =========================================================================


@pytest.fixture
def seededEngine(engine):
    """Engine with 5 real + 3 sim drives producing a proposal."""
    with Session(engine) as session:
        for i in range(1, 6):
            _seedDrive(session, driveId=i, isReal=True, stats={"RPM": 860.0})
        for i in range(6, 9):
            _seedDrive(session, driveId=i, isReal=False, stats={"RPM": 900.0})
        session.commit()
    return engine


class TestCalibrateCli:
    """scripts/report.py --calibrate prints a comparison table, writes nothing."""

    def test_calibrateRendersTable(self, seededEngine):
        args = report_cli.parseArguments(["--calibrate", "--device", _DEVICE])
        output = report_cli.renderReport(args, seededEngine)
        assert "Baseline Calibration" in output
        assert "RPM" in output
        assert "900" in output  # sim value
        assert "860" in output  # real value
        assert "UPDATE" in output

    def test_calibrateDoesNotWriteBaselines(self, seededEngine):
        args = report_cli.parseArguments(["--calibrate", "--device", _DEVICE])
        report_cli.renderReport(args, seededEngine)

        with Session(seededEngine) as session:
            rows = session.execute(select(Baseline)).scalars().all()
            assert rows == []

    def test_insufficientDataMessage(self, engine):
        with Session(engine) as session:
            # Only 3 real drives — below threshold
            for i in range(1, 4):
                _seedDrive(session, driveId=i, isReal=True, stats={"RPM": 860})
            session.commit()

        args = report_cli.parseArguments(["--calibrate", "--device", _DEVICE])
        output = report_cli.renderReport(args, engine)
        assert "Need" in output
        assert "2 more real drives" in output or "more real drives" in output

    def test_applyWritesBaselinesAtomically(self, seededEngine):
        args = report_cli.parseArguments(
            ["--calibrate", "--apply", "--device", _DEVICE],
        )
        output = report_cli.renderReport(args, seededEngine)
        assert "Baseline Calibration" in output
        assert "Applied" in output or "written" in output.lower()

        with Session(seededEngine) as session:
            rows = session.execute(select(Baseline)).scalars().all()
            assert len(rows) == 1
            assert rows[0].parameter_name == "RPM"
            assert rows[0].avg_value == pytest.approx(860.0)

    def test_applyWithoutCalibrateIsRejected(self):
        """argparse must reject `--apply` without `--calibrate`."""
        with pytest.raises(SystemExit):
            report_cli.parseArguments(["--apply", "--device", _DEVICE])

    def test_calibrateIsMutuallyExclusiveWithDrive(self):
        with pytest.raises(SystemExit):
            report_cli.parseArguments(
                ["--calibrate", "--drive", "latest"],
            )


# =========================================================================
# Main-level CLI smoke test
# =========================================================================


class TestMainCliSmoke:
    """main() writes to stdout and returns 0 for a valid --calibrate call."""

    def test_calibrateMainReturnsZero(self, seededEngine, monkeypatch):
        dbUrl = str(seededEngine.url)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = report_cli.main(
                ["--calibrate", "--device", _DEVICE, "--db-url", dbUrl],
            )
        assert rc == 0
        assert "Baseline Calibration" in buf.getvalue()
