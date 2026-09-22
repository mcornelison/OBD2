################################################################################
# File Name: test_persistence_drive_attribution.py
# Purpose/Description: US-777 -- a realtime_data row is attributed to the drive
#     it was CAPTURED during, not to whatever drive is live when the
#     PersistenceSubscriber drain thread reaches it. The producer
#     (RealtimeDataLogger._publishReading) already stamps Sample.driveId via
#     getCurrentDriveId() at capture; before US-777 the subscriber discarded
#     it and ObdDataLogger.logReading re-resolved at WRITE time, so a drain lag
#     that spans a drive close NULLed (or re-attributed) the rows. Ralph
#     measured 31 NULL rows at a 90 s drain lag on 2026-09-21.
# Author: Rex (US-777)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-21    | Rex (US-777)   | Initial -- capture-time attribution across a
#               |                | drain lag; explicit NULL never inherits; one
#               |                | staleness predicate.
# ================================================================================
################################################################################
"""US-777: capture-time drive attribution through the bus persistence path."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import pi.obdii.drive.detector as detectorModule
import pi.obdii.drive_id as driveIdModule
from pi.bus.bus import SampleBus
from pi.bus.persistence_subscriber import PersistenceSubscriber
from pi.bus.sample import QoS
from pi.obdii.data.logger import ObdDataLogger
from pi.obdii.data.realtime import RealtimeDataLogger
from pi.obdii.data.types import LoggedReading
from pi.obdii.database import ObdDatabase
from pi.obdii.drive.detector import DriveDetector
from pi.obdii.drive_id import (
    armDriveIdleBound,
    clearCurrentDriveId,
    getCurrentDriveId,
    getRawCurrentDriveId,
    isDriveIdStale,
    setCurrentDriveId,
)

_PROFILE_ID = "daily"
# Production driveEndDurationSeconds; the drive_id idle bound reuses it.
_IDLE_BOUND_S = 60.0
# The drain lag Ralph measured producing 31 NULL rows (2026-09-21).
_DRAIN_LAG_S = 90.0


@pytest.fixture(autouse=True)
def _cleanDriveContext():
    clearCurrentDriveId()
    yield
    clearCurrentDriveId()


def _db(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "attr.db"), walMode=False)
    db.initialize()
    with db.connect() as conn:
        conn.execute("INSERT INTO profiles (id, name) VALUES (?, ?)", (_PROFILE_ID, "Daily"))
    return db


def _driveIds(db: ObdDatabase) -> list[int | None]:
    with db.connect() as conn:
        return [r[0] for r in conn.execute("SELECT drive_id FROM realtime_data ORDER BY id")]


class _Rig:
    """The REAL producer method, a bus, and the REAL subscriber + write path.

    Samples are captured into a LOSSLESS subscription and drained later, by
    hand, so the drain lag is exactly what the test makes it.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.db = _db(tmp_path)
        self.bus = SampleBus()
        self.sub = self.bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
        self.dataLogger = ObdDataLogger(
            connection=None, database=self.db, profileId=_PROFILE_ID, dataSource="real"
        )
        self.persistence = PersistenceSubscriber(self.sub, self.dataLogger)
        # Only the attributes RealtimeDataLogger._publishReading touches.
        self._producer = SimpleNamespace(
            _seq=0, _producerSource="obd", _dataSource="real", _bus=self.bus,
            _stats=SimpleNamespace(totalLogged=0), _markRowWritten=lambda: None,
        )

    def capture(self, n: int, name: str = "RPM") -> None:
        """Capture ``n`` readings through the production producer method."""
        for i in range(n):
            reading = LoggedReading(name, 3000.0 + i, datetime.now(), "rpm", None)
            RealtimeDataLogger._publishReading(self._producer, reading)  # type: ignore[arg-type]

    def drain(self) -> int:
        drained = 0
        while (sample := self.sub.poll()) is not None:
            self.persistence.handleSample(sample)
            drained += 1
        return drained


class TestCaptureTimeAttribution:
    def test_drainLagSpanningAStaleClose_keepsTheCapturingDrive(self, tmp_path: Path) -> None:
        """
        Given: drive 41 live and fresh at capture, rows queued on the bus
        When: the drain reaches them 90 s after the drive's last activity --
            past the 60 s idle bound, so a WRITE-time lookup reads stale
        Then: every row carries drive 41. Pre-fix they were all NULL
        """
        rig = _Rig(tmp_path)
        setCurrentDriveId(41)
        armDriveIdleBound(_IDLE_BOUND_S)  # activity anchored NOW: fresh at capture
        rig.capture(31)

        # The drain thread falls behind: re-anchor the idle clock 90 s in the
        # past, so the drive is stale by the time the rows are written.
        armDriveIdleBound(_IDLE_BOUND_S, nowMono=time.monotonic() - _DRAIN_LAG_S)
        assert getCurrentDriveId() is None, "precondition: write-time lookup is stale"

        assert rig.drain() == 31
        assert _driveIds(rig.db) == [41] * 31

    def test_drainLagSpanningADriveChange_neverTakesTheNextDrive(self, tmp_path: Path) -> None:
        """
        Given: rows captured during drive 41, still queued
        When: drive 41 closes and drive 42 opens before the drain reaches them
        Then: the rows carry 41 -- the write-time lookup would attach 42, which
            is the inheritance this story removes
        """
        rig = _Rig(tmp_path)
        setCurrentDriveId(41)
        rig.capture(5)
        setCurrentDriveId(None)
        setCurrentDriveId(42)

        rig.drain()
        assert _driveIds(rig.db) == [41] * 5

    def test_twoLegsInOneQueue_eachKeepsItsOwnDrive(self, tmp_path: Path) -> None:
        """
        Given: leg A captured in drive 41, key-off, leg B captured in drive 42,
            all drained together at the end
        When: drained
        Then: A rows are 41 and B rows are 42, in order
        """
        rig = _Rig(tmp_path)
        setCurrentDriveId(41)
        rig.capture(3)
        setCurrentDriveId(None)
        setCurrentDriveId(42)
        rig.capture(2)
        rig.drain()
        assert _driveIds(rig.db) == [41, 41, 41, 42, 42]

    def test_ordinaryDrive_oneDriveIdAcrossAllRows(self, tmp_path: Path) -> None:
        """An ordinary start-to-finish drive drained promptly: one id, as today."""
        rig = _Rig(tmp_path)
        setCurrentDriveId(7)
        armDriveIdleBound(_IDLE_BOUND_S)
        for _ in range(4):
            rig.capture(10)
            rig.drain()
        assert _driveIds(rig.db) == [7] * 40


