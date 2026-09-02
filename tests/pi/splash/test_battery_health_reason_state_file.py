################################################################################
# File Name: test_battery_health_reason_state_file.py
# Purpose/Description: US-632 (second half) -- the battery-health unknown-REASON
#   reaches the `battery-health` STATE FILE, not just the journal.
#
#   The first half of US-632 gave the verdict producer a typed reason vocabulary
#   (no_database / log_unreadable / no_qualifying_drains / too_few_drains /
#   health_data_stale / clock_unreadable) and recorded it to the journal, because
#   `buildBatteryHealthState` lives in src/pi/splash/ and was outside the bench
#   surface at the time (BL-us632, since granted).  A journal line is not the
#   SSOT.  This file pins the fact arriving where the story says it must: the
#   payload the card polls.
#
#   THE CLAIM THE STORY ACTUALLY MAKES, and every test here is aimed at it:
#   "we checked, just now, and cannot say" must be DISTINGUISHABLE in the state
#   file from "nothing has checked since May".  Those are different facts and
#   before this change they were the same three characters, `unknown`.
#
#   SHAPE follows the US-628 `power.reasons` precedent in the sibling emitter
#   (system_status_emitter.py:217) verbatim, which in turn follows the
#   imu_state_bridge `reasons` map: a FIELD-KEYED map that is ALWAYS PRESENT and
#   EMPTY when the fact resolved.  A sometimes-missing key is the shape a
#   consumer falls quietly through, and one vocabulary is cheaper to reason
#   about than two.
#
#   NOT IN SCOPE, deliberately: the CARD.  US-632's acceptance says "SCOPE IS THE
#   PRODUCER, not the card", and carousel.js has no health-reason renderer.  Every
#   assertion here stops at the state file.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Ralph (Rex)  | Initial -- US-632 reason reaches the state file.
# ================================================================================
################################################################################

"""US-632: the unknown-verdict reason is published in the battery-health SSOT."""

import json
import re
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
    UNKNOWN_REASONS,
    VERDICT_GOOD,
    VERDICT_UNKNOWN,
)
from pi.splash.battery_health_emitter import (
    buildBatteryHealthState,
    makeBatteryHealthEmitter,
)

_NOW_ISO = "2026-09-01T12:00:00Z"
_LAST_CHECK = "2026-05-16T01:54:27Z"
_NOW = datetime.now(UTC).replace(tzinfo=None)

# The machine-reason idiom: snake_case, lowercase, no spaces.  US-628 found TWO
# reason idioms in this tree that are NOT interchangeable -- the US-429
# `source.*` block carries SPACED HUMAN TEXT because a card renders it verbatim,
# while a `reasons` map carries MACHINE words a consumer maps to display text.
# Pinned as a regex so the two cannot quietly drift into one.
_MACHINE_REASON = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Fixtures -- the pure builder's inputs.
# ---------------------------------------------------------------------------

# The live Pi's own shape: a real gauge reading beside a verdict that cannot be
# formed.  Atlas punch-list 4.1 (gauge real and live) and 4.2 (verdict unknown)
# read THE SAME FILE, so the two halves have to be able to disagree here.
_UNRESOLVED_KW = dict(
    vcellV=4.164,
    soc=96,
    socCalibrated=False,
    crate=1.8,
    charging=True,
    draining=False,
    restedVcellV=None,
    weakEvents30d=0,
    restedHistory=[],
    health=VERDICT_UNKNOWN,
    fullChargeReached=False,
    runtimeToCutoffS=None,
    ambientTempC=None,
    lastHealthCheckTs=_LAST_CHECK,
    ladder=None,
)


def _resolvedKw():
    kw = dict(_UNRESOLVED_KW)
    kw["health"] = VERDICT_GOOD
    kw["runtimeToCutoffS"] = 714
    return kw


# ---------------------------------------------------------------------------
# Fixtures -- the real orchestrator chain (producer -> emitter -> state file).
# ---------------------------------------------------------------------------


