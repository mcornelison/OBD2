################################################################################
# File Name: test_sync_client_residual.py
# Purpose/Description: US-795(a) -- every POST the Pi makes carries what it
#                      STILL holds after that batch: total, exact/at-least,
#                      and the drive/sensor split the CIO ruled.
# Author: Atlas (Architect) -- US-795(a), CIO-directed build
# Creation Date: 2026-10-06
################################################################################
"""The Pi sends its residual on every push (US-795(a)).

MEASURED 2026-10-06: the server half existed since v0028, and the Pi NEVER sent
``residual`` -- 0 of 234,331 sync_history rows carried one. These tests pin the
producer: the delta push, the snapshot push and the drive-counter push all
carry it, so the newest contact the server sees always measured the queue.

Residual = the backlog read just before the POST, MINUS this batch's NEW rows
(pk above the cursor; a re-sent modified row was never in the count). A count
that fails leaves the field OUT -- it never blocks a push and never sends 0.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from typing import Any

import pytest

from src.common.edr.sync_contract import EDR_SYNC_TABLES
from src.pi.data import sync_log
from src.pi.sync import backlog as backlog_module
from src.pi.sync import client as client_module
from src.pi.sync.backlog import SyncBacklog, residualAfterBatch
from src.pi.sync.client import SyncClient

_SENSOR = EDR_SYNC_TABLES[0]


# ================================================================================
# The pure calculation
# ================================================================================


class TestResidualAfterBatch:

    def test_theBatchsNewRowsLeaveTheirOwnGroup(self) -> None:
        backlog = SyncBacklog(perTable={'realtime_data': 500, _SENSOR: 1000})
        assert residualAfterBatch(
            backlog, batchTable='realtime_data', batchNewRows=500,
            sensorTables=EDR_SYNC_TABLES,
        ) == {'outstandingRows': 1000, 'complete': True,
              'groups': {'drive': 0, 'sensor': 1000}}

    def test_aSensorBatchLeavesTheSensorGroup(self) -> None:
        backlog = SyncBacklog(perTable={'realtime_data': 7, _SENSOR: 1000})
        assert residualAfterBatch(
            backlog, batchTable=_SENSOR, batchNewRows=500, sensorTables=EDR_SYNC_TABLES,
        )['groups'] == {'drive': 7, 'sensor': 500}

    def test_anUnreadableTable_makesItAtLeast(self) -> None:
        backlog = SyncBacklog(perTable={'realtime_data': 3}, unreadableTables=('dtc_log',))
        report = residualAfterBatch(
            backlog, batchTable=None, batchNewRows=0, sensorTables=EDR_SYNC_TABLES,
        )
        assert report['complete'] is False and report['outstandingRows'] == 3

    def test_aFailedCount_isNoReport_neverZero(self) -> None:
        assert residualAfterBatch(
            SyncBacklog(error='database is locked'), batchTable=None, batchNewRows=0,
            sensorTables=EDR_SYNC_TABLES,
        ) is None

    def test_neverSubtractsMoreThanWasCounted(self) -> None:
        """A batch can hold more 'new' rows than the earlier count saw (rows
        written between the count and the read); the residual floors at 0."""
        backlog = SyncBacklog(perTable={'realtime_data': 3})
        report = residualAfterBatch(
            backlog, batchTable='realtime_data', batchNewRows=5, sensorTables=EDR_SYNC_TABLES,
        )
        assert report['outstandingRows'] == 0


# ================================================================================
# The wire -- what the server actually receives
# ================================================================================


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def read(self) -> bytes:
        return b'{"status":"ok"}'


def _recordingOpener() -> Any:
    bodies: list[dict] = []

    def _opener(req: Any, timeout: float = 30) -> _Response:  # noqa: ARG001
        bodies.append(json.loads(req.data.decode('utf-8')))
        return _Response()

    _opener.bodies = bodies  # type: ignore[attr-defined]
    return _opener


@pytest.fixture
def dbPath() -> Any:
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    for tableName in sync_log.IN_SCOPE_TABLES:
        if tableName in sync_log.SNAPSHOT_TABLES:
            pk = 'id' if tableName == 'profiles' else 'vin'
            conn.execute(f'CREATE TABLE IF NOT EXISTS {tableName} ({pk} TEXT PRIMARY KEY)')
            continue
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS {tableName} '
            f'({sync_log.PK_COLUMN[tableName]} INTEGER PRIMARY KEY AUTOINCREMENT)',
        )
    conn.execute('DROP TABLE realtime_data')
    conn.execute(
        'CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, value REAL)',
    )
    conn.executemany('INSERT INTO realtime_data (value) VALUES (?)', [(i,) for i in range(5)])
    conn.executemany(f'INSERT INTO {_SENSOR} DEFAULT VALUES', [()] * 3)
    conn.commit()
    conn.close()
    yield path
    os.remove(path)


def _client(dbPath: str, opener: Any, monkeypatch: pytest.MonkeyPatch) -> SyncClient:
    monkeypatch.setenv('COMPANION_API_KEY', 'k')
    return SyncClient(
        {
            'deviceId': 'test-device',
            'pi': {
                'database': {'path': dbPath},
                'companionService': {
                    'enabled': True, 'baseUrl': 'http://server.test:8000',
                    'apiKeyEnv': 'COMPANION_API_KEY', 'batchSize': 500,
                    'retryBackoffSeconds': [],
                },
            },
        },
        httpOpener=opener, sleep=lambda _s: None,
    )


class TestEveryPushCarriesIt:

    def test_aDeltaPush_carriesWhatRemainsAfterIt(self, dbPath, monkeypatch) -> None:
        opener = _recordingOpener()
        _client(dbPath, opener, monkeypatch).pushDelta('realtime_data')

        (body,) = opener.bodies
        assert body['residual'] == {
            'outstandingRows': 3, 'complete': True, 'groups': {'drive': 0, 'sensor': 3},
        }

    def test_theDriveCounterPush_carriesItToo(self, dbPath, monkeypatch) -> None:
        conn = sqlite3.connect(dbPath)
        conn.execute('CREATE TABLE IF NOT EXISTS drive_counter (id INTEGER PRIMARY KEY, last_drive_id INTEGER)')
        conn.execute('INSERT OR REPLACE INTO drive_counter (id, last_drive_id) VALUES (1, 7)')
        conn.commit()
        conn.close()
        opener = _recordingOpener()

        _client(dbPath, opener, monkeypatch).pushDriveCounter(force=True)

        (body,) = opener.bodies
        assert body['residual']['outstandingRows'] == 8
        assert body['residual']['groups'] == {'drive': 5, 'sensor': 3}

    def test_aFailedCount_omitsTheField_andThePushStillHappens(self, dbPath, monkeypatch) -> None:
        monkeypatch.setattr(
            client_module, 'countOutstandingRows',
            lambda *_a, **_k: SyncBacklog(error='database is locked'),
        )
        opener = _recordingOpener()

        result = _client(dbPath, opener, monkeypatch).pushDelta('realtime_data')

        (body,) = opener.bodies
        assert 'residual' not in body
        assert result.rowsPushed == 5

    def test_aCountThatRaises_neverBlocksThePush(self, dbPath, monkeypatch) -> None:
        def _boom(*_a: Any, **_k: Any) -> SyncBacklog:
            raise RuntimeError('unexpected')

        monkeypatch.setattr(client_module, 'countOutstandingRows', _boom)
        opener = _recordingOpener()

        result = _client(dbPath, opener, monkeypatch).pushDelta('realtime_data')

        assert 'residual' not in opener.bodies[0]
        assert result.rowsPushed == 5

    def test_theCountUsesTheSharedBacklogReader(self) -> None:
        """One measurement, one implementation: the client imports the same
        countOutstandingRows the power-watch custody verdict uses."""
        assert client_module.countOutstandingRows is backlog_module.countOutstandingRows
