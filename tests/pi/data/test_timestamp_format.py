################################################################################
# File Name: test_timestamp_format.py
# Purpose/Description: Integration tests asserting canonical ISO-8601 UTC
#                      timestamps in Pi capture tables (connection_log,
#                      alert_log, battery_log, power_log, realtime_data,
#                      statistics) post-US-202 (TD-027 fix) and US-203
#                      (TD-027 sweep of 8 additional naive-timestamp writers).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-202 (TD-027 fix)
# 2026-04-19    | Rex          | US-203: extended with TestExplicitPathWriters
#                               covering the 8 additional capture-table writers
#                               (power_db x3, data logger/helpers, analysis
#                               engine _storeStatistics, alert manager, battery
#                               monitor _logToDatabase).
# ================================================================================
################################################################################

"""Schema-level timestamp format tests.

Validates that the post-US-202 schema DEFAULT clauses on capture tables
produce canonical ISO-8601 UTC strings (`%Y-%m-%dT%H:%M:%SZ`), AND that
every explicit-Python write path produces the identical shape.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

import pytest

from src.common.time.helper import CANONICAL_ISO_REGEX, utcIsoNow
from src.pi.obdii.database_schema import ALL_SCHEMAS

_CANONICAL_RE = re.compile(CANONICAL_ISO_REGEX)

# Tables whose `timestamp` (or `analysis_date`) column the TD-027 fix
# normalizes to canonical ISO-8601 UTC.
_CAPTURE_TABLES_WITH_DEFAULT = [
    ('connection_log', 'timestamp'),
    ('alert_log', 'timestamp'),
    ('battery_log', 'timestamp'),
    ('power_log', 'timestamp'),
]


@pytest.fixture
def freshDb() -> sqlite3.Connection:
    """In-memory sqlite3 with the full Pi schema applied.  Caller owns close."""
    conn = sqlite3.connect(':memory:')
    for _name, ddl in ALL_SCHEMAS:
        conn.executescript(ddl)
    conn.commit()
    return conn


class TestDefaultProducesCanonicalFormat:
    """DEFAULT expressions on capture tables produce canonical format."""

    @pytest.mark.parametrize('table,column', _CAPTURE_TABLES_WITH_DEFAULT)
    def test_defaultTimestamp_isCanonicalIsoUtc(
        self, freshDb: sqlite3.Connection, table: str, column: str
    ) -> None:
        """
        Given: a capture table with DEFAULT (strftime(...)) on `timestamp`
        When: a row is inserted without naming the timestamp column
        Then: the stored value matches the canonical ISO-8601 UTC regex.
        """
        # Seed minimal required columns to satisfy NOT NULL constraints.
        insertSql = _minimalInsert(table)
        freshDb.execute(insertSql)
        freshDb.commit()

        row = freshDb.execute(
            f"SELECT {column} FROM {table} ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

        assert row is not None, f"no row found in {table}"
        storedValue = row[0]

        assert _CANONICAL_RE.match(storedValue), (
            f"{table}.{column} DEFAULT produced {storedValue!r}, which does "
            f"not match canonical regex {CANONICAL_ISO_REGEX!r}"
        )

    def test_noCaptureTableRetainsOldCurrentTimestampDefault(self) -> None:
        """
        Given: the database_schema.py module source
        When: scanning every capture-table SCHEMA_* string
        Then: none retain the old `DEFAULT CURRENT_TIMESTAMP` pattern on a
              non-audit timestamp column.

        This is a belt-and-braces check: even if the DDL compiled, a
        regression that flipped one schema back to CURRENT_TIMESTAMP would
        re-introduce the TD-027 bug on that table.
        """
        from src.pi.obdii import database_schema as schemaModule

        captureTableAttrs = {
            'SCHEMA_CONNECTION_LOG',
            'SCHEMA_ALERT_LOG',
            'SCHEMA_BATTERY_LOG',
            'SCHEMA_POWER_LOG',
        }

        for attr in captureTableAttrs:
            ddl = getattr(schemaModule, attr)
            # The `timestamp` column on capture tables must NOT use the old
            # default.  We intentionally allow `DEFAULT CURRENT_TIMESTAMP`
            # on audit columns (created_at / updated_at) on non-capture
            # tables; that is out of scope for US-202.
            firstTimestampLine = _extractTimestampColumnLine(ddl)
            assert 'CURRENT_TIMESTAMP' not in firstTimestampLine, (
                f"{attr} still uses CURRENT_TIMESTAMP on its timestamp "
                f"column: {firstTimestampLine!r}"
            )


class TestExplicitInsertMatchesDefault:
    """Explicit Python inserts via utcIsoNow() produce the same shape as DEFAULT."""

    def test_explicitInsertMatchesDefaultShape(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """
        Given: one row inserted via DEFAULT (no timestamp column named) and
               another row inserted with an explicit utcIsoNow() value
        When: both are read back
        Then: both match the canonical regex -- same shape.
        """
        # DEFAULT-path row.
        freshDb.execute(
            "INSERT INTO connection_log (event_type, success) "
            "VALUES ('default_path', 1)"
        )

        # Explicit-path row.
        explicit = utcIsoNow()
        freshDb.execute(
            "INSERT INTO connection_log (timestamp, event_type, success) "
            "VALUES (?, 'explicit_path', 1)",
            (explicit,),
        )
        freshDb.commit()

        rows = freshDb.execute(
            "SELECT event_type, timestamp FROM connection_log ORDER BY rowid"
        ).fetchall()
        assert len(rows) == 2

        for eventType, ts in rows:
            assert _CANONICAL_RE.match(ts), (
                f"{eventType} row timestamp {ts!r} does not match "
                f"canonical regex"
            )


class TestNoCurrentTimestampInCaptureSchemas:
    """No capture-table timestamp column references CURRENT_TIMESTAMP anymore."""

    def test_noCurrentTimestampInConnectionLogTimestamp(self) -> None:
        from src.pi.obdii import database_schema as schemaModule

        ddl = schemaModule.SCHEMA_CONNECTION_LOG
        timestampLine = _extractTimestampColumnLine(ddl)

        assert 'strftime' in timestampLine or '%Y-%m-%dT' in timestampLine, (
            f"connection_log.timestamp DEFAULT should use strftime form; "
            f"got: {timestampLine!r}"
        )


class TestBackwardCompatibility:
    """DEFAULT change must remain idempotent -- re-running schema is a no-op."""

    def test_schemaIdempotent_secondExecuteDoesNotRaise(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """CREATE TABLE IF NOT EXISTS means running ALL_SCHEMAS twice is safe."""
        for _name, ddl in ALL_SCHEMAS:
            freshDb.executescript(ddl)
        freshDb.commit()  # no exception = pass


class TestUtcIsoNowViaSchema:
    """Sanity: a canonical-format value stored and round-tripped is consistent."""

    def test_storedValueParsesBackAsUtc(
        self, freshDb: sqlite3.Connection
    ) -> None:
        freshDb.execute(
            "INSERT INTO connection_log (event_type, success) "
            "VALUES ('probe', 0)"
        )
        freshDb.commit()

        stored = freshDb.execute(
            "SELECT timestamp FROM connection_log ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]

        parsed = datetime.fromisoformat(stored.replace('Z', '+00:00'))
        assert parsed.utcoffset().total_seconds() == 0

        # Within 60s of wall-clock "now" in UTC.
        assert abs((datetime.now(UTC) - parsed).total_seconds()) < 60


# ================================================================================
# Helpers
# ================================================================================

def _minimalInsert(table: str) -> str:
    """Return a minimal `INSERT INTO <table>` that relies on the DEFAULT
    timestamp and satisfies the table's NOT NULL constraints.

    Only covers the four capture tables in this test module's scope.
    """
    if table == 'connection_log':
        return "INSERT INTO connection_log (event_type, success) VALUES ('probe', 0)"
    if table == 'alert_log':
        return (
            "INSERT INTO alert_log "
            "(alert_type, parameter_name, value, threshold) "
            "VALUES ('probe', 'rpm', 0.0, 0.0)"
        )
    if table == 'battery_log':
        return (
            "INSERT INTO battery_log (event_type, voltage) "
            "VALUES ('probe', 0.0)"
        )
    if table == 'power_log':
        return (
            "INSERT INTO power_log (event_type, power_source) "
            "VALUES ('probe', 'ac')"
        )
    raise ValueError(f"unhandled table {table!r} in _minimalInsert")


def _extractTimestampColumnLine(ddl: str) -> str:
    """Return the `timestamp` column declaration, flattened across lines.

    Column declarations in the Pi schema span multiple lines (the DEFAULT
    clause sits on its own continuation line).  This helper stitches the
    column's declaration back into one string up to the terminating comma
    so regression checks can scan for CURRENT_TIMESTAMP / strftime in a
    single substring test.
    """
    lines = ddl.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('timestamp '):
            # Consume continuation lines until we hit a comma (end of column
            # definition) or a closing paren.
            parts: list[str] = [stripped]
            for follow in lines[idx + 1:]:
                parts.append(follow.strip())
                if follow.rstrip().endswith(',') or follow.strip() == ');':
                    break
            return ' '.join(parts)
    raise ValueError(f"no 'timestamp' column line found in DDL:\n{ddl}")


# ================================================================================
# US-203 -- explicit-path writer tests
# ================================================================================
#
# US-202 (TD-027 fix) established the canonical ISO-8601 UTC format via the
# schema DEFAULT + utcIsoNow helper.  stopCondition #4 of that story surfaced
# 8 additional capture-table writers that pass naive `datetime.now()` values
# into INSERTs (bypassing the DEFAULT path).  US-203 routes every one of them
# through utcIsoNow at the DB-write boundary.  These tests land the assertion
# that each such writer produces canonical format.


class _FakeDatabase:
    """Minimal stand-in for ``ObdDatabase`` used by capture-write tests.

    The production class exposes ``connect()`` returning a context-managed
    :class:`sqlite3.Connection`.  Writer functions under test call into that
    API and expect the connection to behave like the real DB.  Tests prefer
    an in-memory connection they can inspect after the write, so this fake
    yields the SAME connection on every ``connect()`` call and suppresses
    the implicit close so the test body can run its own SELECTs.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def connect(self) -> _FakeDatabase._PersistentContext:
        return self._PersistentContext(self._conn)

    class _PersistentContext:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def __enter__(self) -> sqlite3.Connection:
            return self._conn

        def __exit__(self, *_args: Any) -> None:
            # Commit so the test body can SELECT the inserted row via the
            # same connection, but never close -- tests own the lifetime.
            self._conn.commit()


