################################################################################
# File Name: test_alerts_arbiter.py
# Purpose/Description: US-897-b2 states/alerts -- the alerts arbiter's payload
#   shape, the live coolant STOP episode (fresh / stale / cleared / re-opened),
#   the icon and entry order, the alert_log overheat record and the per-boot
#   seed from the tmpfs states/alerts.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-b2) | Initial.
# 2026-10-20    | Rex (US-897-b5) | The CODE source, codeAlert and the code icon.
# ================================================================================
################################################################################

"""Tests for ``pi.obdii.alerts_arbiter`` (US-897-b2)."""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import pi.obdii.alerts_arbiter as aa

_STOP_ID = "engine:COOLANT_TEMP:stop"
_NOW = datetime(2026, 10, 20, 15, 12, 29, tzinfo=UTC)

_TOP_LEVEL_KEYS = {
    "ts",
    "dataSource",
    "bootId",
    "sources",
    "codesCheckedThisSession",
    "checkedAtTs",
    "icon",
    "takeover",
    "codeAlert",
    "entries",
}
_ENTRY_KEYS = {
    "id",
    "source",
    "key",
    "tier",
    "title",
    "sentence",
    "directive",
    "value",
    "unit",
    "last",
    "stale",
    "firstSeenTs",
    "lastSeenTs",
    "active",
    "acknowledged",
    "codeStatus",
}


# ------------------------------------------------------------------ helpers


def _band(name: str) -> dict[str, str]:
    return {"band": name, "since": "2026-10-20T15:00:00Z", "reason": "test"}


def _fresh(value: float, ts: str, band: str = "red") -> dict[str, Any]:
    """An obd-live COOLANT_TEMP entry as buildObdLiveState publishes it fresh."""
    return {
        "value": value,
        "unit": "C",
        "ts": ts,
        "stale": False,
        "band": _band(band),
        "last": None,
    }


def _stale(lastValue: float, ts: str, band: str = "red") -> dict[str, Any]:
    """The obd-live stale shape: value null, last {value, band}."""
    return {
        "value": None,
        "unit": "C",
        "ts": ts,
        "stale": True,
        "band": None,
        "noBandReason": "stale",
        "last": {"value": lastValue, "band": _band(band)},
    }


def _notRead(ts: str) -> dict[str, Any]:
    return {
        "value": None,
        "unit": "C",
        "ts": ts,
        "stale": False,
        "band": None,
        "noBandReason": "not_read",
        "last": None,
    }


def _obdLive(coolant: dict[str, Any] | None, dataSource: str = "real") -> dict[str, Any]:
    params = {} if coolant is None else {"COOLANT_TEMP": coolant}
    return {"params": params, "fuel": {}, "dataSource": dataSource, "ts": "2026-10-20T15:12:29Z"}


class _DriveIds:
    def __init__(self, driveId: int | None = 42) -> None:
        self.driveId = driveId

    def __call__(self) -> int | None:
        return self.driveId


def _arbiter(config: dict[str, Any] | None = None, driveId: int | None = 42) -> aa.AlertsArbiter:
    return aa.AlertsArbiter(config or {}, driveIdProvider=_DriveIds(driveId))


def _build(arbiter: aa.AlertsArbiter, obdLive: dict[str, Any] | None, **kw: Any) -> dict[str, Any]:
    return aa.buildAlertsState(
        arbiter.episodes(),
        obdLive,
        _NOW,
        dataSource=kw.get("dataSource", "real"),
        bootId=kw.get("bootId", "b7"),
        codeSource=arbiter.codeSource(),
    )


def _step(
    arbiter: aa.AlertsArbiter,
    coolant: dict[str, Any] | None,
    *,
    database: Any = None,
    dataSource: str = "real",
) -> dict[str, Any]:
    obdLive = _obdLive(coolant, dataSource)
    arbiter.observe(obdLive, dataSource=dataSource, database=database)
    return _build(arbiter, obdLive, dataSource=dataSource)


@pytest.fixture
def db(tmp_path: Path) -> Any:
    from pi.obdii.database import ObdDatabase

    database = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    database.initialize()
    return database


def _alertRows(database: Any) -> list[tuple]:
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, alert_type, parameter_name, value, threshold, drive_id "
            "FROM alert_log ORDER BY id"
        ).fetchall()
    return [tuple(row) for row in rows]


# ------------------------------------------------------------------- shape


def test_shape_everyKeyPresent_nothingAssessed() -> None:
    """
    Given: no episode and no obd-live payload
    When: the state is built
    Then: every s2 key is present, code/system/data are unassessed, icon not_checked
    """
    state = aa.buildAlertsState([], None, _NOW, dataSource=None, bootId="unknown")

    assert set(state) == _TOP_LEVEL_KEYS
    assert state["ts"] == "2026-10-20T15:12:29Z"
    assert state["dataSource"] is None
    assert state["bootId"] == "unknown"
    assert state["sources"] == {
        "code": {"assessed": False, "checkedAtTs": None},
        "engine": {"assessed": False},
        "system": {"assessed": False, "reason": "not_built"},
        "data": {"assessed": False, "reason": "not_built"},
    }
    assert state["codesCheckedThisSession"] is False
    assert state["checkedAtTs"] is None
    assert state["icon"] == {"state": "not_checked", "count": 0, "pulse": False}
    assert state["takeover"] is None
    assert state["codeAlert"] is None
    assert state["entries"] == []


def test_shape_dataSourceAndBootIdPassThrough() -> None:
    state = aa.buildAlertsState([], _obdLive(None), _NOW, dataSource="real", bootId="b7")

    assert state["dataSource"] == "real"
    assert state["bootId"] == "b7"


# ------------------------------------------------------- the coolant STOP


def test_coolantRedFresh_stopEntry_takeover_iconStopPulsing() -> None:
    """VC1: obd-live COOLANT_TEMP 112 C band red, fresh."""
    arbiter = _arbiter()

    state = _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    entry = state["entries"][0]
    assert set(entry) == _ENTRY_KEYS
    assert entry["id"] == _STOP_ID
    assert entry["source"] == "engine"
    assert entry["key"] == "COOLANT_TEMP"
    assert entry["tier"] == "stop"
    assert entry["directive"] == "PULL OVER"
    assert entry["title"] == "ENGINE OVERHEATING"
    assert entry["sentence"] == "Stop safely, engine off. Do not open the radiator cap hot."
    assert entry["value"] == 112
    assert entry["unit"] == "C"
    assert entry["stale"] is False
    assert entry["last"] is None
    assert entry["active"] is True
    assert entry["acknowledged"] is False
    assert entry["firstSeenTs"] == "2026-10-20T15:12:27Z"
    assert entry["lastSeenTs"] == "2026-10-20T15:12:27Z"

    assert state["takeover"] == {
        "id": _STOP_ID,
        "title": "ENGINE OVERHEATING",
        "sentence": "Stop safely, engine off. Do not open the radiator cap hot.",
        "directive": "PULL OVER",
        "value": 112,
        "unit": "C",
        "last": None,
        "stale": False,
        "firstSeenTs": "2026-10-20T15:12:27Z",
        "dismissable": False,
    }
    assert state["icon"] == {"state": "stop", "count": 1, "pulse": True}
    assert state["sources"]["engine"] == {"assessed": True}


def test_coolantRed_laterReading_advancesLastSeen_keepsFirstSeen() -> None:
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    state = _step(arbiter, _fresh(114, "2026-10-20T15:12:29Z"))

    entry = state["entries"][0]
    assert entry["firstSeenTs"] == "2026-10-20T15:12:27Z"
    assert entry["lastSeenTs"] == "2026-10-20T15:12:29Z"
    assert entry["value"] == 114
    assert len(state["entries"]) == 1


