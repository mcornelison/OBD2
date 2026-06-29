################################################################################
# File Name: test_drive2829_close_signal_reproducer.py
# Purpose/Description: US-386 (F-107) -- deterministic in-process reproducer for
#                      the DriveDetector close-signal defect that recurred on
#                      drives 28/29 (drive_start 29 / drive_end 18 -- missed
#                      closes + stale-open absorption).  Replays synthetic
#                      engine-state (RPM) + timing sequences for three scenarios
#                      (short drive / back-to-back / key-on after a missed close)
#                      and asserts CORRECT attribution.  The two stale-open
#                      scenarios ship RED-as-xfail (the defect); US-388 fixes the
#                      detector and removes the xfail markers.
# Author: Rex (Ralph agent)
# Creation Date: 2026-06-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-28    | Rex (US-386) | Initial -- drives 28/29 close-signal reproducer.
#                               Clock-injected (no wall-clock dependency), no
#                               comms events (RPM + the ABSENCE of ticks only --
#                               Spool ruled out comms-drop).  Reproduces the
#                               Root-2 stale-open/missed-close/absorption half of
#                               the 28/29 signature in-process.
# ================================================================================
################################################################################

"""US-386 -- in-process reproducer for the DriveDetector close-signal defect.

Live origin (drives 28/29, ~2026-06-06): the DriveDetector dual-attribution
defect recurred after the US-361 fix.  Spool's 2-table corroboration ruled out
a comms-drop (``connection_log`` shows ZERO drive_id on any failure/disconnect;
the K-line is stable mid-drive) and isolated the bug to the DriveDetector
close-signal state machine: ``drive_start`` fired 29 times but ``drive_end``
only 18 -- 11 drives never closed.  Per Atlas's 2026-06-19 RCA ruling the
signature has two distinct roots:

* **Root 1 -- concurrent process** (two ``eclipse-obd`` PIDs racing the shared
  ``drive_counter``).  This is what produces the server-visible *overlap*
  (two drive_ids open at once, ids possibly out of temporal order).  It is
  mitigated out-of-band (single-instance guard ``d6d8b05`` + RuntimeDirectory
  ``fae7ee7`` + Pi deploy) and made durable by US-389; backstopped server-side
  by ``detect_overlapping_drives`` (US-390).  **It is NOT reproducible inside a
  single in-process detector** -- one ``DriveDetector`` instance can never hold
  two simultaneously-open sessions (the only exit from ``RUNNING`` is
  ``_endDrive``, which writes the matching ``drive_end``).  Reproducing it would
  require two racing processes, i.e. the real lifecycle loop -- out of scope for
  this in-process harness by construction, not by omission.
* **Root 2 -- stale-open / missed-close leak** (the substantive open work,
  fixed by US-388).  When the engine stops and the data-acquisition readings
  STOP before the ``driveEndDurationSeconds`` RPM-debounce completes -- with NO
  adapter heartbeat to drive the US-229 ECU-silence path either (NO comms
  events, per the US-386 contract) -- the drive never closes.  The session sits
  open (stale).  A later key-on arrives while the state machine is still inside
  the open drive, so ``_processRpmValue`` merely *continues* the stale session
  (``RUNNING``/``STOPPING`` + RPM-above-end -> ``belowThresholdSince=None``) and
  mints NO new ``drive_id``.  The second physical drive is ABSORBED into the
  first drive's id (the multi-day-leak / missed-close half of 28/29).

This harness reproduces **Root 2** deterministically, in-process, with no car
and no comms events.  Scenarios:

1. ``test_shortDrive_opensAndClosesExactlyOneDriveId`` (scenario a) -- a clean
   ~3-minute drive whose key-off readings continue long enough to complete the
   RPM-debounce.  GREEN on current code: the control case that proves the
   harness yields CORRECT attribution for a normally-closing drive, so the RED
   in the stale-open scenarios is a real defect and not a harness artifact.
2. ``test_backToBackMissedClose_eachPhysicalDriveOwnDriveId`` (scenario b) --
   two back-to-back drives ~1 minute apart where the FIRST drive's close is
   missed (engine-off readings stop before the debounce completes).  Asserts the
   correct invariant (two distinct closed drive_ids, no absorption).  RED on
   current code (absorbed into one id) -> ships ``xfail``.
3. ``test_keyOnAfterMissedClose_mintsNewDriveId_noAbsorption`` (scenario c) --
   a key-on a full day after a drive whose close never fired.  Same Root-2
   mechanism across a key cycle.  RED on current code -> ships ``xfail``.

Ships RED-as-xfail (the team pattern established by the US-359 Drive 23/24
reproducer): the two stale-open assertions currently fail, pytest reports them
``xfailed``, and the default ``-m "not slow"`` sweep stays GREEN (every sibling
F-107 Story requires "Pi tests stay GREEN").  Run with ``-rx`` to see the
captured absorption message, or ``--runxfail`` to observe the literal assertion
failure (US-386 validationCriteria V-1).  US-388 collapses the absorption to a
fresh drive_id per physical drive and REMOVES the two ``xfail`` markers (one
line each) so the tests become the permanent Root-2 regression net (US-388 AC
"US-386 reproducer GREEN" + US-390 "added to the fast suite / regression
manifest, permanent").

Determinism: the detector reads ``datetime.now()`` for every state-machine
timing decision.  This harness patches the ``datetime`` symbol in both
``drive.detector`` and ``drive.types`` with an :class:`InjectedClock` whose
``now()`` returns a value the replay advances explicitly between events.  There
is no ``time.sleep`` and no wall-clock dependency: re-running the identical
replay is bit-for-bit reproducible (pinned by ``test_reproIsDeterministic``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import src.pi.obdii.drive.detector as detector_mod
import src.pi.obdii.drive.types as types_mod
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import (
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
)
from src.pi.obdii.drive_id import clearCurrentDriveId

# ================================================================================
# Grounded constants
# ================================================================================
#
# Thresholds are the PRODUCTION defaults so the reproducer exercises the same
# timing envelope as the real drives 28/29.  An injected clock makes the
# 10s/60s windows free -- no wall-clock cost, full fidelity.  (Grounding:
# drive/types.py DEFAULT_DRIVE_* + config.json pi.analysis.)
_START_RPM_THRESHOLD = DEFAULT_DRIVE_START_RPM_THRESHOLD  # 500 RPM
_START_DURATION_SEC = DEFAULT_DRIVE_START_DURATION_SECONDS  # 10 s
_END_RPM_THRESHOLD = DEFAULT_DRIVE_END_RPM_THRESHOLD  # 0 RPM
_END_DURATION_SEC = DEFAULT_DRIVE_END_DURATION_SECONDS  # 60 s

# Fixed, NTP-independent epoch for the replay.  Chosen on the drives 28/29
# incident date (2026-06-06) purely for readability; the value is arbitrary
# because the injected clock never consults the real wall clock.
_BASE_TS = datetime(2026, 6, 6, 8, 0, 0)

# RPM values sit inside the normal 4G63 driving envelope (grounded-knowledge.md).
_CRANK_RPM = 600.0      # above the 500 start threshold
_CRUISE_RPM = 2500.0    # cruising
_KEY_OFF_RPM = 0.0      # at/below the 0 end threshold

# ================================================================================
# Replay event sequences -- (offsetSeconds, parameter, value)
# ================================================================================
#
# Every sequence is RPM-ONLY: per the US-386 contract there are NO comms events
# (no BATTERY_V adapter heartbeat), and a "missed close" is modelled by the
# ABSENCE of ticks -- the readings simply stop before the RPM-debounce window
# completes, exactly as a real key-off cuts the data-acquisition loop short.

# Scenario (a): one clean short drive (~3 min).  Key-off readings CONTINUE past
# the 60s debounce, so the drive closes normally -> exactly one closed drive_id.
_SHORT_DRIVE_REPLAY: tuple[tuple[float, str, float], ...] = (
    (0.0, "RPM", _CRANK_RPM),     # STOPPED -> STARTING (above-threshold timer arms)
    (11.0, "RPM", _CRUISE_RPM),   # 11 s >= 10 s -> _startDrive -> drive_id #1, RUNNING
    (60.0, "RPM", _CRUISE_RPM),   # cruising
    (120.0, "RPM", _CRUISE_RPM),
    (170.0, "RPM", _CRUISE_RPM),  # ~3 min of driving
    (180.0, "RPM", _KEY_OFF_RPM),  # RUNNING -> STOPPING (below-end timer arms)
    (241.0, "RPM", _KEY_OFF_RPM),  # 61 s >= 60 s -> RPM-debounce drive_end (#1 closes)
)

# Scenario (b): two back-to-back drives ~1 min apart.  The FIRST drive's close
# is MISSED -- engine off, two RPM=0 readings (only 20 s, < 60 s debounce), then
# the readings stop.  ~1 min later the second drive cranks.  CORRECT behaviour:
# two distinct closed drive_ids.  DEFECT (current): the second drive is absorbed
# into the first's open session -> one drive_id.
_BACK_TO_BACK_MISSED_CLOSE_REPLAY: tuple[tuple[float, str, float], ...] = (
    # -- Drive 1: cranks, runs, engine off, close MISSED (readings stop @ 20 s).
    (0.0, "RPM", _CRANK_RPM),     # STARTING
    (11.0, "RPM", _CRUISE_RPM),   # _startDrive -> drive_id #1, RUNNING
    (60.0, "RPM", _CRUISE_RPM),   # cruising
    (90.0, "RPM", _KEY_OFF_RPM),  # RUNNING -> STOPPING (belowThresholdSince=90)
    (110.0, "RPM", _KEY_OFF_RPM),  # 20 s < 60 s -> debounce NOT met; readings then STOP
    # (gap: ~1 min with no ticks -- the close never completes)
    # -- Drive 2: cranks ~1 min later.  Should mint drive_id #2; instead absorbed.
    (170.0, "RPM", _CRANK_RPM),   # key-on (defect: continues the stale session)
    (181.0, "RPM", _CRUISE_RPM),  # 11 s >= 10 s -> CORRECT: _startDrive #2; DEFECT: still #1
    (230.0, "RPM", _CRUISE_RPM),  # cruising
    (260.0, "RPM", _KEY_OFF_RPM),  # second key-off -> STOPPING
    (321.0, "RPM", _KEY_OFF_RPM),  # 61 s >= 60 s -> RPM-debounce drive_end
)

# Scenario (c): a key-on a FULL DAY after a drive whose close never fired.  Same
# Root-2 mechanism as (b), but across a key cycle / large time gap to prove the
# absorption is not bounded by MIN_INTER_DRIVE_SECONDS.
_DAY = 24 * 60 * 60
_KEY_ON_AFTER_MISSED_CLOSE_REPLAY: tuple[tuple[float, str, float], ...] = (
    # -- Drive 1: cranks, runs, engine off, close MISSED (readings stop @ 20 s).
    (0.0, "RPM", _CRANK_RPM),
    (11.0, "RPM", _CRUISE_RPM),   # _startDrive -> drive_id #1, RUNNING
    (60.0, "RPM", _CRUISE_RPM),
    (90.0, "RPM", _KEY_OFF_RPM),  # STOPPING (belowThresholdSince=90)
    (110.0, "RPM", _KEY_OFF_RPM),  # 20 s < 60 s -> debounce NOT met; readings STOP
    # (gap: a full day with no ticks -- stale-open leak across a key cycle)
    # -- Drive 2: next day's first drive.  Should mint drive_id #2; instead absorbed.
    (float(_DAY), "RPM", _CRANK_RPM),
    (float(_DAY) + 11.0, "RPM", _CRUISE_RPM),  # CORRECT: _startDrive #2; DEFECT: still #1
    (float(_DAY) + 60.0, "RPM", _CRUISE_RPM),
    (float(_DAY) + 120.0, "RPM", _KEY_OFF_RPM),  # STOPPING
    (float(_DAY) + 181.0, "RPM", _KEY_OFF_RPM),  # 61 s >= 60 s -> drive_end
)


# ================================================================================
# Injected clock (deterministic; no wall-clock dependency)
# ================================================================================


class InjectedClock:
    """Controllable stand-in for the ``datetime`` symbol used by the detector.

    Only ``now()`` is consulted by the code under test (``DriveDetector`` +
    ``DriveSession.getDuration``); ``timedelta`` is a separate import and is left
    untouched.  ``current`` is advanced explicitly by the replay driver between
    events so the state machine sees exact, reproducible elapsed times.
    """

    def __init__(self, base: datetime) -> None:
        self.current = base

    def now(self, tz: Any = None) -> datetime:  # noqa: ARG002 - tz parity with datetime.now
        """Return the frozen current time (ignores ``tz``; replay is naive-UTC)."""
        return self.current


# ================================================================================
# Fixtures / harness
# ================================================================================


@pytest.fixture()
def makeDb(tmp_path: Path) -> Callable[[], ObdDatabase]:
    """Factory for fresh, initialized on-disk SQLite databases.

    A factory (not a single DB) because the determinism test needs two
    independent runs.  ``initialize()`` builds ``connection_log`` +
    ``drive_counter`` + ``pi_state`` so ``_openDriveId`` mints real monotonic
    ids and ``drive_start``/``drive_end`` rows persist -- the authoritative
    record of how many distinct drive_ids each replay produced.
    """
    created: list[ObdDatabase] = []

    def _factory() -> ObdDatabase:
        dbPath = tmp_path / f"us386_repro_{len(created)}.db"
        db = ObdDatabase(str(dbPath), walMode=False)
        db.initialize()
        created.append(db)
        return db

    yield _factory
    # Drop the process-wide drive_id context so a stale id can't leak between
    # tests (the US-359 reproducer follows the same teardown discipline).
    clearCurrentDriveId()


def _reproConfig() -> dict[str, Any]:
    """Tier-aware config pinned to production drive-detection thresholds."""
    return {
        "pi": {
            "analysis": {
                "driveStartRpmThreshold": _START_RPM_THRESHOLD,
                "driveStartDurationSeconds": _START_DURATION_SEC,
                "driveEndRpmThreshold": _END_RPM_THRESHOLD,
                "driveEndDurationSeconds": _END_DURATION_SEC,
                # No SummaryRecorder/snapshot source wired -> defer-INSERT
                # disarms immediately; this harness is about drive_id emission.
                "triggerAfterDrive": False,
                "driveSummaryBackfillSeconds": 0,
            },
        },
    }


def _replay(
    db: ObdDatabase, sequence: tuple[tuple[float, str, float], ...]
) -> None:
    """Drive ``sequence`` through a fresh DriveDetector under an injected clock.

    Patches ``datetime`` in the detector + types modules with an
    :class:`InjectedClock`, advances it explicitly between events, and feeds each
    reading through ``processValue``.  ``stop()`` is deliberately NOT used to
    close drives: every replay ends with the detector already STOPPED via the
    natural RPM-debounce, so the persisted ``connection_log`` reflects only the
    detector's own close-signal behaviour (the thing under test).
    """
    clock = InjectedClock(_BASE_TS)
    with (
        patch.object(detector_mod, "datetime", clock),
        patch.object(types_mod, "datetime", clock),
    ):
        detector = DriveDetector(config=_reproConfig(), database=db)
        detector.start()
        for offsetSeconds, parameterName, value in sequence:
            clock.current = _BASE_TS + timedelta(seconds=offsetSeconds)
            detector.processValue(parameterName, value)


def _driveIds(db: ObdDatabase, eventType: str) -> list[int]:
    """Distinct, sorted ``drive_id`` values on ``connection_log`` rows of a type."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT drive_id FROM connection_log "
            "WHERE event_type = ? AND drive_id IS NOT NULL "
            "ORDER BY drive_id ASC",
            (eventType,),
        ).fetchall()
    return [int(r[0]) for r in rows]


