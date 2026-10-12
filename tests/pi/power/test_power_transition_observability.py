################################################################################
# File Name: test_power_transition_observability.py
# Purpose/Description: US-626 -- power_log must record power TRANSITIONS with an
#                      honest observing source, so a loss can never render as
#                      the healthy state and a quiet session is never ambiguous
#                      with an inert one.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-626) | Initial: the measured inversion (a loss row
#                              | stamped power_source='ac_power'), the honest
#                              | three-state observer, record-before-dispatch,
#                              | and the session-open marker that makes "no
#                              | transitions" provable rather than ambiguous.
# ================================================================================
################################################################################

"""US-626: power transitions must be recorded, and recorded honestly.

MEASURED PREMISE (read-only probe against the tree at 195158dc).  Driving
``PowerMonitor.checkPowerStatus`` through the shape the live
``_PowerSourceUiBridge`` produces -- boot read (AC), loss, restore -- writes
seven ``power_log`` rows, and the transition rows carry the PRE-transition
source::

    transition_to_battery  power_source=ac_power  on_ac_power=1   <-- a LOSS
    transition_to_ac       power_source=battery   on_ac_power=0   <-- a RESTORE

``_handleTransition`` runs before ``checkPowerStatus`` assigns
``self._currentPowerSource``, so every power-LOSS row is stamped "on AC
power".  That is not a missing row; it is a row that records the loss and
labels it the healthy state, so a query for ``on_ac_power = 0`` finds none of
the losses.  Same class as US-621's confidently-wrong drain report.

The second half is the observer.  ``PldSensor.isExternalPowerPresent()``
resolves an unreadable line to True (the deliberate non-bricking direction for
the SHUTDOWN path), and the bridge consumes exactly that bool -- so a dead or
contended GPIO6 reads as "AC present" forever and no transition is ever
observed.  ``PowerSourceProvider.isAvailable``'s own docstring already says a
display consumer must not take that at face value (US-502); ``power_log`` is
such a consumer and never got the treatment.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pi.obdii.orchestrator.lifecycle import _PowerSourceUiBridge
from pi.power.power import PowerMonitor
from pi.power.power_db import (
    ensurePowerLogObserverColumns,
    logPowerObservation,
)
from pi.power.types import (
    OBSERVER_STATE_LOST,
    OBSERVER_STATE_PRESENT,
    OBSERVER_STATE_UNKNOWN,
    POWER_LOG_EVENT_OBSERVER_SESSION_START,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
    POWER_OBSERVER_PLD_GPIO6,
    PowerObservation,
)

# ================================================================================
# Helpers
# ================================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS power_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    event_type TEXT NOT NULL,
    power_source TEXT NOT NULL,
    on_ac_power INTEGER NOT NULL DEFAULT 1,
    vcell REAL,
    data_quality TEXT,
    observed_by TEXT,
    observer_state TEXT
)
"""


class _FakeDatabase:
    """Minimal ObdDatabase stand-in whose ``connect()`` yields a real conn."""

    def __init__(self, path: str, *, withObserverColumns: bool = True):
        self.dbPath = path
        ddl = SCHEMA
        if not withObserverColumns:
            # Pre-US-626 shape, for the idempotent-migration tests.
            ddl = SCHEMA.replace(",\n    observed_by TEXT,\n    observer_state TEXT", "")
        with sqlite3.connect(path) as conn:
            conn.execute(ddl)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.dbPath)
        conn.row_factory = sqlite3.Row
        return conn


@pytest.fixture()
def db(tmp_path: Path) -> _FakeDatabase:
    return _FakeDatabase(str(tmp_path / "obd.db"))


def rowsOf(database: _FakeDatabase) -> list[dict]:
    with sqlite3.connect(database.dbPath) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM power_log ORDER BY id"
        )]


def eventsOf(database: _FakeDatabase, eventType: str) -> list[dict]:
    return [r for r in rowsOf(database) if r['event_type'] == eventType]


class _FakeProvider:
    """PowerSourceProvider-shaped double: readability and presence are
    INDEPENDENT, which is the whole point -- the real PldSensor collapses
    them and that collapse is the defect."""

    def __init__(self, *, available: bool = True, present: bool = True):
        self.available = available
        self.present = present
        self.raiseOnRead = False

    @property
    def isAvailable(self) -> bool:
        return self.available

    def isExternalPowerPresent(self) -> bool:
        if self.raiseOnRead:
            raise OSError("gpio line busy")
        # Mirrors PldSensor: unreadable resolves to power-present.
        return True if not self.available else self.present


