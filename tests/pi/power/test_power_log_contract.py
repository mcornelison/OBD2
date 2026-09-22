################################################################################
# File Name: test_power_log_contract.py
# Purpose/Description: US-798 -- power_log has ONE authoritative statement of
#     what it contains: the module docstring of src/pi/power/power_db.py. These
#     tests hold that statement to the code: the writers it names are exactly the
#     functions that INSERT into the table, the event types it names are exactly
#     the POWER_LOG_EVENT_* vocabulary, no module outside power_db.py inserts,
#     production never runs the per-poll path, and one power loss writes the rows
#     the statement says it does (measured on chi-eclipse-01 rows 2799-2802).
# Author: Rex (US-798)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-798)   | Initial -- enumeration == writers, vocabulary,
#               |                | single inserter, event cadence, spec pointers.
# ================================================================================
################################################################################
"""US-798: the power_log contract in power_db.py matches the code that writes."""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import pi.power.power_db as powerDbModule
import pi.power.types as powerTypes
from pi.obdii.orchestrator.lifecycle import _PowerSourceUiBridge
from pi.power.power import PowerMonitor
from pi.power.power_db import logPowerObservation
from pi.power.types import (
    POWER_LOG_EVENT_OBSERVER_SESSION_START,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
)

_REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()
)
_SRC = _REPO_ROOT / "src"
_POWER_DB = _SRC / "pi" / "power" / "power_db.py"
_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+power_log\b", re.IGNORECASE)
# "    logPowerReading -> ac_power, battery_power" in the module docstring.
_WRITER_LINE = re.compile(r"^\s+(log\w+)\s+->\s+([a-z_]+(?:,\s*[a-z_]+)*)\s*$", re.MULTILINE)


def _contractWriters() -> dict[str, set[str]]:
    doc = powerDbModule.__doc__ or ""
    return {m.group(1): {e.strip() for e in m.group(2).split(",")} for m in _WRITER_LINE.finditer(doc)}


def _insertingFunctions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _INSERT.search(sub.value):
                    found.add(node.name)
    return found


# ---------------------------------------------------------------- the statement


def test_contractNamesExactlyTheFunctionsThatInsert() -> None:
    """
    Given: the writer enumeration in power_db.py's docstring
    When: compared with every function in power_db.py that INSERTs into power_log
    Then: the same set -- neither has an entry the other lacks
    """
    writers = _contractWriters()
    assert len(writers) == 5, writers
    assert set(writers) == _insertingFunctions(_POWER_DB)


def test_contractNamesExactlyTheEventVocabulary() -> None:
    """Every POWER_LOG_EVENT_* type is named by a writer line, and no other."""
    vocabulary = {
        value for name, value in vars(powerTypes).items() if name.startswith("POWER_LOG_EVENT_")
    }
    named = set().union(*_contractWriters().values())
    assert named == vocabulary


def test_noModuleOutsidePowerDbInsertsIntoPowerLog() -> None:
    """The five writers are the only door into the table, anywhere in src/."""
    inserters = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if _INSERT.search(path.read_text(encoding="utf-8"))
    )
    assert inserters == ["pi/power/power_db.py"]


def test_insertScanner_seesEveryShape(tmp_path: Path) -> None:
    """The INSERT pattern matches the forms a new writer might use -- a zero
    elsewhere is only evidence because this matches."""
    for sql in (
        "INSERT INTO power_log (a) VALUES (?)",
        "insert into power_log(a) values (?)",
        "INSERT OR IGNORE INTO power_log (a) VALUES (?)",
        "INSERT\n  INTO power_log",
    ):
        assert _INSERT.search(sql), sql
    assert not _INSERT.search("INSERT INTO power_log_archive (a) VALUES (?)")


def test_productionNeverStartsThePerPollLoop() -> None:
    """
    Given: PowerMonitor.start() -- the ONLY path that would write a row per poll
    When: src/ is searched for a call to it
    Then: none -- which is what makes power_log an event log (the contract's
        first claim). Starting it would need a retention rule first.
    """
    # The scanner sees the shapes a caller would use -- and NOT prose that
    # merely names the method (the contract docstring itself does).
    assert _powerMonitorStartCalls("self._powerMonitor.start()\n")
    assert _powerMonitorStartCalls("monitor = PowerMonitor(db)\nPowerMonitor(db).start()\n")
    assert not _powerMonitorStartCalls('"""Never call ``PowerMonitor.start()``."""\n')
    callers = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if _powerMonitorStartCalls(path.read_text(encoding="utf-8"))
    )
    assert callers == []


def _powerMonitorStartCalls(source: str) -> bool:
    """True if ``source`` CALLS ``.start()`` on something named like a power
    monitor, or on a ``PowerMonitor(...)`` construction (AST, not text)."""
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
        ):
            continue
        target = node.func.value
        if isinstance(target, ast.Call):
            target = target.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if "powermonitor" in name.lower():
            return True
    return False