def _startIds(db: ObdDatabase) -> list[int]:
    """Distinct drive_ids that opened a drive (drive_start rows)."""
    return _driveIds(db, "drive_start")


def _endIds(db: ObdDatabase) -> list[int]:
    """Distinct drive_ids that closed a drive (drive_end rows)."""
    return _driveIds(db, "drive_end")


# ================================================================================
# Scenario (a): clean short drive -- the GREEN control
# ================================================================================


class TestShortDriveControl:
    """A normally-closing drive must resolve to exactly one closed drive_id."""

    def test_shortDrive_opensAndClosesExactlyOneDriveId(
        self, makeDb: Callable[[], ObdDatabase]
    ) -> None:
        """
        Given: a single ~3-minute drive whose key-off readings continue long
            enough to complete the RPM-debounce.
        When: replayed through DriveDetector under an injected clock.
        Then: exactly one drive_id, opened AND closed.

        GREEN on current code -- the control that proves the harness yields
        correct attribution for a normally-closing drive, so the RED in the
        stale-open scenarios below is a genuine defect, not a harness artifact.
        """
        db = makeDb()

        _replay(db, _SHORT_DRIVE_REPLAY)

        assert _startIds(db) == _endIds(db), (
            "a cleanly-closing drive must open and close the SAME single id: "
            f"starts={_startIds(db)} ends={_endIds(db)}"
        )
        assert len(_startIds(db)) == 1, (
            f"one physical drive must mint exactly one drive_id; got {_startIds(db)}"
        )


