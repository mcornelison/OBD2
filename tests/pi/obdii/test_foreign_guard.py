################################################################################
# File Name: test_foreign_guard.py
# Purpose/Description: US-424 (F-116) tests for the Pi foreign-vehicle ingest
#                      guard -- sustained bus-rate detection (a sustained
#                      >threshold row rate trips; a legit Eclipse rate / a
#                      start-of-drive burst does NOT), retro-tag on trip, the
#                      writer latch (isDriveForeign), the process-wide singleton
#                      accessors, and the config-gated dark-by-default install.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-424) | Initial -- foreign-vehicle ingest guard tests.
# ================================================================================
################################################################################

"""US-424 / F-116 -- Pi foreign-vehicle ingest guard tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from src.pi.obdii.data_source import ensureDataSourceCheckWidened
from src.pi.obdii.foreign_guard import (
    DEFAULT_BUS_RATE_THRESHOLD_HZ,
    DEFAULT_MEASUREMENT_WINDOW_SECONDS,
    DEFAULT_SUSTAINED_SECONDS,
    ForeignVehicleGuard,
    getForeignGuard,
    installForeignVehicleGuardFromConfig,
    isDriveForeign,
    makeRealtimeDataForeignRetagger,
    observeSample,
    resetForeignGuard,
    setForeignGuard,
)


class FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture(autouse=True)
def _clearGuardSingleton() -> Generator[None, None, None]:
    """Every test starts + ends with a dark singleton (isolation)."""
    resetForeignGuard()
    yield
    resetForeignGuard()


def _feed(
    guard: ForeignVehicleGuard,
    clock: FakeClock,
    driveId: int,
    ratePerSec: float,
    durationSec: float,
) -> None:
    """Feed samples at ``ratePerSec`` for ``durationSec`` of fake-clock time."""
    interval = 1.0 / ratePerSec
    steps = int(durationSec * ratePerSec)
    for _ in range(steps):
        clock.advance(interval)
        guard.observe(driveId)


# ================================================================================
# Rate logic -- the discriminator
# ================================================================================


def test_eclipseRateNeverTrips():
    """A sustained ~6.3/s (Eclipse K-line ceiling) never trips at a 7/s bar."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    _feed(guard, clock, driveId=5, ratePerSec=6.3, durationSec=30.0)
    assert guard.isDriveForeign(5) is False


def test_sustainedForeignRateTrips():
    """A sustained >7/s stream trips once the window is warm."""
    calls: list[int] = []
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
        retagFn=lambda driveId: calls.append(driveId) or 42,
    )
    _feed(guard, clock, driveId=33, ratePerSec=21.0, durationSec=15.0)
    assert guard.isDriveForeign(33) is True
    assert calls == [33]  # retag fired exactly once on the trip


def test_startOfDriveBurstDoesNotTrip():
    """A dense burst shorter than the window (not warm yet) never trips."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    # 200 samples crammed into the first 2 seconds of the drive -> a huge
    # instantaneous rate, but the drive has only been observed for 2s (< window)
    # so warm-up has not completed and the burst ages out.
    for _ in range(200):
        clock.advance(0.01)
        guard.observe(1)
    assert guard.isDriveForeign(1) is False
    # ...and after the burst, a normal Eclipse rate keeps it clean.
    _feed(guard, clock, driveId=1, ratePerSec=6.0, durationSec=20.0)
    assert guard.isDriveForeign(1) is False


def test_noOpWhenNoOpenDrive():
    """observe(None) is ignored -- rows with no drive can't trip a guard."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    for _ in range(500):
        clock.advance(0.01)
        guard.observe(None)
    assert guard.isDriveForeign(None) is False


