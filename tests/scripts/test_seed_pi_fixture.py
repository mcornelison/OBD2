################################################################################
# File Name: test_seed_pi_fixture.py
# Purpose/Description: Tests for scripts/seed_pi_fixture.py (US-191).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-191 (Sprint 13)
# ================================================================================
################################################################################

"""
Tests for :mod:`scripts.seed_pi_fixture`.

Covers:

* Row counts for each canonical fixture match the US-191 AC targets.
* Determinism -- building the same fixture twice produces byte-identical output.
* Schema completeness -- all 13 Pi tables + sync_log exist in the output.
* sync_log seeding -- every in-scope table present at ``last_synced_id=0``.
* CLI parse errors (missing output, missing output-dir) exit non-zero.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from scripts import seed_pi_fixture
from src.pi.data import sync_log

# ==============================================================================
# Helpers
# ==============================================================================


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tableNames(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
    return {r[0] for r in rows}


def _rowCount(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# ==============================================================================
# Row counts per canonical fixture
# ==============================================================================


class TestCanonicalRowCounts:
    """Every canonical fixture hits its documented row count."""

    @pytest.mark.parametrize(
        ("fixtureName", "expectedRealtime", "expectedConnLog"),
        [
            # (fixture, realtime rows, connection_log rows)
            # AC: cold_start ~150 / local_loop ~900 / errand_day ~2000
            # Exact counts are a function of the deterministic generator --
            # any change here signals a fixture regression.
            ("cold_start", 150, 2),
            ("local_loop", 900, 2),
            ("errand_day", 2400, 6),
        ],
    )
    def test_fixture_rowCountsMatchSpec(
        self,
        tmp_path: Path,
        fixtureName: str,
        expectedRealtime: int,
        expectedConnLog: int,
    ) -> None:
        target = tmp_path / f"{fixtureName}.db"
        counts = seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES[fixtureName], target,
        )
        assert counts["realtime_data"] == expectedRealtime
        assert counts["connection_log"] == expectedConnLog
        assert _rowCount(target, "realtime_data") == expectedRealtime
        assert _rowCount(target, "connection_log") == expectedConnLog


# ==============================================================================
# Bit-for-bit determinism
# ==============================================================================


class TestDeterministicOutput:
    """Building the same fixture twice produces byte-identical files."""

    @pytest.mark.parametrize("fixtureName", list(seed_pi_fixture.FIXTURES.keys()))
    def test_fixture_isByteIdenticalOnSecondBuild(
        self, tmp_path: Path, fixtureName: str,
    ) -> None:
        first = tmp_path / "run1.db"
        second = tmp_path / "run2.db"
        spec = seed_pi_fixture.FIXTURES[fixtureName]
        seed_pi_fixture.buildFixture(spec, first)
        seed_pi_fixture.buildFixture(spec, second)
        assert _sha256(first) == _sha256(second), (
            f"{fixtureName} fixture is not deterministic -- "
            f"first={_sha256(first)[:16]} second={_sha256(second)[:16]}"
        )


# ==============================================================================
# Schema completeness
# ==============================================================================


class TestSchemaShape:
    """Each fixture has the complete Pi schema + sync_log initialised."""

    def test_cold_start_hasFullPiSchema(self, tmp_path: Path) -> None:
        target = tmp_path / "cold_start.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["cold_start"], target,
        )
        tables = _tableNames(target)
        # All 10 Pi production tables must exist so the SyncClient's
        # dry-run COUNT(*) doesn't throw "no such table".  sync_log + the
        # auto-generated sqlite_sequence are the extras.  (US-223 dropped
        # the 11th table ``battery_log`` with its writer BatteryMonitor.)
        required = {
            # From ALL_SCHEMAS in src/pi/obdii/database_schema:
            "vehicle_info", "profiles", "static_data", "realtime_data",
            "statistics", "ai_recommendations", "calibration_sessions",
            "alert_log", "connection_log", "power_log",
            # Plus sync_log:
            "sync_log",
        }
        missing = required - tables
        assert not missing, f"missing tables in fixture: {missing}"

    def test_syncLog_seededForEveryInScopeTable(self, tmp_path: Path) -> None:
        """``sync_log`` has one row per IN_SCOPE_TABLES entry, id=0, pending."""
        target = tmp_path / "local_loop.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["local_loop"], target,
        )
        with sqlite3.connect(target) as conn:
            rows = conn.execute(
                "SELECT table_name, last_synced_id, status "
                "FROM sync_log ORDER BY table_name",
            ).fetchall()
        assert {r[0] for r in rows} == sync_log.IN_SCOPE_TABLES
        # Every in-scope table starts at last_synced_id=0 so SyncClient
        # treats every row as pending.
        assert all(r[1] == 0 for r in rows), (
            f"non-zero last_synced_id in seeded sync_log: {rows}"
        )
        assert all(r[2] == "pending" for r in rows)


# ==============================================================================
# Baseline row presence
# ==============================================================================


class TestBaselineRows:
    """profiles + vehicle_info are populated so the FK-present row shape works."""

    def test_profiles_hasDailyRow(self, tmp_path: Path) -> None:
        target = tmp_path / "cold_start.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["cold_start"], target,
        )
        with sqlite3.connect(target) as conn:
            row = conn.execute(
                "SELECT id, name FROM profiles WHERE id = ?", ("daily",),
            ).fetchone()
        assert row is not None
        assert row[0] == "daily"
        assert row[1] == "Daily"

    def test_vehicleInfo_hasEclipseVin(self, tmp_path: Path) -> None:
        target = tmp_path / "cold_start.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["cold_start"], target,
        )
        with sqlite3.connect(target) as conn:
            row = conn.execute(
                "SELECT vin, make, year FROM vehicle_info",
            ).fetchone()
        # Grounding-fact VIN from MEMORY.md / grounded-knowledge.md.
        assert row[0] == "4A3AK54F8WE122916"
        assert row[1] == "MITSUBISHI"
        assert row[2] == 1998


# ==============================================================================
# Drive structure
# ==============================================================================


class TestDriveShape:
    """errand_day has three drives; each fixture has matching drive_start +
    drive_end connection_log events."""

    def test_errandDay_hasThreeDriveStartEnds(self, tmp_path: Path) -> None:
        target = tmp_path / "errand_day.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["errand_day"], target,
        )
        with sqlite3.connect(target) as conn:
            starts = conn.execute(
                "SELECT COUNT(*) FROM connection_log "
                "WHERE event_type = 'drive_start'",
            ).fetchone()[0]
            ends = conn.execute(
                "SELECT COUNT(*) FROM connection_log "
                "WHERE event_type = 'drive_end'",
            ).fetchone()[0]
        assert starts == 3
        assert ends == 3

    def test_coldStart_hasOneDrive(self, tmp_path: Path) -> None:
        target = tmp_path / "cold_start.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["cold_start"], target,
        )
        with sqlite3.connect(target) as conn:
            starts = conn.execute(
                "SELECT COUNT(*) FROM connection_log "
                "WHERE event_type = 'drive_start'",
            ).fetchone()[0]
        assert starts == 1


# ==============================================================================
# Statistics
# ==============================================================================


class TestStatistics:
    """One statistics row per parameter, computed from realtime_data."""

    def test_local_loop_hasTenStatsRows(self, tmp_path: Path) -> None:
        target = tmp_path / "local_loop.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["local_loop"], target,
        )
        assert _rowCount(target, "statistics") == 10  # 10 params in _PARAMS_FULL

    def test_stats_rowsReflectRealtimeAggregate(self, tmp_path: Path) -> None:
        """Each stats row's sample_count matches the realtime count for that param."""
        target = tmp_path / "cold_start.db"
        seed_pi_fixture.buildFixture(
            seed_pi_fixture.FIXTURES["cold_start"], target,
        )
        with sqlite3.connect(target) as conn:
            for (name, sampleCount) in conn.execute(
                "SELECT parameter_name, sample_count FROM statistics",
            ):
                realtimeCount = conn.execute(
                    "SELECT COUNT(*) FROM realtime_data "
                    "WHERE parameter_name = ?",
                    (name,),
                ).fetchone()[0]
                assert sampleCount == realtimeCount