def test_coolantRedGoesStale_stillActive_valueNull_lastCarried_takeoverKept() -> None:
    """VC2: same, reading goes stale -- stale never clears (Spool, Atlas Q10)."""
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    state = _step(arbiter, _stale(112, "2026-10-20T15:12:27Z"))

    entry = state["entries"][0]
    assert entry["active"] is True
    assert entry["stale"] is True
    assert entry["value"] is None
    assert entry["last"]["value"] == 112
    assert entry["last"]["ts"] == "2026-10-20T15:12:27Z"
    assert entry["last"]["band"]["band"] == "red"
    assert state["takeover"] is not None
    assert state["takeover"]["stale"] is True
    assert state["takeover"]["value"] is None
    assert state["takeover"]["last"]["value"] == 112
    assert state["icon"] == {"state": "stop", "count": 1, "pulse": True}
    assert state["sources"]["engine"] == {"assessed": False}


@pytest.mark.parametrize(
    "coolant",
    [None, _notRead("2026-10-20T15:12:29Z")],
    ids=["absent", "not_read"],
)
def test_engineUnassessed_activeStopStaysActiveAndStale(coolant: Any) -> None:
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    state = _step(arbiter, coolant)

    assert state["sources"]["engine"] == {"assessed": False}
    assert state["entries"][0]["active"] is True
    assert state["entries"][0]["stale"] is True
    assert state["entries"][0]["last"]["value"] == 112


def test_noObdLivePayload_activeStopStaysActiveAndStale() -> None:
    """obd-live absent (its write failed / tracker None) -> the STOP never clears."""
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    arbiter.observe(None, dataSource="real", database=None)
    state = _build(arbiter, None)

    assert state["sources"]["engine"] == {"assessed": False}
    assert state["entries"][0]["active"] is True
    assert state["entries"][0]["stale"] is True


def test_bandClears_entryInactiveStillListed_takeoverNull_iconNotChecked() -> None:
    """VC3: band clears (101 held 60 s) -> active false, still listed."""
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    state = _step(arbiter, _fresh(101, "2026-10-20T15:14:00Z", band="amber"))

    entry = state["entries"][0]
    assert entry["id"] == _STOP_ID
    assert entry["active"] is False
    assert entry["acknowledged"] is False
    assert entry["stale"] is False
    assert entry["lastSeenTs"] == "2026-10-20T15:12:27Z"
    assert state["takeover"] is None
    # No dtc payload was handed in, so sources.code is unassessed.
    assert state["icon"] == {"state": "not_checked", "count": 0, "pulse": False}
    assert state["sources"]["engine"] == {"assessed": True}


def test_clearedStop_neverDropsByTime() -> None:
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))
    _step(arbiter, _fresh(95, "2026-10-20T15:14:00Z", band="green"))

    for i in range(5):
        state = _step(arbiter, _fresh(90, f"2026-10-20T16:0{i}:00Z", band="green"))

    assert [e["id"] for e in state["entries"]] == [_STOP_ID]
    assert state["entries"][0]["active"] is False


def test_newRedEpisode_reactivatesTheSameId_withANewFirstSeen() -> None:
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))
    _step(arbiter, _fresh(95, "2026-10-20T15:14:00Z", band="green"))

    state = _step(arbiter, _fresh(111, "2026-10-20T15:30:00Z"))

    assert len(state["entries"]) == 1
    entry = state["entries"][0]
    assert entry["active"] is True
    assert entry["acknowledged"] is False
    assert entry["firstSeenTs"] == "2026-10-20T15:30:00Z"
    assert state["takeover"]["firstSeenTs"] == "2026-10-20T15:30:00Z"


def test_freshNonRedWithoutAnEpisode_noEntry_engineAssessed_iconNotChecked() -> None:
    """Engine running green: nothing listed; not 'none' while codes are unassessed."""
    state = _step(_arbiter(), _fresh(88, "2026-10-20T15:12:27Z", band="green"))

    assert state["entries"] == []
    assert state["sources"]["engine"] == {"assessed": True}
    assert state["icon"] == {"state": "not_checked", "count": 0, "pulse": False}


def test_redTier_comesFromConfig() -> None:
    """The id carries the configured tier (pi.warnings.engine.COOLANT_TEMP.redTier)."""
    config = {"pi": {"warnings": {"engine": {"COOLANT_TEMP": {"redTier": "watch"}}}}}
    arbiter = _arbiter(config)

    state = _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    assert state["entries"][0]["id"] == "engine:COOLANT_TEMP:watch"
    assert state["takeover"] is None
    assert state["icon"] == {"state": "watch", "count": 1, "pulse": True}


# ----------------------------------------------------- icon + entry order


def _episode(**kw: Any) -> aa.AlertEpisode:
    base: dict[str, Any] = {
        "source": "code",
        "key": "P0400",
        "tier": "watch",
        "title": "T",
        "sentence": "S",
        "directive": None,
        "unit": None,
        "firstSeenTs": "2026-10-20T10:00:00Z",
        "lastSeenTs": "2026-10-20T10:00:00Z",
        "active": True,
    }
    base.update(kw)
    return aa.AlertEpisode(**base)


@pytest.mark.parametrize("tier", ["watch", "minor", "unrated"])
def test_icon_activeWatchMinorUnrated_isWatch_codeEntriesDoNotPulse(tier: str) -> None:
    """G7: minor/unrated map to watch (amber); pulse is for ENGINE entries only."""
    state = aa.buildAlertsState(
        [_episode(tier=tier)], None, _NOW, dataSource="real", bootId="b7"
    )

    assert state["icon"] == {"state": "watch", "count": 1, "pulse": False}


def test_icon_activeEngineWatch_pulses() -> None:
    episode = _episode(source="engine", key="BATTERY_V", tier="watch")

    state = aa.buildAlertsState([episode], None, _NOW, dataSource="real", bootId="b7")

    assert state["icon"] == {"state": "watch", "count": 1, "pulse": True}


def test_icon_stopOutranksWatch_countIsActiveEntriesOnly() -> None:
    episodes = [
        _episode(source="engine", key="COOLANT_TEMP", tier="stop"),
        _episode(key="P0443", tier="minor"),
        _episode(key="P0400", tier="watch", active=False),
    ]

    state = aa.buildAlertsState(episodes, None, _NOW, dataSource="real", bootId="b7")

    assert state["icon"] == {"state": "stop", "count": 2, "pulse": True}


def test_entries_orderTierThenLiveBeforeStoredThenNewest() -> None:
    """B5: stop > watch > minor > unrated, then engine before code, then newest."""
    episodes = [
        _episode(key="P1111", tier="unrated", firstSeenTs="2026-10-20T12:00:00Z"),
        _episode(key="P0443", tier="minor", firstSeenTs="2026-10-20T12:00:00Z"),
        _episode(key="P0400", tier="watch", firstSeenTs="2026-10-20T12:00:00Z"),
        _episode(source="engine", key="RPM", tier="watch", firstSeenTs="2026-10-20T09:00:00Z"),
        _episode(key="P0401", tier="watch", firstSeenTs="2026-10-20T13:00:00Z"),
        _episode(source="engine", key="COOLANT_TEMP", tier="stop", active=False),
    ]

    state = aa.buildAlertsState(episodes, None, _NOW, dataSource="real", bootId="b7")

    assert [e["id"] for e in state["entries"]] == [
        "engine:COOLANT_TEMP:stop",
        "engine:RPM:watch",
        "code:P0401:watch",
        "code:P0400:watch",
        "code:P0443:minor",
        "code:P1111:unrated",
    ]
    # The top entry is an INACTIVE stop: the takeover follows the top ACTIVE one.
    assert state["takeover"] is None


# ------------------------------------------------- alert_log overheat record


