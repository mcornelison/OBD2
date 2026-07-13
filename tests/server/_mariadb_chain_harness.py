################################################################################
# File Name: _mariadb_chain_harness.py (tests/server/)
# Purpose/Description: US-464 (TD-055) real-MariaDB migration-chain test harness.
#                      Reusable, importable (NOT a test file -- underscore prefix
#                      keeps pytest from collecting it) support module that lets
#                      the *real* server migration chain run unmodified against a
#                      real MariaDB 11.x, so the migration-vs-live-DB drift class
#                      (BL-019 -> BL-020 -> US-459 theater-trap -> BL-021) is
#                      caught in CI instead of one deploy at a time.
#
#                      The crux is MariaDbCommandRunner: every migration issues
#                      SQL via ctx.runner(argv, input=<sql>) and parses
#                      ``mysql -B -N`` output (tab-delimited, header-less, SQL
#                      NULL -> literal 'NULL').  This adapter pipes the input SQL
#                      into a real MariaDB (testcontainer OR a service DSN) and
#                      re-emits ``-B -N``-shaped output, so MigrationRunner.runAll
#                      + the real v0022/v0023 apply() run against real DDL --
#                      NOT SQLite/create_all, which is precisely what shipped
#                      BL-020 + BL-021 green.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (US-464) | Initial -- Sprint 57 US-464 (TD-055 graduates to
#               |              | funded; Atlas ruling + TIGHTEN-2 version pin).
# ================================================================================
################################################################################

