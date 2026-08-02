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
# ================================================================================
################################################################################

"""US-504: the battery-health card reads the real verdict producer."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG

# Anchored to the wall clock (the mixin owns its own clock, so the fixtures
# have to be real-now-relative) but sampled ONCE at import: re-reading the clock
# per call let a second tick between an insert and its assertion, which is a
# flake, not a finding.
_NOW = datetime.now(UTC)


def _iso(daysAgo: float) -> str:
    """A canonical ISO-8601 UTC instant `daysAgo` days before now."""
    return (_NOW - timedelta(days=daysAgo)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _FakeDatabase:
    """An in-memory battery_health_log shaped exactly like the Pi's."""

    def __init__(self, drains=()):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        for daysAgo, runtimeSeconds, loadClass, closed in drains:
            self._conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, end_timestamp, runtime_seconds, load_class) "
                "VALUES (?, ?, ?, ?)",
                (
                    _iso(daysAgo),
                    _iso(daysAgo - 0.01) if closed else None,
                    runtimeSeconds,
                    loadClass,
                ),
            )
        self._conn.commit()

    @contextmanager
    def connect(self):
        yield self._conn


def _qualifyingDrains(*daysAgo, runtimeSeconds=727):
    return [(d, runtimeSeconds, "production", True) for d in daysAgo]


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
    come from the 4-day-old real drain instead."""
    db = _FakeDatabase(
        [(0.5, 120, "production", True), *_qualifyingDrains(4, 5, 6)]
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


def test_emit_rereadsTheLogEachTick_notCachedAtStartup(tmp_path):
    """A drain recorded while the orchestrator is running must change the card
    without a restart -- the same per-request-read discipline US-501 needed for
    .deploy-version."""
    db = _FakeDatabase(_qualifyingDrains(1, 2))
    orch = _FakeOrch(_config(tmp_path), hardwareManager=_liveUps(), database=db)
    assert _emitAndRead(tmp_path, orch)["health"] == "unknown"

    db._conn.execute(
        "INSERT INTO battery_health_log "
        "(start_timestamp, end_timestamp, runtime_seconds, load_class) "
        "VALUES (?, ?, ?, ?)",
        (_iso(0.2), _iso(0.1), 727, "production"),
    )
    db._conn.commit()

    orch._maybeEmitCardStates()
    bh = json.loads(
        (tmp_path / "states" / "battery-health").read_text(encoding="utf-8")
    )
    assert bh["health"] == "good"
