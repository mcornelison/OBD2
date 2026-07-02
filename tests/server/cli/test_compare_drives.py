################################################################################
# File Name: test_compare_drives.py
# Purpose/Description: Tests for src/server/cli/compare_drives.py -- US-438 /
#                      F-069 cross-drive comparison CLI.  Mirrors the US-436
#                      compute-test discipline (temp-file SQLite + real ORM +
#                      real INSERTs; NO seam mocks) so the tool is exercised
#                      against the real drive_summary / drive_statistics /
#                      drive_derived_signals schema.  Covers: spec/metric
#                      parsing, F-116 foreign exclusion (drive 33 not counted),
#                      honest missing-data rendering, the pure table formatter,
#                      and the CLI wiring (monkeypatch the URL resolver).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-438) | Initial -- F-069 cross-drive comparison tool.
# ================================================================================
################################################################################

"""US-438 / F-069 tests for the cross-drive comparison CLI.

Layers:

* Pure parsing (``parseDriveSpec`` / ``resolveMetricKeys``) -- ordered dedup,
  ranges, unknown-metric rejection.
* F-116 exclusion (``driveExclusionReason``) -- foreign_vehicle + non-real
  data_source.
* DB resolution (``buildComparison``) against seeded rows -- real values,
  missing-data None, foreign-drive exclusion, --include-foreign override.
* Pure formatting (``formatComparisonTable``) -- alignment, ``--`` sentinel,
  EXCLUDED/NOT FOUND headers, honesty footnotes.
* CLI wiring (``main``) -- monkeypatch ``_resolveSyncDatabaseUrl`` onto a
  temp-file SQLite, assert exit code 0 and rendered output (the
  validationCriteria "run the tool comparing several drives" gate, incl.
  "drive 33 not counted").
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import compare_drives as cli  # noqa: E402
from src.server.cli.compare_drives import (  # noqa: E402
    NO_DATA_CELL,
    ComparisonResult,
    DriveColumn,
    buildComparison,
    driveExclusionReason,
    formatComparisonTable,
    parseDriveSpec,
    resolveMetricKeys,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveDerivedSignal,
    DriveStatistic,
    DriveSummary,
)

# =========================================================================
# Fixtures + seed helpers
# =========================================================================

BASE_TS = datetime(2026, 6, 1, 12, 0, 0)


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


def _seedSummary(
    session: Session, *, driveId: int, dataSource: str = "real",
    dataQuality: str = "full",
) -> int:
    row = DriveSummary(
        source_device="chi-eclipse-01",
        source_id=driveId,
        drive_id=driveId,
        start_time=BASE_TS,
        end_time=BASE_TS + timedelta(minutes=10),
        data_source=dataSource,
        data_quality=dataQuality,
    )
    session.add(row)
    session.flush()
    return row.id


def _seedStatistic(
    session: Session, *, summaryId: int, parameter: str,
    maxValue: float | None = None, avgValue: float | None = None,
    sampleCount: int = 100,
) -> None:
    session.add(
        DriveStatistic(
            summary_id=summaryId,
            parameter_name=parameter,
            max_value=maxValue,
            avg_value=avgValue,
            sample_count=sampleCount,
        )
    )


def _seedDerived(
    session: Session, *, summaryId: int,
    distanceKm: float, peakAccel: float | None, peakDecel: float | None,
) -> None:
    session.add(
        DriveDerivedSignal(
            summary_id=summaryId,
            estimated_distance_km=distanceKm,
            peak_acceleration_ms2=peakAccel,
            peak_deceleration_ms2=peakDecel,
            sample_count=100,
            segment_count=99,
            gap_skipped_count=0,
        )
    )


# =========================================================================
# parseDriveSpec
# =========================================================================


class TestParseDriveSpec:
    def test_commaList_ordered(self):
        assert parseDriveSpec("11,20,27") == [11, 20, 27]

    def test_range_expandsInclusive(self):
        assert parseDriveSpec("11-14") == [11, 12, 13, 14]

    def test_mixedRangeAndSingles(self):
        assert parseDriveSpec("11-13,20") == [11, 12, 13, 20]

    def test_duplicates_droppedFirstOccurrenceKept(self):
        assert parseDriveSpec("20,11,20,11") == [20, 11]

    def test_whitespaceTolerated(self):
        assert parseDriveSpec(" 11 , 20 ") == [11, 20]

    def test_empty_raises(self):
        with pytest.raises(SystemExit):
            parseDriveSpec("")

    def test_nonInteger_raises(self):
        with pytest.raises(SystemExit):
            parseDriveSpec("11,abc")

    def test_invertedRange_raises(self):
        with pytest.raises(SystemExit):
            parseDriveSpec("14-11")


# =========================================================================
# resolveMetricKeys
# =========================================================================


class TestResolveMetricKeys:
    def test_none_returnsAllInRegistryOrder(self):
        keys = resolveMetricKeys(None)
        assert keys[0] == "peak_rpm"
        assert "knock_retard" in keys
        assert "ltft" in keys
        assert "distance" in keys

    def test_explicitSubset_preservesOrder(self):
        assert resolveMetricKeys("ltft,peak_rpm") == ["ltft", "peak_rpm"]

    def test_duplicate_dropped(self):
        assert resolveMetricKeys("ltft,ltft") == ["ltft"]

    def test_unknownMetric_raises(self):
        with pytest.raises(SystemExit):
            resolveMetricKeys("ltft,bogus")


# =========================================================================
# driveExclusionReason (F-116)
# =========================================================================


class TestDriveExclusionReason:
    def test_realDrive_notExcluded(self):
        summary = DriveSummary(data_source="real", data_quality="full")
        assert driveExclusionReason(summary) is None

    def test_nullDataSource_treatedAsReal(self):
        summary = DriveSummary(data_source=None, data_quality="full")
        assert driveExclusionReason(summary) is None

    def test_foreignVehicle_excluded(self):
        summary = DriveSummary(
            data_source="real", data_quality="foreign_vehicle",
        )
        assert driveExclusionReason(summary) == "foreign_vehicle"

    def test_foreignDataSource_excluded(self):
        summary = DriveSummary(data_source="foreign", data_quality="full")
        assert driveExclusionReason(summary) == "data_source=foreign"


# =========================================================================
# buildComparison -- DB resolution
# =========================================================================


class TestBuildComparison:
    def test_resolvesRealValues(self, engine):
        with Session(engine) as session:
            sid = _seedSummary(session, driveId=11)
            _seedStatistic(session, summaryId=sid, parameter="RPM", maxValue=6800.0)
            _seedStatistic(
                session, summaryId=sid, parameter="LONG_FUEL_TRIM_1",
                avgValue=3.5,
            )
            _seedDerived(
                session, summaryId=sid, distanceKm=12.4,
                peakAccel=3.1, peakDecel=-4.2,
            )
            session.commit()

            result = buildComparison(
                session, [11], ["peak_rpm", "ltft", "peak_accel", "distance"],
            )

        assert len(result.drives) == 1
        col = result.drives[0]
        assert col.found is True
        assert col.excluded is False
        assert col.values["peak_rpm"] == pytest.approx(6800.0)
        assert col.values["ltft"] == pytest.approx(3.5)
        assert col.values["peak_accel"] == pytest.approx(3.1)
        assert col.values["distance"] == pytest.approx(12.4)

    def test_missingStatistic_rendersNone(self, engine):
        with Session(engine) as session:
            sid = _seedSummary(session, driveId=12)
            # RPM present, but no LTFT row and no derived-signals row.
            _seedStatistic(session, summaryId=sid, parameter="RPM", maxValue=5000.0)
            session.commit()

            result = buildComparison(
                session, [12], ["peak_rpm", "ltft", "distance"],
            )

        col = result.drives[0]
        assert col.values["peak_rpm"] == pytest.approx(5000.0)
        assert col.values["ltft"] is None
        assert col.values["distance"] is None

    def test_knockRetard_alwaysNone(self, engine):
        with Session(engine) as session:
            sid = _seedSummary(session, driveId=13)
            _seedStatistic(session, summaryId=sid, parameter="RPM", maxValue=5000.0)
            session.commit()

            result = buildComparison(session, [13], ["knock_retard"])

        assert result.drives[0].values["knock_retard"] is None

    def test_foreignDrive_excludedByDefault(self, engine):
        with Session(engine) as session:
            _seedSummary(session, driveId=33, dataQuality="foreign_vehicle")
            session.commit()

            result = buildComparison(session, [33], ["peak_rpm"])

        col = result.drives[0]
        assert col.found is True
        assert col.excluded is True
        assert col.exclude_reason == "foreign_vehicle"
        assert col.values == {}

    def test_foreignDrive_includedWithOverride(self, engine):
        with Session(engine) as session:
            sid = _seedSummary(
                session, driveId=33, dataQuality="foreign_vehicle",
            )
            _seedStatistic(session, summaryId=sid, parameter="RPM", maxValue=4200.0)
            session.commit()

            result = buildComparison(
                session, [33], ["peak_rpm"], includeForeign=True,
            )

        col = result.drives[0]
        assert col.excluded is False
        assert col.values["peak_rpm"] == pytest.approx(4200.0)

    def test_driveNotFound_flagged(self, engine):
        with Session(engine) as session:
            result = buildComparison(session, [999], ["peak_rpm"])

        col = result.drives[0]
        assert col.found is False
        assert col.excluded is False

    def test_multipleDrives_orderPreserved(self, engine):
        with Session(engine) as session:
            for did, rpm in ((11, 6000.0), (20, 6500.0), (27, 7000.0)):
                sid = _seedSummary(session, driveId=did)
                _seedStatistic(
                    session, summaryId=sid, parameter="RPM", maxValue=rpm,
                )
            session.commit()

            result = buildComparison(session, [27, 11, 20], ["peak_rpm"])

        assert [c.drive_id for c in result.drives] == [27, 11, 20]
        assert result.drives[0].values["peak_rpm"] == pytest.approx(7000.0)


# =========================================================================
# formatComparisonTable -- pure formatting
# =========================================================================


class TestFormatComparisonTable:
    def test_rendersMetricRowsAndDriveColumns(self):
        result = ComparisonResult(
            metric_keys=["peak_rpm", "ltft"],
            drives=[
                DriveColumn(
                    drive_id=11, found=True, excluded=False,
                    exclude_reason=None,
                    values={"peak_rpm": 6800.0, "ltft": 3.5},
                ),
                DriveColumn(
                    drive_id=20, found=True, excluded=False,
                    exclude_reason=None,
                    values={"peak_rpm": 7000.0, "ltft": None},
                ),
            ],
        )
        table = formatComparisonTable(result)

        assert "drive 11" in table
        assert "drive 20" in table
        assert "Peak RPM (rpm)" in table
        assert "LTFT (avg) (%)" in table
        # peak_rpm precision 0 -> integer render.
        assert "6800" in table
        assert "3.5" in table
        # Missing LTFT for drive 20 -> no-data sentinel.
        assert NO_DATA_CELL in table

    def test_excludedDrive_headerAndFootnote(self):
        result = ComparisonResult(
            metric_keys=["peak_rpm"],
            drives=[
                DriveColumn(
                    drive_id=33, found=True, excluded=True,
                    exclude_reason="foreign_vehicle", values={},
                ),
            ],
        )
        table = formatComparisonTable(result)
        assert "EXCLUDED" in table
        assert "drive 33 EXCLUDED (foreign_vehicle)" in table
        assert "F-116" in table

    def test_notFoundDrive_headerAndFootnote(self):
        result = ComparisonResult(
            metric_keys=["peak_rpm"],
            drives=[
                DriveColumn(
                    drive_id=999, found=False, excluded=False,
                    exclude_reason=None, values={},
                ),
            ],
        )
        table = formatComparisonTable(result)
        assert "NOT FOUND" in table

    def test_unavailableMetric_footnote(self):
        result = ComparisonResult(
            metric_keys=["knock_retard"],
            drives=[
                DriveColumn(
                    drive_id=11, found=True, excluded=False,
                    exclude_reason=None, values={"knock_retard": None},
                ),
            ],
        )
        table = formatComparisonTable(result)
        assert "unavailable" in table
        assert "USB-only" in table


# =========================================================================
# CLI wiring -- main() over a temp-file SQLite (validationCriteria gate)
# =========================================================================


class TestCliWiring:
    def _seedDb(self) -> tuple[str, object]:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        eng = create_engine(f"sqlite:///{tmp.name}")
        Base.metadata.create_all(eng)
        with Session(eng) as session:
            for did, rpm in ((27, 7000.0), (30, 6200.0)):
                sid = _seedSummary(session, driveId=did)
                _seedStatistic(
                    session, summaryId=sid, parameter="RPM", maxValue=rpm,
                )
                _seedDerived(
                    session, summaryId=sid, distanceKm=float(did),
                    peakAccel=2.5, peakDecel=-3.0,
                )
            # Drive 33 = the Ford Explorer, F-116 foreign.
            _seedSummary(session, driveId=33, dataQuality="foreign_vehicle")
            session.commit()
        return tmp.name, eng

    def test_comparesSeveralDrives_excludesForeign(self, monkeypatch, capsys):
        dbPath, eng = self._seedDb()
        monkeypatch.setattr(
            cli, "_resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
        )

        rc = cli.main(["--drives", "27,30,33", "--metrics", "peak_rpm,distance"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "drive 27" in out
        assert "drive 30" in out
        # validationCriteria: drive 33 is foreign -> EXCLUDED, not counted.
        assert "drive 33 (EXCLUDED)" in out
        assert "7000" in out
        assert "6200" in out

        eng.dispose()
        Path(dbPath).unlink(missing_ok=True)

    def test_listMetrics_exitsZero(self, capsys):
        rc = cli.main(["--list-metrics"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "peak_rpm" in out
        assert "knock_retard" in out

    def test_missingDrives_argError(self):
        # argparse parser.error -> SystemExit(2).
        with pytest.raises(SystemExit):
            cli.main([])

    def test_includeForeign_countsDrive33(self, monkeypatch, capsys):
        dbPath, eng = self._seedDb()
        # Give drive 33 a stat so the override shows a value.
        with Session(eng) as session:
            row = session.execute(
                DriveSummary.__table__.select().where(
                    DriveSummary.drive_id == 33
                )
            ).first()
            sid = row.id
            _seedStatistic(session, summaryId=sid, parameter="RPM", maxValue=4200.0)
            session.commit()
        monkeypatch.setattr(
            cli, "_resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
        )

        rc = cli.main([
            "--drives", "33", "--metrics", "peak_rpm", "--include-foreign",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "4200" in out
        assert "EXCLUDED" not in out

        eng.dispose()
        Path(dbPath).unlink(missing_ok=True)
