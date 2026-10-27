################################################################################
# File Name: test_boot_progress_prior_ids.py
# Purpose/Description: US-917-b / Atlas G3 ruling (a) -- arm() persists the
#                      prior trail's boot-id SET to data/boot_progress.prior.json
#                      BEFORE it truncates the trail, so a reader later in the
#                      boot (the system-status emitter) can still ask "is this
#                      record the prior boot's?" through the ONE matching rule,
#                      isPriorBootRecord.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-27    | Rex (US-917-b)| Initial -- pins (i)-(v) of the G3 ruling.
# ================================================================================
################################################################################
"""arm() keeps the prior boot ids beside the trail (Atlas G3 ruling (a))."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

import pytest

from src.pi.diagnostics import boot_progress
from src.pi.diagnostics.boot_progress import (
    DEFAULT_FILE_PATH,
    DEFAULT_PRIOR_FILE_PATH,
    arm,
    isPriorBootRecord,
    readPriorBootIds,
)
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG

_PRIOR_BOOT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_OLDER_BOOT = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_NEW_BOOT = "cccccccccccccccccccccccccccccccc"


def _writeTrail(path: Path, bootIds: list[str]) -> None:
    path.write_text(
        "".join(
            json.dumps({"boot_id": b, "stage": "RUNNING", "ts": "2026-10-27T00:00:00Z",
                        "vcell": None}) + "\n"
            for b in bootIds
        ),
        encoding="utf-8",
    )


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "obd.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_STARTUP_LOG)
    conn.close()
    return db


def _arm(tmp_path: Path, trail: Path) -> None:
    arm(filePath=str(trail), dbPath=str(_db(tmp_path)), bootId=_NEW_BOOT,
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=False,
        clockQualityProvider=lambda _ts: "ok")


def _writePrior(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_defaultPriorFilePath_sitsBesideTheTrail():
    assert DEFAULT_PRIOR_FILE_PATH == DEFAULT_FILE_PATH + ".prior.json"


# --- (i) written before the truncate, holding the prior ids ----------------


def test_arm_writesThePriorIdsFileBeforeTheTruncate(tmp_path, monkeypatch):
    """
    Given: a prior trail naming two boots
    When:  arm() runs
    Then:  boot_progress.prior.json lands (os.replace) BEFORE the trail's own
           replace (the truncate), holding the sorted prior SET and THIS boot id
    """
    trail = tmp_path / "boot_progress"
    priorFile = Path(str(trail) + ".prior.json")
    _writeTrail(trail, [_PRIOR_BOOT, _OLDER_BOOT, _PRIOR_BOOT])
    replaced: list[tuple[str, str]] = []
    realReplace = os.replace

    def spyReplace(src, dst):
        if os.path.abspath(dst) == os.path.abspath(str(trail)):
            # The truncate: the prior-ids file must already be on disk.
            replaced.append(("trail", Path(priorFile).read_text(encoding="utf-8")))
        else:
            replaced.append(("other", str(dst)))
        realReplace(src, dst)

    monkeypatch.setattr(boot_progress.os, "replace", spyReplace)

    _arm(tmp_path, trail)

    assert [tag for tag, _ in replaced] == ["other", "trail"]
    assert os.path.abspath(replaced[0][1]) == os.path.abspath(str(priorFile))
    record = json.loads(replaced[1][1])
    assert record["schema"] == 1
    assert record["boot_id"] == _NEW_BOOT
    assert record["prior_boot_ids"] == sorted([_PRIOR_BOOT, _OLDER_BOOT])
    assert isinstance(record["written_at"], str) and record["written_at"].endswith("Z")


def test_arm_emptyPriorTrail_writesAnEmptySet(tmp_path):
    trail = tmp_path / "boot_progress"

    _arm(tmp_path, trail)

    record = json.loads(Path(str(trail) + ".prior.json").read_text(encoding="utf-8"))
    assert record["prior_boot_ids"] == []
    assert record["boot_id"] == _NEW_BOOT


# --- (ii) the re-arm still happens when the write raises -------------------


def test_arm_priorIdsWriteRaises_logsErrorAndStillReArms(tmp_path, monkeypatch, caplog):
    trail = tmp_path / "boot_progress"
    _writeTrail(trail, [_PRIOR_BOOT])

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(boot_progress, "_writePriorBootIds", boom)

    with caplog.at_level(logging.ERROR, logger=boot_progress.logger.name):
        _arm(tmp_path, trail)

    lines = trail.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rearmed = json.loads(lines[0])
    assert rearmed["stage"] == "RUNNING"
    assert rearmed["boot_id"] == _NEW_BOOT
    assert any("prior boot ids" in r.getMessage() and r.levelno == logging.ERROR
               for r in caplog.records)


# --- (iii)/(iv) no proof -> None ------------------------------------------


def test_readPriorBootIds_staleBootId_isNone(tmp_path, caplog):
    path = tmp_path / "boot_progress.prior.json"
    _writePrior(path, {"schema": 1, "boot_id": _OLDER_BOOT,
                       "prior_boot_ids": [_PRIOR_BOOT], "written_at": "x"})

    with caplog.at_level(logging.WARNING, logger=boot_progress.logger.name):
        assert readPriorBootIds(_NEW_BOOT, str(path)) is None
    assert any("not this boot" in r.getMessage() for r in caplog.records)


def test_readPriorBootIds_missingFile_isNone(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=boot_progress.logger.name):
        assert readPriorBootIds(_NEW_BOOT, str(tmp_path / "absent.json")) is None
    assert any("missing" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("payload", [
    {"schema": 1, "boot_id": _NEW_BOOT, "prior_boot_ids": [], "written_at": "x"},
    {"schema": 1, "boot_id": _NEW_BOOT, "prior_boot_ids": _PRIOR_BOOT, "written_at": "x"},
    {"schema": 1, "boot_id": _NEW_BOOT, "written_at": "x"},
    [_PRIOR_BOOT],
])
def test_readPriorBootIds_emptyOrMalformedSet_isNone(tmp_path, payload):
    path = tmp_path / "boot_progress.prior.json"
    _writePrior(path, payload)

    assert readPriorBootIds(_NEW_BOOT, str(path)) is None


def test_readPriorBootIds_unreadableJson_isNone(tmp_path):
    path = tmp_path / "boot_progress.prior.json"
    path.write_text("{torn", encoding="utf-8")

    assert readPriorBootIds(_NEW_BOOT, str(path)) is None


def test_readPriorBootIds_unknownCurrentBoot_isNone(tmp_path):
    """readBootId()'s failure value proves nothing, even against itself."""
    path = tmp_path / "boot_progress.prior.json"
    _writePrior(path, {"schema": 1, "boot_id": "unknown",
                       "prior_boot_ids": [_PRIOR_BOOT], "written_at": "x"})

    assert readPriorBootIds("unknown", str(path)) is None


# --- (v) valid set: match -> True, no match -> False ------------------------


def test_armThenRead_roundTrip_matchesThePriorBootOnly(tmp_path):
    trail = tmp_path / "boot_progress"
    _writeTrail(trail, [_PRIOR_BOOT])
    _arm(tmp_path, trail)

    ids = readPriorBootIds(_NEW_BOOT, str(trail) + ".prior.json")

    assert ids == {_PRIOR_BOOT}
    assert isPriorBootRecord(_PRIOR_BOOT, ids) is True
    assert isPriorBootRecord(_OLDER_BOOT, ids) is False


@pytest.mark.parametrize("recordBootId", [None, "", "  ", "unknown", 42])
def test_isPriorBootRecord_neverMatchesAnAbsentOrUnknownId(recordBootId):
    assert isPriorBootRecord(recordBootId, {_PRIOR_BOOT, "unknown"}) is False