def test_driveBoundaryResetsWindow():
    """A new drive_id starts a fresh window -- a prior drive can't leak across."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    _feed(guard, clock, driveId=1, ratePerSec=21.0, durationSec=5.0)  # not warm
    assert guard.isDriveForeign(1) is False
    # Switch to a new drive at a legit rate -- must not inherit drive 1's count.
    _feed(guard, clock, driveId=2, ratePerSec=6.0, durationSec=20.0)
    assert guard.isDriveForeign(2) is False


def test_latchedDriveStaysForeign():
    """Once latched, a drive stays foreign even if the rate later drops."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    _feed(guard, clock, driveId=9, ratePerSec=21.0, durationSec=15.0)
    assert guard.isDriveForeign(9) is True
    # Rate collapses (foreign car idles) -- the latch is sticky.
    _feed(guard, clock, driveId=9, ratePerSec=1.0, durationSec=30.0)
    assert guard.isDriveForeign(9) is True


def test_retagFailureDoesNotPropagate():
    """A retag exception is swallowed (never kills the poll loop)."""
    clock = FakeClock()

    def boom(_driveId: int) -> int:
        raise sqlite3.OperationalError("database is locked")

    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock, retagFn=boom,
    )
    _feed(guard, clock, driveId=7, ratePerSec=21.0, durationSec=15.0)
    assert guard.isDriveForeign(7) is True  # trip still latched


def test_constructorRejectsBadParams():
    with pytest.raises(ValueError):
        ForeignVehicleGuard(thresholdHz=0)
    with pytest.raises(ValueError):
        ForeignVehicleGuard(sustainedSeconds=0)
    with pytest.raises(ValueError):
        ForeignVehicleGuard(measurementWindowSeconds=0)


# ================================================================================
# DB retagger -- the retro-tag SQL
# ================================================================================


@pytest.fixture
def widenedDb() -> Generator[sqlite3.Connection, None, None]:
    """A realtime_data table (narrow CHECK -> widened) with a mixed drive."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE realtime_data ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, parameter_name TEXT, value REAL,"
        " data_source TEXT NOT NULL DEFAULT 'real'"
        "   CHECK (data_source IN ('real','replay','physics_sim','fixture')),"
        " drive_id INTEGER)"
    )
    conn.executemany(
        "INSERT INTO realtime_data (parameter_name, value, data_source, drive_id)"
        " VALUES (?, ?, ?, ?)",
        [
            ("RPM", 800.0, "real", 33),
            ("SPEED", 40.0, "real", 33),
            ("RPM", 900.0, "physics_sim", 33),  # sim row must NOT be re-tagged
            ("RPM", 700.0, "real", 34),  # different drive must NOT be touched
        ],
    )
    ensureDataSourceCheckWidened(conn, "realtime_data")
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


class _DbWrapper:
    """Minimal ObdDatabase stand-in: connect() yields the shared connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def connect(self):  # noqa: ANN201 -- context-manager duck type
        conn = self._conn

        class _Ctx:
            def __enter__(self):
                return conn

            def __exit__(self, *_a):
                return False

        return _Ctx()


def test_retaggerFlipsOnlyRealRowsOfTheDrive(widenedDb):
    """The retagger flips the drive's 'real' rows only -- sim + other drives safe."""
    retag = makeRealtimeDataForeignRetagger(_DbWrapper(widenedDb))
    n = retag(33)
    assert n == 2  # the two real rows on drive 33
    rows = dict(
        widenedDb.execute(
            "SELECT id, data_source FROM realtime_data ORDER BY id",
        ).fetchall()
    )
    assert rows == {1: "foreign", 2: "foreign", 3: "physics_sim", 4: "real"}


# ================================================================================
# Singleton accessors + config install (dark by default)
# ================================================================================


def test_moduleAccessorsAreNoOpWhenDark():
    """With no guard installed, observe/isForeign are safe no-ops."""
    assert getForeignGuard() is None
    observeSample(1)  # must not raise
    assert isDriveForeign(1) is False