def test_stageRowsAreHistorical_theWriterIsStoredButNeverCalled() -> None:
    """
    Given: the contract's claim that stage_* rows are historical
    When: the only consumer of the lifecycle-built stage writer is read
    Then: HardwareManager stores the writer and never invokes it. If this ever
        fails, stage rows are live again and the contract must say so
    """
    source = (_SRC / "pi" / "hardware" / "hardware_manager.py").read_text(encoding="utf-8")
    assert "self._powerLogWriter = powerLogWriter" in source  # the seam still exists
    assert "_powerLogWriter(" not in source


# ------------------------------------------------------------- event cadence


class _Db:
    def __init__(self, path: str) -> None:
        self.dbPath = path
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE power_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " timestamp TEXT, event_type TEXT NOT NULL, power_source TEXT NOT NULL,"
                " on_ac_power INTEGER NOT NULL DEFAULT 1, vcell REAL, data_quality TEXT,"
                " observed_by TEXT, observer_state TEXT)"
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.dbPath)
        conn.row_factory = sqlite3.Row
        return conn

    def rows(self) -> list[tuple[str, bool]]:
        with sqlite3.connect(self.dbPath) as conn:
            return [
                (r[0], r[1] is not None)
                for r in conn.execute("SELECT event_type, observed_by FROM power_log ORDER BY id")
            ]


class _Provider:
    def __init__(self) -> None:
        self.present = True
        self.isAvailable = True

    def isExternalPowerPresent(self) -> bool:
        return self.present


def _productionBridge(db: _Db, provider: _Provider) -> _PowerSourceUiBridge:
    """The bridge as lifecycle wires it: PowerMonitor (never started) as the
    sink, and the same session-start / transition recorder."""
    monitor = PowerMonitor(database=db, enabled=True)
    first = [True]

    def recorder(observation) -> None:
        if first[0]:
            first[0] = False
            eventType = POWER_LOG_EVENT_OBSERVER_SESSION_START
        elif observation.onAcPower:
            eventType = POWER_LOG_EVENT_TRANSITION_TO_AC
        else:
            eventType = POWER_LOG_EVENT_TRANSITION_TO_BATTERY
        logPowerObservation(db, eventType, observation)

    return _PowerSourceUiBridge(
        provider=provider, sink=monitor.checkPowerStatus, pollSec=2.0, recorder=recorder
    )


def test_steadyPower_writesOnlyTheSessionStart_notOneRowPerPoll(tmp_path: Path) -> None:
    """
    Given: the production bridge on steady mains power
    When: it polls 100 times
    Then: two rows total (observer_session_start + one ac_power reading) --
        an event log, not a poll log
    """
    db, provider = _Db(str(tmp_path / "p.db")), _Provider()
    bridge = _productionBridge(db, provider)
    for _ in range(100):
        bridge.pollOnce()
    assert db.rows() == [("observer_session_start", True), ("ac_power", False)]


def test_onePowerLoss_writesFourRows_withTheTransitionTwice(tmp_path: Path) -> None:
    """
    Given: the production bridge on mains, then power lost
    When: the loss is polled
    Then: exactly the four rows the contract states (as on the car, rows
        2799-2802 on 2026-09-21): the OBSERVER's transition_to_battery,
        power_saving_enabled, PowerMonitor's transition_to_battery, and a
        battery_power reading -- so a transition count must use observer rows
    """
    db, provider = _Db(str(tmp_path / "p.db")), _Provider()
    bridge = _productionBridge(db, provider)
    bridge.pollOnce()
    provider.present = False
    for _ in range(10):
        bridge.pollOnce()
    assert db.rows()[2:] == [
        ("transition_to_battery", True),
        ("power_saving_enabled", False),
        ("transition_to_battery", False),
        ("battery_power", False),
    ]


# ------------------------------------------------------------ spec pointers


def test_specPointsAtTheContract_andNoLongerSaysEveryPoll() -> None:
    """
    Given: specs/architecture.md, the model docstring and the sync registry
    When: read
    Then: none describes power_log as per-poll, and each points at power_db.py
        instead of restating what the table holds
    """
    arch = (_REPO_ROOT / "specs" / "architecture.md").read_text(encoding="utf-8")
    powerLines = [line for line in arch.splitlines() if "power_log" in line]
    assert not [line for line in powerLines if "every poll" in line.lower()]
    inventory = [line for line in powerLines if line.startswith("| `power_log` |")]
    assert len(inventory) == 1 and "power_db.py" in inventory[0], inventory
    for rel in ("src/server/db/models.py", "src/pi/data/sync_log.py"):
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "power_db.py" in text, f"{rel} does not point at the power_log contract"
