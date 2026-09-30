################################################################################
# File Name: test_card_battery_health_verdict_wiring.py
# Purpose/Description: US-504 tests that the battery-health card's HEALTH
#   verdict + last-health-check are wired to the real battery_health_log
#   producer rather than the hardcoded health="unknown" / lastHealthCheckTs=None
#   the emitter shipped with. Also pins the LAZY database read: the card
#   emitters are constructed in _initializeCardStateEmitters, and a database
#   reference captured at that moment is the exact boot-order trap US-501/US-502
#   hit twice already this sprint.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-504 verdict wiring into the card.
# 2026-09-09    | Ralph (Rex)  | US-617 -- fixture supplies end_vcell_v.  US-527/
#                               TD-074 (2026-08-03) moved the qualifying gate
#                               from DURATION to DEPTH; this fixture kept
#                               inserting the pre-US-527 column set, so every
#                               row was filtered out and all 7 wiring tests read
#                               `unknown`.  The WIRING was never the defect.
# 2026-09-09    | Ralph (Rex)  | US-707 -- the guard now DERIVES what the fixture
#                               must supply from `_QUALIFYING_ROW_SQL` instead of
#                               restating today's 5-tuple arity.  The arity was
#                               real, passed, and could not detect the class of
#                               change it existed to catch: the NEXT required
#                               column would have gone missing exactly as
#                               `end_vcell_v` did.  Covers WHERE-clause filter
#                               columns too, not just the SELECT list.
# 2026-09-24    | Rex (US-683) | The gate now reads close_reason, and the guard
#                               fired as designed: the fixture writes 'clean' on
#                               closed rows (NULL while open), like a real close.
# ================================================================================
################################################################################

"""US-504: the battery-health card reads the real verdict producer."""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG
from pi.power.battery_health_verdict import _QUALIFYING_ROW_SQL

# Anchored to the wall clock (the mixin owns its own clock, so the fixtures
# have to be real-now-relative) but sampled ONCE at import: re-reading the clock
# per call let a second tick between an insert and its assertion, which is a
# flake, not a finding.
_NOW = datetime.now(UTC)


def _iso(daysAgo: float) -> str:
    """A canonical ISO-8601 UTC instant `daysAgo` days before now."""
    return (_NOW - timedelta(days=daysAgo)).strftime("%Y-%m-%dT%H:%M:%SZ")


#: [EXACT-adjacent] A measured end-of-drain cell voltage inside the observed
#: cutoff region for this pack (3.42-3.45 V, Spool Session-27 / 28 drains --
#: see battery_health_verdict.QUALIFYING_MAX_END_VCELL_V).  A drain that ran the
#: pack this low genuinely measured capacity, so it VOTES.
_CUTOFF_END_VCELL_V = 3.44

#: A drain that ended with the pack still near full.  Above the 3.55 V MAX17048
#: low-battery threshold, so the pack did not even get low, let alone reach
#: cutoff: this row measured nothing and must not vote.
_SHALLOW_END_VCELL_V = 4.02


#: The columns this fixture actually writes.  Declared ONCE and used to build
#: every INSERT below, so the guard cannot be checking a column list that the
#: inserts have quietly stopped matching.
_FIXTURE_COLUMNS: tuple[str, ...] = (
    "start_timestamp",
    "end_timestamp",
    "runtime_seconds",
    "load_class",
    "end_vcell_v",
    "close_reason",
)

#: US-683: a closed row carries the reason a real close writes; an open row NULL.
_CLEAN_CLOSE_REASON = "clean"

_INSERT_SQL: str = (
    f"INSERT INTO battery_health_log ({', '.join(_FIXTURE_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_FIXTURE_COLUMNS))})"
)


