################################################################################
# File Name: test_card_battery_health_verdict_wiring.py
# Purpose/Description: The battery-health card's HEALTH verdict, T/J numbers and
#   last-health-check are wired to the real verdict producer.  Also pins the
#   LAZY database read (the US-501/US-502 boot-order trap) and the US-707
#   fixture guard: the fixture must write every column the verdict's own SQL
#   reads or filters on, derived from that SQL rather than restated.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-504 verdict wiring into the card.
# 2026-09-09    | Ralph (Rex)  | US-617 -- fixture supplies end_vcell_v.
# 2026-09-09    | Ralph (Rex)  | US-707 -- the guard DERIVES what the fixture
#                               must supply from the verdict's SQL.
# 2026-09-24    | Rex (US-683) | The gate now reads close_reason.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T7: re-pinned on the T-vs-J
#                               verdict.  The fixture is the shared real-DDL
#                               VerdictDatabase; the US-707 guard now derives
#                               over all four verdict statements and BOTH tables
#                               (battery_health_log + startup_log); the card
#                               carries timeToFloorS / jobAvgS / jobMaxS /
#                               provisional; J's confirm wait is config
#                               pi.powerWatch.smoothingSec (Ruling 10).
# ================================================================================
################################################################################

"""The battery-health card reads the real verdict producer."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from src.common.config.validator import DEFAULTS
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG
from src.pi.power import battery_health_verdict as verdictModule
from src.pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG
from src.pi.power.battery_health_verdict import SHUTDOWN_ALLOWANCE_S, STALE_TEST_DAYS
from tests.pi.battery_verdict_fixture import (
    BATTERY_LOG_COLUMNS,
    CAL_T_FLOOR_S,
    STARTUP_LOG_COLUMNS,
    VerdictDatabase,
    goodPack,
)

# Sampled ONCE at import: the mixin owns its own wall clock.
_NOW = datetime.now(UTC).replace(tzinfo=None)

_VERDICT_SQL = ("_PACK_SQL", "_TEST_SQL", "_CAL_SQL", "_JOBS_SQL", "_FLOOR_SQL")

#: Columns the verdict reads that the fixture may legitimately leave to the
#: database: the autoincrement key, and the verdict the reader itself writes.
_DB_SUPPLIED = frozenset({"drain_event_id", "verdict"})


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


def _config(tmp_path, **powerWatch):
    pi = {
        "splash": {"statesDir": str(tmp_path / "states")},
        "dashboard": {"stateEmitIntervalSeconds": 0.0},
    }
    if powerWatch:
        pi["powerWatch"] = powerWatch
    return {"pi": pi}


def _liveUps():
    return SimpleNamespace(
        upsMonitor=SimpleNamespace(
            getBatteryVoltage=lambda: 4.05,
            getBatteryPercentage=lambda: 82,
            getChargeRatePercentPerHour=lambda: -3.2,
        )
    )


def _readState(tmp_path):
    return json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )


def _emitAndRead(tmp_path, orch):
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    return _readState(tmp_path)


def _defaultJobS(syncS: float = 100.0) -> int:
    return round(DEFAULTS["pi.powerWatch.smoothingSec"] + syncS + SHUTDOWN_ALLOWANCE_S)


# ---------------------------------------------------------------------------
# The real verdict reaches the card.
# ---------------------------------------------------------------------------


def test_emit_carriesTheRealVerdictAndItsNumbers(tmp_path):
    db = goodPack(_NOW)
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "good"
    assert bh["timeToFloorS"] == CAL_T_FLOOR_S
    assert bh["runtimeToCutoffS"] == CAL_T_FLOOR_S
    assert bh["jobAvgS"] == _defaultJobS()
    assert bh["jobMaxS"] == _defaultJobS()
    assert bh["provisional"] is False


def test_emit_lastHealthCheck_isTheCountedTestsDate(tmp_path):
    """A newer key-off row and a newer UNCOUNTED test do not move the date."""
    db = goodPack(_NOW, testDaysAgo=4)
    db.addTest(1, drainRateMvS=None)
    db.addKeyoff(0.5)
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    assert _emitAndRead(tmp_path, orch)["lastHealthCheckTs"] == db.iso(4)


def test_emit_smoothingSec_comesFromConfig(tmp_path):
    """Ruling 10: J's confirm wait is pi.powerWatch.smoothingSec, never a literal."""
    orch = _FakeOrch(_config(tmp_path, smoothingSec=7), hardwareManager=_liveUps(),
                     database=goodPack(_NOW))
    assert _emitAndRead(tmp_path, orch)["jobAvgS"] == round(7 + 100.0 + SHUTDOWN_ALLOWANCE_S)


def test_emit_absentSmoothingSec_fallsBackToTheValidatorDefault(tmp_path):
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=goodPack(_NOW))
    assert _emitAndRead(tmp_path, orch)["jobAvgS"] == _defaultJobS()


def test_emit_honestUnknownWhenTooFewSyncs(tmp_path):
    """Too few syncs to size J -> unknown, and the card still shows WHEN."""
    db = VerdictDatabase(_NOW)
    db.addTest(1)
    db.addJobs(2)
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "unknown"
    assert bh["lastHealthCheckTs"] == db.iso(1)
    assert bh["timeToFloorS"] is None


def test_emit_honestUnknownWhenTheTestIsStale(tmp_path):
    db = goodPack(_NOW, testDaysAgo=STALE_TEST_DAYS + 1)
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "unknown"
    assert bh["lastHealthCheckTs"] == db.iso(STALE_TEST_DAYS + 1)