# ================================================================================
# Scenario (b): back-to-back with a missed first close -- RED (Root-2 absorption)
# ================================================================================


class TestBackToBackMissedClose:
    """Two back-to-back drives, the first's close missed, must NOT be absorbed."""

    @pytest.mark.xfail(
        reason=(
            "US-386 Root-2 reproducer (drives 28/29 stale-open leak): the first "
            "drive's missed close leaves the session open, so the back-to-back "
            "second drive is ABSORBED into drive_id #1 instead of minting #2. "
            "US-388 fixes the close-signal state machine and REMOVES this marker."
        ),
        strict=False,
    )
    def test_backToBackMissedClose_eachPhysicalDriveOwnDriveId(
        self, makeDb: Callable[[], ObdDatabase]
    ) -> None:
        """
        Given: two back-to-back drives ~1 minute apart; the first drive's close
            is missed because the engine-off readings stop (20 s) before the 60 s
            RPM-debounce completes -- and there are NO comms events to drive the
            ECU-silence path either.
        When: replayed through DriveDetector under an injected clock.
        Then (correct): two distinct drive_ids, each opened AND closed; no
            absorption of the second physical drive into the first's id.

        RED on current code: the stale-open first session absorbs the second
        drive -> a single drive_id spans both physical drives (the missed-close
        half of the 28/29 signature).  Ships xfail; US-388 flips it GREEN.
        """
        db = makeDb()

        _replay(db, _BACK_TO_BACK_MISSED_CLOSE_REPLAY)

        starts = _startIds(db)
        assert len(starts) == 2, (
            f"two physical drives must mint two drive_ids; got {starts}. "
            "The first drive's missed close absorbed the second drive into one "
            "id (F-107 Root-2 stale-open leak)."
        )
        assert _endIds(db) == starts, (
            "each physical drive must close on key-off (every opened id must "
            f"also appear as a drive_end): starts={starts} ends={_endIds(db)}"
        )