def test_alertLog_openThenClear_writesTwoRows_openValueThenPeak(db: Any) -> None:
    """VC4: 'coolant_stop' (opening value, threshold redC) then
    'coolant_stop_clear' (episode peak, threshold redClearBelowC)."""
    arbiter = _arbiter(driveId=42)
    _step(arbiter, _fresh(111, "2026-10-20T15:12:27Z"), database=db)
    _step(arbiter, _fresh(116, "2026-10-20T15:12:29Z"), database=db)
    _step(arbiter, _fresh(113, "2026-10-20T15:12:31Z"), database=db)
    _step(arbiter, _stale(113, "2026-10-20T15:12:31Z"), database=db)

    assert _alertRows(db) == [
        ("2026-10-20T15:12:27Z", "coolant_stop", "COOLANT_TEMP", 111.0, 110.0, 42),
    ]

    _step(arbiter, _fresh(101, "2026-10-20T15:14:00Z", band="amber"), database=db)

    assert _alertRows(db) == [
        ("2026-10-20T15:12:27Z", "coolant_stop", "COOLANT_TEMP", 111.0, 110.0, 42),
        ("2026-10-20T15:14:00Z", "coolant_stop_clear", "COOLANT_TEMP", 116.0, 101.0, 42),
    ]
    assert aa.ALERT_TYPE_COOLANT_STOP == "coolant_stop"
    assert aa.ALERT_TYPE_COOLANT_STOP_CLEAR == "coolant_stop_clear"


def test_alertLog_openThenKeyOff_writesOneRow(db: Any) -> None:
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"), database=db)
    _step(arbiter, None, database=db)
    _step(arbiter, _stale(112, "2026-10-20T15:12:27Z"), database=db)

    assert [r[1] for r in _alertRows(db)] == ["coolant_stop"]


def test_alertLog_thresholdsFollowConfig(db: Any) -> None:
    config = {"pi": {"bands": {"coolant": {"redC": 112, "redClearBelowC": 100}}}}
    arbiter = _arbiter(config)
    _step(arbiter, _fresh(113, "2026-10-20T15:12:27Z"), database=db)
    _step(arbiter, _fresh(99, "2026-10-20T15:14:00Z", band="amber"), database=db)

    assert [(r[1], r[4]) for r in _alertRows(db)] == [
        ("coolant_stop", 112.0),
        ("coolant_stop_clear", 100.0),
    ]


@pytest.mark.parametrize("dataSource", ["replay", "physics_sim"])
def test_alertLog_replayOrPhysicsSim_noRow_entryStillShown(db: Any, dataSource: str) -> None:
    """R28: the server rejects those rows, so the Pi never creates them."""
    arbiter = _arbiter()
    state = _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"), database=db, dataSource=dataSource)
    _step(arbiter, _fresh(95, "2026-10-20T15:14:00Z", band="green"), database=db, dataSource=dataSource)

    assert _alertRows(db) == []
    assert state["entries"][0]["active"] is True
    assert state["dataSource"] == dataSource


class _BrokenDatabase:
    def connect(self) -> Any:
        raise OSError("disk I/O error")


def test_alertLog_insertFailure_logsError_stopStillLive(caplog: pytest.LogCaptureFixture) -> None:
    arbiter = _arbiter()

    with caplog.at_level(logging.ERROR, logger="pi.obdii.alerts_arbiter"):
        state = _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"), database=_BrokenDatabase())

    assert state["takeover"]["directive"] == "PULL OVER"
    assert state["entries"][0]["active"] is True
    assert any("alert_log" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)


def test_alertLog_neverUpdated_insertOnly() -> None:
    """Sync is a delta by id: no SQL string in the module UPDATEs alert_log."""
    tree = ast.parse(Path(aa.__file__).read_text(encoding="utf-8"))
    sql = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "alert_log" in node.value
    ]
    assert any("INSERT INTO alert_log" in s for s in sql)
    # Scoped to the SQL form: the module's own prose says "never UPDATE".
    assert not [s for s in sql if re.search(r"\bUPDATE\s+alert_log\b", s, re.IGNORECASE)]


# ------------------------------------------------- per-boot seed (Atlas G3)


def _writeAlerts(statesDir: Path, payload: Any) -> None:
    statesDir.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (statesDir / aa.ALERTS_STATE_FILENAME).write_text(text, encoding="utf-8")


def _priorState(arbiter: aa.AlertsArbiter, obdLive: dict[str, Any] | None) -> dict[str, Any]:
    return _build(arbiter, obdLive)


def test_seed_clearedStopSurvivesARestart(tmp_path: Path) -> None:
    """VC5: cleared STOP listed active:false, then orchestrator restart."""
    first = _arbiter()
    _step(first, _fresh(112, "2026-10-20T15:12:27Z"))
    prior = _step(first, _fresh(95, "2026-10-20T15:14:00Z", band="green"))
    _writeAlerts(tmp_path, prior)

    restarted = aa.AlertsArbiter(
        {}, driveIdProvider=_DriveIds(), seedEntries=aa.readAlertsSeed(str(tmp_path))
    )
    state = _step(restarted, _fresh(90, "2026-10-20T15:20:00Z", band="green"))

    assert [e["id"] for e in state["entries"]] == [_STOP_ID]
    entry = state["entries"][0]
    assert entry["active"] is False
    assert entry["firstSeenTs"] == "2026-10-20T15:12:27Z"
    assert entry["title"] == "ENGINE OVERHEATING"


def test_seed_activeStopIsStaleUntilAFreshReadingDecides(tmp_path: Path, db: Any) -> None:
    first = _arbiter()
    _writeAlerts(tmp_path, _step(first, _fresh(112, "2026-10-20T15:12:27Z")))
    restarted = aa.AlertsArbiter(
        {}, driveIdProvider=_DriveIds(), seedEntries=aa.readAlertsSeed(str(tmp_path))
    )

    seeded = _build(restarted, None)
    assert seeded["entries"][0]["active"] is True
    assert seeded["entries"][0]["stale"] is True
    assert seeded["entries"][0]["value"] is None
    assert seeded["entries"][0]["last"]["value"] == 112
    assert seeded["takeover"]["stale"] is True

    # Still red after the restart: the episode continues (same firstSeenTs) and,
    # as stated (G3), a second 'coolant_stop' open row is written.
    state = _step(restarted, _fresh(113, "2026-10-20T15:13:00Z"), database=db)
    assert state["entries"][0]["stale"] is False
    assert state["entries"][0]["firstSeenTs"] == "2026-10-20T15:12:27Z"
    assert [r[1] for r in _alertRows(db)] == ["coolant_stop"]

    _step(restarted, _fresh(95, "2026-10-20T15:15:00Z", band="green"), database=db)
    assert [(r[1], r[3]) for r in _alertRows(db)] == [
        ("coolant_stop", 113.0),
        ("coolant_stop_clear", 113.0),
    ]


def test_seed_activeStopClearedByTheFirstFreshReading(tmp_path: Path) -> None:
    first = _arbiter()
    _writeAlerts(tmp_path, _step(first, _fresh(112, "2026-10-20T15:12:27Z")))
    restarted = aa.AlertsArbiter(
        {}, driveIdProvider=_DriveIds(), seedEntries=aa.readAlertsSeed(str(tmp_path))
    )

    state = _step(restarted, _fresh(95, "2026-10-20T15:15:00Z", band="green"))

    assert state["entries"][0]["active"] is False
    assert state["takeover"] is None


@pytest.mark.parametrize(
    "content",
    [None, "{not json", "[]", {"entries": "x"}, {"entries": [{"id": "engine:X:stop"}]}],
    ids=["missing", "unparseable", "notAnObject", "entriesNotAList", "unknownId"],
)
def test_seed_missingOrUnusableFile_seedsNothing(tmp_path: Path, content: Any) -> None:
    if content is not None:
        _writeAlerts(tmp_path, content)

    restarted = aa.AlertsArbiter(
        {}, driveIdProvider=_DriveIds(), seedEntries=aa.readAlertsSeed(str(tmp_path))
    )

    assert restarted.episodes() == []


# ------------------------------------------- battery WATCH (US-897-b3)

_BATTERY_ID = "engine:BATTERY_V:watch"
_LOW_TITLE = "CHARGING FAULT"
_LOW_SENTENCE = "Head somewhere safe. Turn off accessories."
_HIGH_TITLE = "OVERCHARGING"
_HIGH_SENTENCE = "Head somewhere safe, then engine off."


