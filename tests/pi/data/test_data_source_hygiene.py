################################################################################
# File Name: test_data_source_hygiene.py
# Purpose/Description: US-212 enforcement: every non-live-OBD capture-table
#                      INSERT passes data_source explicitly; the live-OBD
#                      writer auto-derives the tag from the active connection
#                      rather than relying on the schema DEFAULT.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-212) | Initial -- AST audit of seed + simulator
#                               writers; runtime checks that
#                               ObdDataLogger auto-derives 'physics_sim'
#                               when its connection is SimulatedObdConnection
#                               and helpers.logReading accepts a dataSource
#                               keyword.
# ================================================================================
################################################################################

"""Call-site hygiene tests for the Pi ``data_source`` column (US-212).

US-195 added a ``data_source`` column with ``DEFAULT 'real'`` as a safety
net for the **single live-OBD writer**. The DEFAULT was never intended
as a catchall for every other writer. Spool's benchtest-hygiene note
documented ~352K Sprint-14 benchtest rows that landed as ``'real'``
because the simulator feeds the same writer path as live-OBD and no
caller was ever asked to tag explicitly.

This module closes the bug at two levels:

1. An **AST audit** walks :mod:`scripts.seed_scenarios` and
   :mod:`scripts.seed_pi_fixture` and asserts every capture-table
   ``INSERT`` statement names the ``data_source`` column. Seed scripts
   that silently rely on the schema DEFAULT are the call-site bug.

2. **Runtime checks** exercise the new ``ObdDataLogger.dataSource``
   derivation: pointing the logger at a ``SimulatedObdConnection``
   writes ``'physics_sim'`` rows, pointing it at a plain mock writes
   ``'real'``, and an explicit override wins over the derivation.
   :func:`src.pi.obdii.data.helpers.logReading` accepts a
   ``dataSource`` kwarg that flows into the row.

The AST walker intentionally ignores ``tests/`` (test harnesses may
write to isolated SQLite files without tagging) and the live-OBD
writers at ``src/pi/obdii/data/logger.py`` +
``src/pi/obdii/data/helpers.py`` (those are the one-place DEFAULT
consumers; US-212 auto-tags them via connection shape rather than by
string literal).
"""

from __future__ import annotations

import ast
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.data.helpers import logReading as helperLogReading
from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.data.types import LoggedReading
from src.pi.obdii.data_source import CAPTURE_TABLES, DATA_SOURCE_VALUES
from src.pi.obdii.database import ObdDatabase

# ================================================================================
# Fixtures
# ================================================================================

# Capture tables audited at the AST layer.  Matches :data:`CAPTURE_TABLES`
# plus dtc_log / drive_summary which also carry data_source columns
# (US-204 / US-206 additions).  alert_log is intentionally excluded --
# it has no data_source column per the CAPTURE_TABLES carve-out.
_AUDIT_TABLES: frozenset[str] = frozenset(
    set(CAPTURE_TABLES) | {"dtc_log", "drive_summary"}
)