# ==============================================================================
# FixtureSpec validation
# ==============================================================================


class TestFixtureSpec:
    """FixtureSpec construction catches mismatched driveDurations/gaps length."""

    def test_gapSeconds_wrongLength_raisesValueError(self) -> None:
        with pytest.raises(ValueError, match="gapSeconds length must be"):
            seed_pi_fixture.FixtureSpec(
                name="broken",
                driveDurations=(100, 200, 300),
                gapSeconds=(60,),  # should be 2 entries
                sampleCadenceSeconds=10,
                paramSet=(("RPM", "rpm"),),
            )

    def test_singleDrive_noGaps_valid(self) -> None:
        """A single-drive spec with zero gaps is the baseline case."""
        spec = seed_pi_fixture.FixtureSpec(
            name="single",
            driveDurations=(100,),
            gapSeconds=(),
            sampleCadenceSeconds=5,
            paramSet=(("RPM", "rpm"),),
        )
        assert spec.name == "single"


# ==============================================================================
# CLI parse errors
# ==============================================================================


class TestCliParseErrors:
    """``main`` returns non-zero on missing required arg combinations."""

    def test_allWithoutOutputDir_exits2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = seed_pi_fixture.main(["--all"])
        assert rc == 2
        assert "output-dir" in capsys.readouterr().err

    def test_fixtureWithoutOutput_exits2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = seed_pi_fixture.main(["--fixture", "cold_start"])
        assert rc == 2
        assert "--output" in capsys.readouterr().err


# ==============================================================================
# End-to-end via main()
# ==============================================================================


class TestMainIntegration:
    """Calling ``main`` with real args produces expected output files."""

    def test_main_all_writesAllThreeFixtures(self, tmp_path: Path) -> None:
        rc = seed_pi_fixture.main([
            "--all", "--output-dir", str(tmp_path),
        ])
        assert rc == 0
        for name in ("cold_start", "local_loop", "errand_day"):
            assert (tmp_path / f"{name}.db").exists()

    def test_main_singleFixture_writesOne(self, tmp_path: Path) -> None:
        target = tmp_path / "loop.db"
        rc = seed_pi_fixture.main([
            "--fixture", "local_loop", "--output", str(target),
        ])
        assert rc == 0
        assert target.exists()
        assert _rowCount(target, "realtime_data") == 900