def _batt(value: float, ts: str, band: str | None = "red", reason: str = "test") -> dict[str, Any]:
    """An obd-live BATTERY_V entry as buildObdLiveState publishes it fresh.

    ``band=None`` is the null band (engine_not_running / amber_not_shipped).
    """
    return {
        "value": value,
        "unit": "V",
        "ts": ts,
        "stale": False,
        "band": None if band is None else _band(band),
        **({"noBandReason": reason} if band is None else {}),
        "last": None,
    }


def _battStale(lastValue: float, ts: str) -> dict[str, Any]:
    return {
        "value": None,
        "unit": "V",
        "ts": ts,
        "stale": True,
        "band": None,
        "noBandReason": "stale",
        "last": {"value": lastValue, "band": _band("red")},
    }


def _stepBattery(arbiter: aa.AlertsArbiter, battery: dict[str, Any] | None) -> dict[str, Any]:
    obdLive = _obdLive(None)
    if battery is not None:
        obdLive["params"]["BATTERY_V"] = battery
    arbiter.observe(obdLive, dataSource="real", database=None)
    return _build(arbiter, obdLive)


def _batteryEntry(state: dict[str, Any]) -> dict[str, Any] | None:
    return next((e for e in state["entries"] if e["id"] == _BATTERY_ID), None)


def test_batteryLow_watchEntry_chargingFaultWords_valueFlooredTowardTheBreach() -> None:
    """VC1: 11.96 V red -> CHARGING FAULT, 11.9 (floor toward the breach)."""
    state = _stepBattery(_arbiter(), _batt(11.96, "2026-10-20T15:12:27Z"))

    entry = _batteryEntry(state)
    assert entry is not None
    assert set(entry) == _ENTRY_KEYS
    assert entry["source"] == "engine"
    assert entry["key"] == "BATTERY_V"
    assert entry["tier"] == "watch"
    assert entry["title"] == _LOW_TITLE
    assert entry["sentence"] == _LOW_SENTENCE
    assert entry["directive"] is None
    assert entry["value"] == 11.9
    assert entry["unit"] == "V"
    assert entry["active"] is True
    assert entry["stale"] is False
    assert entry["last"] is None
    assert entry["firstSeenTs"] == "2026-10-20T15:12:27Z"
    # A WATCH never takes over the screen.
    assert state["takeover"] is None


def test_batteryHigh_overchargingWords_valueCeiledTowardTheBreach() -> None:
    """VC2: 15.04 V red -> OVERCHARGING, 15.1 (ceil toward the breach)."""
    entry = _batteryEntry(_stepBattery(_arbiter(), _batt(15.04, "2026-10-20T15:12:27Z")))

    assert entry is not None
    assert entry["title"] == _HIGH_TITLE
    assert entry["sentence"] == _HIGH_SENTENCE
    assert entry["value"] == 15.1


@pytest.mark.parametrize(
    ("value", "expected"),
    [(11.96, 11.9), (11.9, 11.9), (11.01, 11.0), (9.99, 9.9), (15.04, 15.1), (15.1, 15.1),
     (15.0001, 15.1), (16.0, 16.0)],
)
def test_batteryValue_oneDecimal_roundedTowardTheBreach(value: float, expected: float) -> None:
    """Spool 2026-10-19: low floors, high ceils; an exact tenth is never moved."""
    entry = _batteryEntry(_stepBattery(_arbiter(), _batt(value, "2026-10-20T15:12:27Z")))

    assert entry is not None
    assert entry["value"] == expected


def test_batterySide_comesFromTheConfiguredEdges_notTheBandReason() -> None:
    """Side from the VALUE vs pi.bands.battery.redBelowV / redAboveV."""
    config = {"pi": {"bands": {"battery": {"redBelowV": 11.0, "redAboveV": 14.8}}}}
    arbiter = _arbiter(config)

    entry = _batteryEntry(_stepBattery(arbiter, _batt(14.9, "2026-10-20T15:12:27Z")))

    assert entry is not None
    assert entry["title"] == _HIGH_TITLE