def _iso(daysAgo: float) -> str:
    return (_NOW - timedelta(days=daysAgo)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _FakeDatabase:
    """An in-memory battery_health_log that writes the DEPTH-gate column.

    ``end_vcell_v`` 3.45 V is the top of the MEASURED 3.42-3.45 V cutoff range
    (Spool Session-27), i.e. a genuine run-to-shutdown that QUALIFIES.  The
    older tests/pi/orchestrator/test_card_battery_health_verdict_wiring.py omits
    this column, which is why its 7 tests are red at baseline (TD-us632).
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
            getBatteryVoltage=lambda: 4.164,
            getBatteryPercentage=lambda: 96,
            getChargeRatePercentPerHour=lambda: -3.2,
        )
    )


def _qualifying(*daysAgo, runtimeSeconds=727):
    return [(d, runtimeSeconds) for d in daysAgo]


def _readState(tmp_path):
    return json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )


def _emitOnce(tmp_path, *, hardwareManager=None, database=None):
    orch = _FakeOrch(
        _config(tmp_path), hardwareManager=hardwareManager, database=database
    )
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    return _readState(tmp_path)


# ---------------------------------------------------------------------------
# The pure builder -- the reason reaches the payload.
# ---------------------------------------------------------------------------


def test_unknownVerdict_publishesItsReasonKeyedByField():
    """Given: an `unknown` verdict with the typed reason the producer formed.
    When: the payload is assembled.
    Then: `reasons.health` names the cause.

    Keyed by FIELD NAME, following power.reasons, so a second unresolvable
    battery fact can be added later without inventing a second container.
    """
    state = buildBatteryHealthState(
        nowIso=_NOW_ISO, healthReason=REASON_HEALTH_DATA_STALE, **_UNRESOLVED_KW
    )
    assert state["reasons"] == {"health": REASON_HEALTH_DATA_STALE}


def test_theReasonDoesNotReplaceTheVerdict_bothFactsSurvive():
    """The reason EXPLAINS the verdict, it does not stand in for it.

    A consumer reading `health` must still find the four-value enum it has
    always read; a producer that wrote the reason into `health` would break
    every existing renderer while looking more informative.
    """
    state = buildBatteryHealthState(
        nowIso=_NOW_ISO, healthReason=REASON_TOO_FEW_DRAINS, **_UNRESOLVED_KW
    )
    assert state["health"] == VERDICT_UNKNOWN
    assert state["reasons"]["health"] == REASON_TOO_FEW_DRAINS


def test_resolvedVerdict_publishesAnEmptyMap_neverAContradiction():
    """A reason standing beside a RESOLVED verdict is a second, contradictory
    account of the same fact -- the exact rule US-628 wrote for power.reasons.

    A caller that forgets to clear its stale reason must not be able to publish
    `good` alongside "we could not tell": the emitter drops it.
    """
    state = buildBatteryHealthState(
        nowIso=_NOW_ISO, healthReason=REASON_HEALTH_DATA_STALE, **_resolvedKw()
    )
    assert state["health"] == VERDICT_GOOD
    assert state["reasons"] == {}


def test_theReasonsKeyIsAlwaysPresent_neverSometimesMissing():
    """Present on BOTH sides -- resolved and unresolved.

    A sometimes-missing key is the shape a consumer falls quietly through: the
    absent case and the empty case become indistinguishable at the reader, which
    is the same defect class this story exists to close one level up.
    """
    resolved = buildBatteryHealthState(nowIso=_NOW_ISO, **_resolvedKw())
    unresolved = buildBatteryHealthState(
        nowIso=_NOW_ISO, healthReason=REASON_NO_DATABASE, **_UNRESOLVED_KW
    )
    assert "reasons" in resolved
    assert "reasons" in unresolved
    assert resolved["reasons"] == {}


def test_noReasonOffered_publishesAnEmptyMap_notANullEntryAndNotAGuess():
    """`unknown` with NO reason offered is an honest gap in the producer, not a
    licence to invent one -- and `{"health": null}` is a third shape consumers
    would each handle differently.  Empty map, one shape."""
    state = buildBatteryHealthState(
        nowIso=_NOW_ISO, healthReason=None, **_UNRESOLVED_KW
    )
    assert state["reasons"] == {}


def test_theParameterDefaults_soAnUnwiredCallerNeverFabricates():
    """The kwarg is optional (backward compatible, like upsAvailable), and its
    default is silence -- an old caller that has not been taught the vocabulary
    publishes no reason rather than a plausible-looking one."""
    state = buildBatteryHealthState(nowIso=_NOW_ISO, **_UNRESOLVED_KW)
    assert state["reasons"] == {}


def test_everyReasonInTheVocabularyIsTransportedVerbatim():
    """Closure guard: all six producer words survive the emitter unchanged.

    The emitter is a TRANSPORT, not a translator (the `lastDrive` precedent in
    the sibling emitter: "never reformats or re-derives the producer's fact").
    A member added to UNKNOWN_REASONS and not handled here fails HERE.
    """
    assert len(UNKNOWN_REASONS) == 6
    for reason in UNKNOWN_REASONS:
        state = buildBatteryHealthState(
            nowIso=_NOW_ISO, healthReason=reason, **_UNRESOLVED_KW
        )
        assert state["reasons"] == {"health": reason}


def test_theReasonsAreMachineWords_notTheSpacedHumanTextOfTheSourceBlock():
    """US-628 found TWO reason idioms in this tree, one field apart, and they
    are NOT interchangeable.  `source.ups.reason` is SPACED HUMAN TEXT because
    the card renders it verbatim; a `reasons` map carries MACHINE snake_case a
    consumer maps to display text (carousel.js IMU_REASON_TEXT).

    Pinned together, in one test, so nobody 'harmonises' them: they are two
    different jobs that happen to share a word.
    """
    state = buildBatteryHealthState(
        nowIso=_NOW_ISO,
        healthReason=REASON_NO_QUALIFYING_DRAINS,
        upsAvailable=False,
        upsUnavailableReason="gauge unreadable",
        **_UNRESOLVED_KW,
    )
    assert _MACHINE_REASON.match(state["reasons"]["health"])
    for reason in UNKNOWN_REASONS:
        assert _MACHINE_REASON.match(reason)
    # ...and the source block's reason is deliberately NOT of that shape.
    assert not _MACHINE_REASON.match(state["source"]["ups"]["reason"])


def test_aDeadGaugeDoesNotEraseTheHealthReason():
    """THE LOAD-BEARING INDEPENDENCE.  The verdict's source is the drain LOG;
    the gauge is the MAX17048.  The unavailable-UPS branch blanks every
    ups-owned numeric -- and must not reach the health block on its way past.

    A dead gauge erasing the health reason would be the story's own defect
    restored by a different route: the card would read `unknown` with nothing
    to say, on a Pi whose reason we had computed correctly one line earlier.
    """
    state = buildBatteryHealthState(
        nowIso=_NOW_ISO,
        healthReason=REASON_HEALTH_DATA_STALE,
        upsAvailable=False,
        **_UNRESOLVED_KW,
    )
    assert state["vcellV"] is None  # the gauge really is blanked...
    assert state["soc"] is None
    assert state["health"] == VERDICT_UNKNOWN
    assert state["reasons"] == {"health": REASON_HEALTH_DATA_STALE}
    assert state["lastHealthCheckTs"] == _LAST_CHECK  # ...and the history stands


def test_theA3SchemaGainsExactlyOneKey_nothingRenamedOrDropped():
    """The A-3 schema (spec §7) is a published contract.  This change ADDS one
    key; it must move nothing else.  Asserted as a key-set diff rather than a
    fresh exact-dict so a future field cannot be silently swapped for another.
    """
    state = buildBatteryHealthState(nowIso=_NOW_ISO, **_resolvedKw())
    assert set(state) == {
        "vcellV", "soc", "socCalibrated", "crate", "charging", "draining",
        "restedVcellV", "weakEvents30d", "restedHistory", "health",
        "fullChargeReached", "runtimeToCutoffS", "ambientTempC",
        "lastHealthCheckTs", "ladder", "source", "reasons", "ts",
    }


# ---------------------------------------------------------------------------
# The emit callable -- the reason survives the write to disk.
# ---------------------------------------------------------------------------


def test_theEmitCallableCarriesTheReasonIntoTheFile(tmp_path):
    """A builder that accepts a reason and a writer that drops it are two
    correct halves with no join -- the shape this whole sprint keeps finding.
    Pinned through the REAL atomic writer onto a REAL file."""
    statesDir = str(tmp_path / "states")
    emit = makeBatteryHealthEmitter(statesDir, nowIsoFn=lambda: _NOW_ISO)
    emit(healthReason=REASON_TOO_FEW_DRAINS, **_UNRESOLVED_KW)
    assert _readState(tmp_path)["reasons"] == {"health": REASON_TOO_FEW_DRAINS}


def test_theEmitCallableDefaultsToSilence(tmp_path):
    """The emit signature's default matches the builder's -- an existing caller
    that passes no reason writes an empty map, not a missing key."""
    statesDir = str(tmp_path / "states")
    emit = makeBatteryHealthEmitter(statesDir, nowIsoFn=lambda: _NOW_ISO)
    emit(**_UNRESOLVED_KW)
    assert _readState(tmp_path)["reasons"] == {}


# ---------------------------------------------------------------------------
# The whole chain -- real drain log -> real verdict -> real state file.
# ---------------------------------------------------------------------------


def test_theLivePiShape_readsStaleInTheStateFile_notMerelyUnknown(tmp_path):
    """validationCriteria 1 + 2, closed on the SSOT the story names.

    Given: the live Pi's own shape -- real qualifying drains, all aged past the
        90-day horizon (measured 2026-05-16, read 2026-08-31).
    When: a card-emit tick runs.
    Then: the file says `health_data_stale`, keeps the MEASUREMENT date, and
        carries a CURRENT `ts`.

    All three at once, because the story's claim is a composition: "we measured
    this pack, in May, and refuse to call that current."  Any one of the three
    alone is satisfied by a payload that means something else.
    """
    state = _emitOnce(
        tmp_path, hardwareManager=_liveUps(), database=_FakeDatabase(
            _qualifying(107, 109, 111)
        )
    )
    assert state["health"] == VERDICT_UNKNOWN
    assert state["reasons"] == {"health": REASON_HEALTH_DATA_STALE}
    # The MEASUREMENT date is preserved -- never advanced to fake a fresh check.
    assert state["lastHealthCheckTs"] == _iso(107)
    # ...while `ts` proves the verdict was computed NOW.  This is the pair that
    # makes "we checked and cannot say" legible without falsifying anything.
    assert state["ts"] != state["lastHealthCheckTs"]
    emittedAt = datetime.strptime(state["ts"], "%Y-%m-%dT%H:%M:%SZ")
    assert abs((emittedAt - _NOW).total_seconds()) < 120


def test_weCheckedAndCannotSay_isDistinguishableFromNothingHasChecked(tmp_path):
    """THE STORY'S NEGATIVE CASE, stated as the distinguishability claim it is.

    Two Pis, both reporting `health: unknown` with a null-ish history.  Before
    this change their state files were IDENTICAL in every field a reader could
    use.  Now the empty log says `no_qualifying_drains` ("we looked, there is
    nothing to measure") and the aged log says `health_data_stale` ("we measured
    it, in May").  Different facts, different words.
    """
    emptyLog = _emitOnce(
        tmp_path / "a", hardwareManager=_liveUps(), database=_FakeDatabase()
    )
    agedLog = _emitOnce(
        tmp_path / "b", hardwareManager=_liveUps(),
        database=_FakeDatabase(_qualifying(107, 109, 111)),
    )
    assert emptyLog["health"] == agedLog["health"] == VERDICT_UNKNOWN
    assert emptyLog["reasons"] == {"health": REASON_NO_QUALIFYING_DRAINS}
    assert agedLog["reasons"] == {"health": REASON_HEALTH_DATA_STALE}
    assert emptyLog["reasons"] != agedLog["reasons"]


def test_anAbsentDatabase_readsNoDatabase_notAnEmptyMeasurement(tmp_path):
    """An ABSENT instrument and an EMPTY measurement are different facts.  The
    bench (no database wired) must not report the same word as a car that ran
    and logged nothing."""
    state = _emitOnce(tmp_path, hardwareManager=_liveUps())
    assert state["reasons"] == {"health": REASON_NO_DATABASE}


def test_tooFewDrains_readsTooFewDrains_notStale(tmp_path):
    """Two recent qualifying drains: fresh data, just not enough of it to form
    a median.  The two thin-history causes must not collapse into one word."""
    state = _emitOnce(
        tmp_path, hardwareManager=_liveUps(), database=_FakeDatabase(
            _qualifying(1, 2)
        )
    )
    assert state["reasons"] == {"health": REASON_TOO_FEW_DRAINS}


def test_aDeadGaugeAndAStaleLog_bothSpeakForThemselves(tmp_path):
    """The composed live case, end to end: no UPS on the HardwareManager (the
    bench, and the punch-list's own dead-gauge branch) BESIDE a real aged drain
    log.  The gauge's absence travels in `source.ups`; the verdict's in
    `reasons.health`.  Two sources, two truths, neither wearing the other's."""
    state = _emitOnce(
        tmp_path, hardwareManager=SimpleNamespace(upsMonitor=None),
        database=_FakeDatabase(_qualifying(107, 109, 111)),
    )
    assert state["source"]["ups"]["available"] is False
    assert state["vcellV"] is None
    assert state["reasons"] == {"health": REASON_HEALTH_DATA_STALE}
    assert state["lastHealthCheckTs"] == _iso(107)


def test_theStateFileIsTheSurface_theJournalIsNotEnough(tmp_path):
    """US-632's first half recorded the reason to the JOURNAL only, on change,
    because the payload was outside the bench surface.  This test exists to fail
    if that arrangement is ever restored: the journal is a trace, the state file
    is the SSOT, and the card polls the SSOT."""
    state = _emitOnce(
        tmp_path, hardwareManager=_liveUps(), database=_FakeDatabase(
            _qualifying(107, 109, 111)
        )
    )
    assert state["reasons"]["health"] in UNKNOWN_REASONS