class TestExplicitNullNeverInherits:
    def test_capturedWithNoDrive_staysNull_whenADriveOpensBeforeTheWrite(
        self, tmp_path: Path
    ) -> None:
        """
        Given: rows captured with NO drive live (sample.driveId None)
        When: drive 43 opens before the drain reaches them
        Then: the rows stay explicit NULL -- a captured None is never upgraded
            to a drive that was not live when the datum was read
        """
        rig = _Rig(tmp_path)
        rig.capture(4)
        setCurrentDriveId(43)
        rig.drain()
        assert _driveIds(rig.db) == [None] * 4

    def test_unresolvableAtCapture_isNull_neverThePreviousDrive(self, tmp_path: Path) -> None:
        """
        Given: drive 44 is still held in the context but is past its idle bound
            (the attribution genuinely cannot name a live drive)
        When: a row is captured and written
        Then: drive_id is explicit NULL, not the stale 44
        """
        rig = _Rig(tmp_path)
        setCurrentDriveId(44)
        armDriveIdleBound(_IDLE_BOUND_S, nowMono=time.monotonic() - _DRAIN_LAG_S)
        assert getRawCurrentDriveId() == 44
        rig.capture(2)
        rig.drain()
        assert _driveIds(rig.db) == [None, None]


class TestInlinePathUnchanged:
    def test_logReadingWithoutACapturedId_resolvesAtWrite(self, tmp_path: Path) -> None:
        """
        Given: the no-bus inline path (logReading called with no captured id)
        When: a drive is live
        Then: the row carries that drive, exactly as before US-777
        """
        db = _db(tmp_path)
        dataLogger = ObdDataLogger(
            connection=None, database=db, profileId=_PROFILE_ID, dataSource="real"
        )
        setCurrentDriveId(45)
        dataLogger.logReading(LoggedReading("RPM", 900.0, datetime.now(), "rpm", None))
        setCurrentDriveId(None)
        dataLogger.logReading(LoggedReading("RPM", 0.0, datetime.now(), "rpm", None))
        assert _driveIds(db) == [45, None]

    def test_subscriberNeverReResolvesTheDrive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: the bus path
        When: a captured sample is written
        Then: the write path makes NO drive lookup of its own -- the captured
            id is the only attribution
        """
        rig = _Rig(tmp_path)
        setCurrentDriveId(46)
        rig.capture(3)

        import pi.obdii.data.logger as loggerModule

        def boom(*_a: Any, **_k: Any) -> int | None:
            raise AssertionError("write path re-resolved the drive")

        monkeypatch.setattr(loggerModule, "getCurrentDriveId", boom)
        rig.drain()
        assert _driveIds(rig.db) == [46] * 3


class TestOneStalenessPredicate:
    """US-625: the detector's close and the attribution read share ONE predicate
    and ONE bound. Loosening staleness on the attribution side alone would
    split it and re-open the drive-51 defect."""

    def test_detectorAndAttribution_callTheSameFunction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: a spy in place of drive_id.isDriveIdStale
        When: the attribution read (getCurrentDriveId, which the producer calls
            at capture) runs
        Then: it consults the spy; and the detector's close is bound to the
            very same function object
        """
        assert detectorModule.isDriveIdStale is driveIdModule.isDriveIdStale
        calls: list[Any] = []
        real = driveIdModule.isDriveIdStale

        def spy(nowMono: float | None = None) -> bool:
            calls.append(nowMono)
            return real(nowMono)

        monkeypatch.setattr(driveIdModule, "isDriveIdStale", spy)
        setCurrentDriveId(47)
        armDriveIdleBound(_IDLE_BOUND_S)
        assert driveIdModule.getCurrentDriveId() == 47
        assert len(calls) == 1

    @pytest.mark.parametrize(("idleS", "stale"), [(59.5, False), (60.5, True)])
    def test_detectorCloseAndAttribution_flipAtTheSameBound(
        self, idleS: float, stale: bool
    ) -> None:
        """
        Given: a detector armed with driveEndDurationSeconds=60 (its production
            arming path), and the drive idle for ``idleS`` seconds
        When: the attribution read and the detector's bounded-idle close run
        Then: they agree -- both still live below the bound, both over past it
        """
        detector = DriveDetector(config={"pi": {"analysis": {
            "driveStartRpmThreshold": 500, "driveStartDurationSeconds": 10,
            "driveEndRpmThreshold": 0, "driveEndDurationSeconds": _IDLE_BOUND_S,
            "triggerAfterDrive": False, "driveSummaryBackfillSeconds": 0,
        }}})
        detector.start()
        setCurrentDriveId(48)
        detector._armDriveIdleBound(time.monotonic() - idleS)  # noqa: SLF001

        assert isDriveIdStale() is stale
        assert (getCurrentDriveId() is None) is stale
        assert detector._maybeCloseStaleDriveId() is stale  # noqa: SLF001