"""Real-MariaDB migration-chain test harness (US-464 / TD-055).

Why this exists (the A-10 / TD-055 drift class, Atlas's 4th cycle)
-----------------------------------------------------------------

The server migration chain reconciles the deployed MariaDB against the ORM.
Its unit tests (``tests/server/test_migrations.py`` +
``tests/server/test_migration_0022*.py`` + ``test_migration_0023*.py``) drive a
scripted ``FakeRunner`` -- hermetic, fast, and structurally **incapable** of
reproducing MariaDB DDL semantics (1091 on ``DROP CONSTRAINT`` of an inline
CHECK; 1064 on ``DROP CHECK``; ``create_all``-vs-ORM FK-naming drift).  Four
successive deploys shipped green through that gap:

* **BL-019** -- US-424 widened the ``data_source`` enum in Python but never
  ALTERed the live DB; the stale 4-value CHECK rejected ``data_source='foreign'``.
* **BL-020** -- v0022's FK re-point fatalled on the drifted prod schema where
  ``create_all`` never auto-named the FK the ORM assumed (``drive_statistics``
  had no ``summary_id`` FK at all -- state 3).
* **US-459** -- a "green" applied-schema test that compared two equal Python
  tuples: theatre, not a real-DB probe (the theater-trap).
* **BL-021** -- v0023 dropped an **inline** CHECK with ``DROP CONSTRAINT``
  (1091) / ``DROP CHECK`` (1064); the V0.29.10 deploy stalled at v0023.

Each was caught one deploy at a time because no test ran the chain against a
**real** MariaDB.  This harness closes that: it applies the real migrations
against a real MariaDB 11.x (pinned to the prod major, 11.8.6 -- Atlas
TIGHTEN-2: a wrong-version container can green-pass a prod-failing migration)
seeded with the exact drifted historical shape, and asserts the chain fixes the
drift or fails **loudly** -- never green over a broken DB.

Acquisition + honest skip
-------------------------

:func:`acquireMariaDb` yields a real MariaDB from either (1) a service DSN in
``$OBD2_MARIADB_TEST_DSN`` (run locally against a MariaDB 11.x service) or
(2) a ``testcontainers`` MariaDB 11.x container (CI, once Docker is wired).  If
neither is reachable it raises :class:`MariaDbUnavailable` so the caller can
``pytest.skip`` with a clear reason.  That skip is **honest** (it names exactly
why + the CI-enablement follow-up); it is NOT the ``create_all`` substitution
that is the whole trap -- SQLite is never used as a stand-in here.

CI-enablement follow-up (do NOT silently skip -- documented per the AC's
conditionalOutcome): add ``testcontainers`` to a dev/CI requirements set and a
Docker-enabled CI job (or a MariaDB 11.x service container) so this suite runs
on every push.  Until then it runs locally against a MariaDB service via
``$OBD2_MARIADB_TEST_DSN`` and skips honestly elsewhere.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy.engine import make_url

from scripts.apply_server_migrations import HostAddresses, ServerCreds
from src.server.migrations.runner import (
    SCHEMA_MIGRATIONS_TABLE,
    SCHEMA_MIGRATIONS_TABLE_DDL,
    RunnerContext,
)
from src.server.migrations.versions.v0023_us458_drop_stale_data_source_check import (
    EXPECTED_STALE_CHECK_TABLES,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    'DATA_SOURCE_CHECK_TABLES',
    'MARIADB_MAJOR',
    'MARIADB_TEST_DSN_ENV',
    'MARIADB_TEST_IMAGE',
    'TD055_LINEAGE',
    'MariaDbCommandRunner',
    'MariaDbUnavailable',
    'acquireMariaDb',
    'cleanDriveIdentityStatements',
    'driftedDriveIdentityStatements',
    'execStatements',
    'formatMysqlBatchOutput',
    'inlineDataSourceCheckTableDdl',
    'makeContext',
    'markMigrationsAppliedStatements',
    'resetSchemaStatements',
]


# ================================================================================
# Version pin + acquisition constants
# ================================================================================

# Atlas TIGHTEN-2: pin the container to the PROD MariaDB major (11.x, matching
# 11.8.6).  The BL-021 quirk is MariaDB-version-sensitive; a wrong-version
# container could green-pass a prod-failing migration.
MARIADB_TEST_IMAGE: str = 'mariadb:11.8'
MARIADB_MAJOR: str = '11'
MARIADB_TEST_DSN_ENV: str = 'OBD2_MARIADB_TEST_DSN'

# The tables that carry the stale inline data_source CHECK on prod (BL-021).
# Reused from v0023 (define-once) so a future table addition tracks one source.
DATA_SOURCE_CHECK_TABLES: tuple[str, ...] = EXPECTED_STALE_CHECK_TABLES

TD055_LINEAGE: str = (
    'TD-055 lineage: BL-019 (stale data_source enum, never ALTERed) -> '
    'BL-020 (v0022 FK re-point fatalled on create_all drift) -> US-459 '
    '(tuple-compare theater-trap) -> BL-021 (inline-CHECK DROP CONSTRAINT 1091); '
    "Atlas's 4th cycle. This harness runs the real chain on real MariaDB 11.x."
)


class MariaDbUnavailable(Exception):
    """Raised when no real MariaDB 11.x can be reached (caller should skip).

    Distinct from a test failure: absence of infrastructure is an honest skip,
    NOT a green pass and NOT a fall-back to SQLite/create_all (the trap).
    """


# ================================================================================
# mysql -B -N output formatting
# ================================================================================

def formatMysqlBatchOutput(rows: Iterable[Sequence[Any]]) -> str:
    """Render DB rows the way ``mysql -B -N`` does, for the migration parsers.

    The migrations read their probe output with ``mysql``-batch semantics:
    tab-delimited fields, one row per line, NO header, and a SQL ``NULL``
    rendered as the literal token ``NULL`` (v0023's ``_noneIfSqlNull`` maps it
    back to ``None``).  Reproducing that shape lets the real ``_runServerSql``
    consumers parse a live query result unchanged.
    """
    lines: list[str] = []
    for row in rows:
        fields = ['NULL' if value is None else str(value) for value in row]
        lines.append('\t'.join(fields))
    return '\n'.join(lines)


# ================================================================================
# The CommandRunner adapter -- the crux of running the real chain on real DDL
# ================================================================================

class MariaDbCommandRunner:
    """A ``CommandRunner`` that pipes ``input`` SQL into a real MariaDB.

    The migration chain shells out via ``ctx.runner(argv, input=<sql>)`` (an
    ``ssh ... mysql -B -N`` invocation in production).  This adapter ignores the
    ssh/mysql argv wrapper and executes the ``input`` SQL against a live DB-API
    connection (pymysql -> MariaDB testcontainer / service), returning a
    :class:`subprocess.CompletedProcess` whose ``stdout`` is ``-B -N``-shaped and
    whose ``returncode`` is ``1`` on any DB error -- so every migration's
    ``if res.returncode != 0`` branch fires exactly as it would against ``mysql``.

    The wrapped connection MUST autocommit (each statement is its own unit, like
    piping to the ``mysql`` CLI); DDL is implicit-commit on MariaDB regardless.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- matches CommandRunner Protocol
        timeout: float | None = None,  # noqa: ARG002 -- part of the Protocol
    ) -> subprocess.CompletedProcess[str]:
        sql = (input or '').strip()
        if not sql:
            # e.g. loadAddresses' ``bash -c`` is never routed here; an empty
            # payload is a benign no-op with clean output.
            return subprocess.CompletedProcess(list(argv), 0, '', '')
        statement = sql.rstrip(';').strip()
        cursor = self._connection.cursor()
        try:
            cursor.execute(statement)
            if cursor.description is not None:
                stdout = formatMysqlBatchOutput(cursor.fetchall())
            else:
                stdout = ''
            return subprocess.CompletedProcess(list(argv), 0, stdout, '')
        except Exception as err:  # noqa: BLE001 -- mirror mysql's nonzero-exit
            return subprocess.CompletedProcess(list(argv), 1, '', str(err))
        finally:
            cursor.close()