def test_installDefaultsDark():
    """No config -> guard stays dark (disabled by default)."""
    installed = installForeignVehicleGuardFromConfig({}, database=None)
    assert installed is False
    assert getForeignGuard() is None


def test_installArmsWhenEnabled():
    """pi.foreignGuard.enabled=true installs the singleton with config values."""
    config = {
        "pi": {
            "foreignGuard": {
                "enabled": True,
                "busRateThresholdHz": 8.5,
                "sustainedSeconds": 12.0,
                "measurementWindowSeconds": 4.0,
            }
        }
    }
    installed = installForeignVehicleGuardFromConfig(config, database=None)
    assert installed is True
    guard = getForeignGuard()
    assert isinstance(guard, ForeignVehicleGuard)
    assert guard._thresholdHz == 8.5
    assert guard._sustainedSeconds == 12.0
    assert guard._measurementWindowSeconds == 4.0


def test_installClearsWhenDisabledAfterArmed():
    """Re-installing with disabled config clears a previously armed guard."""
    setForeignGuard(ForeignVehicleGuard())
    assert getForeignGuard() is not None
    installForeignVehicleGuardFromConfig(
        {"pi": {"foreignGuard": {"enabled": False}}}, database=None,
    )
    assert getForeignGuard() is None


def test_installedGuardObservedViaModuleApi():
    """observeSample/isDriveForeign route to the installed singleton."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    setForeignGuard(guard)
    for _ in range(int(21.0 * 15.0)):
        clock.advance(1.0 / 21.0)
        observeSample(33)
    assert isDriveForeign(33) is True


def test_defaultsAreGrounded():
    """The module defaults match the grounded Eclipse-vs-CAN threshold."""
    assert DEFAULT_BUS_RATE_THRESHOLD_HZ == 7.0
    assert DEFAULT_SUSTAINED_SECONDS == 10.0
    assert DEFAULT_MEASUREMENT_WINDOW_SECONDS == 3.0


# ================================================================================
# Writer integration -- ObdDataLogger stamps 'foreign' for a latched drive
# ================================================================================


class _StubConnection:
    isSimulated = False


def _latchedGuard(driveId: int) -> ForeignVehicleGuard:
    """A guard with ``driveId`` already latched foreign (no retag DB needed)."""
    clock = FakeClock()
    guard = ForeignVehicleGuard(
        thresholdHz=7.0, sustainedSeconds=10.0,
        measurementWindowSeconds=3.0, clock=clock,
    )
    for _ in range(int(21.0 * 15.0)):
        clock.advance(1.0 / 21.0)
        guard.observe(driveId)
    assert guard.isDriveForeign(driveId) is True
    return guard


def test_writerStampsForeignForLatchedDrive(tmp_path):
    """logReading writes 'foreign' once the guard latches the active drive."""
    from datetime import datetime

    from src.pi.obdii.data.logger import ObdDataLogger
    from src.pi.obdii.data.types import LoggedReading
    from src.pi.obdii.database import ObdDatabase
    from src.pi.obdii.drive_id import setCurrentDriveId

    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    dataLogger = ObdDataLogger(_StubConnection(), db)

    now = datetime.now()
    setCurrentDriveId(33)
    try:
        # Dark guard -> normal 'real' write.
        dataLogger.logReading(
            LoggedReading(parameterName="RPM", value=800.0, timestamp=now,
                          unit="rpm"),
        )
        # Armed + latched -> 'foreign' write.
        setForeignGuard(_latchedGuard(33))
        dataLogger.logReading(
            LoggedReading(parameterName="RPM", value=3200.0, timestamp=now,
                          unit="rpm"),
        )
    finally:
        setCurrentDriveId(None)

    with db.connect() as conn:
        rows = [
            tuple(r) for r in conn.execute(
                "SELECT value, data_source FROM realtime_data ORDER BY id",
            ).fetchall()
        ]
    assert rows == [(800.0, "real"), (3200.0, "foreign")]