def test_batteryTier_comesFromConfig() -> None:
    from common.config.validator import DEFAULTS

    assert DEFAULTS["pi.warnings.engine.BATTERY_V.redTier"] == "watch"
    arbiter = _arbiter()
    entry = _batteryEntry(_stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:27Z")))
    assert entry is not None and entry["tier"] == "watch"


def test_batteryGreen9s_keepsIt_green10s_endsIt_byReadingTime() -> None:
    """VC3: the episode ends only after the band has been GREEN for 10 s, measured
    on the READINGS' ts (not the wall clock)."""
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:00Z"))

    _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:02Z", band="green"))
    held = _batteryEntry(_stepBattery(arbiter, _batt(13.9, "2026-10-20T15:12:11Z", band="green")))
    assert held is not None
    assert held["active"] is True
    assert held["stale"] is False
    # The hold keeps the low side's words.
    assert held["title"] == _LOW_TITLE

    state = _stepBattery(arbiter, _batt(13.9, "2026-10-20T15:12:12Z", band="green"))
    ended = _batteryEntry(state)
    assert ended is not None
    assert ended["active"] is False
    assert ended["value"] is None
    assert ended["last"]["value"] == 11.5
    # Ended stays listed (Q15) and no longer counts.
    assert state["icon"]["count"] == 0


def test_batteryGreenHold_restartsAfterARedReading() -> None:
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:00Z"))
    _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:02Z", band="green"))
    _stepBattery(arbiter, _batt(11.6, "2026-10-20T15:12:06Z"))

    held = _batteryEntry(_stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:13Z", band="green")))
    assert held is not None and held["active"] is True

    ended = _batteryEntry(_stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:23Z", band="green")))
    assert ended is not None and ended["active"] is False


def test_batteryClearGreenHoldSec_comesFromConfig() -> None:
    from common.config.validator import DEFAULTS

    assert DEFAULTS["pi.warnings.battery.clearGreenHoldSec"] == 10
    arbiter = _arbiter({"pi": {"warnings": {"battery": {"clearGreenHoldSec": 3}}}})
    _stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:00Z"))
    _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:02Z", band="green"))

    ended = _batteryEntry(_stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:05Z", band="green")))
    assert ended is not None and ended["active"] is False


@pytest.mark.parametrize("reason", ["engine_not_running", "amber_not_shipped"])
def test_batteryNullBand_neverEndsIt_staysActiveStale(reason: str) -> None:
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(11.96, "2026-10-20T15:12:00Z"))

    for second in range(1, 40, 2):
        state = _stepBattery(
            arbiter, _batt(12.5, f"2026-10-20T15:12:{second:02d}Z", band=None, reason=reason)
        )

    entry = _batteryEntry(state)
    assert entry is not None
    assert entry["active"] is True
    assert entry["stale"] is True
    assert entry["value"] is None
    assert entry["last"]["value"] == 11.9
    assert entry["last"]["ts"] == "2026-10-20T15:12:00Z"


def test_batteryNullBand_breaksTheGreenHold() -> None:
    """Green must be HELD: a null band in between restarts the 10 s."""
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:00Z"))
    _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:02Z", band="green"))
    _stepBattery(arbiter, _batt(13.0, "2026-10-20T15:12:06Z", band=None, reason="amber_not_shipped"))

    held = _batteryEntry(_stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:13Z", band="green")))
    assert held is not None and held["active"] is True


def test_batteryStale_keepsItActive_withLastRoundedTowardTheBreach() -> None:
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(15.04, "2026-10-20T15:12:00Z"))

    state = _stepBattery(arbiter, _battStale(15.04, "2026-10-20T15:12:30Z"))
    entry = _batteryEntry(state)
    assert entry is not None
    assert entry["active"] is True
    assert entry["stale"] is True
    assert entry["value"] is None
    assert entry["last"]["value"] == 15.1
    assert entry["last"]["band"]["band"] == "red"
    assert entry["title"] == _HIGH_TITLE

    # Absent altogether (obd-live published nothing): still active.
    arbiter.observe(None, dataSource="real", database=None)
    assert _batteryEntry(_build(arbiter, None))["active"] is True


def test_batteryFlipLowToHigh_keepsTheId_titleFollowsTheSide() -> None:
    arbiter = _arbiter()
    first = _batteryEntry(_stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:00Z")))

    state = _stepBattery(arbiter, _batt(15.3, "2026-10-20T15:12:02Z"))

    assert [e["id"] for e in state["entries"]] == [_BATTERY_ID]
    flipped = _batteryEntry(state)
    assert flipped is not None
    assert flipped["title"] == _HIGH_TITLE
    assert flipped["sentence"] == _HIGH_SENTENCE
    assert flipped["value"] == 15.3
    assert flipped["firstSeenTs"] == first["firstSeenTs"]
    assert flipped["lastSeenTs"] == "2026-10-20T15:12:02Z"


def test_batteryAmberOrGreen_withoutAnEpisode_makesNoEntry() -> None:
    arbiter = _arbiter()

    _stepBattery(arbiter, _batt(13.0, "2026-10-20T15:12:00Z", band=None, reason="amber_not_shipped"))
    state = _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:02Z", band="green"))

    assert state["entries"] == []
    assert arbiter.episodes() == []


def test_batteryActive_iconWatchPulsing_noTakeover() -> None:
    state = _stepBattery(_arbiter(), _batt(11.5, "2026-10-20T15:12:00Z"))

    assert state["icon"] == {"state": "watch", "count": 1, "pulse": True}
    assert state["takeover"] is None


def test_batteryWatch_ordersBelowTheCoolantStop() -> None:
    arbiter = _arbiter()
    obdLive = _obdLive(_fresh(112, "2026-10-20T15:12:27Z"))
    obdLive["params"]["BATTERY_V"] = _batt(11.5, "2026-10-20T15:12:27Z")
    arbiter.observe(obdLive, dataSource="real", database=None)

    state = _build(arbiter, obdLive)

    assert [e["id"] for e in state["entries"]] == [_STOP_ID, _BATTERY_ID]
    assert state["icon"] == {"state": "stop", "count": 2, "pulse": True}
    assert state["takeover"]["id"] == _STOP_ID


def test_batteryEpisode_writesNoAlertLogRow(db: Any) -> None:
    """Only the coolant STOP is recorded (Atlas Q15); the battery WATCH is not."""
    arbiter = _arbiter()
    obdLive = _obdLive(None)
    obdLive["params"]["BATTERY_V"] = _batt(11.5, "2026-10-20T15:12:00Z")
    arbiter.observe(obdLive, dataSource="real", database=db)

    assert _alertRows(db) == []


def test_batteryNewEpisode_afterAnEnd_reactivatesTheSameIdWithANewFirstSeen() -> None:
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(11.5, "2026-10-20T15:12:00Z"))
    _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:02Z", band="green"))
    _stepBattery(arbiter, _batt(13.8, "2026-10-20T15:12:12Z", band="green"))

    state = _stepBattery(arbiter, _batt(15.2, "2026-10-20T15:20:00Z"))

    assert [e["id"] for e in state["entries"]] == [_BATTERY_ID]
    entry = _batteryEntry(state)
    assert entry["active"] is True
    assert entry["firstSeenTs"] == "2026-10-20T15:20:00Z"
    assert entry["title"] == _HIGH_TITLE


def test_seed_batteryEntrySurvivesARestart_activeIsStale(tmp_path: Path) -> None:
    first = _arbiter()
    _writeAlerts(tmp_path, _stepBattery(first, _batt(15.04, "2026-10-20T15:12:00Z")))

    restarted = aa.AlertsArbiter(
        {}, driveIdProvider=_DriveIds(), seedEntries=aa.readAlertsSeed(str(tmp_path))
    )
    entry = _batteryEntry(_build(restarted, None))

    assert entry is not None
    assert entry["active"] is True
    assert entry["stale"] is True
    assert entry["title"] == _HIGH_TITLE
    assert entry["last"]["value"] == 15.1
    assert entry["firstSeenTs"] == "2026-10-20T15:12:00Z"


# ---------------------------------------------------------------- over-rev
#
# US-897-b4: the peak is fed per READING (observeRpmReading, the seam), the
# end is decided on the tick (observe).

_RPM_ID = "engine:RPM:watch"


def _at(second: float) -> datetime:
    return datetime(2026, 10, 20, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=second)


def _rpmLive(value: float | None, second: int, band: str | None = "green") -> dict[str, Any]:
    """An obd-live payload whose RPM is a fresh reading (band None -> unbanded)."""
    obdLive = _obdLive(None)
    obdLive["params"]["RPM"] = {
        "value": value,
        "unit": "rpm",
        "ts": f"2026-10-20T15:12:{second:02d}Z",
        "stale": False,
        "band": None if band is None else _band(band),
        "last": None,
    }
    return obdLive


def _rpmTick(
    arbiter: aa.AlertsArbiter,
    obdLive: dict[str, Any] | None,
    *,
    recording: bool = False,
    ended: bool = False,
) -> dict[str, Any] | None:
    arbiter.observe(
        obdLive, dataSource="real", database=None, driveRecording=recording, driveEnded=ended
    )
    state = _build(arbiter, obdLive)
    return next((e for e in state["entries"] if e["id"] == _RPM_ID), None)


def test_overRev_peakFromEveryReadingBetweenSnapshots_sampledSentence_valueUnitNull() -> None:
    """VC1: 6900, 7150.75, 7020 (all red) between two ticks -> 'peak 7,150 rpm
    (sampled)' -- the 7150.75 the snapshot never shows is the peak."""
    arbiter = _arbiter()
    for second, rpm in ((1, 6900), (3, 7150.75), (5, 7020)):
        arbiter.observeRpmReading(rpm, _at(second), _band("red"))

    entry = _rpmTick(arbiter, _rpmLive(7020, 5, band="red"), recording=True)

    assert entry is not None
    assert set(entry) == _ENTRY_KEYS
    assert entry["source"] == "engine"
    assert entry["key"] == "RPM"
    assert entry["tier"] == "watch"
    assert entry["title"] == "OVER-REV"
    assert entry["sentence"] == "peak 7,150 rpm (sampled)"
    assert entry["value"] is None
    assert entry["unit"] is None
    assert entry["directive"] is None
    assert entry["active"] is True
    assert entry["firstSeenTs"] == "2026-10-20T15:12:01Z"
    assert entry["lastSeenTs"] == "2026-10-20T15:12:05Z"


@pytest.mark.parametrize(
    ("peak", "sentence"),
    [(7000, "peak 7,000 rpm (sampled)"), (7999.99, "peak 7,999 rpm (sampled)"),
     (12345.5, "peak 12,345 rpm (sampled)"), (950.9, "peak 950 rpm (sampled)")],
)
def test_overRev_sentence_floorAndThousandsSeparator(peak: float, sentence: str) -> None:
    """Spool 2026-10-19: n = floor(peak), ',' thousands, '(sampled)' always."""
    arbiter = _arbiter()
    arbiter.observeRpmReading(peak, _at(1), _band("red"))

    entry = _rpmTick(arbiter, None)

    assert entry is not None
    assert entry["sentence"] == sentence
    assert entry["sentence"].endswith("(sampled)")


def test_overRev_nonRedReadings_neverRaiseThePeakOrOpenAnEpisode() -> None:
    """The band producer is the judge: amber/green readings do not count."""
    arbiter = _arbiter()
    arbiter.observeRpmReading(6500, _at(0), _band("amber"))
    assert _rpmTick(arbiter, None) is None

    arbiter.observeRpmReading(7100, _at(1), _band("red"))
    arbiter.observeRpmReading(9000, _at(2), _band("amber"))

    assert _rpmTick(arbiter, None)["sentence"] == "peak 7,100 rpm (sampled)"


def test_overRev_iconWatchPulsing_noTakeover() -> None:
    arbiter = _arbiter()
    arbiter.observeRpmReading(7100, _at(1), _band("red"))
    arbiter.observe(None, dataSource="real", database=None, driveRecording=True)

    state = _build(arbiter, None)

    assert state["icon"] == {"state": "watch", "count": 1, "pulse": True}
    assert state["takeover"] is None


def test_overRev_endsAtDriveEnd_staysListedInactive() -> None:
    """VC2: drive ends -> active false, still listed (Q15)."""
    arbiter = _arbiter()
    arbiter.observeRpmReading(7150, _at(1), _band("red"))
    assert _rpmTick(arbiter, _rpmLive(7150, 1, band="red"), recording=True)["active"] is True

    entry = _rpmTick(arbiter, None, recording=False, ended=True)

    assert entry is not None
    assert entry["active"] is False
    assert entry["sentence"] == "peak 7,150 rpm (sampled)"
    assert entry["value"] is None
    assert _build(arbiter, None)["icon"]["count"] == 0


def test_overRev_whileRecording_greenNeverEndsIt() -> None:
    arbiter = _arbiter()
    arbiter.observeRpmReading(7150, _at(0), _band("red"))
    for second in range(2, 40, 2):
        arbiter.observeRpmReading(3000, _at(second), _band("green"))

    entry = _rpmTick(arbiter, _rpmLive(3000, 38), recording=True)

    assert entry is not None and entry["active"] is True


def test_overRev_noDriveRecording_green9sKeeps_green10sEnds_byReadingTime() -> None:
    """Atlas Q13: with no drive recording it ends after the band has been green
    for pi.warnings.rpm.clearGreenHoldSec (10 s) by the READINGS' time."""
    arbiter = _arbiter()
    arbiter.observeRpmReading(7150, _at(0), _band("red"))
    arbiter.observeRpmReading(3000, _at(2), _band("green"))
    arbiter.observeRpmReading(3000, _at(11), _band("green"))
    assert _rpmTick(arbiter, _rpmLive(3000, 11))["active"] is True

    arbiter.observeRpmReading(3000, _at(12), _band("green"))
    entry = _rpmTick(arbiter, _rpmLive(3000, 12))

    assert entry is not None and entry["active"] is False


def test_overRev_greenHold_brokenByAmberOrNull_restarts() -> None:
    arbiter = _arbiter()
    arbiter.observeRpmReading(7150, _at(0), _band("red"))
    arbiter.observeRpmReading(3000, _at(2), _band("green"))
    arbiter.observeRpmReading(6000, _at(5), _band("amber"))
    arbiter.observeRpmReading(3000, _at(6), _band("green"))
    arbiter.observeRpmReading(None, _at(8), None)
    arbiter.observeRpmReading(3000, _at(9), _band("green"))
    arbiter.observeRpmReading(3000, _at(15), _band("green"))

    assert _rpmTick(arbiter, _rpmLive(3000, 15))["active"] is True


def test_overRev_greenHold_staleTickNeverEndsIt() -> None:
    """Stale never clears: the tick must see a FRESH green RPM to end it."""
    arbiter = _arbiter()
    arbiter.observeRpmReading(7150, _at(0), _band("red"))
    arbiter.observeRpmReading(3000, _at(2), _band("green"))
    arbiter.observeRpmReading(3000, _at(14), _band("green"))
    stale = _obdLive(None)
    stale["params"]["RPM"] = {
        "value": None, "unit": "rpm", "ts": "2026-10-20T15:12:14Z", "stale": True,
        "band": None, "noBandReason": "stale", "last": {"value": 3000, "band": _band("green")},
    }

    assert _rpmTick(arbiter, stale)["active"] is True
    assert _rpmTick(arbiter, None)["active"] is True


def test_overRev_clearGreenHoldSec_comesFromItsOwnKey() -> None:
    config = {"pi": {"warnings": {"rpm": {"clearGreenHoldSec": 3},
                                  "battery": {"clearGreenHoldSec": 60}}}}
    arbiter = _arbiter(config)
    arbiter.observeRpmReading(7150, _at(0), _band("red"))
    arbiter.observeRpmReading(3000, _at(2), _band("green"))
    arbiter.observeRpmReading(3000, _at(5), _band("green"))

    assert _rpmTick(arbiter, _rpmLive(3000, 5))["active"] is False


def test_overRev_newDrive_resetsThePeak_newEpisodeNewFirstSeen() -> None:
    arbiter = _arbiter()
    arbiter.observeRpmReading(7400, _at(1), _band("red"))
    _rpmTick(arbiter, None, recording=True)
    _rpmTick(arbiter, None, recording=False, ended=True)

    arbiter.resetRpmPeak()
    arbiter.observeRpmReading(7050, _at(30), _band("red"))
    entry = _rpmTick(arbiter, None, recording=True)

    assert entry is not None
    assert entry["active"] is True
    assert entry["sentence"] == "peak 7,050 rpm (sampled)"
    assert entry["firstSeenTs"] == "2026-10-20T15:12:30Z"


def test_overRev_resetWhileActive_peakRestartsFromTheNextRedReading() -> None:
    arbiter = _arbiter()
    arbiter.observeRpmReading(7400, _at(1), _band("red"))

    arbiter.resetRpmPeak()
    arbiter.observeRpmReading(7050, _at(3), _band("red"))

    assert _rpmTick(arbiter, None, recording=True)["sentence"] == "peak 7,050 rpm (sampled)"


def test_overRev_tierComesFromConfig() -> None:
    from common.config.validator import DEFAULTS

    assert DEFAULTS["pi.warnings.engine.RPM.redTier"] == "watch"
    arbiter = _arbiter()
    arbiter.observeRpmReading(7100, _at(1), _band("red"))
    assert _rpmTick(arbiter, None)["tier"] == "watch"


def test_overRev_writesNoAlertLogRow(db: Any) -> None:
    arbiter = _arbiter()
    arbiter.observeRpmReading(7100, _at(1), _band("red"))
    arbiter.observe(None, dataSource="real", database=db, driveEnded=True)

    assert _alertRows(db) == []


@pytest.mark.parametrize("active", [True, False])
def test_seed_overRevAndItsPeakSurviveARestart(tmp_path: Path, active: bool) -> None:
    """G3: the RPM episode and its peak are seeded from tmpfs states/alerts."""
    first = _arbiter()
    first.observeRpmReading(7150.75, _at(1), _band("red"))
    if not active:
        first.observe(None, dataSource="real", database=None, driveEnded=True)
    _writeAlerts(tmp_path, _build(first, None))

    restarted = aa.AlertsArbiter(
        {}, driveIdProvider=_DriveIds(), seedEntries=aa.readAlertsSeed(str(tmp_path))
    )
    entry = next(e for e in _build(restarted, None)["entries"] if e["id"] == _RPM_ID)

    assert entry["active"] is active
    assert entry["sentence"] == "peak 7,150 rpm (sampled)"
    assert entry["firstSeenTs"] == "2026-10-20T15:12:01Z"
    assert entry["value"] is None and entry["unit"] is None
    # An active seeded peak still counts: a lower red reading keeps it; after a
    # cleared one, the same reading opens a new episode with its own peak.
    restarted.observeRpmReading(7020, _at(40), _band("red"))
    expected = "peak 7,150 rpm (sampled)" if active else "peak 7,020 rpm (sampled)"
    assert _rpmTick(restarted, None, recording=True)["sentence"] == expected


# ----------------------------------------------------------------- emitter


def test_makeAlertsEmitter_writesTheStateFile_andReturnsIt(tmp_path: Path) -> None:
    statesDir = str(tmp_path / "states")
    emit = aa.makeAlertsEmitter(statesDir)
    arbiter = _arbiter()
    obdLive = _obdLive(_fresh(112, "2026-10-20T15:12:27Z"))
    arbiter.observe(obdLive, dataSource="real", database=None)

    returned = emit(
        arbiter.episodes(), obdLive, nowUtc=_NOW, dataSource="real", bootId="b7"
    )

    with open(os.path.join(statesDir, "alerts"), encoding="utf-8") as fh:
        written = json.load(fh)
    assert returned == written
    assert written["takeover"]["directive"] == "PULL OVER"


def test_makeAlertsEmitter_neverRaisesOnAWriteFailure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pi.splash.boot_state_emitter as bse

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("tmpfs full")

    monkeypatch.setattr(bse, "writeStateAtomic", boom)
    emit = aa.makeAlertsEmitter(str(tmp_path / "states"))

    assert emit([], None, nowUtc=_NOW, dataSource=None, bootId="b7") is None


# -------------------------------------------------------------- codes (b5)
#
# US-897-b5: the arbiter's CODE source is the dtc payload handed in-process.
# The payloads are built by the REAL buildDtcState over the SHIPPED severity
# table, so the words are Spool's rows, not test literals.

_T0 = "2026-10-20T14:55:00Z"
_T1 = "2026-10-20T15:02:11Z"
_T2 = "2026-10-20T15:09:40Z"
_UNRATED_SENTENCE = "Severity unknown. Get it diagnosed."


def _shippedTable() -> dict[str, dict]:
    from pi.obdii.orchestrator.card_state_emitter import _DEFAULT_SEVERITY_TABLE_PATH
    from pi.splash.dtc_severity_table import loadP1xxxSeverityTable

    return loadP1xxxSeverityTable(_DEFAULT_SEVERITY_TABLE_PATH)


def _dtcPayload(
    codes: list[tuple[str, str]] | None,
    checkedAtTs: str | None,
    *,
    table: dict[str, dict] | None = None,
    firstSeen: dict[str, str] | None = None,
) -> dict[str, Any]:
    """A states/dtc payload as the router publishes it; codes None = unavailable."""
    from pi.splash.dtc_emitter import buildDtcState

    raw = [
        {"code": code, "status": status, "description": "", "driveId": None,
         "setAtTs": None, "logged": True, "syncAcked": False}
        for code, status in (codes or [])
    ]
    return buildDtcState(
        codes=raw,
        severityTable=_shippedTable() if table is None else table,
        mil=any(status == "stored" for _, status in (codes or [])),
        newSinceTs=None,
        sessionResetLock=[],
        nowIso=checkedAtTs or _T0,
        dtcAvailable=codes is not None,
        checkedAtTs=checkedAtTs,
        firstSeenByCode=firstSeen,
    )


def _row(severity: str, title: str | None, sentence: str | None) -> dict[str, Any]:
    """A hand-made severity-table row (the loader's enrichment shape)."""
    return {
        "severity": severity, "severityCaveat": None, "short": "", "long": "",
        "suggestedFix": None, "fixProvenance": "none", "clearEligible": False,
        "title": title, "sentence": sentence,
    }


def test_codes_theCarsTwoCodes_watchThenMinor_codeAlert_sourcesAssessed() -> None:
    """VC1: P0400 (watch) + P0443 (minor) at T -> two entries, codeAlert, assessed."""
    arbiter = _arbiter()
    arbiter.observeDtc(
        _dtcPayload(
            [("P0443", "stored"), ("P0400", "stored")],
            _T1,
            firstSeen={"P0400": "2026-10-01T12:00:00Z", "P0443": "2026-09-02T09:00:00Z"},
        )
    )

    state = _build(arbiter, None)

    entries = state["entries"]
    assert [e["id"] for e in entries] == ["code:P0400:watch", "code:P0443:minor"]
    egr, purge = entries
    assert set(egr) == _ENTRY_KEYS
    assert egr["source"] == "code"
    assert egr["key"] == "P0400"
    assert egr["tier"] == "watch"
    assert egr["title"] == "EGR FLOW (P0400)"
    assert egr["sentence"] == "Drive gently. Get it diagnosed."
    assert egr["codeStatus"] == "stored"
    assert egr["value"] is None and egr["unit"] is None
    assert egr["directive"] is None
    assert egr["firstSeenTs"] == "2026-10-01T12:00:00Z"
    assert egr["lastSeenTs"] == _T1
    assert egr["active"] is True and egr["stale"] is False and egr["last"] is None
    assert purge["title"] == "EVAP PURGE (P0443)"
    assert purge["sentence"] == "Emissions only. Safe to drive."
    assert purge["firstSeenTs"] == "2026-09-02T09:00:00Z"
    assert state["codeAlert"] == {
        "ids": ["code:P0400:watch", "code:P0443:minor"],
        "tier": "watch",
        "dismissable": True,
    }
    assert state["sources"]["code"] == {"assessed": True, "checkedAtTs": _T1}
    assert state["codesCheckedThisSession"] is True
    assert state["checkedAtTs"] == _T1
    # Codes count but never pulse; no code ever takes over.
    assert state["icon"] == {"state": "watch", "count": 2, "pulse": False}
    assert state["takeover"] is None


def test_codes_orderedAfterAnyEngineEntryOfTheSameTier() -> None:
    """Q16: live (engine) before stored (code) inside a tier."""
    arbiter = _arbiter()
    _stepBattery(arbiter, _batt(11.2, "2026-10-20T15:12:27Z"))
    arbiter.observeDtc(_dtcPayload([("P0400", "stored"), ("P0443", "stored")], _T1))

    state = _build(arbiter, None)

    assert [e["id"] for e in state["entries"]] == [
        _BATTERY_ID,
        "code:P0400:watch",
        "code:P0443:minor",
    ]
    # codeAlert lists the CODE entries only, in entries order.
    assert state["codeAlert"]["ids"] == ["code:P0400:watch", "code:P0443:minor"]
    assert state["icon"]["pulse"] is True  # the engine WATCH pulses


def test_codes_untabled_isUnrated_withTheUnratedWords() -> None:
    """VC2: P0300 has no row -> code:P0300:unrated, title the bare code."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0300", "stored")], _T1))

    state = _build(arbiter, None)

    (entry,) = state["entries"]
    assert entry["id"] == "code:P0300:unrated"
    assert entry["tier"] == "unrated"
    assert entry["title"] == "P0300"
    assert entry["sentence"] == _UNRATED_SENTENCE
    assert state["codeAlert"] == {
        "ids": ["code:P0300:unrated"], "tier": "unrated", "dismissable": True,
    }


def test_codes_p0430_isUnrated_neverATier() -> None:
    """P0430 (bank 2, not this car) has no row: UNRATED, never a guessed tier."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0430", "stored")], _T1))

    (entry,) = _build(arbiter, None)["entries"]

    assert entry["id"] == "code:P0430:unrated"
    assert entry["title"] == "P0430"
    assert entry["sentence"] == _UNRATED_SENTENCE


