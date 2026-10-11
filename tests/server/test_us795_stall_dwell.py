################################################################################
# File Name: test_us795_stall_dwell.py
# Purpose/Description: US-795 (reopened 2026-10-11) -- the stall alarm is
#                      Threshold + Dwell: a non-decreasing run of contacts
#                      alarms only when it also SPANS a minimum time. Replays
#                      the real 2026-10-11 sync_history sequences that raised
#                      false alarms at a departure and at a home key-off.
# Author: Atlas (Architect) -- US-795, CIO-directed close-out build
# Creation Date: 2026-10-11
################################################################################
"""The stall alarm needs a run AND a dwell (US-795, reopened 2026-10-11).

What failed on the car (2026-10-11 16:03:59Z): as the car drove out of WiFi
range only one 1-row POST completed per 5 s cycle while the drive's rows
accrued, so three per-table contacts read 57 -> 71 -> 113 inside 8 seconds.
The old rule (3 consecutive non-decreasing contacts, no time term) raised
"the car is reachable and the queue is not draining" -- and the sentence stood
for the whole two-hour drive. A fading link spans seconds; a stalled drain
persists while the car stays in contact. Pattern: specs/design-patterns.md
section 1, Threshold + Dwell.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.server.api.currency import (
    DEFAULT_STALL_DWELL_SECONDS,
    ContactRecord,
    assessVehicleCurrency,
    renderCurrency,
)


def _at(hms: str) -> datetime:
    return datetime.fromisoformat(f'2026-10-11T{hms}+00:00').astimezone(UTC)


def _replay(rows: list[tuple[str, int]]) -> list[ContactRecord]:
    return [
        ContactRecord(contactedAt=_at(hms), residualRows=residual, residualComplete=True)
        for hms, residual in rows
    ]


#: prod sync_history ids 235544..235566, chi-eclipse-01, oldest first -- the
#: boot sync, the drive-105 start, and the WiFi fade as the car left home.
_DEPARTURE_2026_10_11 = [
    ('16:03:21', 28), ('16:03:21', 25), ('16:03:21', 24), ('16:03:22', 15),
    ('16:03:22', 7), ('16:03:22', 3), ('16:03:22', 0), ('16:03:23', 0),
    ('16:03:23', 0), ('16:03:38', 228), ('16:03:38', 228), ('16:03:39', 73),
    ('16:03:39', 36), ('16:03:39', 20), ('16:03:40', 4), ('16:03:45', 67),
    ('16:03:45', 57), ('16:03:45', 48), ('16:03:46', 44), ('16:03:46', 4),
    ('16:03:51', 57), ('16:03:55', 71), ('16:03:59', 113),
]

#: prod sync_history ids 235468..235479 -- the 15:30 at-home key-off: the
#: shutdown drain's own rows (battery_health_log close, drain trajectory)
#: land last, so the residual ticks 3 -> 5 -> 7 inside one second.
_HOME_KEYOFF_2026_10_11 = [
    ('15:30:30', 59), ('15:30:30', 52), ('15:30:31', 53), ('15:30:31', 6),
    ('15:30:37', 38), ('15:30:37', 25), ('15:30:37', 12), ('15:30:37', 8),
    ('15:30:37', 6), ('15:30:38', 3), ('15:30:38', 5), ('15:30:38', 7),
]


class TestTheDwellIsGroundedInThePiCadence:

    def test_dwell_isTwoIdleHeartbeats(self) -> None:
        """Given: the Pi's IDLE cadence default (pi.sync.cadenceIdleSeconds)
        When: the server's dwell is compared to it
        Then: it is exactly two heartbeats -- the server cannot import Pi code
              at runtime, so this test is the cross-tier pin.
        """
        from src.pi.sync.sync_cadence_controller import DEFAULT_IDLE_CADENCE_SECONDS

        assert DEFAULT_STALL_DWELL_SECONDS == 2 * DEFAULT_IDLE_CADENCE_SECONDS


class TestTheRealFalseAlarmsAreGone:

    def test_departureFade_raisesNoAlarm(self) -> None:
        """Given: the 2026-10-11 16:03:59Z sequence (..., 4, 57, 71, 113)
        When: assessed
        Then: no fault -- the rising run spans 13 s, not a stall (DoD c)
        """
        answer = assessVehicleCurrency(_replay(_DEPARTURE_2026_10_11))

        assert answer.fault is None
        assert answer.outstandingRows == 113

    def test_homeKeyoffDrainRows_raiseNoAlarm(self) -> None:
        """Given: the 15:30:38Z at-home key-off (..., 3, 5, 7 in one second)
        When: assessed
        Then: no fault -- the old rule alarmed on this too
        """
        assert assessVehicleCurrency(_replay(_HOME_KEYOFF_2026_10_11)).fault is None


class TestLeadingZerosDoNotStartTheClock:

    def test_yesterdaysCaughtUpContact_doesNotStretchThisMorningsRun(self) -> None:
        """Given: last night's contact owed 0; this morning 3 -> 5 -> 7 in 2 s
        When: assessed
        Then: no fault -- the run starts at the first contact that held rows,
              so it spans 2 s, not 11 h
        """
        contacts = [
            ContactRecord(contactedAt=_at('22:00:00') - timedelta(days=1), residualRows=0, residualComplete=True),
            ContactRecord(contactedAt=_at('09:00:00'), residualRows=3, residualComplete=True),
            ContactRecord(contactedAt=_at('09:00:01'), residualRows=5, residualComplete=True),
            ContactRecord(contactedAt=_at('09:00:02'), residualRows=7, residualComplete=True),
        ]

        assert assessVehicleCurrency(contacts).fault is None


class TestAGenuineStallStillAlarms:

    def test_flatRunSpanningTheDwell_alarms(self) -> None:
        """Given: 400, 400, 400 spanning exactly the dwell
        When: assessed
        Then: fault (DoD d)
        """
        start = _at('12:00:00')
        half = timedelta(seconds=DEFAULT_STALL_DWELL_SECONDS / 2)
        contacts = [
            ContactRecord(contactedAt=start + i * half, residualRows=400, residualComplete=True)
            for i in range(3)
        ]

        assert assessVehicleCurrency(contacts).fault is not None

    def test_flatRunJustShortOfTheDwell_isNotYetAStall(self) -> None:
        """Given: 400, 400, 400 spanning one second less than the dwell
        When: assessed
        Then: no fault yet
        """
        start = _at('12:00:00')
        step = timedelta(seconds=(DEFAULT_STALL_DWELL_SECONDS - 1) / 2)
        contacts = [
            ContactRecord(contactedAt=start + i * step, residualRows=400, residualComplete=True)
            for i in range(3)
        ]

        assert assessVehicleCurrency(contacts).fault is None

    def test_denseStallOverTheDwell_alarms_andTheRunIsMeasuredFromItsStart(self) -> None:
        """Given: a drain that drops to 300, then sits at 300 for 150 s with a
              contact every 0.4 s (ACTIVE density)
        When: assessed
        Then: fault, and the stated span runs from the first 300, not from
              the last three contacts
        """
        start = _at('12:00:00')
        contacts = [ContactRecord(contactedAt=start, residualRows=900, residualComplete=True)]
        contacts += [
            ContactRecord(
                contactedAt=start + timedelta(seconds=1 + 0.4 * i),
                residualRows=300, residualComplete=True,
            )
            for i in range(376)
        ]

        fault = assessVehicleCurrency(contacts).fault

        assert fault is not None
        assert '376 consecutive contacts' in fault
        assert 'over 2 min' in fault


class TestTheSentence:

    def test_theAlarmIsInThePastTense_andMakesNoReachabilityClaim(self) -> None:
        """Given: a genuine stall
        When: rendered
        Then: past tense (DoD b); the present-tense 'is reachable' is gone
        """
        start = _at('12:00:00')
        contacts = [
            ContactRecord(contactedAt=start + timedelta(minutes=i), residualRows=400, residualComplete=True)
            for i in range(3)
        ]

        rendered = renderCurrency(assessVehicleCurrency(contacts), now=start + timedelta(minutes=3))

        assert ' | ALARM: backlog did not decrease across 3 consecutive contacts over 2 min ' in rendered
        assert '(400 -> 400 -> 400)' in rendered
        assert 'the car was in contact and its queue was not draining' in rendered
        assert 'is reachable' not in rendered
        assert 'is not draining' not in rendered

    def test_aLongRun_elidesItsMiddle(self) -> None:
        """Given: a 50-contact flat run over the dwell
        When: rendered
        Then: the count chain shows first, second-to-last and last only
        """
        start = _at('12:00:00')
        contacts = [
            ContactRecord(contactedAt=start + timedelta(seconds=3 * i), residualRows=400, residualComplete=True)
            for i in range(50)
        ]

        fault = assessVehicleCurrency(contacts).fault

        assert fault is not None
        assert '(400 -> ... -> 400 -> 400)' in fault

    def test_theCountsStatementIsUnchanged(self) -> None:
        """Given: the departure replay (no alarm any more)
        When: rendered
        Then: the counts sentence is the US-795(a) sentence, byte for byte (DoD e)
        """
        contacts = _replay(_DEPARTURE_2026_10_11)

        rendered = renderCurrency(assessVehicleCurrency(contacts), now=_at('16:05:00'))

        assert rendered == (
            'last contact 2026-10-11T16:03:59Z (1 min ago): 113 queued (exact); nothing known since'
        )


class TestTheReaderSeesTheWholeDwell:

    def test_aDenseStallAlarmsThroughTheRealReader(self, tmp_path) -> None:
        """Given: sync_history rows every 0.4 s for 150 s, residual flat
        When: the real sync_status reader assesses the device
        Then: fault -- the read window spans the dwell at ACTIVE density
              (the old 20-row window saw ~8 s and could never satisfy it)
        """
        pytest.importorskip('fastapi')
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from src.server.db.models import Base, SyncHistory
        from src.server.services import sync_status

        engine = create_engine(f"sqlite:///{tmp_path / 'server.db'}")
        Base.metadata.create_all(engine)
        start = datetime(2026, 10, 11, 12, 0, 0)
        with Session(engine) as session:
            for i in range(376):
                at = start + timedelta(seconds=0.4 * i)
                session.add(SyncHistory(
                    device_id='car-a', status='completed', started_at=at, completed_at=at,
                    residual_rows=300, residual_complete=True,
                ))
            session.commit()

        with Session(engine) as session:
            (status,) = sync_status.readSyncStatus(
                session, now=datetime(2026, 10, 11, 12, 3, 0, tzinfo=UTC),
            )

        assert status.fault is not None
        assert '| ALARM:' in status.statement
