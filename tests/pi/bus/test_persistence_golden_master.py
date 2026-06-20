################################################################################
# File Name: test_persistence_golden_master.py
# Purpose/Description: Byte-identical golden master for EDR slice 1 (US-383).
#     Proves the bus path (publish -> PersistenceSubscriber.handleSample ->
#     ObdDataLogger.logReading) writes realtime_data rows EQUAL to the existing
#     inline logReading path on the columns that matter
#     (parameter_name, value, unit, profile_id, drive_id, data_source).
#     id and the write-time timestamp are excluded.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Golden-master proof that the bus persistence path is byte-identical."""

from datetime import datetime

from pi.bus.bus import SampleBus
from pi.bus.persistence_subscriber import PersistenceSubscriber
from pi.bus.sample import QoS, Sample
from pi.obdii.data.logger import ObdDataLogger
from pi.obdii.data.types import LoggedReading
from pi.obdii.database import ObdDatabase

# The columns the byte-identical invariant pins (id + write-time timestamp excluded).
_COLS = "parameter_name, value, unit, profile_id, drive_id, data_source"

_PROFILE_ID = "daily"

READINGS = [
    ("RPM", 3500.0, "rpm"),
    ("COOLANT_TEMP", 92.0, "degC"),
    ("SPEED", 64.0, "km/h"),
]


def _newDb(tmp_path, name):
    """Create an initialized SQLite DB with a seeded profile (FK target)."""
    db = ObdDatabase(str(tmp_path / name))
    db.initialize()
    # realtime_data.profile_id FK-references profiles(id); seed the row so both
    # paths can write a non-null profile_id (FK enforcement is ON).
    with db.connect() as conn:
        conn.cursor().execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            (_PROFILE_ID, "Daily"),
        )
    return db


def _rows(db):
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLS} FROM realtime_data ORDER BY id")
        # sqlite3.Row -> tuple so equality compares values, not row objects.
        return [tuple(r) for r in cur.fetchall()]


def test_busPathProducesByteIdenticalRealtimeRows(tmp_path):
    # (a) old path: logReading directly.
    dbA = _newDb(tmp_path, "a.db")
    loggerA = ObdDataLogger(
        connection=None, database=dbA, profileId=_PROFILE_ID, dataSource="real"
    )
    for name, val, unit in READINGS:
        loggerA.logReading(LoggedReading(name, val, datetime.now(), unit, None))

    # (b) new path: publish -> PersistenceSubscriber -> the same logReading.
    dbB = _newDb(tmp_path, "b.db")
    loggerB = ObdDataLogger(
        connection=None, database=dbB, profileId=_PROFILE_ID, dataSource="real"
    )
    bus = SampleBus()
    sub = bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
    ps = PersistenceSubscriber(sub, loggerB)
    for i, (name, val, unit) in enumerate(READINGS, start=1):
        bus.publish(
            Sample(
                topic=f"raw.obd.{name}",
                source="obd",
                value=val,
                unit=unit,
                tsUtc="2026-06-18T00:00:00Z",
                tsCapture=float(i),
                driveId=None,
                dataSource="real",
                seq=i,
            )
        )
        ps.handleSample(sub.poll())  # drain inline -> deterministic, no thread

    assert _rows(dbA) == _rows(dbB)
    assert len(_rows(dbB)) == len(READINGS)