def test_codes_naCodeIsExcluded() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(
        _dtcPayload([("P0705", "stored")], _T1, table={"P0705": _row("na", None, None)})
    )

    state = _build(arbiter, None)

    assert state["entries"] == []
    assert state["codeAlert"] is None
    assert state["sources"]["code"]["assessed"] is True
    assert state["icon"]["state"] == "none"


def test_codes_minorOnly_iconWatch_noPulse() -> None:
    """G7: a minor-only list is counted amber, never grey and never pulsing."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0443", "stored")], _T1))

    state = _build(arbiter, None)

    assert state["icon"] == {"state": "watch", "count": 1, "pulse": False}
    assert state["codeAlert"]["tier"] == "minor"


def test_codes_unratedOnly_iconWatch() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0300", "stored")], _T1))

    assert _build(arbiter, None)["icon"] == {"state": "watch", "count": 1, "pulse": False}


def test_codes_unread_noActiveStopOrWatch_iconNotChecked() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload(None, None))

    state = _build(arbiter, None)

    assert state["icon"]["state"] == "not_checked"
    assert state["sources"]["code"] == {"assessed": False, "checkedAtTs": None}
    assert state["codesCheckedThisSession"] is False
    assert state["codeAlert"] is None


def test_codes_readWithNoCodes_iconNone_assessed() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([], _T1))

    state = _build(arbiter, None)

    assert state["icon"] == {"state": "none", "count": 0, "pulse": False}
    assert state["sources"]["code"] == {"assessed": True, "checkedAtTs": _T1}


def test_codes_null_keepsPriorCodeEntries_assessedFalse() -> None:
    """VC3: codes null (read unavailable) creates and removes nothing."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored"), ("P0443", "stored")], _T1))
    before = _build(arbiter, None)

    arbiter.observeDtc(_dtcPayload(None, _T1))
    after = _build(arbiter, None)

    assert after["entries"] == before["entries"]
    assert after["codeAlert"] == before["codeAlert"]
    assert after["sources"]["code"] == {"assessed": False, "checkedAtTs": _T1}
    assert after["codesCheckedThisSession"] is False


