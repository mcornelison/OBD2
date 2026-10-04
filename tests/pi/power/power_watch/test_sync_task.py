################################################################################
# File Name: test_sync_task.py
# Purpose/Description: Tests: SyncWithServerTask CIO state machine --
#                      home?/sync/retry/classify; every run writes one
#                      outcome record; run() never raises.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T5 sync_with_server tests.
# 2026-10-01    | Rex     | US-776-c: gated on the home state (AWAY skips).
# 2026-10-01    | Rex     | US-776-g: retries run to a ceiling on a fake clock.
# 2026-10-01    | Rex     | US-776-d: one record per run, the AWAY skip included.
# ================================================================================
################################################################################
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask


def _task(reachable, syncSeq, rec, *, ceilingSec=60.0):
    """Build a SyncWithServerTask whose runSync pops syncSeq each call and
    raises any item that is an Exception (else returns success). Waits run
    on a fake clock that only the task's own sleeps advance."""
    seq = iter(syncSeq)
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    def runSync():
        item = next(seq)
        if isinstance(item, Exception):
            raise item

    return SyncWithServerTask(
        homeState=lambda: (
            HomeNetworkState.AT_HOME_SERVER_REACHABLE if reachable else HomeNetworkState.AWAY
        ),
        runSync=runSync,
        writeRecord=rec,
        ceilingSec=ceilingSec,
        sleepFn=sleep,
        monotonic=lambda: now[0],
    )


def test_away_is_benign_skip():
    recs = []
    result = _task(False, [], recs.append).run()
    assert result == OutcomeKind.AWAY
    assert [r[0] for r in recs] == [OutcomeKind.AWAY]  # US-776-d: the skip is recorded too


def test_sync_ok_first_try():
    assert _task(True, [None], [].append).run() == OutcomeKind.DELIVERED


def test_sync_fails_then_retry_ok():
    assert _task(True, [RuntimeError("net"), None], [].append).run() == OutcomeKind.DELIVERED


def test_sync_fails_until_ceiling():
    # A 3 s ceiling leaves room for exactly two attempts (0 s and 2 s).
    recs = []
    result = _task(
        True, [RuntimeError("net"), RuntimeError("net")], recs.append, ceilingSec=3.0
    ).run()
    assert result == OutcomeKind.AT_HOME_SERVER_DOWN
    assert len(recs) == 1  # logged + recorded, then continue


def test_real_error_is_recorded():
    recs = []
    result = _task(True, [ValueError("corrupt db")], recs.append).run()
    assert result == OutcomeKind.REAL_ERROR
    assert recs and recs[0][0] == OutcomeKind.REAL_ERROR