# ================================================================================
# Scenario (c): key-on after a drive whose close never fired -- RED (absorption)
# ================================================================================


class TestKeyOnAfterMissedClose:
    """A key-on after a stale-open drive must open a NEW drive_id."""

    @pytest.mark.xfail(
        reason=(
            "US-386 Root-2 reproducer (drives 28/29 stale-open leak): a drive "
            "whose close never fired stays open across a key cycle, so the next "
            "day's key-on is ABSORBED into the stale drive_id instead of minting "
            "a fresh one. US-388 fixes the close-signal state machine and REMOVES "
            "this marker."
        ),
        strict=False,
    )
    def test_keyOnAfterMissedClose_mintsNewDriveId_noAbsorption(
        self, makeDb: Callable[[], ObdDatabase]
    ) -> None:
        """
        Given: a drive whose close never fired (engine-off readings stopped
            before the debounce completed; no comms events), followed a FULL DAY
            later by a key-on.
        When: replayed through DriveDetector under an injected clock.
        Then (correct): the key-on opens a NEW drive_id -- two distinct drive_ids,
            each opened AND closed, no absorption.

        RED on current code: the next-day key-on continues the stale session, so
        both physical drives share one drive_id (the multi-day-leak / missed-close
        half of the 28/29 signature).  Ships xfail; US-388 flips it GREEN.
        """
        db = makeDb()

        _replay(db, _KEY_ON_AFTER_MISSED_CLOSE_REPLAY)

        starts = _startIds(db)
        assert len(starts) == 2, (
            f"a key-on after a stale-open drive must mint a NEW drive_id; got "
            f"{starts}. The next-day key-on was absorbed into the stale drive_id "
            "(F-107 Root-2 multi-day stale-open leak)."
        )
        assert _endIds(db) == starts, (
            "each physical drive must close on key-off (every opened id must "
            f"also appear as a drive_end): starts={starts} ends={_endIds(db)}"
        )