# ================================================================================
# The measured inversion -- a loss row must not say "on AC power"
# ================================================================================


class TestTransitionRowRecordsThePostTransitionSource:
    """The defect the probe measured: _handleTransition fires BEFORE
    checkPowerStatus assigns _currentPowerSource, so the row describes the
    source being left rather than the one being entered."""

    def test_transitionToBattery_recordsBatteryNotAcPower(self, db):
        """
        Given: a monitor established on AC power
        When: power is lost
        Then: the transition_to_battery row says battery / on_ac_power=0
        """
        monitor = PowerMonitor(database=db)
        monitor.checkPowerStatus(True)   # boot read establishes AC
        monitor.checkPowerStatus(False)  # LOSS

        loss = eventsOf(db, POWER_LOG_EVENT_TRANSITION_TO_BATTERY)
        assert len(loss) == 1, "the loss must produce exactly one transition row"
        assert loss[0]['power_source'] == 'battery'
        assert loss[0]['on_ac_power'] == 0

    def test_aPowerLossIsFindableByTheObviousQuery(self, db):
        """
        Given: a power loss
        When: an analyst runs the query you would actually write --
              WHERE on_ac_power = 0
        Then: the loss is in the result

        This is the story's headline symptom: ten losses, and every row read
        ac_power, so the obvious query returned nothing.
        """
        monitor = PowerMonitor(database=db)
        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)

        with sqlite3.connect(db.dbPath) as conn:
            conn.row_factory = sqlite3.Row
            found = [dict(r) for r in conn.execute(
                "SELECT * FROM power_log WHERE on_ac_power = 0"
            )]
        assert any(
            r['event_type'] == POWER_LOG_EVENT_TRANSITION_TO_BATTERY
            for r in found
        ), "a power loss must be findable by WHERE on_ac_power = 0"

    def test_transitionToAc_recordsAcPowerNotBattery(self, db):
        """
        Given: a monitor that has fallen back to battery
        When: AC power is restored
        Then: the transition_to_ac row says ac_power / on_ac_power=1
        """
        monitor = PowerMonitor(database=db)
        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)
        monitor.checkPowerStatus(True)   # RESTORE

        restore = eventsOf(db, POWER_LOG_EVENT_TRANSITION_TO_AC)
        assert len(restore) == 1
        assert restore[0]['power_source'] == 'ac_power'
        assert restore[0]['on_ac_power'] == 1

    def test_everyRowAgreesWithItsOwnOnAcPowerFlag(self, db):
        """
        Given: a full AC -> battery -> AC cycle
        When: every written row is inspected
        Then: power_source and on_ac_power never contradict each other

        The pre-fix tree violated this on four of seven rows (both transition
        rows and both power_saving rows).
        """
        monitor = PowerMonitor(database=db)
        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)
        monitor.checkPowerStatus(True)

        for row in rowsOf(db):
            expected = 1 if row['power_source'] == 'ac_power' else 0
            assert row['on_ac_power'] == expected, (
                f"row {row['id']} ({row['event_type']}) says "
                f"power_source={row['power_source']} but "
                f"on_ac_power={row['on_ac_power']}"
            )

    def test_powerSavingRowsAlsoRecordThePostTransitionSource(self, db):
        """
        Given: a loss, which enables power saving
        When: the power_saving_enabled row is read
        Then: it records battery -- the state it was entered FOR

        power_saving_enabled is emitted from inside _handleTransition, so it
        inherited the same stale-source read.
        """
        monitor = PowerMonitor(database=db)
        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)

        saving = eventsOf(db, 'power_saving_enabled')
        assert len(saving) == 1
        assert saving[0]['power_source'] == 'battery'
        assert saving[0]['on_ac_power'] == 0


# ================================================================================
# The honest observer -- "I cannot see" must never render as "AC power"
# ================================================================================