# Seed scripts under audit.  These are the code paths that produce
# non-real rows and must therefore tag explicitly.
_SEED_SCRIPTS: tuple[str, ...] = (
    "scripts/seed_scenarios.py",
    "scripts/seed_pi_fixture.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _loadSource(relPath: str) -> str:
    path = _REPO_ROOT / relPath
    return path.read_text(encoding="utf-8")


def _sqlInsertTable(sql: str) -> str | None:
    """Return the target table name of an ``INSERT INTO`` SQL literal.

    Returns ``None`` when ``sql`` is not an INSERT statement.
    """
    stripped = sql.lstrip()
    upper = stripped.upper()
    if not upper.startswith("INSERT INTO"):
        return None
    remainder = stripped[len("INSERT INTO"):].lstrip()
    # Table name ends at whitespace, paren, or newline.
    tokenEnd = len(remainder)
    for i, ch in enumerate(remainder):
        if ch in (" ", "\t", "\n", "(",):
            tokenEnd = i
            break
    return remainder[:tokenEnd].strip()


def _insertStatementsInSource(source: str) -> list[str]:
    """Return the raw SQL text of every ``INSERT INTO`` literal in source.

    Walks the file AST, then re-joins string-concatenation nodes (common
    with ``"foo " "bar"`` or ``"foo " + "bar"``) so multi-line INSERTs
    come back as one blob.  Triple-quoted statements arrive intact via
    :class:`ast.Constant`.
    """
    tree = ast.parse(source)
    statements: list[str] = []
    for node in ast.walk(tree):
        literal = _extractStringLiteral(node)
        if literal is None:
            continue
        if "INSERT INTO" not in literal.upper():
            continue
        statements.append(literal)
    return statements


def _extractStringLiteral(node: ast.AST) -> str | None:
    """Return the concrete string value of a constant / joined-string node.

    Returns None for nodes that are not pure string constants.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _extractStringLiteral(node.left)
        right = _extractStringLiteral(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        # f-string -- reconstruct the non-interpolated segments; if any
        # interpolation is present we cannot statically audit, so return
        # the concatenated static parts and let the caller decide.
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("")
        return "".join(parts)
    return None


# ================================================================================
# AST audit -- seed scripts
# ================================================================================


class TestSeedScriptHygiene:
    """Every capture-table INSERT in a seed script tags data_source."""

    @pytest.mark.parametrize("scriptPath", _SEED_SCRIPTS)
    def test_seedScript_captureInsert_namesDataSource(
        self, scriptPath: str
    ) -> None:
        source = _loadSource(scriptPath)
        inserts = _insertStatementsInSource(source)
        captureInserts = [
            stmt for stmt in inserts
            if _sqlInsertTable(stmt) in _AUDIT_TABLES
        ]
        assert captureInserts, (
            f"{scriptPath} should contain at least one capture-table INSERT "
            "for this audit to be meaningful; if the script no longer seeds "
            "capture tables, prune this audit"
        )
        missing = [
            stmt for stmt in captureInserts
            if "data_source" not in stmt
        ]
        assert missing == [], (
            f"{scriptPath} has {len(missing)} capture-table INSERT(s) that "
            "do not name the data_source column (they would silently inherit "
            "DEFAULT 'real' and poison analytics). Offending statements:\n"
            + "\n---\n".join(missing)
        )


# ================================================================================
# Runtime -- ObdDataLogger derives from connection.isSimulated
# ================================================================================


class _StubObdResponse:
    """Minimal python-obd response shape used by ObdDataLogger."""

    def __init__(self, value: float, unit: str = "rpm") -> None:
        self._value = value
        self._unit = unit

    def is_null(self) -> bool:
        return False

    @property
    def value(self) -> Any:
        return _StubMagnitude(self._value, self._unit)


class _StubMagnitude:
    def __init__(self, value: float, unit: str) -> None:
        self.magnitude = value
        self.units = unit


class _StubObd:
    def __init__(self, value: float) -> None:
        self._value = value

    def query(self, _cmd: object) -> _StubObdResponse:
        return _StubObdResponse(self._value)


class _FakeLiveConnection:
    """Minimal real-OBD connection shape (no isSimulated attribute)."""

    def __init__(self, value: float = 1234.0) -> None:
        self.obd = _StubObd(value)

    def isConnected(self) -> bool:
        return True


class _FakeSimulatedConnection(_FakeLiveConnection):
    """Real-looking connection that self-identifies as simulated."""

    isSimulated: bool = True


@pytest.fixture
def freshDb(tmp_path: Path) -> Generator[ObdDatabase, None, None]:
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    yield db


class TestObdDataLoggerDataSourceDerivation:
    """ObdDataLogger tags rows from the connection shape by default."""

    def test_liveConnection_defaultsToReal(self, freshDb) -> None:
        conn = _FakeLiveConnection()
        logger = ObdDataLogger(conn, freshDb, profileId="daily")
        assert logger.dataSource == "real"

    def test_simulatedConnection_defaultsToPhysicsSim(self, freshDb) -> None:
        conn = _FakeSimulatedConnection()
        logger = ObdDataLogger(conn, freshDb, profileId="daily")
        assert logger.dataSource == "physics_sim"

    def test_explicitOverride_winsOverDerivation(self, freshDb) -> None:
        conn = _FakeLiveConnection()
        logger = ObdDataLogger(
            conn, freshDb, profileId="daily", dataSource="fixture"
        )
        assert logger.dataSource == "fixture"

    def test_explicitOverride_rejectsUnknownValue(self, freshDb) -> None:
        conn = _FakeLiveConnection()
        with pytest.raises(ValueError, match="data_source"):
            ObdDataLogger(
                conn, freshDb, profileId="daily", dataSource="bogus"
            )

    def test_logReading_writesDerivedTag(self, freshDb) -> None:
        conn = _FakeSimulatedConnection()
        logger = ObdDataLogger(conn, freshDb, profileId=None)
        reading = LoggedReading(
            parameterName="RPM",
            value=850.0,
            unit="rpm",
            timestamp=_fixedTs(),
            profileId=None,
        )
        assert logger.logReading(reading) is True
        row = _fetchOneRow(
            freshDb, "SELECT data_source FROM realtime_data"
        )
        assert row[0] == "physics_sim"

    def test_logReading_respectsExplicitReal(self, freshDb) -> None:
        conn = _FakeLiveConnection()
        logger = ObdDataLogger(
            conn, freshDb, profileId=None, dataSource="real"
        )
        reading = LoggedReading(
            parameterName="RPM",
            value=850.0,
            unit="rpm",
            timestamp=_fixedTs(),
            profileId=None,
        )
        logger.logReading(reading)
        row = _fetchOneRow(
            freshDb, "SELECT data_source FROM realtime_data"
        )
        assert row[0] == "real"


# ================================================================================
# Runtime -- helpers.logReading carries an explicit dataSource
# ================================================================================


class TestHelpersLogReadingDataSource:
    """:func:`helpers.logReading` accepts and persists a data_source kwarg."""

    def test_default_tagsAsReal(self, freshDb) -> None:
        reading = LoggedReading(
            parameterName="SPEED",
            value=55.0,
            unit="kph",
            timestamp=_fixedTs(),
            profileId=None,
        )
        helperLogReading(freshDb, reading)
        row = _fetchOneRow(
            freshDb, "SELECT data_source FROM realtime_data"
        )
        assert row[0] == "real"

    def test_fixtureOverride_tagsAsFixture(self, freshDb) -> None:
        reading = LoggedReading(
            parameterName="SPEED",
            value=0.0,
            unit="kph",
            timestamp=_fixedTs(),
            profileId=None,
        )
        helperLogReading(freshDb, reading, dataSource="fixture")
        row = _fetchOneRow(
            freshDb, "SELECT data_source FROM realtime_data"
        )
        assert row[0] == "fixture"

    def test_physicsSimOverride_tagsAsPhysicsSim(self, freshDb) -> None:
        reading = LoggedReading(
            parameterName="RPM",
            value=900.0,
            unit="rpm",
            timestamp=_fixedTs(),
            profileId=None,
        )
        helperLogReading(freshDb, reading, dataSource="physics_sim")
        row = _fetchOneRow(
            freshDb, "SELECT data_source FROM realtime_data"
        )
        assert row[0] == "physics_sim"

    def test_unknownValue_rejected(self, freshDb) -> None:
        reading = LoggedReading(
            parameterName="RPM",
            value=1.0,
            unit="rpm",
            timestamp=_fixedTs(),
            profileId=None,
        )
        with pytest.raises(ValueError, match="data_source"):
            helperLogReading(freshDb, reading, dataSource="nope")


# ================================================================================
# Sanity -- enum values unchanged (US-195 contract)
# ================================================================================


def test_enumValues_unchanged() -> None:
    assert DATA_SOURCE_VALUES == ("real", "replay", "physics_sim", "fixture")


# ================================================================================
# Test helpers
# ================================================================================


def _fetchOneRow(db: ObdDatabase, sql: str) -> tuple[Any, ...]:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()


def _fixedTs() -> datetime:
    return datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
