################################################################################
# File Name: test_boot_reason_v0276_graceful.py
# Purpose/Description: Regression suite for I-030 / US-330 -- the V0.27.6
#                      post-Drain-17 boot wrote a ``startup_log`` row with an
#                      EMPTY ``prior_boot_clean`` field (and empty
#                      ``prior_last_entry_ts``), a regression from the
#                      ``prior_boot_clean=1`` rows V0.27.4/.5 boots produced.
#                      Pre-flight (code archaeology -- live ``journalctl`` on
#                      chi-eclipse-01 is a CIO follow-up, same pattern as
#                      US-326/US-327/US-328 this sprint): the only way the
#                      writer emits NULL for BOTH ``prior_boot_clean`` and
#                      ``prior_last_entry_ts`` is ``detectBootReason``'s
#                      ``priorEntry is None`` branch, which is reached when
#                      ``journalctl --list-boots`` returns ``None`` (the
#                      ``runJournalctl`` failure sentinel -- e.g. the
#                      subprocess times out under boot-time I/O contention from
#                      the V0.27.6 US-322 ``orphan-cleanup.timer`` catch-up
#                      DELETE that now fires at boot) -- with no retry, that
#                      transient failure permanently loses the prior-boot
#                      classification.  Fix (US-330, "race-guard" path per the
#                      story scope): ``detectBootReason`` retries
#                      ``journalctl --list-boots`` with a short backoff so a
#                      transient storm does not strand the row at NULL, and
#                      logs loudly if every attempt fails.  These tests feed a
#                      V0.27.6-flavour journalctl sequence (``--list-boots``
#                      None on the first call, then the real listing) and
#                      assert the writer recovers ``prior_boot_clean=1`` --
#                      they FAIL pre-fix (one ``--list-boots`` call, immediate
#                      give-up).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Rex (US-330) | Initial -- I-030 regression gate: transient
#                                journalctl --list-boots failure no longer
#                                strands startup_log.prior_boot_clean at NULL.
# ================================================================================
################################################################################

