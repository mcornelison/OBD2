################################################################################
# File Name: test_purge_logs_every_run.py
# Purpose/Description: ARCH-060 -- the retention purge must log EVERY run,
#   including the runs that delete nothing. "Ran and deleted 0" and "never ran"
#   were indistinguishable, and that ambiguity cost two days on F-114.
# Author: Atlas (architect) -- CIO-directed
# Creation Date: 2026-09-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-26    | Atlas          | Initial -- silence is not a record.
#               | (ARCH-060)     |
# ================================================================================
################################################################################
"""A log that only speaks when something happened is not a log.

🔴 WHAT THIS COST, AND IT IS THE REASON THE CIO ASKED FOR IT.
``maybePurge`` logged only ``if imuDeleted or lightDeleted or derivedDeleted``. So a
run that deleted nothing was SILENT -- and silence in that journal means two
completely different things that cannot be told apart:

  * "the purge ran and removed those rows"
  * "the purge never ran; something else removed them"

When ~5.35 M rows went missing from ``edr_imu_sample`` (F-114), the journal was
silent. I concluded the purge did it, later WITHDREW that, and then had to
re-derive the whole chain -- getting it backwards once on the way. The final
exclusion only became possible by measuring the ABSENCE of purge lines across a
229 MB journal, which works only because the purge had been noisy in an earlier
period. **Had it been quiet throughout, the question would have been unanswerable.**

⇒ The fix is that the purge states what it did on EVERY run, including zero. Then
"ran, deleted 0" and "never ran" are permanently distinguishable.

⚠️ This is the ``specs/anti-patterns.md`` inert-guard family seen from the other
side: not a check that cannot fail, but a RECORD that cannot testify. The presence
of a log line is evidence about activity only if its absence is also evidence.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber  # noqa: E402


class _Sub(EdrPersistenceSubscriber):
    """Minimal stand-in: only the purge cadence and its logging are exercised."""

    def __init__(self, deletions, *, interval=0.0, days=45):
        self._deletions = deletions
        self._raise = isinstance(deletions, Exception)
        self._lastPurgeMono = -1e9
        self._retentionCheckIntervalS = interval
        self._retentionDays = days
        self._monoNow = 1000.0

    def _monotonic(self):
        return self._monoNow

    def purgeExpired(self):
        if self._raise:
            raise self._deletions
        return self._deletions


def _purgeLines(caplog):
    return [r.getMessage() for r in caplog.records
            if "retention purge" in r.getMessage()]


# --------------------------------------------------------------------------
# 🔴 THE TEST THAT MAKES THE JOURNAL ABLE TO TESTIFY
# --------------------------------------------------------------------------

def test_aRunThatDeletesNOTHINGStillLogs(caplog):
    """🔴 THE WHOLE POINT. Zero deletions must produce a line.

    Without this, "ran and deleted nothing" is indistinguishable from "never ran",
    which is exactly the ambiguity that made the F-114 inversion possible.
    """
    sub = _Sub((0, 0, 0))
    with caplog.at_level(logging.INFO):
        assert sub.maybePurge() is True
    lines = _purgeLines(caplog)
    assert lines, "a purge that deleted nothing logged NOTHING -- the defect"
    # ⚠️ This assertion was wrong on its first pass: it looked for the CHARACTER
    # "0", which the line does not contain because it says "deleted nothing" in
    # words. What matters is that the line states the run happened and that it
    # removed nothing -- not that a particular digit appears in it.
    assert any("ran" in ln.lower() for ln in lines)
    assert any("nothing" in ln.lower() for ln in lines)


def test_theZeroLineSaysITRAN_notJustZero(caplog):
    """A reader must be able to tell activity from absence at a glance."""
    sub = _Sub((0, 0, 0))
    with caplog.at_level(logging.INFO):
        sub.maybePurge()
    joined = " ".join(_purgeLines(caplog)).lower()
    assert "ran" in joined or "no rows" in joined or "nothing" in joined


def test_aRunThatDELETESStillLogsTheCounts(caplog):
    """The pre-existing behaviour must survive -- this adds, it does not replace."""
    sub = _Sub((73798, 12, 4))
    with caplog.at_level(logging.INFO):
        sub.maybePurge()
    joined = " ".join(_purgeLines(caplog))
    assert "73798" in joined
    assert "12" in joined
    assert "4" in joined


def test_theRetentionWINDOWIsInEveryLine(caplog):
    """🔴 MEASURED RELEVANCE: F-114's cause was the window being 7 when config said
    45. A line that reports deletions without the window it applied cannot answer
    "which retention was in force?" -- which is the question that settled F-114."""
    sub = _Sub((0, 0, 0), days=45)
    with caplog.at_level(logging.INFO):
        sub.maybePurge()
    assert any("45" in ln for ln in _purgeLines(caplog))


def test_aSuppressedRunLogsNOTHING_becauseItDidNotRun(caplog):
    """⚠️ THE OTHER HALF, AND IT MATTERS. Cadence suppression must stay silent.

    If a not-yet-due call also logged, the journal would fill with lines that do
    not describe a run, and "the purge ran" would stop meaning anything. Silence
    here is correct BECAUSE the noisy case is now unambiguous.
    """
    sub = _Sub((0, 0, 0), interval=3600.0)
    with caplog.at_level(logging.INFO):
        assert sub.maybePurge() is True        # first call: due
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert sub.maybePurge() is False       # second: not due
    assert _purgeLines(caplog) == []


def test_aFailingPurgeLogsTheFAILURE_andStillDoesNotRaise(caplog):
    """A purge failure is non-fatal, but it must never be silent either."""
    sub = _Sub(RuntimeError("database is locked"))
    with caplog.at_level(logging.INFO):
        assert sub.maybePurge() is True
    joined = " ".join(_purgeLines(caplog)).lower()
    assert "fail" in joined
    assert "database is locked" in joined


@pytest.mark.parametrize("deletions", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
def test_everyDueRunProducesExactlyOneLine(deletions, caplog):
    """One run, one line -- so counting lines counts runs.

    🔴 THIS IS THE PROPERTY THAT MAKES THE JOURNAL COUNTABLE. F-114's exclusion
    worked by counting purge lines across a 229 MB journal and finding ZERO. That
    only means "it never ran" if a run always produces exactly one line.
    """
    sub = _Sub(deletions)
    with caplog.at_level(logging.INFO):
        sub.maybePurge()
    assert len(_purgeLines(caplog)) == 1
    assert "ran" in _purgeLines(caplog)[0].lower()