class TestObservationIsHonestAboutReadability:

    def test_readableAndPresent_isPresent(self):
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=True, present=True),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        assert obs.state == OBSERVER_STATE_PRESENT
        assert obs.onAcPower is True

    def test_readableAndAbsent_isLost(self):
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=True, present=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        assert obs.state == OBSERVER_STATE_LOST
        assert obs.onAcPower is False

    def test_unreadableLine_isUnknown_neverPresent(self):
        """
        Given: a GPIO line that never opened (or is held by another process)
        When: the observation is taken
        Then: the state is 'unknown', NOT 'present'

        This is the ten-boot symptom's root: PldSensor resolves an unreadable
        line to power-present, so the bridge sees a permanent AC reading and
        never observes a transition at all.
        """
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=False, present=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        assert obs.state == OBSERVER_STATE_UNKNOWN
        assert obs.state != OBSERVER_STATE_PRESENT

    def test_unknownKeepsTheNonBrickingDirectionForTheSink(self):
        """
        Given: an unreadable line
        When: the observation is consumed as a bool by the status sink
        Then: it still resolves to on-AC

        The honest state is for the RECORD.  Changing the bool would change
        the shutdown-adjacent safe direction, which is a different failure
        domain and explicitly not this story's business.
        """
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        assert obs.onAcPower is True
        assert obs.state == OBSERVER_STATE_UNKNOWN

    def test_readThatRaises_isUnknown(self):
        provider = _FakeProvider(available=True)
        provider.raiseOnRead = True
        obs = PowerObservation.fromProvider(
            provider, observedBy=POWER_OBSERVER_PLD_GPIO6
        )
        assert obs.state == OBSERVER_STATE_UNKNOWN

    def test_providerWithoutIsAvailable_isTreatedAsReadable(self):
        """
        Given: a provider implementing only isExternalPowerPresent() -- the
               minimal shape _PowerSourceUiBridge documents
        When: observations are taken
        Then: they are present/lost, NOT permanently unknown

        Caught by the EXISTING SS-T4 regression, not by my reasoning: an
        earlier draft defaulted a non-reporting provider to blind, which made
        every reading UNKNOWN and suppressed every transition record -- the
        exact opposite of AC-5.  Defaulting to blind is only correct at the
        hardware boundary (PowerSourceProvider over a PldSensor), where the
        choice governs a SHUTDOWN decision rather than whether anything is
        recorded at all.
        """
        class _MinimalProvider:
            def __init__(self, present: bool):
                self._present = present

            def isExternalPowerPresent(self) -> bool:
                return self._present

        assert PowerObservation.fromProvider(
            _MinimalProvider(True), observedBy=POWER_OBSERVER_PLD_GPIO6
        ).state == OBSERVER_STATE_PRESENT
        assert PowerObservation.fromProvider(
            _MinimalProvider(False), observedBy=POWER_OBSERVER_PLD_GPIO6
        ).state == OBSERVER_STATE_LOST

    def test_observationNamesItsObserver(self):
        obs = PowerObservation.fromProvider(
            _FakeProvider(), observedBy=POWER_OBSERVER_PLD_GPIO6
        )
        assert obs.observedBy == POWER_OBSERVER_PLD_GPIO6


class TestObservationRowsCarryTheObserver:

    def test_rowRecordsObserverAndState(self, db):
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=True, present=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        logPowerObservation(db, POWER_LOG_EVENT_TRANSITION_TO_BATTERY, obs)

        row = rowsOf(db)[0]
        assert row['observed_by'] == POWER_OBSERVER_PLD_GPIO6
        assert row['observer_state'] == OBSERVER_STATE_LOST
        assert row['power_source'] == 'battery'
        assert row['on_ac_power'] == 0

    def test_unknownObservationNeverWritesAConfidentAcRow(self, db):
        """
        Given: an unreadable observer
        When: a session-start row is written
        Then: the row's observer_state is 'unknown'

        A reader must be able to tell "the line said AC" from "the line said
        nothing and we defaulted to AC".
        """
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        logPowerObservation(db, POWER_LOG_EVENT_OBSERVER_SESSION_START, obs)

        row = rowsOf(db)[0]
        assert row['observer_state'] == OBSERVER_STATE_UNKNOWN

    def test_writerNeverRaisesOnAMissingDatabase(self):
        obs = PowerObservation.fromProvider(
            _FakeProvider(), observedBy=POWER_OBSERVER_PLD_GPIO6
        )
        logPowerObservation(None, POWER_LOG_EVENT_OBSERVER_SESSION_START, obs)