def makeContext(connection: Any, dbName: str) -> RunnerContext:
    """Build a :class:`RunnerContext` that drives the real chain at ``dbName``.

    ``addrs`` is a placeholder (the adapter ignores the ssh transport);
    ``creds.dbName`` MUST equal the connected database so the migrations'
    ``information_schema`` probes (``WHERE ...SCHEMA='{dbName}'``) resolve.
    """
    return RunnerContext(
        addrs=HostAddresses(serverHost='mariadb-test', serverUser='test'),
        creds=ServerCreds(dbUser='test', dbPassword='test', dbName=dbName),
        runner=MariaDbCommandRunner(connection),
    )


# ================================================================================
# Acquisition (service DSN OR testcontainer) + honest skip
# ================================================================================

def _pymysqlConnect(url: Any) -> Any:
    """Open an autocommitting pymysql connection from a SQLAlchemy URL."""
    import pymysql  # noqa: PLC0415 -- server dep; hermetic tests never reach here

    return pymysql.connect(
        host=url.host or '127.0.0.1',
        port=url.port or 3306,
        user=url.username,
        password=url.password or '',
        database=url.database,
        autocommit=True,
    )


def _assertMariaDbMajor(connection: Any) -> None:
    """Skip (via :class:`MariaDbUnavailable`) unless the target is MariaDB 11.x.

    Atlas TIGHTEN-2: the BL-021 semantics are version-sensitive; refuse to run
    against a mismatched engine rather than risk a green pass over a
    prod-failing migration.
    """
    cursor = connection.cursor()
    try:
        cursor.execute('SELECT VERSION();')
        row = cursor.fetchone()
    finally:
        cursor.close()
    version = str(row[0]) if row else ''
    if 'mariadb' not in version.lower() or version.split('.', 1)[0] != MARIADB_MAJOR:
        raise MariaDbUnavailable(
            f'expected MariaDB {MARIADB_MAJOR}.x (prod 11.8.6) but the target '
            f'reports {version!r}; refusing to run against a mismatched engine '
            '(Atlas TIGHTEN-2: a wrong-version DB can green-pass a prod-failing '
            'migration).',
        )


@contextmanager
def acquireMariaDb() -> Iterator[tuple[Any, str]]:
    """Yield ``(connection, dbName)`` for a real MariaDB 11.x, or skip honestly.

    Order: an explicit ``$OBD2_MARIADB_TEST_DSN`` service first (local runs),
    then a ``testcontainers`` MariaDB 11.x container (CI).  Raises
    :class:`MariaDbUnavailable` when neither is reachable -- the caller skips.
    """
    dsn = os.environ.get(MARIADB_TEST_DSN_ENV)
    if dsn:
        url = make_url(dsn)
        connection = _pymysqlConnect(url)
        try:
            _assertMariaDbMajor(connection)
            yield connection, url.database
        finally:
            connection.close()
        return

    if importlib.util.find_spec('testcontainers') is None:
        raise MariaDbUnavailable(
            f'no {MARIADB_TEST_DSN_ENV} env DSN set and the "testcontainers" '
            'package is not installed; cannot reach a real MariaDB 11.x. '
            'Install testcontainers + Docker, or point '
            f'{MARIADB_TEST_DSN_ENV} at a MariaDB 11.x service. (SQLite / '
            'create_all is NOT a valid substitute -- that is the BL-019/020/021 '
            'trap this test exists to close.)',
        )

    from testcontainers.mysql import MySqlContainer  # noqa: PLC0415

    container = MySqlContainer(MARIADB_TEST_IMAGE)
    try:
        container.start()
    except Exception as err:  # noqa: BLE001 -- Docker down / image pull failure
        raise MariaDbUnavailable(
            f'the "testcontainers" package is installed but the MariaDB '
            f'{MARIADB_TEST_IMAGE} container failed to start ({err}); is Docker '
            'running?',
        ) from err
    try:
        url = make_url(container.get_connection_url())
        connection = _pymysqlConnect(url)
        try:
            _assertMariaDbMajor(connection)
            yield connection, url.database
        finally:
            connection.close()
    finally:
        container.stop()


