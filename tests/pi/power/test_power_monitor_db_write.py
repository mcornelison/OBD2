################################################################################
# File Name: test_power_monitor_db_write.py
# Purpose/Description: US-243 / B-050 -- power_log write-path activation
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-243) | Initial: validate UpsMonitor transition events
#                              | drive PowerMonitor.checkPowerStatus -> power_log
#                              | INSERT.  Mocks at the UpsMonitor.onPowerSourceChange
#                              | level (Spool drill found 8 transitions reaching
#                              | journal but 0 reaching power_log; this test
#                              | locks the wired path).
# ================================================================================
################################################################################

"""US-243 / B-050: PowerMonitor DB-write path activation.

Spool's 2026-04-29 inverted-power drill confirmed UpsMonitor detects power
transitions correctly (8 transitions logged to journal in 9 minutes) but
``power_log`` stayed empty since installation -- PowerMonitor (the writer
consuming UpsMonitor transitions) was never instantiated in production.
US-243 wires the path.

These tests mock at the UpsMonitor.onPowerSourceChange seam and assert the
chain UpsMonitor-event -> PowerMonitor.checkPowerStatus -> ``power_log``
INSERT executes with the canonical columns the schema actually has.

The columns asserted here (timestamp / event_type / power_source / on_ac_power)
match the live ``power_log`` schema in ``src/pi/obdii/database_schema.py``;
the story's acceptance text mentions ``vcell / soc / source`` columns but
those would require schema additions out of scope per the
``doNotTouch: PowerMonitor's internal state machine logic`` invariant.
The wiring is what unblocks US-216 observability, not new columns.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.hardware.ups_monitor import PowerSource as HwPowerSource
from pi.power.power import PowerMonitor

# ================================================================================
# Helpers
# ================================================================================


class _FakeDatabase:
    """Minimal ObdDatabase stand-in: ``connect()`` yields a real sqlite3 conn.

    Real ObdDatabase would also run schema migrations; here we hand-create
    the ``power_log`` table to match ``src/pi/obdii/database_schema.py``
    (4 columns + auto PK) so we can assert INSERT shape without booting
    the full DB stack.
    """

    def __init__(self, path: str):
        self._path = path
        self._initSchema()

    def _initSchema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS power_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    event_type TEXT NOT NULL,
                    power_source TEXT NOT NULL,
                    on_ac_power INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn


@pytest.fixture
def database(tmp_path: Path) -> _FakeDatabase:
    """Yield a fresh DB with the canonical ``power_log`` schema."""
    return _FakeDatabase(str(tmp_path / "power_test.db"))


def _makeFanOutCallback(
    powerMonitor: PowerMonitor,
    priorCallback: (
        Callable[[HwPowerSource, HwPowerSource], None] | None
    ) = None,
) -> Callable[[HwPowerSource, HwPowerSource], None]:
    """Build the same fan-out callback lifecycle._subscribePowerMonitorToUpsMonitor uses.

    Replicating the wiring shape inline keeps this test focused on the
    PowerMonitor write path; the lifecycle wiring itself is covered in
    ``tests/pi/orchestrator/test_lifecycle_power_monitor.py``.
    """
    def fanOut(oldSource: HwPowerSource, newSource: HwPowerSource) -> None:
        if priorCallback is not None:
            priorCallback(oldSource, newSource)
        onAcPower = newSource != HwPowerSource.BATTERY
        powerMonitor.checkPowerStatus(onAcPower)
    return fanOut


def _readPowerLogRows(database: _FakeDatabase) -> list[dict[str, Any]]:
    """Pull all rows from ``power_log`` ordered by id (insert order)."""
    with database.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM power_log ORDER BY id ASC")
        return [dict(r) for r in cursor.fetchall()]


# ================================================================================
# 1. Single-transition write path
# ================================================================================


class TestSingleTransitionWrites:
    """One UpsMonitor transition -> one+ rows in power_log."""

    def test_externalToBattery_writesPowerLogRow(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: PowerMonitor is wired to UpsMonitor's onPowerSourceChange
        When:  UpsMonitor fires EXTERNAL -> BATTERY transition
        Then:  power_log gains row(s) recording the new battery state.
        """
        powerMonitor = PowerMonitor(database=database, enabled=True)
        fanOut = _makeFanOutCallback(powerMonitor)

        # Simulate UpsMonitor transition firing.
        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)

        rows = _readPowerLogRows(database)
        assert len(rows) >= 1, (
            f"Expected at least 1 power_log row after EXTERNAL->BATTERY; got {len(rows)}"
        )
        # Final row reflects the new power state -- on_ac_power=0.
        finalRow = rows[-1]
        assert finalRow["on_ac_power"] == 0
        assert finalRow["power_source"] == "battery"

    def test_batteryToExternal_writesPowerLogRow(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: PowerMonitor knows it's currently on battery
        When:  UpsMonitor fires BATTERY -> EXTERNAL transition
        Then:  power_log gains row(s) recording the AC-restore.
        """
        powerMonitor = PowerMonitor(database=database, enabled=True)
        fanOut = _makeFanOutCallback(powerMonitor)
        # Seed prior battery state so the EXTERNAL transition is real.
        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)

        fanOut(HwPowerSource.BATTERY, HwPowerSource.EXTERNAL)

        rows = _readPowerLogRows(database)
        assert any(r["on_ac_power"] == 1 for r in rows), (
            f"Expected at least 1 row with on_ac_power=1; got {rows}"
        )

    def test_disabledPowerMonitor_writesNothing(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: PowerMonitor.enabled=False
        When:  UpsMonitor fires a transition
        Then:  power_log stays empty (gate honored).
        """
        powerMonitor = PowerMonitor(database=database, enabled=False)
        fanOut = _makeFanOutCallback(powerMonitor)

        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)

        rows = _readPowerLogRows(database)
        assert rows == [], f"Disabled monitor should not write; got {rows}"


