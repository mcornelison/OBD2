################################################################################
# File Name: test_imu_rate_triple.py
# Purpose/Description: US-796-b -- the IMU rate triple is sampleHz 4 /
#     persistHz 2 / stateHz 1 (CIO ruling 2026-09-21). Pins the shipped
#     values, the EXACT decimation factors, that no row is dropped or
#     double-counted on either consumer path, and that a consumer rate above
#     its source is WARNED (both values named, effective rate stated) rather
#     than silently clamped.
# Author: Rex (US-796-b)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-796-b: the IMU triple 4 / 2 / 1, every factor exact, no silent clamp."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from common.config.validator import ConfigValidator
from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber, _decimationFactor
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase
from pi.sensors.imu_state_bridge import ImuStateBridge

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VALIDATOR_LOGGER = "common.config.validator"

# The ruled triple (CIO 2026-09-21). Exact values, not bounds.
_SAMPLE_HZ = 4
_PERSIST_HZ = 2
_STATE_HZ = 1


def _imu(field: str, value, seq: int, *, capture: float) -> Sample:
    """One raw.imu.<field> sample under a burst's shared seq."""
    return Sample(
        topic=f"raw.imu.{field}",
        source="imu",
        value=value,
        unit="x",
        tsUtc="2026-09-21T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _shippedImu() -> dict:
    with open(_REPO_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)["pi"]["sensors"]["imu"]


def _baseCfg(imu: dict) -> dict:
    return {"protocolVersion": "1", "schemaVersion": "1", "deviceId": "d",
            "pi": {"sensors": {"imu": imu}}, "server": {}}


# ---------------------------------------------------------------------------
# The shipped triple
# ---------------------------------------------------------------------------

def test_configJson_imuTriple_isExactlyFourTwoOne():
    """
    Given: the shipped config.json
    When: the three pi.sensors.imu rates are read
    Then: they are exactly 4 / 2 / 1 -- not a range, not 'at most'
    """
    imu = _shippedImu()
    assert (imu["sampleHz"], imu["persistHz"], imu["stateHz"]) == (4, 2, 1)


def test_validator_acceptsTheShippedTriple_withoutARateWarning(caplog):
    """
    Given: the shipped 4 / 2 / 1 triple
    When: the validator runs
    Then: it is preserved as written and no rate warning is logged
    """
    imu = _shippedImu()
    triple = {"sampleHz": imu["sampleHz"], "persistHz": imu["persistHz"],
              "stateHz": imu["stateHz"]}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        result = ConfigValidator().validate(_baseCfg(dict(triple)))
    got = result["pi"]["sensors"]["imu"]
    assert {k: got[k] for k in triple} == triple
    assert not [r for r in caplog.records if "pi.sensors.imu" in r.getMessage()]


# ---------------------------------------------------------------------------
# Exact factors
# ---------------------------------------------------------------------------

def test_decimationFactor_persistPath_isExactlyTwo():
    """sampleHz 4 / persistHz 2 -> keep 1 of every 2 bursts to the DB."""
    assert _decimationFactor(_SAMPLE_HZ, _PERSIST_HZ) == 2
    assert _SAMPLE_HZ / _decimationFactor(_SAMPLE_HZ, _PERSIST_HZ) == _PERSIST_HZ


def test_decimationFactor_displayRatio_isExactlyFour():
    """sampleHz 4 / stateHz 1 -> 1 of every 4 bursts reaches the display."""
    assert _decimationFactor(_SAMPLE_HZ, _STATE_HZ) == 4
    assert _SAMPLE_HZ / _decimationFactor(_SAMPLE_HZ, _STATE_HZ) == _STATE_HZ


# ---------------------------------------------------------------------------
# No row dropped or double-counted
# ---------------------------------------------------------------------------

def test_persistPath_atFourTwo_keepsExactlyOneOfEveryTwoBursts(tmp_path: Path):
    """
    Given: the EDR subscriber at sampleHz 4 / persistHz 2
    When: 8 full bursts (2 s of sampling) are fed
    Then: exactly the 4 even-seq bursts are persisted, one row each
    """
    db = ObdDatabase(str(tmp_path / "triple.db"), walMode=False)
    db.initialize()
    sub = EdrPersistenceSubscriber(
        None, db, imuSampleHz=_SAMPLE_HZ, imuPersistHz=_PERSIST_HZ
    )
    for seq in range(1, 9):
        capture = seq / _SAMPLE_HZ
        for field, value in (("accel", (0.0, 0.0, 9.8)), ("gyro", (0.0, 0.0, 0.0)),
                             ("mag", (1.0, 2.0, 3.0)), ("temp", 25.0)):
            sub.handleSample(_imu(field, value, seq, capture=capture))
    sub.flushPending()
    with db.connect() as conn:
        seqs = [r[0] for r in conn.execute("SELECT seq FROM edr_imu_sample ORDER BY seq")]
    assert seqs == [2, 4, 6, 8]


def test_displayPath_atFourOne_writesExactlyOneOfEveryFourBursts(tmp_path: Path):
    """
    Given: the state bridge at sampleHz 4 / stateHz 1
    When: 8 accel bursts arrive 0.25 s apart (2 s of sampling)
    Then: exactly 2 state writes -- bursts 1 and 5, one per second
    """
    written: list[int] = []
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=_STATE_HZ, sampleHz=_SAMPLE_HZ)
    current = {"seq": 0}
    bridge._writeState = lambda payload: written.append(current["seq"])  # type: ignore[method-assign]
    for seq in range(1, 9):
        current["seq"] = seq
        bridge.handleSample(_imu("accel", (0.0, 0.0, 9.8), seq, capture=(seq - 1) / _SAMPLE_HZ))
    assert written == [1, 5]


# ---------------------------------------------------------------------------
# No silent clamp: a consumer rate above its source is WARNED
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["persistHz", "stateHz"])
def test_validator_consumerRateAboveSource_warnsNamingBothValues(caplog, key):
    """
    Given: a consumer rate (persistHz or stateHz) of 8 against sampleHz 4
    When: the validator runs
    Then: a WARNING names 8 and 4 and reports the effective rate (4 Hz); the
          config still loads (the path degrades to every burst, not a crash)
    """
    imu = {"sampleHz": 4, "persistHz": 2, "stateHz": 1, key: 8}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        ConfigValidator().validate(_baseCfg(imu))
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and f"pi.sensors.imu.{key}" in r.getMessage()]
    assert len(lines) == 1
    line = lines[0]
    assert f"pi.sensors.imu.{key} 8" in line
    assert "pi.sensors.imu.sampleHz 4" in line
    assert "effective rate 4 Hz" in line


def test_validator_inexactPersistRatio_warnsWithTheEffectiveRate(caplog):
    """
    Given: persistHz 3 against sampleHz 4 (factor rounds to 1)
    When: the validator runs
    Then: a WARNING names both values and the 4 Hz the DB actually receives --
          no config field that lies about its effective rate
    """
    imu = {"sampleHz": 4, "persistHz": 3, "stateHz": 1}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        ConfigValidator().validate(_baseCfg(imu))
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and "pi.sensors.imu.persistHz" in r.getMessage()]
    assert len(lines) == 1
    assert "pi.sensors.imu.persistHz 3" in lines[0]
    assert "pi.sensors.imu.sampleHz 4" in lines[0]
    assert "effective rate 4 Hz" in lines[0]
