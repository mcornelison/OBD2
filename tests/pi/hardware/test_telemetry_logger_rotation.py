################################################################################
# File Name: test_telemetry_logger_rotation.py
# Purpose/Description: End-to-end rotation gate for TelemetryLogger (US-180
#                      AC #6).  Writes enough records to cross the rotation
#                      threshold and verifies backup files appear.  Also
#                      validates JSON shape and the UPS-missing fallback
#                      (relevant on the bench Pi whose X1209 has no I2C
#                      presence — telemetry must still log without
#                      crashing).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation for US-180 (Pi Crawl AC #6)
# ================================================================================
################################################################################

"""
TelemetryLogger rotation + UPS-missing gate for Sprint 10 / US-180 (AC #6).

Scenario coverage:
1. A single record is written as valid JSON on one line.
2. Enough records to cross maxBytes trigger RotatingFileHandler rotation
   and backup files appear (telemetry.log.1, .2, ...).
3. When the UpsMonitor is absent / raising, telemetry still logs — battery
   fields come out as None but the record is still a valid JSON line.
   This is the exact state of the bench Pi (no X1209 I2C presence).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# tests/conftest.py puts src/ on sys.path.
from pi.hardware.telemetry_logger import TelemetryLogger
from pi.hardware.ups_monitor import PowerSource

# ================================================================================
# Helpers
# ================================================================================


def _readLines(path: Path) -> list[str]:
    """Read non-empty lines from the log file."""
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _waitForRecords(path: Path, minRecords: int, timeoutSec: float = 3.0) -> list[str]:
    """Poll the log file until at least `minRecords` lines are present."""
    deadline = time.time() + timeoutSec
    lines: list[str] = []
    while time.time() < deadline:
        lines = _readLines(path)
        if len(lines) >= minRecords:
            return lines
        time.sleep(0.05)
    return lines


# ================================================================================
# Basic write tests
# ================================================================================


def test_telemetryLogger_singleRecord_isValidJson(tmp_path: Path) -> None:
    """
    Given: a TelemetryLogger with no UPS monitor attached
    When:  start() runs briefly, then stop()
    Then:  at least one JSON line has been written.  Each line parses as
           a dict and contains the documented telemetry fields.
    """
    logPath = tmp_path / "telemetry.log"
    tl = TelemetryLogger(logPath=str(logPath), logInterval=0.05)
    tl.setCpuTempReader(lambda: 42.0)
    tl.setDiskFreeReader(lambda: 12345)

    try:
        started = tl.start()
        assert started is True
        lines = _waitForRecords(logPath, minRecords=1, timeoutSec=2.0)
        assert len(lines) >= 1, "no telemetry records written"
    finally:
        tl.stop()

    record = json.loads(lines[0])
    assert set(record.keys()) >= {
        "timestamp",
        "power_source",
        "battery_v",
        "battery_ma",
        "battery_pct",
        "cpu_temp",
        "disk_free_mb",
    }
    assert record["cpu_temp"] == 42.0
    assert record["disk_free_mb"] == 12345


def test_telemetryLogger_withWorkingUps_recordsBatteryFields(tmp_path: Path) -> None:
    """
    Given: a TelemetryLogger with a UPS monitor returning valid telemetry
    When:  a record is logged
    Then:  battery_v / battery_ma / battery_pct are populated, and
           power_source is the enum's string value ('external' / 'battery').
    """
    logPath = tmp_path / "telemetry.log"
    tl = TelemetryLogger(logPath=str(logPath), logInterval=0.05)
    tl.setCpuTempReader(lambda: 40.0)
    tl.setDiskFreeReader(lambda: 999)

    mockUps = MagicMock()
    mockUps.getTelemetry.return_value = {
        "voltage": 12.3,
        "current": -150.0,
        "percentage": 82,
        "powerSource": PowerSource.EXTERNAL,
    }
    tl.setUpsMonitor(mockUps)

    try:
        tl.start()
        lines = _waitForRecords(logPath, minRecords=1, timeoutSec=2.0)
        assert lines, "no telemetry records written"
    finally:
        tl.stop()

    record = json.loads(lines[0])
    assert record["battery_v"] == 12.3
    assert record["battery_ma"] == -150.0
    assert record["battery_pct"] == 82
    assert record["power_source"] == "external"


def test_telemetryLogger_upsRaises_batteryFieldsAreNull_noCrash(tmp_path: Path) -> None:
    """
    Given: the bench-Pi scenario — UPS monitor raises on every call because
           the X1209 has no I2C presence
    When:  telemetry records are logged
    Then:  battery_v / battery_ma / battery_pct are None, power_source is
           None, cpu_temp / disk_free_mb still populated, AND the logger
           keeps running (doesn't crash after the first error).  This is
           the "no UPS telemetry" state the orchestrator actually sees on
           this hardware.
    """
    logPath = tmp_path / "telemetry.log"
    tl = TelemetryLogger(logPath=str(logPath), logInterval=0.05)
    tl.setCpuTempReader(lambda: 48.0)
    tl.setDiskFreeReader(lambda: 7777)

    mockUps = MagicMock()
    mockUps.getTelemetry.side_effect = RuntimeError("no device at 0x36")
    tl.setUpsMonitor(mockUps)

    try:
        tl.start()
        # Must not have crashed — keep waiting for multiple records.
        lines = _waitForRecords(logPath, minRecords=3, timeoutSec=3.0)
        assert len(lines) >= 3, (
            f"logger did not survive repeated UPS errors "
            f"(only {len(lines)} records written)"
        )
    finally:
        tl.stop()

    # Every record is valid JSON with battery fields nulled out.
    for line in lines:
        record = json.loads(line)
        assert record["battery_v"] is None
        assert record["battery_ma"] is None
        assert record["battery_pct"] is None
        assert record["power_source"] is None
        # Non-UPS telemetry still populated.
        assert record["cpu_temp"] == 48.0
        assert record["disk_free_mb"] == 7777


# ================================================================================
# Rotation test
# ================================================================================


def test_telemetryLogger_crossesMaxBytes_rotatesAndCreatesBackup(tmp_path: Path) -> None:
    """
    Given: a TelemetryLogger configured with maxBytes=500 (tiny), backupCount=2
    When:  enough records are written to cross the 500-byte threshold
    Then:  the primary log is rotated (telemetry.log.1 appears) and the
           primary log does NOT exceed maxBytes by more than one record's
           worth of bytes.  Validates that RotatingFileHandler is actually
           wired and fires — without this gate a mis-set maxBytes (or a
           silent rewrite into non-rotating FileHandler) would let the log
           grow unbounded and eventually fill /var/log.
    """
    logPath = tmp_path / "telemetry.log"
    tl = TelemetryLogger(
        logPath=str(logPath),
        logInterval=0.02,
        maxBytes=500,
        backupCount=2,
    )
    tl.setCpuTempReader(lambda: 50.0)
    tl.setDiskFreeReader(lambda: 1000)

    try:
        tl.start()
        # Wait up to 3s for at least one rotation to occur.
        deadline = time.time() + 3.0
        rotated = False
        while time.time() < deadline:
            if (tmp_path / "telemetry.log.1").exists():
                rotated = True
                break
            time.sleep(0.05)
    finally:
        tl.stop()

    assert rotated, "RotatingFileHandler did not rotate before stop()"
    # Primary log is < maxBytes (with ~1 record slack for the write that
    # triggered the rotation-check).
    assert logPath.stat().st_size < 500 + 256


def test_telemetryLogger_invalidInterval_raisesValueError(tmp_path: Path) -> None:
    """
    Given: a TelemetryLogger constructed with logInterval <= 0
    When:  __init__ runs
    Then:  ValueError is raised.  Protects against a misconfigured
           deployment accidentally tight-looping the logger thread and
           DoSing the disk.
    """
    with pytest.raises(ValueError, match="Log interval must be positive"):
        TelemetryLogger(logPath=str(tmp_path / "t.log"), logInterval=0.0)

    with pytest.raises(ValueError, match="Log interval must be positive"):
        TelemetryLogger(logPath=str(tmp_path / "t.log"), logInterval=-1.0)


def test_telemetryLogger_doubleStart_raisesRuntimeError(tmp_path: Path) -> None:
    """
    Given: a TelemetryLogger that is already logging
    When:  start() is called again
    Then:  RuntimeError is raised with a clear message.  Catches an
           orchestrator wiring bug where a re-init path silently spawns a
           second logging thread.
    """
    logPath = tmp_path / "telemetry.log"
    tl = TelemetryLogger(logPath=str(logPath), logInterval=0.5)

    try:
        assert tl.start() is True
        with pytest.raises(RuntimeError, match="already running"):
            tl.start()
    finally:
        tl.stop()


def test_telemetryLogger_stopBeforeStart_isNoOp(tmp_path: Path) -> None:
    """
    Given: a TelemetryLogger that has never started
    When:  stop() is called
    Then:  it quietly returns — mirrors GpioButton's forgiving shutdown
           contract.
    """
    tl = TelemetryLogger(logPath=str(tmp_path / "t.log"), logInterval=0.5)
    # Must not raise or leave state inconsistent.
    tl.stop()
    tl.stop()
    assert tl.isLogging is False


# ================================================================================
# Thread lifecycle gate
# ================================================================================


def test_telemetryLogger_stopTerminatesLoggingThread(tmp_path: Path) -> None:
    """
    Given: a running TelemetryLogger
    When:  stop() is called
    Then:  the background thread exits within the join timeout — no
           daemon-thread leak across test boundaries.  Catches any
           regression that inadvertently breaks the _stopEvent signaling.
    """
    logPath = tmp_path / "telemetry.log"
    tl = TelemetryLogger(logPath=str(logPath), logInterval=0.05)

    assert tl.start() is True
    threading.Event().wait(0.1)
    assert tl.isLogging is True

    tl.stop()
    assert tl.isLogging is False
    # _loggingThread should be None after cleanup.
    assert tl._loggingThread is None