def test_emit_noDatabase_isUnknownNeverGreen(tmp_path):
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps())
    bh = _emitAndRead(tmp_path, orch)
    assert bh["health"] == "unknown"
    assert bh["lastHealthCheckTs"] is None


def test_emit_verdictSurvivesAnUnreadableGauge(tmp_path):
    """The verdict's source is the drain LOG, not the MAX17048 -- a dead gauge
    must not blank the verdict.  The T/J numbers ARE blanked, as
    runtimeToCutoffS always was (the card is whole-card NA then anyway)."""
    hw = SimpleNamespace(
        upsMonitor=SimpleNamespace(
            getBatteryVoltage=lambda: (_ for _ in ()).throw(OSError("i2c")),
            getBatteryPercentage=lambda: 0,
            getChargeRatePercentPerHour=lambda: 0,
        )
    )
    db = goodPack(_NOW)
    orch = _FakeOrch(_config(tmp_path), hardwareManager=hw, database=db)
    bh = _emitAndRead(tmp_path, orch)
    assert bh["source"]["ups"]["available"] is False
    assert bh["health"] == "good"
    assert bh["lastHealthCheckTs"] == db.iso(1)
    assert bh["timeToFloorS"] is None and bh["jobAvgS"] is None and bh["jobMaxS"] is None


# ---------------------------------------------------------------------------
# Boot order (US-501/US-502 trap) and per-tick re-read.
# ---------------------------------------------------------------------------


def test_emit_databaseAttachedAfterEmitterInit_isStillRead(tmp_path):
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps())
    orch._initializeCardStateEmitters()
    orch._database = goodPack(_NOW)
    orch._maybeEmitCardStates()
    assert _readState(tmp_path)["health"] == "good"


def test_emit_rereadsTheLogEachTick_notCachedAtStartup(tmp_path):
    db = VerdictDatabase(_NOW)
    db.addCalibration(10)
    db.addTest(1)
    db.addJobs(2)
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    assert _emitAndRead(tmp_path, orch)["health"] == "unknown"
    db.addJobs(1)
    orch._maybeEmitCardStates()
    assert _readState(tmp_path)["health"] == "good"


# ---------------------------------------------------------------------------
# US-707: the fixture guard must catch the NEXT required column, not today's.
# ---------------------------------------------------------------------------


def _tableColumns(ddl: str, table: str) -> frozenset[str]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(ddl)
        return frozenset(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))
    finally:
        conn.close()


_BATTERY_SCHEMA = _tableColumns(SCHEMA_BATTERY_HEALTH_LOG, "battery_health_log")
_STARTUP_SCHEMA = _tableColumns(SCHEMA_STARTUP_LOG, "startup_log")


def _columnsRequiredBy(sql: str) -> frozenset[str]:
    """Columns of either table that `sql` reads OR filters on (WHERE included)."""
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))
    if "startup_log" in tokens:
        return frozenset(tokens & _STARTUP_SCHEMA)
    return frozenset(tokens & _BATTERY_SCHEMA)


def _assertFixtureCovers(sql: str) -> None:
    written = set(BATTERY_LOG_COLUMNS) | set(STARTUP_LOG_COLUMNS) | _DB_SUPPLIED
    missing = _columnsRequiredBy(sql) - written
    if missing:
        raise AssertionError(
            "the battery-health verdict requires column(s) this fixture does not "
            f"insert: {', '.join(sorted(missing))}. Add them to "
            "tests/pi/battery_verdict_fixture.py -- otherwise every row is "
            "filtered out and the verdict tests read 'unknown' for a reason that "
            "has nothing to do with the wiring (US-527/US-617)."
        )


#: A real column no verdict statement requires today.
_A_NOT_YET_REQUIRED_COLUMN = "start_vcell_v"


def _assertGuardCatches(mutated: str) -> None:
    assert _A_NOT_YET_REQUIRED_COLUMN in mutated, "the mutation must apply"
    try:
        _assertFixtureCovers(mutated)
    except AssertionError as exc:
        assert _A_NOT_YET_REQUIRED_COLUMN in str(exc), exc
    else:
        raise AssertionError("the guard passed a query needing an unwritten column")


def test_fixtureGuard_aNewSelectedColumn_failsAndNamesIt():
    _assertGuardCatches(verdictModule._TEST_SQL.replace(  # noqa: SLF001
        "window_end_s, verdict", f"window_end_s, verdict, {_A_NOT_YET_REQUIRED_COLUMN}"))


def test_fixtureGuard_aColumnRequiredOnlyByTheWhereClause_failsAndNamesIt():
    _assertGuardCatches(verdictModule._TEST_SQL.replace(  # noqa: SLF001
        "drain_rate_mv_s IS NOT NULL",
        f"drain_rate_mv_s IS NOT NULL AND {_A_NOT_YET_REQUIRED_COLUMN} IS NOT NULL"))


def test_fixtureGuard_derivesRealColumns_notAnEmptySet():
    assert {"drain_trigger", "cell_epoch", "drain_rate_mv_s"} <= _columnsRequiredBy(
        verdictModule._TEST_SQL)  # noqa: SLF001
    assert {"prior_boot_sync_outcome", "prior_boot_sync_started_at"} <= _columnsRequiredBy(
        verdictModule._JOBS_SQL)  # noqa: SLF001
    assert "battery_health_log" not in _columnsRequiredBy(verdictModule._TEST_SQL)  # noqa: SLF001


def test_fixtureGuard_todaysQueries_areFullySupplied():
    for name in _VERDICT_SQL:
        _assertFixtureCovers(getattr(verdictModule, name))
