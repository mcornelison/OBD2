################################################################################
# File Name: test_migration_chain_real_mariadb.py (tests/server/)
# Purpose/Description: US-464 (TD-055) -- a test that applies the FULL pending
#                      server migration chain against a REAL MariaDB 11.x (NOT
#                      SQLite/create_all), so the migration-vs-live-DB drift
#                      class (BL-019 -> BL-020 -> US-459 theater-trap -> BL-021,
#                      Atlas's 4th cycle) is caught in CI instead of one deploy
#                      at a time.
#
#                      Two layers (mirrors US-462's proven pattern):
#                        (1) HERMETIC, always-runs -- proves the harness's
#                            machinery: the mysql -B -N output formatter, the
#                            MariaDbCommandRunner adapter over a fake DB-API
#                            connection, the honest-skip acquisition, and the
#                            drifted-seed DDL shape.  Tests the ALARM, not a DB.
#                        (2) LIVE integration -- @pytest.mark.integration|slow;
#                            seeds the exact drifted shape on a real MariaDB and
#                            runs the real v0022/v0023 + MigrationRunner.runAll,
#                            asserting the chain fixes the drift or fails LOUDLY
#                            (never green over a broken DB).  Skips honestly when
#                            no MariaDB is reachable (no testcontainers + no
#                            $OBD2_MARIADB_TEST_DSN) -- NOT a create_all fallback.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (US-464) | Initial -- Sprint 57 US-464 (TD-055 funded).
# ================================================================================
################################################################################

