################################################################################
# File Name: test_boot_reason.py
# Purpose/Description: Unit tests for src/pi/diagnostics/boot_reason.py
#                      (US-263).  Mocks the boot-id reader + journalctl runner
#                      via constructor-style dependency injection so the suite
#                      runs cross-platform (no /proc/sys/kernel/random/boot_id
#                      on Windows, no journalctl binary either).  Covers: prior
#                      boot detected as cleanly shut down (shutdown marker
#                      present in tail journal), prior boot detected as hard
#                      crash (no shutdown marker), no prior boot visible
#                      (fresh Pi or pruned journal), boot-id read failure,
#                      journalctl unavailable, idempotency of the SQL writer,
#                      and end-to-end recordBootReason wiring.  Also pins
#                      pure-helper invariants: --list-boots line parser,
#                      shutdown-marker substring matcher, boot_id normalizer.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-263) | Initial -- boot-reason detector + startup_log
#                                writer test suite.
# 2026-05-03    | Rex (US-283) | Added TestStartupLogSchema -- pins canonical
#                                column set from production SCHEMA_STARTUP_LOG
#                                so future drift (e.g. accidental `id` column,
#                                renamed column, type change, compound PK)
#                                surfaces as an isolated test failure.  Sprint
#                                24 audit (Spool flag) confirmed deployed
#                                schema matches US-263 spec; this guard locks
#                                that in.
# 2026-05-12    | Rex (US-330) | Inject a no-op ``sleeper`` into
#                                test_detectBootReason_journalctlUnavailable_*
#                                so the new US-330 / I-030 ``--list-boots``
#                                retry backoff doesn't make the test block on
#                                real ``time.sleep``.  No behaviour assertion
#                                change -- the post-retry result is identical
#                                to the pre-retry one (all-``None`` fields).
#                                The dedicated I-030 regression gate lives in
#                                tests/pi/diagnostics/test_boot_reason_v0276_graceful.py.
# 2026-05-09    | Rex (US-308) | Added TestProbeLadderGraceful + extended
#                                detectBootReason test classes for the
#                                V0.24.1 ladder graceful-shutdown signal.
#                                Empirical chi-eclipse-01 capture (boot -2
#                                e6ebde20...) showed the 100-line tail
#                                contains zero systemd shutdown markers --
#                                they get rate-limited / lost to abrupt
#                                journald halt under orchestrator + drain
#                                + obd log storm.  The application-emitted
#                                ``PowerDownOrchestrator: TRIGGER at ...``
#                                line IS persisted reliably (~3 min before
#                                journal cut) and is reachable via
#                                ``journalctl -b <id> -g <pattern>``.  Pre-
#                                fix: no journalctl --grep probe; the
#                                ladder shutdown looks identical to a hard
#                                crash.  Post-fix: a second narrow probe
#                                catches the ladder marker; prior_boot_clean
#                                = 1 on V0.24.1 graceful boots.
# 2026-05-15 honest-instrument: startup_log 5->7 col guard updated
#                                (TestStartupLogSchema EXPECTED_COLUMNS +
#                                count test) for prior_boot_last_stage +
#                                prior_boot_reason per design spec
#                                2026-05-15-honest-boot-progress-instrument-design.md.
# ================================================================================
################################################################################

