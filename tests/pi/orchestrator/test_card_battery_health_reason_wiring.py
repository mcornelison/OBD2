################################################################################
# File Name: test_card_battery_health_reason_wiring.py
# Purpose/Description: US-632 -- the battery-health unknown-REASON reaches the
#   journal from the orchestrator's card-emit path.
#
#   The reason cannot reach the `battery-health` state file from this bench:
#   that payload is assembled in `src/pi/splash/battery_health_emitter.py`,
#   whose signature is outside the declared surface (BL-us632).  Until that
#   lands, the journal is where the fact "can be seen" -- which is US-632's own
#   conditionalOutcome: "If the producer is scheduled but failing silently,
#   that silent failure IS the defect -- record it where it can be seen."
#
#   These tests pin BOTH halves of that, and the second half has teeth:
#     1. the reason is recorded, and names the actual cause; and
#     2. it is recorded ON CHANGE ONLY.  The producer recomputes on every emit
#        tick, so an unconditional log line would turn it into a continuous
#        journal writer -- the exact cost US-646 is open about and the exact
#        condition that makes US-644's journal probe time out.
#
#   NOTE ON THE FIXTURE: `_FakeDatabase` here inserts `end_vcell_v`, which the
#   older tests/pi/orchestrator/test_card_battery_health_verdict_wiring.py does
#   NOT.  That omission makes every row in the older file fail Spool's US-527
#   depth gate, which is why those 7 tests are red at baseline.  Recorded in
#   offices/pm/tech_debt/ rather than fixed here -- see TD note in that file.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-632 reason wiring + log-on-change.
# ================================================================================
################################################################################