# ================================================================================
# Seed-DDL builders (drifted historical shapes + clean shapes)
# ================================================================================

def execStatements(connection: Any, statements: Iterable[str]) -> None:
    """Execute each statement against the live connection (seed/reset helper)."""
    cursor = connection.cursor()
    try:
        for statement in statements:
            stripped = statement.strip().rstrip(';').strip()
            if stripped:
                cursor.execute(stripped)
    finally:
        cursor.close()


def inlineDataSourceCheckTableDdl(tableName: str) -> str:
    """CREATE TABLE with the BL-021 stale INLINE data_source CHECK.

    Reproduces the historical (pre-US-424) provisioning: a column-level
    ``data_source VARCHAR(16) ... CHECK (...)`` whose 4-value enum lacks
    ``'foreign'``.  MariaDB names an inline CHECK after the column
    (``CONSTRAINT_NAME == 'data_source'``), which is exactly what v0023 must
    strip via a definition-preserving MODIFY COLUMN.  The current ORM declares
    NO such CHECK, so ``create_all`` cannot produce this -- it must be seeded.
    """
    return (
        f'CREATE TABLE {tableName} ('
        '  id INT AUTO_INCREMENT PRIMARY KEY,'
        '  data_source VARCHAR(16) CHARACTER SET utf8mb4 '
        '    COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT \'real\''
        "    CHECK (data_source IN ('real','replay','physics_sim','fixture'))"
        ') ENGINE=InnoDB;'
    )


def driftedDriveIdentityStatements() -> list[str]:
    """Seed the BL-020 drifted drive-identity shape (v0022's pre-migration state).

    * ``drives`` -- canonical identity with a PRE-widen ``ck_drives_data_quality``
      CHECK (no ``'unmappable_legacy'``, so v0022 substep 1 has work to do).
    * ``drive_statistics`` -- **state 3**: ``summary_id`` with NO FK at all
      (create_all never auto-named the FK the ORM assumed -- the BL-020 fatal).
    * ``drive_derived_signals`` -- **state 1**: ``summary_id`` FK -> the LEGACY
      ``drive_summary(id)`` (the v0017-era name), which v0022 must drop + re-point.

    Seed rows keep the orphan guard at zero (every ``summary_id`` matches a
    ``drives.drive_id``) and give substep 2 exactly one NULL-natural-key legacy
    drive to re-label.
    """
    return [
        'CREATE TABLE drive_summary ('
        '  id INT AUTO_INCREMENT PRIMARY KEY,'
        '  source_device VARCHAR(64), source_id INT'
        ') ENGINE=InnoDB;',
        'CREATE TABLE drives ('
        '  drive_id INT AUTO_INCREMENT PRIMARY KEY,'
        '  source_device VARCHAR(64), source_drive_id INT NULL,'
        '  start_time DATETIME NULL, end_time DATETIME NULL,'
        "  data_source VARCHAR(16) DEFAULT 'real',"
        "  data_quality VARCHAR(32) NOT NULL DEFAULT 'full',"
        "  CONSTRAINT ck_drives_data_quality CHECK (data_quality IN ('full'))"
        ') ENGINE=InnoDB;',
        'CREATE TABLE drive_statistics ('
        '  summary_id INT NOT NULL, parameter_name VARCHAR(64) NOT NULL,'
        '  sample_count INT NOT NULL DEFAULT 0,'
        "  data_quality VARCHAR(32) NOT NULL DEFAULT 'full',"
        '  PRIMARY KEY (summary_id, parameter_name)'
        ') ENGINE=InnoDB;',
        'CREATE TABLE drive_derived_signals ('
        '  summary_id INT NOT NULL PRIMARY KEY,'
        '  CONSTRAINT fk_drive_derived_signals_summary'
        '    FOREIGN KEY (summary_id) REFERENCES drive_summary(id) ON DELETE CASCADE'
        ') ENGINE=InnoDB;',
        "INSERT INTO drive_summary (id, source_device, source_id) "
        "VALUES (1, 'chi-eclipse-01', 1);",
        'INSERT INTO drives (drive_id, source_device, source_drive_id, data_quality) '
        "VALUES (1, 'chi-eclipse-01', 100, 'full');",
        'INSERT INTO drives (drive_id, source_device, source_drive_id, data_quality) '
        "VALUES (2, 'chi-eclipse-01', NULL, 'full');",
        'INSERT INTO drive_statistics (summary_id, parameter_name, sample_count) '
        "VALUES (1, 'RPM', 100);",
        'INSERT INTO drive_derived_signals (summary_id) VALUES (1);',
    ]


