################################################################################
# File Name: test_sync_custody.py
# Purpose/Description: US-621 -- guards for the pre-poweroff sync CUSTODY
#                      record. The properties under test are the ones the CIO's
#                      2026-08-28 shutdown lacked: the shutdown speaks on EVERY
#                      disposition (delivered / outstanding / unknown), it says
#                      so above the lastResort WARNING floor so the line cannot
#                      be dropped by a logging-config regression (US-566), and
#                      it leaves a durable record that survives the poweroff.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- shutdown sync-custody guards.
# ================================================================================
################################################################################
"""US-621 guards for the pre-poweroff sync-custody record."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.pi.power.power_watch.sync_custody import (
    CUSTODY_RECORD_SCHEMA_VERSION,
    SYNC_CUSTODY_PREFIX,
    buildCustodyRecord,
    emitSyncCustody,
    makeSyncCustodyHook,
)
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    BACKLOG_UNKNOWN,
    SyncBacklog,
)

_DELIVERED = SyncBacklog(perTable={"realtime_data": 0}, unreadableTables=())
_OUTSTANDING = SyncBacklog(
    perTable={"realtime_data": 14500, "power_log": 3}, unreadableTables=()
)
_UNKNOWN = SyncBacklog(
    perTable={}, unreadableTables=("realtime_data",), error="locked"
)


# --------------------------------------------------------------------------- #
# It is never silent -- on ANY disposition
# --------------------------------------------------------------------------- #


class TestTheShutdownAlwaysSpeaks:
    """There is no backlog state for which this emits nothing."""

    @pytest.mark.parametrize(
        ("backlog", "verdict"),
        [
            (_DELIVERED, BACKLOG_DELIVERED),
            (_OUTSTANDING, BACKLOG_OUTSTANDING),
            (_UNKNOWN, BACKLOG_UNKNOWN),
        ],
    )
    def test_emitSyncCustody_emitsOnEveryDisposition(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        backlog: SyncBacklog,
        verdict: str,
    ) -> None:
        """
        Given: any backlog state at poweroff
        When: custody is emitted
        Then: exactly one prefixed line names that verdict

        US-621 VC-1 + VC-2: never silent, and "shut down, queue empty" must be
        distinguishable from "shut down, N rows still local". One prefix means
        ONE grep answers "did my data get away?" for every shutdown.
        """
        # Arrange
        caplog.set_level(logging.DEBUG)

        # Act
        line = emitSyncCustody(
            backlog=backlog, recordPath=str(tmp_path / "custody.json")
        )

        # Assert
        assert SYNC_CUSTODY_PREFIX in line
        assert verdict in line
        emitted = [
            r for r in caplog.records if SYNC_CUSTODY_PREFIX in r.getMessage()
        ]
        assert len(emitted) == 1

    @pytest.mark.parametrize(
        "backlog", [_DELIVERED, _OUTSTANDING, _UNKNOWN]
    )
    def test_emitSyncCustody_clearsTheLastResortWarningFloor(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        backlog: SyncBacklog,
    ) -> None:
        """
        Given: any backlog state
        When: custody is emitted
        Then: the record is logged at WARNING or above

        The US-566 lesson, measured on chi-eclipse-01 2026-08-21: this service
        ran with no root handler, so logging.lastResort (level WARNING) was the
        only sink and the ENTIRE INFO TIER went on the floor. A custody line at
        INFO would be invisible in exactly the degraded conditions that make
        custody worth reporting.
        """
        # Arrange
        caplog.set_level(logging.DEBUG)

        # Act
        emitSyncCustody(
            backlog=backlog, recordPath=str(tmp_path / "custody.json")
        )

        # Assert
        emitted = [
            r for r in caplog.records if SYNC_CUSTODY_PREFIX in r.getMessage()
        ]
        assert emitted, "custody line was not emitted at all"
        assert all(r.levelno >= logging.WARNING for r in emitted)

    def test_emitSyncCustody_outstandingIsLoudest(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: rows that never left the Pi
        When: custody is emitted
        Then: it is an ERROR, not a WARNING

        Stranded capture is a data-custody failure, not an operational note.
        """
        # Arrange
        caplog.set_level(logging.DEBUG)

        # Act
        emitSyncCustody(
            backlog=_OUTSTANDING, recordPath=str(tmp_path / "custody.json")
        )

        # Assert
        emitted = [
            r for r in caplog.records if SYNC_CUSTODY_PREFIX in r.getMessage()
        ]
        assert emitted[0].levelno == logging.ERROR