# ================================================================================
# Impossible by construction -- the record must not depend on the sink
# ================================================================================


class TestTransitionRecordIsIndependentOfTheSink:

    def test_transitionIsRecordedEvenWhenTheSinkRaises(self, db):
        """
        Given: a bridge whose sink raises (the bridge swallows sink faults by
               design -- a status surface must never take anything down)
        When: power is lost
        Then: the loss is STILL recorded

        Pre-fix, the swallowed sink exception took the only record with it:
        the transition existed solely as a log line.  AC-5 -- a power loss
        with no corresponding row must be impossible by construction.
        """
        provider = _FakeProvider(available=True, present=True)
        recorded: list[PowerObservation] = []

        def sink(_onAc: bool) -> None:
            raise RuntimeError("sink is down")

        bridge = _PowerSourceUiBridge(
            provider=provider,
            sink=sink,
            pollSec=0.01,
            recorder=recorded.append,
        )
        bridge.pollOnce()          # first read -- establishes present
        provider.present = False
        bridge.pollOnce()          # LOSS

        assert any(o.state == OBSERVER_STATE_LOST for o in recorded), (
            "the loss must be recorded even though the sink raised"
        )

    def test_recorderFaultDoesNotSuppressTheSink(self, db):
        """
        Given: a recorder that raises
        When: a transition occurs
        Then: the sink still runs

        US-621's composePrePowerOffHooks lesson: two independent consumers of
        one event must be isolated, or one bug silently disables the other.
        """
        provider = _FakeProvider(available=True, present=True)
        sunk: list[bool] = []

        def recorder(_obs: PowerObservation) -> None:
            raise RuntimeError("db is down")

        bridge = _PowerSourceUiBridge(
            provider=provider,
            sink=sunk.append,
            pollSec=0.01,
            recorder=recorder,
        )
        bridge.pollOnce()
        provider.present = False
        bridge.pollOnce()

        assert sunk == [True, False]

    def test_bridgeWithoutARecorderStillWorks(self):
        """Back-compat: recorder is optional; existing construction sites and
        the retired-wiring tests must keep passing."""
        provider = _FakeProvider(available=True, present=True)
        sunk: list[bool] = []
        bridge = _PowerSourceUiBridge(
            provider=provider, sink=sunk.append, pollSec=0.01
        )
        assert bridge.pollOnce() is True
        assert sunk == [True]

    def test_everyStateChangeIsRecorded_lossAndRestore(self):
        """VC-1: an AC -> battery -> AC cycle yields a loss row AND a restore
        row, each naming its observing source."""
        provider = _FakeProvider(available=True, present=True)
        recorded: list[PowerObservation] = []
        bridge = _PowerSourceUiBridge(
            provider=provider,
            sink=lambda _x: None,
            pollSec=0.01,
            recorder=recorded.append,
        )
        bridge.pollOnce()
        provider.present = False
        bridge.pollOnce()          # LOSS
        provider.present = True
        bridge.pollOnce()          # RESTORE

        states = [o.state for o in recorded]
        assert states == [
            OBSERVER_STATE_PRESENT, OBSERVER_STATE_LOST, OBSERVER_STATE_PRESENT
        ]
        assert all(o.observedBy for o in recorded), "each row names an observer"

    def test_anObserverGoingBlindWhileOnAcIsRecorded(self):
        """
        Given: a healthy AC session whose GPIO line then becomes unreadable
        When: the bridge polls
        Then: the change to 'unknown' is recorded

        THE CASE THAT MATTERS, and the one a bool cannot see.  present and
        unknown BOTH resolve to onAcPower=True, so change-detection on the
        bool records nothing here -- the log simply goes on implying AC power
        from an instrument that has gone blind.  That is the ten-boot
        symptom's shape: not a wrong row, but a healthy-looking silence.

        Caught by mutation M5, which flipped the comparison back to the bool
        and survived the rest of this suite: the sibling dead-line test
        happens to flip onAcPower too, so it could not distinguish.
        """
        provider = _FakeProvider(available=True, present=True)
        recorded: list[PowerObservation] = []
        bridge = _PowerSourceUiBridge(
            provider=provider,
            sink=lambda _x: None,
            pollSec=0.01,
            recorder=recorded.append,
        )
        bridge.pollOnce()               # present, onAcPower=True
        provider.available = False      # line goes blind; onAcPower STAYS True
        bridge.pollOnce()

        assert [o.state for o in recorded] == [
            OBSERVER_STATE_PRESENT, OBSERVER_STATE_UNKNOWN
        ], "an observer going blind on AC must be recorded, not pass silently"
        assert [o.onAcPower for o in recorded] == [True, True], (
            "premise: the bool is unchanged across this transition, which is "
            "exactly why it cannot be the change-detection signal"
        )

    def test_aDeadLineIsRecordedAsUnknownRatherThanSilence(self):
        """
        Given: a line that goes unreadable mid-session while on battery
        When: the bridge polls
        Then: the change is recorded as 'unknown'

        Pre-fix this rendered as a RESTORE that never happened, because
        unreadable collapses to power-present.
        """
        provider = _FakeProvider(available=True, present=False)
        recorded: list[PowerObservation] = []
        bridge = _PowerSourceUiBridge(
            provider=provider,
            sink=lambda _x: None,
            pollSec=0.01,
            recorder=recorded.append,
        )
        bridge.pollOnce()               # lost
        provider.available = False      # line dies
        bridge.pollOnce()

        assert recorded[-1].state == OBSERVER_STATE_UNKNOWN, (
            "a line that went blind must not be recorded as a power restore"
        )


