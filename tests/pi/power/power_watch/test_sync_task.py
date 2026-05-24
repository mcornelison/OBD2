################################################################################
# File Name: test_sync_task.py
# Purpose/Description: Tests: SyncWithServerTask CIO state machine --
#                      reachable?/sync/retry-once/classify; benign skip writes
#                      no record; real fault recorded; run() never raises.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T5 sync_with_server tests.
# ================================================================================
################################################################################
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask


def _task(reachable, syncSeq, rec):
    """Build a SyncWithServerTask whose runSync pops syncSeq each call and
    raises any item that is an Exception (else returns success)."""
    seq = iter(syncSeq)

    def runSync():
        item = next(seq)
        if isinstance(item, Exception):
            raise item

    return SyncWithServerTask(
        serverReachable=lambda: reachable,
        runSync=runSync,
        writeRecord=rec,
    )


def test_server_unavailable_is_benign_skip():
    recs = []
    result = _task(False, [], recs.append).run()
    assert result == OutcomeKind.SERVER_UNAVAILABLE
    assert recs == []  # benign -> no real-error record


def test_sync_ok_first_try():
    assert _task(True, [None], [].append).run() == OutcomeKind.OK


def test_sync_fails_then_retry_ok():
    assert _task(True, [RuntimeError("net"), None], [].append).run() == OutcomeKind.OK


def test_sync_fails_twice():
    recs = []
    result = _task(True, [RuntimeError("net"), RuntimeError("net")], recs.append).run()
    assert result == OutcomeKind.SYNC_FAILED_AFTER_RETRY
    assert len(recs) == 1  # logged + recorded, then continue


def test_real_error_is_recorded():
    recs = []
    result = _task(True, [ValueError("corrupt db")], recs.append).run()
    assert result == OutcomeKind.REAL_ERROR
    assert recs and recs[0][0] == OutcomeKind.REAL_ERROR