class TestExplicitPathWriters:
    """US-203: every non-DEFAULT capture-table writer stores canonical format.

    Each test constructs a minimal invocation of the production writer
    against an in-memory SQLite database whose schema is the exact Pi
    production schema (``ALL_SCHEMAS``).  The test then SELECTs the
    row back and asserts that the stored timestamp matches the
    canonical regex.  Failure of any of these tests is a regression of
    the TD-027 invariant that every capture-table row carries canonical
    ISO-8601 UTC.
    """

    def test_powerDb_logPowerReading_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``logPowerReading`` (power_log -- ambiguous #7 in US-202 audit)."""
        from src.pi.power.power_db import logPowerReading
        from src.pi.power.types import PowerReading, PowerSource

        reading = PowerReading(
            powerSource=PowerSource.AC_POWER, onAcPower=True
        )
        logPowerReading(_FakeDatabase(freshDb), reading, 'ac_power')

        stored = freshDb.execute(
            'SELECT timestamp FROM power_log ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'logPowerReading stored {stored!r}, not canonical'
        )

    def test_powerDb_logPowerTransition_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``logPowerTransition`` (power_log -- ambiguous #8 in US-202 audit).

        Even when the caller passes a naive local-time datetime (the very
        thing TD-027 Thread 2 documented), the stored row must be canonical.
        """
        from src.pi.power.power_db import logPowerTransition
        from src.pi.power.types import PowerSource

        # Pass an intentionally naive datetime -- the boundary must coerce.
        naiveLocal = datetime(2026, 4, 19, 7, 18, 50)
        logPowerTransition(
            _FakeDatabase(freshDb),
            'transition_to_battery',
            naiveLocal,
            PowerSource.BATTERY,
        )

        stored = freshDb.execute(
            'SELECT timestamp FROM power_log ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'logPowerTransition stored {stored!r}, not canonical'
        )

    def test_powerDb_logPowerSavingEvent_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``logPowerSavingEvent`` (power_log -- confirmed #1 in audit)."""
        from src.pi.power.power_db import logPowerSavingEvent
        from src.pi.power.types import PowerSource

        logPowerSavingEvent(
            _FakeDatabase(freshDb),
            'power_saving_enabled',
            PowerSource.BATTERY,
        )

        stored = freshDb.execute(
            'SELECT timestamp FROM power_log ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'logPowerSavingEvent stored {stored!r}, not canonical'
        )

    def test_dataLogger_logReading_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``ObdDataLogger.logReading`` (realtime_data -- confirmed #2)."""
        from src.pi.obdii.data.logger import ObdDataLogger
        from src.pi.obdii.data.types import LoggedReading

        dbLogger = ObdDataLogger(
            connection=None, database=_FakeDatabase(freshDb), profileId=None
        )
        # Naive local-time reading -- must be coerced at insert boundary.
        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            unit='rpm',
            timestamp=datetime(2026, 4, 19, 7, 18, 50),
            profileId=None,
        )
        dbLogger.logReading(reading)

        stored = freshDb.execute(
            'SELECT timestamp FROM realtime_data ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'ObdDataLogger.logReading stored {stored!r}, not canonical'
        )

    def test_helpers_logReading_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``helpers.logReading`` (realtime_data -- confirmed #3)."""
        from src.pi.obdii.data.helpers import logReading
        from src.pi.obdii.data.types import LoggedReading

        reading = LoggedReading(
            parameterName='COOLANT_TEMP',
            value=90.0,
            unit='C',
            timestamp=datetime(2026, 4, 19, 7, 18, 50),
            profileId=None,
        )
        logReading(_FakeDatabase(freshDb), reading)

        stored = freshDb.execute(
            'SELECT timestamp FROM realtime_data ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'helpers.logReading stored {stored!r}, not canonical'
        )

    def test_analysisEngine_storeStatistics_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``StatisticsEngine._storeStatistics`` (statistics -- confirmed #4)."""
        from common.analysis.types import AnalysisResult, ParameterStatistics
        from src.pi.analysis.engine import StatisticsEngine

        engine = StatisticsEngine(_FakeDatabase(freshDb), config={})
        # analysisDate must be tz-aware post-US-203 so toCanonicalIso accepts it.
        analysisDate = datetime.now(UTC)
        result = AnalysisResult(
            analysisDate=analysisDate, profileId='test', success=True
        )
        result.parameterStats['RPM'] = ParameterStatistics(
            parameterName='RPM',
            analysisDate=analysisDate,
            profileId='test',
            maxValue=5000.0,
            minValue=800.0,
            avgValue=2000.0,
            modeValue=800.0,
            std1=300.0,
            std2=600.0,
            outlierMin=None,
            outlierMax=None,
            sampleCount=10,
        )
        engine._storeStatistics(result)

        stored = freshDb.execute(
            'SELECT analysis_date FROM statistics ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'StatisticsEngine._storeStatistics stored {stored!r}, not canonical'
        )

    def test_alertManager_logAlert_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``AlertManager._logAlertToDatabase`` (alert_log -- confirmed #5)."""
        from src.pi.alert.manager import AlertManager
        from src.pi.alert.types import AlertEvent

        manager = AlertManager(database=_FakeDatabase(freshDb))
        event = AlertEvent(
            alertType='rpm_redline',
            parameterName='RPM',
            value=7500.0,
            threshold=7000.0,
            profileId='daily',
            # Intentionally naive -- must be coerced at insert boundary.
            timestamp=datetime(2026, 4, 19, 7, 18, 50),
        )
        manager._logAlertToDatabase(event)

        stored = freshDb.execute(
            'SELECT timestamp FROM alert_log ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'AlertManager._logAlertToDatabase stored {stored!r}, not canonical'
        )

    def test_batteryMonitor_logToDatabase_writesCanonical(
        self, freshDb: sqlite3.Connection
    ) -> None:
        """``BatteryMonitor._logToDatabase`` (battery_log -- ambiguous #6)."""
        from src.pi.power.battery import BatteryMonitor
        from src.pi.power.types import VoltageReading

        monitor = BatteryMonitor(database=_FakeDatabase(freshDb))
        reading = VoltageReading(
            voltage=12.3,
            timestamp=datetime(2026, 4, 19, 7, 18, 50),  # naive local
        )
        monitor._logToDatabase(reading, 'voltage_reading')

        stored = freshDb.execute(
            'SELECT timestamp FROM battery_log ORDER BY rowid DESC LIMIT 1'
        ).fetchone()[0]
        assert _CANONICAL_RE.match(stored), (
            f'BatteryMonitor._logToDatabase stored {stored!r}, not canonical'
        )


class TestNoDatetimeNowInCaptureWriteFunctions:
    """No naive ``datetime.now()`` inside the specific capture-table-write functions.

    The modules below contain legitimate ``datetime.now()`` calls in non-
    capture-write paths (in-memory session tracking, timing comparisons,
    stats timestamps).  This test targets only the functions whose bodies
    construct an SQL INSERT into a capture table -- i.e., the ones US-202
    + US-203 coerce through utcIsoNow.  Any future regression that drops a
    ``datetime.now()`` literal back into one of these specific function
    bodies is caught here.
    """

    # Attribute path syntax: 'module:Class.method' or 'module:func'.
    # Scope: US-203's 5 confirmed-naive + 3 ambiguous capture-write functions.
    # US-202's scrubbed writers (sync_log helper, switcher, data_retention,
    # drive/detector) are already covered by US-202's existing tests and are
    # out of scope here (their modules retain legitimate datetime.now() calls
    # in non-capture-write paths like session timing and stats).
    _CAPTURE_WRITE_FUNCTIONS: list[str] = [
        'src.pi.power.power_db:logPowerReading',
        'src.pi.power.power_db:logPowerTransition',
        'src.pi.power.power_db:logPowerSavingEvent',
        'src.pi.obdii.data.logger:ObdDataLogger.logReading',
        'src.pi.obdii.data.helpers:logReading',
        'src.pi.analysis.engine:StatisticsEngine._storeStatistics',
        'src.pi.alert.manager:AlertManager._logAlertToDatabase',
        'src.pi.power.battery:BatteryMonitor._logToDatabase',
    ]

    @pytest.mark.parametrize('spec', _CAPTURE_WRITE_FUNCTIONS)
    def test_captureWriteFunction_sourceHasNoNaiveDatetimeNow(
        self, spec: str
    ) -> None:
        """
        Given: a capture-table-write function TD-027 scrubbed
        When: its AST is walked for ``datetime.now()`` call expressions
        Then: zero matches appear (comments and docstrings are ignored).
        """
        naiveCalls = _findNaiveDatetimeNowCalls(_functionSource(spec))
        assert not naiveCalls, (
            f'{spec} contains {len(naiveCalls)} naive datetime.now() '
            f'call(s) in executable code -- TD-027 regression'
        )


def _functionSource(spec: str) -> str:
    """Resolve ``'module:Class.method'`` or ``'module:func'`` to source text."""
    import importlib
    import inspect

    moduleName, attrPath = spec.split(':', 1)
    module = importlib.import_module(moduleName)
    obj: Any = module
    for part in attrPath.split('.'):
        obj = getattr(obj, part)
    return inspect.getsource(obj)


def _findNaiveDatetimeNowCalls(source: str) -> list[int]:
    """Return line numbers of naive ``datetime.now()`` calls in ``source``.

    Uses :mod:`ast` so comments, docstrings, and string literals that happen
    to contain the characters ``datetime.now()`` are ignored.  Only real
    :class:`ast.Call` nodes with zero arguments targeting
    ``datetime.now`` or a bare ``now`` attribute match.
    """
    import ast
    import textwrap

    # ``inspect.getsource`` preserves the original indentation; ``ast.parse``
    # requires top-level column-0 code, so dedent before parsing.
    tree = ast.parse(textwrap.dedent(source))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if node.args or node.keywords:
            continue
        func = node.func
        # Accept both ``datetime.now()`` and ``dt.now()`` (where dt was
        # imported as ``from datetime import datetime as dt``).  Only the
        # attribute name ``now`` on a plain ``Name`` or nested attribute
        # ending in ``datetime`` counts.
        if isinstance(func, ast.Attribute) and func.attr == 'now':
            value = func.value
            if isinstance(value, ast.Name) and value.id in {'datetime', 'dt'}:
                hits.append(node.lineno)
            elif (
                isinstance(value, ast.Attribute)
                and value.attr == 'datetime'
            ):
                hits.append(node.lineno)
    return hits
