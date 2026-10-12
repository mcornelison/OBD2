################################################################################
# File Name: test_sync_client_stored_ack.py
# Purpose/Description: Tests that pushDelta advances a table's high-water mark
#                      only on a matching server stored ack (US-776-i), never
#                      on a bare 2xx.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-11    | Rex (US-776-i)| Initial tests -- advance only on a matching ack
# ================================================================================
################################################################################

"""
pushDelta's advance rule (US-776-i).

The server answers every delta push with ``stored``: per table the
``storedCount`` and ``maxStoredSourceId`` it read back after the commit
(US-776-h).  The Pi advances a table's mark only when that ack says every row
sent is stored: ``storedCount == len(rows)`` and ``maxStoredSourceId ==
max(source_id sent)``.  Anything else -- a short count, a different maximum, or
no ack at all -- is a FAILED push with the mark left where it was.

The fake opener here answers with an ack computed from the request it was
sent, so each test states only how the server's answer differs from "stored".
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.sync import PushStatus, SyncClient

_TABLE = "realtime_data"
_FIRST_ID = 4110647
_ROW_COUNT = 400
_MAX_SENT = _FIRST_ID + _ROW_COUNT - 1  # 4111046, the story's example


# =============================================================================
# Helpers / fixtures
# =============================================================================


class _FakeResponse:
    """Context-manager stand-in for a ``urllib`` response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _sentSourceIds(req: Any) -> dict[str, list[int]]:
    """Table -> the source ids (wire ``id``) a request carried."""
    payload = json.loads(req.data.decode("utf-8"))
    return {
        name: [int(row["id"]) for row in section["rows"]]
        for name, section in payload["tables"].items()
    }


def _ackOpener(
    makeBody: Callable[[dict[str, list[int]]], dict[str, Any]],
) -> Callable[..., _FakeResponse]:
    """Opener answering 200 with ``makeBody(sent source ids per table)``."""

    def _opener(req: Any, timeout: float = 30) -> _FakeResponse:  # noqa: ARG001
        body = makeBody(_sentSourceIds(req))
        return _FakeResponse(json.dumps(body).encode("utf-8"))

    return _opener


def _storedBody(
    sent: dict[str, list[int]], *, dropLast: int = 0, maxShift: int = 0,
) -> dict[str, Any]:
    """The reply a server gives when it stored ``sent`` (less ``dropLast`` rows)."""
    stored: dict[str, Any] = {}
    for name, ids in sent.items():
        kept = sorted(ids)[: len(ids) - dropLast]
        stored[name] = {
            "storedCount": len(kept),
            "maxStoredSourceId": (max(kept) + maxShift) if kept else None,
        }
    return {"status": "ok", "tablesProcessed": {}, "stored": stored}


def _config(dbPath: str) -> dict[str, Any]:
    return {
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": dbPath},
            "companionService": {
                "enabled": True,
                "baseUrl": "http://10.27.27.10:8000",
                "apiKeyEnv": "COMPANION_API_KEY",
                "syncTimeoutSeconds": 30,
                "batchSize": 500,
                "retryMaxAttempts": 1,
                "retryBackoffSeconds": [0],
            },
        },
    }


@pytest.fixture(autouse=True)
def _apiKey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPANION_API_KEY", "test-key-776i")


