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
# ================================================================================
################################################################################

"""Tests for ``pi.obdii.alerts_arbiter`` (US-897-b2)."""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from datetime import UTC, datetime
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
    # sources.code is unassessed until US-897-b5.
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
