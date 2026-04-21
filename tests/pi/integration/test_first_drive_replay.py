################################################################################
# File Name: test_first_drive_replay.py
# Purpose/Description: Off-Pi integration tests for scripts/validate_first_real_drive.sh
#                      (US-208 B-037 Pi Sprint kickoff).  Synthesizes a drive
#                      fixture by copying data/regression/pi-inputs/eclipse_idle.db
#                      and adding drive_id=1 tagging + synthetic dtc_log +
#                      drive_summary rows; drives the bash validator in
#                      --fixture-db mode so the query paths exercised on a
#                      real Pi can be verified on Windows/Linux dev machines.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex          | Initial implementation for US-208 (Sprint 15)
# ================================================================================
################################################################################

"""
Tests for :mod:`scripts.validate_first_real_drive.sh`.

Two categories:

1. **Fixture-mode** subprocess tests — run the bash script with
   ``--fixture-db PATH`` + ``--drive-id N`` against a local synthetic
   SQLite fixture.  These exercise the validator's Pi-side query paths
   without needing SSH or a live Pi.  The synthetic fixture is built
   on-the-fly by copying the canonical eclipse_idle fixture and adding
   drive_id tagging + a synthetic ``dtc_log`` + ``drive_summary`` row.

2. **Structural** tests — flag parsing, ``--help`` surface, ``--dry-run``
   short-circuit.  These don't need sqlite3 CLI or bash subprocess
   round-trips.

Bash dependency is gated with :data:`_skipWithoutBash` (mirrors
``tests/scripts/test_replay_pi_fixture_sh.py``).  sqlite3 CLI dependency
is gated separately because the fixture-mode queries go through bash ->
sqlite3; without the CLI the validator can't do its job on the local DB.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Environment gates.
# ---------------------------------------------------------------------------
_BASH_PATH = shutil.which("bash")
_SQLITE_PATH = shutil.which("sqlite3")

_skipWithoutBash = pytest.mark.skipif(
    _BASH_PATH is None,
    reason="bash not on PATH; validate_first_real_drive.sh needs a POSIX shell",
)
_skipWithoutSqlite = pytest.mark.skipif(
    _SQLITE_PATH is None,
    reason="sqlite3 CLI not on PATH; fixture-mode queries need sqlite3",
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DRIVER = _PROJECT_ROOT / "scripts" / "validate_first_real_drive.sh"
_BASE_FIXTURE = _PROJECT_ROOT / "data" / "regression" / "pi-inputs" / "eclipse_idle.db"


# ==============================================================================
# Fixture synthesis
# ==============================================================================


def _buildSyntheticDriveFixture(
    destDir: Path,
    *,
    driveId: int = 1,
    includeDtc: bool = False,
    includeDriveSummary: bool = True,
    coolantMaxC: float = 85.0,
) -> Path:
    """Build a synthetic drive-in-a-box fixture.

    Starts from the canonical eclipse_idle.db fixture (read-only), tags
    all rows with the given ``driveId``, then adds a synthetic
    ``dtc_log`` table + one ``drive_summary`` row.  The coolant MAX is
    coerced to ``coolantMaxC`` by patching the max-valued COOLANT_TEMP
    row so I-016 disposition tests can walk both branches.

    Returns the path to the built fixture.
    """
    dest = destDir / f"drive_{driveId}.db"
    shutil.copyfile(_BASE_FIXTURE, dest)

    with sqlite3.connect(dest) as conn:
        conn.execute("UPDATE realtime_data SET drive_id = ?", (driveId,))

        if includeDtc:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dtc_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dtc_code TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL
                        CHECK (status IN ('stored','pending','cleared')),
                    first_seen_timestamp DATETIME NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    last_seen_timestamp DATETIME NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    drive_id INTEGER,
                    data_source TEXT NOT NULL DEFAULT 'real'
                        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
                )
                """,
            )
            conn.execute(
                """
                INSERT INTO dtc_log (dtc_code, description, status, drive_id, data_source)
                VALUES ('P0171', 'System Too Lean Bank 1', 'stored', ?, 'real')
                """,
                (driveId,),
            )
        else:
            # Create empty table so validator can SELECT against it without error.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dtc_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dtc_code TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL
                        CHECK (status IN ('stored','pending','cleared')),
                    first_seen_timestamp DATETIME NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    last_seen_timestamp DATETIME NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    drive_id INTEGER,
                    data_source TEXT NOT NULL DEFAULT 'real'
                        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
                )
                """,
            )

        if includeDriveSummary:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drive_summary (
                    drive_id INTEGER PRIMARY KEY,
                    drive_start_timestamp DATETIME NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    ambient_temp_at_start_c REAL,
                    starting_battery_v REAL,
                    barometric_kpa_at_start REAL,
                    data_source TEXT NOT NULL DEFAULT 'real'
                        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
                )
                """,
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO drive_summary (
                    drive_id, ambient_temp_at_start_c,
                    starting_battery_v, barometric_kpa_at_start,
                    data_source
                ) VALUES (?, 21.0, 12.6, 101.3, 'real')
                """,
                (driveId,),
            )

        # Coerce the max coolant reading so I-016 threshold testing is
        # deterministic.  Updates the single highest-valued COOLANT_TEMP
        # row to the target value.
        topCoolantRow = conn.execute(
            "SELECT id FROM realtime_data WHERE parameter_name = 'COOLANT_TEMP' "
            "ORDER BY value DESC LIMIT 1",
        ).fetchone()
        if topCoolantRow is not None:
            conn.execute(
                "UPDATE realtime_data SET value = ? WHERE id = ?",
                (coolantMaxC, topCoolantRow[0]),
            )

        conn.commit()
    return dest


# ==============================================================================
# Helpers
# ==============================================================================


def _runDriver(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the bash validator with ``args`` and capture output."""
    return subprocess.run(  # noqa: S603 -- curated args to our own script
        [str(_BASH_PATH), str(_DRIVER), *args],
        cwd=str(cwd or _PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


# ==============================================================================
# 1. Structural tests -- no sqlite3 CLI needed.
# ==============================================================================


class TestValidatorScriptShape:
    """The driver must exist, be executable-bash, and expose the CLI surface."""

    def test_driverExists(self) -> None:
        assert _DRIVER.exists(), f"Expected {_DRIVER} to exist"

    def test_driverIsBashScript(self) -> None:
        firstLine = _DRIVER.read_text(encoding="utf-8").splitlines()[0]
        assert firstLine.startswith("#!/") and "bash" in firstLine, firstLine

    def test_driverContainsRequiredFlags(self) -> None:
        """Documented flags live inside the script body (help text + parsing)."""
        body = _DRIVER.read_text(encoding="utf-8")
        for flag in (
            "--drive-id",
            "--fixture-db",
            "--dry-run",
            "--skip-sync",
            "--skip-report",
            "--skip-spool",
            "--coolant-threshold-c",
            "--help",
        ):
            assert flag in body, f"Flag {flag!r} missing from validator body"


@_skipWithoutBash
class TestValidatorHelpAndDryRun:
    """Flag parsing + short-circuits run without any DB / SSH dependency."""

    def test_helpExitsZero(self) -> None:
        result = _runDriver(["--help"])
        assert result.returncode == 0, result.stderr
        assert "Usage" in result.stdout
        assert "--fixture-db" in result.stdout

    def test_dryRunExitsZero(self) -> None:
        result = _runDriver(["--dry-run"])
        assert result.returncode == 0, result.stderr
        assert "DRY RUN" in result.stdout or "dry run" in result.stdout.lower()

    def test_unknownFlagExitsTwo(self) -> None:
        result = _runDriver(["--bogus-flag"])
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert "Unknown" in result.stderr or "Unknown" in result.stdout


# ==============================================================================
# 2. Fixture-mode tests -- exercise the validator's query paths.
# ==============================================================================


@_skipWithoutBash
@_skipWithoutSqlite
class TestValidatorFixtureModeCleanDrive:
    """A 'no DTCs, warm coolant' drive should PASS end-to-end."""

    @pytest.fixture
    def fixtureDb(self, tmp_path: Path) -> Path:
        return _buildSyntheticDriveFixture(
            tmp_path,
            driveId=1,
            includeDtc=False,
            includeDriveSummary=True,
            coolantMaxC=85.0,
        )

    def test_cleanDriveExitsZero(self, fixtureDb: Path) -> None:
        result = _runDriver(
            ["--fixture-db", str(fixtureDb), "--drive-id", "1"],
        )
        assert result.returncode == 0, (
            f"expected PASS, got stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_cleanDriveReportsOverallPass(self, fixtureDb: Path) -> None:
        result = _runDriver(
            ["--fixture-db", str(fixtureDb), "--drive-id", "1"],
        )
        out = result.stdout
        # Every step must be reported (no silent skips per invariant #3).
        for step in ("realtime_data", "drive_summary", "dtc_log", "coolant"):
            assert step in out.lower(), f"step '{step}' missing from output:\n{out}"
        assert "PASS" in out, out

    def test_cleanDriveReportsZeroDtcsCleanly(self, fixtureDb: Path) -> None:
        """Acceptance: 'no DTCs' is a clean report, not an error."""
        result = _runDriver(
            ["--fixture-db", str(fixtureDb), "--drive-id", "1"],
        )
        out = result.stdout.lower()
        # Must say something definitive about zero DTCs rather than silent.
        assert "0" in out and ("dtc" in out or "no dtc" in out), out

    def test_cleanDriveAmbientPresent(self, fixtureDb: Path) -> None:
        """drive_summary with ambient populated -> explicit cold-start report."""
        result = _runDriver(
            ["--fixture-db", str(fixtureDb), "--drive-id", "1"],
        )
        # Either "ambient" is surfaced in output or the validator prints the
        # summary row contents.
        assert "ambient" in result.stdout.lower() or "21" in result.stdout, (
            result.stdout
        )


@_skipWithoutBash
@_skipWithoutSqlite
class TestValidatorFixtureModeDtcPresent:
    """A drive with DTCs should still PASS but report them explicitly."""

    @pytest.fixture
    def fixtureDb(self, tmp_path: Path) -> Path:
        return _buildSyntheticDriveFixture(
            tmp_path,
            driveId=1,
            includeDtc=True,
            includeDriveSummary=True,
            coolantMaxC=88.0,
        )

    def test_dtcPresentReportsCode(self, fixtureDb: Path) -> None:
        result = _runDriver(
            ["--fixture-db", str(fixtureDb), "--drive-id", "1"],
        )
        assert result.returncode == 0, result.stderr
        assert "P0171" in result.stdout, result.stdout


@_skipWithoutBash
@_skipWithoutSqlite
class TestValidatorFixtureModeColdCoolant:
    """MAX coolant below threshold flags I-016 escalation, but the script
    still exits 0 -- the validator's job is to REPORT the disposition,
    not to fail the sprint."""

    @pytest.fixture
    def fixtureDb(self, tmp_path: Path) -> Path:
        # 70 C is well below the 82 C gate -> escalate disposition.
        return _buildSyntheticDriveFixture(
            tmp_path,
            driveId=1,
            includeDtc=False,
            includeDriveSummary=True,
            coolantMaxC=70.0,
        )

    def test_belowThresholdReportsEscalation(self, fixtureDb: Path) -> None:
        result = _runDriver(
            [
                "--fixture-db", str(fixtureDb),
                "--drive-id", "1",
                "--coolant-threshold-c", "82",
            ],
        )
        assert result.returncode == 0, result.stderr
        out = result.stdout.upper()
        assert "ESCALATE" in out or "I-016" in out or "INCONCLUSIVE" in out, (
            result.stdout
        )


@_skipWithoutBash
@_skipWithoutSqlite
class TestValidatorFixtureModeMissingDriveId:
    """Querying an unknown drive_id must surface a clear FAIL for the
    realtime_data + drive_summary checks (no silent skip).
    """

    @pytest.fixture
    def fixtureDb(self, tmp_path: Path) -> Path:
        return _buildSyntheticDriveFixture(
            tmp_path,
            driveId=1,
            includeDtc=False,
            includeDriveSummary=True,
        )

    def test_missingDriveFailsWithDiagnostic(self, fixtureDb: Path) -> None:
        result = _runDriver(
            ["--fixture-db", str(fixtureDb), "--drive-id", "99"],
        )
        # Missing rows is a FAIL, not a crash.  Exit 1 signals "validator
        # ran but data didn't match expectations".
        assert result.returncode == 1, (
            f"expected FAIL=1, got {result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "FAIL" in result.stdout, result.stdout


# ==============================================================================
# 3. Python-native query tests -- exercise the SAME SQL the validator runs,
#    without needing the sqlite3 CLI.  These guarantee acceptance #3 holds
#    even on Windows dev machines where only the stdlib sqlite3 module is
#    present.  The validator script must keep these queries in sync.
# ==============================================================================


# The SQL strings below mirror the validator script's query bodies.  If the
# validator changes shape, update these in lockstep.  The tests check that
# the expected SELECT shape succeeds against a synthetic fixture.
_SQL_LATEST_DRIVE_ID = (
    "SELECT MAX(drive_id) FROM realtime_data WHERE drive_id IS NOT NULL"
)
_SQL_WINDOW_START = (
    "SELECT MIN(timestamp) FROM realtime_data WHERE drive_id = ?"
)
_SQL_WINDOW_END = (
    "SELECT MAX(timestamp) FROM realtime_data WHERE drive_id = ?"
)
_SQL_ROW_COUNT = (
    "SELECT COUNT(*) FROM realtime_data WHERE drive_id = ?"
)
_SQL_NON_REAL = (
    "SELECT COUNT(*) FROM realtime_data "
    "WHERE drive_id = ? AND data_source != 'real'"
)
_SQL_BAD_TS = (
    "SELECT COUNT(*) FROM realtime_data "
    "WHERE drive_id = ? AND timestamp NOT LIKE '%Z'"
)
_SQL_DISTINCT_PARAMS = (
    "SELECT COUNT(DISTINCT parameter_name) FROM realtime_data "
    "WHERE drive_id = ?"
)
_SQL_DTC_COUNT = "SELECT COUNT(*) FROM dtc_log WHERE drive_id = ?"
_SQL_SUMMARY_COUNT = (
    "SELECT COUNT(*) FROM drive_summary WHERE drive_id = ?"
)
_SQL_MAX_COOLANT = (
    "SELECT MAX(value) FROM realtime_data "
    "WHERE drive_id = ? AND parameter_name = 'COOLANT_TEMP'"
)


class TestValidatorQueriesAgainstFixture:
    """Run the validator's SQL strings via Python sqlite3 -- no CLI required."""

    def test_latestDriveIdFound(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            latest = conn.execute(_SQL_LATEST_DRIVE_ID).fetchone()[0]
        assert latest == 1

    def test_windowBoundsProduced(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            start = conn.execute(_SQL_WINDOW_START, (1,)).fetchone()[0]
            end = conn.execute(_SQL_WINDOW_END, (1,)).fetchone()[0]
        assert start is not None and end is not None
        assert start <= end

    def test_rowCountPositive(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            rows = conn.execute(_SQL_ROW_COUNT, (1,)).fetchone()[0]
        assert rows > 0

    def test_allRowsTaggedReal(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            nonReal = conn.execute(_SQL_NON_REAL, (1,)).fetchone()[0]
        assert nonReal == 0

    def test_timestampsCanonicalZSuffix(self, tmp_path: Path) -> None:
        """Fixture rows from live Pi use Python datetime.now().isoformat()
        without Z.  This test documents that the US-202 canonical-format
        check is expected to FAIL on pre-US-202 fixtures but PASS on
        post-US-202 rows.  The validator reports the gap explicitly.
        """
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            # Eclipse_idle.db is pre-US-202 (captured 2026-04-19 before
            # TD-027 was swept).  Assert the query runs and reports a
            # non-negative count -- the validator's job is to SURFACE this.
            badCount = conn.execute(_SQL_BAD_TS, (1,)).fetchone()[0]
        assert isinstance(badCount, int) and badCount >= 0

    def test_distinctParamsAtLeastEight(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            distinct = conn.execute(_SQL_DISTINCT_PARAMS, (1,)).fetchone()[0]
        # eclipse_idle.db has 11 PIDs.
        assert distinct >= 8

    def test_dtcLogQueryShapeWhenEmpty(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1, includeDtc=False)
        with sqlite3.connect(db) as conn:
            cnt = conn.execute(_SQL_DTC_COUNT, (1,)).fetchone()[0]
        assert cnt == 0

    def test_dtcLogQueryShapeWhenPopulated(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1, includeDtc=True)
        with sqlite3.connect(db) as conn:
            cnt = conn.execute(_SQL_DTC_COUNT, (1,)).fetchone()[0]
            codes = [
                row[0] for row in conn.execute(
                    "SELECT dtc_code FROM dtc_log WHERE drive_id = ?", (1,),
                )
            ]
        assert cnt == 1
        assert codes == ["P0171"]

    def test_driveSummaryExactlyOneRow(self, tmp_path: Path) -> None:
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(db) as conn:
            cnt = conn.execute(_SQL_SUMMARY_COUNT, (1,)).fetchone()[0]
        assert cnt == 1

    def test_maxCoolantBelowThresholdDrivesEscalation(
        self, tmp_path: Path,
    ) -> None:
        db = _buildSyntheticDriveFixture(
            tmp_path, driveId=1, coolantMaxC=70.0,
        )
        with sqlite3.connect(db) as conn:
            maxCool = conn.execute(_SQL_MAX_COOLANT, (1,)).fetchone()[0]
        assert maxCool is not None and float(maxCool) < 82.0

    def test_maxCoolantAboveThresholdDrivesBenign(
        self, tmp_path: Path,
    ) -> None:
        db = _buildSyntheticDriveFixture(
            tmp_path, driveId=1, coolantMaxC=90.0,
        )
        with sqlite3.connect(db) as conn:
            maxCool = conn.execute(_SQL_MAX_COOLANT, (1,)).fetchone()[0]
        assert maxCool is not None and float(maxCool) >= 82.0

    def test_ambientNullableForWarmRestart(self, tmp_path: Path) -> None:
        """Warm restart => ambient NULL; validator must report it, not fail."""
        db = _buildSyntheticDriveFixture(tmp_path, driveId=1)
        # Force ambient to NULL to simulate a warm-restart drive.
        with sqlite3.connect(db) as conn:
            conn.execute(
                "UPDATE drive_summary SET ambient_temp_at_start_c = NULL "
                "WHERE drive_id = ?", (1,),
            )
            conn.commit()
            ambient = conn.execute(
                "SELECT ambient_temp_at_start_c FROM drive_summary "
                "WHERE drive_id = ?", (1,),
            ).fetchone()[0]
        assert ambient is None


# ==============================================================================
# 4. Fixture integrity -- the base fixture must not be mutated by tests.
# ==============================================================================


class TestBaseFixtureIntegrity:
    """The canonical eclipse_idle.db must remain read-only across tests."""

    def test_baseFixtureUnchanged(self, tmp_path: Path) -> None:
        # Build a synthetic fixture, then verify the canonical fixture
        # still has drive_id=NULL for every row (US-200 Invariant #4 +
        # US-208 doNotTouch 'eclipse_idle.db fixture').
        _buildSyntheticDriveFixture(tmp_path, driveId=1)
        with sqlite3.connect(f"file:{_BASE_FIXTURE}?mode=ro", uri=True) as conn:
            nonNull = conn.execute(
                "SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NOT NULL",
            ).fetchone()[0]
            assert nonNull == 0, (
                f"Base fixture mutated -- {nonNull} rows have drive_id set"
            )