"""I-030 / US-330 regression gate -- transient ``journalctl --list-boots``
failure must not strand ``startup_log.prior_boot_clean`` at NULL.

The V0.27.6 ``orphan-cleanup.timer`` (US-322, ``Persistent=true``) fires
at boot and runs a DELETE against ``realtime_data``; on the Pi 5's SD
card that I/O can starve the concurrently-launching orchestrator's
``journalctl --list-boots`` subprocess past its 10 s timeout, which
``runJournalctl`` surfaces as ``None``.  Pre-fix, ``detectBootReason``
called ``--list-boots`` exactly once and -- on ``None`` -- wrote a
``startup_log`` row with ``prior_boot_clean`` / ``prior_last_entry_ts``
both NULL (the I-030 symptom).  Post-fix it retries the call (bounded:
``LIST_BOOTS_RETRY_ATTEMPTS`` attempts, ``LIST_BOOTS_RETRY_SLEEP_SECONDS``
backoff -- the happy path never retries, so there is zero added latency
when ``--list-boots`` works first try) and only after exhausting the
retries does it fall back to the NULL row, logging a WARNING.

Scope guard: the fix is a *timing* change around the ``--list-boots``
lookup only -- the US-308 graceful-detection logic (tail-marker scan +
the V0.24.1 ladder ``-g`` probe) is untouched, so a hard crash still
classifies as ``prior_boot_clean=0``.  The crash-still-crashes test
below pins that.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.pi.diagnostics.boot_reason import (  # noqa: E402  (import after path-mutate)
    LIST_BOOTS_RETRY_ATTEMPTS,
    detectBootReason,
    recordBootReason,
)

# ================================================================================
# Canned journalctl fixtures (V0.27.6-flavour)
# ================================================================================

# Real-shape ``journalctl --no-pager --list-boots`` output: the prior boot
# (-1) is the post-Drain-17 V0.24.1 ladder graceful shutdown; 0 is the
# current boot that is writing the startup_log row.
_LIST_BOOTS_OUTPUT = (
    "IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY\n"
    " -2 b1f0e8d4c5b94f8b9d3e7a2c1d4e9f8a Sun 2026-05-11 10:00:00 UTC Sun 2026-05-11 12:27:00 UTC\n"
    " -1 a2e1f9d5d6c95f9c0e4f8b3d2e5f0a9b Sun 2026-05-11 12:27:57 UTC Mon 2026-05-12 00:34:32 UTC\n"
    "  0 c3f2e8d6e7da6f0d1f5b9c4e3f6c1d0e Mon 2026-05-12 00:37:02 UTC Mon 2026-05-12 00:38:00 UTC\n"
)
_PRIOR_BOOT_ID = 'a2e1f9d5d6c95f9c0e4f8b3d2e5f0a9b'
_CURRENT_BOOT_ID = 'c3f2e8d6e7da6f0d1f5b9c4e3f6c1d0e'
_PRIOR_LAST_ENTRY = "Mon 2026-05-12 00:34:32 UTC"

# Prior-boot tail of the V0.24.1 ladder poweroff -- as captured on
# chi-eclipse-01 these last 100 lines carry ZERO systemd shutdown markers
# (rate-limited / lost to the abrupt journald halt under the orchestrator +
# drain_forensics + obd.obd log storm).  The graceful signal is the
# application-emitted ``_enterTrigger`` line, reachable only via ``-g``.
_LADDER_TAIL_NO_SYSTEMD_MARKERS = (
    "May 12 00:34:31 chi-eclipse-01 python[2317]: PowerDownOrchestrator.tick: vcell=3.294 stage=trigger\n"
    "May 12 00:34:30 chi-eclipse-01 python[2317]: obd.obd: '0142' is not supported\n"
    "May 12 00:34:28 chi-eclipse-01 python[2403]: drain_forensics: wrote_row csv=drain-forensics-...csv\n"
    "May 12 00:34:25 chi-eclipse-01 python[2317]: PowerDownOrchestrator.tick: vcell=3.301 stage=trigger\n"
)
_LADDER_GREP_HIT = (
    "May 12 00:31:09 chi-eclipse-01 python[2317]: WARNING src.pi.power.orchestrator "
    "_enterTrigger | PowerDownOrchestrator: TRIGGER at 3.445V -- initiating poweroff\n"
)

# Tail of a genuine hard crash -- drive telemetry, no shutdown marker
# anywhere, and no ladder marker either.
_CRASH_TAIL = (
    "May 12 00:34:31 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.45V SOC=72%\n"
    "May 12 00:34:30 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.41V SOC=68%\n"
    "May 12 00:34:29 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.39V SOC=65%\n"
)

# Tail of a low-volume graceful shutdown where the systemd markers DID
# survive (defence-in-depth: the retry path must not disturb this).
_CLEAN_SYSTEMD_TAIL = (
    "May 12 00:34:30 chi-eclipse-01 systemd[1]: Stopped target Multi-User System.\n"
    "May 12 00:34:31 chi-eclipse-01 systemd[1]: Reached target Shutdown.\n"
    "May 12 00:34:32 chi-eclipse-01 systemd-shutdown[1]: Powering off.\n"
)

_NOSLEEP = lambda _seconds: None  # noqa: E731 -- inject a no-op so the suite never actually sleeps


class _SequencedJournalctl:
    """Canned ``runJournalctl`` stand-in with per-call ``--list-boots`` answers.

    ``listBootsResponses`` is consumed one entry per ``['--list-boots']``
    call; once exhausted, the last entry is reused (so e.g.
    ``[None, _LIST_BOOTS_OUTPUT]`` means "fail the first attempt, succeed
    every attempt after").  ``-b <id> -n N --reverse`` returns
    ``priorBootTail``; ``-b <id> -g PATTERN -n N`` returns ``ladderGrep``.
    ``listBootsCalls`` counts the ``--list-boots`` invocations so tests
    can assert the happy path makes exactly one.
    """

    def __init__(
        self,
        listBootsResponses: list[str | None],
        priorBootTail: str | None,
        ladderGrep: str | None,
    ) -> None:
        self._listBootsResponses = list(listBootsResponses)
        self._priorBootTail = priorBootTail
        self._ladderGrep = ladderGrep
        self.listBootsCalls = 0

    def __call__(self, args: list[str]) -> str | None:
        if args == ['--list-boots']:
            self.listBootsCalls += 1
            idx = min(self.listBootsCalls - 1, len(self._listBootsResponses) - 1)
            return self._listBootsResponses[idx]
        if args and args[0] == '-b' and '-g' in args:
            return self._ladderGrep
        if args and args[0] == '-b':
            return self._priorBootTail
        raise AssertionError(f"unexpected journalctl args in test: {args!r}")


class _InMemoryStartupLogDb:
    """Minimal ObdDatabase shape: one ``startup_log`` table, sticky connection."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(':memory:')
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE startup_log (
                boot_id TEXT PRIMARY KEY,
                prior_boot_clean INTEGER,
                prior_last_entry_ts TEXT,
                current_boot_first_entry_ts TEXT,
                recorded_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    @contextmanager
    def connect(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def rows(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM startup_log").fetchall())


@pytest.fixture
def db() -> _InMemoryStartupLogDb:
    return _InMemoryStartupLogDb()


def _bootIdReader(value: str | None = _CURRENT_BOOT_ID):
    def _reader() -> str | None:
        return value
    return _reader


# ================================================================================
# I-030 regression -- transient --list-boots failure is recovered
# ================================================================================

class TestTransientListBootsFailureRecovered:
    """The I-030 cliff: ``--list-boots`` ``None`` on attempt 1, fine after.

    Pre-fix ``detectBootReason`` calls ``--list-boots`` once and, on
    ``None``, returns ``priorBootClean=None`` / ``priorLastEntryTs=None``
    -- the row the PM observed on the V0.27.6 post-Drain-17 boot.
    Post-fix it retries and recovers the V0.24.1 ladder graceful
    classification (``prior_boot_clean=1``).
    """

    def test_v0276FlavourSlice_writerRecoversPriorBootCleanOne(
        self, db: _InMemoryStartupLogDb,
    ) -> None:
        runner = _SequencedJournalctl(
            listBootsResponses=[None, _LIST_BOOTS_OUTPUT],
            priorBootTail=_LADDER_TAIL_NO_SYSTEMD_MARKERS,
            ladderGrep=_LADDER_GREP_HIT,
        )
        inserted = recordBootReason(
            db,
            bootIdReader=_bootIdReader(),
            journalctlRunner=runner,
            sleeper=_NOSLEEP,
        )
        assert inserted is True
        row = db.rows()[0]
        assert row['boot_id'] == _CURRENT_BOOT_ID
        assert row['prior_boot_clean'] == 1, (
            "I-030 regression: a transient journalctl --list-boots failure on "
            "the first attempt must be retried, not left to strand the row at "
            "NULL prior_boot_clean (pre-fix: one --list-boots call, immediate "
            "give-up)."
        )
        assert row['prior_last_entry_ts'] == _PRIOR_LAST_ENTRY

    def test_detectBootReason_retryThenSuccess_returnsPopulatedReport(self) -> None:
        runner = _SequencedJournalctl(
            listBootsResponses=[None, None, _LIST_BOOTS_OUTPUT],
            priorBootTail=_CLEAN_SYSTEMD_TAIL,
            ladderGrep='',
        )
        report = detectBootReason(
            bootIdReader=_bootIdReader(),
            journalctlRunner=runner,
            sleeper=_NOSLEEP,
        )
        assert report is not None
        assert report.priorBootId == _PRIOR_BOOT_ID
        assert report.priorBootClean is True
        assert report.priorLastEntryTs == _PRIOR_LAST_ENTRY
        assert report.currentBootFirstEntryTs == "Mon 2026-05-12 00:37:02 UTC"
        # Two failed attempts + one success.
        assert runner.listBootsCalls == 3

    def test_happyPath_listBootsCalledExactlyOnce_noWastedRetries(self) -> None:
        runner = _SequencedJournalctl(
            listBootsResponses=[_LIST_BOOTS_OUTPUT],
            priorBootTail=_CLEAN_SYSTEMD_TAIL,
            ladderGrep='',
        )
        report = detectBootReason(
            bootIdReader=_bootIdReader(),
            journalctlRunner=runner,
            sleeper=_NOSLEEP,
        )
        assert report is not None
        assert report.priorBootClean is True
        assert runner.listBootsCalls == 1, (
            "the retry must be paid only on the anomalous path -- a "
            "--list-boots that works first try costs exactly one call and "
            "zero backoff sleep"
        )


# ================================================================================
# Graceful degradation when every attempt fails
# ================================================================================

class TestRetryExhausted:
    """All ``--list-boots`` attempts fail -> NULL row still written + loud log."""

    def test_allAttemptsFail_writesNullRowNotCrash(
        self, db: _InMemoryStartupLogDb,
    ) -> None:
        runner = _SequencedJournalctl(
            listBootsResponses=[None],  # reused for every attempt
            priorBootTail=_LADDER_TAIL_NO_SYSTEMD_MARKERS,
            ladderGrep=_LADDER_GREP_HIT,
        )
        inserted = recordBootReason(
            db,
            bootIdReader=_bootIdReader(),
            journalctlRunner=runner,
            sleeper=_NOSLEEP,
        )
        assert inserted is True
        row = db.rows()[0]
        assert row['boot_id'] == _CURRENT_BOOT_ID
        # Disposition genuinely unknown -- the row is still written so the
        # boot_id appears for forward cross-reference (the NULL is itself
        # diagnostic), exactly as the original best-effort contract.
        assert row['prior_boot_clean'] is None
        assert row['prior_last_entry_ts'] is None
        assert runner.listBootsCalls == LIST_BOOTS_RETRY_ATTEMPTS

    def test_allAttemptsFail_emitsWarning(self, caplog: pytest.LogCaptureFixture) -> None:
        runner = _SequencedJournalctl(
            listBootsResponses=[None],
            priorBootTail=None,
            ladderGrep=None,
        )
        with caplog.at_level(logging.WARNING, logger='src.pi.diagnostics.boot_reason'):
            detectBootReason(
                bootIdReader=_bootIdReader(),
                journalctlRunner=runner,
                sleeper=_NOSLEEP,
            )
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "exhausting the --list-boots retries must log loudly, not fail silently"
        assert any('list-boots' in r.getMessage() for r in warnings)


# ================================================================================
# Scope guard -- the retry must not disturb US-308 graceful detection
# ================================================================================

class TestRetryDoesNotChangeClassification:
    """A retry recovers the *listing*; it must not recolour the verdict."""

    def test_crashBoot_afterListBootsRetry_stillClassifiesAsCrash(
        self, db: _InMemoryStartupLogDb,
    ) -> None:
        runner = _SequencedJournalctl(
            listBootsResponses=[None, _LIST_BOOTS_OUTPUT],
            priorBootTail=_CRASH_TAIL,
            ladderGrep='',  # probe ran, no ladder evidence
        )
        recordBootReason(
            db,
            bootIdReader=_bootIdReader(),
            journalctlRunner=runner,
            sleeper=_NOSLEEP,
        )
        row = db.rows()[0]
        assert row['prior_boot_clean'] == 0, (
            "stop-condition guard: a transient --list-boots retry must not "
            "turn a hard crash into a graceful classification"
        )

    def test_recordBootReason_retryThenSuccess_isIdempotent(
        self, db: _InMemoryStartupLogDb,
    ) -> None:
        def _freshRunner() -> _SequencedJournalctl:
            return _SequencedJournalctl(
                listBootsResponses=[None, _LIST_BOOTS_OUTPUT],
                priorBootTail=_LADDER_TAIL_NO_SYSTEMD_MARKERS,
                ladderGrep=_LADDER_GREP_HIT,
            )

        first = recordBootReason(
            db, bootIdReader=_bootIdReader(), journalctlRunner=_freshRunner(), sleeper=_NOSLEEP,
        )
        second = recordBootReason(
            db, bootIdReader=_bootIdReader(), journalctlRunner=_freshRunner(), sleeper=_NOSLEEP,
        )
        assert first is True
        assert second is False
        assert len(db.rows()) == 1
        assert db.rows()[0]['prior_boot_clean'] == 1