"""US-464 / TD-055 -- real-MariaDB migration-chain test (both drift classes)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

pytest.importorskip("sqlalchemy")

from src.server.migrations import (  # noqa: E402
    ALL_MIGRATIONS,
    MigrationRunner,
)
from src.server.migrations.versions import (  # noqa: E402
    v0022_us451_drive_identity_collapse as v0022,
)
from src.server.migrations.versions import (  # noqa: E402
    v0023_us458_drop_stale_data_source_check as v0023,
)
from tests.server._mariadb_chain_harness import (  # noqa: E402
    DATA_SOURCE_CHECK_TABLES,
    MARIADB_MAJOR,
    MARIADB_TEST_DSN_ENV,
    MARIADB_TEST_IMAGE,
    MariaDbCommandRunner,
    MariaDbUnavailable,
    acquireMariaDb,
    cleanDriveIdentityStatements,
    driftedDriveIdentityStatements,
    execStatements,
    formatMysqlBatchOutput,
    inlineDataSourceCheckTableDdl,
    makeContext,
    markMigrationsAppliedStatements,
    resetSchemaStatements,
)

# =============================================================================
# LAYER 1 -- HERMETIC (always runs): proves the harness machinery, no DB
# =============================================================================


class _FakeCursor:
    """Scripted DB-API cursor: match a SQL substring -> (description, rows) | Exc."""

    def __init__(self, script: dict[str, Any]) -> None:
        self._script = script
        self.description: list[tuple] | None = None
        self._rows: list[tuple] = []

    def execute(self, sql: str) -> None:
        self.description = None
        self._rows = []
        for needle, outcome in self._script.items():
            if needle in sql:
                if isinstance(outcome, Exception):
                    raise outcome
                self.description, self._rows = outcome
                return

    def fetchall(self) -> list[tuple]:
        return self._rows

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def close(self) -> None:
        return None


class _FakeConn:
    def __init__(self, script: dict[str, Any] | None = None) -> None:
        self._script = script or {}

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._script)


class TestBatchOutputFormat:
    """formatMysqlBatchOutput must match ``mysql -B -N`` for the real parsers."""

    def test_tab_delimited_no_header(self):
        out = formatMysqlBatchOutput([("realtime_data", "data_source")])
        assert out == "realtime_data\tdata_source"

    def test_multi_row_newline_separated(self):
        out = formatMysqlBatchOutput([("a", "b"), ("c", "d")])
        assert out == "a\tb\nc\td"

    def test_sql_null_renders_as_literal_NULL(self):
        # v0023's _noneIfSqlNull maps the token 'NULL' back to None -- so a NULL
        # collation/default MUST come across as the literal token, not ''.
        out = formatMysqlBatchOutput([("varchar(16)", None, "utf8mb4_unicode_ci")])
        assert out == "varchar(16)\tNULL\tutf8mb4_unicode_ci"

    def test_empty_result_is_empty_string(self):
        assert formatMysqlBatchOutput([]) == ""


class TestMariaDbCommandRunnerHermetic:
    """The adapter turns a DB-API result into a CompletedProcess the chain reads."""

    def test_select_returns_batch_formatted_stdout(self):
        runner = MariaDbCommandRunner(
            _FakeConn({"SELECT TABLE_NAME": ([("t",)], [("statistics", "data_source")])}),
        )
        res = runner(["ssh", "x"], input="SELECT TABLE_NAME, CONSTRAINT_NAME ...;")
        assert res.returncode == 0
        assert res.stdout == "statistics\tdata_source"

    def test_ddl_without_result_set_yields_empty_stdout(self):
        runner = MariaDbCommandRunner(_FakeConn())
        res = runner(["ssh", "x"], input="ALTER TABLE statistics MODIFY COLUMN ...;")
        assert res.returncode == 0
        assert res.stdout == ""

    def test_db_error_maps_to_nonzero_returncode(self):
        # A real 1091/1064 raises in pymysql; the adapter must surface it as a
        # nonzero exit so every migration's `if res.returncode != 0` branch fires.
        runner = MariaDbCommandRunner(
            _FakeConn({"DROP CONSTRAINT": RuntimeError("(1091, \"Can't DROP\")")}),
        )
        res = runner(["ssh", "x"], input="ALTER TABLE t DROP CONSTRAINT data_source;")
        assert res.returncode == 1
        assert "1091" in res.stderr

    def test_empty_input_is_clean_noop(self):
        res = MariaDbCommandRunner(_FakeConn())(["bash", "-c", "true"], input=None)
        assert res.returncode == 0
        assert res.stdout == ""

    def test_is_a_completed_process(self):
        res = MariaDbCommandRunner(_FakeConn())(["x"], input="SELECT 1;")
        assert isinstance(res, subprocess.CompletedProcess)


class TestAcquireHonestSkip:
    """With no service DSN and no testcontainers, acquisition skips HONESTLY."""

    def test_raises_mariadb_unavailable_naming_both_paths(self, monkeypatch):
        monkeypatch.delenv(MARIADB_TEST_DSN_ENV, raising=False)
        # testcontainers is genuinely absent on the dev bench; assert the raise
        # names both acquisition paths + refuses the create_all substitute.
        with pytest.raises(MariaDbUnavailable) as excInfo:
            with acquireMariaDb():
                pass
        msg = str(excInfo.value)
        assert MARIADB_TEST_DSN_ENV in msg
        assert "testcontainers" in msg
        assert "create_all" in msg  # explicitly refuses the trap


class TestSeedDdlShape:
    """The drifted seeders reproduce the exact BL-020 / BL-021 shapes."""

    def test_inline_check_is_column_level_and_missing_foreign(self):
        ddl = inlineDataSourceCheckTableDdl("realtime_data")
        assert "CREATE TABLE realtime_data" in ddl
        # Inline (column-level) CHECK -> MariaDB names it after the column.
        assert "CHECK (data_source IN ('real','replay','physics_sim','fixture'))" in ddl
        assert "foreign" not in ddl  # the stale 4-value enum (BL-019/BL-021)
        # Collation preserved shape -- a bare MODIFY would reset it (BL-021).
        assert "utf8mb4_unicode_ci" in ddl

    def test_drifted_identity_has_state3_stats_and_state1_derived(self):
        stmts = " ".join(driftedDriveIdentityStatements())
        # drive_statistics -- state 3: NO summary_id FK (the BL-020 fatal shape).
        assert "CREATE TABLE drive_statistics" in stmts
        assert "fk_drive_statistics" not in stmts
        # drive_derived_signals -- state 1: FK -> the LEGACY drive_summary(id).
        assert "fk_drive_derived_signals_summary" in stmts
        assert "REFERENCES drive_summary(id)" in stmts
        # Pre-widen drives CHECK -- no 'unmappable_legacy' yet (v0022 substep 1).
        assert "unmappable_legacy" not in stmts

    def test_clean_identity_points_both_fks_at_drives(self):
        stmts = " ".join(cleanDriveIdentityStatements())
        assert "fk_drive_statistics_drives" in stmts
        assert "fk_drive_derived_signals_drives" in stmts
        assert "unmappable_legacy" in stmts  # already widened -> v0022 no-op

    def test_mark_applied_builds_ledger_rows(self):
        stmts = markMigrationsAppliedStatements(["0001", "0002"])
        joined = " ".join(stmts)
        assert "CREATE TABLE IF NOT EXISTS schema_migrations" in joined
        assert "'0001'" in joined and "'0002'" in joined


class TestTd055LineageDocumented:
    """Pin the TD-055 lineage + version pin so the gap stays visible (AC)."""

    def test_harness_documents_lineage_and_version_pin(self):
        from tests.server import _mariadb_chain_harness as harness

        doc = harness.__doc__ or ""
        for token in ("BL-019", "BL-020", "BL-021", "US-459", "TD-055"):
            assert token in doc, f"harness docstring must cite {token}"
        # Atlas TIGHTEN-2 version pin lives in a constant, not a magic literal.
        assert MARIADB_TEST_IMAGE.startswith(f"mariadb:{MARIADB_MAJOR}")

    def test_module_documents_ci_enablement_followup(self):
        from tests.server import _mariadb_chain_harness as harness

        doc = harness.__doc__ or ""
        # conditionalOutcome: do NOT silently skip -- document the CI follow-up.
        assert "CI-enablement follow-up" in doc


# =============================================================================
# LAYER 2 -- LIVE (real MariaDB 11.x): the real acceptance; skips honestly
# =============================================================================

@pytest.fixture(scope="module")
def _mariaDb():
    """Acquire a real MariaDB 11.x for the module, or skip the live layer."""
    try:
        with acquireMariaDb() as db:
            yield db
    except MariaDbUnavailable as err:
        pytest.skip(f"real MariaDB unavailable (honest skip, NOT create_all): {err}")


@pytest.fixture
def liveDb(_mariaDb):
    """A clean real-MariaDB per test: reset the harness-owned tables first."""
    connection, dbName = _mariaDb
    execStatements(connection, resetSchemaStatements())
    return connection, dbName


def _foreignInsertRejected(connection: Any, table: str) -> bool:
    """True if ``data_source='foreign'`` is rejected by ``table`` (CHECK present)."""
    cursor = connection.cursor()
    try:
        cursor.execute(f"INSERT INTO {table} (data_source) VALUES ('foreign')")
    except Exception:  # noqa: BLE001 -- CHECK violation is the signal
        return True
    else:
        return False
    finally:
        cursor.close()


def _countSurvivingDataSourceChecks(connection: Any, dbName: str) -> int:
    """Run v0023's own discovery query -> count surviving data_source CHECKs."""
    cursor = connection.cursor()
    try:
        cursor.execute(v0023.discoverDataSourceCheckSql(dbName).rstrip(";"))
        return len(cursor.fetchall())
    finally:
        cursor.close()