"""US-632: the unknown-reason is recorded where it can be seen, on change."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG
from pi.power.battery_health_verdict import (
    REASON_HEALTH_DATA_STALE,
    REASON_NO_DATABASE,
    REASON_NO_QUALIFYING_DRAINS,
    REASON_TOO_FEW_DRAINS,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)
_LOGGER_NAME = "pi.obdii.orchestrator"


def _iso(daysAgo: float) -> str:
    return (_NOW - timedelta(days=daysAgo)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _FakeDatabase:
    """An in-memory battery_health_log that writes the DEPTH-gate column.

    ``end_vcell_v`` 3.45 V is the top of the MEASURED 3.42-3.45 V cutoff range
    (Spool Session-27), i.e. a genuine run-to-shutdown that QUALIFIES.
    """

    def __init__(self, drains=()):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        for daysAgo, runtimeSeconds in drains:
            self._conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, end_timestamp, runtime_seconds, load_class, "
                " end_vcell_v) VALUES (?, ?, ?, ?, ?)",
                (
                    _iso(daysAgo), _iso(daysAgo - 0.01),
                    runtimeSeconds, "production", 3.45,
                ),
            )
        self._conn.commit()

    @contextmanager
    def connect(self):
        yield self._conn


class _FakeOrch(CardStateEmitterMixin):
    """Minimal composing object exposing the attrs the mixin reads."""

    def __init__(self, config, *, hardwareManager=None, database=None):
        self._config = config
        self._connection = None
        self._driveDetector = None
        self._powerSourceProvider = None
        self._hardwareManager = hardwareManager
        if database is not None:
            self._database = database
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _config(tmp_path):
    return {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitIntervalSeconds": 0.0},
        }
    }


def _liveUps():
    return SimpleNamespace(
        upsMonitor=SimpleNamespace(
            getBatteryVoltage=lambda: 4.05,
            getBatteryPercentage=lambda: 82,
            getChargeRatePercentPerHour=lambda: -3.2,
        )
    )


def _qualifying(*daysAgo, runtimeSeconds=727):
    return [(d, runtimeSeconds) for d in daysAgo]


def _readState(tmp_path):
    return json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )


def _reasonWarnings(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "battery-health verdict is unknown" in r.getMessage()
    ]


# ---------------------------------------------------------------------------
# The reason is RECORDED, and it names the actual cause.
# ---------------------------------------------------------------------------


def test_unknownVerdict_recordsItsReason(tmp_path, caplog):
    """Given: a drain log with too few qualifying drains to median.
    When: the card state is emitted.
    Then: a WARNING names `too_few_drains` -- not merely "unknown".
    """
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(1, 2)),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

    messages = _reasonWarnings(caplog)
    assert len(messages) == 1
    assert REASON_TOO_FEW_DRAINS in messages[0]


def test_theLivePiCase_recordsStale_notNothingEverChecked(tmp_path, caplog):
    """Given: the live Pi's shape -- real qualifying drains, all aged out past
        the 90-day staleness horizon (measured 2026-05-16, read 2026-08-31).
    When: the card state is emitted.
    Then: the recorded reason is `health_data_stale`.

    This is the punch-list 4.2 distinction made observable: the pack WAS
    measured and the measurement aged out, which is a different fact from
    "nothing has ever checked" -- and a very different fact from the reported
    diagnosis, "the producer stopped running".
    """
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(107, 109, 111)),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

    messages = _reasonWarnings(caplog)
    assert len(messages) == 1
    assert REASON_HEALTH_DATA_STALE in messages[0]
    assert REASON_NO_QUALIFYING_DRAINS not in messages[0]
    # And the card still reports WHEN -- the date is the signal, not noise.
    assert _readState(tmp_path)["lastHealthCheckTs"] == _iso(107)


def test_noDatabase_recordsNoDatabase_notAnEmptyLog(tmp_path, caplog):
    """Bench / pre-init is an ABSENT instrument, not an empty measurement."""
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps())
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

    messages = _reasonWarnings(caplog)
    assert len(messages) == 1
    assert REASON_NO_DATABASE in messages[0]


def test_emptyLog_recordsNoQualifyingDrains(tmp_path, caplog):
    orch = _FakeOrch(
        _config(tmp_path), hardwareManager=_liveUps(), database=_FakeDatabase()
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

    assert REASON_NO_QUALIFYING_DRAINS in _reasonWarnings(caplog)[0]


# ---------------------------------------------------------------------------
# The producer DID run -- the log line has to say so, because the punch list's
# reasonable-but-wrong reading was that it had not.
# ---------------------------------------------------------------------------


def test_theRecordedLineStatesThatTheProducerRan(tmp_path, caplog):
    """The whole misdiagnosis in punch-list 4.2 was "the producer stopped
    running". It did not -- it recomputes every emit tick. The line that
    reports the unknown must say so, or the next reader draws the same wrong
    conclusion from the same evidence."""
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps())
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

    assert "DID run" in _reasonWarnings(caplog)[0]


# ---------------------------------------------------------------------------
# ON CHANGE ONLY -- the journal-volume guard.
# ---------------------------------------------------------------------------


def test_steadyUnknown_isRecordedOnceNotOncePerTick(tmp_path, caplog):
    """Given: an unchanging unknown cause.
    When: the card state is emitted five times.
    Then: exactly ONE line is recorded.

    A steady state is not news. Logging per tick would make this producer a
    continuous journal writer -- US-646's open complaint about drain-forensics,
    and the condition that makes US-644's journal probe time out.
    """
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(1, 2)),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        for _ in range(5):
            orch._maybeEmitCardStates()

    assert len(_reasonWarnings(caplog)) == 1


def test_aCHANGEOfCause_isRecordedAgain(tmp_path, caplog):
    """Given: the cause changes between ticks.
    When: both are emitted.
    Then: BOTH are recorded -- deduplication must not swallow a transition.

    This is the half that makes the previous test safe: without it, "log once"
    could be satisfied by logging once EVER, which would hide the moment the
    producer's situation actually changed.
    """
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(1, 2)),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()
        # The log ages out from under the producer.
        orch._database = _FakeDatabase(_qualifying(107, 109, 111))
        orch._maybeEmitCardStates()

    messages = _reasonWarnings(caplog)
    assert len(messages) == 2
    assert REASON_TOO_FEW_DRAINS in messages[0]
    assert REASON_HEALTH_DATA_STALE in messages[1]


def test_resolvedVerdict_recordsNoUnknownWarning(tmp_path, caplog):
    """Given: three recent qualifying drains at the baseline runtime.
    When: the card state is emitted.
    Then: the verdict resolves and NO unknown-reason warning is recorded.
    """
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(1, 2, 3)),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

    assert _readState(tmp_path)["health"] == "good"
    assert _reasonWarnings(caplog) == []


def test_recoveryFromUnknownToResolved_isRecorded(tmp_path, caplog):
    """A producer that starts unknown and later resolves must say so, or the
    journal's last word on the subject stays a warning that is no longer true."""
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(1, 2)),
    )
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()
        orch._database = _FakeDatabase(_qualifying(1, 2, 3))
        orch._maybeEmitCardStates()

    resolved = [
        r.getMessage() for r in caplog.records
        if "verdict resolved" in r.getMessage()
    ]
    assert len(resolved) == 1


# ---------------------------------------------------------------------------
# The REFUSAL, pinned at the wiring level too.
# ---------------------------------------------------------------------------


def test_staleState_neverAdvancesLastHealthCheckTsToNow(tmp_path):
    """US-632 asks for "lastHealthCheckTs is current". It must NOT be met by
    stamping today's date over a measurement that is 107 days old -- that
    fabricates a health check and defeats the F-9 stale-green guard. The
    payload's `ts` is what carries "this was computed just now"."""
    orch = _FakeOrch(
        _config(tmp_path),
        hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(107, 109, 111)),
    )
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    state = _readState(tmp_path)

    assert state["lastHealthCheckTs"] == _iso(107)
    assert state["lastHealthCheckTs"] != state["ts"]
    # `ts` IS current -- the producer ran on this tick. That is the evidence
    # that "the producer stopped running" was a misreading of a stale
    # MEASUREMENT date, not an observation of a dead process.
    assert state["ts"].startswith(_NOW.strftime("%Y-%m-%d"))