# ================================================================================
# VC-2 -- a quiet session must be evident, not ambiguous with an inert one
# ================================================================================


class TestQuietSessionIsProvable:

    def test_bridgeStartWritesASessionOpenRow(self, db):
        """
        Given: a bridge that starts and observes no transitions
        When: power_log is reviewed
        Then: a session-open row proves the observer was watching

        Without it, "no transitions occurred" and "the observer never ran"
        are the same empty result -- which is exactly how ten losses went
        unnoticed.
        """
        provider = _FakeProvider(available=True, present=True)
        bridge = _PowerSourceUiBridge(
            provider=provider,
            sink=lambda _x: None,
            pollSec=0.01,
            recorder=lambda obs: logPowerObservation(
                db, POWER_LOG_EVENT_OBSERVER_SESSION_START, obs
            ),
        )
        bridge.pollOnce()

        opens = eventsOf(db, POWER_LOG_EVENT_OBSERVER_SESSION_START)
        assert len(opens) == 1
        assert opens[0]['observed_by'] == POWER_OBSERVER_PLD_GPIO6
        assert opens[0]['observer_state'] == OBSERVER_STATE_PRESENT

    def test_sessionOpenRowDistinguishesWatchingFromBlind(self, db):
        """A session opened by a BLIND observer is recorded as such, so a
        quiet log is never mistaken for a healthy one."""
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        logPowerObservation(db, POWER_LOG_EVENT_OBSERVER_SESSION_START, obs)
        row = eventsOf(db, POWER_LOG_EVENT_OBSERVER_SESSION_START)[0]
        assert row['observer_state'] == OBSERVER_STATE_UNKNOWN, (
            "a session opened blind must say so"
        )


# ================================================================================
# Migration + wire contract
# ================================================================================


class TestObserverColumnMigration:

    def test_addsColumnsToAPreUs626Table(self, tmp_path):
        database = _FakeDatabase(
            str(tmp_path / "legacy.db"), withObserverColumns=False
        )
        with sqlite3.connect(database.dbPath) as conn:
            assert ensurePowerLogObserverColumns(conn) is True
            cols = {r[1] for r in conn.execute("PRAGMA table_info(power_log)")}
        assert {'observed_by', 'observer_state'} <= cols

    def test_isIdempotent(self, tmp_path):
        database = _FakeDatabase(
            str(tmp_path / "legacy.db"), withObserverColumns=False
        )
        with sqlite3.connect(database.dbPath) as conn:
            ensurePowerLogObserverColumns(conn)
            assert ensurePowerLogObserverColumns(conn) is False

    def test_returnsFalseWhenTableAbsent(self, tmp_path):
        path = str(tmp_path / "empty.db")
        with sqlite3.connect(path) as conn:
            assert ensurePowerLogObserverColumns(conn) is False

    def test_legacyRowsSurvive(self, tmp_path):
        database = _FakeDatabase(
            str(tmp_path / "legacy.db"), withObserverColumns=False
        )
        with sqlite3.connect(database.dbPath) as conn:
            conn.execute(
                "INSERT INTO power_log (timestamp, event_type, power_source, "
                "on_ac_power) VALUES ('2026-08-01T00:00:00Z','ac_power',"
                "'ac_power',1)"
            )
            conn.commit()
            ensurePowerLogObserverColumns(conn)
            row = conn.execute(
                "SELECT observed_by, observer_state FROM power_log"
            ).fetchone()
        assert row == (None, None)