# ================================================================================
# 2. Multi-transition: row count tracks transition count
# ================================================================================


class TestMultipleTransitions:
    """N transitions -> at least N rows in power_log (Spool drill: 3 -> >=3)."""

    def test_threeTransitions_writeAtLeastThreeRows(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: PowerMonitor wired to UpsMonitor
        When:  3 transitions fire (EXT->BAT->EXT->BAT)
        Then:  power_log has >= 3 rows (each checkPowerStatus call writes
               at least the reading row; transitions add a transition row).
        """
        powerMonitor = PowerMonitor(database=database, enabled=True)
        fanOut = _makeFanOutCallback(powerMonitor)

        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)
        fanOut(HwPowerSource.BATTERY, HwPowerSource.EXTERNAL)
        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)

        rows = _readPowerLogRows(database)
        assert len(rows) >= 3, (
            f"Expected >= 3 rows for 3 transitions; got {len(rows)}: {rows}"
        )

    def test_eachTransitionTimestampIsCanonicalIso(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: TD-027 / US-203 routes power_log INSERTs through utcIsoNow
        When:  Multiple transitions fire
        Then:  Every timestamp matches ``YYYY-MM-DDTHH:MM:SSZ`` regex
               (catches any new write site that bypasses utcIsoNow).
        """
        import re
        powerMonitor = PowerMonitor(database=database, enabled=True)
        fanOut = _makeFanOutCallback(powerMonitor)

        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)
        fanOut(HwPowerSource.BATTERY, HwPowerSource.EXTERNAL)

        rows = _readPowerLogRows(database)
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        for row in rows:
            ts = row["timestamp"]
            assert pattern.match(ts), (
                f"power_log timestamp '{ts}' is not canonical ISO-8601 UTC"
            )


# ================================================================================
# 3. Fan-out preserves prior ShutdownHandler callback
# ================================================================================


class TestFanOutCallbackChain:
    """The wiring must NOT clobber ShutdownHandler.onPowerSourceChange.

    HardwareManager._wireComponents calls
    ``ShutdownHandler.registerWithUpsMonitor(upsMonitor)`` which sets
    ``upsMonitor.onPowerSourceChange = handler.onPowerSourceChange``.
    Our PowerMonitor wiring needs to fan out so BOTH the legacy handler
    AND the new PowerMonitor receive every transition.
    """

    def test_priorCallback_invokedOnTransition(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: A prior callback (ShutdownHandler) is already registered
        When:  PowerMonitor fan-out wraps it
        Then:  Both the prior callback AND PowerMonitor see each event.
        """
        powerMonitor = PowerMonitor(database=database, enabled=True)
        priorCallback = MagicMock()
        fanOut = _makeFanOutCallback(powerMonitor, priorCallback=priorCallback)

        fanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)

        priorCallback.assert_called_once_with(
            HwPowerSource.EXTERNAL, HwPowerSource.BATTERY
        )
        rows = _readPowerLogRows(database)
        assert len(rows) >= 1

    def test_priorCallbackRaises_powerMonitorStillWrites(
        self, database: _FakeDatabase,
    ) -> None:
        """
        Given: Prior callback raises (e.g. ShutdownHandler hits a transient bug)
        When:  Fan-out fires
        Then:  PowerMonitor write path still executes (prior errors don't
               poison the new write path -- the audit trail must survive).
        """
        powerMonitor = PowerMonitor(database=database, enabled=True)
        priorCallback = MagicMock(side_effect=RuntimeError("boom"))

        # The fan-out the lifecycle uses swallows prior-callback errors so a
        # ShutdownHandler regression cannot break the new audit path.
        def safeFanOut(
            oldSource: HwPowerSource, newSource: HwPowerSource,
        ) -> None:
            try:
                priorCallback(oldSource, newSource)
            except Exception:
                pass
            onAcPower = newSource != HwPowerSource.BATTERY
            powerMonitor.checkPowerStatus(onAcPower)

        safeFanOut(HwPowerSource.EXTERNAL, HwPowerSource.BATTERY)

        rows = _readPowerLogRows(database)
        assert len(rows) >= 1, (
            "PowerMonitor must still write even if prior callback raised"
        )