def cleanDriveIdentityStatements() -> list[str]:
    """Seed the already-collapsed (post-v0022) clean drive-identity shape.

    Both ``summary_id`` FKs already reference ``drives.drive_id`` and the
    ``ck_drives_data_quality`` CHECK is already widened -- so v0022 is a no-op
    (state 2 everywhere).  Used to assert the clean-schema case
    (validationCriterion 2): the chain applies + passes with no changes.
    """
    return [
        'CREATE TABLE drive_summary ('
        '  id INT AUTO_INCREMENT PRIMARY KEY,'
        '  source_device VARCHAR(64), source_id INT'
        ') ENGINE=InnoDB;',
        'CREATE TABLE drives ('
        '  drive_id INT AUTO_INCREMENT PRIMARY KEY,'
        '  source_device VARCHAR(64), source_drive_id INT NULL,'
        '  start_time DATETIME NULL, end_time DATETIME NULL,'
        "  data_source VARCHAR(16) DEFAULT 'real',"
        "  data_quality VARCHAR(32) NOT NULL DEFAULT 'full',"
        '  CONSTRAINT ck_drives_data_quality CHECK '
        "    (data_quality IN ('full','unmappable_legacy'))"
        ') ENGINE=InnoDB;',
        'CREATE TABLE drive_statistics ('
        '  summary_id INT NOT NULL, parameter_name VARCHAR(64) NOT NULL,'
        '  sample_count INT NOT NULL DEFAULT 0,'
        "  data_quality VARCHAR(32) NOT NULL DEFAULT 'full',"
        '  PRIMARY KEY (summary_id, parameter_name),'
        '  CONSTRAINT fk_drive_statistics_drives'
        '    FOREIGN KEY (summary_id) REFERENCES drives(drive_id) ON DELETE CASCADE'
        ') ENGINE=InnoDB;',
        'CREATE TABLE drive_derived_signals ('
        '  summary_id INT NOT NULL PRIMARY KEY,'
        '  CONSTRAINT fk_drive_derived_signals_drives'
        '    FOREIGN KEY (summary_id) REFERENCES drives(drive_id) ON DELETE CASCADE'
        ') ENGINE=InnoDB;',
        'INSERT INTO drives (drive_id, source_device, source_drive_id, data_quality) '
        "VALUES (1, 'chi-eclipse-01', 100, 'full');",
        'INSERT INTO drive_statistics (summary_id, parameter_name, sample_count) '
        "VALUES (1, 'RPM', 100);",
        'INSERT INTO drive_derived_signals (summary_id) VALUES (1);',
    ]


def markMigrationsAppliedStatements(versions: Iterable[str]) -> list[str]:
    """Create ``schema_migrations`` + record ``versions`` as already applied.

    Lets a test present the runner with a partially-migrated ledger so
    ``runAll`` plans only the pending tail (e.g. the V0.29.10 resume where
    0001-0021 were applied and 0022/0023 are pending).
    """
    statements = [SCHEMA_MIGRATIONS_TABLE_DDL + ';']
    for version in versions:
        statements.append(
            f'INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (version, description) '
            f"VALUES ('{version}', 'seeded-applied');",
        )
    return statements


def resetSchemaStatements() -> list[str]:
    """DROP every table this harness seeds, so each test starts on a clean DB."""
    tables = [
        'drive_derived_signals',
        'drive_statistics',
        'drive_summary',
        'drives',
        SCHEMA_MIGRATIONS_TABLE,
        *DATA_SOURCE_CHECK_TABLES,
    ]
    statements = ['SET FOREIGN_KEY_CHECKS=0;']
    statements.extend(f'DROP TABLE IF EXISTS {table};' for table in tables)
    statements.append('SET FOREIGN_KEY_CHECKS=1;')
    return statements