class TestObserverColumnsArePiLocal:

    def test_strippedFromTheSyncWire(self):
        """The server has no observed_by / observer_state column; its bulk
        insert errors on an unmapped key.  Mirrors the US-419 data_quality
        precedent rather than growing a server migration."""
        from pi.data.sync_log import _WIRE_STRIPPED_COLUMNS
        assert 'observed_by' in _WIRE_STRIPPED_COLUMNS
        assert 'observer_state' in _WIRE_STRIPPED_COLUMNS


class TestWiringGuards:
    """Mutating the WIRING must fail, not just the logic (US-625's M13
    lesson: a hand-built fixture hides a dead call site)."""

    def test_databaseInitializeRunsTheObserverMigration(self):
        import inspect

        from pi.obdii import database as dbmod
        source = inspect.getsource(dbmod)
        # The CALL, not the symbol: the import line also carries the name, so
        # grepping the bare symbol would stay green with the call site deleted.
        assert 'ensurePowerLogObserverColumns(conn)' in source, (
            "the migration must be CALLED in ObdDatabase.initialize, or "
            "existing Pi databases never gain the columns"
        )

    def test_schemaCarriesTheObserverColumns(self):
        """EXECUTE the DDL and read the column names back, rather than
        substring-matching the SQL text.  Mutation M12 renamed the column to
        ``observer_state_renamed`` and a substring assertion stayed green --
        a fresh Pi database would then be missing the column the writer
        INSERTs into.  Ask the schema what it built, not what it says."""
        from pi.obdii.database_schema import SCHEMA_POWER_LOG

        with sqlite3.connect(":memory:") as conn:
            conn.execute(SCHEMA_POWER_LOG)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(power_log)")}
        assert 'observed_by' in cols
        assert 'observer_state' in cols

    def test_aFreshSchemaAcceptsTheWriterInsert(self):
        """The end-to-end pairing: a database built from SCHEMA_POWER_LOG must
        accept a row from the US-626 writer.  Any drift between the DDL and
        the INSERT column list surfaces here as an OperationalError instead of
        as a silently swallowed write on the car."""
        from pi.obdii.database_schema import SCHEMA_POWER_LOG

        class _Db:
            dbPath = ":memory:"

            def __init__(self):
                self._conn = sqlite3.connect(":memory:")
                self._conn.execute(SCHEMA_POWER_LOG)

            def connect(self):
                class _Ctx:
                    def __init__(self, conn):
                        self._conn = conn

                    def __enter__(self):
                        return self._conn

                    def __exit__(self, *a):
                        return False
                return _Ctx(self._conn)

        database = _Db()
        obs = PowerObservation.fromProvider(
            _FakeProvider(available=True, present=False),
            observedBy=POWER_OBSERVER_PLD_GPIO6,
        )
        logPowerObservation(
            database, POWER_LOG_EVENT_TRANSITION_TO_BATTERY, obs
        )
        row = database._conn.execute(
            "SELECT event_type, observed_by, observer_state FROM power_log"
        ).fetchone()
        assert row == (
            POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
            POWER_OBSERVER_PLD_GPIO6,
            OBSERVER_STATE_LOST,
        )

    def test_bridgeIsConstructedWithARecorder(self):
        """The whole fix ships inert if lifecycle builds the bridge without a
        recorder -- exactly the US-625 M13 shape."""
        import inspect

        from pi.obdii.orchestrator import lifecycle
        source = inspect.getsource(
            lifecycle.LifecycleMixin._subscribePowerMonitorToPowerSourceProvider
        )
        assert 'recorder=' in source, (
            "the live bridge must be given a recorder or no transition is "
            "ever persisted"
        )