def test_codes_atBoot_lastKnownMakesNoEntries_assessedFalse() -> None:
    """Before the first successful read, remembered codes are not present."""
    from pi.splash.dtc_emitter import buildDtcState

    payload = buildDtcState(
        codes=[],
        severityTable=_shippedTable(),
        mil=False,
        newSinceTs=None,
        sessionResetLock=None,
        nowIso=_T0,
        dtcAvailable=False,
        lastKnown={
            "codes": [{"code": "P0400", "status": "stored", "description": "",
                       "driveId": 33, "lastSeenTs": _T0}],
            "asOfTs": _T0,
            "source": "dtc_log",
        },
    )
    assert payload["lastKnown"] is not None  # the block IS there to ignore
    arbiter = _arbiter()

    arbiter.observeDtc(payload)
    state = _build(arbiter, None)

    assert state["entries"] == []
    assert state["sources"]["code"]["assessed"] is False
    assert state["icon"]["state"] == "not_checked"


def test_codes_absentFromANewerRead_isRemoved_notKeptInactive() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored"), ("P0443", "stored")], _T1))

    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T2))
    state = _build(arbiter, None)

    assert [e["id"] for e in state["entries"]] == ["code:P0400:watch"]
    assert state["entries"][0]["lastSeenTs"] == _T2
    assert state["codeAlert"]["ids"] == ["code:P0400:watch"]