@pytest.mark.integration
@pytest.mark.slow
class TestMigrationChainRealMariaDb:
    """The chain applies the real DDL on real MariaDB -- catches both classes."""

    def test_bl021_inline_check_stripped_and_foreign_accepted(self, liveDb):
        """BL-021: v0023 strips the inline data_source CHECK via MODIFY COLUMN."""
        connection, dbName = liveDb
        execStatements(
            connection,
            [inlineDataSourceCheckTableDdl(t) for t in DATA_SOURCE_CHECK_TABLES],
        )
        # Drift present pre-migration -- the CHECK rejects 'foreign' (fails loud).
        assert _foreignInsertRejected(connection, "realtime_data"), (
            "seed drift breached: the stale inline CHECK did not reject 'foreign' "
            "-- the BL-021 reproducer is not in place"
        )
        assert _countSurvivingDataSourceChecks(connection, dbName) == len(
            DATA_SOURCE_CHECK_TABLES,
        )

        v0023.apply(makeContext(connection, dbName))

        # Post-migration: every inline CHECK stripped; 'foreign' now accepted.
        assert _countSurvivingDataSourceChecks(connection, dbName) == 0
        assert not _foreignInsertRejected(connection, "statistics"), (
            "v0023 ran but data_source='foreign' is still rejected -- the inline "
            "CHECK survived (old DROP CONSTRAINT would 1091 here; that is the bug "
            "this real-MariaDB test catches that SQLite/create_all could not)"
        )

    def test_bl020_summary_id_fks_repointed_to_drives(self, liveDb):
        """BL-020: v0022 re-points both summary_id FKs onto drives.drive_id."""
        connection, dbName = liveDb
        execStatements(connection, driftedDriveIdentityStatements())
        ctx = makeContext(connection, dbName)

        v0022.apply(ctx)

        # Both collapse tables now reference drives (state-3 ADD + state-1 re-point).
        assert v0022._fkNameReferencing(ctx, "drive_statistics", "drives") is not None
        assert (
            v0022._fkNameReferencing(ctx, "drive_derived_signals", "drives")
            is not None
        )
        # The stale FK -> drive_summary is gone (state-1 drop landed).
        assert (
            v0022._fkNameReferencing(ctx, "drive_derived_signals", "drive_summary")
            is None
        )

    def test_full_pending_chain_resume_fixes_both_classes(self, liveDb):
        """runAll on the drifted resume-deploy applies 0022+0023 + fixes both."""
        connection, dbName = liveDb
        execStatements(connection, driftedDriveIdentityStatements())
        execStatements(
            connection,
            [inlineDataSourceCheckTableDdl(t) for t in DATA_SOURCE_CHECK_TABLES],
        )
        # Mirror the V0.29.10 resume: 0001-0021 already applied, 0022/0023 pending.
        priorVersions = [m.version for m in ALL_MIGRATIONS if m.version < "0022"]
        execStatements(connection, markMigrationsAppliedStatements(priorVersions))
        ctx = makeContext(connection, dbName)

        report = MigrationRunner(ALL_MIGRATIONS).runAll(ctx)

        assert {"0022", "0023"}.issubset(set(report.applied)), (
            f"expected 0022+0023 to apply on the pending chain; got {report.applied}"
        )
        # Both drift classes reconciled by the real chain.
        assert _countSurvivingDataSourceChecks(connection, dbName) == 0
        assert v0022._fkNameReferencing(ctx, "drive_statistics", "drives") is not None
        assert not _foreignInsertRejected(connection, "realtime_data")

    def test_clean_schema_chain_applies_and_passes(self, liveDb):
        """validationCriterion 2: on a clean/expected schema the chain passes."""
        connection, dbName = liveDb
        execStatements(connection, cleanDriveIdentityStatements())
        # data_source tables WITHOUT the stale CHECK -> v0023 is a genuine no-op.
        execStatements(
            connection,
            [
                f"CREATE TABLE {t} (id INT AUTO_INCREMENT PRIMARY KEY, "
                f"data_source VARCHAR(16) NOT NULL DEFAULT 'real')"
                for t in DATA_SOURCE_CHECK_TABLES
            ],
        )
        priorVersions = [m.version for m in ALL_MIGRATIONS if m.version < "0022"]
        execStatements(connection, markMigrationsAppliedStatements(priorVersions))
        ctx = makeContext(connection, dbName)

        # Must NOT raise (idempotent no-op reconciliation on an already-clean DB).
        report = MigrationRunner(ALL_MIGRATIONS).runAll(ctx)

        assert {"0022", "0023"}.issubset(set(report.applied))
        assert _countSurvivingDataSourceChecks(connection, dbName) == 0
        assert v0022._fkNameReferencing(ctx, "drive_statistics", "drives") is not None