# ================================================================================
# Determinism (no wall-clock dependency)
# ================================================================================


class TestReproducerDeterminism:
    """The replay outcome is a pure function of the injected clock."""

    def test_reproIsDeterministic_acrossTwoRuns(
        self, makeDb: Callable[[], ObdDatabase]
    ) -> None:
        """
        Given: two independent databases and the same stale-open replay.
        When: each is replayed under a fresh injected clock.
        Then: both runs produce the identical drive_id attribution.

        Pins the AC "pure in-process; no IRL/hardware dependency": the result is
        reproducible regardless of real time, and the assertion is invariant to
        the US-388 fix (it compares the two runs to each other, not to a count).
        """
        dbA = makeDb()
        dbB = makeDb()

        _replay(dbA, _KEY_ON_AFTER_MISSED_CLOSE_REPLAY)
        _replay(dbB, _KEY_ON_AFTER_MISSED_CLOSE_REPLAY)

        assert _startIds(dbA) == _startIds(dbB), (
            "Replay is not deterministic: two identical runs produced different "
            f"start attributions ({_startIds(dbA)} vs {_startIds(dbB)}). The "
            "injected clock should make the outcome independent of wall-clock time."
        )
        assert _endIds(dbA) == _endIds(dbB)
        # Sanity floor: each replay always opens at least one drive_id under
        # either pre- or post-fix behaviour.
        assert len(_startIds(dbA)) >= 1