"""Unit tests for boot-reason detector + startup_log writer (US-263).

The acceptance criteria call out two canonical paths: clean-shutdown
journalctl output -> ``prior_boot_clean=True``, and crash-shutdown
journalctl output -> ``prior_boot_clean=False``.  Beyond those two
load-bearing cases the suite also pins:

* idempotency of the writer (re-running on the same boot_id does not
  duplicate the row -- the story-level invariant);
* graceful degradation when journalctl is missing or the boot-id
  surface fails (the row is still written with ``priorBootClean=None``
  rather than crashing startup);
* the pure helpers (parser, marker matcher, normalizer) so
  format-drift in journalctl output surfaces as an isolated test
  failure rather than a head-scratching integration breakage.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path -- tests are invoked from various
# CWDs via the makefile + IDE runners; the conftest.py up the tree
# already does this for most files but importing src.pi.diagnostics.*
# from a brand-new package needs the safety net.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.pi.diagnostics import boot_reason
from src.pi.diagnostics.boot_reason import (  # noqa: E402  (import after path-mutate)
    LADDER_GRACEFUL_GREP_PATTERN,
    SHUTDOWN_MARKERS,
    BootReasonReport,
    _hasShutdownMarker,
    _normalizeBootId,
    _probeLadderGraceful,
    detectBootReason,
    parseListBoots,
    readCurrentBootId,
    recordBootReason,
    runJournalctl,
    writeStartupLog,
)
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG  # noqa: E402

# ================================================================================
# Canned journalctl Output Fixtures
# ================================================================================

# Real-shape ``journalctl --list-boots --no-pager`` output (3 boots).
# Idx 0 is the current boot; -1 is the prior boot the detector classifies.
_LIST_BOOTS_OUTPUT = (
    "IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY\n"
    " -2 b1f0e8d4c5b94f8b9d3e7a2c1d4e9f8a Sat 2026-04-30 10:00:00 UTC Sat 2026-04-30 12:00:00 UTC\n"
    " -1 a2e1f9d5d6c95f9c0e4f8b3d2e5f0a9b Fri 2026-05-01 14:00:00 UTC Fri 2026-05-01 22:19:00 UTC\n"
    "  0 c3f2e8d6e7da6f0d1f5b9c4e3f6c1d0e Sat 2026-05-02 09:00:00 UTC Sat 2026-05-02 09:30:00 UTC\n"
)

_PRIOR_BOOT_ID = 'a2e1f9d5d6c95f9c0e4f8b3d2e5f0a9b'
_CURRENT_BOOT_ID = 'c3f2e8d6e7da6f0d1f5b9c4e3f6c1d0e'

# Tail journal of a graceful poweroff.  Carries the canonical systemd
# ``Reached target Shutdown`` marker plus a few surrounding lines so
# the matcher proves substring-not-line semantics.
_CLEAN_SHUTDOWN_JOURNAL = (
    "May 01 22:18:55 chi-eclipse-01 systemd[1]: Stopping User Manager for UID 1000...\n"
    "May 01 22:18:56 chi-eclipse-01 systemd[1]: Stopped target Multi-User System.\n"
    "May 01 22:18:57 chi-eclipse-01 systemd[1]: Reached target Shutdown.\n"
    "May 01 22:18:58 chi-eclipse-01 systemd[1]: Reached target Final Step.\n"
    "May 01 22:18:59 chi-eclipse-01 systemd-shutdown[1]: Sending SIGTERM to remaining processes...\n"
    "May 01 22:19:00 chi-eclipse-01 systemd-shutdown[1]: Powering off.\n"
)

# Tail journal of a hard crash.  Last entries are drive-time telemetry,
# no shutdown marker present anywhere.
_CRASH_JOURNAL = (
    "May 01 22:18:55 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.45V SOC=72%\n"
    "May 01 22:19:00 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.41V SOC=68%\n"
    "May 01 22:19:01 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.39V SOC=65%\n"
    "May 01 22:19:02 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.37V SOC=62%\n"
    "May 01 22:19:03 chi-eclipse-01 eclipse-obd[2317]: VCELL=3.36V SOC=58%\n"
)

# US-308 fixture -- 100-line tail of a V0.24.1 ladder graceful shutdown as
# captured from chi-eclipse-01 boot -2 (e6ebde20ac424acd96c2ed457e91f8d6,
# 2026-05-09T01:40:06Z journal cut after Drain Test 8 graceful poweroff).
# The actual production journal had ZERO systemd shutdown markers in the
# last 100 entries -- they were rate-limited / dropped under the
# orchestrator + drain_forensics + obd.obd log storm.  This fixture
# mirrors that exact pattern: orchestrator ticks at stage=trigger,
# obd.obd PID-not-supported warnings, drain_forensics row writes, and
# ZERO systemd 'Reached target Shutdown' / 'systemd-shutdown' lines.
_LADDER_GRACEFUL_TAIL_NO_SYSTEMD_MARKERS = (
    "May 08 20:40:06 Chi-Eclips-Tuner python[233537]: 2026-05-08 20:40:06 | WARNING  | obd.obd | test_cmd | 'b'0142': Control module voltage' is not supported\n"
    "May 08 20:40:05 Chi-Eclips-Tuner python[233537]: 2026-05-08 20:40:05 | INFO     | src.pi.power.orchestrator | _logTickDecision | PowerDownOrchestrator.tick: vcell=3.294 currentStage=trigger thresholds={WARNING:3.70, IMMINENT:3.55, TRIGGER:3.45} willTransition=False reason=already_at_stage\n"
    "May 08 20:40:03 Chi-Eclips-Tuner python[238834]: 2026-05-08 20:40:03,257 INFO __main__: drain_forensics: wrote_row path=/var/log/eclipse-obd/drain-forensics-20260509T011904Z.csv\n"
    "May 08 20:40:00 Chi-Eclips-Tuner python[233537]: 2026-05-08 20:40:00 | INFO     | src.pi.power.orchestrator | _logTickDecision | PowerDownOrchestrator.tick: vcell=3.301 currentStage=trigger thresholds={WARNING:3.70, IMMINENT:3.55, TRIGGER:3.45} willTransition=False reason=already_at_stage\n"
    "May 08 20:39:55 Chi-Eclips-Tuner python[233537]: 2026-05-08 20:39:55 | INFO     | src.pi.power.orchestrator | _logTickDecision | PowerDownOrchestrator.tick: vcell=3.311 currentStage=trigger thresholds={WARNING:3.70, IMMINENT:3.55, TRIGGER:3.45} willTransition=False reason=already_at_stage\n"
    "May 08 20:39:50 Chi-Eclips-Tuner python[233537]: 2026-05-08 20:39:50 | INFO     | src.pi.power.orchestrator | _logTickDecision | PowerDownOrchestrator.tick: vcell=3.309 currentStage=trigger thresholds={WARNING:3.70, IMMINENT:3.55, TRIGGER:3.45} willTransition=False reason=already_at_stage\n"
    "May 08 20:39:45 Chi-Eclips-Tuner systemd[1]: Finished drain-forensics.service - Eclipse OBD-II drain forensics logger (US-262).\n"
    "May 08 20:39:45 Chi-Eclips-Tuner systemd[1]: drain-forensics.service: Deactivated successfully.\n"
)

# What ``journalctl -b <id> -g 'PowerDownOrchestrator: TRIGGER at' -n 5``
# returns when the V0.24.1 ladder fired during the prior boot.  Captured
# from chi-eclipse-01 boot -2 (real production, 2026-05-09).
_LADDER_GREP_OUTPUT = (
    "May 08 20:36:45 Chi-Eclips-Tuner python[233537]: 2026-05-08 20:36:45 | WARNING  | src.pi.power.orchestrator | _enterTrigger | PowerDownOrchestrator: TRIGGER at 3.424V -- initiating poweroff\n"
)


def _makeJournalctlRunner(
    listBootsOutput: str | None = _LIST_BOOTS_OUTPUT,
    priorBootJournal: str | None = _CLEAN_SHUTDOWN_JOURNAL,
    ladderGrepOutput: str | None = '',
):
    """Return a callable that mimics :func:`runJournalctl` from canned output.

    Inspects the args list to dispatch:
      * ``['--list-boots']``                   -> ``listBootsOutput``
      * ``['-b', <id>, '-n', N, '--reverse']`` -> ``priorBootJournal``
        (the existing tail-window scan)
      * ``['-b', <id>, '-g', PATTERN, '-n', N]`` -> ``ladderGrepOutput``
        (US-308: V0.24.1 ladder application-marker probe)

    Passing ``None`` for any output simulates subprocess failure for that
    surface.  Default ``ladderGrepOutput=''`` means "probe ran, found
    nothing" -- the safe default for legacy test cases that pre-date
    US-308; it keeps existing crash tests classifying as crash without
    any test-rewrite churn.
    """
    def _runner(args: list[str]) -> str | None:
        if args == ['--list-boots']:
            return listBootsOutput
        if args and args[0] == '-b' and '-g' in args:
            return ladderGrepOutput
        if args and args[0] == '-b':
            return priorBootJournal
        raise AssertionError(f"Unexpected journalctl args in test: {args!r}")
    return _runner


def _makeBootIdReader(value: str | None = _CURRENT_BOOT_ID):
    """Return a callable that mimics :func:`readCurrentBootId`."""
    def _reader() -> str | None:
        return value
    return _reader


# ================================================================================
# In-Memory ObdDatabase Stand-In
# ================================================================================

class _InMemoryDatabase:
    """Minimal ObdDatabase shape sufficient for writeStartupLog tests.

    Keeps the SAME sqlite3 connection across ``connect()`` calls so the
    in-memory database survives -- a real ObdDatabase would open a new
    connection each time but persistence is guaranteed by the file
    backing.  Tests assert on the row contents post-write so the model
    just needs commit/rollback to behave correctly.
    """

    def __init__(self) -> None:
        self._conn = sqlite3.connect(':memory:')
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE startup_log (
                boot_id TEXT PRIMARY KEY,
                prior_boot_clean INTEGER,
                prior_last_entry_ts TEXT,
                current_boot_first_entry_ts TEXT,
                recorded_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    @contextmanager
    def connect(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def fetchAll(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM startup_log").fetchall())


@pytest.fixture
def database():
    """Fresh in-memory startup_log database per test."""
    return _InMemoryDatabase()


# ================================================================================
# Pure Helper Tests
# ================================================================================

class TestNormalizeBootId:
    """:func:`_normalizeBootId` lowercases + strips whitespace + strips dashes."""

    @pytest.mark.parametrize("raw,expected", [
        ("abcd1234-abcd-1234-abcd-1234abcd1234\n", "abcd1234abcd1234abcd1234abcd1234"),
        ("A1B2C3D4E5F67890\n", "a1b2c3d4e5f67890"),
        ("  abc-def-123  ", "abcdef123"),
        ("", ""),
    ])
    def test_normalizeBootId_handlesShapes(self, raw: str, expected: str) -> None:
        assert _normalizeBootId(raw) == expected


class TestParseListBoots:
    """:func:`parseListBoots` extracts (idx, bootId, firstEntry, lastEntry)."""

    def test_parseListBoots_threeBoots_returnsThreeEntries(self) -> None:
        entries = parseListBoots(_LIST_BOOTS_OUTPUT)
        assert len(entries) == 3
        assert [e.idx for e in entries] == [-2, -1, 0]
        assert entries[1].bootId == _PRIOR_BOOT_ID
        assert entries[2].bootId == _CURRENT_BOOT_ID

    def test_parseListBoots_capturesTimestampStrings(self) -> None:
        entries = parseListBoots(_LIST_BOOTS_OUTPUT)
        priorEntry = entries[1]
        assert priorEntry.firstEntry == "Fri 2026-05-01 14:00:00 UTC"
        assert priorEntry.lastEntry == "Fri 2026-05-01 22:19:00 UTC"

    def test_parseListBoots_skipsHeaderAndBlankLines(self) -> None:
        entries = parseListBoots(_LIST_BOOTS_OUTPUT)
        # Header line "IDX BOOT ID..." must NOT yield an entry.
        assert all(isinstance(e.idx, int) for e in entries)

    def test_parseListBoots_emptyInput_returnsEmptyList(self) -> None:
        assert parseListBoots("") == []

    def test_parseListBoots_malformedLine_skips(self) -> None:
        garbage = "not-a-boot-line\nthis is also garbage\n"
        assert parseListBoots(garbage) == []

    def test_parseListBoots_dashedUuidFormat_normalizesToDashless(self) -> None:
        # systemd 250+ may emit dashed UUIDs in --list-boots output.
        dashedOutput = (
            "IDX BOOT ID                              FIRST ENTRY                 LAST ENTRY\n"
            " -1 a2e1f9d5-d6c9-5f9c-0e4f-8b3d2e5f0a9b Fri 2026-05-01 14:00:00 UTC Fri 2026-05-01 22:19:00 UTC\n"
            "  0 c3f2e8d6-e7da-6f0d-1f5b-9c4e3f6c1d0e Sat 2026-05-02 09:00:00 UTC Sat 2026-05-02 09:30:00 UTC\n"
        )
        entries = parseListBoots(dashedOutput)
        assert len(entries) == 2
        # Dashes stripped, lowercased.
        assert entries[0].bootId == 'a2e1f9d5d6c95f9c0e4f8b3d2e5f0a9b'
        assert entries[1].bootId == 'c3f2e8d6e7da6f0d1f5b9c4e3f6c1d0e'


class TestHasShutdownMarker:
    """:func:`_hasShutdownMarker` is case-insensitive substring match."""

    @pytest.mark.parametrize("marker", SHUTDOWN_MARKERS)
    def test_hasShutdownMarker_eachCanonicalMarkerMatches(self, marker: str) -> None:
        text = f"some preamble line\n... {marker.upper()} ...\nepilogue\n"
        assert _hasShutdownMarker(text) is True

    def test_hasShutdownMarker_cleanShutdownJournal_matches(self) -> None:
        assert _hasShutdownMarker(_CLEAN_SHUTDOWN_JOURNAL) is True

    def test_hasShutdownMarker_crashJournal_doesNotMatch(self) -> None:
        assert _hasShutdownMarker(_CRASH_JOURNAL) is False

    def test_hasShutdownMarker_emptyText_doesNotMatch(self) -> None:
        assert _hasShutdownMarker("") is False

    def test_hasShutdownMarker_v024LadderTailNoMarkers_doesNotMatch(self) -> None:
        # US-308: the production V0.24.1 ladder tail has zero systemd
        # markers (rate-limited under log storm + lost to abrupt halt).
        # The tail-only matcher MUST NOT spuriously match it -- we want
        # the new ladder probe to be the source of truth for this case.
        assert _hasShutdownMarker(_LADDER_GRACEFUL_TAIL_NO_SYSTEMD_MARKERS) is False


# ================================================================================
# US-308 -- V0.24.1 Ladder Graceful-Shutdown Probe
# ================================================================================

class TestProbeLadderGraceful:
    """:func:`_probeLadderGraceful` checks the prior boot for the ladder marker.

    The narrow ``journalctl -b <id> -g <pattern>`` probe lets us catch a
    graceful V0.24.1 ladder shutdown even when the prior boot's tail
    journal contains no systemd shutdown markers (the empirical case
    captured from chi-eclipse-01 boot -2 / Drain Test 8 / 2026-05-09).
    """

    def test_probeLadderGraceful_grepHit_returnsTrue(self) -> None:
        runner = _makeJournalctlRunner(ladderGrepOutput=_LADDER_GREP_OUTPUT)
        assert _probeLadderGraceful(runner, 'someBootId') is True

    def test_probeLadderGraceful_grepMiss_returnsFalse(self) -> None:
        # Probe ran successfully, found no match -- legitimate "no
        # ladder fired" answer.  Should NOT be conflated with probe
        # failure (which is None).
        runner = _makeJournalctlRunner(ladderGrepOutput='')
        assert _probeLadderGraceful(runner, 'someBootId') is False

    def test_probeLadderGraceful_runnerReturnsNone_returnsNone(self) -> None:
        # journalctl unavailable / --grep not supported / subprocess
        # failure -- classification is UNKNOWN, not a confident "no".
        runner = _makeJournalctlRunner(ladderGrepOutput=None)
        assert _probeLadderGraceful(runner, 'someBootId') is None

    def test_probeLadderGraceful_passesGrepArgs(self) -> None:
        # Pin the subprocess invocation shape so a future refactor
        # can't silently drop ``-g`` or ``-b``.
        seen: list[list[str]] = []

        def _spy(args: list[str]) -> str | None:
            seen.append(args)
            return _LADDER_GREP_OUTPUT

        _probeLadderGraceful(_spy, 'BOOT_ID_42')
        assert len(seen) == 1
        invocation = seen[0]
        assert '-b' in invocation
        assert 'BOOT_ID_42' in invocation
        assert '-g' in invocation
        # The grep pattern is the contract that pairs with the
        # _enterTrigger emitted line in src/pi/power/orchestrator.py.
        # Drift here = silently broken detection in production.
        assert LADDER_GRACEFUL_GREP_PATTERN in invocation

    def test_probeLadderGraceful_grepReturnsMultipleHits_stillTrue(self) -> None:
        # If the prior boot ran multiple drain tests (re-enter NORMAL
        # then re-trigger), --grep returns several lines.  Any non-
        # empty result means the ladder fired at least once.
        twoLines = _LADDER_GREP_OUTPUT + _LADDER_GREP_OUTPUT
        runner = _makeJournalctlRunner(ladderGrepOutput=twoLines)
        assert _probeLadderGraceful(runner, 'someBootId') is True


# ================================================================================
# detectBootReason -- Core Logic
# ================================================================================

class TestDetectBootReasonCleanShutdown:
    """Clean-shutdown happy path -> ``priorBootClean=True`` per acceptance."""

    def test_detectBootReason_cleanShutdown_returnsPriorBootCleanTrue(self) -> None:
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CLEAN_SHUTDOWN_JOURNAL,
            ),
        )
        assert report is not None
        assert report.currentBootId == _CURRENT_BOOT_ID
        assert report.priorBootId == _PRIOR_BOOT_ID
        assert report.priorBootClean is True
        assert report.priorLastEntryTs == "Fri 2026-05-01 22:19:00 UTC"
        assert report.currentBootFirstEntryTs == "Sat 2026-05-02 09:00:00 UTC"


class TestDetectBootReasonCrash:
    """Hard-crash path -> ``priorBootClean=False`` per acceptance."""

    def test_detectBootReason_crash_returnsPriorBootCleanFalse(self) -> None:
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CRASH_JOURNAL,
            ),
        )
        assert report is not None
        assert report.priorBootClean is False
        assert report.priorBootId == _PRIOR_BOOT_ID
        # Even on crash we still capture the prior boot's last-entry
        # timestamp so the row tells the operator WHEN the crash happened.
        assert report.priorLastEntryTs == "Fri 2026-05-01 22:19:00 UTC"


class TestDetectBootReasonDegradation:
    """Detection failures degrade gracefully per the story invariants."""

    def test_detectBootReason_bootIdMissing_returnsNone(self) -> None:
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(value=None),
            journalctlRunner=_makeJournalctlRunner(),
        )
        assert report is None

    def test_detectBootReason_journalctlUnavailable_returnsReportWithNoneFields(self) -> None:
        # ``sleeper`` is a no-op here so the US-330 / I-030 --list-boots
        # retry (which now wraps this "journalctl unavailable" path)
        # doesn't make the test block on real time.sleep backoff.
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(listBootsOutput=None),
            sleeper=lambda _seconds: None,
        )
        assert report is not None
        assert report.currentBootId == _CURRENT_BOOT_ID
        assert report.priorBootId is None
        assert report.priorBootClean is None
        assert report.priorLastEntryTs is None
        assert report.currentBootFirstEntryTs is None

    def test_detectBootReason_priorJournalUnavailable_classifiesAsUnknown(self) -> None:
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(priorBootJournal=None),
        )
        assert report is not None
        # We DID find a prior boot in --list-boots, but the tail probe
        # failed -- classification is UNKNOWN, not crash.
        assert report.priorBootId == _PRIOR_BOOT_ID
        assert report.priorBootClean is None

    def test_detectBootReason_noPriorBootInList_classifiesAsUnknown(self) -> None:
        # Only the current boot is visible (fresh Pi or journal pruned).
        firstBootOnly = (
            "IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY\n"
            "  0 c3f2e8d6e7da6f0d1f5b9c4e3f6c1d0e Sat 2026-05-02 09:00:00 UTC Sat 2026-05-02 09:30:00 UTC\n"
        )
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(listBootsOutput=firstBootOnly),
        )
        assert report is not None
        assert report.priorBootId is None
        assert report.priorBootClean is None
        # Current-boot first-entry still populated -- diagnostic for the
        # fresh-Pi case.
        assert report.currentBootFirstEntryTs == "Sat 2026-05-02 09:00:00 UTC"


class TestDetectBootReasonV024LadderGraceful:
    """US-308 -- V0.24.1 ladder graceful shutdown classification.

    Empirical pre-flight audit (chi-eclipse-01 / 2026-05-09):
    after Drain Test 8's clean ladder shutdown, the prior boot's tail
    journal contained ZERO systemd shutdown markers (rate-limited under
    the orchestrator + drain_forensics + obd.obd log storm + lost to
    abrupt journald halt).  The application-emitted ``_enterTrigger``
    line WAS persisted ~3 min before the journal cut, but is buried
    >700 lines back -- well outside the 100-line tail window.

    Pre-US-308: the heuristic only inspected the 100-line tail; the
    V0.24.1 ladder shutdown was indistinguishable from a hard crash.
    Post-US-308: a second narrow ``journalctl -g`` probe catches the
    application marker; ``prior_boot_clean=1`` on V0.24.1 boots.
    """

    def test_detectBootReason_v024Ladder_noSystemdMarkersInTail_returnsCleanTrue(
        self,
    ) -> None:
        # The empirical production case.  The 100-line tail has only
        # orchestrator ticks + obd warnings + drain_forensics writes;
        # zero systemd shutdown markers.  Pre-fix this returns
        # priorBootClean=False.  Post-fix the ladder grep probe
        # catches the marker and overrides to True.
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_LADDER_GRACEFUL_TAIL_NO_SYSTEMD_MARKERS,
                ladderGrepOutput=_LADDER_GREP_OUTPUT,
            ),
        )
        assert report is not None
        assert report.priorBootClean is True, (
            "V0.24.1 ladder graceful shutdown detected via the application "
            "marker probe (pre-fix: tail-only heuristic returns False because "
            "systemd markers are absent under log-storm rate-limiting; this "
            "test pins the post-fix behavior)."
        )

    def test_detectBootReason_v024Ladder_withSystemdMarkers_returnsCleanTrue(
        self,
    ) -> None:
        # Defense in depth: when BOTH paths see graceful evidence
        # (e.g. low-volume shutdown where systemd markers DID survive),
        # we still classify as clean.  The ladder probe and the tail
        # probe are independent; both-positive is the safest case.
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CLEAN_SHUTDOWN_JOURNAL,
                ladderGrepOutput=_LADDER_GREP_OUTPUT,
            ),
        )
        assert report is not None
        assert report.priorBootClean is True

    def test_detectBootReason_crashAndNoLadderMarker_remainsCleanFalse(self) -> None:
        # Regression guard for stop-condition #2 (the change MUST NOT
        # turn hard crashes into false positives).  When neither the
        # tail nor the ladder probe finds graceful evidence, the
        # classification is still ``False`` (hard crash).
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CRASH_JOURNAL,
                ladderGrepOutput='',
            ),
        )
        assert report is not None
        assert report.priorBootClean is False

    def test_detectBootReason_crashAndProbeFailed_classifiesAsCrash(self) -> None:
        # Probe FAILS (journalctl --grep raised, output=None) AND tail
        # has no systemd markers.  We have a confident "no graceful
        # signal" from the tail; the failed probe doesn't override.
        # Without this, a journalctl flake would silently flip every
        # crash boot to ``unknown`` and lose the post-mortem signal.
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CRASH_JOURNAL,
                ladderGrepOutput=None,
            ),
        )
        assert report is not None
        assert report.priorBootClean is False

    def test_detectBootReason_v024Ladder_probeFailed_falsesNotOverridden(
        self,
    ) -> None:
        # Tail has no systemd markers AND the ladder probe FAILED
        # (None).  Classification is UNKNOWN (None) -- safer than
        # falsely confident True.  This is the legitimate case where
        # journalctl --grep is unsupported on a hypothetical older
        # systemd; we don't want to assume the worst and we don't
        # want to assume the best either.
        report = detectBootReason(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_LADDER_GRACEFUL_TAIL_NO_SYSTEMD_MARKERS,
                ladderGrepOutput=None,
            ),
        )
        assert report is not None
        # tail says False (no systemd markers); ladder probe says
        # None (couldn't tell).  Final answer: False -- the tail's
        # confident "no marker" stands.  We deliberately do NOT
        # promote False -> None on probe failure because the tail's
        # evidence is independently credible.
        assert report.priorBootClean is False


# ================================================================================
# writeStartupLog -- Idempotency + Persistence
# ================================================================================

class TestWriteStartupLog:
    """Writer persists rows + uses INSERT OR IGNORE for idempotency."""

    def test_writeStartupLog_clean_writesRowAndReturnsTrue(
        self, database: _InMemoryDatabase,
    ) -> None:
        report = BootReasonReport(
            currentBootId=_CURRENT_BOOT_ID,
            priorBootId=_PRIOR_BOOT_ID,
            priorBootClean=True,
            priorLastEntryTs="Fri 2026-05-01 22:19:00 UTC",
            currentBootFirstEntryTs="Sat 2026-05-02 09:00:00 UTC",
        )
        inserted = writeStartupLog(database, report)
        assert inserted is True
        rows = database.fetchAll()
        assert len(rows) == 1
        row = rows[0]
        assert row['boot_id'] == _CURRENT_BOOT_ID
        assert row['prior_boot_clean'] == 1
        assert row['prior_last_entry_ts'] == "Fri 2026-05-01 22:19:00 UTC"
        assert row['current_boot_first_entry_ts'] == "Sat 2026-05-02 09:00:00 UTC"
        assert row['recorded_at']  # canonical ISO-8601 UTC populated

    def test_writeStartupLog_crash_persistsZero(
        self, database: _InMemoryDatabase,
    ) -> None:
        report = BootReasonReport(
            currentBootId=_CURRENT_BOOT_ID,
            priorBootId=_PRIOR_BOOT_ID,
            priorBootClean=False,
            priorLastEntryTs="Fri 2026-05-01 22:19:00 UTC",
            currentBootFirstEntryTs="Sat 2026-05-02 09:00:00 UTC",
        )
        writeStartupLog(database, report)
        row = database.fetchAll()[0]
        assert row['prior_boot_clean'] == 0

    def test_writeStartupLog_unknown_persistsNull(
        self, database: _InMemoryDatabase,
    ) -> None:
        report = BootReasonReport(
            currentBootId=_CURRENT_BOOT_ID,
            priorBootId=None,
            priorBootClean=None,
            priorLastEntryTs=None,
            currentBootFirstEntryTs=None,
        )
        writeStartupLog(database, report)
        row = database.fetchAll()[0]
        assert row['prior_boot_clean'] is None
        assert row['prior_last_entry_ts'] is None
        assert row['current_boot_first_entry_ts'] is None

    def test_writeStartupLog_secondCallSameBootId_isNoOp(
        self, database: _InMemoryDatabase,
    ) -> None:
        # Per story invariant: re-running boot_reason for the same boot_id
        # MUST NOT insert a duplicate row.
        report = BootReasonReport(
            currentBootId=_CURRENT_BOOT_ID,
            priorBootId=_PRIOR_BOOT_ID,
            priorBootClean=True,
            priorLastEntryTs="Fri 2026-05-01 22:19:00 UTC",
            currentBootFirstEntryTs="Sat 2026-05-02 09:00:00 UTC",
        )
        first = writeStartupLog(database, report)
        second = writeStartupLog(database, report)
        assert first is True
        assert second is False
        # Still exactly one row.
        assert len(database.fetchAll()) == 1

    def test_writeStartupLog_databaseNone_returnsFalse(self) -> None:
        report = BootReasonReport(
            currentBootId=_CURRENT_BOOT_ID,
            priorBootId=None,
            priorBootClean=None,
            priorLastEntryTs=None,
            currentBootFirstEntryTs=None,
        )
        assert writeStartupLog(None, report) is False


# ================================================================================
# recordBootReason -- End-to-End Wiring
# ================================================================================

class TestRecordBootReason:
    """Top-level orchestrator stitches detection + write."""

    def test_recordBootReason_cleanShutdown_writesPriorBootCleanOne(
        self, database: _InMemoryDatabase,
    ) -> None:
        result = recordBootReason(
            database,
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CLEAN_SHUTDOWN_JOURNAL,
            ),
        )
        assert result is True
        row = database.fetchAll()[0]
        assert row['prior_boot_clean'] == 1
        assert row['boot_id'] == _CURRENT_BOOT_ID

    def test_recordBootReason_crash_writesPriorBootCleanZero(
        self, database: _InMemoryDatabase,
    ) -> None:
        result = recordBootReason(
            database,
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(
                priorBootJournal=_CRASH_JOURNAL,
            ),
        )
        assert result is True
        row = database.fetchAll()[0]
        assert row['prior_boot_clean'] == 0

    def test_recordBootReason_bootIdMissing_returnsFalseWithoutWriting(
        self, database: _InMemoryDatabase,
    ) -> None:
        result = recordBootReason(
            database,
            bootIdReader=_makeBootIdReader(value=None),
            journalctlRunner=_makeJournalctlRunner(),
        )
        assert result is False
        assert database.fetchAll() == []

    def test_recordBootReason_secondInvocationSameBoot_isIdempotent(
        self, database: _InMemoryDatabase,
    ) -> None:
        kwargs = dict(
            bootIdReader=_makeBootIdReader(),
            journalctlRunner=_makeJournalctlRunner(),
        )
        first = recordBootReason(database, **kwargs)
        second = recordBootReason(database, **kwargs)
        assert first is True
        assert second is False
        assert len(database.fetchAll()) == 1


# ================================================================================
# I/O Boundary Tests (subprocess.run + boot_id surface)
# ================================================================================

class TestReadCurrentBootId:
    """Boot-id surface read + normalization."""

    def test_readCurrentBootId_validFile_returnsNormalized(self, tmp_path: Path) -> None:
        bootIdPath = tmp_path / 'boot_id'
        bootIdPath.write_text('ABCD1234-ABCD-1234-ABCD-1234ABCD1234\n')
        result = readCurrentBootId(str(bootIdPath))
        assert result == 'abcd1234abcd1234abcd1234abcd1234'

    def test_readCurrentBootId_missingFile_returnsNone(self, tmp_path: Path) -> None:
        result = readCurrentBootId(str(tmp_path / 'does_not_exist'))
        assert result is None

    def test_readCurrentBootId_emptyFile_returnsNone(self, tmp_path: Path) -> None:
        bootIdPath = tmp_path / 'boot_id'
        bootIdPath.write_text('')
        assert readCurrentBootId(str(bootIdPath)) is None


class TestRunJournalctl:
    """``journalctl --no-pager <args>`` subprocess wrapper."""

    def test_runJournalctl_success_returnsStdout(self) -> None:
        with patch.object(boot_reason.subprocess, 'run') as mockRun:
            mockRun.return_value = subprocess.CompletedProcess(
                args=['journalctl', '--no-pager', '--list-boots'],
                returncode=0,
                stdout=_LIST_BOOTS_OUTPUT,
                stderr='',
            )
            result = runJournalctl(['--list-boots'])
            assert result == _LIST_BOOTS_OUTPUT
            calledArgs = mockRun.call_args.args[0]
            assert calledArgs[0] == 'journalctl'
            assert '--no-pager' in calledArgs
            assert '--list-boots' in calledArgs

    def test_runJournalctl_fileNotFound_returnsNone(self) -> None:
        with patch.object(
            boot_reason.subprocess,
            'run',
            side_effect=FileNotFoundError("journalctl"),
        ):
            assert runJournalctl(['--list-boots']) is None

    def test_runJournalctl_timeout_returnsNone(self) -> None:
        with patch.object(
            boot_reason.subprocess,
            'run',
            side_effect=subprocess.TimeoutExpired(cmd='journalctl', timeout=1.0),
        ):
            assert runJournalctl(['--list-boots']) is None

    def test_runJournalctl_nonZeroExit_returnsStdoutAnyway(self) -> None:
        # journalctl can emit warnings about pruned boots and still
        # produce useful stdout; we should not throw it away.
        with patch.object(boot_reason.subprocess, 'run') as mockRun:
            mockRun.return_value = subprocess.CompletedProcess(
                args=['journalctl', '--no-pager', '--list-boots'],
                returncode=1,
                stdout=_LIST_BOOTS_OUTPUT,
                stderr='Hint: You are currently not seeing messages from other users.',
            )
            assert runJournalctl(['--list-boots']) == _LIST_BOOTS_OUTPUT


# ================================================================================
# US-283 -- Production Schema Pin
# ================================================================================

class TestStartupLogSchema:
    """Pin the canonical ``startup_log`` column set from US-263 (Sprint 22).

    Sprint 24 US-283 audit traced Spool's drift flag to its source: the
    deployed table has no ``id`` column.  That matches the spec -- the
    canonical schema uses ``boot_id`` as the PRIMARY KEY and there never
    was an ``id`` column.  Production ``SCHEMA_STARTUP_LOG`` in
    ``src/pi/obdii/database_schema.py`` already matches the US-263
    contract (5 columns: ``boot_id`` TEXT PK, ``prior_boot_clean``
    INTEGER, ``prior_last_entry_ts`` TEXT, ``current_boot_first_entry_ts``
    TEXT, ``recorded_at`` TEXT NOT NULL).

    These tests apply the production schema to a fresh in-memory SQLite,
    introspect via ``PRAGMA table_info``, and assert the (name, type,
    notnull, pk) tuple matches the contract exactly.  Any future drift --
    a stray ``id`` column, a renamed column, a type change, an added
    NOT NULL, or a compound PK -- breaks the test loudly instead of
    silently rotting the writer / reader contract.
    """

    # (name, type, notnull, pk) per ``PRAGMA table_info`` semantics.
    # ``dflt_value`` is intentionally not pinned: ``recorded_at`` carries
    # a ``DEFAULT (strftime(...))`` expression in production and we treat
    # that detail as orthogonal to the column-set contract.
    EXPECTED_COLUMNS: tuple[tuple[str, str, int, int], ...] = (
        ('boot_id', 'TEXT', 0, 1),
        ('prior_boot_clean', 'INTEGER', 0, 0),
        ('prior_last_entry_ts', 'TEXT', 0, 0),
        ('current_boot_first_entry_ts', 'TEXT', 0, 0),
        # 2026-05-15 honest-instrument addition (spec
        # 2026-05-15-honest-boot-progress-instrument-design.md §4.4):
        # highest boot_progress milestone reached + its decoded reason.
        ('prior_boot_last_stage', 'TEXT', 0, 0),
        ('prior_boot_reason', 'TEXT', 0, 0),
        ('recorded_at', 'TEXT', 1, 0),
    )

    @staticmethod
    def _introspectStartupLog() -> tuple[tuple[str, str, int, int], ...]:
        """Apply production schema to a fresh DB and return PRAGMA tuple."""
        conn = sqlite3.connect(':memory:')
        try:
            conn.executescript(SCHEMA_STARTUP_LOG)
            cursor = conn.execute("PRAGMA table_info(startup_log)")
            return tuple(
                (row[1], row[2].upper(), row[3], row[5])
                for row in cursor.fetchall()
            )
        finally:
            conn.close()

    def test_startupLogSchema_matchesUs263CanonicalColumnSet(self) -> None:
        # 2026-05-15 honest-instrument addition: the canonical set grew
        # from the original US-263 5 columns to 7 -- prior_boot_last_stage
        # and prior_boot_reason were added per design spec
        # 2026-05-15-honest-boot-progress-instrument-design.md §4.4.  This
        # remains a STRICT exact-set assertion (no subset / >=); any other
        # drift still breaks loudly.
        actual = self._introspectStartupLog()
        assert actual == self.EXPECTED_COLUMNS, (
            "startup_log schema drift detected.\n"
            f"Expected: {self.EXPECTED_COLUMNS}\n"
            f"Actual:   {actual}\n"
            "If this fails after a deliberate schema change, update both "
            "EXPECTED_COLUMNS and the US-263 spec; do NOT relax the test."
        )

    def test_startupLogSchema_bootIdIsSolePrimaryKey(self) -> None:
        # Defends specifically against the failure mode Spool flagged:
        # someone "fixing" the schema by adding an ``id INTEGER PRIMARY KEY``
        # rowid alias and demoting boot_id to a UNIQUE column.  That
        # would silently break the writer's INSERT OR IGNORE idempotency
        # contract because the PK changes from boot_id to rowid.
        actual = self._introspectStartupLog()
        pkColumns = [name for (name, _type, _notnull, pk) in actual if pk == 1]
        assert pkColumns == ['boot_id'], (
            f"startup_log PK must be exactly ['boot_id']; got {pkColumns}. "
            "Adding an `id` rowid alias or compound PK breaks the US-263 "
            "INSERT OR IGNORE idempotency contract."
        )

    def test_startupLogSchema_columnCount_isSeven(self) -> None:
        # Quick canary on extra columns: any addition (even if otherwise
        # well-formed) widens the contract surface; force a deliberate
        # spec update instead of silently accepting drift.  2026-05-15
        # honest-instrument: count grew 5 -> 7 (prior_boot_last_stage +
        # prior_boot_reason added per design spec
        # 2026-05-15-honest-boot-progress-instrument-design.md §4.4).
        actual = self._introspectStartupLog()
        assert len(actual) == 7, (
            f"startup_log has {len(actual)} columns; canonical schema is "
            f"exactly 7 (US-263 5-col + 2026-05-15 honest-instrument "
            f"prior_boot_last_stage/prior_boot_reason). "
            f"Got: {[name for (name, *_) in actual]}"
        )


# ================================================================================
# US-287 -- Lifecycle Wiring (writer is called at boot)
# ================================================================================

class TestLifecycleWiring:
    """Pin the US-287 wiring contract: ``recordBootReason`` is invoked at
    boot from ``LifecycleMixin._initializeAllComponents`` immediately after
    ``_initializeDatabase`` and before ``_initializeProfileManager`` -- the
    earliest call site with DB access and prior to the OBD connect path
    that has historically blocked init for hours (US-284).

    Sprint 22 (US-263) shipped the writer + tests; Sprint 24 (US-283)
    pinned the schema; no code path actually invoked the writer until
    this story.  These tests fail pre-fix (no ``_recordStartupLog``
    method on the mixin, no call site in ``_initializeAllComponents``)
    and pass post-fix.

    Wiring scope deviation note: the story's ``scope.filesToTouch`` does
    not list ``src/pi/obdii/orchestrator/lifecycle.py`` explicitly, but
    its ``stopConditions[0]`` says "pick the earliest site that has DB
    access + document choice in completionNotes" -- which authorizes
    touching the lifecycle module.  These tests live alongside the
    writer's own tests in this file rather than spawning a parallel
    test_lifecycle_startup_log.py because the contract under test is
    "the writer reaches the database via the orchestrator's init
    sequence" -- that is squarely a writer-side wiring assertion.
    """

    def test_lifecycleWiring_recordStartupLog_methodExists(self) -> None:
        # Failure mode: pre-US-287 the LifecycleMixin has no
        # _recordStartupLog method, the boot path has no entry point
        # for the writer, and no rows ever land in startup_log.
        from src.pi.obdii.orchestrator.lifecycle import LifecycleMixin
        assert hasattr(LifecycleMixin, '_recordStartupLog'), (
            "LifecycleMixin must expose _recordStartupLog so the boot "
            "path can write the startup_log row.  US-287 wiring."
        )

    def test_lifecycleWiring_recordStartupLog_invokesRecordBootReasonWithDatabase(
        self,
    ) -> None:
        # Pin the contract: _recordStartupLog hands the orchestrator's
        # live database to recordBootReason (the US-263 entry point).
        # Anything else (e.g. None, a different attribute) silently
        # breaks the writer.
        from src.pi.obdii.orchestrator import lifecycle as lifecycleModule

        class _Stub:
            _database = object()

        stub = _Stub()
        seen: list[Any] = []

        def _fakeRecord(database: Any) -> bool:
            seen.append(database)
            return True

        with patch.object(lifecycleModule, 'recordBootReason', _fakeRecord):
            lifecycleModule.LifecycleMixin._recordStartupLog(stub)

        assert seen == [stub._database]

    def test_lifecycleWiring_recordStartupLog_swallowsExceptionsGracefully(
        self,
    ) -> None:
        # Story invariant: "If journalctl is unavailable or returns
        # malformed output -- log error and skip; do NOT crash boot
        # path."  Any exception thrown by recordBootReason MUST NOT
        # propagate; init must continue.
        from src.pi.obdii.orchestrator import lifecycle as lifecycleModule

        class _Stub:
            _database = object()

        def _raisingRecord(database: Any) -> bool:
            raise RuntimeError("simulated journalctl explosion")

        stub = _Stub()
        with patch.object(lifecycleModule, 'recordBootReason', _raisingRecord):
            # Must NOT raise.  Pre-fix this would either fail the
            # missing-method assertion above, or (if a naive impl is
            # added) re-raise the RuntimeError and crash the boot path.
            lifecycleModule.LifecycleMixin._recordStartupLog(stub)

    def test_lifecycleWiring_recordStartupLog_databaseNone_isNoOp(self) -> None:
        # Defensive: if the database somehow failed to initialize and
        # _database is None, the wiring must short-circuit rather than
        # invoking recordBootReason(None) (which itself returns False
        # but emits no row + no log).  Cleaner not to call.
        from src.pi.obdii.orchestrator import lifecycle as lifecycleModule

        class _Stub:
            _database = None

        called = [False]

        def _shouldNotBeCalled(database: Any) -> bool:
            called[0] = True
            return False

        stub = _Stub()
        with patch.object(lifecycleModule, 'recordBootReason', _shouldNotBeCalled):
            lifecycleModule.LifecycleMixin._recordStartupLog(stub)
        assert called == [False], (
            "_recordStartupLog must short-circuit when self._database is "
            "None -- otherwise recordBootReason(None) is invoked needlessly."
        )

    def test_lifecycleWiring_initializeAllComponents_callsRecordStartupLogBetweenDatabaseAndProfile(
        self,
    ) -> None:
        # The acceptance criterion "called at boot from main.py or
        # lifecycle init" requires the call to be wired into the
        # production init sequence.  Source-level inspection: assert
        # _recordStartupLog appears AFTER _initializeDatabase and
        # BEFORE _initializeProfileManager in _initializeAllComponents.
        # The earliest-DB-access invariant is what gives the row a
        # chance to land before the US-284 blocker territory.
        import inspect

        from src.pi.obdii.orchestrator.lifecycle import LifecycleMixin
        src = inspect.getsource(LifecycleMixin._initializeAllComponents)
        assert '_recordStartupLog' in src, (
            "_initializeAllComponents must invoke self._recordStartupLog. "
            "US-287 wiring."
        )
        posDb = src.index('_initializeDatabase')
        posStartup = src.index('_recordStartupLog')
        posProfile = src.index('_initializeProfileManager')
        assert posDb < posStartup < posProfile, (
            "_recordStartupLog must be invoked AFTER _initializeDatabase "
            "(needs self._database) and BEFORE _initializeProfileManager "
            "(stays clear of OBD-connect blocker territory).  "
            f"Got positions: db={posDb} startup={posStartup} profile={posProfile}."
        )