def test_codes_allGoneOnANewerRead_codeAlertNull() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T1))

    arbiter.observeDtc(_dtcPayload([], _T2))
    state = _build(arbiter, None)

    assert state["entries"] == []
    assert state["codeAlert"] is None
    assert state["icon"]["state"] == "none"


def test_codes_sameCheckedAtTs_fewerCodes_removesNothing() -> None:
    """VC4 / G1: an unchanged checkedAtTs never removes an entry."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored"), ("P0443", "stored")], _T1))

    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T1))
    state = _build(arbiter, None)

    assert [e["id"] for e in state["entries"]] == ["code:P0400:watch", "code:P0443:minor"]


def test_codes_olderCheckedAtTs_changesNothing() -> None:
    """G1: a payload older than the last one applied is stale news."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored"), ("P0443", "stored")], _T2))
    before = _build(arbiter, None)

    arbiter.observeDtc(_dtcPayload([("P0300", "stored")], _T1))
    after = _build(arbiter, None)

    assert after["entries"] == before["entries"]
    assert after["sources"]["code"] == {"assessed": True, "checkedAtTs": _T2}


def test_codes_pending_isLabelled_atItsTableTier() -> None:
    """Spool 2026-10-19: a pending code shows at tier, its title ' · pending'."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "pending")], _T1))

    (entry,) = _build(arbiter, None)["entries"]

    assert entry["id"] == "code:P0400:watch"
    assert entry["codeStatus"] == "pending"
    assert entry["title"] == "EGR FLOW (P0400) · pending"
    assert entry["sentence"] == "Drive gently. Get it diagnosed."


def test_codes_pendingThatStores_staysOneEntry_statusFlips() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "pending")], _T1, firstSeen={"P0400": _T0}))

    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T2, firstSeen={"P0400": _T0}))
    entries = _build(arbiter, None)["entries"]

    assert len(entries) == 1
    assert entries[0]["id"] == "code:P0400:watch"
    assert entries[0]["codeStatus"] == "stored"
    assert entries[0]["title"] == "EGR FLOW (P0400)"
    assert entries[0]["firstSeenTs"] == _T0


def test_codes_sameCodeStoredAndPending_inOneRead_isOneStoredEntry() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "pending"), ("P0400", "stored")], _T1))

    entries = _build(arbiter, None)["entries"]

    assert [(e["id"], e["codeStatus"]) for e in entries] == [("code:P0400:watch", "stored")]


_STOP_SENTENCE = "Reduce load. Get it diagnosed now."


def _stopTable() -> dict[str, dict]:
    """A hypothetical stop-tier row (no shipped row is stop today, Spool)."""
    return {"P1999": _row("stop", "TEST STOP (P1999)", _STOP_SENTENCE)}


def test_codes_stopTierRow_publishedAsWatch_keepsTheTablesSentence() -> None:
    """Spool s4 / R31: a code is NEVER stop and never takes over."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P1999", "stored")], _T1, table=_stopTable()))

    state = _build(arbiter, None)

    (entry,) = state["entries"]
    assert entry["id"] == "code:P1999:watch"
    assert entry["tier"] == "watch"
    assert entry["title"] == "TEST STOP (P1999)"
    assert entry["sentence"] == _STOP_SENTENCE
    assert state["takeover"] is None
    assert state["icon"]["state"] == "watch"


def test_codes_stopTierRow_theClearGateStillReadsTheTableTier_refuses() -> None:
    """Spool 2026-10-19 (a): the gate reads the dtc payload's TABLE tier."""
    payload = _dtcPayload([("P1999", "stored")], _T1, table=_stopTable())
    arbiter = _arbiter()

    arbiter.observeDtc(payload)

    assert payload["codes"][0]["severity"] == "stop"  # the payload is untouched
    assert payload["clearGate"] == {"enabled": False, "reason": "severity_present"}
    assert _build(arbiter, None)["entries"][0]["tier"] == "watch"


def test_codes_p1xxxStopTierCaveat_neverYieldsTierStop() -> None:
    """P1103 is 'WATCH -> red if overboost': the caveat never upgrades the tier."""
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P1103", "stored")], _T1))

    state = _build(arbiter, None)

    (entry,) = state["entries"]
    assert entry["id"] == "code:P1103:watch"
    assert entry["title"] == "WASTEGATE (P1103)"
    assert state["takeover"] is None


def test_codes_unparseablePayload_isIgnored() -> None:
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T1))

    for junk in (None, [], "dtc"):
        arbiter.observeDtc(junk)  # type: ignore[arg-type]

    state = _build(arbiter, None)
    assert [e["id"] for e in state["entries"]] == ["code:P0400:watch"]
    assert state["sources"]["code"] == {"assessed": True, "checkedAtTs": _T1}


def test_codes_engineEntriesUnaffectedByACodeRead() -> None:
    arbiter = _arbiter()
    _step(arbiter, _fresh(112, "2026-10-20T15:12:27Z"))

    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T1))
    state = _build(arbiter, _obdLive(_fresh(112, "2026-10-20T15:12:29Z")))

    assert [e["id"] for e in state["entries"]] == [_STOP_ID, "code:P0400:watch"]
    assert state["takeover"]["id"] == _STOP_ID
    assert state["icon"]["state"] == "stop"


def test_engineEntries_carryCodeStatusNull() -> None:
    state = _step(_arbiter(), _fresh(112, "2026-10-20T15:12:27Z"))

    assert state["entries"][0]["codeStatus"] is None


def test_makeAlertsEmitter_carriesTheCodeSource(tmp_path: Path) -> None:
    emit = aa.makeAlertsEmitter(str(tmp_path / "states"))
    arbiter = _arbiter()
    arbiter.observeDtc(_dtcPayload([("P0400", "stored")], _T1))

    written = emit(
        arbiter.episodes(), None, nowUtc=_NOW, dataSource="real", bootId="b7",
        codeSource=arbiter.codeSource(),
    )

    assert written is not None
    assert written["sources"]["code"] == {"assessed": True, "checkedAtTs": _T1}
    assert written["codeAlert"]["ids"] == ["code:P0400:watch"]