def _batteryHealthLogColumns() -> frozenset[str]:
    """Every column the real ``battery_health_log`` schema declares."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        return frozenset(
            row[1] for row in conn.execute("PRAGMA table_info(battery_health_log)")
        )
    finally:
        conn.close()


def _columnsRequiredBy(sql: str) -> frozenset[str]:
    """The ``battery_health_log`` columns `sql` reads OR filters on.

    Derived from the statement rather than restated, which is the whole of
    US-707.  Identifier tokens are intersected with the REAL schema, so SQL
    keywords and the table name drop out without a keyword blocklist to keep
    current -- and a column reached only through the WHERE clause counts, which
    matters because a pure filter column the fixture never writes is NULL, is
    silently excluded, and produces exactly the US-527 failure again.
    """
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))
    return frozenset(tokens & _batteryHealthLogColumns())


def _assertFixtureCoversQualifyingGate(sql: str = _QUALIFYING_ROW_SQL) -> None:
    """Fail, NAMING the columns, if the gate requires more than this fixture writes."""
    missing = _columnsRequiredBy(sql) - set(_FIXTURE_COLUMNS)
    if missing:
        raise AssertionError(
            "the battery-health qualifying gate requires column(s) this fixture "
            f"does not insert: {', '.join(sorted(missing))}. "
            "Add them to _FIXTURE_COLUMNS and to the drain tuple -- otherwise "
            "every row is filtered out and the verdict tests read 'unknown' "
            "for a reason that has nothing to do with the wiring (US-527/US-617)."
        )


class _FakeDatabase:
    """An in-memory battery_health_log shaped exactly like the Pi's.

    US-617: each drain is a 5-tuple ending in ``endVcellV``, and the arity is
    deliberately NOT optional.  US-527 made ``end_vcell_v`` a REQUIRED input to
    the qualifying gate; this fixture went on inserting the pre-US-527 column
    set and every row was silently filtered out, so seven tests asserting real
    verdicts read `unknown` for five weeks.  A missing depth now raises on the
    unpack instead of quietly producing a non-voting row.

    US-707: the arity alone defends only the columns the gate requires TODAY.
    Construction now also asserts, against the gate's OWN sql, that this fixture
    supplies everything it needs -- so the NEXT required column fails loudly and
    by name here, instead of surfacing as a bare `unknown` verdict somewhere
    downstream.
    """

    def __init__(self, drains=()):
        _assertFixtureCoversQualifyingGate()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        for daysAgo, runtimeSeconds, loadClass, closed, endVcellV in drains:
            self._conn.execute(
                _INSERT_SQL,
                (
                    _iso(daysAgo),
                    _iso(daysAgo - 0.01) if closed else None,
                    runtimeSeconds,
                    loadClass,
                    endVcellV if closed else None,
                    _CLEAN_CLOSE_REASON if closed else None,
                ),
            )
        self._conn.commit()

    @contextmanager
    def connect(self):
        yield self._conn


def _qualifyingDrains(*daysAgo, runtimeSeconds=727):
    """Closed production drains that reach cutoff -- i.e. rows that DO vote."""
    return [
        (d, runtimeSeconds, "production", True, _CUTOFF_END_VCELL_V)
        for d in daysAgo
    ]


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


def _emitAndRead(tmp_path, orch):
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    return json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# The real verdict reaches the card.
# ---------------------------------------------------------------------------


def test_emit_carriesTheRealVerdictFromTheDrainLog(tmp_path):
    """Three recent qualifying drains at the baseline -> a REAL 'good', not the
    hardcoded 'unknown' the card shipped with."""
    db = _FakeDatabase(_qualifyingDrains(1, 2, 3))
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "good"


def test_emit_carriesTheRealLastHealthCheckDate(tmp_path):
    """last-health-check is MAX(start_timestamp) over QUALIFYING rows -- the
    newest row here is a 120s key-cycle that measured nothing, so the date must
    come from the 4-day-old real drain instead.

    US-617: what disqualifies that key-cycle is now its DEPTH, not its duration.
    US-527 retired the `runtime_seconds >= 600` gate (120 s clears today's 60 s
    sanity floor), so the row ends at 4.02 V -- the pack never got near cutoff,
    which is the honest reason it measured nothing.
    """
    db = _FakeDatabase(
        [
            (0.5, 120, "production", True, _SHALLOW_END_VCELL_V),
            *_qualifyingDrains(4, 5, 6),
        ]
    )
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["lastHealthCheckTs"] == _iso(4)


def test_emit_honestUnknownWhenTheLogHasTooFewDrains(tmp_path):
    """Two qualifying drains cannot outvote scatter -> unknown, and the card
    still shows WHEN the last real check happened."""
    db = _FakeDatabase(_qualifyingDrains(1, 2))
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "unknown"
    assert bh["lastHealthCheckTs"] == _iso(1)


def test_emit_honestUnknownWhenTheHealthDataIsStale(tmp_path):
    """Good numbers 91 days old are not health data -> forced unknown."""
    db = _FakeDatabase(_qualifyingDrains(91, 92, 93, runtimeSeconds=800))
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "unknown"
    assert bh["lastHealthCheckTs"] == _iso(91)


def test_emit_noDatabase_isUnknownNeverGreen(tmp_path):
    """Bench / pre-init: no drain log -> unknown, never a fabricated verdict."""
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps())
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "unknown"
    assert bh["lastHealthCheckTs"] is None


def test_emit_verdictSurvivesAnUnreadableGauge(tmp_path):
    """The verdict's source is the drain LOG, not the MAX17048 -- a dead gauge
    must not blank a health history that is still real. (The card's US-429
    whole-card NA is a separate display policy layered above this fact.)"""
    hw = SimpleNamespace(
        upsMonitor=SimpleNamespace(
            getBatteryVoltage=lambda: (_ for _ in ()).throw(OSError("i2c")),
            getBatteryPercentage=lambda: 0,
            getChargeRatePercentPerHour=lambda: 0,
        )
    )
    db = _FakeDatabase(_qualifyingDrains(1, 2, 3))
    orch = _FakeOrch(_config(tmp_path), hardwareManager=hw, database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["source"]["ups"]["available"] is False
    assert bh["health"] == "good"
    assert bh["lastHealthCheckTs"] == _iso(1)


# ---------------------------------------------------------------------------
# Boot order (US-501/US-502 trap, 3rd sighting this sprint).
# ---------------------------------------------------------------------------


def test_emit_databaseAttachedAfterEmitterInit_isStillRead(tmp_path):
    """A database reference captured when the emitters are constructed would
    pin whatever existed at that instant. The read must be late-bound."""
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps())
    orch._initializeCardStateEmitters()
    orch._database = _FakeDatabase(_qualifyingDrains(1, 2, 3))

    orch._maybeEmitCardStates()
    bh = json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )
    assert bh["health"] == "good"


# ---------------------------------------------------------------------------
# US-707: the fixture guard must catch the NEXT required column, not today's.
# ---------------------------------------------------------------------------


#: A real `battery_health_log` column the gate does NOT require today, standing
#: in for whatever the next US-527 turns out to be.  It has to be a column that
#: genuinely exists: a gate cannot require one the table does not have -- that
#: sql would not run at all -- so an invented name is not a realistic mutation.
#: `start_vcell_v` is also the plausible one, being the other half of the depth
#: `end_vcell_v` already measures.
_A_NOT_YET_REQUIRED_COLUMN = "start_vcell_v"


def _assertGuardCatches(mutatedGate: str) -> None:
    """The guard must reject `mutatedGate`, naming the column it is missing."""
    assert _A_NOT_YET_REQUIRED_COLUMN in mutatedGate, "the mutation must apply"
    assert _A_NOT_YET_REQUIRED_COLUMN not in _FIXTURE_COLUMNS

    try:
        _assertFixtureCoversQualifyingGate(mutatedGate)
    except AssertionError as exc:
        assert _A_NOT_YET_REQUIRED_COLUMN in str(exc), (
            f"the guard fired but did not name the column: {exc}"
        )
    else:
        raise AssertionError(
            "the guard passed a gate requiring a column the fixture does not "
            "insert -- it is still pinning today's columns"
        )


def test_fixtureGuard_aSixthColumnInTheSelectList_failsAndNamesIt():
    """The guard's whole job. US-617 pinned a 5-tuple ARITY, which defends the
    columns the gate requires TODAY; the next required column would go missing
    exactly as `end_vcell_v` did on 2026-08-03 and the arity would not notice.

    It must also NAME the column -- US-617's root cause took five weeks to find
    precisely because the symptom was a bare `unknown` verdict naming nothing.
    """
    _assertGuardCatches(
        _QUALIFYING_ROW_SQL.replace(
            "       end_vcell_v, close_reason ",
            f"       end_vcell_v, close_reason, {_A_NOT_YET_REQUIRED_COLUMN} ",
        )
    )


def test_fixtureGuard_aColumnRequiredOnlyByTheWhereClause_failsAndNamesIt():
    """The harder half, and the one a SELECT-list-only derivation would miss.

    A column the gate FILTERS on but never SELECTs is still required: the
    fixture would leave it NULL, `IS NOT NULL` would exclude every row, and the
    verdict tests would read `unknown` with nothing in the diagnostic pointing
    at a column at all. That is the US-527 failure exactly, and it is INVISIBLE
    to a guard that only reads what the statement returns.
    """
    _assertGuardCatches(
        _QUALIFYING_ROW_SQL.replace(
            "  AND end_vcell_v IS NOT NULL ",
            f"  AND end_vcell_v IS NOT NULL "
            f"  AND {_A_NOT_YET_REQUIRED_COLUMN} IS NOT NULL ",
        )
    )


def test_fixtureGuard_derivesRealColumns_notAnEmptySet():
    """A derivation law is satisfied by deriving NOTHING (TD-082's lesson): if
    the token scan or the schema intersection ever breaks, `_columnsRequiredBy`
    returns the empty set and the guard above passes forever while testing
    nothing. Pin positive membership beside the law.

    `end_vcell_v` is named explicitly because it is the column whose absence
    WAS the original defect, and it is reached only through the WHERE clause
    filter as well as the SELECT list.
    """
    required = _columnsRequiredBy(_QUALIFYING_ROW_SQL)
    assert "end_vcell_v" in required
    assert {
        "start_timestamp",
        "end_timestamp",
        "runtime_seconds",
        "load_class",
    } <= required
    # Table name and SQL keywords are not columns and must not leak in.
    assert "battery_health_log" not in required


def test_fixtureGuard_todaysGate_isFullySupplied():
    """The control. Today's `_QUALIFYING_ROW_SQL` must pass -- otherwise the
    failure above is not evidence about the guard, it is evidence the fixture
    is broken right now.
    """
    _assertFixtureCoversQualifyingGate(_QUALIFYING_ROW_SQL)


def test_emit_rereadsTheLogEachTick_notCachedAtStartup(tmp_path):
    """A drain recorded while the orchestrator is running must change the card
    without a restart -- the same per-request-read discipline US-501 needed for
    .deploy-version."""
    db = _FakeDatabase(_qualifyingDrains(1, 2))
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    assert _emitAndRead(tmp_path, orch)["health"] == "unknown"

    db._conn.execute(
        _INSERT_SQL,
        (_iso(0.2), _iso(0.1), 727, "production", _CUTOFF_END_VCELL_V,
         _CLEAN_CLOSE_REASON),
    )
    db._conn.commit()

    orch._maybeEmitCardStates()
    bh = json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )
    assert bh["health"] == "good"