@pytest.fixture
def dbPath() -> Iterator[str]:
    """Pi DB holding 400 realtime_data rows, ids 4110647..4111046, mark 4110646."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    sync_log.initDb(conn)
    conn.execute(
        "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY, "
        "timestamp TEXT NOT NULL, parameter_name TEXT NOT NULL, value REAL NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO realtime_data (id, timestamp, parameter_name, value) "
        "VALUES (?, ?, ?, ?)",
        [
            (_FIRST_ID + i, "2026-10-11T13:14:00Z", "RPM", 800.0 + i)
            for i in range(_ROW_COUNT)
        ],
    )
    sync_log.updateHighWaterMark(conn, _TABLE, _FIRST_ID - 1, "seed", status="ok")
    conn.commit()
    conn.close()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def _mark(dbPath: str) -> tuple[int, str]:
    with sqlite3.connect(dbPath) as conn:
        lastId, _, _, status = sync_log.getHighWaterMark(conn, _TABLE)
    return lastId, status


def _push(dbPath: str, opener: Callable[..., Any]) -> Any:
    client = SyncClient(_config(dbPath), httpOpener=opener, sleep=lambda _s: None)
    return client.pushDelta(_TABLE)


# =============================================================================
# A matching ack advances the mark
# =============================================================================


class TestMatchingAckAdvances:
    """storedCount == rows sent AND maxStoredSourceId == max sent -> advance."""

    def test_matchingAck_advancesToMaxStored(self, dbPath: str) -> None:
        """
        Given: 400 rows sent, max 4111046
        When: the server acks storedCount 400, maxStoredSourceId 4111046
        Then: OK, 400 rows pushed, the mark is 4111046
        """
        result = _push(dbPath, _ackOpener(_storedBody))

        assert result.status is PushStatus.OK
        assert result.rowsPushed == _ROW_COUNT
        assert _mark(dbPath) == (_MAX_SENT, "ok")


# =============================================================================
# Anything else is FAILED with the mark held
# =============================================================================


class TestMismatchedAckFails:
    """A 2xx is not delivery: no matching ack -> FAILED, mark unchanged."""

    def test_shortStoredCount_failed_markUnchanged_mismatchLogged(
        self, dbPath: str, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: 400 rows sent, max 4111046
        When: the server acks storedCount 398, maxStoredSourceId 4111044
        Then: FAILED, the mark stays 4110646 (status 'failed'), and one WARNING
              names table, sent, stored, maxSent and maxStored
        """
        caplog.set_level(logging.WARNING, logger="src.pi.sync.client")

        result = _push(dbPath, _ackOpener(lambda s: _storedBody(s, dropLast=2)))

        assert result.status is PushStatus.FAILED
        assert result.rowsPushed == 0
        assert _mark(dbPath) == (_FIRST_ID - 1, "failed")
        expected = (
            "stored-count mismatch | table=realtime_data | sent=400 stored=398 | "
            "maxSent=4111046 maxStored=4111044"
        )
        assert expected in caplog.text
        assert expected in result.reason

    def test_noAck_failed_markUnchanged(
        self, dbPath: str, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: a server on the old build that answers 200 with no 'stored' block
        When: the Pi pushes 400 rows
        Then: FAILED, mark unchanged -- there is no fall-back to a bare 2xx
        """
        caplog.set_level(logging.WARNING, logger="src.pi.sync.client")
        oldServer = _ackOpener(lambda _s: {"status": "ok", "tablesProcessed": {}})

        result = _push(dbPath, oldServer)

        assert result.status is PushStatus.FAILED
        assert _mark(dbPath) == (_FIRST_ID - 1, "failed")
        assert (
            "stored-count mismatch | table=realtime_data | sent=400 stored=missing | "
            "maxSent=4111046 maxStored=missing"
        ) in caplog.text

    def test_differentMaxStoredSourceId_failed_markUnchanged(self, dbPath: str) -> None:
        """
        Given: 400 rows sent, max 4111046
        When: the ack count is 400 but its maximum is 4111047
        Then: FAILED, mark unchanged -- the count alone is not enough
        """
        result = _push(dbPath, _ackOpener(lambda s: _storedBody(s, maxShift=1)))

        assert result.status is PushStatus.FAILED
        assert _mark(dbPath) == (_FIRST_ID - 1, "failed")

    def test_ackForOtherTableOnly_failed(self, dbPath: str) -> None:
        """
        Given: a reply whose 'stored' block names a different table
        When: the Pi pushes realtime_data
        Then: FAILED, mark unchanged -- another table's ack is not this one's
        """
        result = _push(dbPath, _ackOpener(lambda _s: {
            "stored": {"connection_log": {"storedCount": 400, "maxStoredSourceId": _MAX_SENT}},
        }))

        assert result.status is PushStatus.FAILED
        assert _mark(dbPath) == (_FIRST_ID - 1, "failed")

    def test_unparseableBody_failed(self, dbPath: str) -> None:
        """
        Given: a 200 whose body is not JSON
        When: the Pi pushes
        Then: FAILED, mark unchanged
        """
        result = _push(dbPath, lambda _req, timeout=30: _FakeResponse(b"<html>ok</html>"))

        assert result.status is PushStatus.FAILED
        assert _mark(dbPath) == (_FIRST_ID - 1, "failed")

    def test_mismatch_isNotAServerRejection_noQuarantineCount(self, dbPath: str) -> None:
        """
        Given: a short-store ack
        When: the push fails on it
        Then: the US-391 consecutive server-rejection counter is not advanced
              (the quarantine path is unchanged by this story)
        """
        _push(dbPath, _ackOpener(lambda s: _storedBody(s, dropLast=1)))

        with sqlite3.connect(dbPath) as conn:
            sync_log.ensureQuarantineSchema(conn)
            failures, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
        assert failures == 0
        assert quarantinedAt is None

    def test_retryAfterMismatch_resendsSameRows_thenAdvances(self, dbPath: str) -> None:
        """
        Given: a push that failed on a short ack
        When: the next push gets a matching ack
        Then: it re-sent the same 400 rows and the mark advances to 4111046
        """
        _push(dbPath, _ackOpener(lambda s: _storedBody(s, dropLast=2)))
        sentOnRetry: list[list[int]] = []

        def _recordingBody(sent: dict[str, list[int]]) -> dict[str, Any]:
            sentOnRetry.append(sent[_TABLE])
            return _storedBody(sent)

        result = _push(dbPath, _ackOpener(_recordingBody))

        assert result.status is PushStatus.OK
        assert sentOnRetry[0] == list(range(_FIRST_ID, _MAX_SENT + 1))
        assert _mark(dbPath) == (_MAX_SENT, "ok")