class TestTheRecordIsDurableAndStructured:
    """A JSON record survives the poweroff; prose in a journal may not."""

    def test_emitSyncCustody_writesTheOutstandingCountAsANumber(
        self, tmp_path: Path
    ) -> None:
        """
        Given: an outstanding backlog
        When: custody is emitted
        Then: the record carries machine-readable per-table counts

        Stringifying the counts into a prose `detail` would make "how many rows
        were stranded across the last ten shutdowns?" unanswerable without
        parsing English.
        """
        # Arrange
        recordPath = tmp_path / "custody.json"

        # Act
        emitSyncCustody(backlog=_OUTSTANDING, recordPath=str(recordPath))

        # Assert
        rec = json.loads(recordPath.read_text(encoding="utf-8"))
        assert rec["verdict"] == BACKLOG_OUTSTANDING
        assert rec["outstandingRows"] == 14503
        assert rec["perTable"]["realtime_data"] == 14500
        assert rec["schema"] == CUSTODY_RECORD_SCHEMA_VERSION
        assert rec["ts"]

    def test_emitSyncCustody_deliveredRecordIsWrittenToo(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a fully-drained queue
        When: custody is emitted
        Then: a record still lands on disk

        US-621 VC-2 exactly: inspecting the record after a clean shutdown with
        an empty queue must find an explicit statement. Writing only on failure
        makes "no record" mean both "all good" and "the recorder never ran".
        """
        # Arrange
        recordPath = tmp_path / "custody.json"

        # Act
        emitSyncCustody(backlog=_DELIVERED, recordPath=str(recordPath))

        # Assert
        rec = json.loads(recordPath.read_text(encoding="utf-8"))
        assert rec["verdict"] == BACKLOG_DELIVERED
        assert rec["outstandingRows"] == 0

    def test_buildCustodyRecord_marksALowerBoundWhenSomethingWasUnreadable(
        self,
    ) -> None:
        """
        Given: outstanding rows AND a table that could not be read
        When: the record is built
        Then: it flags that the count is not complete

        A reader must be able to tell "exactly 80 stranded" from "at least 80
        stranded, and we could not see one table".
        """
        # Arrange
        backlog = SyncBacklog(
            perTable={"realtime_data": 80}, unreadableTables=("power_log",)
        )

        # Act
        rec = buildCustodyRecord(backlog, nowIso="2026-08-29T00:00:00Z")

        # Assert
        assert rec["countIsComplete"] is False
        assert rec["unreadableTables"] == ["power_log"]

    def test_emitSyncCustody_unwritableRecordPathStillLogs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a record path that cannot be written
        When: custody is emitted
        Then: the journal line is still produced and nothing raises

        Two independent channels, so losing one does not lose the fact.
        """
        # Arrange
        caplog.set_level(logging.DEBUG)

        # Act
        line = emitSyncCustody(
            backlog=_OUTSTANDING, recordPath="/proc/cpuinfo/nope/custody.json"
        )

        # Assert
        assert SYNC_CUSTODY_PREFIX in line
        assert any(
            SYNC_CUSTODY_PREFIX in r.getMessage() for r in caplog.records
        )


class TestTheHookNeverBlocksPoweroff:
    """It runs immediately before `systemctl poweroff`."""

    def test_makeSyncCustodyHook_readerRaises_hookStillReturns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a backlog reader that raises
        When: the pre-poweroff hook runs
        Then: it returns quietly-ish (logged) rather than propagating

        Bookkeeping is never worth leaving a Pi up on a dying battery -- the
        same contract the US-526 drain close already holds.
        """
        # Arrange
        caplog.set_level(logging.DEBUG)

        def _boom() -> SyncBacklog:
            raise RuntimeError("reader exploded")

        hook = makeSyncCustodyHook(
            recordPath=str(tmp_path / "custody.json"), backlogReader=_boom
        )

        # Act / Assert -- must not raise
        hook()

    def test_makeSyncCustodyHook_readerRaises_reportsUnknownNotDelivered(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a backlog reader that raises
        When: the pre-poweroff hook runs
        Then: the recorded verdict is UNKNOWN

        Swallowing the fault into a DELIVERED record would manufacture the
        exact false assurance this story removes.
        """
        # Arrange
        recordPath = tmp_path / "custody.json"

        def _boom() -> SyncBacklog:
            raise RuntimeError("reader exploded")

        hook = makeSyncCustodyHook(
            recordPath=str(recordPath), backlogReader=_boom
        )

        # Act
        hook()

        # Assert
        rec = json.loads(recordPath.read_text(encoding="utf-8"))
        assert rec["verdict"] == BACKLOG_UNKNOWN

    def test_makeSyncCustodyHook_readsTheBacklogAtCallTimeNotBuildTime(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a backlog that drains between hook construction and poweroff
        When: the hook runs
        Then: it reports the state AT POWEROFF, not the state at wiring time

        The hook is built once at service start and fires minutes or hours
        later; capturing a count at build time would record a number that was
        never true at the moment custody actually transferred.
        """
        # Arrange
        recordPath = tmp_path / "custody.json"
        states = iter([_OUTSTANDING, _DELIVERED])
        hook = makeSyncCustodyHook(
            recordPath=str(recordPath), backlogReader=lambda: next(states)
        )

        # Act -- first shutdown sees the backlog, second sees it drained
        hook()
        first = json.loads(recordPath.read_text(encoding="utf-8"))["verdict"]
        hook()
        second = json.loads(recordPath.read_text(encoding="utf-8"))["verdict"]

        # Assert
        assert first == BACKLOG_OUTSTANDING
        assert second == BACKLOG_DELIVERED
